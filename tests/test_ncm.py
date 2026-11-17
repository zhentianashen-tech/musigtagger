from __future__ import annotations

import base64
import hashlib
import json
import struct
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from mutagen import File as MutagenFile

from musigtagger.ncm import (
    NCMFormatError,
    UnsupportedAudioFormatError,
    convert_file,
    decode,
    main,
)

CORE_KEY = b"hzHRAmso5kInbaxW"
METADATA_KEY = b"#14ljk_!\\]&0U<'("
COVER = b"\x89PNG\r\n\x1a\n" + b"synthetic-cover"
FLAC_STREAMINFO = (
    b"\x10\x00\x10\x00"
    + bytes(6)
    + ((44100 << 44) | (1 << 41) | (15 << 36)).to_bytes(8, "big")
    + bytes(16)
)
FLAC = b"fLaC" + b"\x80\x00\x00\x22" + FLAC_STREAMINFO
MP3_FRAME = b"\xff\xfb\x90\x64" + bytes(413)
MP3 = b"ID3\x04\x00\x00\x00\x00\x00\x00" + MP3_FRAME + MP3_FRAME


def encrypt_aes(data: bytes, key: bytes) -> bytes:
    padding = 16 - len(data) % 16
    encryptor = Cipher(algorithms.AES(key), modes.ECB()).encryptor()
    return encryptor.update(data + bytes([padding]) * padding) + encryptor.finalize()


def encrypt_audio(data: bytes, key: bytes) -> bytes:
    box = list(range(256))
    j = 0
    for i in range(256):
        j = (j + box[i] + key[i % len(key)]) & 0xFF
        box[i], box[j] = box[j], box[i]
    result = bytearray(data)
    for start in range(0, len(result), 32768):
        end = min(start + 32768, len(result))
        for index in range(start, end):
            j = (index - start + 1) & 0xFF
            result[index] ^= box[(box[j] + box[(box[j] + j) & 0xFF]) & 0xFF]
    return bytes(result)


def make_ncm(audio: bytes, audio_format: str, cover: bytes = COVER) -> bytes:
    key = b"synthetic-track-key"
    encrypted_key = bytes(
        byte ^ 0x64
        for byte in encrypt_aes(b"neteasecloudmusic" + key, CORE_KEY)
    )
    metadata = json.dumps(
        {
            "musicName": "Synthetic title",
            "artist": [["First artist", 1], ["Second artist", 2]],
            "album": "Synthetic album",
            "format": audio_format,
        }
    ).encode()
    encrypted_metadata = bytes(
        byte ^ 0x63
        for byte in b"163 key(Don't modify):"
        + base64.b64encode(encrypt_aes(b"music:" + metadata, METADATA_KEY))
    )
    return b"".join(
        [
            b"CTENFDAM\x00\x00",
            struct.pack("<I", len(encrypted_key)),
            encrypted_key,
            struct.pack("<I", len(encrypted_metadata)),
            encrypted_metadata,
            bytes(4),
            bytes(5),
            struct.pack("<I", len(cover)),
            cover,
            encrypt_audio(audio, key),
        ]
    )


class NCMDecodeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary_directory.name)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def write_fixture(self, name: str, audio: bytes, audio_format: str) -> Path:
        path = self.directory / name
        path.write_bytes(make_ncm(audio, audio_format))
        return path

    def test_flac_round_trip_preserves_source_and_restores_metadata(self) -> None:
        source = self.write_fixture("track.ncm", FLAC, "flac")
        before = hashlib.sha256(source.read_bytes()).digest()

        track = decode(source)
        output = convert_file(source)

        self.assertEqual(track.audio_bytes, FLAC)
        self.assertEqual(track.format, "flac")
        self.assertEqual(track.extension, ".flac")
        self.assertEqual(track.metadata.artist, "First artist/Second artist")
        self.assertEqual(track.cover, COVER)
        self.assertEqual(output, source.with_suffix(".flac"))
        self.assertEqual(hashlib.sha256(source.read_bytes()).digest(), before)
        tagged = MutagenFile(output)
        self.assertEqual(tagged["title"], ["Synthetic title"])
        self.assertEqual(tagged["artist"], ["First artist/Second artist"])
        self.assertEqual(tagged["album"], ["Synthetic album"])
        self.assertEqual(tagged.pictures[0].data, COVER)
        self.assertEqual(tagged.pictures[0].mime, "image/png")
        descriptor = track.track_descriptor(output)
        self.assertEqual(descriptor.title, "Synthetic title")
        self.assertEqual(descriptor.format, "flac")

    def test_mp3_round_trip_restores_id3_tags_and_cover(self) -> None:
        source = self.write_fixture("track.ncm", MP3, "mp3")
        output = convert_file(source, self.directory / "converted.mp3")

        self.assertEqual(decode(source).audio_bytes, MP3)
        tagged = MutagenFile(output)
        self.assertEqual(str(tagged["TIT2"]), "Synthetic title")
        self.assertEqual(str(tagged["TPE1"]), "First artist/Second artist")
        self.assertEqual(str(tagged["TALB"]), "Synthetic album")
        self.assertEqual(tagged["APIC:Cover"].data, COVER)

    def test_garbage_input_fails_cleanly_without_output(self) -> None:
        source = self.directory / "garbage.ncm"
        source.write_bytes(b"not an NCM file")
        with self.assertRaisesRegex(NCMFormatError, "CTENFDAM"):
            decode(source)
        self.assertFalse(source.with_suffix(".mp3").exists())
        self.assertFalse(source.with_suffix(".flac").exists())

    def test_truncated_input_fails_cleanly(self) -> None:
        source = self.write_fixture("truncated.ncm", FLAC, "flac")
        source.write_bytes(source.read_bytes()[:20])
        with self.assertRaises(NCMFormatError):
            decode(source)

    def test_non_audio_payload_is_rejected(self) -> None:
        source = self.write_fixture("unknown.ncm", b"plain text payload", "mp3")
        with self.assertRaises(UnsupportedAudioFormatError):
            decode(source)

    def test_declared_format_must_match_payload(self) -> None:
        source = self.write_fixture("mismatch.ncm", FLAC, "mp3")
        with self.assertRaisesRegex(NCMFormatError, "does not match"):
            decode(source)

    def test_existing_output_is_not_overwritten(self) -> None:
        source = self.write_fixture("track.ncm", FLAC, "flac")
        output = self.directory / "existing.flac"
        output.write_bytes(b"keep me")
        with self.assertRaises(FileExistsError):
            convert_file(source, output)
        self.assertEqual(output.read_bytes(), b"keep me")

    def test_cli_writes_default_output_and_reports_path(self) -> None:
        source = self.write_fixture("track.ncm", MP3, "mp3")
        stdout = StringIO()
        with redirect_stdout(stdout):
            result = main([str(source)])
        self.assertEqual(result, 0)
        self.assertEqual(stdout.getvalue().strip(), str(source.with_suffix(".mp3")))
        self.assertTrue(source.with_suffix(".mp3").is_file())


if __name__ == "__main__":
    unittest.main()
