"""Freeze the 47-track evaluation set (track list) for plan v0.1/v0.2 runs.

Inputs are the real artifacts:
- /test-data/music-working/eval-input-ncm-remux/conversion-report.json
- /test-data/music-source inventory (FLAC listening copies) and NCM metadata probe
Outputs a content-hashed JSON + CSV under evaluation/fixtures/.
"""

import csv
import hashlib
import json
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

from mutagen import File as MutagenFile

WORKDIR = Path(__file__).resolve().parent
REPO = WORKDIR / "musigtagger"
SRC = Path("/test-data/music-source")
REMUX = Path("/test-data/music-working/eval-input-ncm-remux")
OUT_JSON = REPO / "evaluation/fixtures/fixed-set-47-v1.json"
OUT_CSV = REPO / "evaluation/fixtures/fixed-set-47-v1.csv"
VARIANT_RE = re.compile(r" \((Acapella|Instrumental|Sing-Along)\)$")
COPY_RE = re.compile(r" \(\d+\)$")


def nfc(value):
    return unicodedata.normalize("NFC", value)


def relative_to_root(path, root):
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def main():
    conversion = json.loads((REMUX / "conversion-report.json").read_text(encoding="utf-8"))
    ncm_meta = json.loads((WORKDIR / "ncm-metadata.json").read_text(encoding="utf-8"))
    inventory = json.loads((WORKDIR / "inventory.json").read_text(encoding="utf-8"))

    meta_by_nfc = {nfc(t["file"]): t for t in ncm_meta["tracks"]}
    flac_by_nfc = {nfc(t["file"]): t for t in inventory["tracks"]}

    tracks = []
    for row in conversion["tracks"]:
        source_name = Path(row["source"]).name
        meta = meta_by_nfc[nfc(source_name)]
        raw = meta["raw"]
        destination = Path(row["destination"])
        audio = MutagenFile(destination)
        cover_sha = None
        pictures = getattr(audio, "tags", None)
        if pictures is not None:
            for key in pictures.keys():
                if key.startswith("APIC"):
                    cover_sha = hashlib.sha256(pictures[key].data).hexdigest()
                    break

        title = row["title"]
        variant_match = VARIANT_RE.search(title or "")
        base_title = VARIANT_RE.sub("", title or "").strip()
        base_title = COPY_RE.sub("", base_title).strip()
        flac = flac_by_nfc.get(nfc(Path(source_name).with_suffix(".flac").name))

        tracks.append(
            {
                "track_id": str(raw.get("musicId")),
                "canonical_path": str(destination),
                "canonical_path_relative": relative_to_root(destination, REMUX),
                "source_ncm": row["source"],
                "source_ncm_relative": relative_to_root(Path(row["source"]), SRC),
                "source_ncm_sha256": row["source_sha256"],
                "remux_sha256": row["sha256"],
                "remux_size_bytes": row["size_bytes"],
                "listening_copy_flac": str(SRC / flac["file"]) if flac else None,
                "title": title,
                "artist": row["artist"],
                "artist_parts": meta.get("artist_parts", []),
                "album": row["album"],
                "album_id": raw.get("albumId"),
                "duration_ms": meta.get("duration_ms"),
                "bitrate": row.get("bitrate"),
                "sample_rate": getattr(audio.info, "sample_rate", None) if audio is not None else None,
                "channels": getattr(audio.info, "channels", None) if audio is not None else None,
                "format": (type(audio).__name__ if audio is not None else None),
                "cover_sha256": cover_sha,
                "cover_bytes": meta.get("cover_bytes"),
                "variant": variant_match.group(1) if variant_match else None,
                "album_edition": "deluxe" if "Deluxe" in (row["album"] or "") else "standard",
                "filename_copy_suffix": bool(COPY_RE.search(Path(source_name).stem)),
                "work_key": base_title.casefold(),
                "flac_core_tags": (flac or {}).get("usable_core_tags", 0),
                "flac_cover_art": (flac or {}).get("pictures", 0),
            }
        )

    tracks.sort(key=lambda item: int(item["track_id"]) if item["track_id"].isdigit() else item["track_id"])
    for index, item in enumerate(tracks, start=1):
        item["row"] = index

    canonical = json.dumps(tracks, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    manifest_sha = hashlib.sha256(canonical).hexdigest()

    works = {t["work_key"] for t in tracks}
    base_tracks = [t for t in tracks if t["variant"] is None]
    by_work = {}
    for t in tracks:
        by_work.setdefault(t["work_key"], []).append(t)
    by_work_base = {}
    for t in base_tracks:
        by_work_base.setdefault(t["work_key"], []).append(t)
    cross_edition_instances = sum(
        1
        for t in base_tracks
        if len({m["album_edition"] for m in by_work_base[t["work_key"]]}) > 1
    )
    cross_edition_works = sum(
        1
        for members in by_work_base.values()
        if len({m["album_edition"] for m in members}) > 1
    )
    variant_works = {t["work_key"] for t in tracks if t["variant"]}
    deluxe_only_works = sum(
        1
        for members in by_work_base.values()
        if {m["album_edition"] for m in members} == {"deluxe"}
    )
    instance_counts = {}
    for members in by_work.values():
        instance_counts[len(members)] = instance_counts.get(len(members), 0) + 1

    manifest = {
        "manifest_version": "fixed-set-47-v1",
        "frozen_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "frozen_by": "Evaluation & Review Agent (MUSI-9)",
        "leader_decision": (
            "Frozen evaluation input = the metadata-preserving MUSI-12 NCM remux set "
            "under /test-data/music-working (leader-verified 2026-11-17), not the "
            "metadata-stripped FLAC transcodes. This manifest is the frozen track list."
        ),
        "work_count_note": (
            "Corrects the earlier '35 works' figure in the v0.1 report: 35 was the count "
            "of distinct titles INCLUDING variant suffixes. Distinct works after removing "
            "(Acapella)/(Instrumental)/(Sing-Along) and '(1)' suffixes = 14. Instances per "
            "work: 7 works x5, 5 works x2, 2 works x1."
        ),
        "source_root": str(SRC),
        "evaluation_input_root": str(REMUX),
        "taxonomy_version": "1.0.0",
        "stats": {
            "tracks": len(tracks),
            "unique_works": len(works),
            "works_cross_edition": cross_edition_works,
            "cross_edition_duplicate_instances": cross_edition_instances,
            "variant_instances": sum(1 for t in tracks if t["variant"]),
            "variant_works": len(variant_works),
            "deluxe_only_works": deluxe_only_works,
            "base_version_instances": len(base_tracks),
            "works_by_instance_count": {str(k): v for k, v in sorted(instance_counts.items(), reverse=True)},
            "with_title": sum(1 for t in tracks if t["title"]),
            "with_artist": sum(1 for t in tracks if t["artist"]),
            "with_album": sum(1 for t in tracks if t["album"]),
            "with_cover": sum(1 for t in tracks if t["cover_sha256"]),
            "with_genre": 0,
            "with_release_date": 0,
        },
        "content_sha256": manifest_sha,
        "tracks": tracks,
    }
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    with OUT_CSV.open("w", encoding="utf-8", newline="") as fh:
        fields = [
            "row", "track_id", "work_key", "title", "artist", "album", "album_edition",
            "variant", "filename_copy_suffix", "duration_ms", "bitrate", "cover_bytes",
            "canonical_path", "source_ncm", "remux_sha256", "source_ncm_sha256",
        ]
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for t in tracks:
            writer.writerow({k: t[k] for k in fields})

    print(json.dumps({
        "manifest": str(OUT_JSON),
        "csv": str(OUT_CSV),
        "stats": manifest["stats"],
        "content_sha256": manifest_sha,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
