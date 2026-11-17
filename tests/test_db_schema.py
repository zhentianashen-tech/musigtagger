"""SQLite schema tests: version marker, constraints, review states, backups.

Schema v2 (MUSI-14) adds the additive ``release_date_cache`` table; schema
v3 adds its ``query_version`` column (the defect-fix invalidation). The
v1-focused assertions below all still hold on the current schema.
"""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from musigtagger.db import (
    SCHEMA_VERSION,
    SchemaVersionError,
    apply_migrations,
    connect,
    initialize_database,
)

NOW = "2026-11-17T07:30:00.000Z"

EXPECTED_TABLES = {
    "schema_migrations",
    "tracks",
    "suggestions",
    "write_batches",
    "tag_backups",
    "library_meta",
    "release_date_cache",
}


class SchemaTests(unittest.TestCase):
    def setUp(self) -> None:
        self.connection = connect(":memory:")
        apply_migrations(self.connection)

    def tearDown(self) -> None:
        self.connection.close()

    @property
    def conn(self) -> sqlite3.Connection:
        return self.connection

    def test_version_marker(self) -> None:
        self.assertEqual(SCHEMA_VERSION, 3)
        self.assertEqual(
            self.conn.execute("PRAGMA user_version").fetchone()[0], SCHEMA_VERSION
        )
        rows = self.conn.execute(
            "SELECT version, description FROM schema_migrations"
        ).fetchall()
        self.assertEqual(len(rows), 3)
        self.assertEqual(
            [row["version"] for row in rows], [1, 2, 3]
        )  # forward-only audit trail

    def test_expected_tables_exist(self) -> None:
        rows = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
        tables = {row["name"] for row in rows}
        self.assertTrue(EXPECTED_TABLES.issubset(tables), tables)

    def test_migrations_are_idempotent(self) -> None:
        self.assertEqual(apply_migrations(self.conn), SCHEMA_VERSION)
        count = self.conn.execute(
            "SELECT COUNT(*) FROM schema_migrations"
        ).fetchone()[0]
        self.assertEqual(count, 3)

    def test_v1_database_upgrades_in_place_and_keeps_v1_rows(self) -> None:
        """A v1 database gains the cache table without touching v1 data."""
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "library.sqlite3"
            connection = connect(database)
            # Force the database to v1 only, using the packaged v1 script.
            from musigtagger.db import migrations as migrations_module

            script = migrations_module._read_migration("schema_v1.sql")
            connection.executescript(
                "BEGIN;\n"
                f"{script}\n"
                "INSERT INTO schema_migrations (version, description, applied_at)"
                " VALUES (1, 'schema v1 (test)', '2026-11-17T00:00:00.000Z');\n"
                "PRAGMA user_version = 1;\n"
                "COMMIT;\n"
            )
            connection.execute(
                "INSERT INTO tracks (path, title, last_scanned_at, created_at,"
                " updated_at) VALUES (?, ?, ?, ?, ?)",
                ("/music/a.flac", "A", NOW, NOW, NOW),
            )
            connection.commit()
            self.assertEqual(
                connection.execute("PRAGMA user_version").fetchone()[0], 1
            )

            self.assertEqual(apply_migrations(connection), SCHEMA_VERSION)

            self.assertEqual(
                connection.execute("PRAGMA user_version").fetchone()[0],
                SCHEMA_VERSION,
            )
            # v1 rows survive untouched.
            row = connection.execute(
                "SELECT path, title FROM tracks"
            ).fetchone()
            self.assertEqual((row["path"], row["title"]), ("/music/a.flac", "A"))
            # ...and the new table works.
            connection.execute(
                "INSERT INTO release_date_cache (cache_key, normalized_album,"
                " normalized_artist, found, queried_at)"
                " VALUES ('k', 'album', 'artist', 0, ?)",
                (NOW,),
            )
            connection.commit()
            connection.close()

    def test_v2_database_upgrades_to_v3_and_keeps_cache_rows(self) -> None:
        """The MUSI-14 defect-fix migration adds query_version, keeps rows.

        The stale no-match rows that masked the query bug are *not* deleted
        (they stay inspectable); they are invalidated by their query_version
        of 0 instead of by destruction.
        """
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "library.sqlite3"
            connection = connect(database)
            from musigtagger.db import migrations as migrations_module

            # Force the database to exactly v2.
            scripts = (
                migrations_module._read_migration("schema_v1.sql"),
                migrations_module._read_migration("schema_v2.sql"),
            )
            connection.executescript(
                "BEGIN;\n"
                f"{scripts[0]}\n{scripts[1]}\n"
                "INSERT INTO schema_migrations (version, description, applied_at)"
                " VALUES (1, 'schema v1 (test)', '2026-11-17T00:00:00.000Z'),"
                "        (2, 'schema v2 (test)', '2026-11-17T00:00:01.000Z');\n"
                "PRAGMA user_version = 2;\n"
                "COMMIT;\n"
            )
            # A row exactly like the 16 no-match rows the v0.2 rerun cached.
            connection.execute(
                "INSERT INTO release_date_cache (cache_key, normalized_album,"
                " normalized_artist, found, queried_at)"
                " VALUES ('k', 'album', 'artist', 0, ?)",
                (NOW,),
            )
            connection.commit()

            self.assertEqual(apply_migrations(connection), SCHEMA_VERSION)

            # The stale row survives, tagged query_version 0 (= pre-versioning).
            row = connection.execute(
                "SELECT found, query_version FROM release_date_cache"
                " WHERE cache_key = 'k'"
            ).fetchone()
            self.assertEqual((row["found"], row["query_version"]), (0, 0))
            connection.close()

    def test_newer_database_is_refused(self) -> None:
        self.conn.execute("PRAGMA user_version = 99")
        with self.assertRaises(SchemaVersionError):
            apply_migrations(self.conn)

    def test_foreign_keys_are_enabled_per_connection(self) -> None:
        self.assertEqual(
            self.conn.execute("PRAGMA foreign_keys").fetchone()[0], 1
        )


class LibraryAndReviewTests(unittest.TestCase):
    def setUp(self) -> None:
        self.connection = connect(":memory:")
        apply_migrations(self.connection)

    def tearDown(self) -> None:
        self.connection.close()

    @property
    def conn(self) -> sqlite3.Connection:
        return self.connection

    def _track(self, path: str = "/music/a.mp3") -> int:
        cursor = self.conn.execute(
            """
            INSERT INTO tracks (path, title, artist, format, last_scanned_at,
                                created_at, updated_at)
            VALUES (?, 'Song', 'Artist', 'mp3', ?, ?, ?)
            """,
            (path, NOW, NOW, NOW),
        )
        return int(cursor.lastrowid)

    def _suggestion(
        self,
        track_id: int,
        *,
        tag_id: str = "genre.rock",
        status: str = "suggested",
        confidence: float = 0.5,
        final_tag_id: str | None = None,
        applied_at: str | None = None,
    ) -> int:
        cursor = self.conn.execute(
            """
            INSERT INTO suggestions
                (track_id, tag_id, confidence, source, evidence,
                 taxonomy_version, status, final_tag_id, applied_at,
                 created_at, updated_at)
            VALUES (?, ?, ?, 'metadata.embedded', 'GENRE=Rock', '0.1.0-draft',
                    ?, ?, ?, ?, ?)
            """,
            (track_id, tag_id, confidence, status, final_tag_id, applied_at, NOW, NOW),
        )
        return int(cursor.lastrowid)

    def test_track_insert_and_unique_path(self) -> None:
        track_id = self._track()
        self.assertGreater(track_id, 0)
        with self.assertRaises(sqlite3.IntegrityError):
            self._track()

    def test_suggestion_defaults_to_suggested(self) -> None:
        track_id = self._track()
        suggestion_id = self._suggestion(track_id)
        row = self.conn.execute(
            "SELECT status, final_tag_id FROM suggestions WHERE id = ?",
            (suggestion_id,),
        ).fetchone()
        self.assertEqual(row["status"], "suggested")
        self.assertIsNone(row["final_tag_id"])

    def test_confidence_is_bounded(self) -> None:
        track_id = self._track()
        for bad in (-0.01, 1.01):
            with self.subTest(value=bad):
                with self.assertRaises(sqlite3.IntegrityError):
                    self._suggestion(track_id, confidence=bad)

    def test_unknown_status_is_rejected(self) -> None:
        track_id = self._track()
        with self.assertRaises(sqlite3.IntegrityError):
            self._suggestion(track_id, status="pending")

    def test_accepted_requires_effective_tag(self) -> None:
        track_id = self._track()
        with self.assertRaises(sqlite3.IntegrityError):
            self._suggestion(track_id, status="accepted")
        self._suggestion(
            track_id, status="accepted", final_tag_id="genre.rock"
        )

    def test_edited_requires_effective_tag(self) -> None:
        track_id = self._track()
        with self.assertRaises(sqlite3.IntegrityError):
            self._suggestion(track_id, status="edited")
        self._suggestion(
            track_id, status="edited", final_tag_id="genre.rock.punk"
        )

    def test_rejected_cannot_carry_a_tag(self) -> None:
        track_id = self._track()
        with self.assertRaises(sqlite3.IntegrityError):
            self._suggestion(
                track_id, status="rejected", final_tag_id="genre.rock"
            )
        self._suggestion(track_id, status="rejected")

    def test_applied_requires_applied_at(self) -> None:
        track_id = self._track()
        with self.assertRaises(sqlite3.IntegrityError):
            self._suggestion(
                track_id, status="applied", final_tag_id="genre.rock"
            )
        self._suggestion(
            track_id,
            status="applied",
            final_tag_id="genre.rock",
            applied_at=NOW,
        )

    def test_suggestion_requires_existing_track(self) -> None:
        with self.assertRaises(sqlite3.IntegrityError):
            self._suggestion(9999)

    def test_deleting_a_track_cascades_suggestions(self) -> None:
        track_id = self._track()
        self._suggestion(track_id)
        self.conn.execute("DELETE FROM tracks WHERE id = ?", (track_id,))
        count = self.conn.execute("SELECT COUNT(*) FROM suggestions").fetchone()[0]
        self.assertEqual(count, 0)

    def test_library_meta_stores_pinned_taxonomy_version(self) -> None:
        self.conn.execute(
            "INSERT INTO library_meta (key, value) VALUES ('taxonomy_version', '0.1.0-draft')"
        )
        value = self.conn.execute(
            "SELECT value FROM library_meta WHERE key = 'taxonomy_version'"
        ).fetchone()["value"]
        self.assertEqual(value, "0.1.0-draft")
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute(
                "INSERT INTO library_meta (key, value) VALUES ('taxonomy_version', 'x')"
            )


class BackupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.connection = connect(":memory:")
        apply_migrations(self.connection)

    def tearDown(self) -> None:
        self.connection.close()

    @property
    def conn(self) -> sqlite3.Connection:
        return self.connection

    def _track(self) -> int:
        cursor = self.conn.execute(
            "INSERT INTO tracks (path, last_scanned_at, created_at, updated_at) "
            "VALUES ('/music/a.mp3', ?, ?, ?)",
            (NOW, NOW, NOW),
        )
        return int(cursor.lastrowid)

    def _batch(self, *, status: str = "pending") -> int:
        cursor = self.conn.execute(
            "INSERT INTO write_batches "
            "(kind, status, taxonomy_version, track_count, created_at) "
            "VALUES ('apply', ?, '0.1.0-draft', 1, ?)",
            (status, NOW),
        )
        return int(cursor.lastrowid)

    def _backup(self, batch_id: int, track_id: int) -> int:
        cursor = self.conn.execute(
            "INSERT INTO tag_backups "
            "(batch_id, track_id, prior_tags_json, created_at) "
            "VALUES (?, ?, '{\"genre\": \"Rock\"}', ?)",
            (batch_id, track_id, NOW),
        )
        return int(cursor.lastrowid)

    def test_backup_belongs_to_batch_and_track(self) -> None:
        batch_id = self._batch()
        track_id = self._track()
        backup_id = self._backup(batch_id, track_id)
        self.assertGreater(backup_id, 0)

    def test_one_backup_per_track_per_batch(self) -> None:
        batch_id = self._batch()
        track_id = self._track()
        self._backup(batch_id, track_id)
        with self.assertRaises(sqlite3.IntegrityError):
            self._backup(batch_id, track_id)

    def test_completed_batch_requires_completion_time(self) -> None:
        with self.assertRaises(sqlite3.IntegrityError):
            self._batch(status="completed")

    def test_backup_requires_known_batch_and_track(self) -> None:
        with self.assertRaises(sqlite3.IntegrityError):
            self._backup(9999, 9999)

    def test_deleting_batch_cascades_backups(self) -> None:
        batch_id = self._batch()
        track_id = self._track()
        self._backup(batch_id, track_id)
        self.conn.execute("DELETE FROM write_batches WHERE id = ?", (batch_id,))
        count = self.conn.execute("SELECT COUNT(*) FROM tag_backups").fetchone()[0]
        self.assertEqual(count, 0)


class InitializeDatabaseTests(unittest.TestCase):
    def test_creates_parent_directories_and_file(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "nested" / "library.sqlite3"
            connection = initialize_database(path)
            try:
                self.assertTrue(path.exists())
                self.assertEqual(
                    connection.execute("PRAGMA user_version").fetchone()[0],
                    SCHEMA_VERSION,
                )
                self.assertEqual(
                    connection.execute("PRAGMA foreign_keys").fetchone()[0], 1
                )
            finally:
                connection.close()


if __name__ == "__main__":
    unittest.main()
