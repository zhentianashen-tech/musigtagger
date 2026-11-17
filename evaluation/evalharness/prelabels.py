"""Plan v0.2 track-level pre-labels: reader and expected-tag recall.

The per-work label file is the source of truth; the per-instance worksheet is
its propagation. The harness reads the worksheet (which carries both
``canonical_path`` and ``track_id``) so suggestions can be joined on the same
path the scanner emitted.
"""

from __future__ import annotations

import csv
import json
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

EXPECTED_FIELDS = (
    "expected_genre_primary",
    "expected_genre_secondary",
    "expected_era",
    "expected_origin",
    "expected_mood",
    "expected_activity",
)


def _nfc(value: str) -> str:
    return unicodedata.normalize("NFC", value)


def _split(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    text = str(value).strip()
    if not text:
        return ()
    return tuple(part.strip() for part in text.replace(";", ",").split(",") if part.strip())


@dataclass(frozen=True)
class PreLabel:
    track_id: str
    canonical_path: str
    work_key: str
    expected_tags: tuple[str, ...]
    label_confidence: str = ""
    derived_from_work: str = ""
    blind_status: str = ""
    notes: str = ""

    @property
    def category_tags(self) -> dict[str, tuple[str, ...]]:
        buckets: dict[str, list[str]] = {}
        for tag_id in self.expected_tags:
            category = tag_id.split(".", 1)[0] if "." in tag_id else tag_id
            buckets.setdefault(category, []).append(tag_id)
        return {key: tuple(value) for key, value in buckets.items()}


@dataclass
class PreLabelReadResult:
    labels: list[PreLabel] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    source: str = ""

    @property
    def by_path(self) -> dict[str, PreLabel]:
        return {_nfc(label.canonical_path): label for label in self.labels}


def _from_row(row: Mapping[str, Any], where: str) -> PreLabel | str:
    path = str(row.get("canonical_path") or "").strip()
    track_id = str(row.get("track_id") or "").strip()
    work_key = str(row.get("work_key") or row.get("derived_from_work") or "").strip()
    if not path or not track_id:
        return f"{where}: canonical_path and track_id are required"
    tags: list[str] = []
    for key in EXPECTED_FIELDS:
        tags.extend(_split(row.get(key)))
    return PreLabel(
        track_id=track_id,
        canonical_path=path,
        work_key=work_key,
        expected_tags=tuple(dict.fromkeys(tags)),
        label_confidence=str(row.get("label_confidence") or ""),
        derived_from_work=str(row.get("derived_from_work") or ""),
        blind_status=str(row.get("blind_status") or ""),
        notes=str(row.get("notes") or ""),
    )


def read_prelabels(path: str | Path) -> PreLabelReadResult:
    """Read the per-instance worksheet (CSV) or a JSON label export."""
    source = Path(path)
    result = PreLabelReadResult(source=str(source))
    if not source.exists():
        result.problems.append(f"{source}: file not found")
        return result
    if source.suffix.lower() == ".csv":
        with source.open("r", encoding="utf-8", newline="") as handle:
            for index, row in enumerate(csv.DictReader(handle), start=2):
                parsed = _from_row(row, f"{source}:{index}")
                if isinstance(parsed, PreLabel):
                    result.labels.append(parsed)
                else:
                    result.problems.append(parsed)
        return result

    data = json.loads(source.read_text(encoding="utf-8"))
    rows: Iterable[Mapping[str, Any]]
    if isinstance(data, list):
        rows = data
    elif isinstance(data, Mapping) and "tracks" in data:
        rows = data["tracks"]
    elif isinstance(data, Mapping) and "works" in data:
        result.problems.append(
            f"{source}: per-work JSON has no canonical_path; use the per-instance worksheet CSV"
        )
        return result
    else:
        result.problems.append(f"{source}: unsupported pre-label JSON shape")
        return result

    for index, row in enumerate(rows, start=1):
        parsed = _from_row(row, f"{source}:{index}")
        if isinstance(parsed, PreLabel):
            result.labels.append(parsed)
        else:
            result.problems.append(parsed)
    return result
