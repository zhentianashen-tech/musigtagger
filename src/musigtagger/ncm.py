"""Decode NetEase Cloud Music NCM containers without transcoding.

``decode`` is the scanner-facing, in-memory API. ``convert`` adds the explicit
one-file output operation used by the CLI; it never changes the source file.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import json
import os
import struct
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from mutagen import File as MutagenFile
from mutagen.flac import Picture
from mutagen.id3 import APIC, TALB, TIT2, TPE1, ID3

from .contracts import TrackDescriptor

_MAGIC = b"CTENFDAM"
_CORE_KEY = b"hzHRAmso5kInbaxW"
_METADATA_KEY = b"#14ljk_!\\]&0U<'("
_KEY_XOR = 0x64
_METADATA_XOR = 0x63
_KEY_PREFIX = b"neteasecloudmusic"
_METADATA_PREFIX = b"163 key(Don't modify):"
_JSON_PREFIX = b"music:"


class NCMError(ValueError):
    """Base class for a malformed or unsupported NCM input."""


class NCMFormatError(NCMError):
    """The input is not a structurally valid NCM container."""


class UnsupportedAudioFormatError(NCMError):
    """The decrypted payload is not MP3 or FLAC."""


@dataclass(frozen=True, slots=True)
class NCMMetadata:
    """Normalized metadata extracted from the NCM metadata JSON."""

    title: str | None = None
    artist: str | None = None
    album: str | None = None
    raw: Mapping[str, object] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "raw", MappingProxyType(dict(self.raw)))


@dataclass(frozen=True, slots=True)
class DecodedTrack:
    """Losslessly decrypted audio plus NCM metadata and embedded cover bytes."""

    audio_bytes: bytes
    format: str
    metadata: NCMMetadata
    cover: bytes | None = None

    @property
    def extension(self) -> str:
        return f".{self.format}"

    def track_descriptor(self, path: str | os.PathLike[str]) -> TrackDescriptor:
        """Adapt the normalized metadata to the existing scanner value object."""
        return TrackDescriptor(
            path=str(path),
            title=self.metadata.title,
            artist=self.metadata.artist,
            album=self.metadata.album,
            format=self.format,
        )


def _unpad_pkcs7(data: bytes) -> bytes:
    if not data or len(data) % 16:
        raise NCMFormatError("invalid AES block length")
    padding = data[-1]
    if not 1 <= padding <= 16 or data[-padding:] != bytes([padding]) * padding:
        raise NCMFormatError("invalid AES padding")
    return data[:-padding]


def _decrypt_aes(data: bytes, key: bytes) -> bytes:
    try:
        decryptor = Cipher(algorithms.AES(key), modes.ECB()).decryptor()
        return _unpad_pkcs7(decryptor.update(data) + decryptor.finalize())
    except NCMError:
        raise
    except (ValueError, TypeError) as exc:
        raise NCMFormatError("invalid encrypted NCM field") from exc


def _read_u32(data: bytes, offset: int) -> tuple[int, int]:
    if offset + 4 > len(data):
        raise NCMFormatError("truncated NCM field length")
    return struct.unpack_from("<I", data, offset)[0], offset + 4


def _take(data: bytes, offset: int, length: int, name: str) -> tuple[bytes, int]:
    if length < 0 or offset + length > len(data):
        raise NCMFormatError(f"truncated NCM {name}")
    return data[offset : offset + length], offset + length


def _key_box(key: bytes) -> list[int]:
    if not key:
        raise NCMFormatError("empty NCM audio key")
    box = list(range(256))
    j = 0
    for i in range(256):
        j = (j + box[i] + key[i % len(key)]) & 0xFF
        box[i], box[j] = box[j], box[i]
    return box


def _decrypt_audio(data: bytes, key: bytes) -> bytes:
    box = _key_box(key)
    result = bytearray(data)
    for start in range(0, len(result), 32768):
        end = min(start + 32768, len(result))
        for index in range(start, end):
            j = (index - start + 1) & 0xFF
            result[index] ^= box[(box[j] + box[(box[j] + j) & 0xFF]) & 0xFF]
    return bytes(result)


def _parse_metadata(encrypted: bytes) -> NCMMetadata:
    if not encrypted:
        return NCMMetadata()
    try:
        decoded = bytes(byte ^ _METADATA_XOR for byte in encrypted)
        if not decoded.startswith(_METADATA_PREFIX):
            raise NCMFormatError("invalid NCM metadata prefix")
        encrypted_json = base64.b64decode(
            decoded[len(_METADATA_PREFIX) :], validate=True
        )
        plaintext = _decrypt_aes(encrypted_json, _METADATA_KEY)
        if not plaintext.startswith(_JSON_PREFIX):
            raise NCMFormatError("invalid NCM metadata JSON prefix")
        raw = json.loads(plaintext[len(_JSON_PREFIX) :].decode("utf-8"))
    except NCMError:
        raise
    except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise NCMFormatError("invalid NCM metadata") from exc
    if not isinstance(raw, dict):
        raise NCMFormatError("NCM metadata must be a JSON object")

    def optional_text(name: str) -> str | None:
        value = raw.get(name)
        if value is None:
            return None
        if not isinstance(value, str):
            raise NCMFormatError(f"NCM metadata {name} must be a string")
        return value or None

    artists = raw.get("artist", [])
    if artists is None:
        artists = []
    if not isinstance(artists, list) or any(
        not isinstance(item, (list, tuple)) or not item or not isinstance(item[0], str)
        for item in artists
    ):
        raise NCMFormatError("NCM metadata artist must be a list of [name, id] pairs")
    artist = "/".join(item[0] for item in artists if item[0]) or None
    return NCMMetadata(
        title=optional_text("musicName"),
        artist=artist,
        album=optional_text("album"),
        raw=raw,
    )


def _validate_audio(audio: bytes, declared_format: object) -> str:
    if audio.startswith(b"fLaC"):
        actual_format = "flac"
    elif audio.startswith(b"ID3") or (
        len(audio) >= 2
        and audio[0] == 0xFF
        and audio[1] & 0xE0 == 0xE0
        and audio[1] & 0x06
    ):
        actual_format = "mp3"
    else:
        raise UnsupportedAudioFormatError("decrypted payload is neither MP3 nor FLAC")
    if declared_format is not None:
        if not isinstance(declared_format, str):
            raise NCMFormatError("NCM metadata format must be a string")
        normalized = declared_format.lower()
        if normalized != actual_format:
            raise NCMFormatError(
                f"metadata format {declared_format!r} does not match {actual_format} payload"
            )
    return actual_format


def decode(ncm_path: str | os.PathLike[str]) -> DecodedTrack:
    """Decode one NCM file into memory; perform no writes or network access."""
    try:
        data = Path(ncm_path).read_bytes()
    except OSError as exc:
        raise NCMError(f"cannot read NCM input: {ncm_path}") from exc
    if not data.startswith(_MAGIC):
        raise NCMFormatError("missing CTENFDAM header")
    offset = len(_MAGIC)
    _, offset = _take(data, offset, 2, "header gap")
    key_length, offset = _read_u32(data, offset)
    encrypted_key, offset = _take(data, offset, key_length, "key field")
    encrypted_key = bytes(byte ^ _KEY_XOR for byte in encrypted_key)
    key_data = _decrypt_aes(encrypted_key, _CORE_KEY)
    if not key_data.startswith(_KEY_PREFIX):
        raise NCMFormatError("invalid NCM key prefix (core key did not decrypt)")
    audio_key = key_data[len(_KEY_PREFIX) :]
    _key_box(audio_key)

    metadata_length, offset = _read_u32(data, offset)
    encrypted_metadata, offset = _take(data, offset, metadata_length, "metadata field")
    metadata = _parse_metadata(encrypted_metadata)

    _, offset = _take(data, offset, 4, "CRC field")
    _, offset = _take(data, offset, 5, "image gap")
    cover_length, offset = _read_u32(data, offset)
    cover, offset = _take(data, offset, cover_length, "cover field")
    audio, _ = _take(data, offset, len(data) - offset, "audio payload")
    audio = _decrypt_audio(audio, audio_key)
    audio_format = _validate_audio(audio, metadata.raw.get("format"))
    return DecodedTrack(
        audio_bytes=audio,
        format=audio_format,
        metadata=metadata,
        cover=cover or None,
    )


def _cover_mime(cover: bytes) -> str:
    if cover.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if cover.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    return "application/octet-stream"


def _apply_ncm_tags(path: Path, track: DecodedTrack) -> None:
    audio = MutagenFile(path)
    if audio is None:
        raise UnsupportedAudioFormatError(f"mutagen cannot parse {track.format} output")
    if audio.tags is None:
        audio.add_tags()
    if track.format == "flac":
        if track.metadata.title is not None:
            audio["title"] = track.metadata.title
        if track.metadata.artist is not None:
            audio["artist"] = track.metadata.artist
        if track.metadata.album is not None:
            audio["album"] = track.metadata.album
        if track.cover:
            picture = Picture()
            picture.type = 3
            picture.mime = _cover_mime(track.cover)
            picture.data = track.cover
            audio.clear_pictures()
            audio.add_picture(picture)
    elif isinstance(audio.tags, ID3):
        if track.metadata.title is not None:
            audio.tags.delall("TIT2")
            audio.tags.add(TIT2(encoding=3, text=track.metadata.title))
        if track.metadata.artist is not None:
            audio.tags.delall("TPE1")
            audio.tags.add(TPE1(encoding=3, text=track.metadata.artist))
        if track.metadata.album is not None:
            audio.tags.delall("TALB")
            audio.tags.add(TALB(encoding=3, text=track.metadata.album))
        if track.cover:
            audio.tags.delall("APIC")
            audio.tags.add(
                APIC(
                    encoding=3,
                    mime=_cover_mime(track.cover),
                    type=3,
                    desc="Cover",
                    data=track.cover,
                )
            )
    else:
        raise UnsupportedAudioFormatError(f"unsupported tag format: {track.format}")
    audio.save()


def convert(track: DecodedTrack, output_path: str | os.PathLike[str]) -> Path:
    """Atomically write one decrypted track and restore NCM tags and cover art."""
    output = Path(output_path)
    if output.suffix.lower() != track.extension:
        raise ValueError(f"output extension must be {track.extension}")
    if output.exists():
        raise FileExistsError(f"refusing to overwrite existing output: {output}")
    if not output.parent.is_dir():
        raise FileNotFoundError(f"output directory does not exist: {output.parent}")
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", prefix=f".{output.name}.", dir=output.parent, delete=False
        ) as temporary:
            temporary_name = temporary.name
            temporary.write(track.audio_bytes)
        _apply_ncm_tags(Path(temporary_name), track)
        os.link(temporary_name, output)
    except Exception:
        if temporary_name is not None:
            Path(temporary_name).unlink(missing_ok=True)
        raise
    Path(temporary_name).unlink()
    return output


def convert_file(
    ncm_path: str | os.PathLike[str], output_path: str | os.PathLike[str] | None = None
) -> Path:
    """Decode and convert one file, refusing any output that aliases the input."""
    source = Path(ncm_path)
    track = decode(source)
    output = Path(output_path) if output_path is not None else source.with_suffix(track.extension)
    if output.absolute() == source.absolute():
        raise ValueError("output must be a new file, not the NCM source")
    return convert(track, output)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Losslessly decode one NCM file to MP3/FLAC")
    parser.add_argument("input", type=Path, help="source .ncm file (read-only)")
    parser.add_argument("output", type=Path, nargs="?", help="new .mp3 or .flac output")
    args = parser.parse_args(argv)
    try:
        output = convert_file(args.input, args.output)
    except (NCMError, OSError, ValueError) as exc:
        parser.exit(1, f"error: {exc}\n")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
