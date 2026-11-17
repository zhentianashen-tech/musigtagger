"""End-to-end CLI tests: report rendering, exit codes, and the safety demo."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from evalharness.cli import main

REPO_ROOT = Path(__file__).resolve().parents[2]
TAXONOMY_DIR = REPO_ROOT / "taxonomy"


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


class CliReportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.events = self.dir / "events.jsonl"
        self.handcheck = self.dir / "hc.jsonl"
        self.safety = self.dir / "safety.jsonl"
        self.batches = self.dir / "batches.json"
        self.report = self.dir / "report.md"
        _write_jsonl(
            self.events,
            [
                {
                    "event": "suggestion",
                    "event_version": 1,
                    "run_id": "run-1",
                    "taxonomy_version": "1.0.0",
                    "track": {"path": "/test-data/music-working/x/a.flac", "format": "flac"},
                    "tag_id": "genre.hip-hop",
                    "confidence": 0.8,
                    "source": "metadata.embedded",
                    "evidence": "fixture",
                },
                {
                    "event": "review_outcome",
                    "event_version": 1,
                    "run_id": "run-1",
                    "taxonomy_version": "1.0.0",
                    "track_path": "/test-data/music-working/x/a.flac",
                    "suggestion_id": 1,
                    "from_status": "suggested",
                    "to_status": "accepted",
                    "original_tag_id": "genre.hip-hop",
                    "final_tag_id": "genre.hip-hop",
                    "actor": "local-user",
                },
            ],
        )
        _write_jsonl(
            self.handcheck,
            [
                {
                    "track_path": "/test-data/music-working/x/a.flac",
                    "tag_id": "genre.hip-hop",
                    "decision": "accept",
                }
            ],
        )
        _write_jsonl(
            self.safety,
            [
                {
                    "kind": "backup",
                    "batch_id": "b1",
                    "track_path": "/test-data/music-working/x/a.flac",
                    "ts": "2026-11-17T09:00:00Z",
                    "result": "ok",
                },
                {
                    "kind": "write",
                    "batch_id": "b1",
                    "track_path": "/test-data/music-working/x/a.flac",
                    "ts": "2026-11-17T09:00:05Z",
                    "result": "ok",
                },
            ],
        )
        self.batches.write_text(
            json.dumps([{"id": "b1", "kind": "apply", "status": "completed"}]),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _args(self) -> list[str]:
        return [
            "report",
            "--events", str(self.events),
            "--hand-check", str(self.handcheck),
            "--safety-evidence", str(self.safety),
            "--batches", str(self.batches),
            "--taxonomy-dir", str(TAXONOMY_DIR),
            "--out", str(self.report),
        ]

    def test_full_pass_exit_zero_and_labels(self) -> None:
        exit_code = main(self._args())
        self.assertEqual(exit_code, 0)
        text = self.report.read_text(encoding="utf-8")
        self.assertIn("PROPOSED — pending human sign-off", text)
        self.assertIn("Suggestion precision per category", text)
        self.assertIn("| genre | 1 | 1 | 1 | 0 | 0 | 100.0% |", text)
        self.assertIn("✅ pass", text)

    def test_missing_ground_truth_fails_with_exit_two(self) -> None:
        args = [a for a in self._args() if a != str(self.handcheck)]
        args.remove("--hand-check")
        exit_code = main(args)
        self.assertEqual(exit_code, 2)
        text = self.report.read_text(encoding="utf-8")
        self.assertIn("Ground truth missing", text)

    def test_safety_fault_fails_report_exit_two(self) -> None:
        _write_jsonl(
            self.safety,
            [
                {
                    "kind": "write",
                    "batch_id": "b1",
                    "track_path": "/test-data/music-source/protected.flac",
                    "ts": "2026-11-17T09:00:05Z",
                    "result": "ok",
                }
            ],
        )
        exit_code = main(self._args())
        self.assertEqual(exit_code, 2)
        text = self.report.read_text(encoding="utf-8")
        self.assertIn("❌ FAIL", text)
        self.assertIn("Safety check failed", text)

    def test_worksheet_command(self) -> None:
        out = self.dir / "worksheet.jsonl"
        exit_code = main(["worksheet", "--events", str(self.events), "--out", str(out)])
        self.assertEqual(exit_code, 0)
        rows = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["tag_id"], "genre.hip-hop")
        self.assertEqual(rows[0]["decision"], "")

    def test_safety_demo_detects_all_triggered_faults(self) -> None:
        exit_code = main(["safety-demo"])
        self.assertEqual(exit_code, 0)


if __name__ == "__main__":
    unittest.main()
