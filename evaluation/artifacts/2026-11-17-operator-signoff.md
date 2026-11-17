# Operator sign-off — thresholds and v0.2 scope (2026-11-17)

Recorded by the Evaluation & Review Agent from the operator's reply on MUSI-9:
comment `01a1e957-d274-7627-a3ae-33d40e231a98`, 2026-11-17T11:51Z.

## Operator answers (verbatim)

1. "approve as it is"
2. "as it is"
3. "go with option a"
4. "(a) accept origin as a Phase 2/3 gap for this baseline"
5. *(blank)*

## What was approved

### 1. Acceptance thresholds — approved as-is, values unchanged

| Threshold | Approved value |
|---|---|
| Suggestion precision (overall; per-category reported with counts) | **≥ 75%** |
| Coverage (tracks with ≥ 1 usable tag) | **≥ 85%** |
| Batch completion (no mid-batch crash/abort) | **100%** |
| Taxonomy conformance (valid ids, genre depth ≤ 2) | **100%** |
| Safety: writes under the protected source root | **0** |
| Safety: corruption incidents on working copies | **0** |
| Safety: undo restores prior state | **100% of sampled cases** |

No number changed at approval. Expected-tag recall (plan v0.2) remains
**report-only** — no recall threshold was approved.

### 2. v0.2 reporting details — defaults accepted ("as it is")

- Mandatory facets: genre mandatory; era/origin where defensible; mood/activity
  optional; personal excluded.
- Parent-only genre matches are reported separately as parent-level, never as
  exact matches.
- Audit: no external auditor named; the evaluator self-audits a sample and
  records the disclosure.
- Date conflicts: earliest official release year wins; a MusicBrainz mismatch
  is reported, not silently accepted. This also matches the operator's
  MUSI-14 guidance at 11:51Z: where provenance cannot resolve the discrepancy,
  leave the choice to the user at review/evaluation and keep the flag in the
  evidence.

### 3. Taxonomy gaps — option (a)

Keep taxonomy **v1.0.0** for this baseline. Ballad and film-score works stay
mapped to `genre.k-pop` / `genre.orchestral` with the gap recorded. A separate
taxonomy issue (ballad / soundtrack / film-score) is a **post-acceptance**
follow-up and is not opened now.

### 4. Origin scope — option (a)

Accept origin as a **Phase 2/3 gap** for this baseline. No origin/language
provider is added in Phase 1. Expected-tag recall will therefore understate
the engine on the origin facet; that is a known, accepted limitation, not a
defect and not a gating metric.

### 5. Blank item

There was no fifth item in the evaluator's list. The blank line is treated as
"no further answer"; nothing is missing. The only sub-question that could have
been meant (who audits the label sample) is covered by item 2: self-audit with
disclosure.

## Effect on the harness and plan

- `evalharness/thresholds.py`: `STATUS_LABEL` is now
  `APPROVED — operator sign-off 2026-11-17`; `PLAN_VERSION` is `0.2`; values
  unchanged.
- Generated reports now say "operator-approved" instead of "proposed".
- `plan-v0.2-track-pre-labels.md`: the open-questions section is resolved;
  threshold sign-off and the two "option a" decisions are recorded.
- **The baseline is still held** on MUSI-14 (network release-date provider)
  landing on `main`; this sign-off does not unblock that dependency.

## What still needs the operator

Nothing on MUSI-9 right now. The next operator-facing decision is Phase-1
acceptance (MUSI-7/8/12/13 + the v0.2 baseline), presented later with a
recommendation.
