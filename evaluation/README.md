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

```bash
# from the repo root, after `uv sync` (provides musigtagger + mutagen)
PYTHONPATH=evaluation:src uv run --no-project python -m evalharness report \
    --events path/to/events.jsonl \
    --hand-check path/to/handcheck.jsonl \
    --prelabels evaluation/fixtures/track-pre-label-worksheet-v0.2.csv \
    --safety-evidence path/to/safety.jsonl \
    --batches path/to/batches.json \
    --scan-report path/to/scan-report.json \
    --taxonomy-dir taxonomy --taxonomy-version 1.0.0 \
    --source-root /test-data/music-working/eval-input-ncm-remux \
    --out evaluation/reports/baseline-v0.2.md
```

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

All thresholds in every generated report are **proposals pending human
sign-off** (operator decision, MUSI-4 thread).
