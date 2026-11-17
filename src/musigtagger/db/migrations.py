"""Forward-only SQLite migrations for the library index.

The schema version lives in ``PRAGMA user_version`` (cheap to read before any
tables exist) and is mirrored in ``schema_migrations`` (human audit trail).
Each migration runs in a single transaction including its version marker, so a
crash leaves the database at the previous version, never half-migrated.

Adding migration *n* means: append a ``schema_v<n>.sql`` file, add an entry to
``_MIGRATIONS``, and bump ``SCHEMA_VERSION``. Schema changes after v1 are
escalated before merge (CONTRACTS.md).
"""

from __future__ import annotations

import sqlite3
from importlib import resources
from pathlib import Path
from typing import Final

SCHEMA_VERSION: Final[int] = 1

#: version -> (human description, packaged SQL file)
_MIGRATIONS: Final[dict[int, tuple[str, str]]] = {
    1: (
        "schema v1: library index, review state, write batches with backups",
        "schema_v1.sql",
    ),
}


class SchemaError(Exception):
    """Base class for database schema errors."""


class SchemaVersionError(SchemaError):
    """The database is newer (or otherwise incompatible) with this code."""

    def __init__(self, database_version: int, supported_version: int) -> None:
        self.database_version = database_version
        self.supported_version = supported_version
        super().__init__(
            f"database schema version {database_version} is newer than this "
            f"application supports ({supported_version}); upgrade the application"
        )


def connect(
    database: str | Path, *, check_same_thread: bool = True
) -> sqlite3.Connection:
    """Open a connection with the settings this schema requires.

    Foreign keys are per-connection in SQLite, so every code path must come
    through this helper. A file database's parent directory is created.

    ``check_same_thread=False`` is for the application layer's local web server,
    which serialises access with its own lock and serves requests from a thread
    pool; it is never a licence to share a connection without synchronisation.
    """
    database_text = str(database)
    if database_text != ":memory:":
        path = Path(database_text)
        path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(
        database_text, check_same_thread=check_same_thread
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def get_schema_version(connection: sqlite3.Connection) -> int:
    """Return the database's schema version (0 for an empty database)."""
    row = connection.execute("PRAGMA user_version").fetchone()
    return int(row[0]) if row is not None else 0


def _read_migration(filename: str) -> str:
    # importlib.resources works for editable installs and wheels alike.
    return (
        resources.files("musigtagger.db")
        .joinpath(filename)
        .read_text(encoding="utf-8")
    )


def apply_migrations(connection: sqlite3.Connection) -> int:
    """Apply every pending migration and return the resulting schema version.

    Idempotent: calling it on an up-to-date database is a no-op. Refuses to run
    against a database created by a newer application version instead of
    guessing.
    """
    current = get_schema_version(connection)
    if current > SCHEMA_VERSION:
        raise SchemaVersionError(current, SCHEMA_VERSION)
    if current == SCHEMA_VERSION:
        return current

    for version in sorted(_MIGRATIONS):
        if version <= current:
            continue
        description, filename = _MIGRATIONS[version]
        script = _read_migration(filename)
        escaped_description = description.replace("'", "''")
        # executescript commits any pending transaction first; the explicit
        # BEGIN/COMMIT below makes the schema and its version marker atomic.
        marker = (
            "BEGIN;\n"
            f"{script}\n"
            "INSERT INTO schema_migrations (version, description, applied_at) "
            f"VALUES ({int(version)}, "
            f"'{escaped_description}', "
            "strftime('%Y-%m-%dT%H:%M:%fZ', 'now'));\n"
            f"PRAGMA user_version = {int(version)};\n"
            "COMMIT;\n"
        )
        try:
            connection.executescript(marker)
        except sqlite3.Error:
            connection.rollback()
            raise
        current = version
    return current


def initialize_database(
    database: str | Path, *, check_same_thread: bool = True
) -> sqlite3.Connection:
    """Open ``database``, migrate it to the current schema, and return it."""
    connection = connect(database, check_same_thread=check_same_thread)
    try:
        apply_migrations(connection)
    except Exception:
        connection.close()
        raise
    return connection
