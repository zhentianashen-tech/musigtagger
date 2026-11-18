# Music Tagger — Evaluation Harness (external)

The evaluation harness for the Music Tagger MVP, owned by the Evaluation &
Review Agent. It implements **Evaluation Plan v0.1** plus the operator-approved
**v0.2 track-level pre-label amendment** (`plan-v0.2-track-pre-labels.md`).

**Boundary (CONTRACTS.md §4):** the harness is *external* — it consumes the
suggestion / review-outcome event stream and safety evidence the engine-runner
and application emit. It is never imported by, and never modifies, engine or
application code. Nothing in this directory is on the engine's import path.

## Layout

```
evaluation/
  evalharness/        the harness package (stdlib only; reads musigtagger.contracts
                      solely through the contract-sanctioned TaxonomyLoader)
  fixtures/           sample event logs, incl. triggered safety-fault scenarios
  tests/              standard-library test suite (unittest)
  reports/            generated baseline reports (gitignored artifacts land here)
```

## Usage

### Reproduce the checked-in baseline

The default Phase-1 baseline is
`artifacts/2026-11-18-v0.3-baseline/` (era recall **47/47**, regenerated on
merged `main` after the MUSI-14 era-lookup fix). The v0.2 set is superseded
(kept for audit — see its `SUPERSEDED.md`). Score the checked-in artifacts
(no network needed; exit `0` = all gating checks pass, era recall 47/47):

```bash
# from the repo root, after `uv sync` (provides musigtagger + mutagen)
PYTHONPATH=evaluation:src uv run --no-project python -m evalharness report \
    --events evaluation/artifacts/2026-11-18-v0.3-baseline/engine-events.jsonl \
    --hand-check evaluation/artifacts/2026-11-18-v0.3-baseline/hand-check.jsonl \
    --prelabels evaluation/fixtures/track-pre-label-worksheet-v0.2.csv \
    --safety-evidence evaluation/artifacts/2026-11-17-safety-smoke/safety-evidence.jsonl \
    --batches evaluation/artifacts/2026-11-18-v0.3-baseline/batches.json \
    --scan-report evaluation/artifacts/2026-11-18-v0.3-baseline/scan-report.json \
    --taxonomy-dir taxonomy --taxonomy-version 1.0.0 \
    --source-root /test-data/music-source \
    --out evaluation/reports/baseline-v0.3-reproduced.md
```

Expected numbers: precision 93.6% (44/47), coverage 93.6% (44/47), batch
100% (1/1), taxonomy conformance 100% (94 refs), safety 3/3, era recall
47/47 (100%).

### Regenerate the baseline from a live engine run

To *re-cut* the baseline (regenerates the suggestion events over the frozen
47-track remux input with the local + MusicBrainz network providers — requires
MusicBrainz egress), then re-run the report command above against the fresh
artifacts:

```bash
PYTHONPATH=src:evaluation uv run --no-project python evaluation/tools/run_v0_2_network_baseline.py \
    eval-run-v0.3 --taxonomy taxonomy --run-id-prefix v0.3 --max-attempts 5
```

If the networked pass does not reproduce 47/47 era recall (e.g. MusicBrainz
transient 503 storms), retry before checking in a degraded baseline.

Exit codes: `0` — every gating check passed; `2` — at least one gating check
failed (including "ground truth missing, metrics not computable"). The report
therefore *fails actively* on safety faults and missing evidence.

Generate the worksheet the external verifying agent (computer use, outside this
project) fills in — their accept/reject/modify decisions are the ground truth:

```bash
PYTHONPATH=evaluation:src uv run --no-project python -m evalharness worksheet \
    --events path/to/events.jsonl --out handcheck-worksheet.jsonl
```

Demonstrate that the safety checks actively fail on triggered faults:

```bash
PYTHONPATH=evaluation:src uv run --no-project python -m evalharness safety-demo
```

## Inputs

| Input | Format | Required | Producer |
|---|---|---|---|
| `--events` | JSONL event stream (CONTRACTS.md §4) | yes | engine runner / application |
| `--hand-check` | JSONL or CSV hand-check log | for precision/coverage/burden | external verifying agent |
| `--prelabels` | v0.2 per-instance pre-label worksheet (CSV) | for expected-tag recall (report-only) | Evaluation & Review Agent |
| `--safety-evidence` | JSONL backup/write/undo records | for safety checks | evaluation run of the app's write path |
| `--batches` | JSON batch/run records | for batch completion | engine runner / application |
| `--scan-report` | JSON scan summary | for coverage denominator | application scan |

All thresholds in every generated report carry the **operator sign-off**
(approved unchanged 2026-11-17; see
`artifacts/2026-11-17-operator-signoff.md`). Expected-tag recall remains
report-only until a separate threshold is approved.
