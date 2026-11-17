# Music Tagger — Evaluation Harness (external)

The evaluation harness for the Music Tagger MVP, owned by the Evaluation &
Review Agent. It implements **Evaluation Plan v0.1** (MUSI-4 thread).

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
    --safety-evidence path/to/safety.jsonl \
    --batches path/to/batches.json \
    --scan-report path/to/scan-report.json \
    --taxonomy-dir taxonomy --taxonomy-version 1.0.0 \
    --source-root /test-data/music-source \
    --out evaluation/reports/baseline-v0.1.md
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

## Per-work vs per-instance reporting

The frozen set is 14 distinct works across 47 instances, so instance-level
percentages can be dominated by the seven five-instance works. The roll-up tool
reports both views from the same event stream and hand-check log:

```bash
PYTHONPATH=evaluation:src python evaluation/tools/per_work_rollup.py \
    --manifest evaluation/fixtures/fixed-set-47-v1.json \
    --events eval-run/engine-events.jsonl \
    --hand-check eval-run/hand-check.jsonl \
    --out-json eval-run/per-work-rollup.json \
    --out-md eval-run/per-work-rollup.md
```

`evaluation/tools/frozen_input_probe.py` is the read-only precondition audit for
the frozen input: manifest hash, per-file SHA-256/size, and the local
year/date evidence (embedded tags, filename, title, album) behind the era
coverage statement.

## Inputs

| Input | Format | Required | Producer |
|---|---|---|---|
| `--events` | JSONL event stream (CONTRACTS.md §4) | yes | engine runner / application |
| `--hand-check` | JSONL or CSV hand-check log | for precision/coverage/burden | external verifying agent |
| `--safety-evidence` | JSONL backup/write/undo records | for safety checks | evaluation run of the app's write path |
| `--batches` | JSON batch/run records | for batch completion | engine runner / application |
| `--scan-report` | JSON scan summary | for coverage denominator | application scan |

All thresholds in every generated report are **proposals pending human
sign-off** (operator decision, MUSI-4 thread).
