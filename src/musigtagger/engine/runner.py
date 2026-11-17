"""Batch orchestration around the pure suggestion-provider contract."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterable
from dataclasses import dataclass

from musigtagger.contracts import (
    SuggestionProvider,
    TagSuggestion,
    Taxonomy,
    TrackDescriptor,
)

from .events import JsonlEventLogger
from .scanner import ScanFailure

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class TrackSuggestions:
    track: TrackDescriptor
    suggestions: tuple[TagSuggestion, ...]


@dataclass(frozen=True, slots=True)
class BatchSuggestionResult:
    run_id: str
    results: tuple[TrackSuggestions, ...]
    failures: tuple[ScanFailure, ...]


class SuggestionRunner:
    """Validate, log, and isolate provider results for a descriptor batch."""

    def __init__(self, taxonomy: Taxonomy, event_logger: JsonlEventLogger) -> None:
        self.taxonomy = taxonomy
        self.event_logger = event_logger

    def suggest_batch(
        self,
        tracks: Iterable[TrackDescriptor],
        provider: SuggestionProvider,
        *,
        run_id: str | None = None,
    ) -> BatchSuggestionResult:
        engine_run_id = run_id or f"run-{uuid.uuid4().hex}"
        results: list[TrackSuggestions] = []
        failures: list[ScanFailure] = []
        for track in tracks:
            try:
                suggestions = tuple(provider.suggest(track))
                self.taxonomy.validate_tag_ids(
                    suggestion.tag_id for suggestion in suggestions
                )
            except Exception as exc:  # third-party providers share this boundary
                reason = f"{type(exc).__name__}: {exc}"
                failures.append(ScanFailure(track.path, reason))
                LOGGER.warning("Skipping suggestions for %s: %s", track.path, reason)
                continue

            for suggestion in suggestions:
                self.event_logger.log_suggestion(
                    track,
                    suggestion,
                    run_id=engine_run_id,
                    taxonomy_version=self.taxonomy.version,
                )
            results.append(TrackSuggestions(track, suggestions))

        return BatchSuggestionResult(engine_run_id, tuple(results), tuple(failures))
