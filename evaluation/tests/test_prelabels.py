"""Tests for plan-v0.2 pre-label reading and expected-tag recall."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from evalharness.events import EventReadResult, SuggestionEvent
from evalharness.metrics import compute_recall, load_taxonomy
from evalharness.prelabels import read_prelabels

REPO_ROOT = Path(__file__).resolve().parents[2]
TAXONOMY_DIR = REPO_ROOT / "taxonomy"

CSV_ROWS = """row,track_id,work_key,canonical_path,expected_genre_primary,expected_genre_secondary,expected_era,expected_origin,expected_mood,expected_activity,label_confidence
1,1,w1,/a.mp3,genre.k-pop,,era.2020s,origin.east-asia,,,high
2,2,w2,/b.mp3,genre.orchestral,,era.2020s,,,,medium
3,3,w1,/c.mp3,genre.k-pop,,era.2020s,origin.east-asia,,,high
"""


def _suggestion(path: str, tag: str) -> SuggestionEvent:
    return SuggestionEvent(
        run_id="run-1",
        track_path=path,
        track_format="mp3",
        tag_id=tag,
        confidence=0.5,
        source="metadata.path",
        evidence="test",
        taxonomy_version="1.0.0",
        occurred_at=None,
    )


class RecallTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.taxonomy, cls.error = load_taxonomy(TAXONOMY_DIR, "1.0.0")
        if cls.taxonomy is None:
            raise unittest.SkipTest(f"taxonomy unavailable: {cls.error}")

    def _prelabels(self, text: str):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "prelabels.csv"
        path.write_text(text, encoding="utf-8")
        return read_prelabels(path)

    def _events(self):
        events = EventReadResult()
        events.suggestions.extend(
            [
                _suggestion("/a.mp3", "genre.pop"),      # parent of genre.k-pop
                _suggestion("/a.mp3", "era.2020s"),
                _suggestion("/a.mp3", "origin.east-asia"),
                _suggestion("/b.mp3", "genre.classical"),  # parent of genre.orchestral
                _suggestion("/b.mp3", "era.2020s"),
            ]
        )
        return events

    def test_csv_reading_and_tag_expansion(self) -> None:
        prelabels = self._prelabels(CSV_ROWS)
        self.assertEqual(len(prelabels.labels), 3)
        first = prelabels.labels[0]
        self.assertEqual(first.canonical_path, "/a.mp3")
        self.assertEqual(
            first.expected_tags, ("genre.k-pop", "era.2020s", "origin.east-asia")
        )

    def test_parent_and_exact_matches_with_missed(self) -> None:
        recall = compute_recall(self._events(), self._prelabels(CSV_ROWS), self.taxonomy)
        genre = recall.per_category["genre"]
        self.assertEqual((genre.expected, genre.exact, genre.parent_only, genre.missed), (3, 0, 2, 1))
        era = recall.per_category["era"]
        self.assertEqual((era.expected, era.exact, era.missed), (3, 2, 1))
        origin = recall.per_category["origin"]
        self.assertEqual((origin.expected, origin.exact, origin.missed), (2, 1, 1))
        self.assertEqual(
            (recall.overall.expected, recall.overall.exact, recall.overall.parent_only, recall.overall.missed),
            (8, 3, 2, 3),
        )
        self.assertEqual(recall.tracks_with_expected_no_suggestion, ["/c.mp3"])

    def test_work_level_deduplicates_instances(self) -> None:
        recall = compute_recall(self._events(), self._prelabels(CSV_ROWS), self.taxonomy)
        work1 = recall.per_work["w1"]
        # w1 has two instances with identical expected tags; matches on /a count once.
        self.assertEqual((work1.expected, work1.exact, work1.parent_only, work1.missed), (3, 2, 1, 0))
        self.assertEqual(recall.work_overall.expected, 5)

    def test_unknown_tag_is_reported_not_counted_as_match(self) -> None:
        rows = CSV_ROWS.replace("genre.k-pop,,era.2020s", "genre.not-a-tag,,era.2020s", 1)
        recall = compute_recall(self._events(), self._prelabels(rows), self.taxonomy)
        self.assertTrue(any("unknown taxonomy tag" in f.summary for f in recall.findings.items))
        self.assertGreaterEqual(recall.overall.missed, 1)

    def test_per_work_json_without_paths_is_rejected_with_guidance(self) -> None:
        import json

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "works.json"
        path.write_text(json.dumps({"works": [{"work_key": "x"}]}), encoding="utf-8")
        result = read_prelabels(path)
        self.assertEqual(result.labels, [])
        self.assertTrue(any("per-instance worksheet" in p for p in result.problems))


if __name__ == "__main__":
    unittest.main()
