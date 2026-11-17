# Taxonomy

Music Tagger tag taxonomy — versioned structured data. **Current version: `1.0.0` (frozen).**
Downstream layers (loader, engine, application, evaluation) must pin `1.0.0` via
`TaxonomyLoader.load(directory, version='1.0.0')` and refuse versions outside their
supported set.

This directory is data and policy only. Loader/schema implementation lives in
`src/musigtagger/contracts/taxonomy.py` (scaffold, MUSI-6).

## Files

| File | Purpose |
|---|---|
| `taxonomy-1.0.0.json` | The v1.0.0 taxonomy document. Named per the loader's `taxonomy-<version>.json` discovery pattern. |
| `CHANGELOG.md` | Version history; every change traceable to a human decision or a documented refinement. |

## Document format

The schema of these files is **owned by [`FORMAT.md`](FORMAT.md)** (schema_version 1) and
enforced by `musigtagger.contracts.taxonomy`. This README does not restate it. The format
choice itself (canonical committed form = JSON, one document per frozen version) is also
defined there.

## Vocabulary policy extensions

Beyond the loader-known fields, each document carries three policy blocks that the loader
tolerates as extensions but does not interpret. They are the designer-owned semantics of
the vocabulary:

- `label_policy` — native-original-language canonical rule, alias handling, unmapped-input
  review path. The loader's `canonical_label_policy: "native-original-language"` field is
  the machine-readable marker of this policy.
- `naming_rules` — slug charset, near-duplicate gates, minimum specificity, broad-before-
  narrow, query-time parent imputation, scheme-generated `origin.lang-<iso639-3>` values.
- `versioning_policy` — bump table and the consumer pinning requirement.

Facet and tag records also carry extension fields the loader ignores (cardinality
guardrails, phase outlook notes, `native_language`). These matter: **`Taxonomy.dumps()`
round-trips only loader-known keys, so a loader dump is lossy — the committed JSON file is
the canonical source, not any serialized `Taxonomy` object.**

## Change process

Taxonomy edits are owned by the Tag Taxonomy Designer. Every edit bumps `version` per
`versioning_policy.bump_rules` and gets a `CHANGELOG.md` entry. Adding facets beyond the
six frozen ones requires escalation to the Lead Architect (MUSI-2 scope decision).
