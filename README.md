# Music Tagger

Local, metadata-first music tagging with human review. Phase 1 reads existing
filenames and embedded tags, proposes taxonomy tags, lets you accept / edit /
reject them in a minimal local web app, and applies accepted tags with a
mandatory backup and undo.

**This repository currently contains the Phase 1 scaffold and the shared
contracts only.** It has no suggestion logic, no review UI, and no tag-writing
code yet — those are separate deliverables (`CONTRACTS.md` §7). The point of
this layer is to freeze the interfaces every later component builds against.

- **Contracts:** [`CONTRACTS.md`](CONTRACTS.md)
- **Taxonomy data format:** [`taxonomy/FORMAT.md`](taxonomy/FORMAT.md)
- **Current taxonomy:** `taxonomy/taxonomy-0.1.0-draft.json` (v0; v1.0.0 lands
  as a new file with no schema change)

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

The committed tests use only the standard library, so they run without the dev
extra:

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

## Quick start (contracts only)

Load the pinned taxonomy, inspect it, and validate tag references:

```python
from musigtagger.contracts import TaxonomyLoader

taxonomy = TaxonomyLoader.load("taxonomy", version="0.1.0-draft")
print(taxonomy.version, len(taxonomy), taxonomy.facet_ids)
print(taxonomy.tag("genre.hip-hop").canonical_label)   # "Hip-hop"
print(taxonomy.tag("genre.hip-hop").display_label("zh"))  # "嘻哈"
taxonomy.validate_tag_ids(["genre.rock.progressive-rock", "era.1990s"])
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
taxonomy/
  FORMAT.md                  taxonomy data format (schema_version 1)
  taxonomy-0.1.0-draft.json  v0 vocabulary from Taxonomy Proposal v0
src/musigtagger/
  contracts/                 immutable value types, provider protocol, taxonomy loader
  db/                        SQLite schema v1 + forward-only migration runner
tests/                       standard-library test suite
```

## Phase 1 status and boundaries

| Piece | Where | Status |
|---|---|---|
| Repo scaffold, contracts v1, taxonomy loader, schema v1 | this issue (MUSI-6) | delivered |
| Taxonomy v1.0.0 data | MUSI-5 | parallel |
| Library scanner + metadata suggestion provider | MUSI-7 | next stage |
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
