# v0.2 baseline acceptance (operator) — 2026-11-17

**Accepted:** the operator's reply "your recommendation is accepted" on MUSI-9
(comment `01a1e963-dcea-7704-b122-fc9f8e6bd098`, 2026-11-17T12:03:18Z) accepts
the recommendation attached to the v0.2 baseline report.

## What is accepted

- The **four approved quality bars** are accepted on the v0.2 baseline run
  (`origin/main` `5354663`, MUSI-14 `edc827d`):
  precision **93.6%** (44/47), coverage **93.6%** (44/47), batch completion
  **100%** (1/1), taxonomy conformance **100%** (47 refs).
- **Era recall is recorded as "unmeasured — runtime egress"** for this run,
  not as a measured zero and not as a provider defect. The run measured the
  offline degradation path: 16/16 MusicBrainz pairs failed with "No route to
  host", 47/47 abstentions, zero hangs.
- The 3 rejects (`Score Suite` ×2, `Prologue`) are accepted as the expected
  film-score false positives; the taxonomy v1.1 follow-up remains the agreed
  post-acceptance work.
- **One networked date check is required before final Phase-1 acceptance.**
  This is the only outstanding v0.2 evaluation precondition. It does not block
  the MUSI-8 review or the MUSI-10 integration pass.

## What is not accepted / still open

- **Safety is not satisfied** by this audit run: no apply / backup / undo batch
  was exercised. Safety remains pending the MUSI-8 write-path review and the
  MUSI-10 integration pass.
- The **era recall number itself** is not yet measured; the 65.9% instance /
  65% work forecast remains a forecast until the networked check runs.
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
- `egress-check.txt` — DNS/TCP/API evidence for the blocked network.
- `networked-date-check-offline-smoke.json` — tool smoke test in this runtime:
  `status: network_unavailable`, 16 pairs, 47 network errors, exit 3.
- Operator sign-off for thresholds: `../2026-11-17-operator-signoff.md`.
