# Network release-date lookup (MusicBrainz) — MUSI-14

The minimal network release-date lookup provider is the **only** network
capability in Phase 1 (operator-approved 2026-11-17, pulled forward from
Phase 3). General network enrichment (genre aggregation etc.) remains a
Phase 3 concern. This note documents the chosen endpoints, parameters,
caching, failure behaviour, and privacy properties.

## Endpoint and parameters

Two HTTP requests per distinct work at most (stage 2 runs only when stage 1
matches nothing):

```
GET https://musicbrainz.org/ws/2/release-group/?query=releasegroup:"<album>" AND artist:"<artist>"&fmt=json&limit=10   # stage 1
GET https://musicbrainz.org/ws/2/release-group/?query=releasegroup:"<album>"&fmt=json&limit=10                        # stage 2
```

- `<album>` is the embedded album string with any trailing **edition
  suffix** stripped (` / Deluxe Version`, `- Remastered Edition`,
  `(Deluxe)` … — only segments *starting* with a known edition word, so
  genuine album titles are preserved). An edition suffix never matches a
  release-group title.
- `releasegroup:` and `artist:` phrase queries, Lucene-quoted, so album and
  artist text is treated as data, never as query syntax.
- `fmt=json`; `limit=10` is enough because resolution takes the first
  score-ordered compatible hit.
- **`first-release-date`** on the release-group search result is the
  earliest release of the *work* — exactly the "original/first release
  year" the operator asked for — so no second detail request is needed.

MusicBrainz asks anonymous clients to stay around **1 request/second**; the
transport enforces **≥ 1.1 s between any two HTTP requests, across retries
and pairs alike** (the 1.0 s default measured 503 bursts on the v0.2
rerun), and the provider caches every result, so a full-library batch makes
~14 lookups once and zero afterwards. Requests identify the application via
User-Agent
`MusicTagger/0.1.0 (local personal-library tagger; https://github.com/zhentianashen-tech/musigtagger)`.

## Why two stages (v0.2 era-recall defect, fixed 2026-11-17)

The original single-stage query `releasegroup:"<album>" AND artist:"<artist>"`
returned **zero** results for every track of a various-artists soundtrack
library: a cast-credited release group (`KPop Demon Hunters Cast/HUNTR/X/
Saja Boys`) shares no artist token with a per-track artist (`TWICE`,
`MeloMance`, `Marcelo Zarvos`), and the embedded ` / Deluxe Version` album
suffix matched no title — while album-only queries returned the correct
release group immediately. Hence:

1. **Stage 1 — precise.** Album + artist query; the first score-ordered
   entry whose artist credit is compatible wins. Normal libraries resolve
   here with no suspicion.
2. **Stage 2 — album-only fallback.** Runs only when stage 1 matched
   nothing. The guard becomes a strong **album title** match (normalized
   equality, or containment either direction for punctuation/edition
   variants). An artist credit that shares no token with the query artist
   no longer rejects the entry — it is **FLAGGED** in the evidence and
   logged, never silently accepted, so the reviewer decides (standing
   guidance: discrepancy cases go to the user at review).

## Matching rule (deterministic)

Search results arrive in MusicBrainz score order.

- **Stage 1:** the first entry whose `artist-credit` is compatible with the
  query artist (at least one shared word either way — exact equality is too
  strict for multi-artist credits and translations) and carries a parseable
  `first-release-date` year wins. Entries credited to an incompatible
  artist are rejected outright.
- **Stage 2:** the first title-compatible entry with a compatible artist
  credit wins; if none, the first *title-compatible* entry is used with an
  `artist not credited` flag. Entries whose title does not match the album
  at all are rejected outright.

If nothing matches, the lookup is recorded as a negative cache entry ("no
match") and the provider abstains.

Matches that disagree with the query text (matched release-group title
differs from the queried album after normalization, or the stage-2 artist
mismatch) are **flagged, not silently accepted**: a warning is logged and
the evidence string carries a `FLAGGED:` prefix for the reviewer.

## Era mapping and confidence

The resolved year maps to the taxonomy's `era.<decade>s` tag through the
**same** mapping the local metadata provider uses
(`era.{year // 10 * 10}s`, must exist in taxonomy v1.0.0). Suggestions carry
`source = "network.musicbrainz"` and confidence **0.85** — deliberately
below embedded metadata (0.98) and above every text-derived era signal
(≤ 0.65). **This value is a proposal for evaluation tuning, not a settled
threshold.**

## Caching (schema migrations v2 + v3)

Lookups are cached in the library SQLite database table
`release_date_cache`, keyed by the normalized `(album, artist)` pair
(normalized exactly like the local provider normalizes text). Migration v2
is purely additive — one new table, no v1 table or column touched — and was
escalated and leader-approved in advance via MUSI-14, per CONTRACTS §5.

Every row carries the semantic **`query_version`** of the lookup that
produced it (migration v3 adds the column; also additive). The provider
only trusts rows written by the *current* query version
(`musigtagger.engine.network.QUERY_VERSION`). When the query construction
or matching rule changes, the version is bumped and stale rows — including
the 16 `found=false` rows that masked the v0.2 era-recall defect — are
ignored and overwritten by the fixed query. Old rows are kept, not deleted,
so the audit trail remains inspectable.

Negative results are cached too, so repeated batches never re-query a work
MusicBrainz could not resolve. The cache is refreshed on re-query only via
an explicit upsert; entries carry `queried_at` for auditing.

Contract note: CONTRACTS §2 describes `suggest` as free of I/O; the leader
approved (MUSI-14) that this provider touches **only** its own cache table
inside `suggest`, via a cache injected through the constructor. The
`suggest(track_descriptor)` signature and the pure-value contract are
unchanged.

## Failure behaviour (CONTRACTS §3.6)

| Condition | Behaviour |
|---|---|
| Network unavailable / DNS / refused | `NetworkLookupError` → runner logs the skip, batch continues; **not** retried within the run (fails fast), retried on the next run |
| Timeout | Every HTTP call carries `timeout_seconds` (default 5 s); a hanging server cannot stall the batch |
| Rate limit / transient 5xx (429, 500, 502, 503, 504) | Retried in-run, bounded (5 attempts, paced backoff ≥ 1.1 s); then the same abstention path |
| Non-transient HTTP error / non-JSON body | Same abstention path |
| No matching release group | Empty suggestion list + negative cache entry |
| Album or artist missing | Empty suggestion list, no network call |
| Decade missing from taxonomy | Abstains (never invents tags) |

The runner (`SuggestionRunner`) already isolates per-track provider
exceptions, so one network failure never aborts or hangs the batch. With
`--no-network` (or with the provider simply not constructed) a run degrades
to exactly the pre-MUSI-14 behaviour.

## Privacy / locality

Network requests carry **only** the album and artist query strings and the
User-Agent. No personal data, no file contents, no paths, no telemetry.
Lookup results persist only in the local library database; nothing is sent
to or stored in any cloud service.

## CLI

```
musigtagger-suggest /path/to/music [--library library.sqlite3]
                    [--events history/engine-events.jsonl]
                    [--no-network] [--json]
```

Suggest path only: it prints proposals (tag, confidence, source, evidence)
and abstentions, and never writes audio files — the sole-writer boundary
stays with the application layer.
