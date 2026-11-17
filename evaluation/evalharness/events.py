"""Event-stream ingestion for the CONTRACTS.md §4 JSONL event families.

The reader is tolerant by design: malformed lines are counted and surfaced as
findings, never fatal — a broken history log must not hide real events.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

SUGGESTION_REQUIRED = ("run_id", "taxonomy_version", "track", "tag_id", "source")
REVIEW_OUTCOME_REQUIRED = (
    "run_id",
    "taxonomy_version",
    "track_path",
    "from_status",
    "to_status",
    "original_tag_id",
)


@dataclass(frozen=True)
class SuggestionEvent:
    run_id: str
    track_path: str
    track_format: str | None
    tag_id: str
    confidence: float | None
    source: str
    evidence: str
    taxonomy_version: str
    occurred_at: str | None

    @property
    def category(self) -> str:
        """Facet/category prefix of the tag id (e.g. ``genre``)."""
        return self.tag_id.split(".", 1)[0] if "." in self.tag_id else self.tag_id


@dataclass(frozen=True)
class ReviewOutcomeEvent:
    run_id: str
    track_path: str
    suggestion_id: Any
    from_status: str
    to_status: str
    original_tag_id: str
    final_tag_id: str | None
    actor: str
    reason: str | None
    taxonomy_version: str
    occurred_at: str | None


@dataclass
class EventReadResult:
    suggestions: list[SuggestionEvent] = field(default_factory=list)
    outcomes: list[ReviewOutcomeEvent] = field(default_factory=list)
    malformed_lines: int = 0
    unknown_event_lines: int = 0
    invalid_records: list[str] = field(default_factory=list)
    files_read: list[str] = field(default_factory=list)

    @property
    def run_ids(self) -> tuple[str, ...]:
        runs = {e.run_id for e in self.suggestions} | {e.run_id for e in self.outcomes}
        return tuple(sorted(r for r in runs if r))

    @property
    def distinct_tracks(self) -> tuple[str, ...]:
        paths = {e.track_path for e in self.suggestions}
        paths |= {e.track_path for e in self.outcomes}
        return tuple(sorted(paths))


def _as_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_suggestion(record: Mapping[str, Any]) -> SuggestionEvent | str:
    missing = [key for key in SUGGESTION_REQUIRED if key not in record]
    if missing:
        return f"suggestion record missing {missing}"
    track = record.get("track")
    if not isinstance(track, Mapping) or "path" not in track:
        return "suggestion record has no track.path"
    return SuggestionEvent(
        run_id=str(record.get("run_id") or ""),
        track_path=str(track.get("path") or ""),
        track_format=track.get("format"),
        tag_id=str(record.get("tag_id") or ""),
        confidence=_as_float(record.get("confidence")),
        source=str(record.get("source") or ""),
        evidence=str(record.get("evidence") or ""),
        taxonomy_version=str(record.get("taxonomy_version") or ""),
        occurred_at=record.get("occurred_at"),
    )


def _parse_outcome(record: Mapping[str, Any]) -> ReviewOutcomeEvent | str:
    missing = [key for key in REVIEW_OUTCOME_REQUIRED if key not in record]
    if missing:
        return f"review_outcome record missing {missing}"
    final = record.get("final_tag_id")
    return ReviewOutcomeEvent(
        run_id=str(record.get("run_id") or ""),
        track_path=str(record.get("track_path") or ""),
        suggestion_id=record.get("suggestion_id"),
        from_status=str(record.get("from_status") or ""),
        to_status=str(record.get("to_status") or ""),
        original_tag_id=str(record.get("original_tag_id") or ""),
        final_tag_id=str(final) if final is not None else None,
        actor=str(record.get("actor") or ""),
        reason=record.get("reason"),
        taxonomy_version=str(record.get("taxonomy_version") or ""),
        occurred_at=record.get("occurred_at"),
    )


def parse_event_record(record: Any) -> SuggestionEvent | ReviewOutcomeEvent | str:
    """Parse one JSONL record; returns an event or an error description."""
    if not isinstance(record, Mapping):
        return "record is not a JSON object"
    kind = record.get("event")
    if kind == "suggestion":
        return _parse_suggestion(record)
    if kind == "review_outcome":
        return _parse_outcome(record)
    return f"unknown event kind {kind!r}"


def read_event_logs(paths: Iterable[str | Path]) -> EventReadResult:
    """Read one or more JSONL event logs, tolerating malformed lines."""
    result = EventReadResult()
    for raw_path in paths:
        path = Path(raw_path)
        result.files_read.append(str(path))
        if not path.exists():
            result.invalid_records.append(f"{path}: file not found")
            continue
        with path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    result.malformed_lines += 1
                    continue
                parsed = parse_event_record(record)
                if isinstance(parsed, SuggestionEvent):
                    result.suggestions.append(parsed)
                elif isinstance(parsed, ReviewOutcomeEvent):
                    result.outcomes.append(parsed)
                else:
                    if str(parsed).startswith("unknown event kind"):
                        result.unknown_event_lines += 1
                    else:
                        result.invalid_records.append(f"{path}:{line_number}: {parsed}")
    return result
