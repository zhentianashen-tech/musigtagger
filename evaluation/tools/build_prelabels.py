"""Validate the v0.2 per-work pre-labels and build the 47-row worksheet."""

import csv
import json
from collections import Counter
from datetime import datetime
from pathlib import Path

from musigtagger.contracts import TaxonomyLoader

REPO = Path(__file__).resolve().parents[2]
FIX = REPO / "evaluation/fixtures"
MANIFEST = FIX / "fixed-set-47-v1.json"
PRELABELS = FIX / "prelabels-v0.2-works.json"
WORKSHEET = FIX / "track-pre-label-worksheet-v0.2.csv"
VALIDATION = FIX / "prelabels-v0.2-validation.json"
TAXONOMY = REPO / "taxonomy"

DISCLOSED_TITLE = "Soda Pop"

FIELDS = [
    "row", "track_id", "work_key", "canonical_path", "title", "artist", "album",
    "album_edition", "variant", "label_scope", "derived_from_work", "blind_status",
    "expected_genre_primary", "expected_genre_secondary", "expected_era",
    "expected_release_year", "expected_origin", "expected_mood", "expected_activity",
    "label_confidence", "release_year_confidence", "evidence_basis",
    "release_date_evidence", "evaluator", "labeled_at", "audit_note", "notes",
]


def depth(taxonomy, tag_id):
    if not tag_id.startswith("genre."):
        return None
    d = 1
    current = tag_id
    seen = {current}
    while True:
        tag = taxonomy.tag(current)
        parent = getattr(tag, "parent", None)
        if parent is None:
            return d
        if parent in seen:
            return d
        seen.add(parent)
        current = parent
        d += 1


def main():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    pre = json.loads(PRELABELS.read_text(encoding="utf-8"))
    taxonomy = TaxonomyLoader.load(TAXONOMY, version="1.0.0")

    issues = []
    manifest_works = {}
    for track in manifest["tracks"]:
        manifest_works.setdefault(track["work_key"], []).append(track)

    label_works = {w["work_key"]: w for w in pre["works"]}
    if set(label_works) != set(manifest_works):
        issues.append(
            "work-key mismatch: missing=%s extra=%s"
            % (sorted(set(manifest_works) - set(label_works)), sorted(set(label_works) - set(manifest_works)))
        )

    tag_usage = Counter()
    for work_key, work in label_works.items():
        instances = manifest_works.get(work_key, [])
        if len(instances) != work["instance_count"]:
            issues.append(f"{work_key}: instance_count {work['instance_count']} != manifest {len(instances)}")
        ids = sorted(t["track_id"] for t in instances)
        if ids != sorted(work["instance_track_ids"]):
            issues.append(f"{work_key}: instance_track_ids mismatch")
        expected = work["expected"]
        genre_ids = [expected["genre_primary"]] + list(expected["genre_secondary"])
        if not 1 <= len(genre_ids) <= 3:
            issues.append(f"{work_key}: genre cardinality {len(genre_ids)} outside 1..3")
        for tag_id in genre_ids:
            if not taxonomy.has_tag(tag_id):
                issues.append(f"{work_key}: unknown genre tag {tag_id}")
            else:
                d = depth(taxonomy, tag_id)
                if d is not None and d > 2:
                    issues.append(f"{work_key}: genre depth {d} > 2 for {tag_id}")
            tag_usage[tag_id] += 1
        for key in ("era", "origin", "mood", "activity"):
            values = [expected[key]] if key == "era" and expected[key] else list(expected[key])
            for tag_id in values:
                if not taxonomy.has_tag(tag_id):
                    issues.append(f"{work_key}: unknown {key} tag {tag_id}")
                tag_usage[tag_id] += 1
        if len(expected["origin"]) > 2:
            issues.append(f"{work_key}: origin cardinality > 2")
        if not expected["era"].startswith("era."):
            issues.append(f"{work_key}: era is not an era tag")
        if "personal" in json.dumps(expected):
            issues.append(f"{work_key}: personal tag must not be pre-labeled")

    rows = []
    for track in manifest["tracks"]:
        work = label_works[track["work_key"]]
        expected = work["expected"]
        disclosed = track["title"].split(" (")[0].strip() == DISCLOSED_TITLE
        rows.append(
            {
                "row": track["row"],
                "track_id": track["track_id"],
                "work_key": track["work_key"],
                "canonical_path": track["canonical_path"],
                "title": track["title"],
                "artist": track["artist"],
                "album": track["album"],
                "album_edition": track["album_edition"],
                "variant": track["variant"] or "",
                "label_scope": "work-propagated",
                "derived_from_work": work["work_key"],
                "blind_status": "disclosed-v0.1" if disclosed else "blind",
                "expected_genre_primary": expected["genre_primary"],
                "expected_genre_secondary": ";".join(expected["genre_secondary"]),
                "expected_era": expected["era"],
                "expected_release_year": expected["release_year"],
                "expected_origin": ";".join(expected["origin"]),
                "expected_mood": ";".join(expected["mood"]),
                "expected_activity": ";".join(expected["activity"]),
                "label_confidence": work["label_confidence"],
                "release_year_confidence": work["release_year_confidence"],
                "evidence_basis": work["evidence_basis"],
                "release_date_evidence": work["release_date_evidence"],
                "evaluator": pre["evaluator"],
                "labeled_at": pre["labeled_at"],
                "audit_note": "aggregate 55/57 provider result disclosed before labelling; per-track suggestions not consulted (Soda Pop instances disclosed-v0.1)",
                "notes": work["notes"] + " [propagated from work label]",
            }
        )

    with WORKSHEET.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    validation = {
        "schema": "musigtagger.prelabels.validation.v0.2",
        "checked_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "manifest_sha256": manifest["content_sha256"],
        "works": len(label_works),
        "instances": len(rows),
        "genre_primary_counts": dict(Counter(r["expected_genre_primary"] for r in rows)),
        "era_counts": dict(Counter(r["expected_era"] for r in rows)),
        "origin_counts": dict(Counter(r["expected_origin"] or "(none)" for r in rows)),
        "release_year_counts": dict(Counter(r["expected_release_year"] for r in rows)),
        "disclosed_rows": sum(1 for r in rows if r["blind_status"] == "disclosed-v0.1"),
        "tag_usage": dict(tag_usage),
        "issues": issues,
        "valid": not issues,
    }
    VALIDATION.write_text(json.dumps(validation, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(validation, ensure_ascii=False, indent=2))
    return 0 if not issues else 2


if __name__ == "__main__":
    raise SystemExit(main())
