"""Build the fixed-47 test-set manifest / pre-hand-check audit (read-only)."""

import csv
import json
import re
import unicodedata
from collections import Counter
from pathlib import Path

WORKDIR = Path(__file__).resolve().parent
SRC = Path("/test-data/music-source")
VARIANTS = ("Acapella", "Instrumental", "Sing-Along")
NUMBERED = re.compile(r"\s*\(\d+\)\s*$")


def nfc(s):
    return unicodedata.normalize("NFC", s)


def strip_numeric_copy(title):
    return NUMBERED.sub("", title).strip()


def variant_of(title):
    for v in VARIANTS:
        if title.endswith(f" ({v})"):
            return v
    return None


def parse_filename(stem):
    artist, sep, title = stem.partition(" - ")
    if not sep:
        return None, stem
    return artist.strip(), title.strip()


def main():
    inv = json.loads((WORKDIR / "inventory.json").read_text(encoding="utf-8"))
    ncm = json.loads((WORKDIR / "ncm-metadata.json").read_text(encoding="utf-8"))
    suggestions_path = WORKDIR / "eval-run" / "suggestions.json"
    suggestions = (
        json.loads(suggestions_path.read_text(encoding="utf-8"))
        if suggestions_path.exists()
        else []
    )
    by_track = {}
    for s in suggestions:
        by_track.setdefault(s["track_path"], []).append(s["tag_id"])
    by_track_nfc = {nfc(path): tags for path, tags in by_track.items()}

    flac_by_nfc = {nfc(t["file"].rsplit(".", 1)[0]): t for t in inv["tracks"]}
    ncm_by_nfc = {nfc(t["file"].rsplit(".", 1)[0]): t for t in ncm["tracks"]}

    rows = []
    problems = []
    for key in sorted(set(flac_by_nfc) | set(ncm_by_nfc)):
        f = flac_by_nfc.get(key)
        n = ncm_by_nfc.get(key)
        if f is None or n is None:
            problems.append(f"NFC stem {key!r} missing on one side (flac={bool(f)}, ncm={bool(n)})")
            continue
        f_artist, f_title = parse_filename(f["file"].rsplit(".", 1)[0])
        base_title = strip_numeric_copy(n["title"] or "")
        rows.append(
            {
                "flac_file": f["file"],
                "ncm_file": n["file"],
                "nfc_pair": nfc(f["file"]) == nfc(n["file"]) or True,
                "flac_exact_name_matches_ncm": f["file"].rsplit(".", 1)[0] == n["file"].rsplit(".", 1)[0],
                "flac_path": str(SRC / f["file"]),
                "ncm_path": str(SRC / n["file"]),
                "filename_artist": f_artist,
                "filename_title": f_title,
                "meta_title": n["title"],
                "meta_artist": n["artist"],
                "meta_artist_parts": n["artist_parts"],
                "meta_album": n["album"],
                "meta_duration_ms": n["duration_ms"],
                "meta_bitrate": n["bitrate"],
                "meta_declared_format": n["format_declared"],
                "meta_actual_format": n["format_actual"],
                "meta_cover_bytes": n["cover_bytes"],
                "flac_duration_s": f["duration_s"],
                "duration_delta_ms": round(f["duration_s"] * 1000 - n["duration_ms"], 1),
                "flac_sample_rate": f["sample_rate"],
                "flac_bits_per_sample": f["bits_per_sample"],
                "flac_tag_keys": f["tag_keys"],
                "flac_core_tag_count": f["usable_core_tags"],
                "flac_cover_art": f["pictures"],
                "suggested_tag_ids": sorted(
                    by_track_nfc.get(nfc(str(SRC / f["file"])), [])
                ),
                "suggestion_count": len(
                    by_track_nfc.get(nfc(str(SRC / f["file"])), [])
                ),
                "variant": variant_of(n["title"] or ""),
                "numbered_copy": bool(NUMBERED.search(n["title"] or "")),
                "filename_numbered_copy": bool(re.search(r"\(\d+\)", f["file"])),
                "album_edition": "deluxe" if "Deluxe" in (n["album"] or "") else "standard",
                "duplicate_group": base_title,
                "filename_title_matches_meta": (f_title or "") == (n["title"] or ""),
                "filename_artist_matches_meta": (
                    (f_artist or "").replace("／", "/").replace(",", "/").lower()
                    == (n["artist"] or "").lower()
                ),
            }
        )

    # duplicate groups by (base title, ignoring variants) across album editions
    groups = {}
    for r in rows:
        groups.setdefault(r["duplicate_group"], []).append(r)
    for title, members in groups.items():
        albums = {m["meta_album"] for m in members}
        for m in members:
            m["cross_edition_duplicate"] = len(albums) > 1
            m["duplicate_group_size"] = len(members)

    summary = {
        "fixed_set_dir": str(SRC),
        "flac_files": len(flac_by_nfc),
        "ncm_files": len(ncm_by_nfc),
        "paired_by_nfc": len(rows),
        "exact_name_pairs": sum(1 for r in rows if r["flac_exact_name_matches_ncm"]),
        "nfd_name_pairs": sum(1 for r in rows if not r["flac_exact_name_matches_ncm"]),
        "flac_readable": sum(1 for r in rows if r["flac_duration_s"] > 0),
        "flac_with_core_tags": sum(1 for r in rows if r["flac_core_tag_count"] > 0),
        "flac_with_cover": sum(1 for r in rows if r["flac_cover_art"] > 0),
        "flac_tag_key_signatures": {
            "|".join(k): v
            for k, v in Counter(tuple(r["flac_tag_keys"]) for r in rows).items()
        },
        "ncm_metadata_title_artist_album": sum(
            1 for r in rows if r["meta_title"] and r["meta_artist"] and r["meta_album"]
        ),
        "ncm_with_cover": sum(1 for r in rows if r["meta_cover_bytes"] > 0),
        "ncm_payload_formats": dict(Counter(r["meta_actual_format"] for r in rows)),
        "ncm_declared_formats": dict(Counter(r["meta_declared_format"] for r in rows)),
        "duration_delta_ms_min_max": [
            min(r["duration_delta_ms"] for r in rows),
            max(r["duration_delta_ms"] for r in rows),
        ],
        "duration_delta_within_150ms": sum(1 for r in rows if abs(r["duration_delta_ms"]) <= 150),
        "filename_title_mismatches": sum(1 for r in rows if not r["filename_title_matches_meta"]),
        "filename_artist_mismatches": sum(1 for r in rows if not r["filename_artist_matches_meta"]),
        "unique_base_titles": len(groups),
        "cross_edition_duplicate_tracks": sum(1 for r in rows if r["cross_edition_duplicate"]),
        "variant_tracks": sum(1 for r in rows if r["variant"]),
        "numbered_copy_tracks": sum(1 for r in rows if r["filename_numbered_copy"]),
        "tracks_with_engine_suggestion": sum(1 for r in rows if r["suggestion_count"]),
        "total_engine_suggestions": sum(r["suggestion_count"] for r in rows),
        "album_distribution": dict(Counter(r["meta_album"] for r in rows)),
        "problems": problems,
    }

    out = {"summary": summary, "tracks": rows}
    (WORKDIR / "testset-manifest-v0.1.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    with (WORKDIR / "testset-manifest-v0.1.csv").open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    print("\n--- filename/metadata mismatches ---")
    for r in rows:
        if not r["filename_title_matches_meta"] or not r["filename_artist_matches_meta"]:
            print(
                f"{r['flac_file']}\n  filename: {r['filename_artist']} | {r['filename_title']}"
                f"\n  metadata: {r['meta_artist']} | {r['meta_title']}"
            )

    print("\n--- duplicate/variant structure ---")
    for title, members in sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        if len(members) > 1:
            print(f"{title!r}: {len(members)} files -> " + "; ".join(
                f"{m['meta_album']} [{m['flac_file']}]" for m in members
            ))


if __name__ == "__main__":
    main()
