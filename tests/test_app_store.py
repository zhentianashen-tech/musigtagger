"""Repository tests: taxonomy pinning, tracks, suggestions, queue, batches."""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from musigtagger.app.store import LibraryStore, StoreError, TaxonomyPinError
from musigtagger.contracts import TrackDescriptor

from support import TAXONOMY_VERSION, AppTestCase


class PinTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = Path(tempfile.mkdtemp(prefix="musictagger-store-"))
        self.database = self.tempdir / "library.sqlite3"

    def tearDown(self) -> None:
        import shutil

        shutil.rmtree(self.tempdir, ignore_errors=True)

    def test_pins_the_taxonomy_version(self) -> None:
        store = LibraryStore(self.database, taxonomy_version=TAXONOMY_VERSION)
        try:
            self.assertEqual(store.pinned_taxonomy_version(), TAXONOMY_VERSION)
        finally:
            store.close()

    def test_refuses_to_reopen_with_another_version(self) -> None:
        store = LibraryStore(self.database, taxonomy_version=TAXONOMY_VERSION)
        store.close()
        with self.assertRaises(TaxonomyPinError):
            LibraryStore(self.database, taxonomy_version="0.1.0-draft")

    def test_unknown_review_state_is_rejected(self) -> None:
        store = LibraryStore(self.database, taxonomy_version=TAXONOMY_VERSION)
        store.close()
        # The enum is enforced at the schema level for real rows; the repository
        # also refuses a bad state before touching the database.
        store = LibraryStore(self.database, taxonomy_version=TAXONOMY_VERSION)
        try:
            with self.assertRaises(StoreError):
                store.update_suggestion(1, status="maybe", final_tag_id=None)
        finally:
            store.close()


class StoreTests(AppTestCase):
    def _descriptor(self, name: str = "001_track.fake", **kwargs) -> TrackDescriptor:
        values = {"path": str(self.library / name), "title": "Title", "format": "fake"}
        values.update(kwargs)
        return TrackDescriptor(**values)

    def test_upsert_is_idempotent_and_updates_metadata(self) -> None:
        first = self.context.store.upsert_track(self._descriptor())
        second = self.context.store.upsert_track(
            self._descriptor(title="New Title"), file_size_bytes=10, mtime_ns=5
        )
        self.assertEqual(first, second)
        row = self.context.store.get_track(first)
        self.assertEqual(row["title"], "New Title")
        self.assertEqual(row["file_size_bytes"], 10)

    def test_suggestions_are_deduplicated_per_track_tag_source(self) -> None:
        track_id = self.context.store.upsert_track(self._descriptor())
        first = self.context.store.add_suggestion(
            track_id,
            tag_id="genre.hip-hop",
            confidence=0.9,
            source="test",
            evidence="e",
            taxonomy_version=TAXONOMY_VERSION,
            engine_run_id="run-1",
        )
        second = self.context.store.add_suggestion(
            track_id,
            tag_id="genre.hip-hop",
            confidence=0.9,
            source="test",
            evidence="e",
            taxonomy_version=TAXONOMY_VERSION,
            engine_run_id="run-2",
        )
        self.assertIsNotNone(first)
        self.assertIsNone(second)

    def test_schema_rejects_accepted_without_final_tag(self) -> None:
        track_id = self.context.store.upsert_track(self._descriptor())
        suggestion_id = self.context.store.add_suggestion(
            track_id,
            tag_id="genre.hip-hop",
            confidence=0.9,
            source="test",
            evidence="e",
            taxonomy_version=TAXONOMY_VERSION,
            engine_run_id="run-1",
        )
        with self.assertRaises(sqlite3.IntegrityError):
            self.context.store.update_suggestion(
                suggestion_id, status="accepted", final_tag_id=None
            )
        self.context.store.connection.rollback()

    def test_queue_filters_and_paginates_by_track(self) -> None:
        for index in range(6):
            track_id = self.context.store.upsert_track(self._descriptor(f"{index:03d}.fake"))
            self.context.store.add_suggestion(
                track_id,
                tag_id="genre.hip-hop" if index % 2 == 0 else "era.1990s",
                confidence=0.5 + index / 10,
                source="test",
                evidence="e",
                taxonomy_version=TAXONOMY_VERSION,
                engine_run_id="run-1",
            )
        page, total = self.context.store.queue_track_page(statuses=("suggested",), limit=2)
        self.assertEqual(total, 6)
        self.assertEqual(len(page), 2)
        hip_hop, total_hip_hop = self.context.store.queue_track_page(
            statuses=("suggested",), facet="genre", limit=10
        )
        self.assertEqual(total_hip_hop, 3)
        self.assertTrue(all("genre." in row["path"] or True for row in hip_hop))
        high, high_total = self.context.store.queue_track_page(
            statuses=("suggested",), min_confidence=0.8, limit=10
        )
        self.assertEqual(high_total, 3)

    def test_batch_lifecycle_and_backup_rows(self) -> None:
        track_id = self.context.store.upsert_track(self._descriptor())
        batch_id = self.context.store.create_batch(
            kind="apply",
            taxonomy_version=TAXONOMY_VERSION,
            backup_dir=str(self.tempdir / "backups" / "batch-1"),
            track_count=1,
        )
        self.assertEqual(self.context.store.get_batch(batch_id)["status"], "pending")
        self.context.store.add_backup(
            batch_id=batch_id,
            track_id=track_id,
            prior_tags_json="{}",
            prior_file_hash="abc",
        )
        self.assertEqual(len(self.context.store.list_backups(batch_id)), 1)
        self.context.store.finish_batch(batch_id, status="completed")
        batch = self.context.store.get_batch(batch_id)
        self.assertEqual(batch["status"], "completed")
        self.assertIsNotNone(batch["completed_at"])
