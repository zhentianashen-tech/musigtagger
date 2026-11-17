"""Run the recovered MUSI-13 engine build against the fixed 47-FLAC set.

Read-only against /test-data/music-source: the 47 FLACs are exposed through
symlinks in a scratch directory, so the scanner never opens a source file for
writing. Emits the real suggestion event stream consumed by the evaluation
harness.
"""

import json
import os
import shutil
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

SRC = Path("/test-data/music-source")
RUN = Path(sys.argv[1] if len(sys.argv) > 1 else "eval-run")
TAXONOMY = Path("/tmp/musi13/taxonomy")


def main():
    RUN.mkdir(parents=True, exist_ok=True)
    link_dir = RUN / "fixed-flac-set"
    if link_dir.exists():
        shutil.rmtree(link_dir)
    link_dir.mkdir()
    flacs = sorted(SRC.glob("*.flac"))
    for src in flacs:
        os.symlink(src.resolve(), link_dir / src.name)

    db_path = RUN / "library.sqlite3"
    if db_path.exists():
        db_path.unlink()
    connection = initialize_database(db_path)

    scan = LibraryScanner(connection).scan_directory(link_dir)
    taxonomy = TaxonomyLoader.load(TAXONOMY, version="1.0.0")
    provider = MetadataSuggestionProvider(taxonomy)
    events_path = RUN / "engine-events.jsonl"
    if events_path.exists():
        events_path.unlink()
    logger = JsonlEventLogger(events_path)
    result = SuggestionRunner(taxonomy, logger).suggest_batch(scan.tracks, provider)

    all_suggestions = []
    for item in result.results:
        for s in item.suggestions:
            all_suggestions.append(
                {
                    "track_path": item.track.path,
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

    scan_report = {
        "indexed": len(scan.tracks),
        "discovered_audio_files": scan.discovered_audio_files,
        "failures": [{"path": f.path, "reason": f.reason} for f in scan.failures],
        "batch_status": "completed" if scan.completed else "crashed",
    }
    (RUN / "scan-report.json").write_text(json.dumps(scan_report, ensure_ascii=False, indent=2), encoding="utf-8")
    (RUN / "suggestions.json").write_text(json.dumps(all_suggestions, ensure_ascii=False, indent=2), encoding="utf-8")
    (RUN / "batches.json").write_text(
        json.dumps([{"id": result.run_id, "status": "completed", "indexed": len(scan.tracks)}], indent=2),
        encoding="utf-8",
    )

    by_cat = Counter(s["tag_id"].split(".", 1)[0] for s in all_suggestions)
    by_tag = Counter(s["tag_id"] for s in all_suggestions)
    by_source = Counter(s["source"] for s in all_suggestions)
    with_suggestion = {s["track_path"] for s in all_suggestions}
    print("run_id:", result.run_id)
    print("discovered:", scan.discovered_audio_files, "indexed:", len(scan.tracks), "failures:", len(scan.failures))
    print("suggestions:", len(all_suggestions), "tracks with >=1:", len(with_suggestion), "/", len(scan.tracks))
    print("by category:", dict(by_cat))
    print("by source:", dict(by_source))
    print("by tag:", dict(by_tag))
    print("failures:", [(f.path, f.reason) for f in result.failures])
    print("\nper-track:")
    for item in result.results:
        tags = ", ".join(f"{s.tag_id}({s.confidence:.2f},{s.source})" for s in item.suggestions)
        print(f"  {Path(item.track.path).name}: {tags or '-'}")


if __name__ == "__main__":
    main()
