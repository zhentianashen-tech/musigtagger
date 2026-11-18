# Plan v0.3 baseline run — 2026-11-18

**Status: networked baseline regenerated on merged `main` after the MUSI-14
era-lookup fix; era recall is now a measured 47/47. This artifact set is the
default Phase-1 baseline and supersedes `2026-11-17-v0.2-baseline/` (kept for
audit history — see its `SUPERSEDED.md`).**

## Why this run exists

The v0.2 baseline checked in by MUSI-16 predates the MUSI-14 era-lookup fix
(`d50a813`). Its report records era recall **0/47** — a provider query defect
that MUSI-14 later fixed and that the v0.3 networked re-baseline measured at
**47/47 (100%), 0 network errors** on merged `main`. This run regenerates the
baseline from the current head so the checked-in numbers match the live engine.

## Engine build and input

- `main` = `29cd5e0` (MUSI-15 app fixes merged on top of the MUSI-14 era fix
  `d50a813`). Local metadata provider + MusicBrainz release-year provider,
  schema v3 (query-versioned release-date cache).
- Frozen input: `/test-data/music-working/eval-input-ncm-remux` (47 MP3s,
  title/artist/album/cover 47/47; genre/date 0/47).
- Frozen track list: `evaluation/fixtures/fixed-set-47-v1.json`.
- Pre-labels: plan v0.2 in force, 14 works / 47 instances
  (`evaluation/fixtures/track-pre-label-worksheet-v0.2.csv`).
- Ground truth: the evaluator hand-check carried forward from v0.2 unchanged
  (47 genre decisions; era is scored against pre-labels, not hand-checked).

## Regeneration command

```
PYTHONPATH=src:evaluation uv run --no-project python evaluation/tools/run_v0_2_network_baseline.py \
  eval-run-v0.3 --taxonomy taxonomy --run-id-prefix v0.3 --max-attempts 5
```

## Run summary

- Scan: **47/47 indexed, 0 scan failures**, batch completed.
- Local provider: **47 suggestions, all `genre.k-pop`**, source
  `metadata.album`, confidence 0.60.
- Network provider: **47 suggestions, all `era.2020s`**, source
  `network.musicbrainz`, confidence 0.85 — **0 network errors**.
- Network ledger: 32 HTTP requests across 18 unique pairs, 2 transient
  retries (503 bursts, all recovered), min request spacing 1.1 s
  (mean 2.3 s), 0 transport failures. Cache: 16 rows, all `found=true`.
- 12/47 instances carry the reviewer-visible artist-credit flag (cast-credited
  release group vs per-track artist); **none changes the era outcome** — every
  flagged instance resolves `era.2020s` matching the pre-labels.

## Measures against the operator-approved bars

| Metric | Measured | Verdict |
|---|---|---|
| Suggestion precision (overall) | 93.6% (44/47) | **PASS** (≥75%) |
| Coverage | 93.6% (44/47) | **PASS** (≥85%) |
| Batch completion | 100% (1/1) | **PASS** |
| Taxonomy conformance | 100% (94 tag refs) | **PASS** |
| Safety | 3/3 checks pass (v0.2 safety smoke) | **PASS** |
| Era recall (report-only) | **47/47 = 100.0%** | **measured** |

Recall (report-only): genre 93.6% (44/47), era **100.0% (47/47)**, origin
0/44 (accepted Phase 2/3 gap), overall **65.9% instance (91/138) / 65.0% work
(26/40)**.

## Reproduce (scores the checked-in artifacts; no network needed)

```
uv sync
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

Exit `0` = all gating checks pass; the report renders era recall **47/47**.

## Artifacts

- `evaluation-report-v0.3.md` — harness report (approved thresholds, findings)
- `engine-events.jsonl` — 94 real suggestion events (47 local + 47 network era)
- `worksheet.jsonl` / `hand-check.jsonl` — generated worksheet and decisions
- `suggestions.json`, `scan-report.json`, `batches.json`, `network-stats.json`
- `../2026-11-17-safety-smoke/` — option-A safety evidence (apply/backup/undo)
