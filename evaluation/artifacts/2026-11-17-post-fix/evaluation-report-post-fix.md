# Music Tagger — Evaluation Report

- Evaluation plan version: **v0.1**
- Dataset: frozen 47-track NCM remux set (/test-data/music-working/eval-input-ncm-remux); 14 works / 47 instances; engine = main ea40353
- Run ids: run-e83520cfc5a94969a100df91f9ca8579
- Taxonomy pinned: `1.0.0`

> **All thresholds below are proposals — PROPOSED — pending human sign-off.** Nothing in this report settles an acceptance bar.

## Gating summary

| Metric | Measured | Proposed threshold | Verdict |
|---|---|---|---|
| Suggestion precision (overall) | 93.6% (44/47 checked) | ≥ 75% | ✅ meets proposed threshold (PROPOSED — pending human sign-off) |
| Coverage (tracks with ≥1 usable tag) | 93.6% (44/47) | ≥ 85% | ✅ meets proposed threshold (PROPOSED — pending human sign-off) |
| Batch completion rate | 100.0% (1/1) | = 100% | ✅ meets proposed threshold (PROPOSED — pending human sign-off) |
| Taxonomy conformance | 100.0% (47 tag refs checked) | = 100% | ✅ meets proposed threshold (PROPOSED — pending human sign-off) |
| Safety (source protection / backup / undo) | FAIL | zero violations | ❌ fails proposed threshold (PROPOSED — pending human sign-off) |

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
- Coverage: **93.6%** — ✅ meets proposed threshold (PROPOSED — pending human sign-off)

## 3. Correction burden

- Modifications per checked track: 0.00
- Rejections per checked track: 0.06
- App-side edits per track (cross-check from review outcomes): 0.00

## 4. Batch completion (gating robustness metric)

- Batches observed: 1; completed without mid-run crash: 1 (rate 100.0%) — ✅ meets proposed threshold (PROPOSED — pending human sign-off)

## 5. Taxonomy conformance

- Tag references checked: 47
- Unknown tag ids: 0
- Genre depth violations (depth > 2): 0
- Conformance: 100.0% — ✅ meets proposed threshold (PROPOSED — pending human sign-off)

## 6. Safety

- Evidence records read: 0

| Check | Result | Detail |
|---|---|---|
| safety evidence present | ❌ FAIL | no backup/write/undo evidence supplied — safety is unverified, which fails the report by design |

Proposed thresholds: zero writes to the source library, zero corruption incidents, undo verified on every sampled case (PROPOSED — pending human sign-off).

## 7. Cross-check: evaluator decisions vs app review outcomes

- Comparable decisions: 0; agreements: 0

## 8. Defects and findings (severity order)

| Severity | Classification | Finding | Responsible role |
|---|---|---|---|
| medium | taxonomy/specification problem | No film-score/soundtrack genre in taxonomy v1.0.0, so album-level K-pop inference mis-tags score cues (Score Suite x2, Prologue x1) | Tag Taxonomy Designer |
| low | tagging-engine defect | Album-level genre signal applied uniformly to score cues: 3/47 instances rejected (Score Suite x2, Prologue x1) | Tagging Engine Engineer |
| info | evaluation-data problem | All 47 suggestions are one tag on one album (KPop Demon Hunters soundtrack); precision does not generalize beyond genre.k-pop on this set | Evaluation & Review Agent |

### Reproduction evidence


## 9. Limitations

- Sample size: the fixed evaluation set is 47 files; per-category precision may rest on very few items. Counts are reported alongside percentages for this reason.
- The library comes from one source/folder; its genre and era distribution may not represent future batches.
- Ground truth is a single external evaluator; reasons on rejections/modifications keep drift auditable.

## 10. Evidence artifacts

- Event stream files read:
  - `../eval-run-remux-post-fix/engine-events.jsonl`
- Evaluator hand-check log (ground truth): see `--hand-check` input.
- Tagging-history log (the app's own §4 event stream) cross-checked in §7.
- Safety test notes: see `--safety-evidence` input and §6.

## Per-work vs per-instance reporting (14 works / 47 instances)

The frozen set is 14 distinct works: 7 works x5 instances, 5 works x2, 2 works x1. Instance-level figures let the seven five-instance works dominate; the work-level rows deduplicate decisions to (work, tag) pairs.

| Level | Units | Suggestions | Checked | Accepted | Rejected | Modified | Precision | Coverage |
|---|---|---|---|---|---|---|---|---|
| instance | 47 tracks | 47 | 47 | 44 | 3 | 0 | 93.6% | 93.6% (44/47) |
| work (dedup) | 14 works | 14 pairs | 14 | 12 | 2 | 0 | 85.7% | 85.7% (12/14) |

- Works fully accepted (no rejected/modified pair): 12/14 (85.7%).
- Per-category at work level: genre 12/14 accepted.

### Era / release-date coverage (explicit)

- Era suggestions: **0** at instance level, **0** at work level.
- Era coverage: **0.0%** of instances, **0.0%** of works.
- On this library that is the correct outcome under the binding operator rule: no local source on any of the 47 tracks carries a year or date. The local-date audit verified 0 embedded date tags (`TDRC`/`TDRL`/`TYER`/`date`/`year`), 0 filename year matches, 0 title year matches and 0 album year matches. A date present locally but not suggested would be the bug; there is none to surface.

### Work-level decisions

| Work | Instances | Tag | Source | Verdict |
|---|---|---|---|---|
| Free | 5 | `genre.k-pop` | metadata.album | accept |
| Golden | 5 | `genre.k-pop` | metadata.album | accept |
| How It’s Done | 5 | `genre.k-pop` | metadata.album | accept |
| Jinu’s Lament | 1 | `genre.k-pop` | metadata.album | accept |
| Prologue (Hunter’s Mantra) | 1 | `genre.k-pop` | metadata.album | reject |
| Score Suite | 2 | `genre.k-pop` | metadata.album | reject |
| Soda Pop | 5 | `genre.k-pop` | metadata.album | accept |
| Strategy | 2 | `genre.k-pop` | metadata.album | accept |
| Takedown | 5 | `genre.k-pop` | metadata.album | accept |
| TAKEDOWN (JEONGYEON, JIHYO, CHAEYOUNG) | 2 | `genre.k-pop` | metadata.album | accept |
| What It Sounds Like | 5 | `genre.k-pop` | metadata.album | accept |
| Your Idol | 5 | `genre.k-pop` | metadata.album | accept |
| 사랑인가 봐 Love, Maybe | 2 | `genre.k-pop` | metadata.album | accept |
| 오솔길 Path | 2 | `genre.k-pop` | metadata.album | accept |
### Re-run delta vs the v0.1 prefix baseline (same frozen input)

| Run | Engine state | Suggestions | Instances with a suggestion | Usable instances | Accepted | Era suggestions |
|---|---|---|---|---|---|---|
| v0.1 prefix | `main` @ `1a92b2c` (no provider fix) | 5 | 5/47 (10.6%) | 5/47 (10.6%) | 0/5 (0.0%) | 0 |
| post-fix | `main` @ `ea40353` (carries `0a6e90a`) | 47 | 47/47 (100.0%) | 44/47 (93.6%) | 44/47 (93.6%) | 0 |

- The "Soda Pop" title-word accident is fixed: the stream contains **0** `genre.pop` suggestions. The five Soda Pop instances now receive `genre.k-pop` from the album and are accepted.
- All new coverage comes from one signal: `metadata.album` → `genre.k-pop` (the album title contains the `kpop` alias), confidence 0.60, on every one of the 47 instances.
- The provider still abstains on mood, activity, origin and the user-owned personal facet. Era abstains because no local date exists (see the local-date audit above), which is the honest-abstention branch of the binding requirement, not a miss.

### Local-date audit (binding requirement: a date present locally must become an era suggestion)

Audited every one of the 47 frozen instances, read-only, against all four local sources:

- Embedded date tags (`TDRC`, `TDRL`, `TDOR`, `TYER`, `date`, `year`): **0/47**.
- Year in filename: **0/47**.
- Year in embedded title: **0/47**.
- Year in embedded album: **0/47**.

Embedded tags present are exactly `TIT2` (title) 47/47, `TPE1` (artist) 47/47, `TALB` (album) 47/47, `APIC:Cover` 47/47, and `TSSE` (`encoder` tag written by the remux) 47/47; no genre, no date. Therefore **0 era suggestions is correct for this library**, and the engine's embedded-year → `era.<decade>s` path is covered by the new explicit test `test_embedded_release_date_always_surfaces_an_era` (full dates `1994-05-01`, `1994-05`, `1994` via `_parse_year`), not by this dataset.

### Path-dependence check

The 47 suggestions are all one tag (`genre.k-pop`) on one album; the 44 accepted instances collapse to 12 accepted works. The 93.6% / 85.7% figures are therefore evidence that the album signal works for this soundtrack set, not evidence of general genre precision. They should not be compared to the 75% proposal as if they measured the provider's performance across categories.
### Finding reproduction — the three rejected instances

| Track file (in the frozen input) | Suggested | Decision | Reason |
|---|---|---|---|
| `Marcelo Zarvos - Score Suite.mp3` | `genre.k-pop` @0.60 `metadata.album` | reject | 3:00 orchestral film-score suite by the film composer; not a K-pop song. No other tag was offered. |
| `Marcelo Zarvos - Score Suite (1).mp3` | `genre.k-pop` @0.60 `metadata.album` | reject | Duplicate instance of the same score suite (standard/deluxe album pair); not a K-pop song. |
| `Marcelo Zarvos,EJAE - Prologue (Hunter’s Mantra).mp3` | `genre.k-pop` @0.60 `metadata.album` | reject | 96 s film-score/chant prologue by the film composer with EJAE; not a K-pop song. |

Reproduce with the committed artifacts: the rejected rows in
`evaluation/artifacts/2026-11-17-post-fix/hand-check.jsonl`, the matching
`metadata.album` evidence lines in `engine-events.jsonl`, and the work-level
table produced by `evaluation/tools/per_work_rollup.py`.
