"""Review state machine, taxonomy validation, and review-outcome events."""

from __future__ import annotations

from musigtagger.app.review import ReviewError

from support import AppTestCase


class ReviewTests(AppTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.library.mkdir(parents=True, exist_ok=True)
        from support import make_library

        make_library(self.library, 2)
        self.scan()

    def _suggestion(self, tag_id: str = "genre.hip-hop"):
        for row in self.suggestion_rows("suggested"):
            if row["tag_id"] == tag_id:
                return row
        raise AssertionError(f"no suggested row for {tag_id}")

    def test_accept_keeps_the_proposed_tag(self) -> None:
        row = self._suggestion()
        updated = self.context.review.accept(int(row["id"]))
        self.assertEqual(updated["status"], "accepted")
        self.assertEqual(updated["final_tag_id"], row["tag_id"])
        self.assertIsNotNone(updated["reviewed_at"])
        events = [event for event in self.events() if event["event"] == "review_outcome"]
        self.assertEqual(events[-1]["to_status"], "accepted")
        self.assertEqual(events[-1]["suggestion_id"], int(row["id"]))
        self.assertEqual(events[-1]["event_version"], 1)

    def test_edit_replaces_the_tag_inside_the_facet(self) -> None:
        row = self._suggestion()
        self.assertEqual(row["tag_id"], "genre.hip-hop")
        updated = self.context.review.edit(int(row["id"]), "genre.jazz")
        self.assertEqual(updated["status"], "edited")
        self.assertEqual(updated["final_tag_id"], "genre.jazz")
        self.assertEqual(updated["tag_id"], "genre.hip-hop")

    def test_edit_across_facets_is_refused(self) -> None:
        row = self._suggestion()
        with self.assertRaises(ReviewError):
            self.context.review.edit(int(row["id"]), "era.1990s")

    def test_edit_to_unknown_tag_is_refused(self) -> None:
        row = self._suggestion()
        with self.assertRaises(Exception):
            self.context.review.edit(int(row["id"]), "genre.not-a-real-tag")

    def test_reject_clears_the_effective_tag(self) -> None:
        row = self._suggestion()
        updated = self.context.review.reject(int(row["id"]))
        self.assertEqual(updated["status"], "rejected")
        self.assertIsNone(updated["final_tag_id"])

    def test_rejected_is_terminal(self) -> None:
        row = self._suggestion()
        self.context.review.reject(int(row["id"]))
        with self.assertRaises(ReviewError):
            self.context.review.accept(int(row["id"]))

    def test_batch_accept_respects_min_confidence(self) -> None:
        self.assertEqual(len(self.suggestion_rows("suggested")), 4)
        changed = self.context.review.batch_accept(
            track_ids=self.all_track_ids(), min_confidence=0.7
        )
        self.assertEqual(changed, 2)  # only the 0.9 genre suggestions
        remaining = self.suggestion_rows("suggested")
        self.assertEqual(len(remaining), 2)
        self.assertTrue(all(row["tag_id"] == "era.1990s" for row in remaining))

    def test_batch_reject(self) -> None:
        changed = self.context.review.batch_reject(track_ids=self.all_track_ids())
        self.assertEqual(changed, 4)
        self.assertEqual(self.suggestion_rows("suggested"), [])

    def test_applied_suggestion_cannot_be_reviewed(self) -> None:
        rows = self.suggestion_rows("suggested")
        for row in rows:
            self.context.review.accept(int(row["id"]))
        result = self.context.writer.apply()
        self.assertEqual(result.status, "completed")
        applied = self.suggestion_rows("applied")
        self.assertTrue(applied)
        with self.assertRaises(ReviewError):
            self.context.review.reject(int(applied[0]["id"]))
