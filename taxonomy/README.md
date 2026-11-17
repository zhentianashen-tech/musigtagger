# Taxonomy

Music Tagger tag taxonomy — versioned structured data. **Current version: `1.0.0` (frozen).**
Downstream layers (taxonomy loader, engine, application, evaluation) must pin `1.0.0` and refuse
to run against versions outside their supported set.

This directory is data and specification only. The loader/validator implementation lives with the
scaffold/contracts work (MUSI-6); engine internals do not belong here.

## Files

| File | Purpose |
|---|---|
| `taxonomy.json` | The taxonomy: version, facets, tags, labeling/naming/versioning rules. |
| `CHANGELOG.md` | Version history; every change traceable to a human decision or a documented refinement. |

## Format choice: JSON

JSON was chosen over YAML because: it needs no third-party parser (Python `json` is stdlib, and
the approved stack is Python), it has exactly one canonical form, and the version string must be
machine-readable — `$.version` is the pinned value.

Top-level shape (`schema_version` describes the *file format*, so format tweaks do not consume a
taxonomy version bump):

```
schema_version      1 — format of this file
id                  "music-tagger-taxonomy"
version             "1.0.0"  ← the string downstream must pin
status              "frozen" | "draft"
supersedes          "0.1.0-draft"
label_policy        native-language-canonical rules (see below)
naming_rules        id pattern, slug charset, near-duplicate gates, parent imputation
versioning_policy   bump rules + pinning requirement
facets[]            six facets: key, structure, depth_cap, cardinality, availability marks
tags[]              tag records (see below)
```

Tag record:

```
id                 "<facet-key>/<slug>", globally unique (e.g. "genre/progressive-rock")
facet              one of the six facet keys (explicit, even though the id embeds it)
parent             id of parent tag, or null (genre and origin only; depth ≤ 2, single parent)
native_language    language whose label is canonical (BCP-47/ISO tag; default "en")
labels             {language: display label} — labels[native_language] is THE canonical label;
                   other entries are display-only variants and never create tag identity
aliases            [{label, language}] — normalization inputs mapped to this tag on write;
                   never stored on tracks; each alias maps to exactly one canonical tag
```

The `personal` facet has no seeded tags: it is user free-form under the `personal/` prefix
(≤ 40 chars after the prefix), exempt from slug rules and near-duplicate gates.
The `origin` facet additionally accepts scheme-generated language values
`origin/language:<iso-639-3>` (not enumerated in `tags`; validate against
`naming_rules.language_value_pattern`). **Note for the loader (MUSI-6):** conformance checking
must accept scheme-valid `origin/language:xxx` ids in addition to enumerated tag ids.

## Labeling rules (v1 additions from the human decisions, MUSI-2 2026-11-17)

1. **Native-language-canonical (general rule):** where competing terms for the same concept exist
   in different languages, the term originating in the concept's own language or culture is
   canonical; competing terms in other languages become aliases. Worked example: `genre/hip-hop`
   is canonical; `rap` is its alias — a tag exists for the concept, not per language.
2. **Multilingual display variants:** `labels` may carry per-language display strings. They are
   display-only; ingestion normalization matches ids and aliases only.
3. **Aliases are stored off-track:** they live only in this file and are normalized to the
   canonical id at write time.

## Availability marks

Each facet carries `phase1_availability` (`full` / `partial` / `none`) — how well Phase 1
(metadata-only, local-only) can fill it — plus Phase-2 (audio) and Phase-3 (network) outlook
notes. `none` facets (mood, activity) are *available but unfilled* in Phase 1, never broken;
no tag's format depends on how it was derived.

## Change process

Taxonomy edits are owned by the Tag Taxonomy Designer. Every edit bumps `version` per
`versioning_policy.bump_rules` and gets a `CHANGELOG.md` entry. Adding facets beyond the six
frozen ones requires escalation to the Lead Architect (MUSI-2 scope decision).
