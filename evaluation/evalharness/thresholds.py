"""Proposed acceptance thresholds (Evaluation Plan v0.1 §3).

These are *proposals for operator approval* — nothing here is settled. Every
generated report carries ``STATUS_LABEL`` next to each threshold comparison.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Required label on every threshold comparison in every report.
STATUS_LABEL = "PROPOSED — pending human sign-off"

#: Plan version this threshold set belongs to.
PLAN_VERSION = "0.1"


@dataclass(frozen=True)
class Thresholds:
    """The plan-v0.1 proposed acceptance bar."""

    suggestion_precision_min: float = 0.75  # overall; per-category reported with counts
    coverage_min: float = 0.85  # tracks receiving >= 1 usable tag
    batch_completion_min: float = 1.0  # no mid-batch crash/abort (gating)
    taxonomy_conformance_min: float = 1.0  # applied/suggested ids valid, genre depth <= 2
    source_writes_max: int = 0  # writes under the protected source root
    corruption_incidents_max: int = 0  # failed writes/undos on working copies
    undo_success_min: float = 1.0  # undo restores prior state, every sampled case


DEFAULT_THRESHOLDS = Thresholds()
