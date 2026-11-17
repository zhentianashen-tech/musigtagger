"""Plan-v0.1 metrics computed from events + ground truth.

Primary metric: per-category suggestion precision with counts (n=47 is a
small sample — percentages alone over-read single-category results).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from .events import EventReadResult
from .findings import Classification, Finding, FindingList, Severity
from .groundtruth import HandCheckReadResult


@dataclass
class CategoryCounts:
    """Decision counts for one category (facet) or the overall roll-up."""

    suggested: int = 0
    checked: int = 0
    accepted: int = 0
    rejected: int = 0
    modified: int = 0
    unchecked: int = 0

    @property
    def precision(self) -> float | None:
        """accepted / checked decisions; None when nothing was checked."""
        if self.checked == 0:
            return None
        return self.accepted / self.checked


@dataclass
class ConformanceResult:
    total_tag_refs: int = 0
    unknown_refs: list[str] = field(default_factory=list)
    genre_depth_violations: list[str] = field(default_factory=list)

    @property
    def conformance(self) -> float | None:
        if self.total_tag_refs == 0:
            return None
        bad = len(self.unknown_refs) + len(self.genre_depth_violations)
        return (self.total_tag_refs - bad) / self.total_tag_refs


@dataclass
class QualityResult:
    """The computed plan-v0.1 quality metrics plus the findings they raised."""

    per_category: dict[str, CategoryCounts] = field(default_factory=dict)
    per_source: dict[str, CategoryCounts] = field(default_factory=dict)
    overall: CategoryCounts = field(default_factory=CategoryCounts)
    coverage: float | None = None
    coverage_numerator: int = 0
    coverage_denominator: int = 0
    coverage_denominator_source: str = ""
    modifies_per_track: float | None = None
    rejects_per_track: float | None = None
    app_edits_per_track: float | None = None
    crosscheck_compared: int = 0
    crosscheck_agreements: int = 0
    crosscheck_disagreements: list[str] = field(default_factory=list)
    conformance: ConformanceResult = field(default_factory=ConformanceResult)
    ground_truth_present: bool = False
    findings: FindingList = field(default_factory=FindingList)


def load_taxonomy(directory: str | Path, version: str) -> tuple[Any | None, str | None]:
    """Load the pinned taxonomy via the contract loader (read-only use).

    Returns (taxonomy, error). The harness never re-implements validation;
    CONTRACTS.md §1.3 names TaxonomyLoader as the only supported reader.
    """
    try:
        from musigtagger.contracts import TaxonomyLoader
    except ImportError as exc:  # pragma: no cover - environment problem
        return None, f"musigtagger.contracts not importable: {exc}"
    try:
        return TaxonomyLoader.load(directory, version=version), None
    except Exception as exc:  # noqa: BLE001 - surface any loader failure as data
        return None, f"taxonomy load failed ({directory}, {version}): {exc}"


def _genre_depth(tag_id: str, taxonomy: Any) -> int | None:
    """Depth of a genre tag via parent links (1 = root); None if unresolvable."""
    depth = 1
    current = tag_id
    seen = {current}
    while True:
        tag = taxonomy.tag(current)
        parent = getattr(tag, "parent", None)
        if parent is None:
            return depth
        if parent in seen:
            return depth  # cycle guard; malformed taxonomy is reported elsewhere
        seen.add(parent)
        current = parent
        depth += 1


def check_conformance(
    events: EventReadResult,
    hand_check: HandCheckReadResult | None,
    taxonomy: Any | None,
    findings: FindingList,
) -> ConformanceResult:
    """Validate every referenced tag id; genre depth must stay <= 2."""
    result = ConformanceResult()
    refs: list[tuple[str, str]] = []  # (tag_id, origin description)
    for event in events.suggestions:
        refs.append((event.tag_id, f"suggestion on {event.track_path}"))
    for outcome in events.outcomes:
        if outcome.final_tag_id:
            refs.append((outcome.final_tag_id, f"review outcome on {outcome.track_path}"))
    if hand_check is not None:
        for decision in hand_check.decisions:
            if decision.modified_tag_id:
                refs.append(
                    (decision.modified_tag_id, f"hand-check correction on {decision.track_path}")
                )
    result.total_tag_refs = len(refs)
    if taxonomy is None:
        findings.add(
            Finding(
                severity=Severity.HIGH,
                classification=Classification.EVALUATION_DATA,
                summary="Taxonomy could not be loaded; conformance not verifiable",
                evidence="see loader error in report header",
                responsible_role="Evaluation & Review Agent",
            )
        )
        return result
    for tag_id, origin in refs:
        if not taxonomy.has_tag(tag_id):
            result.unknown_refs.append(f"{tag_id} ({origin})")
            findings.add(
                Finding(
                    severity=Severity.HIGH,
                    classification=Classification.ENGINE_DEFECT,
                    summary=f"Unknown tag id referenced: {tag_id}",
                    evidence=origin,
                    reproduction="grep the event stream for this tag id",
                    responsible_role="Tagging Engine Engineer",
                )
            )
            continue
        if tag_id.startswith("genre."):
            depth = _genre_depth(tag_id, taxonomy)
            if depth is not None and depth > 2:
                result.genre_depth_violations.append(f"{tag_id} depth={depth} ({origin})")
                findings.add(
                    Finding(
                        severity=Severity.HIGH,
                        classification=Classification.ENGINE_DEFECT,
                        summary=f"Genre tag deeper than depth 2: {tag_id} (depth {depth})",
                        evidence=origin,
                        responsible_role="Tagging Engine Engineer",
                    )
                )
    return result


def compute_quality(
    events: EventReadResult,
    hand_check: HandCheckReadResult | None,
    taxonomy: Any | None,
    scan_report: Mapping[str, Any] | None = None,
) -> QualityResult:
    """Compute the plan-v0.1 quality metrics from events + ground truth."""
    result = QualityResult()

    if events.malformed_lines or events.invalid_records:
        result.findings.add(
            Finding(
                severity=Severity.LOW,
                classification=Classification.APP_INTEGRATION_DEFECT,
                summary=(
                    f"Event stream has {events.malformed_lines} malformed line(s) and "
                    f"{len(events.invalid_records)} invalid record(s)"
                ),
                evidence="; ".join(events.invalid_records[:10]),
                responsible_role="Application & Integration Engineer",
            )
        )

    decisions_by_key = hand_check.by_key if hand_check is not None else {}
    result.ground_truth_present = bool(decisions_by_key)

    if hand_check is not None and hand_check.problems:
        result.findings.add(
            Finding(
                severity=Severity.MEDIUM,
                classification=Classification.EVALUATION_DATA,
                summary=f"Hand-check log has {len(hand_check.problems)} invalid row(s)",
                evidence="; ".join(hand_check.problems[:10]),
                responsible_role="Evaluation & Review Agent",
            )
        )

    # -- per-category / per-source precision (primary metric, with counts) ----
    def bucket(table: dict[str, CategoryCounts], key: str) -> CategoryCounts:
        return table.setdefault(key, CategoryCounts())

    unmatched_decisions: list[str] = []
    for event in events.suggestions:
        for table, key in (
            (result.per_category, event.category),
            (result.per_source, event.source),
        ):
            counts = bucket(table, key)
            counts.suggested += 1
        result.overall.suggested += 1
        decision = decisions_by_key.get((event.track_path, event.tag_id))
        for counts in (
            bucket(result.per_category, event.category),
            bucket(result.per_source, event.source),
            result.overall,
        ):
            if decision is None:
                counts.unchecked += 1
            else:
                counts.checked += 1
                if decision.decision == "accept":
                    counts.accepted += 1
                elif decision.decision == "reject":
                    counts.rejected += 1
                elif decision.decision == "modify":
                    counts.modified += 1

    if hand_check is not None:
        suggestion_keys = {(e.track_path, e.tag_id) for e in events.suggestions}
        for decision in hand_check.decisions:
            if decision.key not in suggestion_keys:
                unmatched_decisions.append(f"{decision.track_path} :: {decision.tag_id}")
        if unmatched_decisions:
            result.findings.add(
                Finding(
                    severity=Severity.MEDIUM,
                    classification=Classification.EVALUATION_DATA,
                    summary=(
                        f"{len(unmatched_decisions)} hand-check decision(s) match no "
                        "suggestion event"
                    ),
                    evidence="; ".join(unmatched_decisions[:10]),
                    responsible_role="Evaluation & Review Agent",
                )
            )

    # -- coverage: tracks with >= 1 usable tag --------------------------------
    tracks_with_usable: set[str] = set()
    if decisions_by_key:
        for decision in hand_check.decisions:
            if decision.decision in ("accept", "modify"):
                tracks_with_usable.add(decision.track_path)
    else:
        # No ground truth yet: fall back to app review outcomes as a lower bound.
        for outcome in events.outcomes:
            if outcome.to_status in ("accepted", "edited", "applied"):
                tracks_with_usable.add(outcome.track_path)
    if scan_report is not None and "indexed" in scan_report:
        denominator = int(scan_report.get("indexed") or 0)
        source = "scan report (indexed tracks)"
    else:
        denominator = len(events.distinct_tracks)
        source = "distinct tracks in event stream (no scan report supplied)"
    result.coverage_numerator = len(tracks_with_usable)
    result.coverage_denominator = denominator
    result.coverage_denominator_source = source
    result.coverage = (len(tracks_with_usable) / denominator) if denominator else None

    # -- correction burden -----------------------------------------------------
    checked_tracks = {d.track_path for d in (hand_check.decisions if hand_check else [])}
    if hand_check is not None and checked_tracks:
        modifies = sum(1 for d in hand_check.decisions if d.decision == "modify")
        rejects = sum(1 for d in hand_check.decisions if d.decision == "reject")
        result.modifies_per_track = modifies / len(checked_tracks)
        result.rejects_per_track = rejects / len(checked_tracks)
    app_edits = [o for o in events.outcomes if o.to_status == "edited"]
    if events.distinct_tracks:
        result.app_edits_per_track = len(app_edits) / len(events.distinct_tracks)

    # -- cross-check: hand-check vs the app's own review outcomes --------------
    app_decision_by_key: dict[tuple[str, str], str] = {}
    for outcome in events.outcomes:
        if outcome.to_status in ("accepted", "edited", "rejected", "applied"):
            app_decision_by_key[(outcome.track_path, outcome.original_tag_id)] = (
                outcome.to_status
            )
    agree_map = {"accept": {"accepted", "applied"}, "modify": {"edited"}, "reject": {"rejected"}}
    if hand_check is not None:
        for decision in hand_check.decisions:
            app_status = app_decision_by_key.get(decision.key)
            if app_status is None:
                continue
            result.crosscheck_compared += 1
            if app_status in agree_map.get(decision.decision, set()):
                result.crosscheck_agreements += 1
            else:
                result.crosscheck_disagreements.append(
                    f"{decision.track_path} :: {decision.tag_id}: "
                    f"evaluator={decision.decision} vs app={app_status}"
                )

    # -- taxonomy conformance ---------------------------------------------------
    result.conformance = check_conformance(events, hand_check, taxonomy, result.findings)
    return result


# ---------------------------------------------------------------------------
# Batch completion (gating robustness metric, plan v0.1 §1)
# ---------------------------------------------------------------------------

TERMINAL_OK = ("completed", "failed")  # 'failed' = per-track errors logged, batch terminated cleanly


@dataclass
class BatchCompletionResult:
    total: int = 0
    completed: int = 0
    incomplete: list[str] = field(default_factory=list)

    @property
    def rate(self) -> float | None:
        return (self.completed / self.total) if self.total else None


def compute_batch_completion(batches: list[Mapping[str, Any]]) -> BatchCompletionResult:
    """Share of batches that ran to a terminal state without crashing mid-run.

    A batch recorded as ``failed`` still counts as complete: per-track failures
    are skipped-and-logged by design (CONTRACTS.md §3.6). A batch with no
    terminal status, or an explicit ``crashed`` marker, did not complete.
    """
    result = BatchCompletionResult(total=len(batches))
    for batch in batches:
        batch_id = str(batch.get("id", "?"))
        status = str(batch.get("status", "")).lower()
        if status in TERMINAL_OK:
            result.completed += 1
        else:
            result.incomplete.append(f"{batch_id}: status={status or 'missing'}")
    return result


def load_batches(path: str | Path) -> list[Mapping[str, Any]]:
    """Load batch/run records: a JSON list, or an object with a ``batches`` key."""
    with Path(path).open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if isinstance(data, Mapping):
        data = data.get("batches", [])
    if not isinstance(data, list):
        raise ValueError(f"{path}: expected a JSON list of batch records")
    return [dict(item) for item in data]


def load_scan_report(path: str | Path) -> Mapping[str, Any]:
    """Load a scan summary (``indexed`` is used as the coverage denominator)."""
    with Path(path).open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, Mapping):
        raise ValueError(f"{path}: expected a JSON object")
    return data
