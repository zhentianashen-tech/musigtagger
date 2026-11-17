# Music Tagger

Local, metadata-first music tagging with human review. Phase 1 reads existing
filenames and embedded tags, proposes taxonomy tags, lets you accept / edit /
reject them in a minimal local web app, and applies accepted tags with a
mandatory backup and undo.

The repository now contains the Phase 1 scaffold and shared contracts, the
frozen taxonomy, and the **application layer**: the review web app and the only
code path allowed to write audio files (`docs/APP.md`). The engine (scanner +
metadata provider) is a separate deliverable (`MUSI-7`).

- **Contracts:** [`CONTRACTS.md`](CONTRACTS.md)
- **Application layer / operator guide:** [`docs/APP.md`](docs/APP.md)
- **Taxonomy data format:** [`taxonomy/FORMAT.md`](taxonomy/FORMAT.md)
- **Current taxonomy:** `taxonomy/taxonomy-1.0.0.json` (pinned by the app)

## Requirements

- Python 3.11+
- `mutagen` (pinned in `pyproject.toml`) for tag I/O
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

The test suite uses only the standard library (a fake tag codec stands in for
`mutagen`), so it runs without the dev extra. The real-container tests skip with
an explicit message when `mutagen` is not installed:

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
# or, with the dev extra installed:
pytest
```

## Quick start (application layer)

```bash
pip install -e .        # pins mutagen==1.48.1
python -m musigtagger.app --library-root ~/Music/import scan
python -m musigtagger.app serve     # http://127.0.0.1:8765/
```

The app scans, stores suggestions, lets you accept/edit/reject in the browser,
applies reviewed tags with a verified backup of every file, and undoes a batch
byte-for-byte. Details, safety design, and limits: [`docs/APP.md`](docs/APP.md).

## Quick start (contracts only)

Load the pinned taxonomy, inspect it, and validate tag references:

```python
from musigtagger.contracts import TaxonomyLoader

taxonomy = TaxonomyLoader.load("taxonomy", version="1.0.0")
print(taxonomy.version, len(taxonomy), taxonomy.facet_ids)
print(taxonomy.tag("genre.hip-hop").canonical_label)   # "Hip-hop"
print(taxonomy.tag("genre.hip-hop").display_label("ja"))  # "ヒップホップ"
taxonomy.validate_tag_ids(["genre.hip-hop", "era.1990s"])
```

Create the library database (schema v1):

```python
from musigtagger.db import initialize_database

connection = initialize_database("library.sqlite3")
print(connection.execute("PRAGMA user_version").fetchone()[0])  # 1
```

The migrated schema includes `tracks`, `suggestions` (five review states),
`write_batches`, `tag_backups`, `library_meta`, and the
`schema_migrations` audit table. See `src/musigtagger/db/schema_v1.sql`.

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
  app/                       review UI, write path, backups/undo, events, CLI
tests/                       standard-library test suite
```

## Phase 1 status and boundaries

| Piece | Where | Status |
|---|---|---|
| Repo scaffold, contracts v1, taxonomy loader, schema v1 | MUSI-6 | delivered |
| Taxonomy v1.0.0 data | MUSI-5 | delivered |
| Library scanner + metadata suggestion provider | MUSI-7 | in progress; plugs into `--scanner` / `--provider` |
| Review web app + safe tag write / backup / undo | MUSI-8 | delivered (this layer) |

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
- Schema changes after v1 are escalated before merge.
