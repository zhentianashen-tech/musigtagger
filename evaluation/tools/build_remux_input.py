"""Build the frozen evaluation input: 47 NCM containers remuxed to MP3.

Uses the leader-accepted MUSI-13 branch (which carries MUSI-12's fixed decoder)
via ``musigtagger.ncm.decode/convert``. Read-only against /test-data/music-source;
writes the persistent remux set under /test-data/music-working. No transcoding:
the decoder's MP3 payload is written verbatim and tags/cover are attached.
"""

import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from mutagen import File as MutagenFile
from mutagen.mp3 import MP3

from musigtagger.ncm import convert, decode

SRC = Path("/test-data/music-source")
OUT = Path("/test-data/music-working/eval-input-ncm-remux")


def sha256(path):
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    started = now()
    outcomes = []
    errors = []
    for source in sorted(SRC.glob("*.ncm")):
        record = {"source": str(source), "status": "unknown"}
        try:
            track = decode(source)
            destination = OUT / f"{source.stem}{track.extension}"
            if destination.exists():
                record.update(
                    destination=str(destination),
                    status="skipped-existing",
                    format=track.format,
                )
            else:
                written = convert(track, destination)
                record.update(destination=str(written), status="converted", format=track.format)

            audio = MutagenFile(destination)
            tags = audio.tags
            tag_map = {}
            if tags is not None:
                for key in tags.keys():
                    value = tags[key]
                    tag_map[str(key)] = [str(v) for v in value] if isinstance(value, list) else str(value)
            record.update(
                title=track.metadata.title,
                artist=track.metadata.artist,
                album=track.metadata.album,
                format_declared=track.metadata.raw.get("format"),
                audio_format=type(audio).__name__ if audio is not None else None,
                duration_seconds=round(audio.info.length, 3) if audio is not None else None,
                bitrate=getattr(audio.info, "bitrate", None) if audio is not None else None,
                size_bytes=destination.stat().st_size,
                sha256=sha256(destination),
                source_sha256=sha256(source),
                embedded_tag_keys=sorted(tag_map.keys()),
                has_cover=bool(getattr(audio, "tags", None) and any(
                    k.startswith("APIC") for k in tag_map
                )),
                tags=tag_map,
            )
            outcomes.append(record)
            print(f"[ok] {source.name} -> {destination.name} ({record['size_bytes']} bytes)")
        except Exception as exc:  # noqa: BLE001 — isolate per-file faults
            record["status"] = "failed"
            record["error"] = f"{type(exc).__name__}: {exc}"
            errors.append(record)
            print(f"[fail] {source.name}: {record['error']}")

    summary = {
        "schema": "musigtagger.evaluation-input.v1",
        "source_root": str(SRC),
        "output_root": str(OUT),
        "started_at": started,
        "finished_at": now(),
        "counts": {
            "source_ncm": len(list(SRC.glob("*.ncm"))),
            "written": sum(1 for r in outcomes if r["status"] == "converted"),
            "skipped_existing": sum(1 for r in outcomes if r["status"] == "skipped-existing"),
            "failed": len(errors),
        },
        "with_title": sum(1 for r in outcomes if r.get("title")),
        "with_artist": sum(1 for r in outcomes if r.get("artist")),
        "with_album": sum(1 for r in outcomes if r.get("album")),
        "with_cover": sum(1 for r in outcomes if r.get("has_cover")),
        "format_counts": {},
        "total_bytes": sum(r.get("size_bytes", 0) for r in outcomes),
    }
    for r in outcomes:
        key = r.get("audio_format")
        summary["format_counts"][key] = summary["format_counts"].get(key, 0) + 1

    report = {"summary": summary, "tracks": outcomes, "errors": errors}
    report_path = OUT / "conversion-report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n" + json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"report: {report_path}")
    return 0 if not errors else 2


if __name__ == "__main__":
    sys.exit(main())
