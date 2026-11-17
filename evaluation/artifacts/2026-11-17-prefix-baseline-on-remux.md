# Pre-fix baseline on the frozen remux evaluation input

Status: **pre-fix baseline**, not the re-baseline. The provider signal fix
(MUSI-7) had not landed when this ran; the official re-run happens after it
and after the merged `main` build is verified.

## 1. The input that was built

- Source: 47 `.ncm` files in `/test-data/music-source` (read-only).
- Converter: `musigtagger.ncm.decode/convert` from the leader-accepted MUSI-13
  branch (`6df6ffc`), which carries MUSI-12's fixed decoder. No transcoding:
  the MP3 payload is written verbatim and NCM title/artist/album/cover are
  attached by the decoder.
- Output: `/test-data/music-working/eval-input-ncm-remux/` — **47/47 converted,
  0 failed, 371,411,291 bytes, 47 MP3s**.
- Embedded metadata: **title 47/47, artist 47/47, album 47/47, cover 47/47;
  genre 0/47, release date 0/47** (NCM carries neither).
- Full outcomes and per-file SHA-256: `conversion-report.json` in the output
  directory, copied to `evaluation/artifacts/2026-11-17-remux-input-report.json`.

## 2. Pre-fix engine result on the rebuilt input

Engine: main-merged MUSI-13 build (provider unchanged) scanning
`/test-data/music-working/eval-input-ncm-remux`.

| Metric | Value |
|---|---|
| Tracks indexed | 47 / 47 discovered, 0 scan failures |
| Descriptor coverage | title 47, artist 47, album 47, genre 0, year 0 |
| Suggestions | **5** (all `genre.pop`, `metadata.path`, confidence 0.55, evidence "path contains 'Pop'") |
| Hand-check | 5 modified → `genre.k-pop`; precision **0/5** |
| Coverage | **5/47 = 10.6%** (file level) |
| Batch completion | 1/1 = 100% |
| Taxonomy conformance | 100% (10 tag refs) |
| Safety | unverified (no write batch) → fails by design |

This is the same result as the tagless FLAC pass, and it is exactly the defect
the leader routed: the provider consumes `genre`, `year` and the path, so the
newly available title/artist/album/cover evidence changes nothing.

## 3. Set-shape correction (important)

The earlier "35 works / 47 files" figure was wrong. 35 is the count of distinct
titles **including** variant suffixes. The frozen manifest now records:

| Shape | Count |
|---|---|
| Track instances | 47 |
| **Distinct works** (strip `(Acapella)`/`(Instrumental)`/`(Sing-Along)` and `(1)`) | **14** |
| Works with 5 instances (2 album editions + 3 variants) | 7 |
| Works with 2 instances (one per edition) | 5 |
| Deluxe-only works | 2 |
| Variant instances | 21 |
| Cross-edition duplicate instances | 24 |

Consequences for reporting:

- File-level coverage pre-fix is 5/47 = 10.6%; **work-level coverage is 5/14 =
  35.7%**. Both stay below the proposed 85%, but the two denominators must be
  stated, and per-category results must not let the 7 five-instance works
  dominate.
- The two "오솔길 Path" instances (Jokers / 죠커스, one per album edition,
  identical 221.805 s duration) are grouped as one work; the artist-credit
  difference is a metadata inconsistency to record, not a second work.

## 4. What the provider fix has to close

1. **Use artist and album.** The album string
   `KPop Demon Hunters (Soundtrack from the Netflix Film ...)` and artists
   (TWICE, MeloMance, Saja Boys, HUNTR/X, …) are present on all 47 tracks and
   are the only non-path signals that identify K-pop. Cite the field and value
   in `evidence`, keep confidence honest/low, and do not use `genre.pop` just
   because a title contains "Pop".
2. **Do not promise era from NCM.** There is no release date in NCM metadata;
   era suggestions can only come from external knowledge or a later provider.
   The structural ceiling should be stated, not hidden.
3. **Cover art is not a tag signal** in the current provider; it is preserved
   for the app/UI and future providers.

## 5. Re-run queue

- `origin/main` now contains the accepted engine + single decoder
  (`1a92b2c`, MUSI-13 merge, 2026-11-17 10:16Z).
- MUSI-7 (provider fix) is `blocked` on an OpenCode provider outage, not on
  this evaluation; the existing MUSI-7-`done` wakeup will resume MUSI-9.
- Re-run command is ready (`run_engine_on_dir.py` + `evalharness report`) and
  will use the frozen manifest and this remux input unchanged.
