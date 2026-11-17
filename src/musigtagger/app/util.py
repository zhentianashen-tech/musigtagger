"""Small shared helpers: UTC timestamps, hashing, and atomic file replacement."""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

#: Clock type used across the application. Tests inject a fixed clock so that
#: persisted timestamps and event envelopes are deterministic.
Clock = Callable[[], str]


def utc_now_iso() -> str:
    """Return the current UTC time as ``YYYY-MM-DDTHH:MM:SS.sssZ``.

    The schema (src/musigtagger/db/schema_v1.sql) and the event envelope both
    specify exactly this textual form, with millisecond precision.
    """
    now = datetime.now(timezone.utc)
    return f"{now:%Y-%m-%dT%H:%M:%S}.{now.microsecond // 1000:03d}Z"


def sha256_file(path: str | Path, *, chunk_size: int = 1024 * 1024) -> str:
    """Return the hex SHA-256 of a file's complete contents."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def fsync_path(path: str | Path) -> None:
    """Flush a file's contents to disk (no-op where fsync is unsupported)."""
    with open(path, "rb") as handle:
        os.fsync(handle.fileno())


def copy_file_durable(source: str | Path, destination: str | Path) -> None:
    """Copy ``source`` to ``destination``, preserving its mode, and flush it."""
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with open(source, "rb") as read_handle, open(destination, "wb") as write_handle:
        while True:
            chunk = read_handle.read(1024 * 1024)
            if not chunk:
                break
            write_handle.write(chunk)
        write_handle.flush()
        os.fsync(write_handle.fileno())
    # The temporary/replacement file must keep the original's permissions; a
    # music file silently becoming owner-only is a side effect of a tag write.
    try:
        shutil.copymode(source, destination)
    except OSError:  # pragma: no cover - exotic filesystems
        pass


def atomic_replace(source: str | Path, destination: str | Path) -> None:
    """Atomically move ``source`` over ``destination`` and flush the directory."""
    source = Path(source)
    destination = Path(destination)
    os.replace(source, destination)
    directory = destination.parent
    try:
        descriptor = os.open(directory, os.O_RDONLY)
    except OSError:  # pragma: no cover - platform dependent
        return
    try:
        os.fsync(descriptor)
    except OSError:  # pragma: no cover - platform dependent
        pass
    finally:
        os.close(descriptor)


def unique_temp_path(directory: Path, prefix: str, suffix: str = ".tmp") -> Path:
    """Reserve a unique, hidden temporary path inside ``directory``."""
    handle, name = tempfile.mkstemp(prefix=prefix, suffix=suffix, dir=directory)
    os.close(handle)
    return Path(name)


def relative_to(path: str | Path, base: str | Path) -> str:
    """Return ``path`` relative to ``base`` as a POSIX string."""
    return Path(os.path.relpath(Path(path), Path(base))).as_posix()
