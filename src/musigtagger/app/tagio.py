"""Audio tag I/O: the mutagen adapter (the only place tag frames are written).

This module is one narrow adapter behind :class:`TagCodec`. It knows nothing
about taxonomy *content* (which tags exist) or review state — it receives a
field→values projection from :mod:`musigtagger.app.tagmap` and writes it.

Design constraints:

* ``mutagen`` is imported lazily, inside the functions that need it, so the rest
  of the application (and the safety-critical backup/undo tests) run without it.
* Only the two Phase 1 tag families are written: ID3v2 (mp3) and Vorbis comments
  (flac/ogg). Any other container is refused, not guessed at.
* The caller always writes to a throw-away copy and renames it over the target;
  this adapter never claims atomicity of its own.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Protocol, Sequence, runtime_checkable

from .tagmap import (
    FAMILY_ID3,
    FAMILY_VORBIS,
    TXXX_PREFIX,
    UnsupportedFormatError,
    family_for_format,
    managed_fields,
)


class TagReadError(Exception):
    """An audio file could not be parsed for tags."""


class UnsupportedTagContainerError(Exception):
    """The parsed container has no tag family this Phase 1 path can write."""

    def __init__(self, format_name: str | None) -> None:
        self.format_name = format_name
        super().__init__(
            f"container {format_name!r} has no supported tag family "
            "(expected ID3v2 or Vorbis comments)"
        )


@dataclass(frozen=True)
class AudioProbe:
    """Format-level facts used to prove a tag write did not touch the audio."""

    format: str | None
    duration_seconds: float | None
    sample_rate: int | None
    channels: int | None
    bitrate: int | None
    size_bytes: int

    def audio_matches(self, other: "AudioProbe") -> bool:
        """True when the audio stream looks unchanged.

        Container rewrites are allowed to change the file size (tag length), so
        size is not compared; duration, sample rate, and channel count are.
        Duration may shift by a frame or two when a tag is re-encoded, hence the
        50 ms tolerance.
        """
        if self.format != other.format:
            return False
        if self.sample_rate != other.sample_rate:
            return False
        if self.channels != other.channels:
            return False
        if self.duration_seconds is None or other.duration_seconds is None:
            return self.duration_seconds is None and other.duration_seconds is None
        return abs(self.duration_seconds - other.duration_seconds) <= 0.05


@runtime_checkable
class TagCodec(Protocol):
    """The tag read/write port the write path depends on."""

    def read(self, path: str | Path) -> dict[str, list[str]]:
        ...

    def write(self, path: str | Path, fields: Mapping[str, Sequence[str]]) -> None:
        ...

    def probe(self, path: str | Path) -> AudioProbe:
        ...

    def supports(self, path: str | Path) -> bool:
        ...


def _import_mutagen():  # pragma: no cover - import indirection is trivial
    try:
        import mutagen  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - depends on the environment
        raise TagReadError(
            "mutagen is not installed; install the pinned dependency "
            "(mutagen==1.48.1) to read or write audio tags"
        ) from exc
    return mutagen


def _format_name(audio: object) -> str | None:
    name = type(audio).__name__
    mapping = {
        "MP3": "mp3",
        "FLAC": "flac",
        "OggVorbis": "ogg",
        "OggOpus": "opus",
        "OggTheora": "ogg",
    }
    return mapping.get(name, name.lower())


class MutagenTagger:
    """Production :class:`TagCodec` backed by ``mutagen``."""

    def read(self, path: str | Path) -> dict[str, list[str]]:
        mutagen = _import_mutagen()
        try:
            audio = mutagen.File(str(path))
        except Exception as exc:  # noqa: BLE001 - mutagen raises many types
            raise TagReadError(f"cannot parse {path}: {exc}") from exc
        if audio is None:
            raise TagReadError(f"unrecognised audio file: {path}")
        tags = audio.tags
        if tags is None:
            return {}
        if isinstance(tags, mutagen.id3.ID3):
            collected: dict[str, list[str]] = {}
            for frame in tags.values():
                frame_id = getattr(frame, "FrameID", None)
                if frame_id == "TXXX":
                    desc = str(getattr(frame, "desc", "") or "").strip()
                    text = [str(value) for value in getattr(frame, "text", [])]
                    if desc:
                        collected[f"{TXXX_PREFIX}{desc}"] = text
                    continue
                text = getattr(frame, "text", None)
                if frame_id and text is not None:
                    collected[frame_id] = [str(value) for value in text]
            return collected
        try:
            keys = list(tags.keys())
        except AttributeError:
            return {}
        return {str(key): [str(value) for value in tags[key]] for key in keys}

    def write(self, path: str | Path, fields: Mapping[str, Sequence[str]]) -> None:
        mutagen = _import_mutagen()
        try:
            audio = mutagen.File(str(path))
        except Exception as exc:  # noqa: BLE001 - mutagen raises many types
            raise TagReadError(f"cannot parse {path}: {exc}") from exc
        if audio is None:
            raise TagReadError(f"unrecognised audio file: {path}")
        tags = audio.tags
        if tags is None:
            audio.add_tags()
            tags = audio.tags
        if isinstance(tags, mutagen.id3.ID3):
            self._write_id3(mutagen, tags, fields)
        elif type(tags).__name__ in ("VCommentDict", "VCFLACDict"):
            self._write_vorbis(tags, fields)
        else:
            raise UnsupportedTagContainerError(_format_name(audio))
        audio.save()

    @staticmethod
    def _write_id3(mutagen, tags, fields: Mapping[str, Sequence[str]]) -> None:
        managed = set(managed_fields(FAMILY_ID3))
        # Remove every field this application owns before rewriting, so a
        # reviewed-out tag disappears instead of lingering.
        for frame_id in ("TCON",):
            if frame_id in managed and frame_id in tags:
                del tags[frame_id]
        for frame in list(tags.getall("TXXX")):
            desc = str(getattr(frame, "desc", "") or "").strip()
            if f"{TXXX_PREFIX}{desc}" in managed:
                tags.delall(frame.HashKey)
        for field, values in fields.items():
            if field not in managed:
                continue
            clean = [value for value in values if str(value).strip()]
            if not clean:
                continue
            if field.startswith(TXXX_PREFIX):
                desc = field[len(TXXX_PREFIX) :]
                tags.add(
                    mutagen.id3.TXXX(encoding=1, desc=desc, text=[str(v) for v in clean])
                )
            else:
                tags.add(mutagen.id3.Frames[field](encoding=1, text=[str(v) for v in clean]))

    @staticmethod
    def _write_vorbis(tags, fields: Mapping[str, Sequence[str]]) -> None:
        managed = set(managed_fields(FAMILY_VORBIS))
        for field in managed:
            if field in tags:
                del tags[field]
        for field, values in fields.items():
            if field not in managed:
                continue
            clean = [str(value) for value in values if str(value).strip()]
            if clean:
                tags[field] = clean

    def probe(self, path: str | Path) -> AudioProbe:
        mutagen = _import_mutagen()
        try:
            audio = mutagen.File(str(path))
        except Exception as exc:  # noqa: BLE001 - mutagen raises many types
            raise TagReadError(f"cannot parse {path}: {exc}") from exc
        if audio is None:
            raise TagReadError(f"unrecognised audio file: {path}")
        info = getattr(audio, "info", None)
        return AudioProbe(
            format=_format_name(audio),
            duration_seconds=_optional_float(getattr(info, "length", None)),
            sample_rate=_optional_int(getattr(info, "sample_rate", None)),
            channels=_optional_int(getattr(info, "channels", None)),
            bitrate=_optional_int(getattr(info, "bitrate", None)),
            size_bytes=Path(path).stat().st_size,
        )

    def supports(self, path: str | Path) -> bool:
        try:
            mutagen = _import_mutagen()
            audio = mutagen.File(str(path))
        except Exception:  # noqa: BLE001 - unsupported/unparseable is "no"
            return False
        if audio is None:
            return False
        tags = audio.tags
        return isinstance(tags, mutagen.id3.ID3) or type(tags).__name__ in (
            "VCommentDict",
            "VCFLACDict",
        )


def codec_for_format(format_name: str | None) -> str:
    """Validate that a scanner-reported format is writable; returns the family."""
    return family_for_format(format_name)


def _optional_float(value: object) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _optional_int(value: object) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


__all__ = [
    "AudioProbe",
    "MutagenTagger",
    "TagCodec",
    "TagReadError",
    "UnsupportedFormatError",
    "UnsupportedTagContainerError",
    "codec_for_format",
]
