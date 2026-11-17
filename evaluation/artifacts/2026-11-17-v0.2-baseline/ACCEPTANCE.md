# v0.2 baseline acceptance (operator) — 2026-11-17

**Update 2026-11-17T12:13Z:** option A executed — the safety smoke passed, so
all five approved bars now pass.

**Update 2026-11-17T12:37Z:** the networked date check has now run with the
project UA, cache reuse, and ≤1 req/s pacing. Measured **era recall 0/47
(0.0%)**: all 16 unique album+artist pairs returned HTTP 200 with zero matching
release groups. This is a **critical MUSI-14 provider query defect**, not an
unmeasured value: the provider queries release groups by the embedded album
title **plus the track artist**, while the library is a various-artists
soundtrack whose release group is credited to the cast; the deluxe album
suffix and composite artist strings also defeat the query. Album-only queries
return the correct 2025-06-20 release group. Final Phase-1 acceptance should
not claim era coverage until the provider is fixed and the date path re-run.

**Accepted:** the operator's reply "your recommendation is accepted" on MUSI-9
(comment `01a1e963-dcea-7704-b122-fc9f8e6bd098`, 2026-11-17T12:03:18Z) accepts
the recommendation attached to the v0.2 baseline report.

## What is accepted

- The **four approved quality bars** are accepted on the v0.2 baseline run
  (`origin/main` `5354663`, MUSI-14 `edc827d`):
  precision **93.6%** (44/47), coverage **93.6%** (44/47), batch completion
  **100%** (1/1), taxonomy conformance **100%** (47 refs).
- **Era recall is now measured at 0/47 (0.0%)** on the live run; it is a
  provider query-construction defect, not a denominator or test-data issue.
  The earlier offline run's "unmeasured — runtime egress" label is superseded.
  The four quality bars and the option-A safety bar remain accepted; the
  operator's "correct release date is required" condition is **not met** until
  the provider is fixed.
- The 3 rejects (`Score Suite` ×2, `Prologue`) are accepted as the expected
  film-score false positives; the taxonomy v1.1 follow-up remains the agreed
  post-acceptance work.
- **Safety is accepted on the option-A scope** (operator: "go with A"): a
  2-track copy-based smoke through the real application write path — backup
  before write, tags written, undo byte-exact, source untouched — passes all
  three harness safety checks. Evidence: `../2026-11-17-safety-smoke/`.
- The **networked date check has run** (result above). The remaining
  precondition is the provider fix plus a re-run of the date path, not another
  manual check.

## What is not accepted / still open

- Safety is satisfied for the option-A scope only (2 tracks, MP3/ID3); the
  leader's MUSI-8 review and the MUSI-10 integration pass still cover full app
  behaviour. There is no remaining safety blocker for Phase-1 acceptance at the
  agreed scope.
- **Era coverage is not met**: measured 0/47 because the provider's
  album+track-artist release-group query matches none of the 16 pairs. A
  bounded MUSI-14 fix (album-only/recording-level query, edition-suffix
  stripping) and cache invalidation/versioning are required before the date
  path can be accepted.
- Final Phase-1 acceptance (MUSI-7/8/12/13/14 + MUSI-9) remains the operator's
  later decision, on the leader's recommendation after MUSI-10.

## Networked date check — runbook (one command)

Run on any machine with egress to `musicbrainz.org`, from a **`main` checkout**
(which carries the MUSI-14 provider). The check tool lives on the evaluation
branch, so copy just that file into the `main` checkout first:

```bash
git fetch origin
git checkout main
git checkout origin/agent/evaluation-review-agent/956ae907db4b -- \
  evaluation/tools/networked_date_check.py
PYTHONPATH=src python evaluation/tools/networked_date_check.py \
  --input /test-data/music-working/eval-input-ncm-remux \
  --taxonomy taxonomy \
  --manifest evaluation/fixtures/fixed-set-47-v1.json \
  --prelabels evaluation/fixtures/prelabels-v0.2-works.json \
  --out networked-date-check.json
```

(If the evaluation branch has already been merged to `main`, the checkout step
is a no-op. The manifest/prelabel fixtures also live on that branch; copy them
with the tool if the merge has not happened.)

- It runs the real `MusicBrainzReleaseYearProvider` over the frozen set:
  16 unique `(album, artist)` pairs, ~16 paced queries, cached in the local
  database so a re-run is free.
- Exit `0`: every instance resolved to the expected era (`era.2020s`); year
  differences within the same decade are reported, not fatal.
- Exit `2`: an era mismatch, or unresolved works (unless `--allow-abstain`).
- Exit `3`: network unavailable — re-run on a networked machine.
- The JSON report lists per-work resolved/unresolved, years, expected years,
  and flagged suspicious matches. Attach it to MUSI-9 for the record.

The tool was smoke-tested in the evaluation runtime and fails closed with
exit `3` / `status: network_unavailable`, 16 pairs, 47 network errors — the
expected offline behavior, proving it cannot pass without egress.

## Evidence

- `RUN.md` — baseline run, measures, environment.
- `evaluation-report-v0.2.md` — harness report with approved thresholds.
- `hand-check.jsonl`, `worksheet.jsonl`, `engine-events.jsonl` — decisions and
  real event stream.
- `egress-check.txt` — DNS/TCP/API evidence for the earlier blocked network.
- `network-live/` — live-network report, events, worksheet, hand-check, and the
  two-pass cache/request/retry ledger; measured era recall 0/47.
- `../2026-11-17-safety-smoke/` — option-A safety evidence: safety-evidence
  JSONL, app event stream, smoke report, RUN.md.
- `networked-date-check-offline-smoke.json` — tool smoke test in this runtime:
  `status: network_unavailable`, 16 pairs, 47 network errors, exit 3.
- Operator sign-off for thresholds: `../2026-11-17-operator-signoff.md`.
