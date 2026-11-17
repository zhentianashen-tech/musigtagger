# Music Tagger — Evaluation Report

- Evaluation plan version: **v0.1**
- Dataset: fixed 47-file library (/test-data/music-source, read-only)
- Run ids: run-6acdcf18653a470dbb1eceb192d4e7f3
- Taxonomy pinned: `1.0.0`

> **All thresholds below are proposals — PROPOSED — pending human sign-off.** Nothing in this report settles an acceptance bar.

## Gating summary

| Metric | Measured | Proposed threshold | Verdict |
|---|---|---|---|
| Suggestion precision (overall) | 0.0% (0/5 checked) | ≥ 75% | ❌ fails proposed threshold (PROPOSED — pending human sign-off) |
| Coverage (tracks with ≥1 usable tag) | 10.6% (5/47) | ≥ 85% | ❌ fails proposed threshold (PROPOSED — pending human sign-off) |
| Batch completion rate | 100.0% (1/1) | = 100% | ✅ meets proposed threshold (PROPOSED — pending human sign-off) |
| Taxonomy conformance | 100.0% (10 tag refs checked) | = 100% | ✅ meets proposed threshold (PROPOSED — pending human sign-off) |
| Safety (source protection / backup / undo) | FAIL | zero violations | ❌ fails proposed threshold (PROPOSED — pending human sign-off) |

## 1. Suggestion precision per category (primary metric)

*Reported with counts: the evaluation set is small (n=47), so a percentage resting on a handful of items must not be over-read.*

| Category | Suggested | Checked | Accepted | Rejected | Modified | Precision (acc/checked) |
|---|---|---|---|---|---|---|
| genre | 5 | 5 | 0 | 0 | 5 | 0.0% |
| **overall** | 5 | 5 | 0 | 0 | 5 | **0.0%** |

### Precision by suggestion source

| Source | Suggested | Checked | Accepted | Rejected | Modified | Precision |
|---|---|---|---|---|---|---|
| metadata.path | 5 | 5 | 0 | 0 | 5 | 0.0% |

## 2. Coverage

- Tracks with ≥1 usable tag: **5**
- Denominator: **47** (scan report (indexed tracks))
- Coverage: **10.6%** — ❌ fails proposed threshold (PROPOSED — pending human sign-off)

## 3. Correction burden

- Modifications per checked track: 1.00
- Rejections per checked track: 0.00
- App-side edits per track (cross-check from review outcomes): 0.00

## 4. Batch completion (gating robustness metric)

- Batches observed: 1; completed without mid-run crash: 1 (rate 100.0%) — ✅ meets proposed threshold (PROPOSED — pending human sign-off)

## 5. Taxonomy conformance

- Tag references checked: 10
- Unknown tag ids: 0
- Genre depth violations (depth > 2): 0
- Conformance: 100.0% — ✅ meets proposed threshold (PROPOSED — pending human sign-off)

## 6. Safety

- Evidence records read: 0

| Check | Result | Detail |
|---|---|---|
| safety evidence present | ❌ FAIL | no backup/write/undo evidence supplied — safety is unverified, which fails the report by design |

Proposed thresholds: zero writes to the source library, zero corruption incidents, undo verified on every sampled case (PROPOSED — pending human sign-off).

## 7. Cross-check: evaluator decisions vs app review outcomes

- Comparable decisions: 0; agreements: 0

## 8. Defects and findings (severity order)

| Severity | Classification | Finding | Responsible role |
|---|---|---|---|
| high | tagging-engine defect | Coverage on the frozen set is 5/47 (10.6%): one path-derived genre.pop suggestion for 5 'Soda Pop' files, nothing for 42 tracks | Tagging Engine Engineer |
| high | evaluation-data problem | Fixed 47-FLAC evaluation set is metadata-stripped: 0/47 carry title/artist/album/genre/date or cover art | Lead Architect / fixed-set owner |
| high | tagging-engine defect | Provider ignores title/artist/album: freezing the metadata-bearing NCM library still yields 5/47 coverage, not more | Tagging Engine Engineer |
| medium | application/integration defect | 4/47 FLAC/NCM pairs differ only by Unicode normalisation (NFC vs NFD); exact-string pairing or dedup will miss them | Application & Integration Engineer |
| medium | architectural/cross-component problem | The '47 converted FLAC files' are not the product of MUSI-12: every NCM payload is MP3, so the FLAC set is an external transcode that dropped tags/cover | Lead Architect (freeze the evaluation input) |
| medium | evaluation-data problem | The 47 files are 35 unique works: 12 works duplicated across standard/deluxe album editions and 21 variant files (acapella/instrumental/sing-along) of 7 works | Lead Architect / fixed-set owner |
| info | evaluation-data problem | Independent confirmation of the leader's 47/47 decode claim — for metadata and MP3 payload, not FLAC output | Evaluation & Review Agent |

### Reproduction evidence

- **Coverage on the frozen set is 5/47 (10.6%): one path-derived genre.pop suggestion for 5 'Soda Pop' files, nothing for 42 tracks**
  - Evidence: Real engine run (47 FLACs, 47 indexed, 0 scan failures): 5 suggestion events, all tag_id=genre.pop, source=metadata.path, confidence=0.55, evidence='path contains Pop'. 42/47 tracks receive zero suggestions; 0 era, 0 origin, 0 mood, 0 activity, 0 personal suggestions were produced.
  - Reproduction: PYTHONPATH=/tmp/musi13/src:/root/.cache/uv/archive-v0/4MYScmba3_-DuKml:/root/.cache/uv/archive-v0/dNYpoOn6YUQebGSh .venv/bin/python run_engine_eval.py eval-run
- **Fixed 47-FLAC evaluation set is metadata-stripped: 0/47 carry title/artist/album/genre/date or cover art**
  - Evidence: mutagen over all 47 files at /test-data/music-source: every file's only Vorbis comments are encoder=Lavf59.27.100 and encoding_tool=sdk_2118(...); 0/47 have any of title/artist/album/genre/date; 0/47 have an embedded picture.
  - Reproduction: for f in /test-data/music-source/*.flac; do PYTHONPATH=src .venv/bin/python -c 'import sys;from mutagen.flac import FLAC;a=FLAC(sys.argv[1]);print(sys.argv[1], sorted(a.tags))' "$f"; done
- **Provider ignores title/artist/album: freezing the metadata-bearing NCM library still yields 5/47 coverage, not more**
  - Evidence: Diagnostic on descriptors built from the real NCM metadata (title/artist/album populated; genre=None, year=None because NCM carries neither): 47 descriptors, 35 unique works, 5 with a suggestion, 5 suggestions — all genre.pop from metadata.path. Album 'KPop Demon Hunters (Soundtrack from the Netflix Film ...)' and K-pop artists (TWICE, MeloMance, Saja Boys) are present but the provider reads only descriptor.genre, descriptor.year and the path. Metadata preservation alone cannot lift coverage on this library.
  - Reproduction: PYTHONPATH=/tmp/musi13/src .venv/bin/python simulate_ncm_descriptors.py
- **4/47 FLAC/NCM pairs differ only by Unicode normalisation (NFC vs NFD); exact-string pairing or dedup will miss them**
  - Evidence: 43/47 basenames match exactly; the 4 NFD NCM names (Jokers - 오솔길 Path, MeloMance - 사랑인가 봐 Love, Maybe [x2], 죠커스 - 오솔길 Path) normalise to their NFC FLAC twins. macOS path resolution opens either form, but any code that joins or dedups by raw string will fail and may index/copy duplicates.
  - Reproduction: python build_manifest.py — see exact_name_pairs=43, nfd_name_pairs=4
- **The '47 converted FLAC files' are not the product of MUSI-12: every NCM payload is MP3, so the FLAC set is an external transcode that dropped tags/cover**
  - Evidence: All 47 NCM containers decrypt (fixed core key hzHRAmso5kInbaxW, XOR 0x64 on the key blob, XOR 0x63 -> prefix -> base64 -> AES for metadata) and every payload is MP3 (declared and actual), 320 kbps, with title/artist/album and a cover image (2 distinct album covers). The 47 FLACs are 24-bit, have Lavf/encoding_tool tags, and their durations track the NCM metadata duration within 25-135 ms — i.e. they are a transcode of the NCM audio with all metadata/cover stripped. The decoder emits .mp3 for these inputs, never .flac.
  - Reproduction: python ncm_probe.py ncm-metadata.json; see summary formats_actual={mp3:47}
- **The 47 files are 35 unique works: 12 works duplicated across standard/deluxe album editions and 21 variant files (acapella/instrumental/sing-along) of 7 works**
  - Evidence: NCM metadata (title/album/musicId) over all 47 containers: 47 files but 35 distinct works once '(1)' and acapella/instrumental/sing-along suffixes are stripped; 35 files carry album 'KPop Demon Hunters (Deluxe Version)' and 12 carry the standard edition, so 12 works appear in both editions (24 file instances); 21 files are variants of 7 works; 11 files carry a '(1)' filename suffix. Effective independent sample for per-category precision is 35 works, and the only measured category rests on 1 work.
  - Reproduction: python build_manifest.py (writes testset-manifest-v0.1.json/.csv)
- **Independent confirmation of the leader's 47/47 decode claim — for metadata and MP3 payload, not FLAC output**
  - Evidence: Read-only probe of all 47 NCMs: 47/47 metadata blocks decrypt, 47/47 declare and carry MP3, 47/47 have title+artist+album, 47/47 have a cover. Full decode() spot-check on 3 representative files (fullwidth '／', NFD Hangul, plain ASCII) produced valid MP3 streams and correct metadata.
  - Reproduction: PYTHONPATH=/tmp/musi12/src .venv/bin/python ncm_probe.py; decode() spot-check script

## 9. Limitations

- Sample size: the fixed evaluation set is 47 files; per-category precision may rest on very few items. Counts are reported alongside percentages for this reason.
- The library comes from one source/folder; its genre and era distribution may not represent future batches.
- Ground truth is a single external evaluator; reasons on rejections/modifications keep drift auditable.

## 10. Evidence artifacts

- Event stream files read:
  - `eval-run/engine-events.jsonl`
- Evaluator hand-check log (ground truth): see `--hand-check` input.
- Tagging-history log (the app's own §4 event stream) cross-checked in §7.
- Safety test notes: see `--safety-evidence` input and §6.

## 11. Test-set audit (engine-independent, read-only)

| Check | Result |
|---|---|
| FLAC files | 47, all readable (mutagen), 24-bit, 44.1/48 kHz, 46.9–251.1 s |
| FLAC embedded metadata | 0/47 with title/artist/album/genre/date; only `encoder`, `encoding_tool` |
| FLAC cover art | 0/47 embedded pictures |
| NCM files | 47; metadata decodes for 47/47; title+artist+album 47/47; cover art 47/47 |
| NCM payload | MP3 320 kbps for 47/47 (declared and actual) |
| FLAC vs NCM duration | delta -25 to -135 ms for 47/47 → same recordings, FLAC is a transcode |
| Name pairing | 43 exact, 4 NFD/NFC; 47/47 pair after NFC normalisation |
| Works vs files | 35 unique works; 12 cross-edition duplicates; 21 variant files |

Consequence: the metadata-first engine sees **filenames only** on this set. Era
(needs a release date), genre (needs an embedded genre), and cover-dependent
behaviour are structurally unexercisable; mood/activity are Phase-1-unavailable
by design and personal is user-owned, so the only auto-suggested facet can be
genre/origin from path words.

Preserving the NCM metadata does **not** change that: NCM carries title/artist/
album but no genre and no release date, and the provider consumes only
`genre`, `year` and the path. A descriptor-level diagnostic using the real NCM
metadata reproduces exactly the same 5 suggestions. Coverage is therefore an
engine gap as well as a test-set gap.

## 12. Scope and sensitivity of this result

- Engine build evaluated: **MUSI-13 branch agent/application-integration-engine/a9f30fec959e @ 6df6ffc (unreviewed recovery of MUSI-7)**. This is a candidate build; the hand-check log is versioned and must be re-run if the provider changes.
- Strict reading (this log): all 5 broad `genre.pop` suggestions are **modified** to the specific `genre.k-pop` → precision 0/5. The operator asked for genre + subgenre and the track is K-pop, so the specific tag is the correct primary genre; the engine fired on the title word "Pop", not on evidence.
- Lenient reading (sensitivity only, does not change the log): if a depth-1 `genre.pop` is accepted as taxonomy-valid, precision becomes 5/5 (100%).
- Either reading rests on **one unique work** (5 files = 2 album-edition copies + 3 variants); neither changes the coverage failure (5/47 = 10.6%).
- Safety was not exercised in this run (no write/backup/undo batch); the harness reports safety as **unverified → FAIL by design**, not as a measured violation. The source mount is read-only, so no source write was possible.
- The 42 tracks with no suggestions cannot enter the precision denominator; their effect is the coverage failure.
- Recommendation: freeze the evaluation input explicitly. Preferred: the product's persistent NCM→MP3 conversion (title/artist/album/cover preserved) as the primary set, with the tagless 47 FLACs as a filename-only robustness subset — but note that today it produces the **same 5/47**, so this is about representativeness, not a coverage fix. That is a plan-v0.1 test-set change and needs the leader/operator decision; this report does not substitute it silently.
- Coverage threshold: the proposed ≥85% is not reachable on this library with the current provider (no embedded genre/date, no album/artist use) and no Phase-2/3 provider. That is a threshold decision for the operator, not something I will relax; the engine-side fix is to use album/artist signals at honest low confidence.

## 13. Reproduce

```bash
# 1. Probe NCM metadata (read-only)
PYTHONPATH=<cryptography wheel dirs> .venv/bin/python ncm_probe.py ncm-metadata.json
# 2. Audit the fixed set
.venv/bin/python build_manifest.py
# 3. Run the candidate engine over the 47 FLACs (symlinked, source untouched)
PYTHONPATH=/tmp/musi13/src .venv/bin/python run_engine_eval.py eval-run
# 4. Generate worksheet, fill decisions, render report
PYTHONPATH=evaluation .venv/bin/python -m evalharness worksheet \
  --events eval-run/engine-events.jsonl --out eval-run/worksheet.jsonl
PYTHONPATH=evaluation .venv/bin/python -m evalharness report \
  --events eval-run/engine-events.jsonl --hand-check eval-run/hand-check.jsonl \
  --taxonomy-dir taxonomy --scan-report eval-run/scan-report.json \
  --batches eval-run/batches.json --out eval-run/report.md
```

