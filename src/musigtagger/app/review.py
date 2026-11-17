"""Human review: accept / edit / reject suggestions, singly or in batches.

The five review states are the schema's (``suggested``, ``accepted``, ``edited``,
``rejected``, ``applied``). This service owns the state machine:

* ``suggested`` → ``accepted`` (keep the proposal), ``edited`` (replace it), or
  ``rejected`` (no tag);
* ``accepted``/``edited`` → ``edited``/``rejected`` while still reviewable;
* ``accepted``/``edited`` → ``applied`` happens in the write path, not here;
* ``applied`` and ``rejected`` are terminal until an undo or a re-scan.

Every transition validates the effective tag id against the pinned taxonomy and
emits a CONTRACTS.md §4 ``review_outcome`` event, so evaluation never has to read
this database's internals. An edit may only stay inside the suggestion's own
facet: changing a genre suggestion into an era tag is a different claim, not a
correction.
"""

from __future__ import annotations

import sqlite3
from typing import Sequence

from .events import EventLog, review_outcome_event
from .store import LibraryStore
from .taxonomy_service import TaxonomyService
from .util import Clock, utc_now_iso

ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "suggested": {"accepted", "edited", "rejected"},
    "accepted": {"edited", "rejected"},
    "edited": {"edited", "rejected"},
    "applied": set(),
    "rejected": set(),
}


class ReviewError(Exception):
    """A review action is invalid for the suggestion's current state."""


class ReviewService:
    def __init__(
        self,
        store: LibraryStore,
        taxonomy: TaxonomyService,
        events: EventLog,
        *,
        clock: Clock = utc_now_iso,
        actor: str = "local-user",
    ) -> None:
        self.store = store
        self.taxonomy = taxonomy
        self.events = events
        self._clock = clock
        self.actor = actor

    # -- single-suggestion actions ---------------------------------------

    def accept(self, suggestion_id: int, *, reason: str | None = None) -> sqlite3.Row:
        row = self._row(suggestion_id)
        return self._transition(
            row,
            to_status="accepted",
            final_tag_id=str(row["tag_id"]),
            reason=reason,
        )

    def edit(
        self, suggestion_id: int, tag_id: str, *, reason: str | None = None
    ) -> sqlite3.Row:
        row = self._row(suggestion_id)
        new_tag = self.taxonomy.tag(tag_id)  # raises UnknownTagError
        original_facet = self.taxonomy.facet_for(str(row["tag_id"]))
        if new_tag.facet != original_facet:
            raise ReviewError(
                f"suggestion {suggestion_id} is a {original_facet} suggestion; "
                f"{tag_id!r} is a {new_tag.facet} tag. Reject it and add a "
                f"{new_tag.facet} tag from that facet instead."
            )
        return self._transition(
            row,
            to_status="edited",
            final_tag_id=new_tag.id,
            reason=reason,
        )

    def reject(self, suggestion_id: int, *, reason: str | None = None) -> sqlite3.Row:
        row = self._row(suggestion_id)
        return self._transition(
            row,
            to_status="rejected",
            final_tag_id=None,
            reason=reason,
        )

    # -- batch actions ---------------------------------------------------

    def batch_accept(
        self,
        *,
        suggestion_ids: Sequence[int] | None = None,
        track_ids: Sequence[int] | None = None,
        min_confidence: float | None = None,
        reason: str | None = None,
    ) -> int:
        """Accept every selected ``suggested`` row above ``min_confidence``."""
        return self._batch(
            "accepted",
            suggestion_ids=suggestion_ids,
            track_ids=track_ids,
            min_confidence=min_confidence,
            reason=reason,
        )

    def batch_reject(
        self,
        *,
        suggestion_ids: Sequence[int] | None = None,
        track_ids: Sequence[int] | None = None,
        min_confidence: float | None = None,
        reason: str | None = None,
    ) -> int:
        """Reject every selected ``suggested`` row above ``min_confidence``."""
        return self._batch(
            "rejected",
            suggestion_ids=suggestion_ids,
            track_ids=track_ids,
            min_confidence=min_confidence,
            reason=reason,
        )

    def suggestions_for_batch(
        self,
        *,
        suggestion_ids: Sequence[int] | None = None,
        track_ids: Sequence[int] | None = None,
        min_confidence: float | None = None,
    ) -> list[sqlite3.Row]:
        rows: list[sqlite3.Row] = []
        for row in self.store.suggestions_with_status(
            ("suggested",), track_ids=list(track_ids) if track_ids else None
        ):
            if suggestion_ids is not None and int(row["id"]) not in set(suggestion_ids):
                continue
            if min_confidence is not None and float(row["confidence"]) < min_confidence:
                continue
            rows.append(row)
        return rows

    # -- internals -------------------------------------------------------

    def _batch(
        self,
        to_status: str,
        *,
        suggestion_ids: Sequence[int] | None,
        track_ids: Sequence[int] | None,
        min_confidence: float | None,
        reason: str | None,
    ) -> int:
        rows = self.suggestions_for_batch(
            suggestion_ids=suggestion_ids,
            track_ids=track_ids,
            min_confidence=min_confidence,
        )
        changed = 0
        for row in rows:
            if to_status == "rejected":
                self._transition(row, to_status="rejected", final_tag_id=None, reason=reason)
            else:
                self._transition(
                    row,
                    to_status="accepted",
                    final_tag_id=str(row["tag_id"]),
                    reason=reason,
                )
            changed += 1
        return changed

    def _row(self, suggestion_id: int) -> sqlite3.Row:
        row = self.store.get_suggestion_with_track(suggestion_id)
        if row is None:
            raise ReviewError(f"suggestion {suggestion_id} does not exist")
        return row

    def _transition(
        self,
        row: sqlite3.Row,
        *,
        to_status: str,
        final_tag_id: str | None,
        reason: str | None = None,
    ) -> sqlite3.Row:
        from_status = str(row["status"])
        allowed = ALLOWED_TRANSITIONS.get(from_status, set())
        if to_status not in allowed:
            raise ReviewError(
                f"suggestion {row['id']} is {from_status!r}; cannot move it to "
                f"{to_status!r}"
                + (
                    " (undo the batch first)"
                    if from_status == "applied"
                    else ""
                )
            )
        expected_final = None if to_status == "rejected" else final_tag_id
        if to_status in ("accepted", "edited") and not expected_final:
            raise ReviewError(f"{to_status} requires a tag id")
        now = self._clock()
        self.store.update_suggestion(
            int(row["id"]),
            status=to_status,
            final_tag_id=expected_final,
            reviewed_at=now,
            applied_at=None,
        )
        self.events.emit(
            review_outcome_event(
                run_id=str(row["engine_run_id"] or "manual"),
                taxonomy_version=str(row["taxonomy_version"]),
                track_path=str(row["track_path"]),
                suggestion_id=int(row["id"]),
                from_status=from_status,
                to_status=to_status,
                original_tag_id=str(row["tag_id"]),
                final_tag_id=expected_final,
                actor=self.actor,
                reason=reason,
            )
        )
        updated = self.store.get_suggestion_with_track(int(row["id"]))
        if updated is None:  # pragma: no cover - row cannot disappear
            raise ReviewError(f"suggestion {row['id']} vanished during review")
        return updated
