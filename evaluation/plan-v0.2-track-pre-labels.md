# Evaluation Plan v0.2 — track-level pre-labels (IN FORCE)

**Status: IN FORCE — approved 2026-11-17T11:09:46Z.**
Thresholds approved **as-is** 2026-11-17 (see `artifacts/2026-11-17-operator-signoff.md`); the acceptance bar values are unchanged. Recall remains report-only.
Operator approval recorded on MUSI-9 (comment `01a1e932-dbda-7ebc-9366-d867650d4007`):
"approve, and label per work with per-instance propagation." The leader recorded
the plan in force at 11:11:39Z (comment `01a1e934-9514-7c82-87be-ab3a70bbc5a0`).
This document supersedes the 2026-11-17 proposal; git history keeps the
proposal text.

- Author/owner: Evaluation & Review Agent (MUSI-9)
- Applies to: Evaluation Plan v0.1 §2 (ground truth) and §4 (evidence artifacts)
- Frozen track list: `evaluation/fixtures/fixed-set-47-v1.json`, content
  `181e18b469de4b2ef8e3d8c9b5903b81c44ed5f0820074a40ee4a1eb916988c3`
- Frozen evaluation input: `/test-data/music-working/eval-input-ncm-remux`
  (47 MP3s, title/artist/album/cover preserved, no genre/date)
- Per-work labels: `evaluation/fixtures/prelabels-v0.2-works.json`
- Per-instance worksheet: `evaluation/fixtures/track-pre-label-worksheet-v0.2.csv`
- Validation record: `evaluation/fixtures/prelabels-v0.2-validation.json`

## 1. What the amendment does

Plan v0.1 defines ground truth as the evaluator's accept / reject / modify
decisions **per suggestion**. That measures precision but cannot see a track
the engine never suggested a tag for. In the first pass, 5 suggestions covered
47 tracks; the other 42 were invisible to precision.

v0.2 adds a **track-level pre-label** layer:

1. The evaluator records an expected tag set per **work** (14 works), before
   consulting the run's per-track suggestion log, and propagates it to every
   instance (47) by default.
2. The run still produces suggestions; the evaluator still makes
   accept / reject / modify decisions per suggestion. Those decisions remain
   the ground truth for precision and correction burden.
3. The harness additionally computes expected-tag recall and missed-tag counts
   by joining pre-labels and suggestions on `track_id` / `canonical_path`.

The amendment is additive: no threshold is relaxed, no decision is redefined,
and no taxonomy tag is invented.

## 2. Shape approved (per work, per-instance propagation)

- 47 track instances, **14 distinct works** (corrects the earlier "35 works"
  figure; 35 counted distinct titles including variant suffixes).
- 7 works have 5 instances (2 album editions + 3 variants), 5 works have 2
  instances (one per edition), 2 works are deluxe-only.
- Labels are authored once per work and propagated to instances.
  Instance-level override is allowed only for a version-specific facet
  (e.g. `activity.sing-along`); none is asserted in this pass.
- Recall is reported per instance and per work, so the 7 five-instance works
  cannot dominate the headline.

## 3. Label schema (in force)

Per-work record (`prelabels-v0.2-works.json`):

| Field | Meaning |
|---|---|
| `work_key`, `title`, `primary_artist`, `album`, `album_editions` | identity (frozen manifest keys) |
| `instance_count`, `instance_track_ids` | propagation targets |
| `expected.genre_primary` | exactly one taxonomy genre id, depth ≤ 2 |
| `expected.genre_secondary` | 0–2 co-primary ids; not used as parent fallback |
| `expected.era` | 0–1 era id |
| `expected.release_year` | audit value; the tag is the decade |
| `expected.origin` | 0–2 origin ids; empty when no defensible tradition |
| `expected.mood`, `expected.activity` | optional; Phase-1-unavailable facets are left empty |
| `label_confidence` | high / medium / low |
| `release_year_confidence` | audit value for the year |
| `evidence_basis` | metadata / listening / both / external-knowledge |
| `release_date_evidence`, `sources`, `notes` | audit trail |

Per-instance worksheet columns add: `label_scope`, `derived_from_work`,
`blind_status`, `audit_note`. `personal.*` is never pre-labeled (user-owned).

## 4. Labels recorded (2026-11-17)

14 works labelled, 47 instances propagated, validation clean (0 issues):

| Expected | Instances |
|---|---|
| `genre.k-pop` primary | 44 (12 works) |
| `genre.orchestral` primary | 3 (2 works: Score Suite, Prologue) |
| `era.2020s` | 47 (all works; release years 2025×12, 2024×1, 2022×1) |
| `origin.east-asia` | 44 (12 K-pop works) |
| origin empty | 3 (2 orchestral score cues — album-level Korea hint would be a false positive) |

- Genre secondary, mood, activity: intentionally empty in this pass. No
  `genre.ballad`, `genre.soundtrack`, or film-score tag exists in taxonomy
  v1.0.0; ballad/score works map to the closest valid tag and the gap is
  recorded, not redefined.
- The 5 "Soda Pop" instances are `disclosed-v0.1` (their v0.1 suggestion was
  seen). All other instances are `blind`.
- **Bias disclosure:** the leader disclosed the aggregate post-fix result
  (55/57 `genre.k-pop`) before labelling. It is aggregate, not per-track;
  labels come from NCM metadata + external release knowledge. This is recorded
  in every row's `audit_note`.
- **Source limitation:** live page fetches failed in this runtime
  (`web_fetch` errors); release years rely on search-result titles plus known
  release facts. MUSI-14's MusicBrainz lookup is the independent cross-check;
  any mismatch is a finding for the baseline report.

## 5. Metrics added (report-only; no new gate)

| Metric | Definition |
|---|---|
| Expected-tag recall | expected tags matched by an accepted/modified suggestion or applied tag ÷ expected tags |
| Missed tags per category | expected tags with no matching suggestion |
| Tracks with expected tags but zero suggestions | count and list |
| Parent-level match | expected specific tag matched only by its parent suggestion |
| Exact match | expected tag equals suggested tag |

Precision, coverage, correction burden, batch completion, taxonomy conformance,
and safety keep their v0.1 definitions. Recall is **not** a gating threshold
until the operator sets one.

Harness support is implemented: `evalharness report --prelabels <worksheet>`
reads the per-instance worksheet, computes instance-level and work-level
recall, and renders report section 5b; 28 harness tests pass. A smoke test on
the pre-fix event stream (not a baseline) gives 3.6% instance recall / 2.5%
work recall with 42 no-suggestion tracks — the known pre-fix state, recorded
only to prove the metric runs.

## 6. Baseline sequencing (binding)

The full v0.2 baseline **was held** until the network release-date provider
(MUSI-14) landed on `main`; it has now been executed on `main` `5354663`. The
operator approved pulling a minimal MusicBrainz date lookup into Phase 1
(2026-11-17T11:09:46Z); era was structurally 0 under local-only sources, and
hand-checking era twice would be wasted work. The local-only re-run queued
earlier is **superseded**; the formal numbers come from one clean baseline
with the date provider in the loop.

The re-run uses the frozen input + frozen 47-track manifest + these pre-labels,
with the hand-check worksheet generated from the real event stream.

A **post-fix audit run** predates v0.2 and is preserved at
`evaluation/artifacts/2026-11-17-post-fix/` (47/47 `genre.k-pop`, 44 accept /
3 reject on orchestral cues, 93.6% instance precision/coverage, 85.7%
work-level). It has no pre-labels/recall and no date provider; it is evidence,
not the v0.2 baseline.

**Baseline executed 2026-11-17** on `main` `5354663` (MUSI-14 merge of
`edc827d`). Result: precision 93.6% (44/47), coverage 93.6% (44/47), batch
completion 100%, conformance 100% — **all four approved quality bars pass**.
Safety remains unverified (pending MUSI-8). Era recall is **unmeasured**: this
runtime has no route to `musicbrainz.org`, so 16/16 lookup pairs failed and
47/47 tracks abstained with logged `NetworkLookupError` (zero hangs). Overall
report-only recall is 31.9% instance / 30.0% work-level; the date-resolved
forecast is 65.9% / 65% if all 14 works resolve. Full evidence:
`artifacts/2026-11-17-v0.2-baseline/RUN.md`.

## 7. Decisions resolved (operator, 2026-11-17)

The operator answered on MUSI-9 (`01a1e957-d274-7627-a3ae-33d40e231a98`); the
full record is `artifacts/2026-11-17-operator-signoff.md`.

1. **Acceptance thresholds — approved as-is, values unchanged.** Precision
   ≥75%, coverage ≥85%, batch completion 100%, taxonomy conformance 100%,
   safety zero writes / zero corruption / undo verified. Recall remains
   report-only; no recall threshold was approved.
2. **v0.2 reporting details — defaults accepted ("as it is").** Genre
   mandatory; era/origin where defensible; mood/activity optional; personal
   excluded. Parent-only matches reported separately, never exact. No external
   auditor named: the evaluator self-audits a sample and records the
   disclosure. Date conflicts: earliest official release year wins; a
   MusicBrainz mismatch is reported, not silently accepted.
3. **Taxonomy gaps — option (a).** Keep taxonomy v1.0.0 for this baseline;
   ballad and score works stay mapped to `genre.k-pop` / `genre.orchestral`
   with the gap recorded. A separate taxonomy issue (ballad / soundtrack /
   film-score) is a **post-acceptance follow-up**, not opened now.
4. **Origin — option (a).** Accept origin as a Phase 2/3 gap for this
   baseline; no Phase-1 origin/language provider. Expected-tag recall will
   understate the engine on origin; known and accepted, not a defect and not a
   gate.

There are no open evaluation-side questions blocking the baseline.

## 8. Change log

- 2026-11-17 10:19Z — v0.2 proposal drafted (MUSI-9), blank worksheet.
- 2026-11-17 11:09:46Z — operator approves v0.2 and the Phase-1 date lookup;
  label shape = per work, per-instance propagation.
- 2026-11-17 11:11:39Z — leader records v0.2 in force; baseline sequencing set
  after MUSI-14.
- 2026-11-17 11:18Z — 14 works labelled, 47 instances propagated, validation
  clean; plan frozen in force. Baseline not run.
- 2026-11-17 11:30Z — recall harness implemented (`--prelabels`, report 5b)
  and smoke-tested; 28 harness tests pass. No baseline run.
- 2026-11-17 11:51Z — operator sign-off: thresholds approved as-is, v0.2
  defaults accepted, taxonomy option (a) deferred post-acceptance, origin
  accepted as a Phase 2/3 gap. No baseline run.
- 2026-11-17 12:00Z — v0.2 baseline executed on `main` 5354663; four approved
  quality bars pass, safety unverified (MUSI-8), era recall unmeasured
  (runtime egress). See `artifacts/2026-11-17-v0.2-baseline/RUN.md`.

## 9. What was deliberately not done

- No threshold changed; no taxonomy tag created.
- No local-only baseline run (superseded by sequencing).
- No instance-level overrides asserted.
- No personal tags pre-labeled.
