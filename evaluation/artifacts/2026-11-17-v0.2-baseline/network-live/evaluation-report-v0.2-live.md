# Music Tagger — Evaluation Report

- Evaluation plan version: **v0.2**
- Dataset: frozen 47-track NCM remux set; engine main 5354663 (MUSI-14 edc827d); live MusicBrainz run (16 unique pairs, 0 matches)
- Run ids: v0.2-local
- Taxonomy pinned: `1.0.0`

> **All thresholds below are operator-approved — APPROVED — operator sign-off 2026-11-17.** The values were approved unchanged on 2026-11-17.

## Gating summary

| Metric | Measured | Approved threshold | Verdict |
|---|---|---|---|
| Suggestion precision (overall) | 93.6% (44/47 checked) | ≥ 75% | ✅ meets threshold (APPROVED — operator sign-off 2026-11-17) |
| Coverage (tracks with ≥1 usable tag) | 93.6% (44/47) | ≥ 85% | ✅ meets threshold (APPROVED — operator sign-off 2026-11-17) |
| Batch completion rate | 100.0% (1/1) | = 100% | ✅ meets threshold (APPROVED — operator sign-off 2026-11-17) |
| Taxonomy conformance | 100.0% (47 tag refs checked) | = 100% | ✅ meets threshold (APPROVED — operator sign-off 2026-11-17) |
| Safety (source protection / backup / undo) | all checks passed | zero violations | ✅ meets threshold (APPROVED — operator sign-off 2026-11-17) |

## 1. Suggestion precision per category (primary metric)

*Reported with counts: the evaluation set is small (n=47), so a percentage resting on a handful of items must not be over-read.*

| Category | Suggested | Checked | Accepted | Rejected | Modified | Precision (acc/checked) |
|---|---|---|---|---|---|---|
| genre | 47 | 47 | 44 | 3 | 0 | 93.6% |
| **overall** | 47 | 47 | 44 | 3 | 0 | **93.6%** |

### Precision by suggestion source

| Source | Suggested | Checked | Accepted | Rejected | Modified | Precision |
|---|---|---|---|---|---|---|
| metadata.album | 47 | 47 | 44 | 3 | 0 | 93.6% |

## 2. Coverage

- Tracks with ≥1 usable tag: **44**
- Denominator: **47** (scan report (indexed tracks))
- Coverage: **93.6%** — ✅ meets threshold (APPROVED — operator sign-off 2026-11-17)

## 3. Correction burden

- Modifications per checked track: 0.00
- Rejections per checked track: 0.06
- App-side edits per track (cross-check from review outcomes): 0.00

## 4. Batch completion (gating robustness metric)

- Batches observed: 1; completed without mid-run crash: 1 (rate 100.0%) — ✅ meets threshold (APPROVED — operator sign-off 2026-11-17)

## 5. Taxonomy conformance

- Tag references checked: 47
- Unknown tag ids: 0
- Genre depth violations (depth > 2): 0
- Conformance: 100.0% — ✅ meets threshold (APPROVED — operator sign-off 2026-11-17)

## 5b. Expected-tag recall (plan v0.2 — report-only)

*Report-only: no recall threshold gates acceptance. Counts are shown with every rate.*

| Category | Expected | Exact | Parent-only | Missed | Recall (exact) | Recall (any) |
|---|---|---|---|---|---|---|
| era | 47 | 0 | 0 | 47 | 0.0% | 0.0% |
| genre | 47 | 44 | 0 | 3 | 93.6% | 93.6% |
| origin | 44 | 0 | 0 | 44 | 0.0% | 0.0% |
| **overall (instances)** | 138 | 44 | 0 | 94 | 31.9% | 31.9% |

### Per-work view

| Work | Expected | Exact | Parent-only | Missed | Recall (any) |
|---|---|---|---|---|---|
| free | 3 | 1 | 0 | 2 | 33.3% |
| golden | 3 | 1 | 0 | 2 | 33.3% |
| how it’s done | 3 | 1 | 0 | 2 | 33.3% |
| jinu’s lament | 3 | 1 | 0 | 2 | 33.3% |
| prologue (hunter’s mantra) | 2 | 0 | 0 | 2 | 0.0% |
| score suite | 2 | 0 | 0 | 2 | 0.0% |
| soda pop | 3 | 1 | 0 | 2 | 33.3% |
| strategy | 3 | 1 | 0 | 2 | 33.3% |
| takedown | 3 | 1 | 0 | 2 | 33.3% |
| takedown (jeongyeon, jihyo, chaeyoung) | 3 | 1 | 0 | 2 | 33.3% |
| what it sounds like | 3 | 1 | 0 | 2 | 33.3% |
| your idol | 3 | 1 | 0 | 2 | 33.3% |
| 사랑인가 봐 love, maybe | 3 | 1 | 0 | 2 | 33.3% |
| 오솔길 path | 3 | 1 | 0 | 2 | 33.3% |
| **overall (works)** | 40 | 12 | 0 | 28 | 30.0% |

- Tracks with expected tags but no suggestions: **0**

## 6. Safety

- Evidence records read: 8

| Check | Result | Detail |
|---|---|---|
| source-root protection (zero writes to music-source) | ✅ pass | no write records under /test-data/music-source |
| backup exists before every write batch | ✅ pass | every write record is preceded by a backup record |
| undo restores prior state | ✅ pass | all undo operations succeeded and cover the written tracks |

Approved thresholds: zero writes to the source library, zero corruption incidents, undo verified on every sampled case (APPROVED — operator sign-off 2026-11-17).

## 7. Cross-check: evaluator decisions vs app review outcomes

- Comparable decisions: 0; agreements: 0

## 8. Defects and findings (severity order)

| Severity | Classification | Finding | Responsible role |
|---|---|---|---|
| critical | tagging-engine defect | MusicBrainz date provider resolves 0/16 unique album+artist pairs: all are cached no-match, so era recall is 0/47 (0.0%) | Tagging Engine Engineer (MUSI-14 provider) |
| medium | taxonomy/specification problem | Album-level genre.k-pop remains a false positive on the 3 film-score instances (taxonomy v1.0.0 has no film-score tag) | Taxonomy Designer / Lead (post-acceptance) |
| medium | tagging-engine defect | No-match cache is keyed only by (album, artist); a query fix will be masked until the cache is invalidated or versioned | Tagging Engine Engineer / Application & Integration Engineer |
| info | evaluation-data problem | All five approved acceptance bars pass; era recall is 0% and is a provider correctness defect to fix, not a threshold failure | Evaluation & Review Agent |
| info | evaluation-data problem | Network protocol complied: project UA on every request, <=1 req/s, 3-attempt retry with backoff, cache reused, failures and retries recorded | Evaluation & Review Agent |

### Reproduction evidence

- **MusicBrainz date provider resolves 0/16 unique album+artist pairs: all are cached no-match, so era recall is 0/47 (0.0%)**
  - Evidence: Live run: 16 unique pairs, 0 era suggestions, 16/16 cached found=false. The provider queries releasegroup:"<embedded album>" AND artist:"<track artists>". The library is a various-artists soundtrack: the official release group is 'KPop Demon Hunters: Soundtrack From the Netflix Film' (2025-06-20) credited to the cast, so a track artist (TWICE, MeloMance, Marcelo Zarvos) yields 0 results; the composite credit 'HUNTR/X/EJAE/AUDREY NUNA/...' also yields 0; the ' / Deluxe Version' album suffix yields 0. Album-only query returns the correct RG. This is a provider query-construction defect against the operator's 'correct release date is required' rule, not a denominator or test-data problem.
  - Reproduction: curl -A 'MusicTagger/0.1.0 ...' 'https://musicbrainz.org/ws/2/release-group/?query=releasegroup%3A%22KPop%20Demon%20Hunters%20(Soundtrack%20from%20the%20Netflix%20Film)%22&fmt=json' -> 1 result (2025-06-20); adding AND artist:"TWICE" -> 0 results.
- **Album-level genre.k-pop remains a false positive on the 3 film-score instances (taxonomy v1.0.0 has no film-score tag)**
  - Evidence: Score Suite (2) and Prologue (1) are orchestral cues; the hand-check rejects their genre.k-pop suggestions (expected genre.orchestral). Post-acceptance taxonomy v1.1 gap.
- **No-match cache is keyed only by (album, artist); a query fix will be masked until the cache is invalidated or versioned**
  - Evidence: The 16 no-match entries are stored as found=false under normalized (album, artist). A corrected query would hit these rows and never reach MusicBrainz. The cache needs a query-version key or a one-time invalidation.
- **All five approved acceptance bars pass; era recall is 0% and is a provider correctness defect to fix, not a threshold failure**
  - Evidence: Precision 93.6% (44/47), coverage 93.6% (44/47), batch completion 100%, taxonomy conformance 100% (47 refs), safety 3/3 on the option-A copy smoke. Expected-tag recall is report-only; era 0/47, origin 0/44 (accepted gap), overall 31.9% instance / 30.0% work.
- **Network protocol complied: project UA on every request, <=1 req/s, 3-attempt retry with backoff, cache reused, failures and retries recorded**
  - Evidence: Pass 1: cache 0->11, 19 track hits / 28 misses, 28 requests, 17 failed attempts, 9 retries, min start interval 1.101 s. Pass 2: cache 11->16, 42 hits / 5 misses, 6 requests, 1 failed attempt, 1 retry, min 1.102 s. All requests carried the project UA. Final 16/16 pairs returned 200 no-match; no transport-unresolved pair remains in the final run.

## 9. Limitations

- Sample size: the fixed evaluation set is 47 files; per-category precision may rest on very few items. Counts are reported alongside percentages for this reason.
- The library comes from one source/folder; its genre and era distribution may not represent future batches.
- Ground truth is a single external evaluator; reasons on rejections/modifications keep drift auditable.

## 10. Evidence artifacts

- Event stream files read:
  - `eval-run-v0.2-network-live2/engine-events.jsonl`
- Evaluator hand-check log (ground truth): see `--hand-check` input.
- Tagging-history log (the app's own §4 event stream) cross-checked in §7.
- Safety test notes: see `--safety-evidence` input and §6.

## 11. Measured era recall (report-only) — 0/47, definitive

| Level | Expected | Exact | Parent-only | Missed | Recall |
|---|---|---|---|---|---|
| Instances | 47 | 0 | 0 | 47 | **0.0%** |
| Works | 14 | 0 | 0 | 14 | **0.0%** |

- Denominator is the full frozen set: 47 expected `era.2020s` tags, 47 missed.
  No unresolved work was excluded.
- Final provider state: **16/16 unique pairs returned HTTP 200 with zero matching
  release groups** and were cached as `found=false`. There are no
  transport-unresolved pairs in the final run.
- Pass 1 left 5 pairs unresolved after 3 attempts (17 instances, MusicBrainz
  503); pass 2 retried only those misses and all 5 returned no-match. Both passes
  are included in the ledger; only pass 2's event stream is scored, and every
  pair is resolved no-match.
- Overall expected-tag recall: genre 44/47 (93.6%), era 0/47, origin 0/44
  (accepted Phase 2/3 gap) → **31.9% instance / 30.0% work**.

## 12. Cache, requests, failures, retries, pacing

| Pass | Cache rows | Track cache hits | Track misses | Network requests | Failed attempts | Retries | Min start interval |
|---|---|---|---|---|---|---|---|
| 1 (`v0.2-network` live) | 0 → 11 no-match | 19 | 28 | 28 | 17 | 9 | 1.101 s |
| 2 (retry misses) | 11 → 16 no-match | 42 | 5 | 6 | 1 | 1 | 1.102 s |

- User-Agent on every request: `MusicTagger/0.1.0 (local personal-library
  tagger; https://github.com/zhentianashen-tech/musigtagger)`.
- Retry policy in the evaluation transport: 3 attempts per pair, 2 s / 4 s
  backoff; the provider itself does not retry. Failed pairs are memoized per
  batch and are not written to the cache, so a rerun retries them.
- Observed start-to-start intervals are all ≥1.101 s (≤0.91 req/s); the min is
  recorded above.
- The existing cache was empty before the run (the prior offline run cached no
  failures). All 16 pairs were therefore misses; pass 2 fetched only the 5
  misses left by pass 1.

## 13. Root cause and limitations

The provider builds `releasegroup:"<embedded album>" AND artist:"<track
artists>"`. On a various-artists soundtrack that fails three ways:

1. **Track artist is not the release-group credit.** The official RG
   `KPop Demon Hunters: Soundtrack From the Netflix Film` (2025-06-20) is
   credited to `KPop Demon Hunters Cast; HUNTR/X; Saja Boys`. Querying
   `artist:"TWICE"`, `"MeloMance"` or `"Marcelo Zarvos"` returns 0.
2. **Composite artist strings.** The descriptors join credits with `/`
   (`HUNTR/X/EJAE/AUDREY NUNA/...`); the quoted phrase matches nothing.
3. **Deluxe album suffix.** The deluxe album string ends with
   ` / Deluxe Version)`, which returns 0; album-only returns the RG.

A fix belongs to the provider owner (album-only query + artist-compatibility,
recording-level search, or edition-suffix stripping). It was not changed here.
The no-match cache entries must be invalidated/versioned when that fix lands,
otherwise the cached `found=false` rows mask it.

**Limitation:** this run measures the provider as delivered; it does not prove
MusicBrainz has no data for these works. Album-only queries do return the
correct 2025 RG, so the date exists and is reachable. Safety is the
operator-approved option-A scope (2-track copy smoke, MP3/ID3); full app
behaviour remains with the MUSI-8 review and MUSI-10 integration pass.

## 14. Reproduce

```bash
# from a main checkout, with the harness on PYTHONPATH
PYTHONPATH=src:evaluation python evaluation/tools/run_v0_2_network_baseline.py \
  eval-run-v0.2-network --cache-db <prior-cache.sqlite3> --taxonomy taxonomy
PYTHONPATH=evaluation python -m evalharness worksheet \
  --events eval-run-v0.2-network/engine-events.jsonl --out eval-run-v0.2-network/worksheet.jsonl
PYTHONPATH=evaluation python -m evalharness report \
  --events eval-run-v0.2-network/engine-events.jsonl \
  --hand-check eval-run-v0.2-network/hand-check.jsonl \
  --prelabels evaluation/fixtures/track-pre-label-worksheet-v0.2.csv \
  --scan-report eval-run-v0.2-network/scan-report.json \
  --batches eval-run-v0.2-network/batches.json \
  --taxonomy-dir taxonomy --out eval-run-v0.2-network/report.md
```

