"""Read-only precondition probe for the frozen evaluation input.

Verifies (a) every frozen-manifest entry matches the file on disk by SHA-256 and
size, (b) the manifest's own content hash, and (c) which local year/date
evidence actually exists: embedded date tags, filenames, title text and album
text. This is the audit behind the era-coverage statement in the report.

Never writes into the input or source directories.

Usage:
    PYTHONPATH=evaluation:src python evaluation/tools/frozen_input_probe.py \
        --manifest evaluation/fixtures/fixed-set-47-v1.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

from mutagen import File as MutagenFile

YEAR_RE = re.compile(r"(?<!\d)(19\d{2}|20\d{2})(?!\d)")
DATE_TAG_KEYS = ("TDRC", "TDRL", "TDOR", "TYER", "date", "year", "originaldate")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def probe(manifest_path: Path) -> dict:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    tracks = manifest["tracks"]

    canonical = json.dumps(
        tracks, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    recomputed = hashlib.sha256(canonical).hexdigest()

    report: dict = {
        "manifest_version": manifest.get("manifest_version"),
        "declared_content_sha256": manifest.get("content_sha256"),
        "recomputed_content_sha256": recomputed,
        "manifest_hash_match": recomputed == manifest.get("content_sha256"),
        "tracks": len(tracks),
        "manifest_stats": manifest.get("stats"),
        "missing_files": [],
        "hash_or_size_mismatches": [],
        "core_tag_presence": {"title": 0, "artist": 0, "album": 0, "genre": 0},
        "tag_keys": {},
        "embedded_date_tags": [],
        "filename_year_matches": [],
        "title_year_matches": [],
        "album_year_matches": [],
    }
    tag_keys: dict[str, int] = report["tag_keys"]

    for track in tracks:
        path = Path(track["canonical_path"])
        if not path.exists():
            report["missing_files"].append(str(path))
            continue
        size = path.stat().st_size
        digest = sha256(path)
        if size != track.get("remux_size_bytes") or digest != track.get("remux_sha256"):
            report["hash_or_size_mismatches"].append(
                {
                    "path": str(path),
                    "size_ok": size == track.get("remux_size_bytes"),
                    "sha_ok": digest == track.get("remux_sha256"),
                }
            )

        audio = MutagenFile(path)
        tags = getattr(audio, "tags", None) or {}
        for key in tags.keys():
            tag_keys[key] = tag_keys.get(key, 0) + 1

        def first(*names):
            for name in names:
                try:
                    value = tags.get(name)
                except Exception:  # noqa: BLE001 - a malformed frame must not abort the audit
                    value = None
                if value:
                    return value
            return None

        title = first("TIT2", "title")
        artist = first("TPE1", "artist")
        album = first("TALB", "album")
        genre = first("TCON", "genre")
        for name, value in (
            ("title", title),
            ("artist", artist),
            ("album", album),
            ("genre", genre),
        ):
            if value:
                report["core_tag_presence"][name] += 1

        for key in tags.keys():
            if key in DATE_TAG_KEYS or key.upper().startswith("TDR"):
                value = tags.get(key)
                if value:
                    report["embedded_date_tags"].append(
                        {"file": path.name, "key": key, "value": str(value)}
                    )

        stem = path.stem
        if YEAR_RE.search(stem):
            report["filename_year_matches"].append(
                {"file": path.name, "match": YEAR_RE.search(stem).group(0)}
            )
        if title and YEAR_RE.search(str(title)):
            report["title_year_matches"].append({"file": path.name, "title": str(title)})
        if album and YEAR_RE.search(str(album)):
            report["album_year_matches"].append({"file": path.name, "album": str(album)})

    report["verification"] = (
        "PASS"
        if not report["missing_files"]
        and not report["hash_or_size_mismatches"]
        and report["manifest_hash_match"]
        else "FAIL"
    )
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        default="evaluation/fixtures/fixed-set-47-v1.json",
        help="frozen manifest JSON",
    )
    parser.add_argument("--out", help="write the JSON report here instead of stdout")
    args = parser.parse_args(argv)

    report = probe(Path(args.manifest))
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if report["verification"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
