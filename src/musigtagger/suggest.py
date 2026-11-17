"""Command-line entry point for the batch *suggest* path.

This is engine-side wiring only (MUSI-14): it scans a music directory, runs
suggestion providers over the descriptors, and prints the proposals with
source, confidence, and evidence. It writes audio files never — the review
and tag-write workflow belongs to the application layer (MUSI-8).

With ``--no-network`` (or with the network simply down) the run is exactly
the pre-network Phase 1 behaviour: the local metadata provider alone, plus
logged abstentions when the network provider is enabled but cannot reach
MusicBrainz.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from musigtagger.db import initialize_database
from musigtagger.engine import (
    JsonlEventLogger,
    LibraryScanner,
    MetadataSuggestionProvider,
    SuggestionRunner,
)
from musigtagger.engine.network import (
    MusicBrainzReleaseYearProvider,
    ReleaseDateCache,
)

LOGGER = logging.getLogger(__name__)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="musigtagger-suggest",
        description="Scan a music directory and print taxonomy tag suggestions.",
    )
    parser.add_argument("music_dir", help="directory to scan recursively")
    parser.add_argument(
        "--library",
        default="library.sqlite3",
        help="library SQLite database (default: ./library.sqlite3)",
    )
    parser.add_argument(
        "--events",
        default="history/engine-events.jsonl",
        help="JSONL suggestion-event log (default: ./history/engine-events.jsonl)",
    )
    parser.add_argument(
        "--taxonomy",
        default=None,
        help="taxonomy directory (default: packaged repo checkout not required; "
        "falls back to ./taxonomy)",
    )
    parser.add_argument(
        "--no-network",
        action="store_true",
        help="disable the MusicBrainz release-date provider",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="emit one JSON object per line instead of human-readable text",
    )
    return parser


def _load_taxonomy(explicit: str | None):
    from musigtagger.contracts import TaxonomyLoader

    candidates = (
        [Path(explicit)]
        if explicit
        else [Path("taxonomy"), Path(__file__).resolve().parents[2] / "taxonomy"]
    )
    for candidate in candidates:
        if (candidate / "taxonomy-1.0.0.json").is_file():
            return TaxonomyLoader.load(str(candidate), version="1.0.0")
    raise SystemExit(
        "taxonomy v1.0.0 not found; pass --taxonomy pointing at the taxonomy "
        "directory"
    )


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = _build_parser().parse_args(argv)

    taxonomy = _load_taxonomy(args.taxonomy)
    connection = initialize_database(args.library)
    event_logger = JsonlEventLogger(args.events)
    runner = SuggestionRunner(taxonomy, event_logger)

    scan = LibraryScanner(connection).scan_directory(args.music_dir)
    print(
        f"scanned {len(scan.tracks)} tracks "
        f"({len(scan.failures)} scan failures) from {args.music_dir}",
        file=sys.stderr,
    )

    providers = [MetadataSuggestionProvider(taxonomy)]
    if not args.no_network:
        providers.append(
            MusicBrainzReleaseYearProvider(taxonomy, ReleaseDateCache(connection))
        )

    for provider in providers:
        result = runner.suggest_batch(scan.tracks, provider)
        for item in result.results:
            for suggestion in item.suggestions:
                if args.json:
                    print(
                        json.dumps(
                            {
                                "path": item.track.path,
                                "tag_id": suggestion.tag_id,
                                "confidence": suggestion.confidence,
                                "source": suggestion.source,
                                "evidence": suggestion.evidence,
                            },
                            ensure_ascii=False,
                        )
                    )
                else:
                    print(
                        f"{item.track.path}\n"
                        f"  {suggestion.tag_id}  confidence="
                        f"{suggestion.confidence:.2f}  [{suggestion.source}]\n"
                        f"    {suggestion.evidence}"
                    )
        for failure in result.failures:
            if args.json:
                print(
                    json.dumps(
                        {"path": failure.path, "abstained": failure.reason},
                        ensure_ascii=False,
                    )
                )
            else:
                print(f"{failure.path}\n  ABSTAINED: {failure.reason}")

    connection.close()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
