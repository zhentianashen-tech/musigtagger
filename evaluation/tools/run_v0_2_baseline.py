"""Run the single plan-v0.2 baseline on the frozen remux input (main build).

Composes the local metadata provider and, unless ``--no-network`` is passed,
the MUSI-14 MusicBrainz release-year provider. Emits the real suggestion event
stream, scan report, batch record and abstention log the harness consumes.

Read-only against the input directory; the SQLite cache is written inside the
run directory.
"""

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from musigtagger.contracts import TaxonomyLoader
from musigtagger.db import initialize_database
from musigtagger.engine import (
    JsonlEventLogger,
    LibraryScanner,
    MetadataSuggestionProvider,
    MusicBrainzReleaseYearProvider,
    ReleaseDateCache,
    SuggestionRunner,
)

DEFAULT_INPUT = Path("/test-data/music-working/eval-input-ncm-remux")
DEFAULT_TAXONOMY = Path("/tmp/musi-main/taxonomy")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--taxonomy", type=Path, default=DEFAULT_TAXONOMY)
    parser.add_argument("--no-network", action="store_true")
    parser.add_argument("--run-id-prefix", default="v0.2")
    args = parser.parse_args()

    run_dir = args.run_dir
    run_dir.mkdir(parents=True, exist_ok=True)
    db_path = run_dir / "library.sqlite3"
    if db_path.exists():
        db_path.unlink()
    connection = initialize_database(db_path)

    taxonomy = TaxonomyLoader.load(args.taxonomy, version="1.0.0")
    scan = LibraryScanner(connection).scan_directory(args.input)
    logger = JsonlEventLogger(run_dir / "engine-events.jsonl")
    runner = SuggestionRunner(taxonomy, logger)

    suggestions = []
    providers = [("local", MetadataSuggestionProvider(taxonomy))]
    network = None
    if not args.no_network:
        network = MusicBrainzReleaseYearProvider(taxonomy, ReleaseDateCache(connection))
        providers.append(("network", network))

    provider_runs = []
    for name, provider in providers:
        result = runner.suggest_batch(
            scan.tracks, provider, run_id=f"{args.run_id_prefix}-{name}"
        )
        provider_runs.append(
            {
                "provider": name,
                "run_id": result.run_id,
                "suggestions": sum(len(item.suggestions) for item in result.results),
                "failures": len(result.failures),
                "failure_sample": [
                    {"path": f.path, "reason": f.reason} for f in result.failures[:3]
                ],
            }
        )
        for item in result.results:
            for s in item.suggestions:
                suggestions.append(
                    {
                        "track_path": item.track.path,
                        "track_id": None,
                        "tag_id": s.tag_id,
                        "confidence": s.confidence,
                        "source": s.source,
                        "evidence": s.evidence,
                        "title": item.track.title,
                        "artist": item.track.artist,
                        "album": item.track.album,
                        "genre": item.track.genre,
                        "year": item.track.year,
                    }
                )

    tracks = list(scan.tracks)
    scan_report = {
        "input_root": str(args.input),
        "indexed": len(tracks),
        "discovered_audio_files": scan.discovered_audio_files,
        "failures": [{"path": f.path, "reason": f.reason} for f in scan.failures],
        "batch_status": "completed" if scan.completed else "crashed",
        "with_title": sum(1 for t in tracks if t.title),
        "with_artist": sum(1 for t in tracks if t.artist),
        "with_album": sum(1 for t in tracks if t.album),
        "with_genre": sum(1 for t in tracks if t.genre),
        "with_year": sum(1 for t in tracks if t.year),
        "providers": provider_runs,
        "network_enabled": not args.no_network,
        "network_attempted_pairs": len(getattr(network, "_failed_pairs", ())) if network else 0,
    }
    (run_dir / "scan-report.json").write_text(
        json.dumps(scan_report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (run_dir / "suggestions.json").write_text(
        json.dumps(suggestions, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (run_dir / "batches.json").write_text(
        json.dumps(
            [
                {
                    "id": f"{args.run_id_prefix}-scan-batch",
                    "status": "completed" if scan.completed else "crashed",
                    "indexed": len(tracks),
                }
            ],
            indent=2,
        ),
        encoding="utf-8",
    )

    print("indexed:", len(tracks), "discovered:", scan.discovered_audio_files,
          "scan_failures:", len(scan.failures))
    print("descriptor coverage:", {k: scan_report[k] for k in
          ("with_title", "with_artist", "with_album", "with_genre", "with_year")})
    for pr in provider_runs:
        print(f"{pr['provider']}: run_id={pr['run_id']} suggestions={pr['suggestions']} "
              f"failures={pr['failures']}")
        for f in pr["failure_sample"]:
            print("  fail:", f["reason"][:180])
    print("by tag:", dict(Counter(s["tag_id"] for s in suggestions)))
    print("by source:", dict(Counter(s["source"] for s in suggestions)))
    print("network attempted pairs:", scan_report["network_attempted_pairs"])
    connection.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
