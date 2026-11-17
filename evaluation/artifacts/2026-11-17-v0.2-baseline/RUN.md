# Plan v0.2 baseline run — 2026-11-17

**Status: baseline executed on the merged `main`; the four quality bars are
accepted by the operator (2026-11-17T12:03:18Z), the safety gate is satisfied by
the option-A 2-track copy smoke (all five approved bars now pass), and era recall
is recorded as "unmeasured — runtime egress". One networked date check remains
before final Phase-1 acceptance (see `ACCEPTANCE.md`).**

## Engine build and input

- `origin/main` = `5354663` (MUSI-14 merge of `edc827d`): local metadata
  provider + MusicBrainz release-year provider, schema v2.
- Frozen input: `/test-data/music-working/eval-input-ncm-remux` (47 MP3s,
  title/artist/album/cover 47/47; genre/date 0/47).
- Frozen track list: `evaluation/fixtures/fixed-set-47-v1.json`
  (`content_sha256 181e18b4…`).
- Pre-labels: plan v0.2 in force, 14 works / 47 instances.

## Run

```
PYTHONPATH=src:evaluation python evaluation/tools/run_v0_2_baseline.py eval-run-v0.2
```

- Scan: 47/47 indexed, 0 scan failures, batch completed.
- Local provider: **47 suggestions, all `genre.k-pop`**, source
  `metadata.album`, confidence 0.60. The `Soda Pop` title-word false-positive
  class is gone.
- Network provider: **16 unique (album, artist) pairs attempted, 47/47 tracks
  abstained, 0 era suggestions**, 49.5 s total, zero hangs. Every failure is
  `NetworkLookupError: No route to host`; memoization limited the batch to 16
  attempts, not 47.
- Hand-check: **44 accept / 3 reject / 0 modify**. Rejected: the two
  `Score Suite` instances and `Prologue (Hunter's Mantra)` — film-score cues
  the album-level K-pop suggestion gets wrong (taxonomy has no film-score tag;
  post-acceptance v1.1 gap).

## Measures against the operator-approved bars

| Bar | Measured | Verdict |
|---|---|---|
| Suggestion precision | 93.6% (44/47) | **PASS** (≥75%) |
| Coverage | 93.6% (44/47) | **PASS** (≥85%) |
| Batch completion | 100% (1/1) | **PASS** |
| Taxonomy conformance | 100% (47 refs) | **PASS** |
| Safety | 3/3 checks pass on a 2-track copy smoke (option A) | **PASS** |

Recall (report-only): genre 93.6% (44/47), era **0/47**, origin 0/44, overall
**31.9% instance / 30.0% work-level**. Era is not a provider-logic failure:
`musicbrainz.org:443` has no route from this runtime (DNS resolves, TCP
blocked; evidence in `egress-check.txt`, matching MUSI-14's own delivery
note). If the date lookup resolved all 14 works, era would add 47/47 and lift
instance recall to **65.9%** (work-level 65%); origin stays 0 under the
accepted Phase 2/3 gap. `Score Suite` may still abstain even with network
because its album is the separate score release group, so 47/47 is a ceiling.

## Decision (resolved 2026-11-17T12:03:18Z)

The operator accepted option 1: **baseline accepted on the four approved bars;
era recall recorded as "unmeasured — runtime egress"; one networked date check
required before final Phase-1 acceptance.** Record: `ACCEPTANCE.md`
(operator comment `01a1e963-dcea-7704-b122-fc9f8e6bd098`). The check tool is
`evaluation/tools/networked_date_check.py`, runbook in `ACCEPTANCE.md`.

Safety is satisfied for the operator-approved option-A scope by the
`2026-11-17-safety-smoke/` run: real app write path on 2 copies, backup before
write, byte-exact undo, source untouched, all three harness checks pass. The
leader's MUSI-8 review and MUSI-10 integration still cover full app behaviour.

## Artifacts

- `evaluation-report-v0.2.md` — harness report (approved thresholds, findings)
- `engine-events.jsonl` — real suggestion events (47 local)
- `worksheet.jsonl` / `hand-check.jsonl` — generated worksheet and decisions
- `suggestions.json`, `scan-report.json`, `batches.json`
- `egress-check.txt` — DNS/TCP/API evidence and provider run summary
- `../2026-11-17-safety-smoke/` — option-A safety evidence (apply/backup/undo)
