"""Tests for the gating safety checks, including the triggered-fault fixtures."""

from __future__ import annotations

import unittest
from pathlib import Path

from evalharness.events import read_event_logs
from evalharness.safety import read_safety_evidence, run_safety_checks

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
SOURCE_ROOT = "/test-data/music-source"


class SafetyTests(unittest.TestCase):
    def _run(self, name: str, with_events: bool = True):
        evidence = read_safety_evidence(FIXTURES / f"safety-{name}.jsonl")
        events_path = FIXTURES / f"events-{name}.jsonl"
        events = read_event_logs([events_path]) if with_events and events_path.exists() else None
        return run_safety_checks(evidence, events, SOURCE_ROOT)

    def test_clean_evidence_passes(self) -> None:
        result = self._run("clean")
        self.assertTrue(result.evidence_present)
        self.assertTrue(result.passed, [c.detail for c in result.checks])

    def test_triggered_fault_source_write_fails(self) -> None:
        result = self._run("fault-source-write")
        self.assertFalse(result.passed)
        source_check = next(c for c in result.checks if "source-root" in c.name)
        self.assertFalse(source_check.passed)
        self.assertTrue(any("music-source" in v for v in source_check.violations))
        # critical finding routed to the app engineer
        criticals = [f for f in result.findings.items if f.severity.value == "critical"]
        self.assertTrue(criticals)
        self.assertEqual(criticals[0].responsible_role, "Application & Integration Engineer")

    def test_triggered_fault_missing_backup_fails(self) -> None:
        result = self._run("fault-missing-backup")
        self.assertFalse(result.passed)
        backup_check = next(c for c in result.checks if "backup" in c.name)
        self.assertFalse(backup_check.passed)
        self.assertTrue(any("no backup" in v for v in backup_check.violations))

    def test_triggered_fault_failed_undo_fails(self) -> None:
        result = self._run("fault-failed-undo")
        self.assertFalse(result.passed)
        undo_check = next(c for c in result.checks if "undo" in c.name)
        self.assertFalse(undo_check.passed)
        self.assertTrue(any("failed undo" in v for v in undo_check.violations))

    def test_missing_evidence_fails_by_design(self) -> None:
        result = run_safety_checks(None, None, SOURCE_ROOT)
        self.assertFalse(result.passed)
        self.assertFalse(result.evidence_present)


if __name__ == "__main__":
    unittest.main()
