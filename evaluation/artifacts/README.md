# Evaluation artifacts — 2026-11-17 (MUSI-9)

Ground-truth pass for the fixed 47-file library, run against the recovered
engine candidate (MUSI-13 branch `agent/application-integration-engine/a9f30fec959e`
@ `6df6ffc`, unreviewed at the time of the run).

| File | What it is |
|---|---|
| `2026-11-17-hand-check.jsonl` | Evaluator accept/reject/modify decisions = ground truth (5 rows; every real suggestion was checked) |
| `2026-11-17-worksheet.jsonl` | Blank worksheet generated from the real suggestion event stream (the exact read the evaluator used) |
| `2026-11-17-engine-events.jsonl` | Real suggestion events emitted by the engine on 47 FLACs |
| `2026-11-17-testset-manifest.csv/.json` | 47-track join keys + NCM metadata + metadata state + suggestion state |
| `2026-11-17-engine-a9f30fe-report.md` | Harness report: metrics vs proposed thresholds, findings, test-set audit |
| `2026-11-17-provider-on-ncm-metadata.json` | Diagnostic: provider output when fed real NCM metadata (title/artist/album, no genre/date) |
| `../tools/` | The four read-only scripts used to produce the above |

## Result in one line

5 suggestions / 47 tracks, all `genre.pop` from a path word, all modified to
`genre.k-pop`; coverage 10.6% against a proposed 85% bar; batch completion
1/1; safety not exercised (no write batch).

## Important method note

The hand-check is per suggestion (`track_path`, `tag_id`), per Evaluation Plan
v0.1 §2. Tracks with no suggestion cannot carry an accept/reject/modify
decision; their effect is the coverage metric, not the precision denominator.

## Reproduction

Run scripts from the task workdir with `PYTHONPATH` pointing at the candidate
branch's `src/` plus the harness (`evaluation/`). The scripts are read-only
against `/test-data/music-source`; the engine run exposes the 47 FLACs through
symlinks so no source file is opened for writing.

```bash
python ncm_probe.py ncm-metadata.json                 # NCM metadata, no audio decrypt
python build_manifest.py                              # 47-track manifest + audit
PYTHONPATH=<branch-src> python run_engine_eval.py eval-run
PYTHONPATH=evaluation python -m evalharness worksheet \
  --events eval-run/engine-events.jsonl --out eval-run/worksheet.jsonl
PYTHONPATH=evaluation python -m evalharness report \
  --events eval-run/engine-events.jsonl --hand-check eval-run/hand-check.jsonl \
  --taxonomy-dir taxonomy --scan-report eval-run/scan-report.json \
  --batches eval-run/batches.json --out eval-run/report.md
```
