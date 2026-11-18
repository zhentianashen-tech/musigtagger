# SUPERSEDED

This v0.2 baseline artifact set is **superseded** and no longer the default
Phase-1 baseline. It is kept for audit history only — do not delete it.

**Superseded by:** `../2026-11-18-v0.3-baseline/` (era recall measured at
47/47 on merged `main` after the MUSI-14 era-lookup fix `d50a813`).

**Why:** the v0.2 report records era recall **0/47** because it was generated
*before* the MUSI-14 fix. The live engine on `main` measures era recall
**47/47 (100%)**, so the v0.2 numbers no longer describe the checked-in
engine. See `../2026-11-18-v0.3-baseline/RUN.md` for the superseding run and
the current reproduce command.

The precision / coverage / batch / conformance / safety numbers here remain
valid (they measure the local provider and safety path, which did not change),
but any Phase-1 acceptance claim must use the v0.3 baseline for the era number.
