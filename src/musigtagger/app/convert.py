"""Batch conversion: the persistent "step 0" of the pipeline.

NetEase `.ncm` files are encrypted containers, not audio files. The decoder is
not part of the application layer (MUSI-12 delivers ``musigtagger.ncm``); this
module owns the batch orchestration around it:

* walk a source tree and convert every `.ncm` to a **persistent** MP3/FLAC in an
  output tree (transient output is only acceptable in tests);
* preserve the relative directory layout, so the output tree can be used as the
  app's ``--library-root``;
* never write into the source tree or a protected read-only root;
* skip already-converted files unless ``--force`` is given;
* isolate per-file faults (skip/log/continue, consistent with the rest of the
  pipeline) and write a machine-readable ``conversion-report.json``.

The converter is a port: any callable ``(source_path, destination_path) -> Path``
can be supplied (``--ncm-converter module:Attribute``). The default is
``musigtagger.ncm:convert_file``, the function MUSI-12 exposes.
"""

from __future__ import annotations

import importlib
import json
import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Protocol

from .config import AppConfig
from .ingest import IngestError, load_object
from .util import Clock, atomic_replace, utc_now_iso

DEFAULT_DECODER_MODULE = "musigtagger.ncm"
NCM_SUFFIX = ".ncm"
REPORT_NAME = "conversion-report.json"
AUDIO_SUFFIXES = (".mp3", ".flac", ".ogg", ".oga")


class ConversionError(Exception):
    """A conversion batch cannot start or a result is unusable."""


class ConverterUnavailableError(ConversionError):
    """The configured NCM decoder is not importable in this environment."""


class UnsupportedOutputError(ConversionError):
    """The converter produced bytes that are not a recognised audio stream."""


class Converter(Protocol):
    def __call__(self, source: str | Path, destination: str | Path) -> Path | None:
        """Write the decoded audio to ``destination`` and return the path used."""
        ...


@dataclass(frozen=True)
class ConversionOutcome:
    source: str
    destination: str | None
    status: str  # "converted" | "skipped" | "failed"
    format: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class ConversionReport:
    source_root: str
    output_root: str
    started_at: str
    finished_at: str
    outcomes: tuple[ConversionOutcome, ...] = field(default_factory=tuple)
    report_path: str | None = None

    @property
    def converted(self) -> tuple[ConversionOutcome, ...]:
        return tuple(o for o in self.outcomes if o.status == "converted")

    @property
    def skipped(self) -> tuple[ConversionOutcome, ...]:
        return tuple(o for o in self.outcomes if o.status == "skipped")

    @property
    def failed(self) -> tuple[ConversionOutcome, ...]:
        return tuple(o for o in self.outcomes if o.status == "failed")

    @property
    def converted_count(self) -> int:
        return len(self.converted)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": "musigtagger.conversion.v1",
            "source_root": self.source_root,
            "output_root": self.output_root,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "counts": {
                "total": len(self.outcomes),
                "converted": len(self.converted),
                "skipped": len(self.skipped),
                "failed": len(self.failed),
            },
            "outcomes": [
                {
                    "source": outcome.source,
                    "destination": outcome.destination,
                    "status": outcome.status,
                    "format": outcome.format,
                    "error": outcome.error,
                }
                for outcome in self.outcomes
            ],
        }


class EngineNcmConverter:
    """Adapter for MUSI-12's ``musigtagger.ncm`` decoder module.

    The engine's ``convert_file`` refuses an output whose extension does not
    match the decoded payload, so the application passes a decoder-agnostic
    temporary name. This adapter asks ``decode`` for the extension, gives the
    temp file that suffix, and writes through the engine's own tag/cover
    restoration. It never re-implements decoding.
    """

    def __init__(self, module: object) -> None:
        self._decode = getattr(module, "decode", None)
        self._convert = getattr(module, "convert", None)
        self._convert_file = getattr(module, "convert_file", None)
        if self._decode is None or (self._convert is None and self._convert_file is None):
            raise ConverterUnavailableError(
                "the NCM decoder module has no decode()/convert() API; "
                "expected MUSI-12's musigtagger.ncm contract"
            )

    def __call__(self, source: str | Path, destination: str | Path) -> Path:
        track = self._decode(source)
        extension = getattr(track, "extension", None)
        if not extension:
            raise ConversionError(
                f"decoder did not report an output extension for {source}"
            )
        target = Path(destination).with_suffix(str(extension))
        if self._convert is not None:
            written = self._convert(track, target)
        else:  # pragma: no cover - fallback for a decode/convert_file-only module
            written = self._convert_file(source, target)
        return Path(written) if written is not None else target


def load_converter(spec: str | None = None) -> Converter:
    """Resolve the converter port, failing with an actionable message."""
    if spec:
        try:
            target = load_object(spec, kind="NCM converter")
        except IngestError as exc:
            raise ConverterUnavailableError(
                f"NCM converter {spec!r} is not available in this checkout "
                f"({exc}). Conversion is delivered by MUSI-12 "
                "(musigtagger.ncm); merge/install it, or pass "
                "--ncm-converter module:Attribute."
            ) from exc
        if not callable(target):
            raise ConverterUnavailableError(f"{spec!r} is not callable")
        return target
    try:
        module = importlib.import_module(DEFAULT_DECODER_MODULE)
    except ImportError as exc:
        raise ConverterUnavailableError(
            f"NCM decoder module {DEFAULT_DECODER_MODULE!r} is not available in "
            f"this checkout ({exc}). Conversion is delivered by MUSI-12; "
            "merge/install it, or pass --ncm-converter module:Attribute."
        ) from exc
    return EngineNcmConverter(module)


def sniff_audio_suffix(path: str | Path) -> str:
    """Return the audio suffix for a decoded stream, or raise.

    Conversion is a remux, so the payload is already MP3/FLAC/Ogg; the suffix
    must follow the bytes, not the source container's name.
    """
    with open(path, "rb") as handle:
        head = handle.read(12)
    if head[:4] == b"fLaC":
        return ".flac"
    if head[:4] == b"OggS":
        return ".ogg"
    if head[:3] == b"ID3":
        return ".mp3"
    if len(head) >= 2 and head[0] == 0xFF and head[1] in (0xFB, 0xF3, 0xF2, 0xFA):
        return ".mp3"
    raise UnsupportedOutputError(
        f"converter output for {path} is not a recognised MP3/FLAC/Ogg stream "
        f"(starts with {head[:8]!r})"
    )


class ConversionService:
    """Converts a tree of containers into a persistent audio tree."""

    def __init__(
        self,
        config: AppConfig,
        converter: Converter,
        *,
        clock: Clock = utc_now_iso,
    ) -> None:
        self.config = config
        self.converter = converter
        self._clock = clock

    def convert_tree(
        self,
        source_root: str | Path,
        output_root: str | Path,
        *,
        force: bool = False,
        limit: int | None = None,
    ) -> ConversionReport:
        source = Path(source_root).expanduser().resolve()
        output = Path(output_root).expanduser().resolve()
        if not source.is_dir():
            raise ConversionError(f"source directory does not exist: {source}")
        self._validate_roots(source, output)
        output.mkdir(parents=True, exist_ok=True)

        started = self._clock()
        outcomes: list[ConversionOutcome] = []
        for index, ncm_path in enumerate(self._ncm_files(source)):
            if limit is not None and index >= limit:
                break
            outcomes.append(self._convert_one(source, output, ncm_path, force=force))
        finished = self._clock()
        report = ConversionReport(
            source_root=str(source),
            output_root=str(output),
            started_at=started,
            finished_at=finished,
            outcomes=tuple(outcomes),
        )
        report_path = self._write_report(output, report)
        return ConversionReport(
            source_root=report.source_root,
            output_root=report.output_root,
            started_at=report.started_at,
            finished_at=report.finished_at,
            outcomes=report.outcomes,
            report_path=str(report_path),
        )

    # -- internals -------------------------------------------------------

    def _validate_roots(self, source: Path, output: Path) -> None:
        if output == source or _is_within(output, source):
            raise ConversionError(
                f"output directory {output} must be outside the source tree "
                f"{source}: converted files are a separate persistent library"
            )
        if _is_within(source, output):
            raise ConversionError(
                f"source directory {source} must not be inside the output "
                f"directory {output}"
            )
        # The output (and every file written below it) must be writable; this
        # also refuses the read-only source root and anything under it.
        self.config.assert_writable(output)

    @staticmethod
    def _ncm_files(root: Path) -> Iterable[Path]:
        for directory, subdirectories, filenames in os.walk(root):
            subdirectories[:] = sorted(
                name for name in subdirectories if not name.startswith(".")
            )
            for filename in sorted(filenames):
                if filename.startswith("."):
                    continue
                path = Path(directory) / filename
                if path.suffix.lower() == NCM_SUFFIX:
                    yield path

    def _convert_one(
        self, source_root: Path, output_root: Path, ncm_path: Path, *, force: bool
    ) -> ConversionOutcome:
        relative = ncm_path.relative_to(source_root)
        stem = (output_root / relative).with_suffix("")
        existing = _existing_audio(stem)
        if existing is not None and not force:
            return ConversionOutcome(
                source=str(ncm_path),
                destination=str(existing),
                status="skipped",
                format=existing.suffix.lstrip("."),
            )
        temporary = stem.parent / f".{stem.name}.{secrets.token_hex(4)}.partial"
        written: Path | None = None
        destination: Path | None = None
        try:
            stem.parent.mkdir(parents=True, exist_ok=True)
            self.config.assert_writable(temporary)
            result = self.converter(ncm_path, temporary)
            written = Path(result) if result is not None else temporary
            if not written.is_file():
                raise ConversionError(
                    f"converter produced no file for {ncm_path}"
                )
            suffix = sniff_audio_suffix(written)
            destination = stem.with_suffix(suffix)
            self.config.assert_writable(destination)
            final = destination
            atomic_replace(written, final)
            return ConversionOutcome(
                source=str(ncm_path),
                destination=str(final),
                status="converted",
                format=suffix.lstrip("."),
            )
        except Exception as exc:  # noqa: BLE001 - per-file isolation
            return ConversionOutcome(
                source=str(ncm_path),
                destination=str(stem),
                status="failed",
                error=f"{type(exc).__name__}: {exc}",
            )
        finally:
            for candidate in {temporary, written}:
                if candidate is None or candidate == destination:
                    continue
                if candidate.exists():
                    try:
                        candidate.unlink()
                    except OSError:  # pragma: no cover - best effort cleanup
                        pass

    def _write_report(self, output: Path, report: ConversionReport) -> Path:
        destination = output / REPORT_NAME
        temporary = output / f".{REPORT_NAME}.{secrets.token_hex(4)}.tmp"
        temporary.write_text(
            json.dumps(report.to_dict(), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        atomic_replace(temporary, destination)
        return destination


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _existing_audio(stem: Path) -> Path | None:
    for suffix in AUDIO_SUFFIXES:
        candidate = stem.with_suffix(suffix)
        if candidate.is_file():
            return candidate
    return None
