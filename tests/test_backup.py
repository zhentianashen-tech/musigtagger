"""Mandatory backups and byte-exact restore."""

from __future__ import annotations

import json
from pathlib import Path

from musigtagger.app.backup import (
    BackupError,
    BackupIntegrityError,
    BackupManager,
)
from musigtagger.app.config import ProtectedPathError
from musigtagger.app.util import sha256_file

from support import AppTestCase, make_library


class BackupTests(AppTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.library.mkdir(parents=True, exist_ok=True)
        self.paths = make_library(self.library, 2)
        self.scan()
        self.tracks = self.context.store.list_tracks(limit=10)
        self.batch_id = self.context.store.create_batch(
            kind="apply",
            taxonomy_version=self.context.taxonomy.version,
            backup_dir=None,
            track_count=len(self.tracks),
        )
        self.backups = BackupManager(
            self.config, self.context.store, self.tagger
        )

    def test_budgets_prior_state_for_every_track(self) -> None:
        records = self.backups.prepare_batch(self.batch_id, self.tracks)
        self.assertEqual(len(records), len(self.tracks))
        for record in records:
            self.assertTrue(record.sidecar_path.is_file())
            self.assertEqual(sha256_file(record.sidecar_path), record.sha256)
            self.assertEqual(
                record.sidecar_path.read_bytes(), Path(record.track_path).read_bytes()
            )
            row = self.context.store.get_backup(self.batch_id, record.track_id)
            self.assertIsNotNone(row)
            self.assertEqual(row["prior_file_hash"], record.sha256)
            payload = json.loads(row["prior_tags_json"])
            self.assertEqual(payload["schema"], "musigtagger.backup.v1")
            self.assertEqual(payload["sha256"], record.sha256)
            self.assertEqual(payload["format"], "mp3")
            self.assertIn("sidecar", payload)

    def test_restore_returns_the_exact_bytes(self) -> None:
        records = self.backups.prepare_batch(self.batch_id, self.tracks)
        record = records[0]
        original = Path(record.track_path).read_bytes()
        Path(record.track_path).write_bytes(b"completely different content")
        self.backups.restore(record)
        self.assertEqual(Path(record.track_path).read_bytes(), original)
        self.assertEqual(sha256_file(record.track_path), record.sha256)

    def test_corrupt_backup_is_refused_and_target_untouched(self) -> None:
        records = self.backups.prepare_batch(self.batch_id, self.tracks)
        record = records[0]
        current = b"current valid content"
        Path(record.track_path).write_bytes(current)
        record.sidecar_path.write_bytes(b"bit rot")
        with self.assertRaises(BackupIntegrityError):
            self.backups.restore(record)
        self.assertEqual(Path(record.track_path).read_bytes(), current)

    def test_missing_target_is_reported_before_any_backup_is_trusted(self) -> None:
        Path(self.paths[1]).unlink()
        with self.assertRaises(BackupError):
            self.backups.prepare_batch(self.batch_id, self.tracks)

    def test_protected_source_root_is_never_backed_up(self) -> None:
        source_file = self.source / "readonly.fake"
        source_file.write_bytes(b"source bytes")
        path = str(source_file)
        track_id = self.context.store.upsert_track(
            _descriptor(path), file_size_bytes=12, mtime_ns=1
        )
        track = self.context.store.get_track(track_id)
        with self.assertRaises(ProtectedPathError):
            self.backups.prepare_batch(self.batch_id, [track])
        self.assertFalse(self.context.store.get_backup(self.batch_id, track_id))
        self.assertEqual(source_file.read_bytes(), b"source bytes")


def _descriptor(path: str):
    from musigtagger.contracts import TrackDescriptor

    return TrackDescriptor(path=path, title="readonly", format="mp3")
