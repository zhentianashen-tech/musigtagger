"""Mandatory, verified backups and byte-exact restore (CONTRACTS.md §3.2/§3.3).

The rule this module enforces is the operator's one unforgivable failure mode:
**no tag write may happen without a stored prior state, and undo must put the
file back byte-for-byte.**

Backup strategy: a complete sidecar copy of each file, plus its SHA-256 and its
parsed tag state, recorded in ``tag_backups``. A full copy is a deliberate
superset of the required "sidecar copy of the tag payload": it makes undo exact
for *every* container (ID3, Vorbis, even formats this Phase 1 path cannot tag),
with no dependency on how ``mutagen`` re-paginates a file. The cost is disk
space — documented in ``docs/APP.md`` — and quality-over-speed was the
operator's explicit choice.

Undo verifies the sidecar hash before touching the target, writes through a
temporary file in the target directory, atomically renames it into place, and
re-hashes the result. It never leaves a half-written file, and it refuses to
overwrite a target whose backup is missing or whose bytes do not match.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from .config import AppConfig
from .store import LibraryStore
from .tagio import TagCodec
from .tagmap import family_for_format
from .util import (
    Clock,
    atomic_replace,
    copy_file_durable,
    relative_to,
    sha256_file,
    unique_temp_path,
    utc_now_iso,
)

BACKUP_SCHEMA = "musigtagger.backup.v1"


class BackupError(Exception):
    """A backup could not be created; the batch must not start writing."""


class BackupIntegrityError(BackupError):
    """A stored backup no longer matches its recorded hash."""


class BackupRestoreError(BackupError):
    """Restoring a backup failed; the target was left in a valid state."""


@dataclass(frozen=True)
class BackupRecord:
    """One stored prior state, shaped for the restore path."""

    batch_id: int
    track_id: int
    track_path: str
    sidecar_path: Path
    sha256: str
    tag_format: str | None
    prior_tags: dict[str, list[str]]
    prior_tags_json: str


def _sidecar_name(track_id: int, original: Path) -> str:
    suffix = original.suffix.lower()
    if not suffix or len(suffix) > 12:
        suffix = ".audio"
    return f"{track_id:06d}{suffix}.bak"


class BackupManager:
    """Creates and restores the prior state for write batches."""

    def __init__(
        self,
        config: AppConfig,
        store: LibraryStore,
        codec: TagCodec,
        *,
        clock: Clock = utc_now_iso,
    ) -> None:
        self.config = config
        self.store = store
        self.codec = codec
        self._clock = clock

    def batch_directory(self, batch_id: int) -> Path:
        return self.config.backup_root / f"batch-{batch_id:06d}"

    def prepare_batch(
        self, batch_id: int, tracks: Sequence[sqlite3.Row]
    ) -> list[BackupRecord]:
        """Back up every target track before the batch is allowed to write.

        All-or-nothing: if any track cannot be backed up, ``BackupError`` is
        raised and no audio file has been written yet.
        """
        records: list[BackupRecord] = []
        for track in tracks:
            records.append(self._backup_track(batch_id, track))
        return records

    def _backup_track(self, batch_id: int, track: sqlite3.Row) -> BackupRecord:
        path = Path(track["path"])
        self.config.assert_writable(path)
        if not path.is_file():
            raise BackupError(f"cannot back up missing file: {path}")
        directory = self.batch_directory(batch_id)
        self.config.assert_writable(directory)
        sidecar = directory / _sidecar_name(int(track["id"]), path)
        try:
            copy_file_durable(path, sidecar)
        except OSError as exc:
            raise BackupError(f"cannot copy {path} to {sidecar}: {exc}") from exc
        source_hash = sha256_file(path)
        copy_hash = sha256_file(sidecar)
        if source_hash != copy_hash:
            raise BackupError(
                f"backup copy of {path} does not match the source; refusing to "
                f"write (source {source_hash}, copy {copy_hash})"
            )
        try:
            prior_tags = self.codec.read(path)
            tag_error = None
        except Exception as exc:  # noqa: BLE001 - any parse failure is recorded
            prior_tags = {}
            tag_error = f"{type(exc).__name__}: {exc}"
        try:
            family = family_for_format(track["format"])
        except Exception:  # noqa: BLE001 - unknown format is recorded, not fatal
            family = None
        payload = {
            "schema": BACKUP_SCHEMA,
            "format": track["format"],
            "tag_family": family,
            "size_bytes": path.stat().st_size,
            "sha256": source_hash,
            "sidecar": relative_to(sidecar, self.config.backup_root),
            "tags": prior_tags,
            "tag_read_error": tag_error,
            "created_at": self._clock(),
        }
        prior_json = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        self.store.add_backup(
            batch_id=batch_id,
            track_id=int(track["id"]),
            prior_tags_json=prior_json,
            prior_file_hash=source_hash,
        )
        return BackupRecord(
            batch_id=batch_id,
            track_id=int(track["id"]),
            track_path=str(path),
            sidecar_path=sidecar,
            sha256=source_hash,
            tag_format=track["format"],
            prior_tags=prior_tags,
            prior_tags_json=prior_json,
        )

    def record_for(self, backup_row: sqlite3.Row, track_path: str) -> BackupRecord:
        """Rebuild a :class:`BackupRecord` from a ``tag_backups`` row."""
        payload = json.loads(backup_row["prior_tags_json"])
        sidecar_relative = payload.get("sidecar")
        if not sidecar_relative:
            raise BackupIntegrityError(
                f"backup row {backup_row['id']} has no sidecar path recorded"
            )
        sidecar = (self.config.backup_root / sidecar_relative).resolve()
        root = self.config.backup_root.resolve()
        if not str(sidecar).startswith(str(root) + "/"):
            raise BackupIntegrityError(
                f"backup row {backup_row['id']} points outside the backup root"
            )
        return BackupRecord(
            batch_id=int(backup_row["batch_id"]),
            track_id=int(backup_row["track_id"]),
            track_path=track_path,
            sidecar_path=sidecar,
            sha256=str(backup_row["prior_file_hash"]),
            tag_format=payload.get("format"),
            prior_tags=payload.get("tags") or {},
            prior_tags_json=str(backup_row["prior_tags_json"]),
        )

    def restore(self, record: BackupRecord) -> None:
        """Put the exact prior bytes back, verifying before and after."""
        target = Path(record.track_path)
        self.config.assert_writable(target)
        sidecar = Path(record.sidecar_path)
        if not sidecar.is_file():
            raise BackupIntegrityError(f"backup sidecar is missing: {sidecar}")
        actual = sha256_file(sidecar)
        if actual != record.sha256:
            raise BackupIntegrityError(
                f"backup for {target} is corrupt: expected {record.sha256}, "
                f"sidecar has {actual}; refusing to restore"
            )
        temp = unique_temp_path(target.parent, prefix=f".{target.name}.restore-")
        try:
            copy_file_durable(sidecar, temp)
            atomic_replace(temp, target)
        except OSError as exc:
            raise BackupRestoreError(f"cannot restore {target}: {exc}") from exc
        finally:
            if temp.exists():
                try:
                    temp.unlink()
                except OSError:  # pragma: no cover - best effort cleanup
                    pass
        restored_hash = sha256_file(target)
        if restored_hash != record.sha256:
            raise BackupRestoreError(
                f"restored {target} does not match its backup "
                f"(expected {record.sha256}, got {restored_hash})"
            )
