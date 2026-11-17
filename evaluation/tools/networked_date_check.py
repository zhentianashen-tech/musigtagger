"""One-shot networked date check for plan v0.2 (run on a machine with egress).

The evaluation runtime has no route to musicbrainz.org, so the v0.2 baseline
measured only the offline degradation path. This tool is the pre-acceptance
check the operator accepted: it runs the real MusicBrainz provider over the
frozen 47-track set, compares the resolved era against the v0.2 pre-labels,
and exits non-zero on a real mismatch or an unresolved work.

Exit codes: 0 = all works resolved to the expected era (year-only flags are
reported, not fatal); 2 = era mismatch or unresolved works (unless
``--allow-abstain``); 3 = network unavailable (no pair resolved).
"""

from __future__ import annotations

import argparse
import json
import sys
import unicodedata
from collections import Counter
from pathlib import Path

from musigtagger.contracts import TaxonomyLoader
from musigtagger.db import initialize_database
from musigtagger.engine import (
    LibraryScanner,
    MusicBrainzReleaseYearProvider,
    NetworkLookupError,
    ReleaseDateCache,
)
from musigtagger.engine.metadata import _normalise as normalise_text

DEFAULT_INPUT = Path("/test-data/music-working/eval-input-ncm-remux")
DEFAULT_TAXONOMY = Path("taxonomy")
DEFAULT_MANIFEST = Path("evaluation/fixtures/fixed-set-47-v1.json")
DEFAULT_PRELABELS = Path("evaluation/fixtures/prelabels-v0.2-works.json")


def nfc(value: str) -> str:
    return unicodedata.normalize("NFC", value)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--taxonomy", type=Path, default=DEFAULT_TAXONOMY)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--prelabels", type=Path, default=DEFAULT_PRELABELS)
    parser.add_argument("--out", type=Path, default=Path("networked-date-check.json"))
    parser.add_argument(
        "--allow-abstain",
        action="store_true",
        help="treat unresolved works as warnings (known score-release-group case)",
    )
    args = parser.parse_args()

    taxonomy = TaxonomyLoader.load(args.taxonomy, version="1.0.0")
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    prelabels = json.loads(args.prelabels.read_text(encoding="utf-8"))
    expected_year_by_work = {
        work["work_key"]: work["expected"]["release_year"]
        for work in prelabels["works"]
    }
    expected_era_by_work = {
        work["work_key"]: work["expected"]["era"] for work in prelabels["works"]
    }
    track_by_path = {
        nfc(track["canonical_path"]): track for track in manifest["tracks"]
    }

    connection = initialize_database(":memory:")
    scan = LibraryScanner(connection).scan_directory(args.input)
    provider = MusicBrainzReleaseYearProvider(
        taxonomy, ReleaseDateCache(connection)
    )

    records = []
    for track in scan.tracks:
        path_key = nfc(track.path)
        frozen = track_by_path.get(path_key)
        work_key = frozen["work_key"] if frozen else None
        expected_year = expected_year_by_work.get(work_key)
        expected_era = expected_era_by_work.get(work_key)
        try:
            suggestions = provider.suggest(track)
        except NetworkLookupError as exc:
            records.append(
                {
                    "path": track.path,
                    "work_key": work_key,
                    "album": track.album,
                    "artist": track.artist,
                    "status": "network_error",
                    "error": str(exc)[:300],
                    "expected_era": expected_era,
                    "expected_year": expected_year,
                }
            )
            continue
        era = next((s for s in suggestions if s.tag_id.startswith("era.")), None)
        if era is None:
            records.append(
                {
                    "path": track.path,
                    "work_key": work_key,
                    "album": track.album,
                    "artist": track.artist,
                    "status": "unresolved",
                    "expected_era": expected_era,
                    "expected_year": expected_year,
                }
            )
            continue
        year = None
        for token in era.evidence.replace("(", " ").replace(")", " ").split():
            if token.isdigit() and len(token) == 4:
                year = int(token)
                break
        flagged = "FLAGGED:" in era.evidence
        records.append(
            {
                "path": track.path,
                "work_key": work_key,
                "album": track.album,
                "artist": track.artist,
                "status": "resolved",
                "era": era.tag_id,
                "expected_era": expected_era,
                "year": year,
                "expected_year": expected_year,
                "year_matches_label": year == expected_year,
                "era_matches_label": era.tag_id == expected_era,
                "flagged": flagged,
                "evidence": era.evidence,
            }
        )

    resolved = [r for r in records if r["status"] == "resolved"]
    unresolved = [r for r in records if r["status"] == "unresolved"]
    network_errors = [r for r in records if r["status"] == "network_error"]
    era_mismatches = [r for r in resolved if not r.get("era_matches_label", False)]
    year_mismatches = [r for r in resolved if not r.get("year_matches_label", False)]
    unique_pairs = {
        (normalise_text(r["album"] or ""), normalise_text(r["artist"] or ""))
        for r in records
    }

    if not resolved and network_errors:
        status = "network_unavailable"
        exit_code = 3
    elif era_mismatches or (unresolved and not args.allow_abstain):
        status = "fail"
        exit_code = 2
    else:
        status = "pass"
        exit_code = 0

    summary = {
        "schema": "musigtagger.networked-date-check.v1",
        "status": status,
        "input": str(args.input),
        "taxonomy_version": taxonomy.version,
        "instances": len(records),
        "unique_album_artist_pairs": len(unique_pairs),
        "resolved_instances": len(resolved),
        "unresolved_instances": len(unresolved),
        "network_error_instances": len(network_errors),
        "era_mismatches": len(era_mismatches),
        "year_mismatches_same_era": len(year_mismatches),
        "flagged_instances": sum(1 for r in resolved if r.get("flagged")),
        "era_counts": dict(Counter(r["era"] for r in resolved)),
        "expected_era_counts": dict(Counter(r["expected_era"] for r in records)),
        "work_resolution": {
            work: {
                "resolved": sum(1 for r in resolved if r["work_key"] == work),
                "unresolved": sum(1 for r in unresolved if r["work_key"] == work),
                "years": sorted({r["year"] for r in resolved if r["work_key"] == work}),
                "expected_year": expected_year_by_work.get(work),
            }
            for work in sorted(expected_year_by_work)
        },
        "abstain_allowed": args.allow_abstain,
    }
    payload = {"summary": summary, "tracks": records}
    args.out.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"\nfull report: {args.out}")

    if status == "network_unavailable":
        print(
            "\nNETWORK UNAVAILABLE: no MusicBrainz lookup succeeded. Run this on a "
            "machine with egress before final Phase-1 acceptance.",
            file=sys.stderr,
        )
    for r in unresolved[:10]:
        print(
            f"UNRESOLVED: {r['work_key']} | {r['album']!r} | {r['artist']!r}",
            file=sys.stderr,
        )
    for r in era_mismatches[:10]:
        print(
            f"ERA MISMATCH: {r['work_key']} -> {r['era']} (expected {r['expected_era']})",
            file=sys.stderr,
        )
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
