# Plan v0.2 proposal — track-level pre-labels for suggestion recall

**Status: PROPOSAL — not in force.** Evaluation Plan v0.1 remains authoritative.
This amendment requires the operator's sign-off. No pre-labels have been
recorded; the attached worksheet is blank on purpose.

- Author: Evaluation & Review Agent (MUSI-9)
- Date: 2026-11-17
- Applies to: Evaluation Plan v0.1 §2 (ground truth) and §4 (evidence artifacts)
- Companion files:
  - `evaluation/fixtures/fixed-set-47-v1.json` / `.csv` — frozen 47-track list
  - `evaluation/fixtures/track-pre-label-worksheet-v0.2-proposal.csv` — blank worksheet

## 1. Why this amendment is proposed

Plan v0.1 defines ground truth as the evaluator's accept / reject / modify
decisions **per suggestion**. That works for precision, but it cannot see a
track the engine never suggested a tag for: there is no row to decide on.

The first real pass exposed the consequence. The engine emitted 5 suggestions
across 47 tracks (all a path-word match on "Soda Pop"). The hand-check could
only decide on those 5. The other 42 tracks were invisible to precision — they
showed up only as the coverage denominator. There was no per-category way to
say **which expected tags the engine missed**, and no way to distinguish "the
engine was silent because this track has no defensible tags" from "the engine
missed `genre.k-pop` and `era.2020s` on a track that clearly has both".

Track-level pre-labels close that gap without changing the meaning of a
suggestion decision.

## 2. What changes

Add a **pre-label** step before each evaluation run:

1. The evaluator records an expected tag set for every track in the frozen
   47-track list (schema in §3), from the NCM metadata, filenames, and
   listening — **before opening that run's suggestion log**.
2. The run then produces suggestions as today. The evaluator still makes
   accept / reject / modify decisions per suggestion; those remain the ground
   truth for precision and correction burden.
3. The harness additionally computes **expected-tag recall** and **missed-tag
   counts** by joining pre-labels and suggestions on `track_id` /
   `canonical_path`.

The amendment is additive. It does not relax a threshold, redefine a decision,
or replace the per-suggestion log.

## 3. Pre-label schema (one row per track)

| Field | Values | Notes |
|---|---|---|
| `row`, `track_id`, `canonical_path` | frozen manifest | join keys; never edited |
| `title`, `artist`, `album`, `album_edition`, `variant` | frozen manifest | copy, not re-typed |
| `blind_status` | `blind` \| `disclosed-v0.1` | `disclosed-v0.1` for the 5 "Soda Pop" instances already seen |
| `expected_genre_primary` | one taxonomy genre id | most specific defensible genre; depth 1–2 |
| `expected_genre_secondary` | 0–2 taxonomy genre ids | only if genuinely co-primary |
| `expected_era` | 0–1 era id | only when the release era is known; NCM has no date, so this will often be empty or inferred from album knowledge |
| `expected_origin` | 0–2 origin ids or `origin.lang-<iso639-3>` | language/origin only when defensible |
| `expected_mood` | 0–4 mood ids | optional; Phase 1 has no mood source |
| `expected_activity` | 0–3 activity ids | optional; e.g. `activity.sing-along` for sing-along versions |
| `label_confidence` | `high` \| `medium` \| `low` | per row; low/medium requires a note |
| `evidence_basis` | `metadata` \| `listening` \| `both` \| `external-knowledge` | what the label rests on |
| `evaluator`, `labeled_at`, `notes` | free text | notes are mandatory for low confidence and for parent-only genre choices |

Rules:

- Every tag id must exist in the pinned taxonomy (v1.0.0) and genre depth must
  be ≤ 2. `personal.*` is not pre-labeled — it is user-owned by design.
- Genre is recorded at the most specific defensible level. If the only honest
  answer is the parent (`genre.pop` because `genre.k-pop` is uncertain), the
  row's `notes` must say `parent-only` and recall will count it at parent
  level, not as an exact match.
- Variants inherit the work's genre/era/origin unless listening shows
  otherwise; `activity` may differ (e.g. sing-along versions).
- Labels are recorded once per frozen manifest version and reused until the
  track list or taxonomy version changes.

## 4. Metrics added (report-only; no new gate)

| Metric | Definition | Why |
|---|---|---|
| Expected-tag recall | expected tags matched by an accepted/modified suggestion or applied tag ÷ expected tags | measures the tags the engine misses, not only the ones it proposes |
| Missed tags per category | expected tags with no matching suggestion | makes false negatives visible per facet |
| Tracks with expected tags but zero suggestions | count and list | names the 42-track blind spot directly |
| Parent-level match | expected specific tag matched only by its parent suggestion | separates "right family, under-specific" from "wrong" |
| Exact match | expected tag equals suggested tag | the strict view |

Precision, coverage, correction burden, batch completion, taxonomy conformance,
and safety keep their v0.1 definitions. Recall is reported with counts and is
**not** a gating threshold until the operator sets one.

## 5. Labelling protocol and bias controls

- **Order matters.** Label before opening the run's suggestion event log. For
  the first v0.2 pass the 5 "Soda Pop" instances are already seen; they are
  marked `disclosed-v0.1` and the note records that the suggestion was
  `genre.pop`. This is the only disclosed subset.
- **One evaluator, reasons on uncertainty.** The evaluator records
  `label_confidence` and a note for every low/medium label, so drift is
  auditable. A second reviewer can audit a sample later.
- **Set shape is recorded honestly.** The frozen set is 47 track instances but
  only 14 distinct works: 7 works have 5 instances (2 album editions + 3
  variants), 5 works have 2 instances (one per edition), 2 works are
  deluxe-only. Recall is reported both per track instance and per work, so the
  7 heavily repeated works cannot dominate the headline.
- **Known ambiguity.** The album is a K-pop soundtrack; `genre.k-pop` vs
  `genre.pop`, and score cues vs `genre.orchestral`, are judgement calls. The
  notes field and parent-level reporting keep them visible.

## 6. Open questions for the operator

1. **Approve the amendment?** If yes, this becomes plan v0.2 and the worksheet
   gets filled before the next evaluation run.
2. **Label all 47 track instances, or 14 works?** The proposed default is 47
   rows (direct join, variant-specific activity); work-level reporting is
   derived.
3. **Which facets are mandatory?** Proposed: genre mandatory, era/origin
   expected where defensible, mood/activity optional, personal excluded.
4. **Should a parent-only genre match count as recall?** Proposed: reported
   separately as parent-level, never silently counted as exact.
5. **Who audits a sample?** The leader or the operator can re-check 5–10 rows
   before the first scored run.

## 7. Harness impact (if approved)

- New reader for the pre-label worksheet (CSV/JSONL) and a validator against
  the pinned taxonomy.
- New recall/missed-tag computation joined on `track_id` / `canonical_path`.
- Report section with expected-tag recall per category, parent-level matches,
  and the no-suggestion track list.
- No change to `HandCheckDecision`, the accept/reject/modify semantics, the
  proposed thresholds, or the safety checks.

## 8. What was deliberately not done

- No pre-labels were recorded in this run.
- No threshold was changed.
- No taxonomy tag was invented for this set.
- The earlier "35 works" figure is corrected in the frozen manifest: the set
  has **14 distinct works** across 47 instances (see §5).
