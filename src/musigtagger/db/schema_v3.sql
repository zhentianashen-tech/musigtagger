-- Music Tagger schema v3: query versioning for the release-date lookup cache.
--
-- Migration v3 is additive: it adds exactly one column to the v2
-- ``release_date_cache`` table and touches nothing else. No v1 table is
-- modified, and no cached row is deleted (MUSI-14 defect fix, 2026-11-17).
--
-- Why: the v0.2 era-recall defect (MUSI-14 reopened) changed the provider's
-- query construction. The 16 rows cached under the old query — all
-- ``found=false`` — would otherwise mask the fix forever: the cache is keyed
-- by (album, artist) and would keep answering "no match" without a network
-- attempt. Rows now carry the semantic ``query_version`` of the query that
-- produced them (see musigtagger.engine.network.QUERY_VERSION);
-- ``ReleaseDateCache.get`` only trusts rows written by the *current* query
-- version, so a lookup-rule change re-runs the fixed query automatically.
-- Old rows are kept (not deleted) so the audit trail of what the previous
-- query resolved remains inspectable.

ALTER TABLE release_date_cache
    ADD COLUMN query_version INTEGER NOT NULL DEFAULT 0;
