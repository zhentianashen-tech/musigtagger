# Network release-date lookup (MusicBrainz) — MUSI-14

The minimal network release-date lookup provider is the **only** network
capability in Phase 1 (operator-approved 2026-11-17, pulled forward from
Phase 3). General network enrichment (genre aggregation etc.) remains a
Phase 3 concern. This note documents the chosen endpoints, parameters,
caching, failure behaviour, and privacy properties.

## Endpoint and parameters

One HTTP request per distinct work:

```
GET https://musicbrainz.org/ws/2/release-group/?query=releasegroup:"<album>" AND artist:"<artist>"&fmt=json&limit=10
```

- `releasegroup:` and `artist:` phrase queries, Lucene-quoted, so album and
  artist text is treated as data, never as query syntax.
- `fmt=json`; `limit=10` is enough because resolution takes the first
  score-ordered compatible hit.
- **`first-release-date`** on the release-group search result is the
  earliest release of the *work* — exactly the "original/first release
  year" the operator asked for — so no second detail request is needed.

MusicBrainz asks anonymous clients to stay around **1 request/second**; the
provider paces actual network queries (`min_query_interval_seconds`, default
1.0) and caches every result, so a full-library batch makes ~14 queries once
and zero afterwards. Requests identify the application via User-Agent
`MusicTagger/0.1.0 (local personal-library tagger; no public contact endpoint)`.

## Matching rule (deterministic)

Search results arrive in MusicBrainz score order; the provider takes the
**first** entry whose `artist-credit` is compatible with the query artist
(at least one shared word of length ≥ 2 either way — exact equality is too
strict for multi-artist credits and translations) and carries a parseable
`first-release-date` year. If none matches, the lookup is recorded as a
negative cache entry ("no match") and the provider abstains.

Matches that disagree with the query text (e.g. the matched release-group
title differs from the queried album after normalization) are **flagged,
not silently accepted**: a warning is logged and the evidence string carries
a `FLAGGED:` prefix for the reviewer.

## Era mapping and confidence

The resolved year maps to the taxonomy's `era.<decade>s` tag through the
**same** mapping the local metadata provider uses
(`era.{year // 10 * 10}s`, must exist in taxonomy v1.0.0). Suggestions carry
`source = "network.musicbrainz"` and confidence **0.85** — deliberately
below embedded metadata (0.98) and above every text-derived era signal
(≤ 0.65). **This value is a proposal for evaluation tuning, not a settled
threshold.**

## Caching (schema migration v2)

Lookups are cached in the library SQLite database table
`release_date_cache`, keyed by the normalized `(album, artist)` pair
(normalized exactly like the local provider normalizes text). Migration v2
is purely additive — one new table, no v1 table or column touched — and was
escalated and leader-approved in advance via MUSI-14, per CONTRACTS §5.
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
| Network unavailable / DNS / refused | `NetworkLookupError` → runner logs the skip, batch continues |
| Timeout | Every HTTP call carries `timeout_seconds` (default 5 s); a hanging server cannot stall the batch |
| Rate limit (HTTP 429/503) | Same abstention path, message names the rate limit |
| 5xx / non-JSON body | Same abstention path |
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
