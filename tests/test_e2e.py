"""End-to-end: scan -> review -> apply -> undo on a local library.

Uses the fake tag codec (the real mutagen path has its own gated test), so this
test can run offline anywhere: what it proves is the application workflow and
the safety invariants — every batch backed up, per-track isolation, and undo
returning the exact original bytes for a 100+-track batch.
"""

from __future__ import annotations

import json
from pathlib import Path

from musigtagger.app.util import sha256_file

from support import AppTestCase, make_library

TRACK_COUNT = 120


class EndToEndTests(AppTestCase):
    page_size = 25

    def test_full_workflow_on_a_large_batch(self) -> None:
        self.library.mkdir(parents=True, exist_ok=True)
        paths = make_library(self.library, TRACK_COUNT)
        originals = {path: path.read_bytes() for path in paths}
        original_hashes = {path: sha256_file(path) for path in paths}

        report = self.scan()
        self.assertEqual(report.indexed, TRACK_COUNT)
        self.assertEqual(report.suggestions_new, TRACK_COUNT * 2)

        track_ids = self.all_track_ids()
        self.assertEqual(len(track_ids), TRACK_COUNT)
        accepted = self.context.review.batch_accept(track_ids=track_ids)
        self.assertEqual(accepted, TRACK_COUNT * 2)

        result = self.context.writer.apply()
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.succeeded, TRACK_COUNT)
        self.assertEqual(result.failures, ())

        backups = self.context.store.list_backups(result.batch_id)
        self.assertEqual(len(backups), TRACK_COUNT)
        for row in backups:
            payload = json.loads(row["prior_tags_json"])
            sidecar = self.config.backup_root / payload["sidecar"]
            track_path = Path(self.context.store.get_track(int(row["track_id"]))["path"])
            self.assertEqual(sidecar.read_bytes(), originals[track_path])
            self.assertEqual(payload["sha256"], original_hashes[track_path])

        applied = self.context.store.suggestions_with_status(("applied",))
        self.assertEqual(len(applied), TRACK_COUNT * 2)

        undo = self.context.writer.undo(result.batch_id)
        self.assertEqual(undo.status, "completed")
        for path in paths:
            self.assertEqual(sha256_file(path), original_hashes[path])
            self.assertEqual(path.read_bytes(), originals[path])

        self.assertEqual(self.context.store.suggestions_with_status(("applied",)), [])
        self.assertEqual(self.context.store.get_batch(result.batch_id)["status"], "undone")

        # Event stream: complete suggestion + review-outcome coverage.
        events = self.events()
        suggestions = [event for event in events if event["event"] == "suggestion"]
        outcomes = [event for event in events if event["event"] == "review_outcome"]
        self.assertEqual(len(suggestions), TRACK_COUNT * 2)
        applied_events = [event for event in outcomes if event["to_status"] == "applied"]
        self.assertEqual(len(applied_events), TRACK_COUNT * 2)
        self.assertTrue(all(event["actor"] == "local-user" for event in applied_events))

        # The read-only source root was never touched.
        self.assertEqual(list(self.source.iterdir()), [])
