"""SQLite persistence for the library index, review state, and write batches.

This module is a thin repository over schema v1 (``db/schema_v1.sql``). It adds
no schema of its own: every table and constraint it uses is the frozen v1
contract. Review transitions are enforced by :mod:`musigtagger.app.review`; this
layer stores them atomically.

One connection and one :class:`threading.RLock` are shared: the app is a
single-user local server, so serialising database access is simpler and safer
than a pool. All reads/writes go through the lock.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Iterable, Sequence

from ..contracts import TrackDescriptor
from ..db import initialize_database
from .util import Clock, utc_now_iso

REVIEW_STATES = ("suggested", "accepted", "edited", "rejected", "applied")
BATCH_KINDS = ("apply", "undo")
BATCH_STATES = ("pending", "completed", "failed", "undone")


class StoreError(Exception):
    """Base class for persistence errors raised by the application layer."""


class TaxonomyPinError(StoreError):
    """The database is pinned to a different taxonomy version than configured."""

    def __init__(self, pinned: str, requested: str) -> None:
        self.pinned = pinned
        self.requested = requested
        super().__init__(
            f"library is pinned to taxonomy {pinned!r} but the application is "
            f"configured for {requested!r}; refusing to mix taxonomy versions"
        )


def _in_clause(count: int) -> str:
    return ", ".join("?" for _ in range(count))


class LibraryStore:
    """Repository for tracks, suggestions, write batches, and backups."""

    def __init__(
        self,
        database_path: str | Path,
        *,
        taxonomy_version: str,
        clock: Clock = utc_now_iso,
    ) -> None:
        self.database_path = str(database_path)
        self._clock = clock
        self._lock = threading.RLock()
        self.connection = initialize_database(
            self.database_path, check_same_thread=False
        )
        self._pin_taxonomy(taxonomy_version)

    # -- lifecycle -------------------------------------------------------

    def close(self) -> None:
        with self._lock:
            self.connection.close()

    def __enter__(self) -> "LibraryStore":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def _now(self) -> str:
        return self._clock()

    def _execute(self, sql: str, parameters: Sequence[object] = ()) -> sqlite3.Cursor:
        return self.connection.execute(sql, tuple(parameters))

    # -- taxonomy pinning ------------------------------------------------

    def _pin_taxonomy(self, version: str) -> None:
        with self._lock:
            row = self._execute(
                "SELECT value FROM library_meta WHERE key = 'taxonomy_version'"
            ).fetchone()
            if row is None:
                self._execute(
                    "INSERT INTO library_meta (key, value) VALUES ('taxonomy_version', ?)",
                    (version,),
                )
                self.connection.commit()
            elif row["value"] != version:
                raise TaxonomyPinError(row["value"], version)

    def pinned_taxonomy_version(self) -> str:
        with self._lock:
            row = self._execute(
                "SELECT value FROM library_meta WHERE key = 'taxonomy_version'"
            ).fetchone()
        if row is None:  # pragma: no cover - the constructor always pins
            raise StoreError("library has no pinned taxonomy version")
        return str(row["value"])

    # -- tracks ----------------------------------------------------------

    def upsert_track(
        self,
        descriptor: TrackDescriptor,
        *,
        file_size_bytes: int | None = None,
        mtime_ns: int | None = None,
    ) -> int:
        """Insert or refresh one track; returns its ``tracks.id``."""
        now = self._now()
        features_json = (
            json.dumps(descriptor.features.extra, sort_keys=True)
            if descriptor.features is not None
            else None
        )
        with self._lock:
            row = self._execute(
                "SELECT id FROM tracks WHERE path = ?", (descriptor.path,)
            ).fetchone()
            if row is None:
                cursor = self._execute(
                    "INSERT INTO tracks (path, title, artist, album, genre, year, "
                    "duration_seconds, format, file_size_bytes, mtime_ns, "
                    "features_json, last_scanned_at, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        descriptor.path,
                        descriptor.title,
                        descriptor.artist,
                        descriptor.album,
                        descriptor.genre,
                        descriptor.year,
                        descriptor.duration_seconds,
                        descriptor.format,
                        file_size_bytes,
                        mtime_ns,
                        features_json,
                        now,
                        now,
                        now,
                    ),
                )
                self.connection.commit()
                return int(cursor.lastrowid)
            self._execute(
                "UPDATE tracks SET title = ?, artist = ?, album = ?, genre = ?, "
                "year = ?, duration_seconds = ?, format = ?, file_size_bytes = ?, "
                "mtime_ns = ?, features_json = ?, last_scanned_at = ?, updated_at = ? "
                "WHERE id = ?",
                (
                    descriptor.title,
                    descriptor.artist,
                    descriptor.album,
                    descriptor.genre,
                    descriptor.year,
                    descriptor.duration_seconds,
                    descriptor.format,
                    file_size_bytes,
                    mtime_ns,
                    features_json,
                    now,
                    now,
                    int(row["id"]),
                ),
            )
            self.connection.commit()
            return int(row["id"])

    def get_track(self, track_id: int) -> sqlite3.Row | None:
        with self._lock:
            return self._execute(
                "SELECT * FROM tracks WHERE id = ?", (track_id,)
            ).fetchone()

    def get_track_by_path(self, path: str) -> sqlite3.Row | None:
        with self._lock:
            return self._execute(
                "SELECT * FROM tracks WHERE path = ?", (path,)
            ).fetchone()

    def list_tracks(self, *, limit: int = 100, offset: int = 0) -> list[sqlite3.Row]:
        with self._lock:
            return self._execute(
                "SELECT * FROM tracks ORDER BY path LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()

    # -- suggestions -----------------------------------------------------

    def add_suggestion(
        self,
        track_id: int,
        *,
        tag_id: str,
        confidence: float,
        source: str,
        evidence: str,
        taxonomy_version: str,
        engine_run_id: str | None,
    ) -> int | None:
        """Persist one provider suggestion; returns its id, or None if it is a
        duplicate of an already-known (track, tag, source) suggestion.

        Duplicates include rejected suggestions: a human decision is not
        resurrected by a re-scan.
        """
        now = self._now()
        with self._lock:
            existing = self._execute(
                "SELECT id FROM suggestions WHERE track_id = ? AND tag_id = ? "
                "AND source = ?",
                (track_id, tag_id, source),
            ).fetchone()
            if existing is not None:
                return None
            cursor = self._execute(
                "INSERT INTO suggestions (track_id, tag_id, confidence, source, "
                "evidence, taxonomy_version, engine_run_id, status, created_at, "
                "updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, 'suggested', ?, ?)",
                (
                    track_id,
                    tag_id,
                    float(confidence),
                    source,
                    evidence,
                    taxonomy_version,
                    engine_run_id,
                    now,
                    now,
                ),
            )
            self.connection.commit()
            return int(cursor.lastrowid)

    def get_suggestion(self, suggestion_id: int) -> sqlite3.Row | None:
        with self._lock:
            return self._execute(
                "SELECT * FROM suggestions WHERE id = ?", (suggestion_id,)
            ).fetchone()

    def get_suggestion_with_track(self, suggestion_id: int) -> sqlite3.Row | None:
        with self._lock:
            return self._execute(
                "SELECT s.*, t.path AS track_path, t.title AS track_title, "
                "t.artist AS track_artist, t.album AS track_album "
                "FROM suggestions s JOIN tracks t ON t.id = s.track_id "
                "WHERE s.id = ?",
                (suggestion_id,),
            ).fetchone()

    def suggestions_for_track(
        self,
        track_id: int,
        *,
        statuses: Sequence[str] | None = None,
    ) -> list[sqlite3.Row]:
        with self._lock:
            if statuses:
                return self._execute(
                    "SELECT * FROM suggestions WHERE track_id = ? AND status IN "
                    f"({_in_clause(len(statuses))}) ORDER BY tag_id",
                    (track_id, *statuses),
                ).fetchall()
            return self._execute(
                "SELECT * FROM suggestions WHERE track_id = ? ORDER BY tag_id",
                (track_id,),
            ).fetchall()

    def suggestions_for_tracks(
        self,
        track_ids: Sequence[int],
        *,
        statuses: Sequence[str] | None = None,
    ) -> list[sqlite3.Row]:
        if not track_ids:
            return []
        with self._lock:
            for chunk_start in range(0, len(track_ids), 500):
                chunk = track_ids[chunk_start : chunk_start + 500]
                status_sql = (
                    f" AND status IN ({_in_clause(len(statuses))})" if statuses else ""
                )
                parameters: tuple[object, ...] = tuple(chunk)
                if statuses:
                    parameters = parameters + tuple(statuses)
                rows = self._execute(
                    "SELECT * FROM suggestions WHERE track_id IN "
                    f"({_in_clause(len(chunk))}){status_sql} ORDER BY track_id, tag_id",
                    parameters,
                ).fetchall()
                if chunk_start == 0:
                    collected = list(rows)
                else:
                    collected.extend(rows)
        return collected

    def suggestions_with_status(
        self,
        statuses: Sequence[str],
        *,
        track_ids: Sequence[int] | None = None,
    ) -> list[sqlite3.Row]:
        if not statuses:
            return []
        with self._lock:
            sql = (
                "SELECT s.*, t.path AS track_path, t.title AS track_title, "
                "t.artist AS track_artist, t.format AS track_format "
                "FROM suggestions s JOIN tracks t ON t.id = s.track_id "
                f"WHERE s.status IN ({_in_clause(len(statuses))})"
            )
            parameters: list[object] = list(statuses)
            if track_ids is not None:
                if not track_ids:
                    return []
                sql += f" AND s.track_id IN ({_in_clause(len(track_ids))})"
                parameters.extend(track_ids)
            sql += " ORDER BY s.track_id, s.tag_id"
            return self._execute(sql, parameters).fetchall()

    def update_suggestion(
        self,
        suggestion_id: int,
        *,
        status: str,
        final_tag_id: str | None,
        reviewed_at: str | None = None,
        applied_at: str | None = None,
    ) -> None:
        if status not in REVIEW_STATES:
            raise StoreError(f"unknown review state {status!r}")
        now = self._now()
        with self._lock:
            self._execute(
                "UPDATE suggestions SET status = ?, final_tag_id = ?, "
                "reviewed_at = COALESCE(?, reviewed_at), "
                "applied_at = ?, updated_at = ? WHERE id = ?",
                (
                    status,
                    final_tag_id,
                    reviewed_at,
                    applied_at,
                    now,
                    suggestion_id,
                ),
            )
            self.connection.commit()

    def applied_tag_ids(self) -> list[str]:
        with self._lock:
            rows = self._execute(
                "SELECT DISTINCT final_tag_id FROM suggestions "
                "WHERE status = 'applied' AND final_tag_id IS NOT NULL"
            ).fetchall()
        return [str(row["final_tag_id"]) for row in rows]

    def review_counts(self) -> dict[str, int]:
        with self._lock:
            rows = self._execute(
                "SELECT status, COUNT(*) AS count FROM suggestions GROUP BY status"
            ).fetchall()
        counts = {state: 0 for state in REVIEW_STATES}
        for row in rows:
            counts[str(row["status"])] = int(row["count"])
        return counts

    # -- review queue (paginated by track) -------------------------------

    def _queue_where(
        self,
        *,
        statuses: Sequence[str],
        facet: str | None,
        min_confidence: float | None,
        query: str | None,
    ) -> tuple[str, list[object]]:
        clauses = [f"s.status IN ({_in_clause(len(statuses))})"]
        parameters: list[object] = list(statuses)
        if facet:
            clauses.append("s.tag_id LIKE ?")
            parameters.append(f"{facet}.%")
        if min_confidence is not None:
            clauses.append("s.confidence >= ?")
            parameters.append(float(min_confidence))
        if query:
            clauses.append(
                "(t.path LIKE ? OR IFNULL(t.title, '') LIKE ? OR "
                "IFNULL(t.artist, '') LIKE ? OR IFNULL(t.album, '') LIKE ?)"
            )
            like = f"%{query}%"
            parameters.extend([like, like, like, like])
        return " AND ".join(clauses), parameters

    def queue_track_page(
        self,
        *,
        statuses: Sequence[str] = ("suggested",),
        facet: str | None = None,
        min_confidence: float | None = None,
        query: str | None = None,
        limit: int = 25,
        offset: int = 0,
    ) -> tuple[list[sqlite3.Row], int]:
        """Return one page of tracks with matching suggestions, plus a count."""
        where, parameters = self._queue_where(
            statuses=statuses,
            facet=facet,
            min_confidence=min_confidence,
            query=query,
        )
        with self._lock:
            total = int(
                self._execute(
                    "SELECT COUNT(DISTINCT s.track_id) FROM suggestions s "
                    f"JOIN tracks t ON t.id = s.track_id WHERE {where}",
                    parameters,
                ).fetchone()[0]
            )
            rows = self._execute(
                "SELECT DISTINCT t.* FROM tracks t JOIN suggestions s "
                f"ON s.track_id = t.id WHERE {where} ORDER BY t.path "
                "LIMIT ? OFFSET ?",
                (*parameters, limit, offset),
            ).fetchall()
        return rows, total

    def queue_track_ids(
        self,
        *,
        statuses: Sequence[str] = ("suggested",),
        facet: str | None = None,
        min_confidence: float | None = None,
        query: str | None = None,
    ) -> list[int]:
        """Every track id matching the queue filters (for batch actions)."""
        where, parameters = self._queue_where(
            statuses=statuses,
            facet=facet,
            min_confidence=min_confidence,
            query=query,
        )
        with self._lock:
            rows = self._execute(
                "SELECT DISTINCT s.track_id FROM suggestions s "
                f"JOIN tracks t ON t.id = s.track_id WHERE {where} "
                "ORDER BY s.track_id",
                parameters,
            ).fetchall()
        return [int(row["track_id"]) for row in rows]

    # -- batches ---------------------------------------------------------

    def create_batch(
        self,
        *,
        kind: str,
        taxonomy_version: str,
        backup_dir: str | None,
        track_count: int,
        note: str | None = None,
    ) -> int:
        if kind not in BATCH_KINDS:
            raise StoreError(f"unknown batch kind {kind!r}")
        now = self._now()
        with self._lock:
            cursor = self._execute(
                "INSERT INTO write_batches (kind, status, taxonomy_version, "
                "backup_dir, track_count, note, created_at) "
                "VALUES (?, 'pending', ?, ?, ?, ?, ?)",
                (kind, taxonomy_version, backup_dir, int(track_count), note, now),
            )
            self.connection.commit()
            return int(cursor.lastrowid)

    def finish_batch(
        self,
        batch_id: int,
        *,
        status: str,
        note: str | None = None,
        completed_at: str | None = None,
    ) -> None:
        if status not in BATCH_STATES:
            raise StoreError(f"unknown batch state {status!r}")
        now = self._now()
        if status == "completed" and completed_at is None:
            completed_at = now
        with self._lock:
            self._execute(
                "UPDATE write_batches SET status = ?, note = COALESCE(?, note), "
                "completed_at = COALESCE(?, completed_at) WHERE id = ?",
                (status, note, completed_at, batch_id),
            )
            self.connection.commit()

    def set_batch_backup_dir(self, batch_id: int, backup_dir: str) -> None:
        with self._lock:
            self._execute(
                "UPDATE write_batches SET backup_dir = ? WHERE id = ?",
                (backup_dir, batch_id),
            )
            self.connection.commit()

    def set_batch_status(self, batch_id: int, status: str) -> None:
        if status not in BATCH_STATES:
            raise StoreError(f"unknown batch state {status!r}")
        with self._lock:
            self._execute(
                "UPDATE write_batches SET status = ? WHERE id = ?",
                (status, batch_id),
            )
            self.connection.commit()

    def get_batch(self, batch_id: int) -> sqlite3.Row | None:
        with self._lock:
            return self._execute(
                "SELECT * FROM write_batches WHERE id = ?", (batch_id,)
            ).fetchone()

    def list_batches(self, *, limit: int = 50) -> list[sqlite3.Row]:
        with self._lock:
            return self._execute(
                "SELECT * FROM write_batches ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()

    # -- backups ---------------------------------------------------------

    def add_backup(
        self,
        *,
        batch_id: int,
        track_id: int,
        prior_tags_json: str,
        prior_file_hash: str,
    ) -> int:
        now = self._now()
        with self._lock:
            cursor = self._execute(
                "INSERT INTO tag_backups (batch_id, track_id, prior_tags_json, "
                "prior_file_hash, created_at) VALUES (?, ?, ?, ?, ?)",
                (batch_id, track_id, prior_tags_json, prior_file_hash, now),
            )
            self.connection.commit()
            return int(cursor.lastrowid)

    def get_backup(self, batch_id: int, track_id: int) -> sqlite3.Row | None:
        with self._lock:
            return self._execute(
                "SELECT * FROM tag_backups WHERE batch_id = ? AND track_id = ?",
                (batch_id, track_id),
            ).fetchone()

    def list_backups(self, batch_id: int) -> list[sqlite3.Row]:
        with self._lock:
            return self._execute(
                "SELECT * FROM tag_backups WHERE batch_id = ? ORDER BY id",
                (batch_id,),
            ).fetchall()

    def mark_backup_restored(
        self, *, batch_id: int, track_id: int, restored_at: str | None = None
    ) -> None:
        with self._lock:
            self._execute(
                "UPDATE tag_backups SET restored_at = COALESCE(?, ?) "
                "WHERE batch_id = ? AND track_id = ?",
                (restored_at, self._now(), batch_id, track_id),
            )
            self.connection.commit()

    def counts(self) -> dict[str, int]:
        with self._lock:
            return {
                "tracks": int(self._execute("SELECT COUNT(*) FROM tracks").fetchone()[0]),
                "suggestions": int(
                    self._execute("SELECT COUNT(*) FROM suggestions").fetchone()[0]
                ),
                "batches": int(
                    self._execute("SELECT COUNT(*) FROM write_batches").fetchone()[0]
                ),
            }
