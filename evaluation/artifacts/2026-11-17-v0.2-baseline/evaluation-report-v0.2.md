# Music Tagger — Evaluation Report

- Evaluation plan version: **v0.2**
- Dataset: frozen 47-track NCM remux set (/test-data/music-working/eval-input-ncm-remux); engine main 5354663 (MUSI-14 edc827d)
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
| high | evaluation-data problem | Runtime has no egress to musicbrainz.org: 16/16 network lookups failed with 'No route to host'; era recall is unmeasured, not zero-in-principle | Evaluation & Review Agent / runtime infrastructure |
| medium | taxonomy/specification problem | Album-level genre.k-pop is a false positive on the 3 film-score instances; taxonomy v1.0.0 has no soundtrack/film-score genre | Taxonomy Designer / Lead (post-acceptance v1.1) |
| info | evaluation-data problem | All five approved bars now pass: the four quality bars on the 47-track baseline, and safety on the operator-approved 2-track copy smoke (apply / backup / byte-exact undo) | Evaluation & Review Agent |
| info | tagging-engine defect | Offline degradation verified: batch completes with 47 logged abstentions, zero hangs, local suggestions unaffected | Tagging Engine Engineer |

### Reproduction evidence

- **Runtime has no egress to musicbrainz.org: 16/16 network lookups failed with 'No route to host'; era recall is unmeasured, not zero-in-principle**
  - Evidence: Network provider run: 16 unique (album, artist) pairs attempted, 47/47 tracks abstained, 0 era suggestions, 0 hangs, batch completed in 49.5s. Direct checks: curl to musicbrainz.org:443 -> 'No route to host'; DNS resolves but TCP is blocked. MUSI-14 delivery documents the same runtime firewall. This is an environment limitation, not a provider defect.
  - Reproduction: curl -sS --max-time 10 https://musicbrainz.org/ws/2/release-group/ → connect: No route to host
- **Album-level genre.k-pop is a false positive on the 3 film-score instances; taxonomy v1.0.0 has no soundtrack/film-score genre**
  - Evidence: Score Suite (2 instances) and Prologue (1) are orchestral film-score cues on a Korean soundtrack album; the provider suggests genre.k-pop from album evidence. The hand-check rejects all 3 (expected genre.orchestral). This is the recorded v1.1 taxonomy gap (ballad/soundtrack/film-score), deferred to post-acceptance by operator decision.
- **All five approved bars now pass: the four quality bars on the 47-track baseline, and safety on the operator-approved 2-track copy smoke (apply / backup / byte-exact undo)**
  - Evidence: Precision 93.6% (44/47) vs >=75%; coverage 93.6% (44/47) vs >=85%; batch completion 100% (1/1); taxonomy conformance 100% (47 tag refs). Safety: 2-track copy smoke through the real app write path — backup before write, undo byte-exact, source untouched; all three harness checks pass. Evidence: evaluation/artifacts/2026-11-17-safety-smoke/.
- **Offline degradation verified: batch completes with 47 logged abstentions, zero hangs, local suggestions unaffected**
  - Evidence: MUSI-14 provider with network down: per-pair memoization limited the run to 16 attempts, every track was skipped-and-logged, the scan/quality batch completed 1/1, and the 47 local genre suggestions were unaffected.

## 9. Limitations

- Sample size: the fixed evaluation set is 47 files; per-category precision may rest on very few items. Counts are reported alongside percentages for this reason.
- The library comes from one source/folder; its genre and era distribution may not represent future batches.
- Ground truth is a single external evaluator; reasons on rejections/modifications keep drift auditable.

## 10. Evidence artifacts

- Event stream files read:
  - `eval-run-v0.2/engine-events.jsonl`
- Evaluator hand-check log (ground truth): see `--hand-check` input.
- Tagging-history log (the app's own §4 event stream) cross-checked in §7.
- Safety test notes: see `--safety-evidence` input and §6.

## 11. Baseline environment — the one unmeasured metric

- **Engine build:** `origin/main` `5354663` (MUSI-14 merge of `edc827d`).
- **Frozen input:** `/test-data/music-working/eval-input-ncm-remux` (47 MP3s,
  title/artist/album/cover 47/47, genre/date 0/47).
- **Frozen track list:** `evaluation/fixtures/fixed-set-47-v1.json`
  (`content_sha256 181e18b4…`).
- **Pre-labels:** 14 works / 47 instances, plan v0.2 in force.
- **Network run id:** `v0.2-network` (0 suggestions, 47 abstentions).
- **Safety evidence:** `evaluation/artifacts/2026-11-17-safety-smoke/` — real app
  write path on 2 copies: 2 backups, 2 writes, 2 byte-exact undos; source hashes
  unchanged; all three harness safety checks pass.
- **Runtime egress:** **blocked**. `musicbrainz.org:443` resolves but has no
  route; 16/16 unique lookup pairs failed in 49.5s, 47/47 tracks abstained with
  logged `NetworkLookupError`, zero hangs. The local suggestions were
  unaffected, which is the intended offline degradation.

Consequence: **era recall is unmeasured in this run**, not zero because the
provider logic failed. The four approved acceptance bars do not depend on it;
expected-tag recall is report-only.

## 12. Approved-bar reading

| Approved bar | Measured | Verdict |
|---|---|---|
| Suggestion precision | 93.6% (44/47) | PASS (>=75%) |
| Coverage | 93.6% (44/47) | PASS (>=85%) |
| Batch completion | 100% (1/1) | PASS |
| Taxonomy conformance | 100% (94 refs) | PASS |
| Safety | 3/3 checks pass on a 2-track copy smoke | PASS (option A scope) |

## 13. Recall forecast if egress were available

The pre-labels expect 138 instance tags: 47 genre, 47 era, 44 origin.
Measured exact matches: 44 genre (93.6%), 0 era, 0 origin → overall 31.9%
(instance) / 30.0% (work). If the date provider resolved all 14 works, era
would add 47/47, lifting instance recall to **65.9% (91/138)** and work-level
to **65% (26/40)**. Origin stays 0 by the operator's Phase 2/3 deferral. A
networked re-run is required to confirm the era number; `Score Suite` may
still abstain even with network because its album is the separate score
release group, so 47/47 is a ceiling, not a guarantee.

## 14. Reproduce

```bash
# from the repo root on main, with the harness on PYTHONPATH
PYTHONPATH=src:evaluation python evaluation/tools/run_v0_2_baseline.py eval-run-v0.2
PYTHONPATH=evaluation python -m evalharness worksheet \
  --events eval-run-v0.2/engine-events.jsonl --out eval-run-v0.2/worksheet.jsonl
PYTHONPATH=evaluation python -m evalharness report \
  --events eval-run-v0.2/engine-events.jsonl \
  --hand-check eval-run-v0.2/hand-check.jsonl \
  --prelabels evaluation/fixtures/track-pre-label-worksheet-v0.2.csv \
  --scan-report eval-run-v0.2/scan-report.json \
  --batches eval-run-v0.2/batches.json \
  --taxonomy-dir taxonomy --out eval-run-v0.2/evaluation-report-v0.2.md
```

> Every threshold in this report is **operator-approved 2026-11-17** (values
> unchanged from the v0.1 proposals). Recall remains report-only.

