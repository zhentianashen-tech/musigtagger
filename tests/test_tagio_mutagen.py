"""Real-container tag I/O with mutagen (skipped when mutagen is unavailable).

These tests build tiny but structurally valid MP3 and FLAC files in a temporary
directory, write real ID3/Vorbis tags with :class:`MutagenTagger`, and run the
full apply → undo cycle through the write path. They are the executable form of
the "byte-equivalent restore" acceptance bar for actual tag frames.

``mutagen`` is a runtime dependency, not a test dependency: in a runtime without
it these tests skip with an explicit message rather than failing.
"""

from __future__ import annotations

import hashlib
import struct
import tempfile
import unittest
from pathlib import Path

from musigtagger.app.config import AppConfig
from musigtagger.app.factory import build_context
from musigtagger.app.ingest import ScanItem
from musigtagger.app.tagio import MutagenTagger
from musigtagger.app.tagmap import normalise_fields
from musigtagger.contracts import TrackDescriptor

from support import StubProvider, TAXONOMY_DIR, TAXONOMY_VERSION

try:  # pragma: no cover - depends on the environment
    import mutagen  # type: ignore[import-not-found]

    HAS_MUTAGEN = True
except ImportError:  # pragma: no cover - depends on the environment
    HAS_MUTAGEN = False


def _mp3_bytes() -> bytes:
    # Three MPEG-1 Layer III frames at 128 kbps / 44.1 kHz (417-byte frames).
    frame = b"\xff\xfb\x90\x00" + b"\x00" * (417 - 4)
    return frame * 3


def _flac_bytes() -> bytes:
    streaminfo = (
        struct.pack(">HH", 4096, 4096)
        + b"\x00" * 6
        + (
            (44100 << 44) | ((2 - 1) << 41) | ((16 - 1) << 36) | 44100
        ).to_bytes(8, "big")
        + b"\x00" * 16
    )
    header = bytes([0x80]) + len(streaminfo).to_bytes(3, "big")
    return b"fLaC" + header + streaminfo


class FixtureScanner:
    def __init__(self, formats: dict[str, str]) -> None:
        self.formats = formats

    def scan(self, root: Path):
        for path in sorted(Path(root).iterdir()):
            if not path.is_file() or path.name.startswith("."):
                continue
            format_name = self.formats.get(path.suffix.lower())
            if format_name is None:
                yield ScanItem(path=path, error="not a fixture")
                continue
            yield ScanItem(
                path=path,
                descriptor=TrackDescriptor(
                    path=str(path), title=path.stem, format=format_name
                ),
                file_size_bytes=path.stat().st_size,
                mtime_ns=path.stat().st_mtime_ns,
            )


@unittest.skipUnless(HAS_MUTAGEN, "mutagen is not installed in this runtime")
class MutagenTaggerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = Path(tempfile.mkdtemp(prefix="musictagger-mutagen-"))
        self.mp3 = self.tempdir / "one.mp3"
        self.mp3.write_bytes(_mp3_bytes())
        self.flac = self.tempdir / "two.flac"
        self.flac.write_bytes(_flac_bytes())
        try:
            for path in (self.mp3, self.flac):
                if mutagen.File(str(path)) is None:
                    self.skipTest(f"mutagen cannot parse the synthesized {path.suffix}")
        except Exception as exc:  # noqa: BLE001 - fixture limitation, not a defect
            self.skipTest(f"synthesized audio fixtures are unusable here: {exc}")
        self.tagger = MutagenTagger()

    def tearDown(self) -> None:
        import shutil

        shutil.rmtree(self.tempdir, ignore_errors=True)

    def test_id3_round_trip_and_managed_field_replacement(self) -> None:
        self.tagger.write(
            self.mp3, {"TCON": ["Hip-hop"], "TXXX:ERA": ["1990s"]}
        )
        self.assertEqual(
            normalise_fields(self.tagger.read(self.mp3), family="id3"),
            normalise_fields(
                {"TCON": ["Hip-hop"], "TXXX:ERA": ["1990s"]}, family="id3"
            ),
        )
        # Rewriting replaces, never duplicates, the application-owned fields.
        self.tagger.write(self.mp3, {"TCON": ["Jazz"], "TXXX:ERA": ["2000s"]})
        self.assertEqual(
            normalise_fields(self.tagger.read(self.mp3), family="id3")["TCON"],
            ["Jazz"],
        )
        self.assertEqual(
            normalise_fields(self.tagger.read(self.mp3), family="id3")["TXXX:ERA"],
            ["2000s"],
        )
        self.assertEqual(self.tagger.probe(self.mp3).format, "mp3")

    def test_vorbis_round_trip(self) -> None:
        self.tagger.write(
            self.flac, {"GENRE": ["Hip-hop"], "ERA": ["1990s"]}
        )
        read = normalise_fields(self.tagger.read(self.flac), family="vorbis")
        self.assertEqual(read["GENRE"], ["Hip-hop"])
        self.assertEqual(read["ERA"], ["1990s"])
        self.assertEqual(self.tagger.probe(self.flac).format, "flac")

    def test_mp3_via_default_scanner_reports_mp3_and_undo_is_byte_exact(self) -> None:
        # MUSI-15 finding 1: the bundled stopgap scanner reads ``easy=True``, so
        # an MP3 descriptor used to come back with ``format='easymp3'`` and the
        # write path refused it. This exercises the *default* scan path (the
        # bundled MutagenScanner, not a hand-written fixture scanner) and proves
        # the MP3 is writable and that undo restores the exact original bytes.
        from musigtagger.app.ingest import MutagenScanner

        context = build_context(
            AppConfig(
                library_root=self.tempdir,
                database_path=self.tempdir / "library.sqlite3",
                backup_root=self.tempdir / "backups",
                events_path=self.tempdir / "events.jsonl",
                taxonomy_dir=TAXONOMY_DIR,
                taxonomy_version=TAXONOMY_VERSION,
                protected_roots=(),
            ),
            codec=self.tagger,
            scanner=MutagenScanner(),
            providers=[("test.stub", StubProvider())],
            run_id_factory=lambda: "run-default-scanner",
        )
        try:
            original = self.mp3.read_bytes()
            report = context.ingestion.scan(self.tempdir)
            self.assertEqual(report.indexed, 2)  # mp3 + flac both parsed
            formats = {
                Path(row["path"]).suffix: row["format"]
                for row in context.store.list_tracks(limit=10)
            }
            self.assertEqual(formats[".mp3"], "mp3")
            self.assertEqual(formats[".flac"], "flac")

            track_ids = [int(row["id"]) for row in context.store.list_tracks(limit=10)]
            context.review.batch_accept(track_ids=track_ids)
            result = context.writer.apply()
            self.assertEqual(result.status, "completed", result.outcomes)
            self.assertIn("Hip-hop", str(self.tagger.read(self.mp3)))

            undo = context.writer.undo(result.batch_id)
            self.assertEqual(undo.status, "completed", undo.outcomes)
            self.assertEqual(self.mp3.read_bytes(), original)
            self.assertEqual(
                hashlib.sha256(self.mp3.read_bytes()).hexdigest(),
                hashlib.sha256(original).hexdigest(),
            )
        finally:
            context.close()

    def test_apply_then_undo_restores_the_original_bytes(self) -> None:
        context = build_context(
            AppConfig(
                library_root=self.tempdir,
                database_path=self.tempdir / "library.sqlite3",
                backup_root=self.tempdir / "backups",
                events_path=self.tempdir / "events.jsonl",
                taxonomy_dir=TAXONOMY_DIR,
                taxonomy_version=TAXONOMY_VERSION,
                protected_roots=(),
            ),
            codec=self.tagger,
            scanner=FixtureScanner({".mp3": "mp3", ".flac": "flac"}),
            providers=[("test.stub", StubProvider())],
            run_id_factory=lambda: "run-mutagen",
        )
        try:
            originals = {
                path: path.read_bytes() for path in (self.mp3, self.flac)
            }
            report = context.ingestion.scan(self.tempdir)
            self.assertEqual(report.indexed, 2)
            track_ids = [int(row["id"]) for row in context.store.list_tracks(limit=10)]
            context.review.batch_accept(track_ids=track_ids)
            result = context.writer.apply()
            self.assertEqual(result.status, "completed", result.outcomes)
            for path in (self.mp3, self.flac):
                read = self.tagger.read(path)
                self.assertIn("Hip-hop", str(read))
            undo = context.writer.undo(result.batch_id)
            self.assertEqual(undo.status, "completed", undo.outcomes)
            for path, original in originals.items():
                self.assertEqual(path.read_bytes(), original)
                self.assertEqual(
                    hashlib.sha256(path.read_bytes()).hexdigest(),
                    hashlib.sha256(original).hexdigest(),
                )
        finally:
            context.close()
