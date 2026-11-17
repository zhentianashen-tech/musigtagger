"""Local JSONL observability events, emitted outside pure provider calls."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from musigtagger.contracts import TagSuggestion, TrackDescriptor


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


class JsonlEventLogger:
    """Append CONTRACTS.md §4 suggestion and review-outcome events locally."""

    def __init__(
        self, path: str | Path, *, clock: Callable[[], str] = _utc_now
    ) -> None:
        self.path = Path(path)
        self._clock = clock

    def log_suggestion(
        self,
        track: TrackDescriptor,
        suggestion: TagSuggestion,
        *,
        run_id: str,
        taxonomy_version: str,
    ) -> None:
        self._append(
            {
                "event": "suggestion",
                "event_version": 1,
                "occurred_at": self._clock(),
                "run_id": run_id,
                "taxonomy_version": taxonomy_version,
                "track": {"path": track.path, "format": track.format},
                "tag_id": suggestion.tag_id,
                "confidence": suggestion.confidence,
                "source": suggestion.source,
                "evidence": suggestion.evidence,
            }
        )

    def log_review_outcome(
        self,
        *,
        run_id: str,
        taxonomy_version: str,
        track_path: str,
        suggestion_id: int | None,
        from_status: str,
        to_status: str,
        original_tag_id: str,
        final_tag_id: str | None,
        actor: str = "local-user",
    ) -> None:
        self._append(
            {
                "event": "review_outcome",
                "event_version": 1,
                "occurred_at": self._clock(),
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
        )

    def _append(self, event: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event, ensure_ascii=False) + "\n")
