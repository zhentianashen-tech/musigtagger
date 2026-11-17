"""Markdown evaluation report renderer (Evaluation Plan v0.1 §4).

Every threshold comparison is labeled as a proposal pending human sign-off.
"""

from __future__ import annotations

from typing import Any

from .findings import FindingList
from .metrics import (
    BatchCompletionResult,
    CategoryCounts,
    QualityResult,
)
from .safety import SafetyResult
from .thresholds import STATUS_LABEL, Thresholds

NOT_COMPUTED = "not computed"


def _pct(value: float | None) -> str:
    return f"{value * 100:.1f}%" if value is not None else NOT_COMPUTED


def _verdict(passed: bool | None) -> str:
    if passed is None:
        return f"⚠️ {NOT_COMPUTED} ({STATUS_LABEL})"
    return ("✅ meets" if passed else "❌ fails") + f" proposed threshold ({STATUS_LABEL})"


def _meets(value: float | None, minimum: float) -> bool | None:
    return None if value is None else value >= minimum


def _category_table(per_category: dict[str, CategoryCounts]) -> list[str]:
    lines = [
        "| Category | Suggested | Checked | Accepted | Rejected | Modified | Precision (acc/checked) |",
        "|---|---|---|---|---|---|---|",
    ]
    for category in sorted(per_category):
        if category == "__overall__":
            continue
        counts = per_category[category]
        lines.append(
            f"| {category} | {counts.suggested} | {counts.checked} | {counts.accepted} "
            f"| {counts.rejected} | {counts.modified} | {_pct(counts.precision)} |"
        )
    overall = per_category.get("__overall__")
    if overall is not None:
        lines.append(
            f"| **overall** | {overall.suggested} | {overall.checked} | {overall.accepted} "
            f"| {overall.rejected} | {overall.modified} | **{_pct(overall.precision)}** |"
        )
    return lines


def render_report(
    *,
    plan_version: str,
    dataset_note: str,
    run_ids: tuple[str, ...],
    files_read: list[str],
    quality: QualityResult,
    safety: SafetyResult,
    batch_completion: BatchCompletionResult,
    thresholds: Thresholds,
    taxonomy_version: str,
    taxonomy_error: str | None,
    extra_findings: FindingList | None = None,
    extra_sections: list[str] | None = None,
) -> str:
    """Render the full markdown report."""
    quality_per_category = dict(quality.per_category)
    quality_per_category["__overall__"] = quality.overall

    precision_pass = _meets(quality.overall.precision, thresholds.suggestion_precision_min)
    coverage_pass = _meets(quality.coverage, thresholds.coverage_min)
    batch_pass = _meets(batch_completion.rate, thresholds.batch_completion_min)
    conformance_pass = _meets(
        quality.conformance.conformance, thresholds.taxonomy_conformance_min
    )

    lines: list[str] = [
        "# Music Tagger — Evaluation Report",
        "",
        f"- Evaluation plan version: **v{plan_version}**",
        f"- Dataset: {dataset_note}",
        f"- Run ids: {', '.join(run_ids) if run_ids else '(none found in event stream)'}",
        f"- Taxonomy pinned: `{taxonomy_version}`"
        + (f" — ⚠️ {taxonomy_error}" if taxonomy_error else ""),
        "",
        f"> **All thresholds below are proposals — {STATUS_LABEL}.** "
        "Nothing in this report settles an acceptance bar.",
        "",
        "## Gating summary",
        "",
        "| Metric | Measured | Proposed threshold | Verdict |",
        "|---|---|---|---|",
        (
            f"| Suggestion precision (overall) | {_pct(quality.overall.precision)} "
            f"({quality.overall.accepted}/{quality.overall.checked} checked) "
            f"| ≥ {thresholds.suggestion_precision_min:.0%} | {_verdict(precision_pass)} |"
        ),
        (
            f"| Coverage (tracks with ≥1 usable tag) | {_pct(quality.coverage)} "
            f"({quality.coverage_numerator}/{quality.coverage_denominator}) "
            f"| ≥ {thresholds.coverage_min:.0%} | {_verdict(coverage_pass)} |"
        ),
        (
            f"| Batch completion rate | {_pct(batch_completion.rate)} "
            f"({batch_completion.completed}/{batch_completion.total}) "
            f"| = {thresholds.batch_completion_min:.0%} | {_verdict(batch_pass)} |"
        ),
        (
            f"| Taxonomy conformance | {_pct(quality.conformance.conformance)} "
            f"({quality.conformance.total_tag_refs} tag refs checked) "
            f"| = {thresholds.taxonomy_conformance_min:.0%} | {_verdict(conformance_pass)} |"
        ),
        (
            f"| Safety (source protection / backup / undo) | "
            f"{'all checks passed' if safety.passed else 'FAIL'} "
            f"| zero violations | {_verdict(safety.passed)} |"
        ),
        "",
        "## 1. Suggestion precision per category (primary metric)",
        "",
        "*Reported with counts: the evaluation set is small (n=47), so a "
        "percentage resting on a handful of items must not be over-read.*",
        "",
        *_category_table(quality_per_category),
        "",
    ]
    if quality.per_source:
        lines += [
            "### Precision by suggestion source",
            "",
            "| Source | Suggested | Checked | Accepted | Rejected | Modified | Precision |",
            "|---|---|---|---|---|---|---|",
        ]
        for source in sorted(quality.per_source):
            counts = quality.per_source[source]
            lines.append(
                f"| {source} | {counts.suggested} | {counts.checked} | {counts.accepted} "
                f"| {counts.rejected} | {counts.modified} | {_pct(counts.precision)} |"
            )
        lines.append("")
    if not quality.ground_truth_present:
        lines += [
            f"⚠️ **Ground truth missing** — no hand-check decisions were supplied, "
            f"so precision is {NOT_COMPUTED} and this report cannot pass. "
            "The external verifying agent's hand-check log is the ground truth "
            "(plan v0.1 §2).",
            "",
        ]
    lines += [
        "## 2. Coverage",
        "",
        f"- Tracks with ≥1 usable tag: **{quality.coverage_numerator}**",
        f"- Denominator: **{quality.coverage_denominator}** ({quality.coverage_denominator_source})",
        f"- Coverage: **{_pct(quality.coverage)}** — {_verdict(coverage_pass)}",
        "",
        "## 3. Correction burden",
        "",
        f"- Modifications per checked track: "
        f"{f'{quality.modifies_per_track:.2f}' if quality.modifies_per_track is not None else NOT_COMPUTED}",
        f"- Rejections per checked track: "
        f"{f'{quality.rejects_per_track:.2f}' if quality.rejects_per_track is not None else NOT_COMPUTED}",
        f"- App-side edits per track (cross-check from review outcomes): "
        f"{f'{quality.app_edits_per_track:.2f}' if quality.app_edits_per_track is not None else NOT_COMPUTED}",
        "",
        "## 4. Batch completion (gating robustness metric)",
        "",
        f"- Batches observed: {batch_completion.total}; "
        f"completed without mid-run crash: {batch_completion.completed} "
        f"(rate {_pct(batch_completion.rate)}) — {_verdict(batch_pass)}",
    ]
    if batch_completion.incomplete:
        lines += ["", "Incomplete batches:", ""]
        lines += [f"- {item}" for item in batch_completion.incomplete]
    lines += [
        "",
        "## 5. Taxonomy conformance",
        "",
        f"- Tag references checked: {quality.conformance.total_tag_refs}",
        f"- Unknown tag ids: {len(quality.conformance.unknown_refs)}",
        f"- Genre depth violations (depth > 2): {len(quality.conformance.genre_depth_violations)}",
        f"- Conformance: {_pct(quality.conformance.conformance)} — {_verdict(conformance_pass)}",
    ]
    if quality.conformance.unknown_refs:
        lines += ["", "Unknown refs (sample):", ""]
        lines += [f"- `{ref}`" for ref in quality.conformance.unknown_refs[:20]]
    if quality.conformance.genre_depth_violations:
        lines += ["", "Depth violations:", ""]
        lines += [f"- `{ref}`" for ref in quality.conformance.genre_depth_violations[:20]]
    lines += [
        "",
        "## 6. Safety",
        "",
        f"- Evidence records read: {safety.records_read}",
        "",
        "| Check | Result | Detail |",
        "|---|---|---|",
    ]
    for check in safety.checks:
        lines.append(
            f"| {check.name} | {'✅ pass' if check.passed else '❌ FAIL'} | {check.detail} |"
        )
    lines += [
        "",
        "Proposed thresholds: zero writes to the source library, zero corruption "
        f"incidents, undo verified on every sampled case ({STATUS_LABEL}).",
        "",
        "## 7. Cross-check: evaluator decisions vs app review outcomes",
        "",
        f"- Comparable decisions: {quality.crosscheck_compared}; "
        f"agreements: {quality.crosscheck_agreements}",
    ]
    if quality.crosscheck_disagreements:
        lines += ["", "Disagreements:", ""]
        lines += [f"- {item}" for item in quality.crosscheck_disagreements[:20]]
    lines += ["", "## 8. Defects and findings (severity order)", ""]
    findings = FindingList()
    findings.extend(quality.findings.items)
    findings.extend(safety.findings.items)
    if extra_findings is not None:
        findings.extend(extra_findings.items)
    if findings.items:
        lines += [
            "| Severity | Classification | Finding | Responsible role |",
            "|---|---|---|---|",
        ]
        for finding in findings.ordered():
            lines.append(
                f"| {finding.severity.value} | {finding.classification.value} "
                f"| {finding.summary} | {finding.responsible_role or '—'} |"
            )
        lines += ["", "### Reproduction evidence", ""]
        for finding in findings.ordered():
            if finding.evidence or finding.reproduction:
                lines.append(f"- **{finding.summary}**")
                if finding.evidence:
                    lines.append(f"  - Evidence: {finding.evidence}")
                if finding.reproduction:
                    lines.append(f"  - Reproduction: {finding.reproduction}")
    else:
        lines.append("None recorded.")
    lines += [
        "",
        "## 9. Limitations",
        "",
        "- Sample size: the fixed evaluation set is 47 files; per-category "
        "precision may rest on very few items. Counts are reported alongside "
        "percentages for this reason.",
        "- The library comes from one source/folder; its genre and era "
        "distribution may not represent future batches.",
        "- Ground truth is a single external evaluator; reasons on "
        "rejections/modifications keep drift auditable.",
        "",
        "## 10. Evidence artifacts",
        "",
        "- Event stream files read:",
        *[f"  - `{path}`" for path in files_read],
        "- Evaluator hand-check log (ground truth): see `--hand-check` input.",
        "- Tagging-history log (the app's own §4 event stream) cross-checked in §7.",
        "- Safety test notes: see `--safety-evidence` input and §6.",
    ]
    if extra_sections:
        lines += ["", *extra_sections]
    lines.append("")
    return "\n".join(lines)
