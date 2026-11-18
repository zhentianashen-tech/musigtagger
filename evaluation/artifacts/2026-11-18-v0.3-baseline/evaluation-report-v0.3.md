# Music Tagger — Evaluation Report

- Evaluation plan version: **v0.2**
- Dataset: fixed 47-file library (/test-data/music-working/eval-input-ncm-remux, read-only remux input)
- Run ids: v0.3-local, v0.3-network
- Taxonomy pinned: `1.0.0`

> **All thresholds below are operator-approved — APPROVED — operator sign-off 2026-11-17.** The values were approved unchanged on 2026-11-17.

## Gating summary

| Metric | Measured | Approved threshold | Verdict |
|---|---|---|---|
| Suggestion precision (overall) | 93.6% (44/47 checked) | ≥ 75% | ✅ meets threshold (APPROVED — operator sign-off 2026-11-17) |
| Coverage (tracks with ≥1 usable tag) | 93.6% (44/47) | ≥ 85% | ✅ meets threshold (APPROVED — operator sign-off 2026-11-17) |
| Batch completion rate | 100.0% (1/1) | = 100% | ✅ meets threshold (APPROVED — operator sign-off 2026-11-17) |
| Taxonomy conformance | 100.0% (94 tag refs checked) | = 100% | ✅ meets threshold (APPROVED — operator sign-off 2026-11-17) |
| Safety (source protection / backup / undo) | all checks passed | zero violations | ✅ meets threshold (APPROVED — operator sign-off 2026-11-17) |

## 1. Suggestion precision per category (primary metric)

*Reported with counts: the evaluation set is small (n=47), so a percentage resting on a handful of items must not be over-read.*

| Category | Suggested | Checked | Accepted | Rejected | Modified | Precision (acc/checked) |
|---|---|---|---|---|---|---|
| era | 47 | 0 | 0 | 0 | 0 | not computed |
| genre | 47 | 47 | 44 | 3 | 0 | 93.6% |
| **overall** | 94 | 47 | 44 | 3 | 0 | **93.6%** |

### Precision by suggestion source

| Source | Suggested | Checked | Accepted | Rejected | Modified | Precision |
|---|---|---|---|---|---|---|
| metadata.album | 47 | 47 | 44 | 3 | 0 | 93.6% |
| network.musicbrainz | 47 | 0 | 0 | 0 | 0 | not computed |

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

- Tag references checked: 94
- Unknown tag ids: 0
- Genre depth violations (depth > 2): 0
- Conformance: 100.0% — ✅ meets threshold (APPROVED — operator sign-off 2026-11-17)

## 5b. Expected-tag recall (plan v0.2 — report-only)

*Report-only: no recall threshold gates acceptance. Counts are shown with every rate.*

| Category | Expected | Exact | Parent-only | Missed | Recall (exact) | Recall (any) |
|---|---|---|---|---|---|---|
| era | 47 | 47 | 0 | 0 | 100.0% | 100.0% |
| genre | 47 | 44 | 0 | 3 | 93.6% | 93.6% |
| origin | 44 | 0 | 0 | 44 | 0.0% | 0.0% |
| **overall (instances)** | 138 | 91 | 0 | 47 | 65.9% | 65.9% |

### Per-work view

| Work | Expected | Exact | Parent-only | Missed | Recall (any) |
|---|---|---|---|---|---|
| free | 3 | 2 | 0 | 1 | 66.7% |
| golden | 3 | 2 | 0 | 1 | 66.7% |
| how it’s done | 3 | 2 | 0 | 1 | 66.7% |
| jinu’s lament | 3 | 2 | 0 | 1 | 66.7% |
| prologue (hunter’s mantra) | 2 | 1 | 0 | 1 | 50.0% |
| score suite | 2 | 1 | 0 | 1 | 50.0% |
| soda pop | 3 | 2 | 0 | 1 | 66.7% |
| strategy | 3 | 2 | 0 | 1 | 66.7% |
| takedown | 3 | 2 | 0 | 1 | 66.7% |
| takedown (jeongyeon, jihyo, chaeyoung) | 3 | 2 | 0 | 1 | 66.7% |
| what it sounds like | 3 | 2 | 0 | 1 | 66.7% |
| your idol | 3 | 2 | 0 | 1 | 66.7% |
| 사랑인가 봐 love, maybe | 3 | 2 | 0 | 1 | 66.7% |
| 오솔길 path | 3 | 2 | 0 | 1 | 66.7% |
| **overall (works)** | 40 | 26 | 0 | 14 | 65.0% |

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

None recorded.

## 9. Limitations

- Sample size: the fixed evaluation set is 47 files; per-category precision may rest on very few items. Counts are reported alongside percentages for this reason.
- The library comes from one source/folder; its genre and era distribution may not represent future batches.
- Ground truth is a single external evaluator; reasons on rejections/modifications keep drift auditable.

## 10. Evidence artifacts

- Event stream files read:
  - `evaluation/artifacts/2026-11-18-v0.3-baseline/engine-events.jsonl`
- Evaluator hand-check log (ground truth): see `--hand-check` input.
- Tagging-history log (the app's own §4 event stream) cross-checked in §7.
- Safety test notes: see `--safety-evidence` input and §6.
