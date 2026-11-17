"""Tests for the event-stream reader."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from evalharness.events import read_event_logs

SUGGESTION = {
    "event": "suggestion",
    "event_version": 1,
    "occurred_at": "2026-11-17T09:00:00Z",
    "run_id": "run-1",
    "taxonomy_version": "1.0.0",
    "track": {"path": "/music/a.flac", "format": "flac"},
    "tag_id": "genre.hip-hop",
    "confidence": 0.72,
    "source": "metadata.embedded",
    "evidence": "Vorbis GENRE='Hip Hop'",
}
OUTCOME = {
    "event": "review_outcome",
    "event_version": 1,
    "run_id": "run-1",
    "taxonomy_version": "1.0.0",
    "track_path": "/music/a.flac",
    "suggestion_id": 42,
    "from_status": "suggested",
    "to_status": "edited",
    "original_tag_id": "genre.hip-hop",
    "final_tag_id": "genre.trap",
    "actor": "local-user",
}


class EventReadTests(unittest.TestCase):
    def _write(self, directory: Path, name: str, lines: list[str]) -> Path:
        path = directory / name
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path

    def test_parses_both_families(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(
                Path(tmp),
                "events.jsonl",
                [json.dumps(SUGGESTION), json.dumps(OUTCOME)],
            )
            result = read_event_logs([path])
        self.assertEqual(len(result.suggestions), 1)
        self.assertEqual(len(result.outcomes), 1)
        self.assertEqual(result.suggestions[0].category, "genre")
        self.assertEqual(result.suggestions[0].confidence, 0.72)
        self.assertEqual(result.outcomes[0].final_tag_id, "genre.trap")
        self.assertEqual(result.run_ids, ("run-1",))
        self.assertEqual(result.distinct_tracks, ("/music/a.flac",))
        self.assertEqual(result.malformed_lines, 0)

    def test_tolerates_malformed_and_unknown_lines(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(
                Path(tmp),
                "events.jsonl",
                [
                    json.dumps(SUGGESTION),
                    "{not json",
                    json.dumps({"event": "telemetry", "x": 1}),
                    json.dumps({"event": "suggestion", "tag_id": "genre.x"}),  # incomplete
                    "",
                ],
            )
            result = read_event_logs([path])
        self.assertEqual(len(result.suggestions), 1)
        self.assertEqual(result.malformed_lines, 1)
        self.assertEqual(result.unknown_event_lines, 1)
        self.assertEqual(len(result.invalid_records), 1)

    def test_missing_file_is_reported_not_fatal(self) -> None:
        result = read_event_logs(["/nonexistent/events.jsonl"])
        self.assertEqual(len(result.invalid_records), 1)
        self.assertEqual(result.suggestions, [])


if __name__ == "__main__":
    unittest.main()
