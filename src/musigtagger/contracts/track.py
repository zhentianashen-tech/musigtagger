"""Track descriptors: the engine's input value object.

A :class:`TrackDescriptor` is the complete, already-parsed view of one audio
file that a suggestion provider is allowed to see. Building one is the
scanner's job (file ingestion belongs to the application/engine boundary); the
provider never opens the file itself.

Design notes
------------
* Immutable value type: providers must not be able to mutate their input.
* No I/O: the descriptor is plain data. Paths are stored as strings so the
  descriptor is hashable and JSON-loggable.
* Phase 2 audio features have reserved slots (:class:`AudioFeatures`). Phase 1
  providers receive ``features=None`` and must not require it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping


def _require_optional_text(field_name: str, value: object) -> None:
    if value is not None and not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string or None")


def _require_unit_interval(field_name: str, value: float | None) -> None:
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field_name} must be a number or None")
    if not math.isfinite(value) or not 0.0 <= float(value) <= 1.0:
        raise ValueError(f"{field_name} must be between 0.0 and 1.0, got {value!r}")


@dataclass(frozen=True, slots=True)
class AudioFeatures:
    """Reserved Phase 2 audio-analysis slots.

    Phase 1 never populates this object. Phase 2 providers may do so and still
    implement the same provider interface; no contract change is required.
    Providers that need extra, provider-specific values use ``extra``.
    """

    tempo_bpm: float | None = None
    energy: float | None = None
    valence: float | None = None
    danceability: float | None = None
    key: str | None = None
    mode: str | None = None
    extra: Mapping[str, float | str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.tempo_bpm is not None:
            if isinstance(self.tempo_bpm, bool) or not isinstance(
                self.tempo_bpm, (int, float)
            ):
                raise TypeError("tempo_bpm must be a number or None")
            if not math.isfinite(self.tempo_bpm) or self.tempo_bpm <= 0:
                raise ValueError(f"tempo_bpm must be > 0, got {self.tempo_bpm!r}")
            object.__setattr__(self, "tempo_bpm", float(self.tempo_bpm))
        for name in ("energy", "valence", "danceability"):
            _require_unit_interval(name, getattr(self, name))
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, float(value))
        _require_optional_text("key", self.key)
        _require_optional_text("mode", self.mode)
        extra = dict(self.extra)
        for key, value in extra.items():
            if not isinstance(key, str) or not key:
                raise TypeError("extra feature keys must be non-empty strings")
            if not isinstance(value, (str, int, float)) or isinstance(value, bool):
                raise TypeError(
                    f"extra feature {key!r} must be a string or number"
                )
        object.__setattr__(self, "extra", MappingProxyType(extra))


@dataclass(frozen=True, slots=True)
class TrackDescriptor:
    """Parsed view of a single audio track, as handed to a provider.

    Parameters
    ----------
    path:
        Absolute path to the audio file. Only the application layer may use it
        to read or write; providers treat it as an opaque identifier.
    title, artist, album, genre:
        Existing embedded metadata, parsed to plain strings. ``None`` means the
        field was absent (not empty string).
    year:
        Release year parsed from ``TDRC``/``DATE``/``YEAR`` when present. Needed
        by the metadata provider for ``era`` suggestions.
    duration_seconds:
        Track duration in seconds, if known.
    format:
        Container/codec name as reported by the scan (``"mp3"``, ``"flac"``,
        ``"ogg"``).
    features:
        Phase 2 audio features; ``None`` in Phase 1.
    """

    path: str
    title: str | None = None
    artist: str | None = None
    album: str | None = None
    genre: str | None = None
    year: int | None = None
    duration_seconds: float | None = None
    format: str | None = None
    features: AudioFeatures | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.path, str) or not self.path.strip():
            raise ValueError("path must be a non-empty string")
        for name in ("title", "artist", "album", "genre", "format"):
            _require_optional_text(name, getattr(self, name))
        if self.year is not None:
            if isinstance(self.year, bool) or not isinstance(self.year, int):
                raise TypeError("year must be an integer or None")
            if not 1 <= self.year <= 9999:
                raise ValueError(f"year must be between 1 and 9999, got {self.year}")
        if self.duration_seconds is not None:
            if isinstance(self.duration_seconds, bool) or not isinstance(
                self.duration_seconds, (int, float)
            ):
                raise TypeError("duration_seconds must be a number or None")
            if not math.isfinite(self.duration_seconds) or self.duration_seconds < 0:
                raise ValueError(
                    "duration_seconds must be a finite number >= 0, "
                    f"got {self.duration_seconds!r}"
                )
            object.__setattr__(self, "duration_seconds", float(self.duration_seconds))
        if self.features is not None and not isinstance(self.features, AudioFeatures):
            raise TypeError("features must be an AudioFeatures instance or None")
