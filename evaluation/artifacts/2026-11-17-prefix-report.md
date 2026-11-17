# Music Tagger — Evaluation Report

- Evaluation plan version: **v0.1**
- Dataset: frozen 47-track NCM remux set (/test-data/music-working/eval-input-ncm-remux)
- Run ids: run-f8dbbf0d73cd41e996b719171b564fdd
- Taxonomy pinned: `1.0.0`

> **All thresholds below are proposals — PROPOSED — pending human sign-off.** Nothing in this report settles an acceptance bar.

## Gating summary

| Metric | Measured | Proposed threshold | Verdict |
|---|---|---|---|
| Suggestion precision (overall) | 0.0% (0/5 checked) | ≥ 75% | ❌ fails proposed threshold (PROPOSED — pending human sign-off) |
| Coverage (tracks with ≥1 usable tag) | 10.6% (5/47) | ≥ 85% | ❌ fails proposed threshold (PROPOSED — pending human sign-off) |
| Batch completion rate | 100.0% (1/1) | = 100% | ✅ meets proposed threshold (PROPOSED — pending human sign-off) |
| Taxonomy conformance | 100.0% (10 tag refs checked) | = 100% | ✅ meets proposed threshold (PROPOSED — pending human sign-off) |
| Safety (source protection / backup / undo) | FAIL | zero violations | ❌ fails proposed threshold (PROPOSED — pending human sign-off) |

## 1. Suggestion precision per category (primary metric)

*Reported with counts: the evaluation set is small (n=47), so a percentage resting on a handful of items must not be over-read.*

| Category | Suggested | Checked | Accepted | Rejected | Modified | Precision (acc/checked) |
|---|---|---|---|---|---|---|
| genre | 5 | 5 | 0 | 0 | 5 | 0.0% |
| **overall** | 5 | 5 | 0 | 0 | 5 | **0.0%** |

### Precision by suggestion source

| Source | Suggested | Checked | Accepted | Rejected | Modified | Precision |
|---|---|---|---|---|---|---|
| metadata.path | 5 | 5 | 0 | 0 | 5 | 0.0% |

## 2. Coverage

- Tracks with ≥1 usable tag: **5**
- Denominator: **47** (scan report (indexed tracks))
- Coverage: **10.6%** — ❌ fails proposed threshold (PROPOSED — pending human sign-off)

## 3. Correction burden

- Modifications per checked track: 1.00
- Rejections per checked track: 0.00
- App-side edits per track (cross-check from review outcomes): 0.00

## 4. Batch completion (gating robustness metric)

- Batches observed: 1; completed without mid-run crash: 1 (rate 100.0%) — ✅ meets proposed threshold (PROPOSED — pending human sign-off)

## 5. Taxonomy conformance

- Tag references checked: 10
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

None recorded.

## 9. Limitations

- Sample size: the fixed evaluation set is 47 files; per-category precision may rest on very few items. Counts are reported alongside percentages for this reason.
- The library comes from one source/folder; its genre and era distribution may not represent future batches.
- Ground truth is a single external evaluator; reasons on rejections/modifications keep drift auditable.

## 10. Evidence artifacts

- Event stream files read:
  - `eval-run-remux-prefix/engine-events.jsonl`
- Evaluator hand-check log (ground truth): see `--hand-check` input.
- Tagging-history log (the app's own §4 event stream) cross-checked in §7.
- Safety test notes: see `--safety-evidence` input and §6.
