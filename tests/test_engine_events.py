from __future__ import annotations

import json
import sys
import tempfile
import types
import unittest
from pathlib import Path

try:
    import mutagen  # noqa: F401
except ModuleNotFoundError:
    sys.modules["mutagen"] = types.SimpleNamespace(File=None)

from musigtagger.contracts import TagSuggestion, TaxonomyLoader, TrackDescriptor
from musigtagger.engine import (
    JsonlEventLogger,
    MetadataSuggestionProvider,
    SuggestionRunner,
)


NOW = "2026-11-17T07:30:00.000Z"
TAXONOMY_DIR = Path(__file__).resolve().parents[1] / "taxonomy"


class EventAndRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.event_path = Path(self.tempdir.name) / "events" / "engine.jsonl"
        self.logger = JsonlEventLogger(self.event_path, clock=lambda: NOW)
        self.taxonomy = TaxonomyLoader.load(TAXONOMY_DIR, version="1.0.0")
        self.provider = MetadataSuggestionProvider(self.taxonomy)
        self.runner = SuggestionRunner(self.taxonomy, self.logger)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def events(self):
        return [json.loads(line) for line in self.event_path.read_text().splitlines()]

    def test_suggestion_events_are_complete_and_run_outside_provider(self) -> None:
        track = TrackDescriptor(
            path="/music/a.flac", format="flac", genre="Rock", year=1975
        )
        result = self.runner.suggest_batch([track], self.provider, run_id="run-test")

        self.assertEqual(result.failures, ())
        self.assertEqual(len(result.results[0].suggestions), 2)
        events = self.events()
        self.assertEqual(len(events), 2)
        for event in events:
            self.assertEqual(event["event"], "suggestion")
            self.assertEqual(event["event_version"], 1)
            self.assertEqual(event["occurred_at"], NOW)
            self.assertEqual(event["run_id"], "run-test")
            self.assertEqual(event["taxonomy_version"], "1.0.0")
            self.assertEqual(event["track"], {"path": track.path, "format": "flac"})
            self.assertTrue(event["source"])
            self.assertTrue(event["evidence"])
            self.assertGreaterEqual(event["confidence"], 0.0)
            self.assertLessEqual(event["confidence"], 1.0)

    def test_provider_fault_is_logged_and_does_not_abort_batch(self) -> None:
        good = TrackDescriptor(path="/music/good.mp3", genre="Rock")
        bad = TrackDescriptor(path="/music/bad.mp3")

        class SometimesBroken:
            def suggest(self, track):
                if track == bad:
                    raise RuntimeError("provider failed")
                return self.provider.suggest(track)

        broken = SometimesBroken()
        broken.provider = self.provider
        with self.assertLogs("musigtagger.engine.runner", level="WARNING"):
            result = self.runner.suggest_batch([bad, good], broken)

        self.assertEqual(len(result.results), 1)
        self.assertEqual(result.results[0].track, good)
        self.assertEqual(len(result.failures), 1)
        self.assertIn("provider failed", result.failures[0].reason)

    def test_unknown_provider_tag_is_rejected_before_event_emission(self) -> None:
        class UnknownTag:
            def suggest(self, track):
                return [TagSuggestion("genre.invented", 0.9, "test", "bad tag")]

        result = self.runner.suggest_batch(
            [TrackDescriptor(path="/music/a.mp3")], UnknownTag()
        )
        self.assertEqual(result.results, ())
        self.assertEqual(len(result.failures), 1)
        self.assertFalse(self.event_path.exists())

    def test_review_outcome_event_contains_decision_and_effective_tag(self) -> None:
        self.logger.log_review_outcome(
            run_id="run-test",
            taxonomy_version="1.0.0",
            track_path="/music/a.flac",
            suggestion_id=42,
            from_status="suggested",
            to_status="edited",
            original_tag_id="genre.hip-hop",
            final_tag_id="genre.hip-hop.trap",
        )
        event = self.events()[0]
        self.assertEqual(event["event"], "review_outcome")
        self.assertEqual(event["suggestion_id"], 42)
        self.assertEqual(event["from_status"], "suggested")
        self.assertEqual(event["to_status"], "edited")
        self.assertEqual(event["final_tag_id"], "genre.hip-hop.trap")
        self.assertEqual(event["actor"], "local-user")
        self.assertEqual(event["occurred_at"], NOW)


if __name__ == "__main__":
    unittest.main()
