"""One copy-based safety smoke test for the Phase-1 acceptance gate.

Option A (operator, 2026-11-17): instead of a full write exercise, apply one
small batch on copies under /test-data/music-working, confirm the backup, run
undo, and compare bytes. Uses the application's **real** ApplyService /
BackupManager / MutagenTagger path — no reimplementation.

Emits the harness safety-evidence JSONL (backup/write/undo) and a JSON report.
Exit 0 only when the harness safety checks pass and the files are byte-identical
after undo.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

from musigtagger.app.config import AppConfig
from musigtagger.app.factory import build_context
from musigtagger.app.tagio import MutagenTagger
from musigtagger.app.util import sha256_file
from musigtagger.contracts import TrackDescriptor

DEFAULT_INPUT = Path("/test-data/music-working/eval-input-ncm-remux")
DEFAULT_TAXONOMY = Path("taxonomy")
DEFAULT_SOURCE_ROOT = Path("/test-data/music-source")
SAMPLE = [
    "Saja Boys,Andrew 崔,Neckwav - Soda Pop.mp3",
    "TWICE - Strategy.mp3",
]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--taxonomy", type=Path, default=DEFAULT_TAXONOMY)
    parser.add_argument("--source-root", type=Path, default=DEFAULT_SOURCE_ROOT)
    parser.add_argument(
        "--work-root",
        type=Path,
        default=None,
        help="default: /test-data/music-working/safety-smoke-<timestamp>",
    )
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    work = args.work_root or Path(f"/test-data/music-working/safety-smoke-{stamp}")
    library = work / "library"
    backups = work / "backups"
    library.mkdir(parents=True, exist_ok=True)
    backups.mkdir(parents=True, exist_ok=True)
    evidence_path = args.out or (work / "safety-evidence.jsonl")
    report_path = work / "safety-smoke-report.json"

    sources = [args.input / name for name in SAMPLE]
    for source in sources:
        if not source.is_file():
            print(f"missing sample: {source}", file=sys.stderr)
            return 2
        shutil.copy2(source, library / source.name)
    source_hashes_before = {str(p): sha256_file(p) for p in sources}

    config = AppConfig(
        library_root=library,
        database_path=work / "library.sqlite3",
        backup_root=backups,
        events_path=work / "events.jsonl",
        taxonomy_dir=args.taxonomy,
        taxonomy_version="1.0.0",
        protected_roots=(args.source_root,),
    )
    context = build_context(config, providers=[])
    records: list[dict] = []
    failures: list[str] = []
    try:
        copies = [library / name for name in SAMPLE]
        originals = {str(path): path.read_bytes() for path in copies}
        track_ids = []
        for path in copies:
            descriptor = TrackDescriptor(
                path=str(path),
                title=path.stem,
                artist="safety-smoke",
                album="safety-smoke",
                genre=None,
                year=None,
                duration_seconds=None,
                format="mp3",
            )
            track_id = context.store.upsert_track(descriptor)
            suggestion_id = context.store.add_suggestion(
                track_id,
                tag_id="genre.k-pop",
                confidence=0.9,
                source="safety.smoke",
                evidence="copy-based safety smoke test",
                taxonomy_version="1.0.0",
                engine_run_id="safety-smoke",
            )
            if suggestion_id is None:
                raise RuntimeError("suggestion insert was treated as a duplicate")
            context.review.accept(suggestion_id)
            track_ids.append(track_id)

        apply_result = context.writer.apply()
        apply_batch = context.store.get_batch(apply_result.batch_id)
        backups_rows = context.store.list_backups(apply_result.batch_id)
        if apply_result.status != "completed" or apply_result.succeeded != len(copies):
            failures.append(f"apply did not complete: {apply_result!r}")
        if len(backups_rows) != len(copies):
            failures.append(f"expected {len(copies)} backups, got {len(backups_rows)}")

        tagger = MutagenTagger()
        expected_genre = context.taxonomy.tag("genre.k-pop").canonical_label
        for path in copies:
            payload = tagger.read(path)
            if expected_genre not in payload.get("TCON", []):
                failures.append(
                    f"genre tag not written to {path}: expected {expected_genre!r}, "
                    f"got {payload.get('TCON', [])!r}"
                )
            if path.read_bytes() == originals[str(path)]:
                failures.append(f"file bytes unchanged after apply: {path}")

        for row in backups_rows:
            payload = json.loads(row["prior_tags_json"])
            sidecar = config.backup_root / payload["sidecar"]
            track_path = Path(context.store.get_track(int(row["track_id"]))["path"])
            if sidecar.read_bytes() != originals[str(track_path)]:
                failures.append(f"backup sidecar does not match original: {track_path}")
            records.append(
                {
                    "kind": "backup",
                    "batch_id": str(apply_result.batch_id),
                    "track_path": str(track_path),
                    "ts": str(row["created_at"]),
                    "result": "ok",
                    "detail": f"sidecar {sidecar.name}",
                }
            )

        write_ts = str(apply_batch["completed_at"] or utc_now())
        for path in copies:
            records.append(
                {
                    "kind": "write",
                    "batch_id": str(apply_result.batch_id),
                    "track_path": str(path),
                    "ts": write_ts,
                    "result": "ok",
                    "detail": "apply batch completed",
                }
            )

        undo_result = context.writer.undo(apply_result.batch_id)
        undo_batch = context.store.get_batch(undo_result.batch_id)
        undo_ts = str(undo_batch["completed_at"] or utc_now())
        for row in context.store.list_backups(undo_result.batch_id):
            records.append(
                {
                    "kind": "backup",
                    "batch_id": str(undo_result.batch_id),
                    "track_path": str(context.store.get_track(int(row["track_id"]))["path"]),
                    "ts": str(row["created_at"]),
                    "result": "ok",
                    "detail": "undo pre-backup",
                }
            )
        for path in copies:
            records.append(
                {
                    "kind": "undo",
                    "batch_id": str(undo_result.batch_id),
                    "track_path": str(path),
                    "ts": undo_ts,
                    "result": "ok" if undo_result.status == "completed" else "failed",
                    "detail": "undo batch completed" if undo_result.status == "completed" else str(undo_result.note),
                }
            )

        if undo_result.status != "completed":
            failures.append(f"undo did not complete: {undo_result!r}")
        for path in copies:
            if path.read_bytes() != originals[str(path)]:
                failures.append(f"undo did not restore exact bytes: {path}")

        with evidence_path.open("w", encoding="utf-8") as fh:
            for record in records:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")

        from evalharness.safety import read_safety_evidence, run_safety_checks

        evidence = read_safety_evidence(evidence_path)
        safety = run_safety_checks(evidence, None, str(args.source_root))
        if not safety.passed:
            failures.append("harness safety checks failed")
        for check in safety.checks:
            print(f"[{'PASS' if check.passed else 'FAIL'}] {check.name}: {check.detail}")

        source_hashes_after = {str(p): sha256_file(p) for p in sources}
        if source_hashes_before != source_hashes_after:
            failures.append("a source file changed during the smoke test")

        report = {
            "schema": "musigtagger.safety-smoke.v1",
            "ran_at": utc_now(),
            "work_root": str(work),
            "samples": [str(p) for p in sources],
            "apply_batch_id": apply_result.batch_id,
            "apply_status": apply_result.status,
            "undo_batch_id": undo_result.batch_id,
            "undo_status": undo_result.status,
            "backups": len(backups_rows),
            "evidence_path": str(evidence_path),
            "safety_checks": [
                {"name": c.name, "passed": c.passed, "detail": c.detail} for c in safety.checks
            ],
            "source_hashes_unchanged": source_hashes_before == source_hashes_after,
            "files_restored_byte_exact": all(
                path.read_bytes() == originals[str(path)] for path in copies
            ),
            "failures": failures,
            "passed": not failures and safety.passed,
        }
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["passed"] else 2
    finally:
        context.close()


if __name__ == "__main__":
    sys.exit(main())
