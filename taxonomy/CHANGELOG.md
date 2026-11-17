# Taxonomy changelog

All notable changes to the Music Tagger taxonomy. Every change from the previous version is
traceable to a **human decision** (D#, recorded on MUSI-2, 2026-11-17) or a **documented
refinement** (R#, designer judgment within the v0 proposal's own rules).

The format of this file: one section per released version, newest first.

## 1.0.0 — 2026-11-17 (frozen)

First frozen version. Supersedes `0.1.0-draft` (Taxonomy Proposal v0, MUSI-3).
Encoded as versioned data at `taxonomy/taxonomy-1.0.0.json` (`$.version` is the pin target).
Document schema is owned by `taxonomy/FORMAT.md` and the
`musigtagger.contracts.taxonomy` loader; this file is data, not a format spec.

### Loader-alignment re-encode (2026-11-17, same day; encoding only, no vocabulary change)

The first commit encoded the document in the designer's own README layout, which the
scaffold's `TaxonomyLoader` could not read. Re-encoded to `FORMAT.md` (schema_version 1)
after leader integration review. Version stays `1.0.0`: the encoding changed, the vocabulary
did not (same 160 tags, same rules). Changes:

- **Filename** `taxonomy.json` → `taxonomy-1.0.0.json` (loader discovers `taxonomy-*.json`).
- **Document `name` added** (required, non-empty); `id` kept as a document extension.
- **Facet fields mapped** to the loader contract: `key`→`id`, `question`→`description`, short
  `label` added; `structure`/`depth_cap`/`single_parent` folded into `hierarchy` + `max_depth`
  (tree→`hierarchy: true, max_depth: 2` for genre/origin; flat facets `max_depth: 1`;
  single-parent is enforced structurally by the loader, no longer restated);
  `phase1_availability` full/partial→`phase1_available: true`, none→`false`.
- **Tag ids `/` → `.`** (`genre/blues` → `genre.blues`, `era/1950s` → `era.1950s`; parents
  updated): the loader's tag-id regex requires dot-namespacing under the facet id. This was
  not in the reviewer's fix list but is required to load.
- **`canonical_label` added** per tag, set to `labels[native_language]` (the D3 rule itself);
  `native_language` retained as an extension field for provenance.
- **Aliases re-typed** `[{label, language}]` → plain strings (loader contract; supersedes R5 —
  the alias language annotation carried no matching semantics, and the competing-terms rule
  is already expressed by native-canonical labels).
- **One alias dropped**: `contemporary r&b` on `genre.contemporary-rhythm-and-blues`
  case-insensitively duplicated its own canonical label (`Contemporary R&B`), which the
  loader rejects and was redundant as a normalization input.
- **`naming_rules` updated** to defer to FORMAT.md: `tag_id_pattern` `<facet-id>.<slug>`;
  language-value convention aligned to the format's flat form `origin.lang-<iso639-3>`
  (pattern `^origin\.lang-[a-z]{3}$`); `personal` exception prefix reworded for dot ids.
- **README slimmed** to a pointer: format authority deferred to `FORMAT.md`; this directory
  documents only the vocabulary-policy extensions. `Taxonomy.dumps()` round-trips only
  loader-known keys, so the committed JSON file remains the canonical source.

### Human decisions applied

- **D1 — Six facets confirmed** (genre, mood, era, activity, origin, personal): all six facets
  ship in v1, including the `none`-availability facets (mood, activity) that stay empty under
  Phase 1 metadata-only operation. v0 had offered a thinner starter set as an option; not taken.
- **D2 — Genre hierarchy depth = 2, final:** the v0 cap of 2 levels is confirmed as permanent
  for the current major version. `depth_cap: 2` on `genre` is now a frozen constraint, not a
  proposal; depth-3 nodes are rejected until a MAJOR version revisits it.
- **D3 — Multilingual labels, native-language-canonical:** v1 adds the general labeling rule:
  where competing terms for one concept exist across languages, the native/original-language term
  is canonical and competing terms are aliases. Worked example (the human's own): `hip-hop`
  canonical, `Rap` an alias of it. v0 had asked (§7.5/§7.6) whether to merge Rap→hip-hop and
  whether to support multilingual display; both are now settled by this single general rule plus
  per-language `labels` variants.

### Structure

- Tags carry: `id` (originally `<facet>/<slug>`, re-encoded to `<facet>.<slug>` in the
  loader-alignment pass above), explicit `facet`, `parent` (genre/origin only, depth ≤ 2,
  single parent), `native_language`, `labels` (per-language display variants), `aliases`
  (originally `{label, language}`, re-typed to plain strings in the same pass).
- Facets carry: structure (`tree`/`flat`/`open`), `depth_cap`, cardinality guardrails, and
  per-phase availability marks (`phase1_availability` + Phase-2/Phase-3 outlook notes).
- `label_policy`, `naming_rules`, `versioning_policy` blocks encode v0 §3/§5 rules in
  machine-readable form (near-duplicate gates, minimum specificity, broad-before-narrow,
  query-time parent imputation, bump table, consumer pinning requirement).
- Seeded vocabulary: 160 tags — genre 97 (21 roots, 76 children, depth ≤ 2), mood 16, era 8
  (1950s–2020s), activity 10, origin 29 (region tree depth ≤ 2, incl. culture-level examples
  `brazil`, `jamaica`, `andalusia`); `personal` intentionally unseeded (open user set).
- `schema_version: 1` introduced, separate from the taxonomy version, so file-format tweaks do
  not consume taxonomy version semantics.

### Documented refinements (designer judgment, consistent with v0 rules)

- **R1 — Mood cardinality 1–4 → 0–4** (v0 §2 said 1–4): a facet that is legitimately empty under
  Phase 1 cannot require a minimum of 1 per track. The v0 number was written before D1 confirmed
  empty-under-A facets ship.
- **R2 — Era cardinality "exactly 1" → 0–1:** tracks with no parsable release date and no
  filename year get no era tag; forcing one would violate the no-guessing rule (v0 §3).
- **R3 — Origin tree child policy made explicit:** children of a region root are subregions
  *or* specific countries/cultures at the same depth (both at depth 2), keeping the depth ≤ 2
  cap intact for culture-level entries such as `brazil` or `andalusia`.
- **R4 — Multilingual demonstration nodes:** `bossa-nova` (pt), `enka` (ja), `bhangra` (pa),
  `qawwali` (ur), `andalusia`/`brazil` (native labels) included to exercise the D3 rule on real
  non-English-native terms; a handful of common genres carry ja/ko display variants to exercise
  `labels`.
- **R5 — `aliases` typed as `{label, language}` objects** rather than bare strings, so a
  competing term's language is recorded (required to express D3 generally, e.g. a Spanish
  synonym aliasing an English-canonical tag). *Superseded in the loader-alignment pass:
  aliases are bare strings per FORMAT.md; the language annotation carried no matching
  semantics.*

### Rules carried over from v0 unchanged

Naming/alias rules (slug charset, singular, facet-prefixed ids, aliases stored off-track,
unmapped-inputs review path), hierarchy rules (single parent, strict-subset parent/child,
query-time parent imputation, no cycles), versioning bump table, per-facet Phase-1 availability
marks (genre 🟡, mood 🔴, era 🟢, activity 🔴, origin 🟡, personal 🟢). The `texture` facet
deliberately remains absent from the file; adding it for Phase 2 would be a MINOR bump.

### Still open (carried from v0 §7, unanswered; v0 defaults in force)

- ID3v1 numeric genre code handling (proposal stands: map standard 0–79 to canonical tags,
  Winamp extensions 80–147 go to the review queue as unmapped).
- Query-time parent imputation accepted by default; the human has not objected, but it remains
  reversible within MINOR semantics.
- Starter mood/activity vocabulary stands as-is, revisable from real usage (PATCH-level adds;
  human may curate later).

### Compatibility implications for downstream

- Engine (MUSI-7) and application (MUSI-8) pin `1.0.0` and refuse other versions.
- Scaffold loader (MUSI-6) must accept scheme-generated `origin.lang-<iso639-3>` ids in
  addition to enumerated tags at validation time, and must expose `$.version`. (Exposure
  is delivered; runtime acceptance of scheme-valid language ids remains open — enumerated
  `origin.*` tags only cover regions, not languages.)
- Migration trustworthiness requires tag stores to record the taxonomy version in force at
  write time (routed to the contracts spec).
- The Rap→hip-hop resolution means ID3 genre strings "Rap", "Hip Hop", "Hip-Hop/Rap" all
  normalize to `genre.hip-hop`; normalizers should treat them as one concept.

## 0.1.0-draft — 2026-11-17

Taxonomy Proposal v0 (MUSI-3). Document-only; never encoded as data. Proposed the six facets,
depth-2 genre cap, naming/alias rules, query-time parent imputation, MAJOR.MINOR.PATCH bump
policy, and per-facet Option-A availability marks; §7 listed the open questions resolved by
D1–D3 above.
