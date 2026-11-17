# Safety smoke test — option A (2026-11-17)

**Operator decision:** "go with A" (MUSI-9, 2026-11-17) — keep the safety gate
but shrink it to one copy-based apply / backup / undo smoke test.

## What was run

- Application code: MUSI-8 branch `agent/application-integration-engine/ad8d3c40c54f`
  (`c3dc20b`) — the real `ApplyService` / `BackupManager` / `MutagenTagger`
  write path, not a reimplementation.
- Samples: 2 MP3s copied from the frozen remux set into
  `/test-data/music-working/safety-smoke-20261117T121323Z/library/`
  (`Saja Boys,Andrew 崔,Neckwav - Soda Pop.mp3`, `TWICE - Strategy.mp3`).
- Batch 1: `genre.k-pop` accepted and applied → 2 backup sidecars, 2 writes,
  batch `completed`.
- Batch 2: undo → 2 undo pre-backups, 2 restores, batch `completed`; both files
  byte-identical to the originals (SHA-256 and bytes).
- Source library hashes unchanged before/after; the protected root was never
  written.

## Harness safety checks (all pass)

| Check | Result |
|---|---|
| Source-root protection (zero writes to `music-source`) | PASS |
| Backup exists before every write batch | PASS |
| Undo restores prior state | PASS |

Evidence: `safety-evidence.jsonl` (backup/write/undo records with timestamps),
`app-events.jsonl` (the app's review-outcome stream), `safety-smoke-report.json`.

## Scope and limitations

- 2 tracks, MP3/ID3 only; FLAC/Vorbis is covered by the app's own tests and the
  MUSI-10 integration pass, not by this smoke test.
- The smoke tests the write path, backup, and byte-exact undo; it does not test
  the 47-track batch throughput or the web UI.
- This is the operator-approved minimal safety gate. The leader's MUSI-8 review
  and MUSI-10 integration pass still cover the full app behavior.

## Result

The safety gate is **satisfied for the agreed scope**. The v0.2 baseline
report can now be rendered with this evidence; the only remaining Phase-1
precondition is the networked date check.
