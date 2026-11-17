# Music Tagger — Evaluation Report

- Evaluation plan version: **v0.1**
- Dataset: fixed 47-file library (47 converted FLAC + 47 original .ncm + meta/) at /test-data/music-source, read-only; scan executed by the real MUSI-8 app @ c3dc20b
- Run ids: (none found in event stream)
- Taxonomy pinned: `1.0.0`

> **All thresholds below are proposals — PROPOSED — pending human sign-off.** Nothing in this report settles an acceptance bar.

## Gating summary

| Metric | Measured | Proposed threshold | Verdict |
|---|---|---|---|
| Suggestion precision (overall) | not computed (0/0 checked) | ≥ 75% | ⚠️ not computed (PROPOSED — pending human sign-off) |
| Coverage (tracks with ≥1 usable tag) | 0.0% (0/47) | ≥ 85% | ❌ fails proposed threshold (PROPOSED — pending human sign-off) |
| Batch completion rate | 100.0% (1/1) | = 100% | ✅ meets proposed threshold (PROPOSED — pending human sign-off) |
| Taxonomy conformance | not computed (0 tag refs checked) | = 100% | ⚠️ not computed (PROPOSED — pending human sign-off) |
| Safety (source protection / backup / undo) | FAIL | zero violations | ❌ fails proposed threshold (PROPOSED — pending human sign-off) |

## 1. Suggestion precision per category (primary metric)

*Reported with counts: the evaluation set is small (n=47), so a percentage resting on a handful of items must not be over-read.*

| Category | Suggested | Checked | Accepted | Rejected | Modified | Precision (acc/checked) |
|---|---|---|---|---|---|---|
| **overall** | 0 | 0 | 0 | 0 | 0 | **not computed** |

⚠️ **Ground truth missing** — no hand-check decisions were supplied, so precision is not computed and this report cannot pass. The external verifying agent's hand-check log is the ground truth (plan v0.1 §2).

## 2. Coverage

- Tracks with ≥1 usable tag: **0**
- Denominator: **47** (scan report (indexed tracks))
- Coverage: **0.0%** — ❌ fails proposed threshold (PROPOSED — pending human sign-off)

## 3. Correction burden

- Modifications per checked track: not computed
- Rejections per checked track: not computed
- App-side edits per track (cross-check from review outcomes): not computed

## 4. Batch completion (gating robustness metric)

- Batches observed: 1; completed without mid-run crash: 1 (rate 100.0%) — ✅ meets proposed threshold (PROPOSED — pending human sign-off)

## 5. Taxonomy conformance

- Tag references checked: 0
- Unknown tag ids: 0
- Genre depth violations (depth > 2): 0
- Conformance: not computed — ⚠️ not computed (PROPOSED — pending human sign-off)

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
| critical | architectural/cross-component problem | MUSI-7 engine code absent from all origin branches while the issue sits in_review; no suggestion events can be produced, blocking precision/coverage/burden ground truth | Lead Architect (reroute to Tagging Engine Engineer) |
| high | evaluation-data problem | Safety write path never exercised (no suggestions to apply), so backup/undo evidence does not exist yet; safety is unverified, not failed | Evaluation & Review Agent (re-run after MUSI-7/MUSI-8 merge) |
| info | evaluation-data problem | The fixed test set changed mid-phase: 47 converted FLAC files now sit alongside the 47 original .ncm containers (operator-directed step-0 conversion); baseline must target the FLAC files | Evaluation & Review Agent |

### Reproduction evidence


## 9. Limitations

- Sample size: the fixed evaluation set is 47 files; per-category precision may rest on very few items. Counts are reported alongside percentages for this reason.
- The library comes from one source/folder; its genre and era distribution may not represent future batches.
- Ground truth is a single external evaluator; reasons on rejections/modifications keep drift auditable.

## 10. Evidence artifacts

- Event stream files read:
  - `../eval-run/events.jsonl`
- Evaluator hand-check log (ground truth): see `--hand-check` input.
- Tagging-history log (the app's own §4 event stream) cross-checked in §7.
- Safety test notes: see `--safety-evidence` input and §6.

## 11. Run notes (baseline v0.1, 2026-11-17)

- The scan is a REAL run of the application layer (branch `agent/application-integration-engine/ad8d3c40c54f` @ `c3dc20b`, MUSI-8 in_review) against the read-only source library. It indexed 47 converted FLAC tracks, skipped 47 .ncm containers (`ncm_requires_conversion`, step-0 conversion per operator decision) and 140 non-audio files, and completed cleanly (batch completion 1/1 = 100%).
- **No suggestion events exist**: no provider was configured because the MUSI-7 engine code is absent from every origin branch (verified via `git log --all`), although MUSI-7 sits in `in_review`. Precision, coverage-vs-usable-tags, correction burden, and taxonomy conformance are therefore **not computable** this round, and this report FAILS its gating checks by design (exit code 2).
- Safety evidence (backup/write/undo records) could not be produced: without suggestions there is nothing to review/apply, so the write path was never exercised. Safety is UNVERIFIED, which also fails the report by design. The triggered-fault demonstration (`evalharness safety-demo`) proves the checks actively fail on a source write, a missing backup, and a failed undo.
- Once MUSI-7 merges and MUSI-8 is accepted, the intended flow is: convert (step 0, already done for the source set) → scan with the real provider → worksheet generation → external evaluator hand-check (ground truth) → apply/undo safety exercise → this harness re-run.
