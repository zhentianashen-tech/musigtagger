"""Tests for the metric computations, run against the real taxonomy v1.0.0."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from evalharness.events import read_event_logs
from evalharness.groundtruth import read_hand_check
from evalharness.metrics import (
    compute_batch_completion,
    compute_quality,
    load_taxonomy,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
TAXONOMY_DIR = REPO_ROOT / "taxonomy"


def _suggestion(track: str, tag: str, source: str = "metadata.embedded") -> dict:
    return {
        "event": "suggestion",
        "event_version": 1,
        "run_id": "run-1",
        "taxonomy_version": "1.0.0",
        "track": {"path": track, "format": "flac"},
        "tag_id": tag,
        "confidence": 0.8,
        "source": source,
        "evidence": "test fixture",
    }


class MetricTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.taxonomy, cls.taxonomy_error = load_taxonomy(TAXONOMY_DIR, "1.0.0")
        if cls.taxonomy is None:
            raise unittest.SkipTest(f"taxonomy unavailable: {cls.taxonomy_error}")

    def _run(
        self,
        suggestions: list[dict],
        decisions: list[dict] | None,
        scan_report: dict | None = None,
    ):
        with tempfile.TemporaryDirectory() as tmp:
            events_path = Path(tmp) / "events.jsonl"
            events_path.write_text(
                "\n".join(json.dumps(s) for s in suggestions) + "\n", encoding="utf-8"
            )
            events = read_event_logs([events_path])
            hand_check = None
            if decisions is not None:
                hc_path = Path(tmp) / "hc.jsonl"
                hc_path.write_text(
                    "\n".join(json.dumps(d) for d in decisions) + "\n", encoding="utf-8"
                )
                hand_check = read_hand_check(hc_path)
            return compute_quality(events, hand_check, self.taxonomy, scan_report)

    def test_per_category_precision_with_counts(self) -> None:
        suggestions = [
            _suggestion("/a.flac", "genre.hip-hop"),
            _suggestion("/a.flac", "mood.calm"),
            _suggestion("/b.flac", "genre.hip-hop"),
            _suggestion("/b.flac", "era.1990s"),
        ]
        decisions = [
            {"track_path": "/a.flac", "tag_id": "genre.hip-hop", "decision": "accept"},
            {
                "track_path": "/a.flac",
                "tag_id": "mood.calm",
                "decision": "reject",
                "reason": "wrong",
            },
            {
                "track_path": "/b.flac",
                "tag_id": "genre.hip-hop",
                "decision": "modify",
                "modified_tag_id": "genre.trap",
                "reason": "narrower",
            },
            {"track_path": "/b.flac", "tag_id": "era.1990s", "decision": "accept"},
        ]
        result = self._run(suggestions, decisions)
        genre = result.per_category["genre"]
        self.assertEqual((genre.suggested, genre.checked, genre.accepted, genre.modified), (2, 2, 1, 1))
        self.assertAlmostEqual(genre.precision, 0.5)
        self.assertAlmostEqual(result.overall.precision, 2 / 4)
        self.assertEqual(result.overall.suggested, 4)
        # coverage: /a.flac has accept, /b.flac has accept+modify -> 2/2
        self.assertAlmostEqual(result.coverage, 1.0)
        self.assertEqual(result.coverage_denominator_source, "distinct tracks in event stream (no scan report supplied)")
        # correction burden
        self.assertAlmostEqual(result.modifies_per_track, 0.5)
        self.assertAlmostEqual(result.rejects_per_track, 0.5)
        # conformance: hip-hop.trap must exist in taxonomy v1.0.0
        self.assertEqual(result.conformance.unknown_refs, [])
        self.assertAlmostEqual(result.conformance.conformance, 1.0)

    def test_unknown_tag_id_is_flagged_as_engine_defect(self) -> None:
        suggestions = [_suggestion("/a.flac", "genre.totally-not-real")]
        decisions = [
            {
                "track_path": "/a.flac",
                "tag_id": "genre.totally-not-real",
                "decision": "reject",
                "reason": "nonsense tag",
            }
        ]
        result = self._run(suggestions, decisions)
        self.assertEqual(len(result.conformance.unknown_refs), 1)
        self.assertLess(result.conformance.conformance, 1.0)
        severities = [f.summary for f in result.findings.ordered()]
        self.assertTrue(any("Unknown tag id" in s for s in severities))

    def test_unmatched_hand_check_rows_are_evaluation_data_problems(self) -> None:
        suggestions = [_suggestion("/a.flac", "genre.hip-hop")]
        decisions = [
            {"track_path": "/zzz.flac", "tag_id": "genre.hip-hop", "decision": "accept"},
        ]
        result = self._run(suggestions, decisions)
        self.assertTrue(
            any("match no suggestion event" in f.summary for f in result.findings.items)
        )
        self.assertEqual(result.overall.unchecked, 1)
        self.assertIsNone(result.overall.precision)

    def test_coverage_uses_scan_report_denominator(self) -> None:
        suggestions = [_suggestion("/a.flac", "genre.hip-hop")]
        decisions = [
            {"track_path": "/a.flac", "tag_id": "genre.hip-hop", "decision": "accept"},
        ]
        result = self._run(
            suggestions, decisions, scan_report={"indexed": 10, "skipped": 2}
        )
        self.assertAlmostEqual(result.coverage, 0.1)
        self.assertIn("scan report", result.coverage_denominator_source)

    def test_no_ground_truth_means_no_precision(self) -> None:
        suggestions = [_suggestion("/a.flac", "genre.hip-hop")]
        result = self._run(suggestions, None)
        self.assertIsNone(result.overall.precision)
        self.assertFalse(result.ground_truth_present)
        # fallback coverage from app outcomes: none here
        self.assertAlmostEqual(result.coverage, 0.0)

    def test_batch_completion_counts_crashes(self) -> None:
        batches = [
            {"id": "b1", "kind": "scan", "status": "completed"},
            {"id": "b2", "kind": "apply", "status": "failed"},  # clean terminal failure
            {"id": "b3", "kind": "apply", "status": "crashed"},
            {"id": "b4", "kind": "apply"},  # no terminal status
        ]
        result = compute_batch_completion(batches)
        self.assertEqual(result.total, 4)
        self.assertEqual(result.completed, 2)
        self.assertEqual(len(result.incomplete), 2)
        self.assertAlmostEqual(result.rate, 0.5)


if __name__ == "__main__":
    unittest.main()
