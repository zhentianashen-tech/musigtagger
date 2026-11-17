"""Ingestion: scan trigger, provider execution, skips, and suggestion events."""

from __future__ import annotations

from support import AppTestCase, StubProvider, make_library


class IngestTests(AppTestCase):
    def test_scan_indexes_tracks_and_persists_suggestions(self) -> None:
        make_library(self.library, 4)
        report = self.scan()
        self.assertEqual(report.indexed, 4)
        self.assertEqual(report.skipped_count, 0)
        self.assertEqual(report.suggestions_new, 8)
        self.assertEqual(report.providers, ("test.stub",))
        self.assertEqual(len(self.context.store.list_tracks(limit=10)), 4)
        events = [event for event in self.events() if event["event"] == "suggestion"]
        self.assertEqual(len(events), 8)
        self.assertEqual(events[0]["taxonomy_version"], self.context.taxonomy.version)
        self.assertEqual(events[0]["run_id"], "run-test")

    def test_rescan_does_not_duplicate_suggestions(self) -> None:
        make_library(self.library, 2)
        self.scan()
        second = self.scan()
        self.assertEqual(second.indexed, 2)
        self.assertEqual(second.suggestions_new, 0)
        self.assertEqual(second.suggestions_duplicate, 4)
        self.assertEqual(len(self.suggestion_rows()), 4)

    def test_unreadable_files_are_skipped_not_fatal(self) -> None:
        make_library(self.library, 2)
        (self.library / "cover.jpg").write_bytes(b"jpeg")
        report = self.scan()
        self.assertEqual(report.indexed, 2)
        self.assertEqual(report.skipped_count, 1)
        self.assertIn("unsupported test container", report.skipped[0].reason)

    def test_provider_failure_on_one_track_does_not_abort_the_scan(self) -> None:
        make_library(self.library, 3)
        self.context.ingestion.providers = [
            ("test.stub", StubProvider(fail_on={"001 track"}))
        ]
        report = self.scan()
        self.assertEqual(report.indexed, 3)
        self.assertEqual(report.suggestions_new, 4)  # two tracks x two suggestions
        self.assertEqual(report.skipped_count, 1)
        self.assertIn("provider test.stub failed", report.skipped[0].reason)

    def test_unknown_tag_suggestions_are_rejected_and_logged(self) -> None:
        make_library(self.library, 2)
        self.context.ingestion.providers = [
            (
                "test.bad",
                StubProvider(
                    tags=[
                        ("genre.not-a-tag", 0.9, "test.bad", "bad"),
                        ("genre.jazz", 0.8, "test.bad", "good"),
                    ]
                ),
            )
        ]
        report = self.scan()
        self.assertEqual(report.suggestions_unknown, 2)
        self.assertEqual(report.suggestions_new, 2)
        self.assertEqual(
            [row["tag_id"] for row in self.suggestion_rows()], ["genre.jazz", "genre.jazz"]
        )
        suggestion_events = [
            event for event in self.events() if event["event"] == "suggestion"
        ]
        self.assertEqual(len(suggestion_events), 2)
        self.assertTrue(
            all(event["tag_id"] == "genre.jazz" for event in suggestion_events)
        )

    def test_scanning_the_read_only_source_creates_no_files(self) -> None:
        source_file = self.source / "in-source.fake"
        source_file.write_bytes(b"audio")
        before = sorted(path.name for path in self.source.iterdir())
        self.context.config = self.context.config
        report = self.context.ingestion.scan(self.source)
        self.assertEqual(report.indexed, 1)
        self.assertEqual(
            sorted(path.name for path in self.source.iterdir()), before
        )
        self.assertEqual(source_file.read_bytes(), b"audio")

    def test_scanner_errors_are_reported_per_path(self) -> None:
        self.library.mkdir(parents=True, exist_ok=True)
        report = self.context.ingestion.scan(self.library)
        self.assertEqual(report.indexed, 0)
        self.assertEqual(report.skipped_count, 0)
