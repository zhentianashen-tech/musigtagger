"""Command line interface for the evaluation harness.

Subcommands:

- ``report``      — compute plan-v0.1 metrics and render the markdown report.
- ``worksheet``   — generate the blank hand-check worksheet from suggestion events.
- ``safety-demo`` — run the triggered-fault fixtures to prove the safety checks
                    actively fail the report (acceptance-criteria demonstration).

Exit codes: 0 = all gating checks pass; 2 = at least one gating check failed
(including missing ground truth / missing safety evidence); 1 = usage error.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .events import read_event_logs
from .findings import Classification, Finding, FindingList, Severity
from .groundtruth import build_worksheet, read_hand_check, write_worksheet
from .metrics import (
    compute_batch_completion,
    compute_quality,
    compute_recall,
    load_batches,
    load_scan_report,
    load_taxonomy,
)
from .prelabels import read_prelabels
from .report import render_report
from .safety import read_safety_evidence, run_safety_checks
from .thresholds import DEFAULT_THRESHOLDS, PLAN_VERSION

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


def _cmd_report(args: argparse.Namespace) -> int:
    events = read_event_logs(args.events)

    hand_check = None
    if args.hand_check:
        hand_check = read_hand_check(args.hand_check)

    taxonomy = None
    taxonomy_error = None
    if args.taxonomy_dir:
        taxonomy, taxonomy_error = load_taxonomy(args.taxonomy_dir, args.taxonomy_version)

    scan_report = None
    if args.scan_report:
        scan_report = load_scan_report(args.scan_report)

    batches = []
    if args.batches:
        batches = load_batches(args.batches)
    batch_completion = compute_batch_completion(batches)

    safety_evidence = None
    if args.safety_evidence:
        safety_evidence = read_safety_evidence(args.safety_evidence)

    quality = compute_quality(events, hand_check, taxonomy, scan_report)
    recall = None
    if args.prelabels:
        recall = compute_recall(events, read_prelabels(args.prelabels), taxonomy)
    safety = run_safety_checks(safety_evidence, events, args.source_root)

    extra_findings = FindingList()
    for spec in args.finding or []:
        parts = [part.strip() for part in spec.split("|")]
        if len(parts) != 4:
            print(f"invalid --finding (need 4 '|' separated parts): {spec}", file=sys.stderr)
            return 1
        try:
            severity = Severity(parts[0])
            classification = Classification(parts[1])
        except ValueError as exc:
            print(f"invalid --finding value: {exc}", file=sys.stderr)
            return 1
        extra_findings.add(
            Finding(
                severity=severity,
                classification=classification,
                summary=parts[2],
                responsible_role=parts[3],
            )
        )
    if not batches:
        extra_findings.add(
            Finding(
                severity=Severity.MEDIUM,
                classification=Classification.EVALUATION_DATA,
                summary="No batch/run records supplied; batch completion not evaluated",
                responsible_role="Evaluation & Review Agent",
            )
        )

    thresholds = DEFAULT_THRESHOLDS
    report = render_report(
        plan_version=PLAN_VERSION,
        dataset_note=args.dataset_note,
        run_ids=events.run_ids,
        files_read=events.files_read,
        quality=quality,
        safety=safety,
        batch_completion=batch_completion,
        thresholds=thresholds,
        taxonomy_version=args.taxonomy_version,
        taxonomy_error=taxonomy_error,
        extra_findings=extra_findings,
        extra_sections=args.extra_section or None,
        recall=recall,
    )

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report, encoding="utf-8")
    print(f"report written to {out_path}")

    # Gating: every proposed threshold that is computable must pass; anything
    # not computable (missing ground truth / evidence) fails the report.
    gating_failures: list[str] = []
    if quality.overall.precision is None:
        gating_failures.append("suggestion precision not computable (ground truth missing)")
    elif quality.overall.precision < thresholds.suggestion_precision_min:
        gating_failures.append("suggestion precision below proposed threshold")
    if quality.coverage is None:
        gating_failures.append("coverage not computable")
    elif quality.coverage < thresholds.coverage_min:
        gating_failures.append("coverage below proposed threshold")
    if batch_completion.rate is None:
        gating_failures.append("batch completion not evaluated (no batch records)")
    elif batch_completion.rate < thresholds.batch_completion_min:
        gating_failures.append("batch completion below proposed threshold")
    if quality.conformance.conformance is None:
        gating_failures.append("taxonomy conformance not verifiable")
    elif quality.conformance.conformance < thresholds.taxonomy_conformance_min:
        gating_failures.append("taxonomy conformance below proposed threshold")
    if not safety.passed:
        gating_failures.append("safety checks failed or safety evidence missing")

    if gating_failures:
        print("REPORT FAILS gating checks:", file=sys.stderr)
        for failure in gating_failures:
            print(f"  - {failure}", file=sys.stderr)
        return 2
    print("all gating checks pass against the PROPOSED thresholds (pending human sign-off)")
    return 0


def _cmd_worksheet(args: argparse.Namespace) -> int:
    events = read_event_logs(args.events)
    rows = build_worksheet(events.suggestions)
    write_worksheet(rows, args.out)
    print(f"worksheet with {len(rows)} rows written to {args.out}")
    return 0


def _cmd_safety_demo(args: argparse.Namespace) -> int:
    """Prove the safety checks actively fail on three triggered faults."""
    scenarios = [
        ("clean", "clean safety evidence must PASS"),
        ("fault-source-write", "a write under the protected source root must FAIL"),
        ("fault-missing-backup", "a write with no preceding backup must FAIL"),
        ("fault-failed-undo", "a failed undo must FAIL"),
    ]
    all_detected = True
    for name, expectation in scenarios:
        evidence_path = FIXTURES / f"safety-{name}.jsonl"
        events_path = FIXTURES / f"events-{name}.jsonl"
        if not evidence_path.exists():
            print(f"missing fixture {evidence_path}", file=sys.stderr)
            all_detected = False
            continue
        evidence = read_safety_evidence(evidence_path)
        events = read_event_logs([events_path]) if events_path.exists() else None
        result = run_safety_checks(evidence, events, args.source_root)
        expected_pass = name == "clean"
        detected = result.passed == expected_pass
        all_detected = all_detected and detected
        status = "PASS" if result.passed else "FAIL"
        mark = "✅ as expected" if detected else "❌ UNEXPECTED"
        print(f"[{status:4}] {name}: {expectation} — {mark}")
        for check in result.checks:
            if not check.passed:
                print(f"       failed check: {check.name} — {check.detail}")
    if not all_detected:
        print("safety-demo: fault detection did not behave as expected", file=sys.stderr)
        return 2
    print("safety-demo: all triggered faults actively failed the report; clean evidence passed")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="evalharness",
        description="External evaluation harness (Evaluation Plan v0.1).",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    report = sub.add_parser("report", help="compute metrics and render the markdown report")
    report.add_argument("--events", nargs="+", required=True, help="JSONL event log(s)")
    report.add_argument("--hand-check", help="hand-check log (JSONL or CSV) = ground truth")
    report.add_argument(
        "--prelabels",
        help="plan v0.2 per-instance pre-label worksheet (CSV), enables expected-tag recall",
    )
    report.add_argument("--safety-evidence", help="JSONL backup/write/undo records")
    report.add_argument("--batches", help="JSON batch/run records")
    report.add_argument("--scan-report", help="JSON scan summary (coverage denominator)")
    report.add_argument("--taxonomy-dir", default="taxonomy")
    report.add_argument("--taxonomy-version", default="1.0.0")
    report.add_argument("--source-root", default="/test-data/music-source")
    report.add_argument(
        "--dataset-note",
        default="fixed 47-file library (/test-data/music-source, read-only)",
    )
    report.add_argument(
        "--extra-section",
        action="append",
        help="additional markdown section text (repeatable)",
    )
    report.add_argument(
        "--finding",
        action="append",
        metavar="SEVERITY|CLASSIFICATION|SUMMARY|ROLE",
        help="record an upstream finding, e.g. "
        "'critical|architectural/cross-component problem|engine code absent|Lead Architect' "
        "(repeatable)",
    )
    report.add_argument("--out", required=True, help="output markdown path")
    report.set_defaults(func=_cmd_report)

    worksheet = sub.add_parser("worksheet", help="generate the hand-check worksheet")
    worksheet.add_argument("--events", nargs="+", required=True)
    worksheet.add_argument("--out", required=True)
    worksheet.set_defaults(func=_cmd_worksheet)

    demo = sub.add_parser(
        "safety-demo", help="prove safety checks actively fail on triggered faults"
    )
    demo.add_argument("--source-root", default="/test-data/music-source")
    demo.set_defaults(func=_cmd_safety_demo)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
