"""The safe tag-write path: apply, retry, and undo (CONTRACTS.md §3).

Every batch follows the same sequence:

1. **Validate** every tag id against the pinned taxonomy, including tags already
   recorded as applied. An unknown id aborts before any file is touched.
2. **Back up** every target track (all-or-nothing). No write may start before
   the batch owns a complete prior state.
3. **Write per track, isolated**: each track gets a temporary copy, the tags are
   written there, the intended fields and the audio stream are verified, and
   only then is the copy atomically renamed over the target. Any failure leaves
   the original untouched, is recorded, and the batch continues. A post-write
   verification failure restores that track's backup immediately.
4. **Record** the outcome on the batch: ``completed`` when every track
   succeeded, ``failed`` (backups kept) when any did.

Undo creates its own ``undo`` batch, backs up the applied state first (so an
undo is itself recoverable), restores each apply backup byte-for-byte, and
reverts the review state from ``applied`` back to ``accepted``/``edited``.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Sequence

from .backup import BackupError, BackupManager, BackupRecord
from .config import AppConfig
from .events import EventLog, review_outcome_event
from .store import LibraryStore
from .tagio import TagCodec
from .tagmap import family_for_format, normalise_fields, project
from .taxonomy_service import TaxonomyService
from .util import (
    Clock,
    atomic_replace,
    copy_file_durable,
    unique_temp_path,
    utc_now_iso,
)

WRITABLE_STATES = ("accepted", "edited")


class WriteError(Exception):
    """A write batch or a single track write cannot proceed."""


class NothingToApplyError(WriteError):
    """No accepted or edited suggestions matched the request."""


@dataclass(frozen=True)
class TrackOutcome:
    track_id: int
    path: str
    ok: bool
    error: str | None = None


@dataclass(frozen=True)
class BatchResult:
    batch_id: int
    kind: str
    status: str
    track_count: int
    outcomes: tuple[TrackOutcome, ...] = field(default_factory=tuple)
    note: str | None = None

    @property
    def failures(self) -> tuple[TrackOutcome, ...]:
        return tuple(outcome for outcome in self.outcomes if not outcome.ok)

    @property
    def succeeded(self) -> int:
        return sum(1 for outcome in self.outcomes if outcome.ok)


class ApplyService:
    """Applies reviewed tags, retries failed batches, and undoes them."""

    def __init__(
        self,
        config: AppConfig,
        store: LibraryStore,
        taxonomy: TaxonomyService,
        backups: BackupManager,
        codec: TagCodec,
        events: EventLog,
        *,
        clock: Clock = utc_now_iso,
        actor: str = "local-user",
    ) -> None:
        self.config = config
        self.store = store
        self.taxonomy = taxonomy
        self.backups = backups
        self.codec = codec
        self.events = events
        self._clock = clock
        self.actor = actor

    # -- apply -----------------------------------------------------------

    def apply(
        self,
        *,
        track_ids: Sequence[int] | None = None,
        note: str | None = None,
    ) -> BatchResult:
        rows = self.store.suggestions_with_status(WRITABLE_STATES, track_ids=track_ids)
        if not rows:
            raise NothingToApplyError(
                "no accepted or edited suggestions to apply; review some tracks first"
            )
        self._validate(rows)
        by_track: dict[int, list[sqlite3.Row]] = {}
        for row in rows:
            by_track.setdefault(int(row["track_id"]), []).append(row)
        track_rows = [self._require_track(track_id) for track_id in by_track]
        batch_id = self.store.create_batch(
            kind="apply",
            taxonomy_version=self.taxonomy.version,
            backup_dir=None,
            track_count=len(track_rows),
            note=note,
        )
        self.store.set_batch_backup_dir(
            batch_id, str(self.backups.batch_directory(batch_id))
        )
        try:
            records = self.backups.prepare_batch(batch_id, track_rows)
        except Exception as exc:  # noqa: BLE001 - backup failures are hard stops
            self.store.finish_batch(
                batch_id,
                status="failed",
                note=_note(
                    [
                        TrackOutcome(
                            track_id=int(track["id"]),
                            path=str(track["path"]),
                            ok=False,
                            error=f"backup failed: {exc}",
                        )
                        for track in track_rows
                    ],
                    error=f"backup failed before any write: {exc}",
                ),
            )
            raise
        return self._execute_apply(batch_id, records, by_track, track_rows)

    def retry(self, batch_id: int) -> BatchResult:
        """Retry the tracks of a failed apply batch that still need writing."""
        batch = self.store.get_batch(batch_id)
        if batch is None:
            raise WriteError(f"batch {batch_id} does not exist")
        if batch["kind"] != "apply":
            raise WriteError(f"batch {batch_id} is not an apply batch")
        if batch["status"] not in ("failed", "pending"):
            raise WriteError(
                f"batch {batch_id} is {batch['status']}; only a failed batch can be retried"
            )
        backup_rows = self.store.list_backups(batch_id)
        track_ids = [int(row["track_id"]) for row in backup_rows]
        rows = self.store.suggestions_with_status(WRITABLE_STATES, track_ids=track_ids)
        if not rows:
            raise NothingToApplyError(
                f"batch {batch_id} has no remaining tracks to write"
            )
        self._validate(rows)
        by_track: dict[int, list[sqlite3.Row]] = {}
        for row in rows:
            by_track.setdefault(int(row["track_id"]), []).append(row)
        track_rows = [self._require_track(track_id) for track_id in by_track]
        records = []
        for track in track_rows:
            backup_row = self.store.get_backup(batch_id, int(track["id"]))
            if backup_row is None:  # pragma: no cover - invariant from prepare_batch
                raise BackupError(
                    f"batch {batch_id} has no backup for track {track['id']}"
                )
            records.append(
                self.backups.record_for(backup_row, str(track["path"]))
            )
        self.store.set_batch_status(batch_id, "pending")
        return self._execute_apply(batch_id, records, by_track, track_rows)

    def _execute_apply(
        self,
        batch_id: int,
        records: Sequence[BackupRecord],
        by_track: dict[int, list[sqlite3.Row]],
        track_rows: Sequence[sqlite3.Row],
    ) -> BatchResult:
        records_by_track = {record.track_id: record for record in records}
        outcomes: list[TrackOutcome] = []
        applied_ids: list[int] = []
        for track in track_rows:
            track_id = int(track["id"])
            path = str(track["path"])
            rows_for_track = list(by_track[track_id])
            # Keep already-applied tags for this track in the file: applying a
            # later suggestion must not erase facets applied by an earlier batch.
            present = {int(row["id"]) for row in rows_for_track}
            for applied_row in self.store.suggestions_for_track(
                track_id, statuses=("applied",)
            ):
                if int(applied_row["id"]) not in present:
                    rows_for_track.append(applied_row)
            try:
                self._write_track(track, rows_for_track, records_by_track[track_id])
            except Exception as exc:  # noqa: BLE001 - per-track isolation
                outcomes.append(
                    TrackOutcome(track_id=track_id, path=path, ok=False, error=str(exc))
                )
                continue
            now = self._clock()
            self._mark_applied(by_track[track_id], now)
            applied_ids.extend(int(row["id"]) for row in by_track[track_id])
            outcomes.append(TrackOutcome(track_id=track_id, path=path, ok=True))
        status = "completed" if all(o.ok for o in outcomes) else "failed"
        note = _note(outcomes, applied_suggestion_ids=applied_ids)
        self.store.finish_batch(batch_id, status=status, note=note)
        return BatchResult(
            batch_id=batch_id,
            kind="apply",
            status=status,
            track_count=len(track_rows),
            outcomes=tuple(outcomes),
            note=note,
        )

    def _write_track(
        self,
        track: sqlite3.Row,
        suggestion_rows: Sequence[sqlite3.Row],
        record: BackupRecord,
    ) -> None:
        path = Path(track["path"])
        self.config.assert_writable(path)
        if not path.is_file():
            raise WriteError(f"file is missing: {path}")
        family = family_for_format(track["format"])
        tag_ids = sorted({str(row["final_tag_id"]) for row in suggestion_rows})
        tags = [self.taxonomy.tag(tag_id) for tag_id in tag_ids]
        projection = project(tags, family)
        expected = normalise_fields(projection, family=family)
        before = self.codec.probe(path)
        temporary = unique_temp_path(path.parent, prefix=f".{path.name}.tag-")
        try:
            copy_file_durable(path, temporary)
            self.codec.write(temporary, projection)
            written = normalise_fields(self.codec.read(temporary), family=family)
            if written != expected:
                raise WriteError(
                    "tag write verification failed on the temporary copy: "
                    f"wrote {expected!r}, read back {written!r}"
                )
            after = self.codec.probe(temporary)
            if not after.audio_matches(before):
                raise WriteError(
                    "audio stream changed while retagging; refusing to replace "
                    f"the file (before={before!r}, after={after!r})"
                )
            atomic_replace(temporary, path)
        finally:
            if temporary.exists():
                try:
                    temporary.unlink()
                except OSError:  # pragma: no cover - best effort cleanup
                    pass
        # Post-write check on the real file; on failure, put the backup back.
        try:
            final = normalise_fields(self.codec.read(path), family=family)
            if final != expected:
                raise WriteError(
                    "post-write verification failed: "
                    f"expected {expected!r}, file has {final!r}"
                )
            final_probe = self.codec.probe(path)
            if not final_probe.audio_matches(before):
                raise WriteError("post-write audio probe does not match the original")
        except Exception:
            self.backups.restore(record)
            raise

    # -- undo ------------------------------------------------------------

    def undo(self, apply_batch_id: int) -> BatchResult:
        apply_batch = self.store.get_batch(apply_batch_id)
        if apply_batch is None:
            raise WriteError(f"batch {apply_batch_id} does not exist")
        if apply_batch["kind"] != "apply":
            raise WriteError(f"batch {apply_batch_id} is not an apply batch")
        if apply_batch["status"] == "undone":
            raise WriteError(f"batch {apply_batch_id} has already been undone")
        applied_ids = _applied_ids_from_note(apply_batch)
        backup_rows = [
            row
            for row in self.store.list_backups(apply_batch_id)
            if row["restored_at"] is None
        ]
        if not backup_rows:
            raise WriteError(f"batch {apply_batch_id} has nothing to undo")
        track_rows = [self._require_track(int(row["track_id"])) for row in backup_rows]
        undo_batch_id = self.store.create_batch(
            kind="undo",
            taxonomy_version=self.taxonomy.version,
            backup_dir=None,
            track_count=len(track_rows),
            note=f"undo of apply batch {apply_batch_id}",
        )
        self.store.set_batch_backup_dir(
            undo_batch_id, str(self.backups.batch_directory(undo_batch_id))
        )
        try:
            # Back up the current (applied) state first: an undo is itself a
            # write batch and must be recoverable.
            self.backups.prepare_batch(undo_batch_id, track_rows)
        except Exception as exc:  # noqa: BLE001 - hard stop before restoring
            self.store.finish_batch(
                undo_batch_id,
                status="failed",
                note=f"backup before undo failed; nothing was restored: {exc}",
            )
            raise
        outcomes: list[TrackOutcome] = []
        for backup_row, track in zip(backup_rows, track_rows):
            track_id = int(track["id"])
            path = str(track["path"])
            try:
                record = self.backups.record_for(backup_row, path)
                self.backups.restore(record)
                self.store.mark_backup_restored(
                    batch_id=apply_batch_id, track_id=track_id
                )
                self._revert_suggestions(track_id, applied_ids)
                outcomes.append(TrackOutcome(track_id=track_id, path=path, ok=True))
            except Exception as exc:  # noqa: BLE001 - per-track isolation
                outcomes.append(
                    TrackOutcome(track_id=track_id, path=path, ok=False, error=str(exc))
                )
        status = "completed" if all(outcome.ok for outcome in outcomes) else "failed"
        note = _note(outcomes, error=None)
        self.store.finish_batch(undo_batch_id, status=status, note=note)
        if status == "completed":
            self.store.finish_batch(
                apply_batch_id,
                status="undone",
                note=f"undone by batch {undo_batch_id}",
            )
        return BatchResult(
            batch_id=undo_batch_id,
            kind="undo",
            status=status,
            track_count=len(track_rows),
            outcomes=tuple(outcomes),
            note=note,
        )

    # -- internals -------------------------------------------------------

    def _require_track(self, track_id: int) -> sqlite3.Row:
        track = self.store.get_track(track_id)
        if track is None:
            raise WriteError(f"track {track_id} is not in the library index")
        return track

    def _validate(self, rows: Sequence[sqlite3.Row]) -> None:
        tag_ids = [str(row["final_tag_id"]) for row in rows if row["final_tag_id"]]
        self.taxonomy.validate(tag_ids)
        self.taxonomy.validate(self.store.applied_tag_ids())

    def _mark_applied(self, rows: Sequence[sqlite3.Row], now: str) -> None:
        for row in rows:
            self.store.update_suggestion(
                int(row["id"]),
                status="applied",
                final_tag_id=str(row["final_tag_id"]),
                applied_at=now,
            )
            self.events.emit(
                review_outcome_event(
                    run_id=str(row["engine_run_id"] or "manual"),
                    taxonomy_version=str(row["taxonomy_version"]),
                    track_path=str(row["track_path"]),
                    suggestion_id=int(row["id"]),
                    from_status=str(row["status"]),
                    to_status="applied",
                    original_tag_id=str(row["tag_id"]),
                    final_tag_id=str(row["final_tag_id"]),
                    actor=self.actor,
                )
            )

    def _revert_suggestions(self, track_id: int, only_ids: set[int]) -> None:
        """Return this batch's applied suggestions to their pre-apply state.

        ``only_ids`` comes from the apply batch's note, so undoing one batch can
        never revert a suggestion another batch applied. Legacy batches without
        recorded ids fall back to every applied row on the track.
        """
        now = self._clock()
        for row in self.store.suggestions_for_track(track_id, statuses=("applied",)):
            if only_ids and int(row["id"]) not in only_ids:
                continue
            target_status = (
                "accepted" if row["final_tag_id"] == row["tag_id"] else "edited"
            )
            self.store.update_suggestion(
                int(row["id"]),
                status=target_status,
                final_tag_id=str(row["final_tag_id"]),
                applied_at=None,
            )
            self.events.emit(
                review_outcome_event(
                    run_id=str(row["engine_run_id"] or "manual"),
                    taxonomy_version=str(row["taxonomy_version"]),
                    track_path=str(self._require_track(track_id)["path"]),
                    suggestion_id=int(row["id"]),
                    from_status="applied",
                    to_status=target_status,
                    original_tag_id=str(row["tag_id"]),
                    final_tag_id=str(row["final_tag_id"]),
                    actor=self.actor,
                    reason=f"undo at {now}",
                )
            )


def _note(
    outcomes: Iterable[TrackOutcome],
    *,
    error: str | None = None,
    applied_suggestion_ids: Sequence[int] = (),
) -> str:
    payload: dict[str, object] = {
        "outcomes": [
            {
                "track_id": outcome.track_id,
                "path": outcome.path,
                "ok": outcome.ok,
                "error": outcome.error,
            }
            for outcome in outcomes
        ]
    }
    if error:
        payload["error"] = error
    payload["applied_suggestion_ids"] = sorted(set(applied_suggestion_ids))
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _applied_ids_from_note(batch: sqlite3.Row) -> set[int]:
    """Read the recorded applied-suggestion ids of an apply batch."""
    try:
        payload = json.loads(batch["note"] or "{}")
    except (TypeError, json.JSONDecodeError):
        return set()
    if not isinstance(payload, dict):
        return set()
    ids: set[int] = set()
    for value in payload.get("applied_suggestion_ids", []) or []:
        try:
            ids.add(int(value))
        except (TypeError, ValueError):
            continue
    return ids
