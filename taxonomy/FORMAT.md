# Taxonomy data format (schema version 1)

The taxonomy is **versioned data, not code**. This document is the schema the
`musigtagger.contracts.taxonomy` loader understands; it is owned by the
Application & Integration Engineer. Vocabulary content and version numbers are
owned by the Tag Taxonomy Designer.

- Canonical committed form: **JSON**, one document per frozen version, named
  `taxonomy/taxonomy-<version>.json` (for example
  `taxonomy/taxonomy-1.0.0.json`).
- YAML (`.yaml` / `.yml`) is read-only convenience support through the optional
  `musigtagger[yaml]` extra. It is never the canonical committed form.
- Consumers must load by pinned version; there is no "latest" API.

`taxonomy/taxonomy-0.1.0-draft.json` is the v0 document from Taxonomy Proposal
v0 (MUSI-3), encoded here so the loader is exercised.
`taxonomy/taxonomy-1.0.0.json` is the frozen Phase 1 vocabulary (MUSI-5) and is
the version consumers pin. It dropped in with **no schema change**: the loader
reads the version from the document, and `schema_version` stays `1`.
Both files coexist because discovery is by filename and selection is by the
pinned `version`, not by a "latest" ordering.

## Top-level document

```json
{
  "schema_version": 1,
  "version": "1.0.0",
  "name": "Music Tagger Taxonomy",
  "canonical_label_policy": "native-original-language",
  "facets": [ ... ],
  "tags": [ ... ]
}
```

| Field | Type | Required | Meaning |
|---|---|---|---|
| `schema_version` | integer | yes | Data-format version. Must be `1` for this loader. |
| `version` | string | yes | Vocabulary version, `MAJOR.MINOR.PATCH[-suffix]` (`0.1.0-draft`, `1.0.0`). This is what consumers pin. |
| `name` | string | yes | Human-readable taxonomy name. |
| `description` | string | no | Free-text purpose/scope note. Preserved by round-trip. |
| `canonical_label_policy` | string | no | How canonical labels were chosen. The approved policy is `native-original-language`: the native/original-language term is canonical (`Hip-hop`), competing terms are aliases (`Rap`). |
| `facets` | array | yes | At least one facet; see below. |
| `tags` | array | yes | At least one tag; see below. |

Unknown top-level fields are ignored by the loader. They are **not** a
migration mechanism: structural additions bump `schema_version`.

## Facet object

```json
{
  "id": "genre",
  "label": "Genre",
  "description": "What kind of music this is.",
  "phase1_available": true,
  "hierarchy": true,
  "max_depth": 2,
  "open_set": false
}
```

| Field | Type | Default | Rules |
|---|---|---|---|
| `id` | string | required | `^[a-z][a-z0-9-]*$`, unique. Facet ids are never user-created. |
| `label` | string | required | Non-empty display label. |
| `description` | string | `""` | Optional prose. |
| `phase1_available` | boolean | `true` | Whether the facet can receive suggestions from Phase 1 metadata. Empty-but-available is a valid state, not a broken one. |
| `hierarchy` | boolean | `false` | Whether tags in this facet may declare a `parent`. |
| `max_depth` | integer | `1` | Maximum tag depth. `1` = flat (root tags only), `2` = root + child. Must be `1` when `hierarchy` is false. |
| `open_set` | boolean | `false` | `true` for the `personal` facet: users create tags at runtime and the taxonomy does not enumerate them. An `open_set` facet cannot be hierarchical. |

## Tag object

```json
{
  "id": "genre.hip-hop",
  "facet": "genre",
  "canonical_label": "Hip-hop",
  "labels": { "en": "Hip-hop", "zh": "嘻哈" },
  "aliases": ["Hip Hop", "Rap"],
  "parent": null
}
```

| Field | Type | Default | Rules |
|---|---|---|---|
| `id` | string | required | `^[a-z][a-z0-9-]*(?:\.[a-z0-9][a-z0-9-]*)+$` and must start with `<facet>.`. Ids are stable across versions; renaming/removing one is a MAJOR taxonomy change. |
| `facet` | string | required | Must match a declared facet id. |
| `canonical_label` | string | required | Non-empty; the native/original-language term. Unique (case-insensitively) within its facet. |
| `labels` | object | required | At least one `language-tag -> label` entry. Values are non-empty. BCP-47-ish codes (`en`, `zh`, `de`) are recommended. Display layers pick a variant and fall back to `canonical_label`. |
| `aliases` | array of strings | `[]` | Non-empty strings, unique (case-insensitively) within the facet, and may not duplicate the tag's own canonical label. An alias maps to exactly one tag per facet and must not shadow another tag's canonical label. Aliases are stored in the taxonomy, **never on tracks**. |
| `parent` | string or null | `null` | Must be a tag id in the same hierarchical facet. Single parent, no cycles, depth ≤ the facet's `max_depth`. Parent imputation is a query-time rule, not a stored tag. |

Language tags for `origin` use the flat convention `origin.lang-<iso639-3>`
(`origin.lang-deu`, `origin.lang-nya`) so that language values are not confused
with the facet's region tree. The closed ISO 639-3 list is intentionally not
enumerated in v0; tags are added as used, which is a PATCH bump under the
taxonomy versioning rules.

## Loader behaviour and validation

`musigtagger.contracts.taxonomy.TaxonomyLoader`:

- `load(directory, *, version=...)` — **the consumer entry point**. Discovers
  the documents in `directory`, returns the one whose `version` is exactly
  `version`. Missing → `TaxonomyVersionMismatch`; two files with the same
  version → `TaxonomyVersionAmbiguous`. `version` is keyword-only and
  required; there is no unpinned overload.
- Discovery rule (exact): a file is considered only when it is a regular file
  whose stem **starts with `taxonomy-`** and whose suffix is `.json`, `.yaml`,
  or `.yml`. The filename is only a container — the version comes from the
  document — but the prefix is required: `taxonomy.json`, `v1-taxonomy-1.0.0.json`,
  and `taxonomy1.0.0.json` are **not** discovered. Name files
  `taxonomy-<version>.json`; anything else in the directory is ignored.
- `load_file(path)` — tooling/tests only. Loads a single document.
- `available_versions(directory)` — for diagnostics/configuration UIs.
- `dumps(taxonomy)` / `dump(taxonomy, path)` — canonical JSON serialisation.

The loader rejects, with `TaxonomyFormatError` (malformed document) or
`TaxonomyValidationError` (parsed but structurally invalid):

- unknown `schema_version`, malformed `version`, missing/empty fields;
- duplicate facet ids or tag ids;
- a tag whose `facet` does not exist or whose id is not namespaced under it;
- a `parent` that is unknown, in another facet, in a flat facet, cyclic, or
  deeper than the facet allows;
- duplicate canonical labels within a facet, duplicate aliases, or an alias
  that shadows another tag's canonical label;
- empty `labels`, or non-string/empty labels and aliases.

The loader does not evaluate semantic quality (whether a tag is a good idea,
whether an alias is linguistically right). That stays a taxonomy-review
decision.

### Known limitation: scheme-generated `origin.lang-<iso639-3>` ids

The `origin.lang-<iso639-3>` convention above is a *scheme*, and those ids are
not enumerated as tags by design. `Taxonomy.validate_tag_ids` checks membership
against the documents in this directory, so a scheme-generated language id is
rejected (`UnknownTagError`) even though it is well formed. This is a known
contract gap, not a loader defect: consuming such ids in suggestions or applied
tags requires a leader-approved **additive** contract change first. Nothing in
this document format needs to change to support it.

## Versioning

- The version is inside the document and never inferred from the filename.
- Adding a tag or alias: PATCH. Adding a facet: MINOR. Renaming/removing/
  remapping canonical tags or moving a node out of its root family: MAJOR.
- `schema_version` is independent of `version` and changes only when this
  document format changes.
- Every consumer persists the pinned taxonomy `version` (the application stores
  it in `library_meta.taxonomy_version`) and validates applied tags against it.
  A library on `1.0.0` must not silently accept a `1.1.0` tag id.
