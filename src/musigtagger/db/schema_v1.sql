-- Music Tagger library index and review state, schema version 1.
--
-- Conventions:
--   * every timestamp is ISO-8601 UTC text: YYYY-MM-DDTHH:MM:SS.sssZ
--   * tag ids are taxonomy ids, validated by the application against the
--     taxonomy version pinned in library_meta ('taxonomy_version')
--   * tag frame payloads are stored as JSON text; the application owns the
--     representation and must be able to restore it byte-for-byte.

CREATE TABLE schema_migrations (
    version     INTEGER PRIMARY KEY,
    description TEXT NOT NULL,
    applied_at  TEXT NOT NULL
);

-- One row per audio file in the scanned library. The scanner upserts on path.
CREATE TABLE tracks (
    id               INTEGER PRIMARY KEY,
    path             TEXT NOT NULL UNIQUE,
    title            TEXT,
    artist           TEXT,
    album            TEXT,
    genre            TEXT,
    year             INTEGER CHECK (year IS NULL OR year BETWEEN 1 AND 9999),
    duration_seconds REAL CHECK (duration_seconds IS NULL OR duration_seconds >= 0),
    format           TEXT,
    file_size_bytes  INTEGER CHECK (file_size_bytes IS NULL OR file_size_bytes >= 0),
    mtime_ns         INTEGER CHECK (mtime_ns IS NULL OR mtime_ns >= 0),
    -- Reserved for Phase 2 audio features. Phase 1 leaves this NULL.
    features_json    TEXT,
    last_scanned_at  TEXT NOT NULL,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL
);

CREATE INDEX idx_tracks_artist ON tracks (artist);
CREATE INDEX idx_tracks_album ON tracks (album);

-- Suggestions emitted by a provider run. A row is a review-queue item whose
-- status is one of the five review states. Suggestions are never mutated back
-- into 'suggested'; decisions move forward and are timestamped.
CREATE TABLE suggestions (
    id               INTEGER PRIMARY KEY,
    track_id         INTEGER NOT NULL REFERENCES tracks (id) ON DELETE CASCADE,
    tag_id           TEXT NOT NULL,
    confidence       REAL NOT NULL CHECK (confidence >= 0.0 AND confidence <= 1.0),
    source           TEXT NOT NULL,
    evidence         TEXT NOT NULL,
    taxonomy_version TEXT NOT NULL,
    engine_run_id    TEXT,
    status           TEXT NOT NULL DEFAULT 'suggested'
                     CHECK (status IN (
                         'suggested', 'accepted', 'edited', 'rejected', 'applied'
                     )),
    -- Effective tag id once a human has acted. For 'accepted' the application
    -- sets this to tag_id; for 'edited' it holds the corrected tag.
    final_tag_id     TEXT,
    reviewed_at      TEXT,
    applied_at       TEXT,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL,
    CHECK (
        (status IN ('suggested', 'rejected') AND final_tag_id IS NULL)
        OR (status IN ('accepted', 'edited', 'applied') AND final_tag_id IS NOT NULL)
    ),
    CHECK (status <> 'applied' OR applied_at IS NOT NULL)
);

CREATE INDEX idx_suggestions_track_status ON suggestions (track_id, status);
CREATE INDEX idx_suggestions_status ON suggestions (status);

-- One row per apply/undo batch. The application creates a batch and its
-- backups before touching any audio file, so a crashed or failed batch is
-- always recoverable.
CREATE TABLE write_batches (
    id               INTEGER PRIMARY KEY,
    kind             TEXT NOT NULL CHECK (kind IN ('apply', 'undo')),
    status           TEXT NOT NULL DEFAULT 'pending'
                     CHECK (status IN ('pending', 'completed', 'failed', 'undone')),
    taxonomy_version TEXT NOT NULL,
    backup_dir       TEXT,
    track_count      INTEGER NOT NULL DEFAULT 0 CHECK (track_count >= 0),
    note             TEXT,
    created_at       TEXT NOT NULL,
    completed_at     TEXT,
    CHECK (status <> 'completed' OR completed_at IS NOT NULL)
);

CREATE INDEX idx_write_batches_status ON write_batches (status);

-- Prior tag state for one track in one batch. "Mandatory backup" lives here:
-- a batch may not start writing until one row exists per target track.
CREATE TABLE tag_backups (
    id              INTEGER PRIMARY KEY,
    batch_id        INTEGER NOT NULL REFERENCES write_batches (id) ON DELETE CASCADE,
    track_id        INTEGER NOT NULL REFERENCES tracks (id) ON DELETE CASCADE,
    prior_tags_json TEXT NOT NULL,
    prior_file_hash TEXT,
    restored_at     TEXT,
    created_at      TEXT NOT NULL,
    UNIQUE (batch_id, track_id)
);

CREATE INDEX idx_tag_backups_track ON tag_backups (track_id);

-- Per-library metadata, notably the pinned taxonomy version that applied tags
-- must validate against. Written by the application on first scan.
CREATE TABLE library_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
