"""The CONTRACTS.md §4 event stream."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from musigtagger.app.events import (
    EventLog,
    read_events,
    review_outcome_event,
    suggestion_event,
)
from musigtagger.contracts import TagSuggestion

FIXED_TIME = "2026-11-17T07:30:00.000Z"


class EventLogTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = Path(tempfile.mkdtemp(prefix="musictagger-events-"))
        self.path = self.tempdir / "events.jsonl"
        self.log = EventLog(self.path, clock=lambda: FIXED_TIME)

    def tearDown(self) -> None:
        import shutil

        shutil.rmtree(self.tempdir, ignore_errors=True)

    def test_suggestion_event_matches_the_contract_shape(self) -> None:
        suggestion = TagSuggestion(
            tag_id="genre.hip-hop",
            confidence=0.72,
            source="metadata.embedded",
            evidence="Vorbis GENRE='Hip Hop'",
        )
        self.log.emit(
            suggestion_event(
                run_id="run-1",
                taxonomy_version="1.0.0",
                track_path="/music/a.flac",
                track_format="flac",
                suggestion=suggestion,
            )
        )
        record = read_events(self.path)[0]
        self.assertEqual(record["event"], "suggestion")
        self.assertEqual(record["event_version"], 1)
        self.assertEqual(record["occurred_at"], FIXED_TIME)
        self.assertEqual(record["run_id"], "run-1")
        self.assertEqual(record["taxonomy_version"], "1.0.0")
        self.assertEqual(record["track"], {"path": "/music/a.flac", "format": "flac"})
        self.assertEqual(record["tag_id"], "genre.hip-hop")
        self.assertEqual(record["confidence"], 0.72)
        self.assertEqual(record["source"], "metadata.embedded")
        self.assertEqual(record["evidence"], "Vorbis GENRE='Hip Hop'")

    def test_review_outcome_event_matches_the_contract_shape(self) -> None:
        self.log.emit(
            review_outcome_event(
                run_id="run-1",
                taxonomy_version="1.0.0",
                track_path="/music/a.flac",
                suggestion_id=42,
                from_status="suggested",
                to_status="edited",
                original_tag_id="genre.hip-hop",
                final_tag_id="genre.jazz",
                actor="local-user",
            )
        )
        record = read_events(self.path)[0]
        self.assertEqual(record["event"], "review_outcome")
        self.assertEqual(record["suggestion_id"], 42)
        self.assertEqual(record["from_status"], "suggested")
        self.assertEqual(record["to_status"], "edited")
        self.assertEqual(record["final_tag_id"], "genre.jazz")
        self.assertEqual(record["actor"], "local-user")

    def test_append_only_and_filterable(self) -> None:
        for index in range(3):
            self.log.emit({"event": "suggestion", "index": index})
        self.log.emit({"event": "review_outcome", "index": 9})
        self.assertEqual(len(read_events(self.path)), 4)
        outcomes = read_events(self.path, event="review_outcome")
        self.assertEqual(len(outcomes), 1)
        self.assertEqual(read_events(self.path, limit=1)[0]["index"], 9)

    def test_malformed_lines_are_tolerated(self) -> None:
        self.path.write_text("{not json}\n\n", encoding="utf-8")
        self.log.emit({"event": "review_outcome"})
        records = read_events(self.path)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["event"], "review_outcome")

    def test_emission_failure_does_not_raise(self) -> None:
        self.path.mkdir()  # a directory cannot be opened for append
        self.assertIsNone(self.log.emit({"event": "suggestion"}))
        self.assertEqual(read_events(self.path), [])

    def test_disabled_log_writes_nothing(self) -> None:
        log = EventLog(None)
        self.assertIsNone(log.emit({"event": "suggestion"}))

    def test_records_are_one_json_object_per_line(self) -> None:
        self.log.emit({"event": "suggestion", "note": "line\nbreak"})
        lines = self.path.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 1)
        self.assertIsInstance(json.loads(lines[0]), dict)
