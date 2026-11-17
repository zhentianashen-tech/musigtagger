"""Batch-oriented local audio scanner and SQLite library-index upserts.

The scanner is the only engine component that reads audio files. It never opens
one for writing. A malformed or unreadable track is logged and isolated from
the rest of the directory batch.
"""

from __future__ import annotations

import logging
import re
import sqlite3
import tempfile
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import mutagen

from musigtagger.contracts import TrackDescriptor
from musigtagger.ncm import convert, decode

LOGGER = logging.getLogger(__name__)
SUPPORTED_AUDIO_SUFFIXES = frozenset({".mp3", ".flac", ".ncm", ".ogg", ".oga"})
_YEAR_RE = re.compile(r"(?<!\d)(\d{4})(?!\d)")


@dataclass(frozen=True, slots=True)
class ScanFailure:
    """One non-fatal per-track scanning failure."""

    path: str
    reason: str


@dataclass(frozen=True, slots=True)
class ScanBatchResult:
    """Successful descriptors and all failures from one directory batch."""

    tracks: tuple[TrackDescriptor, ...]
    failures: tuple[ScanFailure, ...]
    discovered_audio_files: int

    @property
    def completed(self) -> bool:
        """Whether the batch ran to completion, including isolated failures."""
        return True


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def _first_text(tags: Any, *keys: str) -> str | None:
    if tags is None:
        return None
    for key in keys:
        try:
            value = tags.get(key)
        except AttributeError:
            return None
        if value is None:
            continue
        if isinstance(value, (list, tuple)):
            value = value[0] if value else None
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def _parse_year(value: str | None) -> int | None:
    if value is None:
        return None
    match = _YEAR_RE.search(value)
    if match is None:
        return None
    year = int(match.group(1))
    return year if 1 <= year <= 9999 else None


def _format_name(audio: Any, path: Path) -> str:
    if path.suffix.lower() != ".audio":
        return path.suffix.lower().lstrip(".")
    return {
        "EasyMP3": "mp3",
        "MP3": "mp3",
        "FLAC": "flac",
        "OggVorbis": "ogg",
        "OggOpus": "ogg",
        "OggFLAC": "oga",
    }.get(type(audio).__name__, path.suffix.lower().lstrip("."))


def parse_audio_file(path: str | Path) -> tuple[TrackDescriptor, int, int]:
    """Read one supported file and return its descriptor, size, and mtime.

    This function deliberately raises on malformed input; the batch scanner is
    the isolation boundary that logs the error and continues.
    """
    audio_path = Path(path)
    stat = audio_path.stat()
    audio = mutagen.File(audio_path, easy=True)
    if audio is None:
        raise ValueError("mutagen could not identify a supported audio stream")

    tags = getattr(audio, "tags", None)
    info = getattr(audio, "info", None)
    length = getattr(info, "length", None)
    duration = float(length) if length is not None else None
    descriptor = TrackDescriptor(
        path=str(audio_path.resolve()),
        title=_first_text(tags, "title"),
        artist=_first_text(tags, "artist", "albumartist"),
        album=_first_text(tags, "album"),
        genre=_first_text(tags, "genre"),
        year=_parse_year(_first_text(tags, "date", "originaldate", "year")),
        duration_seconds=duration,
        format=_format_name(audio, audio_path),
    )
    return descriptor, stat.st_size, stat.st_mtime_ns


def _parse_candidate(path: Path) -> tuple[TrackDescriptor, int, int]:
    if path.suffix.lower() != ".ncm":
        return parse_audio_file(path)

    stat = path.stat()
    decoded = decode(path)
    with tempfile.TemporaryDirectory(prefix="musigtagger-ncm-") as directory:
        converted = Path(directory) / f"decoded{decoded.extension}"
        convert(decoded, converted)
        descriptor, _, _ = parse_audio_file(converted)
    descriptor = replace(descriptor, path=str(path.resolve()))
    return descriptor, stat.st_size, stat.st_mtime_ns


class LibraryScanner:
    """Scan directory batches and upsert tracks into schema-v1 SQLite storage."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def scan_directory(self, directory: str | Path) -> ScanBatchResult:
        """Recursively scan supported files, preserving successful work on faults."""
        root = Path(directory)
        if not root.is_dir():
            raise ValueError(f"library directory does not exist: {root}")

        candidates = sorted(
            (
                path
                for path in root.rglob("*")
                if path.is_file() and path.suffix.lower() in SUPPORTED_AUDIO_SUFFIXES
            ),
            key=lambda path: str(path).casefold(),
        )
        tracks: list[TrackDescriptor] = []
        failures: list[ScanFailure] = []
        for path in candidates:
            try:
                descriptor, size, mtime_ns = _parse_candidate(path)
                self._upsert(descriptor, size, mtime_ns)
            except Exception as exc:  # mutagen and filesystem errors vary by codec
                reason = f"{type(exc).__name__}: {exc}"
                failures.append(ScanFailure(str(path.resolve()), reason))
                LOGGER.warning("Skipping unreadable audio file %s: %s", path, reason)
                continue
            tracks.append(descriptor)

        return ScanBatchResult(
            tracks=tuple(tracks),
            failures=tuple(failures),
            discovered_audio_files=len(candidates),
        )

    def _upsert(self, track: TrackDescriptor, size: int, mtime_ns: int) -> None:
        now = _utc_now()
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO tracks (
                    path, title, artist, album, genre, year, duration_seconds,
                    format, file_size_bytes, mtime_ns, last_scanned_at,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(path) DO UPDATE SET
                    title = excluded.title,
                    artist = excluded.artist,
                    album = excluded.album,
                    genre = excluded.genre,
                    year = excluded.year,
                    duration_seconds = excluded.duration_seconds,
                    format = excluded.format,
                    file_size_bytes = excluded.file_size_bytes,
                    mtime_ns = excluded.mtime_ns,
                    last_scanned_at = excluded.last_scanned_at,
                    updated_at = excluded.updated_at
                """,
                (
                    track.path,
                    track.title,
                    track.artist,
                    track.album,
                    track.genre,
                    track.year,
                    track.duration_seconds,
                    track.format,
                    size,
                    mtime_ns,
                    now,
                    now,
                    now,
                ),
            )
