"""Run a candidate engine build over an explicit library directory.

Used for the frozen remux evaluation input and for the post-fix re-run. Writes
a real suggestion event stream, scan report and batch record for the harness.
"""

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
    SuggestionRunner,
)

RUN = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("eval-run-remux")
INPUT = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("/test-data/music-working/eval-input-ncm-remux")
TAXONOMY = Path(sys.argv[3]) if len(sys.argv) > 3 else Path("/tmp/musi13/taxonomy")


def main():
    RUN.mkdir(parents=True, exist_ok=True)
    db_path = RUN / "library.sqlite3"
    if db_path.exists():
        db_path.unlink()
    connection = initialize_database(db_path)

    scan = LibraryScanner(connection).scan_directory(INPUT)
    taxonomy = TaxonomyLoader.load(TAXONOMY, version="1.0.0")
    provider = MetadataSuggestionProvider(taxonomy)
    events_path = RUN / "engine-events.jsonl"
    if events_path.exists():
        events_path.unlink()
    logger = JsonlEventLogger(events_path)
    result = SuggestionRunner(taxonomy, logger).suggest_batch(scan.tracks, provider)

    suggestions = []
    for item in result.results:
        for s in item.suggestions:
            suggestions.append(
                {
                    "track_path": item.track.path,
                    "tag_id": s.tag_id,
                    "confidence": s.confidence,
                    "source": s.source,
                    "evidence": s.evidence,
                }
            )

    tracks = list(scan.tracks)
    scan_report = {
        "input_root": str(INPUT),
        "indexed": len(tracks),
        "discovered_audio_files": scan.discovered_audio_files,
        "failures": [{"path": f.path, "reason": f.reason} for f in scan.failures],
        "batch_status": "completed" if scan.completed else "crashed",
        "with_title": sum(1 for t in tracks if t.title),
        "with_artist": sum(1 for t in tracks if t.artist),
        "with_album": sum(1 for t in tracks if t.album),
        "with_genre": sum(1 for t in tracks if t.genre),
        "with_year": sum(1 for t in tracks if t.year),
    }
    (RUN / "scan-report.json").write_text(json.dumps(scan_report, ensure_ascii=False, indent=2), encoding="utf-8")
    (RUN / "suggestions.json").write_text(json.dumps(suggestions, ensure_ascii=False, indent=2), encoding="utf-8")
    (RUN / "batches.json").write_text(
        json.dumps([{"id": result.run_id, "status": "completed", "indexed": len(tracks)}], indent=2),
        encoding="utf-8",
    )

    print("run_id:", result.run_id)
    print("indexed:", len(tracks), "discovered:", scan.discovered_audio_files, "failures:", len(scan.failures))
    print("descriptor coverage:", {k: scan_report[k] for k in ("with_title", "with_artist", "with_album", "with_genre", "with_year")})
    print("suggestions:", len(suggestions), "tracks with >=1:", len({s["track_path"] for s in suggestions}))
    print("by tag:", dict(Counter(s["tag_id"] for s in suggestions)))
    print("by source:", dict(Counter(s["source"] for s in suggestions)))
    print("failures:", [(f.path, f.reason) for f in result.failures])


if __name__ == "__main__":
    main()
