# Post-fix baseline run — 2026-11-17

Re-run of the frozen-input evaluation baseline after the provider fix merged to
`main`. This is an **audit run**: no review application / write batch was
involved, so safety remains unverified and the report fails that gating check by
design.

## Engine state

- `origin/main` = `ea40353` ("MUSI-7: merge provider artist/album signals and
  date-coverage tests into main"), which carries `0a6e90a` (provider fix) and
  `6a1c09e` (embedded-date-to-era tests).
- Post-merge suite on `ea40353`: **118 tests OK, 1 skipped (pre-existing)**
  ```
  PYTHONPATH=src uv run --no-project --offline python -m unittest discover -s tests
  ```
- Taxonomy pinned: `1.0.0` (unchanged).

## Frozen input

- Input root: `/test-data/music-working/eval-input-ncm-remux` (read-only use;
  no writes).
- Frozen track list: `evaluation/fixtures/fixed-set-47-v1.json`
  (`content_sha256 181e18b469de4b2ef8e3d8c9b5903b81c44ed5f0820074a40ee4a1eb916988c3`).
- Precondition probe: `local-date-audit.json` — 47/47 files present, 0 SHA/size
  mismatches, manifest hash MATCH, `verification: PASS`.

## Commands

Engine run (from the `main` checkout, with this harness on `PYTHONPATH`):

```
PYTHONPATH=src:../eval-harness/evaluation uv run --offline python \
  ../eval-harness/evaluation/tools/run_engine_on_dir.py \
  ../eval-run-remux-post-fix \
  /test-data/music-working/eval-input-ncm-remux \
  "$PWD/taxonomy"
```

Harness report:

```
PYTHONPATH=evaluation:../musigtagger/src uv run --project ../musigtagger python \
  -m evalharness report \
  --events ../eval-run-remux-post-fix/engine-events.jsonl \
  --hand-check ../eval-run-remux-post-fix/hand-check.jsonl \
  --batches ../eval-run-remux-post-fix/batches.json \
  --scan-report ../eval-run-remux-post-fix/scan-report.json \
  --taxonomy-dir ../musigtagger/taxonomy --taxonomy-version 1.0.0 \
  --source-root /test-data/music-source \
  --out ../eval-run-remux-post-fix/evaluation-report-post-fix.md
```

(Rendered with `--extra-section` for per-work reporting, the delta table and the
finding reproduction, and with three `--finding` entries.)

Per-work roll-up:

```
PYTHONPATH=evaluation:../musigtagger/src uv run --project ../musigtagger python \
  evaluation/tools/per_work_rollup.py \
  --manifest evaluation/fixtures/fixed-set-47-v1.json \
  --events ../eval-run-remux-post-fix/engine-events.jsonl \
  --hand-check ../eval-run-remux-post-fix/hand-check.jsonl \
  --out-json ../eval-run-remux-post-fix/per-work-rollup.json \
  --out-md ../eval-run-remux-post-fix/per-work-rollup.md
```

## Results

- Run id `run-e83520cfc5a94969a100df91f9ca8579`; 47/47 indexed, 0 scan
  failures, 1/1 batch completed.
- Suggestions 47 (one per instance), all `genre.k-pop` @0.60 from
  `metadata.album`; **0** `genre.pop` (the "Soda Pop" regression is gone).
- Hand-check: 44 accept / 3 reject / 0 modify. Rejected: the two
  `Score Suite` instances and `Prologue (Hunter's Mantra)` (film-score cues,
  not K-pop; taxonomy has no soundtrack/film-score genre).
- Instance level: precision 93.6% (44/47), coverage 93.6% (44/47).
- Work level (14 works, deduplicated to (work, tag) pairs): precision 85.7%
  (12/14), coverage 85.7% (12/14).
- Era: 0 suggestions / 0% coverage at both levels. Correct under the binding
  operator rule — the local-date audit found no date anywhere (0 embedded date
  tags, 0 filename/title/album year matches).
- Taxonomy conformance 100% (47 refs, genre depth ≤ 2).
- Safety: unverified — no write batch was run; the report fails by design.
