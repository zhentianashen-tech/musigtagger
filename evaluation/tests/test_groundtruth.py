"""Tests for the hand-check (ground truth) reader and worksheet builder."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from evalharness.events import SuggestionEvent
from evalharness.groundtruth import build_worksheet, read_hand_check


def _suggestion(track: str, tag: str) -> SuggestionEvent:
    return SuggestionEvent(
        run_id="run-1",
        track_path=track,
        track_format="flac",
        tag_id=tag,
        confidence=0.5,
        source="metadata.embedded",
        evidence="test",
        taxonomy_version="1.0.0",
        occurred_at=None,
    )


class HandCheckTests(unittest.TestCase):
    def test_jsonl_round_trip_and_reason_required(self) -> None:
        rows = [
            {"track_path": "/a.flac", "tag_id": "genre.hip-hop", "decision": "accept"},
            {
                "track_path": "/a.flac",
                "tag_id": "mood.calm",
                "decision": "reject",
                "reason": "not calm at all",
            },
            {
                "track_path": "/b.flac",
                "tag_id": "genre.rock",
                "decision": "modify",
                "modified_tag_id": "genre.rock.indie",
                "reason": "more specific",
            },
            # invalid: reject without reason
            {"track_path": "/b.flac", "tag_id": "era.1990s", "decision": "reject"},
            # invalid: modify without target
            {"track_path": "/b.flac", "tag_id": "mood.calm", "decision": "modify"},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "handcheck.jsonl"
            path.write_text(
                "\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8"
            )
            result = read_hand_check(path)
        self.assertEqual(len(result.decisions), 3)
        self.assertEqual(len(result.problems), 2)
        self.assertIn(("/a.flac", "genre.hip-hop"), result.by_key)

    def test_csv_input(self) -> None:
        content = (
            "track_path,tag_id,decision,modified_tag_id,reason,evaluator,checked_at\n"
            "/a.flac,genre.hip-hop,accept,,,ext-agent,2026-11-17T10:00:00Z\n"
            "/a.flac,mood.calm,reject,,wrong mood,ext-agent,2026-11-17T10:00:01Z\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "handcheck.csv"
            path.write_text(content, encoding="utf-8")
            result = read_hand_check(path)
        self.assertEqual(len(result.decisions), 2)
        self.assertEqual(result.problems, [])

    def test_blank_worksheet_rows_are_skipped(self) -> None:
        rows = [
            {"track_path": "/a.flac", "tag_id": "genre.hip-hop", "decision": ""},
            {"track_path": "/a.flac", "tag_id": "mood.calm", "decision": "accept"},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "worksheet.jsonl"
            path.write_text(
                "\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8"
            )
            result = read_hand_check(path)
        self.assertEqual(len(result.decisions), 1)

    def test_worksheet_builder_dedupes_and_preserves_keys(self) -> None:
        suggestions = [
            _suggestion("/b.flac", "genre.rock"),
            _suggestion("/a.flac", "genre.hip-hop"),
            _suggestion("/a.flac", "genre.hip-hop"),  # duplicate event
        ]
        rows = build_worksheet(suggestions)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["track_path"], "/a.flac")
        self.assertEqual(rows[0]["decision"], "")
        self.assertEqual(rows[1]["tag_id"], "genre.rock")


if __name__ == "__main__":
    unittest.main()
