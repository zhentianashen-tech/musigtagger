"""The CONTRACTS.md §4 event stream: local JSON Lines, append-only.

Two event families are emitted, always from *outside* the pure provider call:

* ``suggestion`` — one per suggestion a provider returns for a track;
* ``review_outcome`` — one per accept / edit / reject / apply / undo decision.

The file is a product feature (the operator's tagging history) and the
evaluation harness's input. It is append-only, local-only, and never influences
application behaviour: a failure to write an event is logged and swallowed so
that a broken history log cannot block or corrupt a tag write.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping

from ..contracts import TagSuggestion
from .util import Clock, utc_now_iso

EVENT_VERSION = 1


def suggestion_event(
    *,
    run_id: str,
    taxonomy_version: str,
    track_path: str,
    track_format: str | None,
    suggestion: TagSuggestion,
) -> dict[str, Any]:
    """Build the §4 ``suggestion`` envelope for one provider claim."""
    return {
        "event": "suggestion",
        "event_version": EVENT_VERSION,
        "run_id": run_id,
        "taxonomy_version": taxonomy_version,
        "track": {"path": track_path, "format": track_format},
        "tag_id": suggestion.tag_id,
        "confidence": suggestion.confidence,
        "source": suggestion.source,
        "evidence": suggestion.evidence,
    }


def review_outcome_event(
    *,
    run_id: str,
    taxonomy_version: str,
    track_path: str,
    suggestion_id: int,
    from_status: str,
    to_status: str,
    original_tag_id: str,
    final_tag_id: str | None,
    actor: str = "local-user",
    reason: str | None = None,
) -> dict[str, Any]:
    """Build the §4 ``review_outcome`` envelope for one decision."""
    event: dict[str, Any] = {
        "event": "review_outcome",
        "event_version": EVENT_VERSION,
        "run_id": run_id,
        "taxonomy_version": taxonomy_version,
        "track_path": track_path,
        "suggestion_id": suggestion_id,
        "from_status": from_status,
        "to_status": to_status,
        "original_tag_id": original_tag_id,
        "final_tag_id": final_tag_id,
        "actor": actor,
    }
    if reason:
        event["reason"] = reason
    return event


class EventLog:
    """Append-only JSONL event writer (see CONTRACTS.md §4)."""

    def __init__(self, path: str | Path | None, *, clock: Clock = utc_now_iso) -> None:
        self.path = Path(path) if path is not None else None
        self._clock = clock
        self._warned = False

    @property
    def enabled(self) -> bool:
        return self.path is not None

    def emit(self, event: Mapping[str, Any]) -> dict[str, Any] | None:
        """Append ``event`` with envelope fields; returns what was written.

        Event emission is best-effort by design: CONTRACTS.md §4.5 says enabling
        or disabling logging must not change behaviour, so an I/O failure here
        must never abort a review or a tag write.
        """
        if self.path is None:
            return None
        record = {"event_version": EVENT_VERSION, "occurred_at": self._clock()}
        record.update(dict(event))
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.path, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError as exc:  # pragma: no cover - environmental failures
            if not self._warned:
                print(
                    f"warning: cannot write event log {self.path}: {exc}",
                    file=sys.stderr,
                )
                self._warned = True
            return None
        return record


def read_events(
    path: str | Path | None,
    *,
    limit: int | None = None,
    event: str | None = None,
) -> list[dict[str, Any]]:
    """Read events back for the history view, tolerating malformed lines."""
    if path is None:
        return []
    path = Path(path)
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(record, dict):
                    continue
                if event is not None and record.get("event") != event:
                    continue
                records.append(record)
    except OSError:
        return []
    if limit is not None:
        records = records[-limit:]
    return records


def iter_event_lines(records: Iterable[Mapping[str, Any]]) -> str:
    """Render records as JSON Lines (used by tests and export paths)."""
    return "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records)
