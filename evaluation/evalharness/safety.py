"""Safety checks (Evaluation Plan v0.1 §1, §3).

Three gating safety properties, each of which must *actively fail* the report:

1. **Source-root protection** — zero writes to the protected read-only source
   library (operator protocol: ``/test-data/music-source`` is never written).
2. **Backup before every write batch** — no write record may exist without a
   prior backup record for the same track in the same batch.
3. **Undo restores prior state** — any failed undo, or an undone apply batch
   missing restore records for written tracks, fails the check.

The evidence is a JSONL stream of write-path records (backup / write / undo),
produced while exercising the application's write path during evaluation. The
harness additionally scans the §4 review-outcome stream for write-ish outcomes
that touch the protected root.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

from .events import EventReadResult
from .findings import Classification, Finding, FindingList, Severity

RECORD_KINDS = ("backup", "write", "undo")
WRITE_ISH_OUTCOME_STATUSES = ("applied", "undone")


@dataclass(frozen=True)
class SafetyRecord:
    kind: str  # backup | write | undo
    batch_id: str
    track_path: str
    ts: str
    result: str = "ok"  # ok | failed
    detail: str = ""


@dataclass
class SafetyReadResult:
    records: list[SafetyRecord] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)


@dataclass
class CheckOutcome:
    name: str
    passed: bool
    detail: str
    violations: list[str] = field(default_factory=list)


@dataclass
class SafetyResult:
    checks: list[CheckOutcome] = field(default_factory=list)
    records_read: int = 0
    evidence_present: bool = False
    findings: FindingList = field(default_factory=FindingList)

    @property
    def passed(self) -> bool:
        return self.evidence_present and all(check.passed for check in self.checks)


def _is_under(path: str, root: str) -> bool:
    try:
        Path(path).resolve().relative_to(Path(root).resolve())
    except (ValueError, OSError):
        return False
    return True


def read_safety_evidence(path: str | Path) -> SafetyReadResult:
    """Read backup/write/undo records (JSONL)."""
    result = SafetyReadResult()
    path = Path(path)
    if not path.exists():
        result.problems.append(f"{path}: file not found")
        return result
    with path.open("r", encoding="utf-8") as handle:
        for index, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                result.problems.append(f"{path}:{index}: malformed JSON line")
                continue
            if not isinstance(record, Mapping):
                result.problems.append(f"{path}:{index}: not a JSON object")
                continue
            kind = str(record.get("kind") or "")
            if kind not in RECORD_KINDS:
                result.problems.append(f"{path}:{index}: unknown kind {kind!r}")
                continue
            result.records.append(
                SafetyRecord(
                    kind=kind,
                    batch_id=str(record.get("batch_id") or ""),
                    track_path=str(record.get("track_path") or ""),
                    ts=str(record.get("ts") or ""),
                    result=str(record.get("result") or "ok"),
                    detail=str(record.get("detail") or ""),
                )
            )
    return result


def check_source_root_protection(
    records: Iterable[SafetyRecord],
    events: EventReadResult | None,
    source_root: str,
) -> CheckOutcome:
    """Zero write operations may touch the protected source root."""
    violations: list[str] = []
    for record in records:
        if _is_under(record.track_path, source_root):
            violations.append(
                f"{record.kind} on {record.track_path} (batch {record.batch_id})"
            )
    if events is not None:
        for outcome in events.outcomes:
            if outcome.to_status in WRITE_ISH_OUTCOME_STATUSES and _is_under(
                outcome.track_path, source_root
            ):
                violations.append(
                    f"review outcome '{outcome.to_status}' on {outcome.track_path}"
                )
        for event in events.suggestions:
            # Suggestions are reads; only flag them if the *emitter* claims a
            # write-side evidence path under the root. Kept conservative: no flag.
            _ = event
    passed = not violations
    return CheckOutcome(
        name="source-root protection (zero writes to music-source)",
        passed=passed,
        detail=(
            f"no write records under {source_root}"
            if passed
            else f"{len(violations)} write operation(s) under protected root {source_root}"
        ),
        violations=violations,
    )


def check_backup_before_write(records: Iterable[SafetyRecord]) -> CheckOutcome:
    """Every write needs a prior backup for the same track in the same batch."""
    records = list(records)
    backups: dict[tuple[str, str], str] = {}
    for record in records:
        if record.kind == "backup" and record.result == "ok":
            key = (record.batch_id, record.track_path)
            if key not in backups or record.ts < backups[key]:
                backups[key] = record.ts
    violations: list[str] = []
    for record in records:
        if record.kind != "write":
            continue
        backup_ts = backups.get((record.batch_id, record.track_path))
        if backup_ts is None:
            violations.append(
                f"write with no backup: {record.track_path} (batch {record.batch_id})"
            )
        elif backup_ts > record.ts:
            violations.append(
                f"backup timestamp after write: {record.track_path} (batch {record.batch_id})"
            )
    passed = not violations
    return CheckOutcome(
        name="backup exists before every write batch",
        passed=passed,
        detail=(
            "every write record is preceded by a backup record"
            if passed
            else f"{len(violations)} write(s) without a preceding backup"
        ),
        violations=violations,
    )


def check_undo_restores(records: Iterable[SafetyRecord]) -> CheckOutcome:
    """Undo must succeed for every written track of an undone apply batch."""
    records = list(records)
    violations: list[str] = []
    undos = [r for r in records if r.kind == "undo"]
    for record in undos:
        if record.result != "ok":
            violations.append(
                f"failed undo on {record.track_path} (batch {record.batch_id}): "
                f"{record.detail or 'no detail'}"
            )
    # Completeness: batches that contain undo records must cover every track
    # that batch wrote successfully.
    writes_by_batch: dict[str, set[str]] = {}
    for record in records:
        if record.kind == "write" and record.result == "ok":
            writes_by_batch.setdefault(record.batch_id, set()).add(record.track_path)
    ok_undos_by_batch: dict[str, set[str]] = {}
    for record in undos:
        if record.result == "ok":
            ok_undos_by_batch.setdefault(record.batch_id, set()).add(record.track_path)
    for batch_id, undone in ok_undos_by_batch.items():
        written = writes_by_batch.get(batch_id, set())
        missing = written - undone
        for track_path in sorted(missing):
            violations.append(
                f"undo batch {batch_id} missing restore for written track {track_path}"
            )
    passed = not violations
    return CheckOutcome(
        name="undo restores prior state",
        passed=passed,
        detail=(
            "all undo operations succeeded and cover the written tracks"
            if passed
            else f"{len(violations)} undo violation(s)"
        ),
        violations=violations,
    )


def run_safety_checks(
    evidence: SafetyReadResult | None,
    events: EventReadResult | None,
    source_root: str,
) -> SafetyResult:
    """Run all gating safety checks; missing evidence is itself a failure."""
    result = SafetyResult()
    records = evidence.records if evidence is not None else []
    result.records_read = len(records)
    result.evidence_present = bool(records)
    if evidence is not None and evidence.problems:
        result.findings.add(
            Finding(
                severity=Severity.MEDIUM,
                classification=Classification.EVALUATION_DATA,
                summary=f"Safety evidence has {len(evidence.problems)} invalid row(s)",
                evidence="; ".join(evidence.problems[:10]),
                responsible_role="Evaluation & Review Agent",
            )
        )
    if not records:
        result.checks.append(
            CheckOutcome(
                name="safety evidence present",
                passed=False,
                detail=(
                    "no backup/write/undo evidence supplied — safety is unverified, "
                    "which fails the report by design"
                ),
            )
        )
        return result
    checks = [
        check_source_root_protection(records, events, source_root),
        check_backup_before_write(records),
        check_undo_restores(records),
    ]
    result.checks.extend(checks)
    for check in checks:
        if not check.passed:
            result.findings.add(
                Finding(
                    severity=Severity.CRITICAL,
                    classification=Classification.APP_INTEGRATION_DEFECT,
                    summary=f"Safety check failed: {check.name}",
                    evidence="; ".join(check.violations[:10]),
                    reproduction=(
                        "re-run the evaluation write batch and inspect the safety "
                        "evidence stream"
                    ),
                    responsible_role="Application & Integration Engineer",
                )
            )
    return result
