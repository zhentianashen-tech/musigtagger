"""Plan-v0.2 baseline with the live MusicBrainz date provider.

Reuses an existing SQLite response cache (copying it into the run directory so
the original evidence is untouched), fetches only cache misses, sends the
project User-Agent, paces requests at <= 1/s, and records cache hits/misses,
network requests, failures, retries and the observed request intervals.
"""

import argparse
import json
import shutil
import sqlite3
import statistics
import sys
import time
from collections import Counter
from pathlib import Path

from musigtagger.contracts import TaxonomyLoader
from musigtagger.db import initialize_database
from musigtagger.engine import (
    JsonlEventLogger,
    LibraryScanner,
    MetadataSuggestionProvider,
    MusicBrainzHttpTransport,
    MusicBrainzReleaseYearProvider,
    NetworkLookupError,
    ReleaseDateCache,
    SuggestionRunner,
)

DEFAULT_INPUT = Path("/test-data/music-working/eval-input-ncm-remux")
DEFAULT_TAXONOMY = Path("/tmp/musi-main/taxonomy")
DEFAULT_UA = (
    "MusicTagger/0.1.0 (local personal-library tagger; "
    "https://github.com/zhentianashen-tech/musigtagger)"
)
MIN_INTERVAL = 1.1


class CountingCache(ReleaseDateCache):
    def __init__(self, connection: sqlite3.Connection) -> None:
        super().__init__(connection)
        self.hits = 0
        self.misses = 0

    def get(self, normalized_album: str, normalized_artist: str):
        value = super().get(normalized_album, normalized_artist)
        if value is None:
            self.misses += 1
        else:
            self.hits += 1
        return value


class CountingTransport:
    """Wrap the real transport with retries, pacing, and per-attempt records."""

    def __init__(
        self,
        inner: MusicBrainzHttpTransport,
        *,
        max_attempts: int = 3,
        backoff_seconds: float = 2.0,
    ) -> None:
        self.inner = inner
        self.max_attempts = max_attempts
        self.backoff_seconds = backoff_seconds
        self.attempts: list[dict] = []
        self.failures: list[dict] = []
        self._last_start: float | None = None

    def _throttle(self) -> None:
        """Enforce the 1 req/s rule across pairs *and* retries."""
        now = time.monotonic()
        if self._last_start is not None:
            wait = MIN_INTERVAL - (now - self._last_start)
            if wait > 0:
                time.sleep(wait)
        self._last_start = time.monotonic()

    def search_release_groups(self, *, album: str, artist: str) -> dict:
        for attempt in range(1, self.max_attempts + 1):
            if attempt > 1:
                time.sleep(self.backoff_seconds * (attempt - 1))
            self._throttle()
            started = time.monotonic()
            record = {
                "album": album,
                "artist": artist,
                "attempt": attempt,
                "started": started,
            }
            try:
                document = self.inner.search_release_groups(album=album, artist=artist)
            except NetworkLookupError as exc:
                record.update(
                    outcome="error", error=str(exc), finished=time.monotonic()
                )
                self.attempts.append(record)
                self.failures.append(record)
                if attempt == self.max_attempts:
                    raise
                continue
            record.update(outcome="ok", finished=time.monotonic())
            self.attempts.append(record)
            return document
        raise AssertionError("unreachable")


def cache_stats(connection: sqlite3.Connection) -> dict:
    rows = connection.execute(
        "SELECT found, COUNT(*) AS n FROM release_date_cache GROUP BY found"
    ).fetchall()
    by_found = {str(bool(row["found"])): int(row["n"]) for row in rows}
    total = connection.execute("SELECT COUNT(*) FROM release_date_cache").fetchone()[0]
    return {"rows": int(total), "found": by_found.get("True", 0),
            "no_match": by_found.get("False", 0)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--taxonomy", type=Path, default=DEFAULT_TAXONOMY)
    parser.add_argument("--cache-db", type=Path, default=None)
    parser.add_argument("--user-agent", default=DEFAULT_UA)
    parser.add_argument("--run-id-prefix", default="v0.2")
    parser.add_argument("--max-attempts", type=int, default=3)
    args = parser.parse_args()

    run_dir = args.run_dir
    run_dir.mkdir(parents=True, exist_ok=True)
    db_path = run_dir / "library.sqlite3"
    if args.cache_db is not None:
        shutil.copy2(args.cache_db, db_path)
        cache_source = str(args.cache_db)
    else:
        cache_source = "(fresh)"
        if db_path.exists():
            db_path.unlink()
    connection = initialize_database(db_path)
    before = cache_stats(connection)

    taxonomy = TaxonomyLoader.load(args.taxonomy, version="1.0.0")
    scan = LibraryScanner(connection).scan_directory(args.input)
    logger = JsonlEventLogger(run_dir / "engine-events.jsonl")
    runner = SuggestionRunner(taxonomy, logger)

    suggestions = []
    local_result = runner.suggest_batch(
        scan.tracks, MetadataSuggestionProvider(taxonomy), run_id=f"{args.run_id_prefix}-local"
    )

    cache = CountingCache(connection)
    transport = CountingTransport(
        MusicBrainzHttpTransport(user_agent=args.user_agent, timeout_seconds=15, limit=10),
        max_attempts=args.max_attempts,
    )
    provider = MusicBrainzReleaseYearProvider(
        taxonomy,
        cache,
        transport,
        min_query_interval_seconds=0.0,
    )
    network_result = runner.suggest_batch(
        scan.tracks, provider, run_id=f"{args.run_id_prefix}-network"
    )
    after = cache_stats(connection)

    for result in (local_result, network_result):
        for item in result.results:
            for s in item.suggestions:
                suggestions.append(
                    {
                        "track_path": item.track.path,
                        "tag_id": s.tag_id,
                        "confidence": s.confidence,
                        "source": s.source,
                        "evidence": s.evidence,
                        "title": item.track.title,
                        "artist": item.track.artist,
                        "album": item.track.album,
                    }
                )

    starts = sorted(a["started"] for a in transport.attempts)
    intervals = [b - a for a, b in zip(starts, starts[1:])]
    attempts_by_pair = {}
    for a in transport.attempts:
        key = f"{a['album']}\x1f{a['artist']}"
        attempts_by_pair[key] = attempts_by_pair.get(key, 0) + 1
    network_stats = {
        "cache_source": cache_source,
        "cache_rows_before": before["rows"],
        "cache_rows_after": after["rows"],
        "cache_rows_found_after": after["found"],
        "cache_rows_no_match_after": after["no_match"],
        "cache_hits_at_provider": cache.hits,
        "cache_misses_at_provider": cache.misses,
        "network_requests": len(transport.attempts),
        "unique_pairs_attempted": len(attempts_by_pair),
        "retries": sum(1 for n in attempts_by_pair.values() if n > 1),
        "transport_failures": len(transport.failures),
        "min_start_interval_seconds": round(min(intervals), 3) if intervals else None,
        "mean_start_interval_seconds": round(statistics.mean(intervals), 3) if intervals else None,
        "user_agent": args.user_agent,
        "pacing_contract_seconds": MIN_INTERVAL,
        "attempts": transport.attempts,
        "failures": transport.failures,
    }

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
        "local_suggestions": sum(len(i.suggestions) for i in local_result.results),
        "network_suggestions": sum(len(i.suggestions) for i in network_result.results),
        "network_failures": len(network_result.failures),
        "network": network_stats,
    }
    (run_dir / "scan-report.json").write_text(
        json.dumps(scan_report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (run_dir / "network-stats.json").write_text(
        json.dumps(network_stats, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (run_dir / "suggestions.json").write_text(
        json.dumps(suggestions, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (run_dir / "batches.json").write_text(
        json.dumps(
            [{"id": f"{args.run_id_prefix}-scan-batch", "status": "completed", "indexed": len(tracks)}],
            indent=2,
        ),
        encoding="utf-8",
    )

    print("indexed:", len(tracks), "scan_failures:", len(scan.failures))
    print("local suggestions:", scan_report["local_suggestions"])
    print("network suggestions:", scan_report["network_suggestions"],
          "network failures:", scan_report["network_failures"])
    print("by tag:", dict(Counter(s["tag_id"] for s in suggestions)))
    print(json.dumps({k: v for k, v in network_stats.items() if k not in ("attempts", "failures")}, indent=2))
    connection.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
