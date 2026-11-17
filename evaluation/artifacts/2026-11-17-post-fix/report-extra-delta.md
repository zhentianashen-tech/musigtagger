### Re-run delta vs the v0.1 prefix baseline (same frozen input)

| Run | Engine state | Suggestions | Instances with a suggestion | Usable instances | Accepted | Era suggestions |
|---|---|---|---|---|---|---|
| v0.1 prefix | `main` @ `1a92b2c` (no provider fix) | 5 | 5/47 (10.6%) | 5/47 (10.6%) | 0/5 (0.0%) | 0 |
| post-fix | `main` @ `ea40353` (carries `0a6e90a`) | 47 | 47/47 (100.0%) | 44/47 (93.6%) | 44/47 (93.6%) | 0 |

- The "Soda Pop" title-word accident is fixed: the stream contains **0** `genre.pop` suggestions. The five Soda Pop instances now receive `genre.k-pop` from the album and are accepted.
- All new coverage comes from one signal: `metadata.album` → `genre.k-pop` (the album title contains the `kpop` alias), confidence 0.60, on every one of the 47 instances.
- The provider still abstains on mood, activity, origin and the user-owned personal facet. Era abstains because no local date exists (see the local-date audit above), which is the honest-abstention branch of the binding requirement, not a miss.

### Local-date audit (binding requirement: a date present locally must become an era suggestion)

Audited every one of the 47 frozen instances, read-only, against all four local sources:

- Embedded date tags (`TDRC`, `TDRL`, `TDOR`, `TYER`, `date`, `year`): **0/47**.
- Year in filename: **0/47**.
- Year in embedded title: **0/47**.
- Year in embedded album: **0/47**.

Embedded tags present are exactly `TIT2` (title) 47/47, `TPE1` (artist) 47/47, `TALB` (album) 47/47, `APIC:Cover` 47/47, and `TSSE` (`encoder` tag written by the remux) 47/47; no genre, no date. Therefore **0 era suggestions is correct for this library**, and the engine's embedded-year → `era.<decade>s` path is covered by the new explicit test `test_embedded_release_date_always_surfaces_an_era` (full dates `1994-05-01`, `1994-05`, `1994` via `_parse_year`), not by this dataset.

### Path-dependence check

The 47 suggestions are all one tag (`genre.k-pop`) on one album; the 44 accepted instances collapse to 12 accepted works. The 93.6% / 85.7% figures are therefore evidence that the album signal works for this soundtrack set, not evidence of general genre precision. They should not be compared to the 75% proposal as if they measured the provider's performance across categories.
