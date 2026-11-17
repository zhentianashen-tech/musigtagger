"""SQLite persistence for the Phase 1 library index and review state.

The schema is versioned and applied by a small migration runner. Only this
package knows the physical schema; the rest of the application uses it through
queries it owns. Schema changes after v1 require escalation (see CONTRACTS.md).
"""

from __future__ import annotations

from .migrations import (
    SCHEMA_VERSION,
    SchemaError,
    SchemaVersionError,
    apply_migrations,
    connect,
    get_schema_version,
    initialize_database,
)

__all__ = [
    "SCHEMA_VERSION",
    "SchemaError",
    "SchemaVersionError",
    "apply_migrations",
    "connect",
    "get_schema_version",
    "initialize_database",
]
