"""Finding 2: the engine wired into the app via app-layer adapters/factories.

The app's default scan path (``python -m musigtagger.app scan`` with no
``--scanner`` / ``--provider`` flags) must be wired to the engine: the engine
``LibraryScanner`` parses the library and the engine metadata provider yields a
non-empty review queue with genre/era suggestions. These tests run the default
wiring directly (network disabled, so they stay offline) and prove the single
CLI flow scan -> review -> apply -> undo works end to end.
"""

from __future__ import annotations

import hashlib
import shutil
import tempfile
import unittest
from pathlib import Path

from musigtagger.app.config import AppConfig
from musigtagger.app.factory import build_context
from musigtagger.app.ingest import EngineLibraryScannerAdapter, default_providers

from support import TAXONOMY_DIR, TAXONOMY_VERSION

try:  # pragma: no cover - depends on the environment
    import mutagen  # type: ignore[import-not-found]

    HAS_MUTAGEN = True
except ImportError:  # pragma: no cover - depends on the environment
    HAS_MUTAGEN = False


def _mp3_bytes() -> bytes:
    # Three MPEG-1 Layer III frames at 128 kbps / 44.1 kHz (417-byte frames).
    frame = b"\xff\xfb\x90\x00" + b"\x00" * (417 - 4)
    return frame * 3


def _tagged_mp3(path: Path, *, genre: str = "Hip-hop", year: str = "1994") -> None:
    path.write_bytes(_mp3_bytes())
    from mutagen.id3 import ID3, TCON, TDRC

    tags = ID3()
    tags.add(TCON(encoding=3, text=[genre]))
    tags.add(TDRC(encoding=3, text=[year]))
    tags.save(str(path))


@unittest.skipUnless(HAS_MUTAGEN, "mutagen is not installed in this runtime")
class EngineWiringTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = Path(tempfile.mkdtemp(prefix="musictagger-wiring-"))
        self.library = self.tempdir / "library"
        self.library.mkdir()

    def tearDown(self) -> None:
        shutil.rmtree(self.tempdir, ignore_errors=True)

    def _config(self) -> AppConfig:
        return AppConfig(
            library_root=self.library,
            database_path=self.tempdir / "library.sqlite3",
            backup_root=self.tempdir / "backups",
            events_path=self.tempdir / "events.jsonl",
            taxonomy_dir=TAXONOMY_DIR,
            taxonomy_version=TAXONOMY_VERSION,
            protected_roots=(),
            network_enabled=False,
        )

    def test_default_providers_map_to_the_engine_components(self) -> None:
        from musigtagger.contracts import TaxonomyLoader
        from musigtagger.db import apply_migrations, connect
        from musigtagger.engine import MetadataSuggestionProvider
        from musigtagger.engine.network import (
            MusicBrainzReleaseYearProvider,
        )

        taxonomy = TaxonomyLoader.load(TAXONOMY_DIR, version=TAXONOMY_VERSION)
        connection = connect(":memory:")
        try:
            apply_migrations(connection)
            local_only = default_providers(taxonomy, connection, include_network=False)
            self.assertEqual([name for name, _ in local_only], ["metadata"])
            self.assertIsInstance(local_only[0][1], MetadataSuggestionProvider)

            with_network = default_providers(
                taxonomy, connection, include_network=True, network_transport=object()
            )
            self.assertEqual(
                [name for name, _ in with_network], ["metadata", "network.musicbrainz"]
            )
            self.assertIsInstance(with_network[1][1], MusicBrainzReleaseYearProvider)
        finally:
            connection.close()

    def test_default_scan_produces_genre_and_era_suggestions(self) -> None:
        _tagged_mp3(self.library / "one.mp3")

        context = build_context(self._config(), run_id_factory=lambda: "run-wiring")
        try:
            # Default wiring resolves to the engine scanner adapter and the
            # engine metadata provider (no manual flags).
            self.assertIsInstance(context.ingestion.scanner, EngineLibraryScannerAdapter)

            report = context.ingestion.scan(self.library)
            self.assertEqual(report.indexed, 1)
            self.assertIn("metadata", report.providers)
            self.assertGreater(report.suggestions_new, 0)

            tag_ids = {
                row["tag_id"]
                for row in context.store.suggestions_with_status(("suggested",))
            }
            self.assertIn("genre.hip-hop", tag_ids)
            self.assertIn("era.1990s", tag_ids)
        finally:
            context.close()

    def test_default_path_apply_and_undo_are_byte_exact(self) -> None:
        path = self.library / "one.mp3"
        _tagged_mp3(path)
        original = path.read_bytes()

        # The fully-default wiring: engine scanner, engine providers, and the
        # real mutagen codec — nothing injected.
        context = build_context(self._config(), run_id_factory=lambda: "run-wiring")
        try:
            report = context.ingestion.scan(self.library)
            self.assertEqual(report.indexed, 1)
            self.assertGreater(report.suggestions_new, 0)

            track_ids = [int(row["id"]) for row in context.store.list_tracks(limit=10)]
            context.review.batch_accept(track_ids=track_ids)
            result = context.writer.apply()
            self.assertEqual(result.status, "completed", result.outcomes)

            undo = context.writer.undo(result.batch_id)
            self.assertEqual(undo.status, "completed", undo.outcomes)
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(
                hashlib.sha256(path.read_bytes()).hexdigest(),
                hashlib.sha256(original).hexdigest(),
            )
        finally:
            context.close()
