# Music Tagger — Shared Contracts v1

**Status:** v1, Phase 1 interface freeze. **Scope:** metadata-only, local-only
tagging with human review. Audio analysis (Phase 2) and network enrichment
(Phase 3) are future **providers behind the engine interface defined here** —
they are not part of Phase 1.

This document is the agreement between the three layers and the external
evaluation harness:

| Layer | Owner | Can write audio files? | Can change the taxonomy? |
|---|---|---|---|
| Taxonomy | Tag Taxonomy Designer | no | yes (versioned, via review) |
| Tagging engine | Tagging Engine Engineer | **no** | no |
| Application / integration | Application & Integration Engineer | **yes, sole writer** | no |
| Evaluation harness | Evaluation & Review Agent | no | no |

If an interface here is missing or unsuitable, propose a concrete change to the
Lead Architect and the affected specialist. Do not silently change a contract,
and do not duplicate another layer's work to get around one.

Code references:

- `src/musigtagger/contracts/` — value types, provider protocol, taxonomy loader.
- `src/musigtagger/db/schema_v1.sql` — SQLite schema v1.
- `src/musigtagger/db/migrations.py` — migration runner and version marker.
- `taxonomy/FORMAT.md` — taxonomy data format.

---

## 1. Taxonomy contract

**The taxonomy is versioned data, not code.** It defines the closed vocabulary
of tag ids a library may contain.

Required properties:

1. **Versioned.** Every taxonomy document carries an explicit `version`
   (`MAJOR.MINOR.PATCH[-suffix]`, e.g. `0.1.0-draft`, `1.0.0`). Version bumps
   follow the rules in `taxonomy/FORMAT.md`; renaming or removing a canonical
   tag is a MAJOR change because stored tags must be remapped.
2. **Versioned data, read-only to non-designers.** Engine and application code
   read the taxonomy; they never add, rename, or reparent tags at runtime.
   Vocabulary gaps are reported back to the designer/leader, not patched in
   application code.
3. **Loaded through one loader.** `musigtagger.contracts.taxonomy.TaxonomyLoader`
   is the only supported reader. The in-memory `Taxonomy` object is immutable
   and exposes `version`, facet/tag lookups, and validation helpers.
4. **Consumers pin the loaded version.** Loading by pinned version is
   structural: `TaxonomyLoader.load(directory, version=...)` has no unpinned
   variant. The application records the pin in
   `library_meta('taxonomy_version')`; every run that emits or applies tags
   carries that version in its database rows and evaluation events.
5. **Tag references are validated.** A tag id that is not in the pinned
   version is an error (`UnknownTagError`), never a new tag. This applies to
   suggestions before persistence and to applied tags before any write.
6. **v0 → v1 drop-in.** The v0 document (`0.1.0-draft`) and the frozen v1
   document use the same `schema_version: 1` structure. Freezing v1 adds a new
   file and a new version string; it must not require a loader or SQLite schema
   change.
7. **Multilingual and alias rules live in the data.** Canonical labels follow
   the approved native/original-language policy; aliases map to exactly one
   canonical tag per facet. Nothing about provenance (which provider proposed a
   tag) belongs in the taxonomy — it belongs to suggestions and events.

The taxonomy does **not** decide suggestion logic, confidence thresholds, or
which provider to use. Those are engine concerns.

---

## 2. Engine contract (tagging providers)

The engine turns a `TrackDescriptor` into zero or more `TagSuggestion`s.

```python
class SuggestionProvider(Protocol):
    def suggest(self, track_descriptor: TrackDescriptor) -> list[TagSuggestion]: ...
```

Required properties:

1. **Pure suggestion function.** `suggest` performs no audio-file writes, no
   tag writes, no database writes, no network calls, and no UI work. It reads
   only the descriptor it is given. Persistence, logging, and review-queue
   updates happen in the caller around the provider.
2. **Same interface for every provider kind.** The Phase 1 metadata provider,
   Phase 2 audio provider, and Phase 3 network provider all implement
   `SuggestionProvider`. Adding a provider must not change this interface or
   the application's contract.
3. **Every suggestion carries `source` and `confidence`.** `source` is a stable
   provider identifier; `confidence` is a number in `[0.0, 1.0]`. Omitting
   either is a contract violation; a low-information provider reports low
   confidence rather than padding results.
4. **Every suggestion carries `evidence`.** A specific, human-readable
   justification (`"ID3 TCON='Alt. Rock'"`, `"filename artist/album/01 - Title.mp3"`).
   The review UI and evaluation both need it; an unexplained suggestion is not
   reviewable.
5. **Taxonomy-bound.** Every `tag_id` must exist in the taxonomy version pinned
   for the run. Providers do not invent tags and do not write `personal/` tags
   on the user's behalf.
6. **Deterministic per (descriptor, pinned taxonomy).** Same input, same
   output. Non-determinism makes evaluation and undo reasoning impossible.
7. **No UI concerns.** Ordering, grouping, thresholds, and presentation belong
   to the review application.
8. **Immutable value types.** `TrackDescriptor`, `AudioFeatures`,
   `TagSuggestion`, `Taxonomy`, `TaxonomyFacet`, and `TaxonomyTag` are frozen.
   Providers must not try to mutate their inputs.
9. **Phase 2 seam only.** `TrackDescriptor.features` is the reserved optional
   slot for audio analysis. Phase 1 providers receive `None` and must not
   require features. Nothing else about the interface changes for Phase 2.

Engine outputs are *claims*, not state. The application decides what to store,
show, or apply.

---

## 3. Application contract (the sole writer)

The application/integration layer owns ingestion, persistence, review, and tag
writes. It is the **only** component allowed to modify audio files.

Non-negotiable properties:

1. **Sole writer.** No engine/provider code path may open an audio file for
   writing. The engine emits suggestions; the application maps accepted tags to
   tag frames and writes them.
2. **Mandatory backup before any write batch.** Before the first byte of a
   batch is written, the application stores the complete prior tag state for
   every target track in `tag_backups` (and, for defence in depth, a sidecar
   copy of the tag payload under the batch's backup location). A batch may not
   start if any target's backup is missing. `write_batches.status` is
   `pending` → `completed`/`failed`; a failed batch keeps its backups.
3. **Undo restores prior tags exactly.** Undo is a first-class operation that
   restores the backed-up tag frame data for every track in the batch and marks
   the backups `restored_at`. "Byte-equivalent for the tag frame data" is the
   acceptance bar; a best-effort rewrite of parsed fields is not enough.
4. **Applied tags validate against the pinned taxonomy.** The application
   resolves `library_meta('taxonomy_version')` and validates every tag it is
   about to write, plus every tag already recorded as applied. An unknown tag
   id aborts the batch before any file is touched. The application never
   silently drops or invents a tag during migration.
5. **Review state machine.** The five states are
   `suggested → accepted | edited | rejected → applied`.
   `suggested`, `accepted`, `edited`, `rejected` and `applied` are exactly the
   values enforced by `suggestions.status`. `accepted`/`edited`/`applied`
   carry the effective tag in `final_tag_id`; `rejected` carries none.
   `applied` also requires `applied_at`.
6. **Partial failure is explicit and recoverable.** A batch that fails on track
   *n* is marked `failed`, keeps its backups, and records what completed. The
   user can retry the remainder or undo the completed part. No code path may
   leave a file half-written without a recorded backup.
7. **User input and errors are surfaced.** Malformed/unreadable files are
   skipped with a logged reason, not silently dropped; unknown taxonomy ids and
   backup failures are hard errors; undo failures are reported per track with
   the file left in a valid state.
8. **Review outcomes are persisted and logged.** Status transitions and their
   timestamps are stored in SQLite; the same outcomes are emitted to the
   external event stream (§4) so evaluation does not have to read the app's
   database internals.
9. **No taxonomy or engine mutation.** The application does not add tags, relax
   validation, or reimplement suggestion logic. If the taxonomy is wrong, it
   escalates.

Schema v1 (`src/musigtagger/db/schema_v1.sql`) supplies the storage for all of
the above: `tracks`, `suggestions` (five review states, `final_tag_id`,
`applied_at`), `write_batches`, `tag_backups`, `library_meta`, and the
`schema_migrations` / `PRAGMA user_version` marker. Changes after v1 are
escalated, not slipped into a feature branch.

---

## 4. Evaluation observability contract

Evaluation is **outside** the engine and must stay there. It consumes an event
stream that the application and engine-runner emit around the pure
`suggest()` call. The engine must not know about evaluation, and evaluation must
not require engine changes to run.

Two event families are mandatory:

- **Suggestion events** — every suggestion a provider emits, with track
  identity, `tag_id`, `confidence`, `source`, `evidence`, `taxonomy_version`,
  and the engine run id.
- **Review-outcome events** — every accept/edit/reject/apply/undo decision,
  with the previous and new state, the effective tag id, the deciding actor (or
  `local-user`), and a timestamp.

Recommended event envelope (JSON Lines, one object per line, written outside
the pure provider call):

```json
{
  "event": "suggestion",
  "event_version": 1,
  "occurred_at": "2026-11-17T07:30:00.000Z",
  "run_id": "run-20261117-073000-abc123",
  "taxonomy_version": "1.0.0",
  "track": { "path": "/music/a/b.flac", "format": "flac" },
  "tag_id": "genre.hip-hop",
  "confidence": 0.72,
  "source": "metadata.embedded",
  "evidence": "Vorbis GENRE='Hip Hop'"
}
```

```json
{
  "event": "review_outcome",
  "event_version": 1,
  "occurred_at": "2026-11-17T07:32:11.000Z",
  "run_id": "run-20261117-073000-abc123",
  "taxonomy_version": "1.0.0",
  "track_path": "/music/a/b.flac",
  "suggestion_id": 42,
  "from_status": "suggested",
  "to_status": "edited",
  "original_tag_id": "genre.hip-hop",
  "final_tag_id": "genre.hip-hop.trap",
  "actor": "local-user"
}
```

Requirements:

1. **Loggable outside the engine.** The emitter lives in the engine runner or
   application, never inside `suggest()`. A provider that cannot emit events is
   still conformant; the caller supplies the event.
2. **Complete enough for metrics.** Suggestion precision (accepted / emitted),
   coverage (tracks with ≥1 accepted tag), correction burden (edits per track),
   taxonomy conformance (unknown ids = 0), and safety events (apply/undo
   failures) must all be derivable without reading application internals.
3. **Stable identifiers.** `run_id`, `track.path`, `source`, and
   `taxonomy_version` are mandatory. Paths may be hashed or redacted only if
   the mapping is available to the evaluation run.
4. **Local-only by default.** Phase 1 emits events to a local file. Network
   export is a Phase 3 concern and is off by default.
5. **No behaviour change.** Enabling or disabling event emission must not
   alter suggestions, review state, or writes.

The event format may evolve additively (`event_version`); removing or renaming
a required field is a contract change.

---

## 5. Versioning and change control

| Contract | Version marker | Change process |
|---|---|---|
| Taxonomy | `version` inside the taxonomy document | Designer owns content; bump per `taxonomy/FORMAT.md`; freezing v1.0.0 is a reviewed deliverable |
| Data format | `schema_version` inside the taxonomy document | Bump only with a loader migration |
| Engine interface | this document + `contracts/` | Proposal to Lead Architect + affected specialist; downstream tests must be updated in the same change |
| SQLite schema | `PRAGMA user_version` + `schema_migrations` | Forward-only migration; **after v1 escalate before merging** |

Compatibility rule: adding optional fields is allowed; changing a field's
meaning, making an optional field required, or removing a field is a contract
version change. A newer database refuses to open in an older application
(`SchemaVersionError`) rather than guessing.

---

## 6. Conformance and tests

The scaffold's tests are the executable part of this document:

- `tests/test_contract_types.py` — immutability and validation of
  `TrackDescriptor`, `AudioFeatures`, `TagSuggestion`, and the provider
  protocol.
- `tests/test_taxonomy_loader.py` — v0 load, version reporting, pinning,
  round-trip, v1.0.0 drop-in, and rejection of invalid taxonomies.
- `tests/test_db_schema.py` — schema v1 version marker, migration idempotency,
  review-state and confidence constraints, backup/undo tables, foreign keys.

Run them with `python -m unittest discover -s tests -v` (no third-party test
dependency) or `pytest` when the dev extra is installed.

---

## 7. Explicitly out of scope for v1

- Suggestion/classification logic and confidence thresholds.
- Review UI and any web framework choice.
- Tag-writing, backup/undo implementation (the contract and schema exist; the
  implementation is MUSI-8).
- Audio analysis and network providers.
- Evaluation metrics and harness implementation.
- `personal/` tag governance beyond the namespace rule.
