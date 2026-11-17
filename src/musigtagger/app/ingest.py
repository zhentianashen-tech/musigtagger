"""Library ingestion: the scan trigger, provider execution, and suggestion events.

Boundary: the scanner turns files into :class:`TrackDescriptor`s (ingestion), the
provider turns a descriptor into :class:`TagSuggestion`s (the engine's job), and
this service persists both, emits the §4 suggestion events **outside** the pure
provider call, and skips-and-logs per-track failures instead of aborting a batch.

The scanner and provider are ports: configure them with ``--scanner module:attr``
and ``--provider module:attr``. The engine engineer's scanner/provider drop in
without an application change. A small mutagen-based scanner is bundled as a
stopgap so the app is runnable before that lands; it builds descriptors only and
contains no classification logic.
"""

from __future__ import annotations

import importlib
import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Protocol, Sequence, runtime_checkable

from ..contracts import SuggestionProvider, TagSuggestion, TrackDescriptor
from .config import AppConfig
from .events import EventLog, suggestion_event
from .store import LibraryStore
from .taxonomy_service import TaxonomyService
from .util import Clock, utc_now_iso


class IngestError(Exception):
    """A configured scanner or provider could not be loaded."""


@dataclass(frozen=True)
class ScanItem:
    """One scanner result: a descriptor, or a logged skip reason."""

    path: Path
    descriptor: TrackDescriptor | None = None
    error: str | None = None
    file_size_bytes: int | None = None
    mtime_ns: int | None = None


@dataclass(frozen=True)
class SkippedPath:
    path: str
    reason: str


@dataclass(frozen=True)
class ScanReport:
    run_id: str
    root: str
    indexed: int
    skipped: tuple[SkippedPath, ...] = ()
    suggestions_new: int = 0
    suggestions_duplicate: int = 0
    suggestions_unknown: int = 0
    providers: tuple[str, ...] = field(default_factory=tuple)

    @property
    def skipped_count(self) -> int:
        return len(self.skipped)


@runtime_checkable
class Scanner(Protocol):
    """Port: a local directory walk that yields descriptors (no writes)."""

    def scan(self, root: Path) -> Iterable[ScanItem]:
        ...


def load_object(spec: str, *, kind: str) -> Any:
    """Load ``module:attr`` (a class or callable) for the scanner/provider port."""
    if ":" not in spec:
        raise IngestError(
            f"{kind} spec {spec!r} must look like 'python.module:Attribute'"
        )
    module_name, attribute = spec.split(":", 1)
    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:
        raise IngestError(f"cannot import {module_name!r} for the {kind}: {exc}") from exc
    try:
        target = getattr(module, attribute)
    except AttributeError as exc:
        raise IngestError(
            f"{module_name!r} has no attribute {attribute!r} (needed for the {kind})"
        ) from exc
    return target


def instantiate(target: Any) -> Any:
    """Instantiate a configured class, or return a ready-made object."""
    if isinstance(target, type):
        return target()
    if not callable(target):
        return target
    if hasattr(target, "suggest") or hasattr(target, "scan"):
        return target
    return target()


class MutagenScanner:
    """Bundled fallback scanner: descriptor construction only (no tag logic).

    **Stopgap.** The Phase 1 scanner is MUSI-7's deliverable; this adapter exists
    so the review/write path can be exercised end to end before that merges.
    Configure the real one with ``--scanner`` and this becomes dead code.

    Every file is attempted; unsupported or unreadable files yield a
    :class:`ScanItem` with an ``error`` rather than an exception, so a batch
    survives malformed files.
    """

    def scan(self, root: Path) -> Iterable[ScanItem]:
        root = Path(root)
        if not root.is_dir():
            raise IngestError(f"scan root is not a directory: {root}")
        for directory, subdirectories, filenames in os.walk(root):
            subdirectories[:] = sorted(
                name for name in subdirectories if not name.startswith(".")
            )
            for filename in sorted(filenames):
                if filename.startswith("."):
                    continue
                path = Path(directory) / filename
                yield self._item(path)

    def _item(self, path: Path) -> ScanItem:
        try:
            stat = path.stat()
        except OSError as exc:
            return ScanItem(path=path, error=f"cannot stat: {exc}")
        try:
            descriptor = self._descriptor(path)
        except Exception as exc:  # noqa: BLE001 - per-file isolation
            return ScanItem(
                path=path,
                error=f"{type(exc).__name__}: {exc}",
                file_size_bytes=stat.st_size,
                mtime_ns=stat.st_mtime_ns,
            )
        return ScanItem(
            path=path,
            descriptor=descriptor,
            file_size_bytes=stat.st_size,
            mtime_ns=stat.st_mtime_ns,
        )

    @staticmethod
    def _descriptor(path: Path) -> TrackDescriptor:
        try:
            import mutagen  # type: ignore[import-not-found]
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise IngestError(
                "mutagen is not installed; cannot scan audio descriptors"
            ) from exc
        audio = mutagen.File(str(path), easy=True)
        if audio is None:
            raise IngestError("not a recognised audio container")
        tags = audio.tags or {}

        def first(*keys: str) -> str | None:
            for key in keys:
                try:
                    values = tags.get(key)
                except Exception:  # noqa: BLE001 - odd tag implementations
                    values = None
                if values:
                    for value in values:
                        text = str(value).strip()
                        if text:
                            return text
            return None

        date_text = first("date", "year", "originaldate")
        year = None
        if date_text:
            digits = "".join(
                character for character in date_text[:4] if character.isdigit()
            )
            if len(digits) == 4:
                year = int(digits)
        info = getattr(audio, "info", None)
        duration = getattr(info, "length", None)
        return TrackDescriptor(
            path=str(path),
            title=first("title"),
            artist=first("artist", "albumartist"),
            album=first("album"),
            genre=first("genre"),
            year=year,
            duration_seconds=float(duration) if duration is not None else None,
            format=_format_name(audio),
        )


def _format_name(audio: object) -> str | None:
    mapping = {
        "MP3": "mp3",
        "FLAC": "flac",
        "OggVorbis": "ogg",
        "OggOpus": "opus",
        "MP4": "m4a",
        "WAVE": "wav",
        "AIFF": "aiff",
    }
    return mapping.get(type(audio).__name__, type(audio).__name__.lower())


class IngestionService:
    """Runs the scanner and providers, persists tracks/suggestions, logs events."""

    def __init__(
        self,
        config: AppConfig,
        store: LibraryStore,
        taxonomy: TaxonomyService,
        events: EventLog,
        *,
        scanner: Scanner | None = None,
        providers: Sequence[tuple[str, SuggestionProvider]] = (),
        clock: Clock = utc_now_iso,
        run_id_factory=None,
    ) -> None:
        self.config = config
        self.store = store
        self.taxonomy = taxonomy
        self.events = events
        self.scanner = scanner or MutagenScanner()
        self.providers = tuple(providers)
        self._clock = clock
        self._run_id_factory = run_id_factory or new_run_id

    def scan(self, root: str | Path | None = None) -> ScanReport:
        scan_root = (
            Path(root).expanduser().resolve() if root else self.config.library_root
        )
        run_id = self._run_id_factory()
        indexed = 0
        skipped: list[SkippedPath] = []
        created = duplicates = unknown = 0
        for item in self.scanner.scan(scan_root):
            if item.descriptor is None:
                skipped.append(
                    SkippedPath(path=str(item.path), reason=item.error or "unreadable")
                )
                continue
            track_id = self.store.upsert_track(
                item.descriptor,
                file_size_bytes=item.file_size_bytes,
                mtime_ns=item.mtime_ns,
            )
            indexed += 1
            for source_name, provider in self.providers:
                try:
                    suggestions = provider.suggest(item.descriptor)
                except Exception as exc:  # noqa: BLE001 - per-track isolation
                    skipped.append(
                        SkippedPath(
                            path=str(item.path),
                            reason=f"provider {source_name} failed: {exc}",
                        )
                    )
                    continue
                for suggestion in suggestions:
                    if not isinstance(suggestion, TagSuggestion):
                        skipped.append(
                            SkippedPath(
                                path=str(item.path),
                                reason=(
                                    f"provider {source_name} returned a non-"
                                    f"TagSuggestion: {suggestion!r}"
                                ),
                            )
                        )
                        continue
                    try:
                        self.taxonomy.validate([suggestion.tag_id])
                    except Exception as exc:  # noqa: BLE001 - unknown tag is data
                        unknown += 1
                        skipped.append(
                            SkippedPath(
                                path=str(item.path),
                                reason=(
                                    f"provider {source_name} suggested unknown tag "
                                    f"{suggestion.tag_id!r}: {exc}"
                                ),
                            )
                        )
                        continue
                    self.events.emit(
                        suggestion_event(
                            run_id=run_id,
                            taxonomy_version=self.taxonomy.version,
                            track_path=item.descriptor.path,
                            track_format=item.descriptor.format,
                            suggestion=suggestion,
                        )
                    )
                    suggestion_id = self.store.add_suggestion(
                        track_id,
                        tag_id=suggestion.tag_id,
                        confidence=suggestion.confidence,
                        source=suggestion.source,
                        evidence=suggestion.evidence,
                        taxonomy_version=self.taxonomy.version,
                        engine_run_id=run_id,
                    )
                    if suggestion_id is None:
                        duplicates += 1
                    else:
                        created += 1
        return ScanReport(
            run_id=run_id,
            root=str(scan_root),
            indexed=indexed,
            skipped=tuple(skipped),
            suggestions_new=created,
            suggestions_duplicate=duplicates,
            suggestions_unknown=unknown,
            providers=tuple(name for name, _provider in self.providers),
        )


def new_run_id() -> str:
    stamp = utc_now_iso().replace("-", "").replace(":", "").replace(".", "")
    return f"run-{stamp}-{secrets.token_hex(3)}"


def build_scanner(config: AppConfig) -> Any:
    if not config.scanner_spec:
        return MutagenScanner()
    return instantiate(load_object(config.scanner_spec, kind="scanner"))


def build_providers(config: AppConfig) -> list[tuple[str, SuggestionProvider]]:
    if not config.provider_spec:
        return []
    specs = [part for part in config.provider_spec.split(",") if part.strip()]
    providers: list[tuple[str, SuggestionProvider]] = []
    for spec in specs:
        spec = spec.strip()
        name = spec.split(":", 1)[-1]
        provider = instantiate(load_object(spec, kind="provider"))
        if not hasattr(provider, "suggest"):
            raise IngestError(f"configured provider {spec!r} has no suggest() method")
        providers.append((name, provider))
    return providers
