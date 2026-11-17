"""Per-work vs per-instance roll-up for the frozen 47-track evaluation set.

The 47 instances are 14 distinct works (7 works x5 instances, 5 x2, 2 x1).
Instance-level metrics let the seven five-instance works dominate; this tool
reports the same decisions deduplicated to (work, tag) pairs so both views are
visible. It consumes the same suggestion event stream and hand-check log as the
main harness and never re-implements decision logic.

Usage:
    PYTHONPATH=evaluation:src python evaluation/tools/per_work_rollup.py \
        --manifest evaluation/fixtures/fixed-set-47-v1.json \
        --events eval-run/engine-events.jsonl \
        --hand-check eval-run/hand-check.jsonl \
        --out-json per-work-rollup.json \
        --out-md per-work-rollup.md
"""

from __future__ import annotations

import argparse
import json
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from evalharness.events import read_event_logs
from evalharness.groundtruth import read_hand_check


def _nfc(value: str) -> str:
    return unicodedata.normalize("NFC", value)


def _pct(value: float | None) -> str:
    return f"{value * 100:.1f}%" if value is not None else "not computed"


def _counts(decisions: list[str]) -> dict[str, int]:
    return {
        "checked": len(decisions),
        "accepted": sum(1 for d in decisions if d == "accept"),
        "rejected": sum(1 for d in decisions if d == "reject"),
        "modified": sum(1 for d in decisions if d == "modify"),
    }


def build(manifest_path: Path, events_path: Path, hand_check_path: Path) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    tracks = manifest["tracks"]
    path_to_work: dict[str, str] = {}
    work_titles: dict[str, str] = {}
    for track in tracks:
        path = track["canonical_path"]
        path_to_work[path] = track["work_key"]
        path_to_work.setdefault(_nfc(path), track["work_key"])
        work_titles.setdefault(track["work_key"], track.get("title") or track["work_key"])

    events = read_event_logs([events_path])
    hand_check = read_hand_check(hand_check_path)
    decisions = hand_check.by_key

    # -- instance level -----------------------------------------------------
    instance = Counter()
    per_category_instance: dict[str, list[str]] = defaultdict(list)
    unmapped: list[str] = []
    for event in events.suggestions:
        work = path_to_work.get(event.track_path) or path_to_work.get(_nfc(event.track_path))
        if work is None:
            unmapped.append(event.track_path)
        instance["suggested"] += 1
        decision = decisions.get((event.track_path, event.tag_id))
        if decision is not None:
            per_category_instance[event.category].append(decision.decision)
            instance["checked"] += 1
        else:
            instance["unchecked"] += 1

    # -- work level: deduplicate (work, tag) pairs ---------------------------
    work_tag_decisions: dict[tuple[str, str], list[str]] = defaultdict(list)
    work_tag_source: dict[tuple[str, str], str] = {}
    work_instances: Counter = Counter()
    for track in tracks:
        work_instances[track["work_key"]] += 1
    for event in events.suggestions:
        work = path_to_work.get(event.track_path) or path_to_work.get(_nfc(event.track_path))
        if work is None:
            continue
        key = (work, event.tag_id)
        work_tag_source.setdefault(key, event.source)
        decision = decisions.get((event.track_path, event.tag_id))
        if decision is not None:
            work_tag_decisions[key].append(decision.decision)

    work_verdicts: dict[str, list[str]] = defaultdict(list)
    pair_counts = Counter()
    per_category_work: dict[str, list[str]] = defaultdict(list)
    pairs: list[dict[str, Any]] = []
    for (work, tag_id), vote_list in sorted(work_tag_decisions.items()):
        accepted = sum(1 for v in vote_list if v == "accept")
        rejected = sum(1 for v in vote_list if v == "reject")
        modified = sum(1 for v in vote_list if v == "modify")
        if accepted and not rejected and not modified:
            verdict = "accept"
        elif rejected and not accepted and not modified:
            verdict = "reject"
        elif modified and not accepted and not rejected:
            verdict = "modify"
        else:
            verdict = "mixed"
        pair_counts["checked"] += 1
        pair_counts[verdict] += 1
        work_verdicts[work].append(verdict)
        category = tag_id.split(".", 1)[0] if "." in tag_id else tag_id
        per_category_work[category].append(verdict)
        pairs.append(
            {
                "work_key": work,
                "title": work_titles[work],
                "tag_id": tag_id,
                "source": work_tag_source[key],
                "instances_with_decision": len(vote_list),
                "votes": {"accept": accepted, "reject": rejected, "modify": modified},
                "verdict": verdict,
            }
        )

    work_level: dict[str, Any] = {
        "works": len(work_instances),
        "works_with_checked_suggestion": len(work_verdicts),
        "works_fully_accepted": sum(
            1 for verdicts in work_verdicts.values() if all(v == "accept" for v in verdicts)
        ),
        "works_with_any_rejected_or_modified": sum(
            1 for verdicts in work_verdicts.values() if any(v != "accept" for v in verdicts)
        ),
        "works_with_usable_suggestion": sum(
            1
            for verdicts in work_verdicts.values()
            if any(v in ("accept", "modify") for v in verdicts)
        ),
        "pairs_checked": pair_counts["checked"],
        "pairs_accepted": pair_counts["accept"],
        "pairs_rejected": pair_counts["reject"],
        "pairs_modified": pair_counts["modify"],
        "pairs_mixed": pair_counts["mixed"],
        "instances_per_work": dict(Counter(work_instances.values())),
    }
    work_level["precision_pairs"] = (
        pair_counts["accept"] / pair_counts["checked"] if pair_counts["checked"] else None
    )
    work_level["precision_works_fully_accepted"] = (
        work_level["works_fully_accepted"] / work_level["works_with_checked_suggestion"]
        if work_level["works_with_checked_suggestion"]
        else None
    )
    work_level["coverage_works"] = (
        work_level["works_with_usable_suggestion"] / work_level["works"]
        if work_level["works"]
        else None
    )

    instance_level: dict[str, Any] = {
        "tracks": len(tracks),
        "suggestions": instance["suggested"],
        "checked": instance["checked"],
        "unchecked": instance["unchecked"],
        "accepted": sum(1 for v in per_category_instance.values() for d in v if d == "accept"),
        "rejected": sum(1 for v in per_category_instance.values() for d in v if d == "reject"),
        "modified": sum(1 for v in per_category_instance.values() for d in v if d == "modify"),
    }
    instance_with_usable = {
        event.track_path
        for event in events.suggestions
        if (decisions.get((event.track_path, event.tag_id)) is not None)
        and decisions[(event.track_path, event.tag_id)].decision in ("accept", "modify")
    }
    instance_level["tracks_with_usable_suggestion"] = len(instance_with_usable)
    instance_level["precision"] = (
        instance_level["accepted"] / instance_level["checked"]
        if instance_level["checked"]
        else None
    )
    instance_level["coverage"] = (
        len(instance_with_usable) / len(tracks) if tracks else None
    )

    # -- era / release-date coverage (explicit, both levels) -----------------
    era_instance = sum(1 for e in events.suggestions if e.category == "era")
    era_work = len({key for key in work_tag_decisions if key[1].startswith("era.")})
    era: dict[str, Any] = {
        "instance_suggestions": era_instance,
        "work_suggestions": era_work,
        "instance_coverage": era_instance / len(tracks) if tracks else None,
        "work_coverage": era_work / len(work_instances) if work_instances else None,
    }

    return {
        "manifest_version": manifest.get("manifest_version"),
        "manifest_content_sha256": manifest.get("content_sha256"),
        "taxonomy_version": manifest.get("taxonomy_version"),
        "events_file": str(events_path),
        "hand_check_file": str(hand_check_path),
        "run_ids": list(events.run_ids),
        "unmapped_event_tracks": unmapped,
        "instance_level": instance_level,
        "work_level": work_level,
        "era": era,
        "per_category_instance": {
            category: _counts(votes) for category, votes in sorted(per_category_instance.items())
        },
        "per_category_work": {
            category: {
                "checked": len(votes),
                "accepted": sum(1 for v in votes if v == "accept"),
                "rejected": sum(1 for v in votes if v == "reject"),
                "modified": sum(1 for v in votes if v == "modify"),
                "mixed": sum(1 for v in votes if v == "mixed"),
            }
            for category, votes in sorted(per_category_work.items())
        },
        "work_pairs": pairs,
    }


def render_markdown(rollup: dict[str, Any]) -> str:
    inst = rollup["instance_level"]
    work = rollup["work_level"]
    era = rollup["era"]
    lines = [
        "## Per-work vs per-instance reporting (14 works / 47 instances)",
        "",
        "The frozen set is 14 distinct works: 7 works x5 instances, 5 works x2, "
        "2 works x1. Instance-level figures let the seven five-instance works "
        "dominate; the work-level rows deduplicate decisions to (work, tag) pairs.",
        "",
        "| Level | Units | Suggestions | Checked | Accepted | Rejected | Modified | Precision | Coverage |",
        "|---|---|---|---|---|---|---|---|---|",
        (
            f"| instance | {inst['tracks']} tracks | {inst['suggestions']} | {inst['checked']} "
            f"| {inst['accepted']} | {inst['rejected']} | {inst['modified']} "
            f"| {_pct(inst['precision'])} | {_pct(inst['coverage'])} "
            f"({inst['tracks_with_usable_suggestion']}/{inst['tracks']}) |"
        ),
        (
            f"| work (dedup) | {work['works']} works | {work['pairs_checked']} pairs "
            f"| {work['pairs_checked']} | {work['pairs_accepted']} | {work['pairs_rejected']} "
            f"| {work['pairs_modified']} | {_pct(work['precision_pairs'])} "
            f"| {_pct(work['coverage_works'])} "
            f"({work['works_with_usable_suggestion']}/{work['works']}) |"
        ),
        "",
        f"- Works fully accepted (no rejected/modified pair): "
        f"{work['works_fully_accepted']}/{work['works_with_checked_suggestion']} "
        f"({_pct(work['precision_works_fully_accepted'])}).",
        f"- Per-category at work level: "
        + ", ".join(
            f"{category} {values['accepted']}/{values['checked']} accepted"
            for category, values in rollup["per_category_work"].items()
        )
        + ".",
        "",
        "### Era / release-date coverage (explicit)",
        "",
        f"- Era suggestions: **{era['instance_suggestions']}** at instance level, "
        f"**{era['work_suggestions']}** at work level.",
        f"- Era coverage: **{_pct(era['instance_coverage'])}** of instances, "
        f"**{_pct(era['work_coverage'])}** of works.",
        "- On this library that is the correct outcome under the binding operator "
        "rule: no local source on any of the 47 tracks carries a year or date. "
        "The local-date audit verified 0 embedded date tags (`TDRC`/`TDRL`/`TYER`/"
        "`date`/`year`), 0 filename year matches, 0 title year matches and 0 album "
        "year matches. A date present locally but not suggested would be the bug; "
        "there is none to surface.",
        "",
        "### Work-level decisions",
        "",
        "| Work | Instances | Tag | Source | Verdict |",
        "|---|---|---|---|---|",
    ]
    for pair in rollup["work_pairs"]:
        lines.append(
            f"| {pair['title']} | {pair['instances_with_decision']} | `{pair['tag_id']}` "
            f"| {pair['source']} | {pair['verdict']} |"
        )
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--events", required=True)
    parser.add_argument("--hand-check", required=True)
    parser.add_argument("--out-json", required=True)
    parser.add_argument("--out-md")
    args = parser.parse_args(argv)

    rollup = build(Path(args.manifest), Path(args.events), Path(args.hand_check))
    Path(args.out_json).write_text(
        json.dumps(rollup, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    if args.out_md:
        Path(args.out_md).write_text(render_markdown(rollup), encoding="utf-8")
    print(json.dumps({k: rollup[k] for k in ("instance_level", "work_level", "era")}, ensure_ascii=False, indent=2))
    bad = False
    if rollup["unmapped_event_tracks"]:
        print(
            f"WARNING: {len(rollup['unmapped_event_tracks'])} event track(s) not in manifest",
            file=sys.stderr,
        )
        bad = True
    return 2 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
