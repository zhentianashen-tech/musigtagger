from __future__ import annotations

import sys
import tempfile
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

try:
    import mutagen  # noqa: F401
except ModuleNotFoundError:
    # Scanner tests replace File below; keep the rest of the stdlib suite usable
    # in offline contract-development environments before dependencies install.
    sys.modules["mutagen"] = types.SimpleNamespace(File=None)

from musigtagger.contracts import TrackDescriptor
from musigtagger.db import initialize_database
from musigtagger.engine import LibraryScanner
from musigtagger.ncm import DecodedTrack, NCMMetadata


def audio(tags: dict[str, list[str]] | None, length: float = 123.4):
    return SimpleNamespace(tags=tags, info=SimpleNamespace(length=length))


class LibraryScannerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.connection = initialize_database(":memory:")
        self.scanner = LibraryScanner(self.connection)

    def tearDown(self) -> None:
        self.connection.close()
        self.tempdir.cleanup()

    def make_file(self, relative: str, content: bytes = b"audio") -> Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path

    def test_full_date_formats_parse_to_release_year(self) -> None:
        # Operator requirement (2026-11-17): a date present in any local source
        # must surface. TDRC carries full dates; every accepted format must
        # yield the release year the provider needs for era suggestions.
        from musigtagger.engine.scanner import _parse_year

        for raw in ("1994", "1994-05", "1994-05-01", "1994-05-01T12:34:56"):
            with self.subTest(raw=raw):
                self.assertEqual(_parse_year(raw), 1994)
        for bad in (None, "", "not-a-year", "19423", "abc19945", "94"):
            with self.subTest(bad=bad):
                self.assertIsNone(_parse_year(bad))

    def test_mixed_batch_skips_malformed_track_and_upserts_the_rest(self) -> None:
        for suffix in ("mp3", "flac", "ogg"):
            self.make_file(f"good.{suffix}")
        self.make_file("broken.mp3")
        self.make_file("notes.txt")

        def read(path, easy):
            self.assertTrue(easy)
            if Path(path).name == "broken.mp3":
                raise ValueError("bad frame")
            return audio(
                {
                    "title": ["Title"],
                    "artist": ["Artist"],
                    "album": ["Album"],
                    "genre": ["Hip Hop"],
                    "date": ["1994-05-01"],
                }
            )

        with patch("musigtagger.engine.scanner.mutagen.File", side_effect=read):
            with self.assertLogs("musigtagger.engine.scanner", level="WARNING") as logs:
                result = self.scanner.scan_directory(self.root)

        self.assertTrue(result.completed)
        self.assertEqual(result.discovered_audio_files, 4)
        self.assertEqual(len(result.tracks), 3)
        self.assertEqual(len(result.failures), 1)
        self.assertIn("bad frame", result.failures[0].reason)
        self.assertIn("broken.mp3", "\n".join(logs.output))
        track = result.tracks[0]
        self.assertEqual(track.title, "Title")
        self.assertEqual(track.year, 1994)
        self.assertEqual(track.duration_seconds, 123.4)
        self.assertEqual(
            self.connection.execute("SELECT COUNT(*) FROM tracks").fetchone()[0], 3
        )

    def test_incremental_rescan_updates_existing_row_without_duplicates(self) -> None:
        path = self.make_file("track.flac")
        with patch(
            "musigtagger.engine.scanner.mutagen.File",
            return_value=audio({"title": ["Before"], "genre": ["Rock"]}),
        ):
            self.scanner.scan_directory(self.root)
        row = self.connection.execute("SELECT * FROM tracks").fetchone()
        track_id, created_at = row["id"], row["created_at"]

        path.write_bytes(b"changed and larger")
        with patch(
            "musigtagger.engine.scanner.mutagen.File",
            return_value=audio({"title": ["After"], "genre": ["Jazz"]}),
        ):
            result = self.scanner.scan_directory(self.root)

        self.assertEqual(len(result.tracks), 1)
        rows = self.connection.execute("SELECT * FROM tracks").fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], track_id)
        self.assertEqual(rows[0]["created_at"], created_at)
        self.assertEqual(rows[0]["title"], "After")
        self.assertEqual(rows[0]["genre"], "Jazz")
        self.assertEqual(rows[0]["file_size_bytes"], path.stat().st_size)

    def test_unidentified_and_invalid_metadata_are_isolated(self) -> None:
        self.make_file("unknown.ogg")
        self.make_file("invalid.flac")

        def read(path, easy):
            if Path(path).suffix == ".ogg":
                return None
            return audio({"date": ["not-a-year"]}, length=float("nan"))

        with patch("musigtagger.engine.scanner.mutagen.File", side_effect=read):
            result = self.scanner.scan_directory(self.root)

        self.assertEqual(len(result.tracks), 0)
        self.assertEqual(len(result.failures), 2)

    def test_ncm_is_converted_in_temporary_storage_and_keeps_source_path(self) -> None:
        source = self.make_file("track.ncm", b"encrypted")

        def convert(track, destination_path):
            Path(destination_path).write_bytes(track.audio_bytes)

        decoded = DecodedTrack(
            audio_bytes=b"decoded", format="mp3", metadata=NCMMetadata()
        )
        descriptor = TrackDescriptor(path="temporary", title="Title", format="mp3")
        with (
            patch("musigtagger.engine.scanner.decode", return_value=decoded),
            patch("musigtagger.engine.scanner.convert", side_effect=convert),
            patch("musigtagger.engine.scanner.parse_audio_file", return_value=(descriptor, 7, 8)),
        ):
            result = self.scanner.scan_directory(self.root)

        self.assertEqual(len(result.tracks), 1)
        self.assertEqual(result.tracks[0].path, str(source.resolve()))
        self.assertEqual(result.tracks[0].format, "mp3")

    def test_missing_directory_is_a_batch_configuration_error(self) -> None:
        with self.assertRaises(ValueError):
            self.scanner.scan_directory(self.root / "missing")


if __name__ == "__main__":
    unittest.main()
