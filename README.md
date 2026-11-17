# Music Tagger

Local, metadata-first music tagging with human review. Phase 1 reads existing
filenames and embedded tags, proposes taxonomy tags, lets you accept / edit /
reject them in a minimal local web app, and applies accepted tags with a
mandatory backup and undo.

The repository contains the shared contracts, taxonomy v1.0.0, and the Phase 1
batch scanner and metadata suggestion engine. The review UI and tag-writing
code remain separate deliverables; the engine never writes audio files.

- **Contracts:** [`CONTRACTS.md`](CONTRACTS.md)
- **Taxonomy data format:** [`taxonomy/FORMAT.md`](taxonomy/FORMAT.md)
- **Current taxonomy:** `taxonomy/taxonomy-1.0.0.json` (the engine pins this
  exact version)

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

The suite needs the runtime dependencies (`mutagen`, `cryptography`) installed:

```bash
python -m unittest discover -s tests -v
```

If you installed the dev extra, `pytest` collects the same tests:

```bash
pytest
```

Without installing the package, point `PYTHONPATH` at `src/`:

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
```

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
taxonomy/
  FORMAT.md                  taxonomy data format (schema_version 1)
  taxonomy-1.0.0.json        frozen Phase 1 vocabulary
src/musigtagger/
  contracts/                 immutable value types, provider protocol, taxonomy loader
  db/                        SQLite schema v1 + forward-only migration runner
  engine/                    scanner, metadata provider, batch runner, JSONL events
  ncm.py                     the single NCM decoder and CLI
tests/                       test suite
```

## Phase 1 status and boundaries

| Piece | Where | Status |
|---|---|---|
| Repo scaffold, contracts v1, taxonomy loader, schema v1 | this issue (MUSI-6) | delivered |
| Taxonomy v1.0.0 data | MUSI-5 | delivered |
| Library scanner + metadata suggestion provider | MUSI-7 | delivered |
| Review web app + safe tag write / backup / undo | MUSI-8 | next stage |

Phase 2 (audio analysis) and Phase 3 (network enrichment) add providers behind
the same `SuggestionProvider` interface. They require no change to these
contracts; `TrackDescriptor.features` is the reserved Phase 2 seam.

## Safety invariants (apply to all later code)

- The engine never writes files; the application is the sole writer.
- No tag write batch starts without a stored backup of prior tag state.
- Undo restores prior tag frames; it is not a best-effort re-tag.
- Applied tags must exist in the pinned taxonomy version.
- Schema changes after v1 are escalated before merge.
