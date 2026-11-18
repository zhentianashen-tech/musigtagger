"""Application configuration and the write-safety policy.

The configuration is deliberately explicit: the library root, the SQLite index,
the taxonomy directory + pinned version, the backup root, and the JSONL event
log. Nothing is discovered implicitly, because a write path must never guess
where it is allowed to write.

``protected_roots`` is the operator's read-only-source rule made executable: a
path under a protected root can be scanned but never written, backed up into, or
undone. The source library (``/test-data/music-source``) is protected by default.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping


class ConfigError(Exception):
    """The application configuration is invalid."""


class ProtectedPathError(Exception):
    """A write was refused because the path is under a read-only source root."""

    def __init__(self, path: str | Path, root: str | Path) -> None:
        self.path = str(path)
        self.root = str(root)
        super().__init__(
            f"refusing to write {self.path!r}: it is under the protected "
            f"read-only source root {self.root!r}"
        )


def _absolute(path: str | Path, *, base: Path | None = None) -> Path:
    candidate = Path(os.path.expanduser(str(path)))
    if not candidate.is_absolute() and base is not None:
        candidate = base / candidate
    return Path(os.path.abspath(candidate))


def _is_under(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


@dataclass(frozen=True)
class AppConfig:
    """Everything the application needs to run, in one immutable record."""

    library_root: Path
    database_path: Path
    backup_root: Path
    events_path: Path
    taxonomy_dir: Path
    taxonomy_version: str
    provider_spec: str | None = None
    scanner_spec: str | None = None
    #: NCM decoder used by the batch conversion step (MUSI-12 provides it).
    ncm_converter_spec: str | None = None
    #: Whether the default wiring includes the MusicBrainz release-date provider.
    #: Offline/local-only operation sets this False (``--no-network``); the
    #: local metadata provider (genre/era) is always part of the default path.
    network_enabled: bool = True
    #: Roots that may be read but never written. The operator's read-only source
    #: library is always protected; extra roots can be added on the command line.
    protected_roots: tuple[Path, ...] = field(
        default_factory=lambda: (Path("/test-data/music-source"),)
    )
    language: str = "en"
    actor: str = "local-user"
    page_size: int = 25

    def __post_init__(self) -> None:
        for name in (
            "library_root",
            "database_path",
            "backup_root",
            "events_path",
            "taxonomy_dir",
        ):
            object.__setattr__(self, name, _absolute(getattr(self, name)))
        if not isinstance(self.taxonomy_version, str) or not self.taxonomy_version:
            raise ConfigError("taxonomy_version must be a non-empty string")
        if self.page_size < 1:
            raise ConfigError("page_size must be >= 1")
        roots: list[Path] = []
        for root in self.protected_roots:
            roots.append(_absolute(root))
        object.__setattr__(self, "protected_roots", tuple(roots))

    @classmethod
    def from_mapping(
        cls,
        values: Mapping[str, object],
        *,
        base: Path | None = None,
    ) -> "AppConfig":
        """Build a config from CLI/env values, resolving relative paths."""

        def path(name: str, fallback: str) -> Path:
            raw = values.get(name, fallback)
            return _absolute(str(raw), base=base)

        protected_raw = values.get("protected_roots")
        # The operator's source library is always protected; --protect adds to it
        # rather than replacing it.
        protected: list[Path] = [Path("/test-data/music-source")]
        if protected_raw is not None:
            if isinstance(protected_raw, str):
                protected.extend(
                    Path(part) for part in protected_raw.split(os.pathsep) if part
                )
            else:
                protected.extend(
                    Path(str(part)) for part in protected_raw  # type: ignore[union-attr]
                )
        seen: set[Path] = set()
        unique_protected: list[Path] = []
        for candidate in protected:
            absolute = _absolute(candidate)
            if absolute not in seen:
                seen.add(absolute)
                unique_protected.append(absolute)

        return cls(
            library_root=path("library_root", "."),
            database_path=path("database_path", "library.sqlite3"),
            backup_root=path("backup_root", "backups"),
            events_path=path("events_path", "events.jsonl"),
            taxonomy_dir=path("taxonomy_dir", "taxonomy"),
            taxonomy_version=str(values.get("taxonomy_version", "1.0.0")),
            provider_spec=(str(values["provider_spec"]) if values.get("provider_spec") else None),
            scanner_spec=(str(values["scanner_spec"]) if values.get("scanner_spec") else None),
            ncm_converter_spec=(
                str(values["ncm_converter_spec"])
                if values.get("ncm_converter_spec")
                else None
            ),
            network_enabled=bool(values.get("network_enabled", True)),
            protected_roots=tuple(unique_protected),
            language=str(values.get("language", "en")),
            actor=str(values.get("actor", "local-user")),
            page_size=int(values.get("page_size", 25)),  # type: ignore[arg-type]
        )

    # -- write safety ----------------------------------------------------

    def protected_root_for(self, path: str | Path) -> Path | None:
        """Return the protected root that contains ``path``, if any.

        Symlinks are resolved first so a symlinked copy cannot sneak a write
        into the source library. Non-existent paths are resolved through their
        nearest existing parent.
        """
        candidate = _absolute(path)
        candidates = [candidate]
        try:
            candidates.append(candidate.resolve(strict=False))
        except OSError:  # pragma: no cover - defensive
            pass
        for root in self.protected_roots:
            resolved_root = root
            try:
                resolved_root = root.resolve(strict=False)
            except OSError:  # pragma: no cover - defensive
                pass
            for probe in candidates:
                if _is_under(probe, root) or _is_under(probe, resolved_root):
                    return root
        return None

    def assert_writable(self, path: str | Path) -> None:
        """Refuse any write into a protected read-only source root."""
        root = self.protected_root_for(path)
        if root is not None:
            raise ProtectedPathError(path, root)

    def ensure_directories(self) -> None:
        """Create the app-owned directories (never the library root)."""
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.backup_root.mkdir(parents=True, exist_ok=True)
        self.events_path.parent.mkdir(parents=True, exist_ok=True)
