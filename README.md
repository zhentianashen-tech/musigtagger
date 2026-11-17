# Music Tagger

Local, metadata-first music tagging with human review. Phase 1 reads existing
filenames and embedded tags, proposes taxonomy tags, lets you accept / edit /
reject them in a minimal local web app, and applies accepted tags with a
mandatory backup and undo.

The repository contains the Phase 1 scaffold and shared contracts, the frozen
taxonomy v1.0.0, the **engine** (batch scanner + metadata suggestion provider,
read-only), and the **application layer**: the review web app and the only code
path allowed to write audio files (`docs/APP.md`).

- **Contracts:** [`CONTRACTS.md`](CONTRACTS.md)
- **Application layer / operator guide:** [`docs/APP.md`](docs/APP.md)
- **Taxonomy data format:** [`taxonomy/FORMAT.md`](taxonomy/FORMAT.md)
- **Current taxonomy:** `taxonomy/taxonomy-1.0.0.json` (pinned by both the
  engine and the app)

## Requirements

- Python 3.11+
- `mutagen` (pinned in `pyproject.toml`) for tag I/O
- `cryptography` (pinned) for native NCM AES decryption
- SQLite (stdlib `sqlite3`)

## Install

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e .
```

Editable install for development:

```bash
pip install -e '.[dev]'    # adds pytest
```

## Run the tests

The suite needs the runtime dependencies (`mutagen`, `cryptography`) installed.
With the dev extra, run `pytest`; without installing the package, point
`PYTHONPATH` at `src/`:

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
# or, with the dev extra installed:
pytest
```

## Quick start (application layer)

```bash
pip install -e .        # pins mutagen==1.48.1

# Step 0 for NetEase libraries: convert .ncm -> persistent MP3/FLAC (remux of
# the embedded stream, sources untouched), then scan the converted tree:
python -m musigtagger.app convert --source ~/Music/ncm --output ~/Music/converted
python -m musigtagger.app --library-root ~/Music/converted scan
python -m musigtagger.app serve     # http://127.0.0.1:8765/
```

`convert` delegates decoding to MUSI-12's `musigtagger.ncm` converter
(`--ncm-converter module:Attribute` to override) and writes persistent files,
never into the source. The app scans, stores suggestions, lets you
accept/edit/reject in the browser, applies reviewed tags with a verified backup
of every file, and undoes a batch byte-for-byte. Scanning an `.ncm` directory
reports those files as needing conversion and indexes nothing — the encrypted
container is never a write target. Details: [`docs/APP.md`](docs/APP.md).

## Quick start (scan and suggest)

Scanning is recursive and batch-oriented. MP3, FLAC, Ogg, and Oga files are
parsed read-only with `mutagen`. NCM files are decoded through the single
`musigtagger.ncm` decoder and converted to their embedded MP3/FLAC/Ogg stream
in temporary storage, including their container metadata; the source file is
never modified. Each malformed track is logged in the returned `failures` and
through Python logging without aborting the batch. Rescans upsert by absolute
path and preserve track ids and creation timestamps.

```python
from musigtagger.contracts import TaxonomyLoader
from musigtagger.db import initialize_database
from musigtagger.engine import (
    JsonlEventLogger,
    LibraryScanner,
    MetadataSuggestionProvider,
    SuggestionRunner,
)

taxonomy = TaxonomyLoader.load("taxonomy", version="1.0.0")
connection = initialize_database("library.sqlite3")
scan = LibraryScanner(connection).scan_directory("/path/to/music")

provider = MetadataSuggestionProvider(taxonomy)  # pure: no I/O
logger = JsonlEventLogger("history/engine-events.jsonl")
result = SuggestionRunner(taxonomy, logger).suggest_batch(scan.tracks, provider)
for item in result.results:
    print(item.track.path, item.suggestions)
```

Embedded genre aliases and release years have high confidence. Album, artist,
folder-name, filename, and title text are graded free-text signals at lower
confidence (folder names are treated as organiser-chosen vocabulary and beat
title words; a bare single-word genre label like "pop" never fires from free
text, only from explicit vocabulary). Phase-1-unavailable facets
and user-owned personal tags are left empty. The runner validates every tag id
against the pinned taxonomy and emits complete suggestion events. Applications
can use the same logger's `log_review_outcome` for review decisions.

The migrated schema includes `tracks`, `suggestions` (five review states),
`write_batches`, `tag_backups`, `library_meta`, and the
`schema_migrations` audit table. See `src/musigtagger/db/schema_v1.sql`.

## Minimal network release-date lookup (MusicBrainz)

One operator-approved network capability ships in Phase 1: the engine can
look up an album + artist pair on the open MusicBrainz API, take the release
group's **first** release year, and propose the matching `era.<decade>s` tag
(`source=network.musicbrainz`, confidence **0.85** — a proposal below the
embedded-metadata 0.98, for evaluation tuning). Lookups are cached in the
library database (additive **schema migration v2**, `release_date_cache`) so
a 47-file batch makes ~14–16 network queries, paced at ~1 req/s. Network
unavailability, timeouts, rate limits, and no-match are honest abstentions:
the provider skips with a logged reason and the batch continues; with the
network off the run is exactly the pre-network behaviour. Requests carry
only the album/artist query strings — no personal data, no file contents.
Endpoints, matching rules, and failure behaviour:
[`docs/musicbrainz-lookup.md`](docs/musicbrainz-lookup.md).

Suggest from the command line (prints proposals and abstentions, never
writes audio files):

```bash
musigtagger-suggest /path/to/music [--library library.sqlite3] [--no-network]
```

## NCM input

Decode one local NetEase Cloud Music file losslessly (no transcoding):

```bash
musigtagger-ncm input.ncm output.flac
```

Omit `output.flac` to choose `.mp3` or `.flac` from the embedded payload. The
source is never changed, existing outputs are not overwritten, and NCM tags and
cover art are restored on the new file. The scanner calls the same
`musigtagger.ncm` module; there is no second decoder implementation. See
[`docs/ncm-format.md`](docs/ncm-format.md) for the decoder API and validation
status.

## Repository layout

```
CONTRACTS.md                 taxonomy / engine / application / observability contracts
docs/APP.md                  application layer: workflow, safety design, limits
taxonomy/
  FORMAT.md                  taxonomy data format (schema_version 1)
  taxonomy-1.0.0.json        frozen Phase 1 vocabulary (the pinned version)
  taxonomy-0.1.0-draft.json  v0 vocabulary, kept for loader/tooling history
src/musigtagger/
  contracts/                 immutable value types, provider protocol, taxonomy loader
  db/                        SQLite schema v1 + forward-only migration runner
  engine/                    scanner, metadata provider, batch runner, JSONL events
  ncm.py                     the single NCM decoder and CLI
  app/                       review UI, write path, backups/undo, events, CLI
tests/                       test suite
```

## Phase 1 status and boundaries

| Piece | Where | Status |
|---|---|---|
| Repo scaffold, contracts v1, taxonomy loader, schema v1 | MUSI-6 | delivered |
| Taxonomy v1.0.0 data | MUSI-5 | delivered |
| Library scanner + metadata suggestion provider | MUSI-7 | delivered |
| Minimal network release-date lookup (MusicBrainz, schema v2 cache) | MUSI-14 | delivered |
| Review web app + safe tag write / backup / undo | MUSI-8 | delivered |

Phase 2 (audio analysis) and Phase 3 (network enrichment) add providers behind
the same `SuggestionProvider` interface. They require no change to these
contracts; `TrackDescriptor.features` is the reserved Phase 2 seam.

## Safety invariants (apply to all later code)

- The engine never writes files; the application is the sole writer.
- No tag write batch starts without a verified backup of every target file.
- Undo restores prior bytes atomically and re-hashes the result; it is not a
  best-effort re-tag.
- Applied tags must exist in the pinned taxonomy version.
- Read-only source roots (default `/test-data/music-source`) are never written,
  not even by tests.
- Non-audio containers (`.ncm`) are converted to FLAC/MP3 before scanning; the
  application never tags an encrypted container.
- Schema changes after v1 are escalated before merge.
