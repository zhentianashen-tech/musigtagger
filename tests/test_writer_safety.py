"""The write path's safety properties: backups first, per-track isolation,
verification, rollback, and byte-exact undo."""

from __future__ import annotations

import json
from pathlib import Path

from musigtagger.app.config import ProtectedPathError
from musigtagger.app.tagmap import normalise_fields
from musigtagger.app.util import sha256_file
from musigtagger.app.writer import NothingToApplyError, WriteError
from musigtagger.contracts import TrackDescriptor, UnknownTagError

from support import AppTestCase, make_library


class WritePathTests(AppTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.library.mkdir(parents=True, exist_ok=True)
        self.paths = make_library(self.library, 3)
        self.scan()
        self.originals = {path: path.read_bytes() for path in self.paths}
        self.context.review.batch_accept(track_ids=self.all_track_ids())

    def _applied_fields(self) -> dict[str, list[str]]:
        projection = {
            "TCON": ["Hip-hop"],
            "TXXX:ERA": ["1990s"],
        }
        return normalise_fields(projection, family="id3")

    def test_apply_writes_reviewed_tags_and_records_backups(self) -> None:
        result = self.context.writer.apply()
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.succeeded, 3)
        self.assertEqual(len(result.failures), 0)
        expected = self._applied_fields()
        for path in self.paths:
            self.assertEqual(
                normalise_fields(self.tagger.read(path), family="id3"), expected
            )
            self.assertNotEqual(path.read_bytes(), self.originals[path])
        backups = self.context.store.list_backups(result.batch_id)
        self.assertEqual(len(backups), 3)
        for row in backups:
            payload = json.loads(row["prior_tags_json"])
            sidecar = self.config.backup_root / payload["sidecar"]
            track_path = Path(self.context.store.get_track(int(row["track_id"]))["path"])
            self.assertEqual(sidecar.read_bytes(), self.originals[track_path])
        batch = self.context.store.get_batch(result.batch_id)
        self.assertEqual(batch["status"], "completed")
        self.assertIsNotNone(batch["completed_at"])
        applied = self.context.store.suggestions_with_status(("applied",))
        self.assertEqual(len(applied), 6)
        self.assertTrue(all(row["applied_at"] for row in applied))

    def test_no_reviewed_tags_means_no_batch(self) -> None:
        self.context.store.connection.execute("DELETE FROM suggestions")
        self.context.store.connection.commit()
        with self.assertRaises(NothingToApplyError):
            self.context.writer.apply()
        self.assertEqual(self.context.store.list_batches(), [])

    def test_one_failing_track_does_not_abort_the_batch(self) -> None:
        broken = str(self.paths[1])
        self.tagger.write_error_on.add(broken)
        result = self.context.writer.apply()
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.succeeded, 2)
        self.assertEqual(len(result.failures), 1)
        self.assertEqual(result.failures[0].path, broken)
        self.assertIn("simulated write failure", result.failures[0].error)
        # The failed file is untouched and its backup is kept.
        self.assertEqual(Path(broken).read_bytes(), self.originals[self.paths[1]])
        self.assertIsNotNone(
            self.context.store.get_backup(
                result.batch_id,
                int(self.context.store.get_track_by_path(broken)["id"]),
            )
        )
        # The other two tracks were written.
        for index in (0, 2):
            self.assertEqual(
                normalise_fields(self.tagger.read(self.paths[index]), family="id3"),
                self._applied_fields(),
            )

    def test_retry_writes_the_remaining_tracks(self) -> None:
        broken = str(self.paths[1])
        self.tagger.write_error_on.add(broken)
        first = self.context.writer.apply()
        self.assertEqual(first.status, "failed")
        self.tagger.write_error_on.clear()
        retried = self.context.writer.retry(first.batch_id)
        self.assertEqual(retried.status, "completed")
        self.assertEqual(retried.succeeded, 1)
        self.assertEqual(
            normalise_fields(self.tagger.read(broken), family="id3"),
            self._applied_fields(),
        )

    def test_post_write_verification_failure_rolls_the_track_back(self) -> None:
        corrupt = str(self.paths[0])
        self.tagger.corrupt_on.add(corrupt)
        result = self.context.writer.apply()
        self.assertEqual(result.status, "failed")
        self.assertEqual(len(result.failures), 1)
        self.assertIn(corrupt, [outcome.path for outcome in result.failures])
        # The corrupt write was detected and the backup put back byte-for-byte.
        self.assertEqual(Path(corrupt).read_bytes(), self.originals[self.paths[0]])
        # The other tracks still completed.
        self.assertEqual(result.succeeded, 2)

    def test_unknown_tag_aborts_before_any_write(self) -> None:
        row = self.context.store.suggestions_with_status(("accepted",))[0]
        self.context.store.update_suggestion(
            int(row["id"]),
            status="accepted",
            final_tag_id="genre.not-in-taxonomy",
            reviewed_at="2026-11-17T00:00:00.000Z",
        )
        with self.assertRaises(UnknownTagError):
            self.context.writer.apply()
        self.assertEqual(self.context.store.list_batches(), [])
        for path in self.paths:
            self.assertEqual(path.read_bytes(), self.originals[path])

    def test_protected_root_write_is_refused(self) -> None:
        source_file = self.source / "source.fake"
        source_file.write_bytes(b"source bytes")
        track_id = self.context.store.upsert_track(
            TrackDescriptor(path=str(source_file), title="source", format="mp3")
        )
        self.context.store.add_suggestion(
            track_id,
            tag_id="genre.hip-hop",
            confidence=0.9,
            source="test.stub",
            evidence="e",
            taxonomy_version=self.context.taxonomy.version,
            engine_run_id="run-test",
        )
        suggestion = self.context.store.suggestions_for_track(track_id)[0]
        self.context.store.update_suggestion(
            int(suggestion["id"]),
            status="accepted",
            final_tag_id="genre.hip-hop",
            reviewed_at="2026-11-17T00:00:00.000Z",
        )
        with self.assertRaises(ProtectedPathError):
            self.context.writer.apply()
        self.assertEqual(source_file.read_bytes(), b"source bytes")
        failed_batches = self.context.store.list_batches()
        self.assertEqual(len(failed_batches), 1)
        self.assertEqual(failed_batches[0]["status"], "failed")

    def test_undo_restores_the_exact_bytes_and_reverts_review_state(self) -> None:
        result = self.context.writer.apply()
        self.assertEqual(result.status, "completed")
        undo = self.context.writer.undo(result.batch_id)
        self.assertEqual(undo.status, "completed")
        for path in self.paths:
            self.assertEqual(sha256_file(path), sha256_of_bytes(self.originals[path]))
            self.assertEqual(path.read_bytes(), self.originals[path])
        self.assertEqual(self.context.store.get_batch(result.batch_id)["status"], "undone")
        self.assertEqual(self.context.store.suggestions_with_status(("applied",)), [])
        reverted = self.context.store.suggestions_with_status(("accepted",))
        self.assertEqual(len(reverted), 6)
        self.assertTrue(all(row["applied_at"] is None for row in reverted))
        restored = [
            row
            for row in self.context.store.list_backups(result.batch_id)
            if row["restored_at"] is not None
        ]
        self.assertEqual(len(restored), 3)
        # The undo itself was a backed-up batch.
        undo_backups = self.context.store.list_backups(undo.batch_id)
        self.assertEqual(len(undo_backups), 3)

    def test_undo_twice_is_refused(self) -> None:
        result = self.context.writer.apply()
        self.context.writer.undo(result.batch_id)
        with self.assertRaises(WriteError):
            self.context.writer.undo(result.batch_id)

    def test_apply_preserves_file_permissions(self) -> None:
        import os
        import stat

        os.chmod(self.paths[0], 0o640)
        self.context.writer.apply()
        self.assertEqual(stat.S_IMODE(os.stat(self.paths[0]).st_mode), 0o640)

    def test_applying_a_later_suggestion_preserves_earlier_facets(self) -> None:
        first = self.context.writer.apply()
        self.assertEqual(first.status, "completed")
        track_id = int(
            self.context.store.get_track_by_path(str(self.paths[0]))["id"]
        )
        extra_id = self.context.store.add_suggestion(
            track_id,
            tag_id="mood.calm",
            confidence=0.8,
            source="test.later",
            evidence="later suggestion",
            taxonomy_version=self.context.taxonomy.version,
            engine_run_id="run-2",
        )
        self.context.review.accept(extra_id)
        second = self.context.writer.apply(track_ids=[track_id])
        self.assertEqual(second.status, "completed")
        fields = normalise_fields(self.tagger.read(self.paths[0]), family="id3")
        self.assertEqual(fields["TCON"], ["Hip-hop"])
        self.assertEqual(fields["TXXX:ERA"], ["1990s"])
        self.assertEqual(fields["TXXX:MOOD"], ["Calm"])

        undo = self.context.writer.undo(second.batch_id)
        self.assertEqual(undo.status, "completed")
        fields = normalise_fields(self.tagger.read(self.paths[0]), family="id3")
        self.assertEqual(fields["TXXX:MOOD"], [])
        self.assertEqual(fields["TCON"], ["Hip-hop"])
        self.assertEqual(fields["TXXX:ERA"], ["1990s"])
        # Undo reverted only the later batch's suggestion.
        self.assertEqual(
            self.context.store.get_suggestion(extra_id)["status"], "accepted"
        )
        self.assertEqual(len(self.context.store.suggestions_with_status(("applied",))), 6)
        self.assertEqual(
            self.context.store.get_batch(first.batch_id)["status"], "completed"
        )

    def test_undo_after_partial_failure_restores_what_completed(self) -> None:
        broken = str(self.paths[2])
        self.tagger.write_error_on.add(broken)
        result = self.context.writer.apply()
        self.assertEqual(result.status, "failed")
        self.assertEqual(Path(broken).read_bytes(), self.originals[self.paths[2]])
        undo = self.context.writer.undo(result.batch_id)
        self.assertEqual(undo.status, "completed")
        for path in self.paths:
            self.assertEqual(path.read_bytes(), self.originals[path])


def sha256_of_bytes(data: bytes) -> str:
    import hashlib

    return hashlib.sha256(data).hexdigest()
