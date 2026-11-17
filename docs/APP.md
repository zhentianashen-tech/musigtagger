# Application layer: review app, safe tag writes, backup and undo

Phase 1, MUSI-8. This is the operator-facing application around the tagging
engine: it scans a local library, stores the engine's suggestions, lets the
operator accept / edit / reject them in a minimal local web app, and writes the
reviewed tags into audio files. It is the **only** component in the product that
writes audio files (`CONTRACTS.md` §3).

## Quick start

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -e .            # installs the pinned mutagen==1.48.1

# 0. convert non-standard containers first (NetEase .ncm -> FLAC/MP3).
#    MUSI-12 ships that decoder/CLI; its output directory is the library below.
#    Conversion is a remux of the embedded MP3/FLAC stream, not a transcode;
#    the encrypted source is never modified.

# 1. review app (binds 127.0.0.1:8765; no network access needed)
python -m musigtagger.app \
  --library-root ~/Music/import-converted \
  --provider myengine.metadata:MetadataProvider \
  serve

# 2. or drive the same workflow from the shell
python -m musigtagger.app --library-root ~/Music/import-converted scan
python -m musigtagger.app status
python -m musigtagger.app apply
python -m musigtagger.app undo --batch 1
python -m musigtagger.app history
```

Every command accepts `--db`, `--backup-dir`, `--events`, `--taxonomy-dir`,
`--taxonomy-version`, `--language`, `--protect PATH` (repeatable), and
`--scanner module:Attribute`.

Default files (relative to the working directory): `library.sqlite3`,
`backups/`, `events.jsonl`.

### Step 0: conversion before scanning

The scan step only indexes files that `mutagen` can parse (mp3, flac, ogg/opus).
A `.ncm` container is **not** an audio file: it must be converted to FLAC/MP3
first, and the converted tree — never the encrypted original — is what the app
scans, backs up, writes, and undoes. Pointing `--library-root` at an `.ncm`
directory does not work by design; the scan reports those files explicitly as
needing conversion rather than silently ignoring them.

Why the write path makes this non-negotiable: `tracks.path` is the target of the
backup and the tag write. A scan-time temporary decode cannot be the write
target, so **production conversion must write persistent MP3/FLAC files** that
survive across runs; those files are the library the app indexes and tags.
Temporary/transient conversion output is fine for tests only (the test suite
uses temporary directories and a fake tag codec), never for real tagging work.

## Where the pieces are

| Concern | Module |
|---|---|
| Configuration, write guard | `app/config.py` |
| SQLite repository (schema v1) | `app/store.py` |
| Review state machine | `app/review.py` |
| Scan trigger + provider execution | `app/ingest.py` |
| Taxonomy loading/labels/validation | `app/taxonomy_service.py` |
| Taxonomy tag → tag-field projection | `app/tagmap.py` |
| mutagen tag I/O (only file-tag writer) | `app/tagio.py` |
| Mandatory backups and byte-exact restore | `app/backup.py` |
| Apply / retry / undo batches | `app/writer.py` |
| `CONTRACTS.md` §4 event stream | `app/events.py` |
| HTML rendering | `app/render.py` |
| Local HTTP server and routes | `app/webapp.py` |
| CLI | `app/__main__.py` |

## Interfaces to the other layers

**Engine (suggestion provider).** The app calls `provider.suggest(descriptor)`
and stores the returned `TagSuggestion`s; it never classifies anything itself.
Wire one in with `--provider package.module:Attribute` (comma-separate several).
The provider must implement the frozen `SuggestionProvider` protocol and is
called outside any write: suggestions are logged as events before they are
stored, and rejected before storage if their tag id is outside the pinned
taxonomy.

**Scanner.** The app's scan trigger delegates to a `Scanner` port:
`scan(root) -> Iterable[ScanItem]` (`app/ingest.py`), configured with
`--scanner package.module:Attribute`. MUSI-7's scanner plugs in there.

> The bundled `MutagenScanner` is a deliberately small stopgap so the review and
> write paths are runnable before MUSI-7 merges. It builds `TrackDescriptor`s
> from embedded metadata only (no policy, no tag mapping) and is replaced by the
> engine engineer's scanner via `--scanner`. Treat it as dead code once that
> lands.

**Taxonomy.** Loaded by pinned version (`1.0.0` for Phase 1) through the frozen
`TaxonomyLoader`; the version is recorded in `library_meta('taxonomy_version')`
and every persisted/applied tag id is validated against it. The app adds no
tags. Values written to files are **canonical labels** (`"Hip-hop"`), never tag
ids.

## The write path (why it is safe)

For one apply batch:

1. **Validate everything first.** All `final_tag_id`s (and all previously
   applied ids) must exist in the pinned taxonomy. An unknown id aborts before a
   batch row or a byte exists.
2. **Back up every target before the first write.** `backups/batch-<id>/` gets a
   complete copy of each file, its SHA-256 is computed and compared with the
   source, and `tag_backups` records the hash plus the parsed prior tag state.
   Any backup failure marks the batch `failed` and no audio file is touched.
3. **Write per track, isolated.** For each track: read the current tags and an
   audio probe; copy the file to a hidden temporary in its own directory; write
   the projection there; read the fields back and compare with what was
   intended; probe the audio stream (format, duration ±50 ms, sample rate,
   channels); only then `os.replace()` the temporary over the target. A failure
   at any point deletes the temporary, leaves the original untouched, records
   the error, and the batch continues. If the post-replace check fails, that
   track's backup is restored immediately.
4. **Record the outcome.** `write_batches.status` becomes `completed` only when
   every track succeeded; otherwise `failed`, and the note contains per-track
   outcomes plus the applied suggestion ids. Backups are always kept.

**Undo** creates its own `undo` batch (backing up the applied state first, so
the undo is itself recoverable), restores each apply backup after verifying its
hash, re-hashes the target, and only then marks the backup `restored_at` and
reverts the review state (`applied` → `accepted`/`edited`). The applied
suggestion ids are read from the apply batch's note, so undoing one batch never
reverts another batch's tags. Undo of a partially failed batch restores the
tracks that were written.

A batch may be **retried** while in `failed` state: the remaining
accepted/edited tracks are written again using the batch's existing backups
(taken before any write), and the batch returns to `completed`/`failed`.

**Backup strategy trade-off.** The sidecar is a full copy of the file, not only
the tag payload. That is a deliberate superset of the contract: it makes undo
byte-exact for every container regardless of how `mutagen` re-paginates a file
(Ogg rewrites pages; FLAC/MP3 re-encode the tag block), and it keeps working for
containers the tag writer does not support. The cost is disk space equal to the
batch's audio; the operator chose quality over speed/space. The parsed tag state
is also stored in `tag_backups.prior_tags_json`, so the tag-level history is
queryable without the sidecar.

**Read-only source roots.** `protected_roots` (default
`/test-data/music-source`) can be scanned but never written: every backup,
write, undo, and temporary file checks the target path (resolved, symlinks
included) against them and raises `ProtectedPathError` otherwise. Symlinked
copies cannot smuggle a write into the source.

## Review workflow and batch UX

- The queue shows one card per track, with one row per suggestion: facet, label,
  confidence, source, evidence, and status.
- Per suggestion: **Accept**, **Reject**, or pick another tag in the same facet
  and **Save edit** (an edit may not change the suggestion's facet — that is a
  different claim, not a correction).
- Per track: **Accept all for this track** / **Reject all for this track**.
- Batch bar: **Accept/Reject all N matching tracks** applies to the current
  filter (status, facet, min confidence, search), not just the visible page —
  this is the 100s-scale flow. The list paginates by track (25 per page).
- **Apply all reviewed tags (N)** writes every accepted/edited suggestion in one
  backed-up batch; **History** lists batches with an **Undo batch** action and
  the last 50 events.
- No JavaScript, no external assets: the pages are self-contained and the app
  runs without network access. It binds `127.0.0.1` and has no authentication:
  it is a single-operator local tool, do not expose the port.

## History log

`events.jsonl` is the product's tagging history and the evaluation harness's
input (`CONTRACTS.md` §4): one JSON object per line, `event_version: 1`, with
`suggestion` and `review_outcome` families, `run_id`, `taxonomy_version`, track
path, tag id, confidence/source/evidence, and before/after review states.
`/history` shows the tail. Emission is best-effort by contract: a broken log
cannot block or change a write. `write_batches` + `tag_backups` add the
operational history (what was written, what was backed up, what was restored).

## Test-data protocol

- The source library (`/test-data/music-source`) is mounted read-only and is
  **never** written — not by tests, not by the app while scanning. Copy a small
  representative sample into `/test-data/music-working` for write tests; never
  copy the whole library.
- The test suite here uses temporary directories and a fake tag codec, so it
  touches neither location. A dedicated test asserts a write aimed at a
  protected root is refused and leaves the source bytes untouched.

### Note on the actual test library

The mounted library at `/test-data/music-source` contains **47 `.ncm` files**
(NetEase Cloud Music's encrypted container) plus cover art — no mp3/flac/ogg.
`mutagen` cannot parse `.ncm`, so a scan of that directory reports 47 files as
`ncm_requires_conversion` and indexes zero tracks. That is the correct, explicit
behaviour: conversion is step 0.

The conversion itself belongs to **MUSI-12** (decoder module + CLI, engine
engineer; one-file-in/one-file-out). I verified the published algorithm against
the operator's real files read-only: all **47/47** decode to a valid MP3 stream
(ID3v2.4 tag followed by a valid MPEG frame chain; duration/bitrate consistent
with the container metadata), with the original files untouched. The payload is
already MP3, so this is remux — no transcode and no quality loss.

Once MUSI-12 lands: convert into `/test-data/music-working/...` (or any writable
tree), then run the app with `--library-root` pointing at the converted output.
The app's scan, review, apply, backup, and undo then operate on real files.

## Test results

Run offline:

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
```

- 84 scaffold/contract/taxonomy tests + 78 application tests = **162 tests**.
- The real-container tests in `tests/test_tagio_mutagen.py` require `mutagen`.
  They are skipped in a runtime without it (they degrade to an explicit skip,
  not a failure). In this runtime `mutagen` is not installed and the environment
  has no network, so those three tests were skipped; the write-path mechanics
  they cover are exercised by the fake-codec tests, and the mutagen adapter is a
  thin, reviewable layer over them. Run the suite in an environment with
  `pip install -e .` to execute them.

## Assumptions, limits, unresolved dependencies

1. **Tag-field projection is an application decision, documented in
   `app/tagmap.py`.** Genre uses the standard `TCON`/`GENRE`; every other facet
   uses a namespaced field (`TXXX:ERA`, `ERA`, ...) because `era.1990s` is not a
   date (`TDRC` would corrupt year semantics) and `mood` has no standard ID3v2.3
   frame. Projecting facets onto standard fields (`TMOO`, `TDRC`) changes what a
   tag *means* and needs a leader/designer decision; it is not settled here.
2. **The `personal` facet is `open_set` and enumerates no tags in v1.0.0**, and
   `origin.lang-<iso>` ids are scheme-generated. Strict taxonomy validation means
   those values cannot be written until an additive contract change (the gap
   already recorded for MUSI-5/MUSI-7). The UI only offers enumerated tags.
3. **Undo is not a redo UI.** The undo batch keeps a backup of the applied state,
   so the data is recoverable, but there is no one-click "redo" action.
4. **Multiple writers are not supported.** Batches assume this process is the
   only writer, as the contract requires. If a file changes outside the app
   between apply and undo, undo restores the pre-apply bytes anyway; the pre-undo
   state is kept in the undo batch.
5. **Format coverage:** mp3 (ID3v2), flac and ogg/opus (Vorbis comments). Other
   containers are refused per track with a logged reason (skip-and-continue), so
   a batch never aborts because of an unsupported file.
6. **No scale work beyond 100s of files per batch**, per the operator; the app
   stores and reviews everything in SQLite and appends events synchronously.
7. **Scanner/provider wiring is pending MUSI-7.** The app runs end to end with
   any conforming `--scanner`/`--provider`; the bundled fallback scanner is a
   stopgap.
