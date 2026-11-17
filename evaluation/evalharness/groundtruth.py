"""Ground truth: the external evaluator's hand-check log (Evaluation Plan v0.1 §2).

The verifying agent is *outside this project* and uses computer use to inspect
each suggested tag. Their accept / reject / modify decisions ARE the ground
truth; every rejection or modification must carry a short reason so evaluator
drift stays auditable.

The harness also generates the worksheet the evaluator fills in, so the join
keys (track path + tag id) always come from the real event stream.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

DECISIONS = ("accept", "reject", "modify")


@dataclass(frozen=True)
class HandCheckDecision:
    track_path: str
    tag_id: str
    decision: str  # accept | reject | modify
    modified_tag_id: str | None = None
    reason: str = ""
    evaluator: str = ""
    checked_at: str = ""

    @property
    def key(self) -> tuple[str, str]:
        return (self.track_path, self.tag_id)

    @property
    def category(self) -> str:
        return self.tag_id.split(".", 1)[0] if "." in self.tag_id else self.tag_id


@dataclass
class HandCheckReadResult:
    decisions: list[HandCheckDecision] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    source: str = ""

    @property
    def by_key(self) -> dict[tuple[str, str], HandCheckDecision]:
        return {decision.key: decision for decision in self.decisions}


def _validate_row(record: Mapping[str, Any], where: str) -> HandCheckDecision | str:
    track_path = str(record.get("track_path") or "").strip()
    tag_id = str(record.get("tag_id") or "").strip()
    decision = str(record.get("decision") or "").strip().lower()
    modified = record.get("modified_tag_id")
    reason = str(record.get("reason") or "").strip()
    if not track_path or not tag_id:
        return f"{where}: track_path and tag_id are required"
    if decision not in DECISIONS:
        return f"{where}: decision must be one of {DECISIONS}, got {decision!r}"
    if decision == "modify" and not (modified and str(modified).strip()):
        return f"{where}: modify requires modified_tag_id"
    if decision in ("reject", "modify") and not reason:
        # Plan v0.1: a short reason per rejection/modification keeps drift auditable.
        return f"{where}: {decision} requires a short reason"
    return HandCheckDecision(
        track_path=track_path,
        tag_id=tag_id,
        decision=decision,
        modified_tag_id=str(modified).strip() if modified else None,
        reason=reason,
        evaluator=str(record.get("evaluator") or ""),
        checked_at=str(record.get("checked_at") or ""),
    )


def read_hand_check(path: str | Path) -> HandCheckReadResult:
    """Read a hand-check log in JSONL or CSV form."""
    result = HandCheckReadResult(source=str(path))
    path = Path(path)
    if not path.exists():
        result.problems.append(f"{path}: file not found")
        return result
    if path.suffix.lower() == ".csv":
        with path.open("r", encoding="utf-8", newline="") as handle:
            for index, row in enumerate(csv.DictReader(handle), start=2):
                parsed = _validate_row(row, f"{path}:{index}")
                if isinstance(parsed, HandCheckDecision):
                    result.decisions.append(parsed)
                else:
                    result.problems.append(parsed)
    else:
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
                # Blank worksheet rows (no decision yet) are skipped, not errors.
                if not str(record.get("decision") or "").strip():
                    continue
                parsed = _validate_row(record, f"{path}:{index}")
                if isinstance(parsed, HandCheckDecision):
                    result.decisions.append(parsed)
                else:
                    result.problems.append(parsed)
    return result


def build_worksheet(suggestions: Iterable[Any]) -> list[dict[str, Any]]:
    """Build blank hand-check rows from suggestion events (stable ordering).

    The external evaluator fills ``decision`` (accept/reject/modify),
    ``modified_tag_id`` (on modify), and ``reason`` (on reject/modify).
    """
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for event in sorted(suggestions, key=lambda e: (e.track_path, e.tag_id)):
        key = (event.track_path, event.tag_id)
        if key in seen:
            continue
        seen.add(key)
        rows.append(
            {
                "track_path": event.track_path,
                "tag_id": event.tag_id,
                "category": event.category,
                "source": event.source,
                "confidence": event.confidence,
                "evidence": event.evidence,
                "decision": "",
                "modified_tag_id": "",
                "reason": "",
                "evaluator": "",
                "checked_at": "",
            }
        )
    return rows


def write_worksheet(rows: Iterable[Mapping[str, Any]], path: str | Path) -> None:
    """Write the worksheet as JSONL for the external evaluator."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(dict(row), ensure_ascii=False) + "\n")
