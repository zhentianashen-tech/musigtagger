"""Generate the blank track-level pre-label worksheet for the v0.2 proposal.

Reads the frozen 47-track manifest and writes an empty worksheet (no labels).
The 5 tracks whose suggestions were already seen in the v0.1 pass are marked
``disclosed-v0.1`` so the labelling protocol's blind-status is auditable.
"""

import csv
import json
import unicodedata
from pathlib import Path

WORKDIR = Path(__file__).resolve().parent
REPO = WORKDIR / "musigtagger"
MANIFEST = REPO / "evaluation/fixtures/fixed-set-47-v1.json"
OUT = REPO / "evaluation/fixtures/track-pre-label-worksheet-v0.2-proposal.csv"

DISCLOSED_TITLE = "Soda Pop"

FIELDS = [
    "row",
    "track_id",
    "work_key",
    "canonical_path",
    "title",
    "artist",
    "album",
    "album_edition",
    "variant",
    "blind_status",
    "expected_genre_primary",
    "expected_genre_secondary",
    "expected_era",
    "expected_origin",
    "expected_mood",
    "expected_activity",
    "label_confidence",
    "evidence_basis",
    "evaluator",
    "labeled_at",
    "notes",
]


def main():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    rows = []
    for track in manifest["tracks"]:
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
                "blind_status": "disclosed-v0.1" if disclosed else "blind",
                "expected_genre_primary": "",
                "expected_genre_secondary": "",
                "expected_era": "",
                "expected_origin": "",
                "expected_mood": "",
                "expected_activity": "",
                "label_confidence": "",
                "evidence_basis": "",
                "evaluator": "",
                "labeled_at": "",
                "notes": "PROPOSAL ONLY — do not fill until the operator signs off on plan v0.2",
            }
        )
    with OUT.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {OUT} ({len(rows)} blank rows)")


if __name__ == "__main__":
    main()
