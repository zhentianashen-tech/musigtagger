-- Music Tagger schema v2: network release-date lookup cache (additive only).
--
-- Migration v2 adds exactly one table and nothing else. No v1 table, column,
-- index, or constraint is modified, so an upgraded database behaves identically
-- to a v1 database for all v1 features (MUSI-14, leader-approved in advance).
--
-- The network provider (musigtagger.engine.network) caches MusicBrainz
-- release-group lookups keyed by the *normalized* (album, artist) pair so a
-- 47-instance library makes ~14 network queries instead of one per file.
-- Rows are pure lookup results: no personal data, no file contents, no paths.

CREATE TABLE release_date_cache (
    -- "normalized album<US>normalized artist" (US = \x1f, which cannot occur
    -- in normalized text; see musigtagger.engine.network.cache_key).
    cache_key                TEXT PRIMARY KEY,
    normalized_album         TEXT NOT NULL,
    normalized_artist        TEXT NOT NULL,
    -- found = 0 means "queried, no confident match" (negative cache: repeated
    -- batches do not re-query a work MusicBrainz could not resolve).
    found                    INTEGER NOT NULL CHECK (found IN (0, 1)),
    -- NULL unless found = 1; the earliest (first) release year of the
    -- matched release group.
    release_year             INTEGER CHECK (
                                 (found = 0 AND release_year IS NULL)
                                 OR (found = 1 AND release_year BETWEEN 1 AND 9999)
                             ),
    musicbrainz_release_group_id TEXT,
    matched_artist           TEXT,
    matched_release          TEXT,
    source_url               TEXT,
    -- Reviewer-facing flag for matches that disagree with the query text
    -- (e.g. album title variant); NULL when nothing is suspicious.
    suspicion                TEXT,
    queried_at               TEXT NOT NULL,
    CHECK (found = 0 OR (
        musicbrainz_release_group_id IS NOT NULL
        AND matched_artist IS NOT NULL
        AND matched_release IS NOT NULL
        AND source_url IS NOT NULL
    ))
);

CREATE INDEX idx_release_date_cache_keys ON release_date_cache (
    normalized_album, normalized_artist
);
