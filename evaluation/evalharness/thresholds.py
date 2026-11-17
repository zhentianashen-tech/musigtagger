"""Operator-approved acceptance thresholds (Evaluation Plan v0.1 §3).

Approved **as-is** by the operator on 2026-11-17 (MUSI-9 comment
``01a1e957-d274-7627-a3ae-33d40e231a98``); no value changed at approval. Every
generated report carries ``STATUS_LABEL`` next to each threshold comparison.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Required label on every threshold comparison in every report.
STATUS_LABEL = "APPROVED — operator sign-off 2026-11-17"

#: Plan version this threshold set runs under (v0.2 amends ground truth only;
#: the threshold values are the v0.1 set, approved unchanged).
PLAN_VERSION = "0.2"


@dataclass(frozen=True)
class Thresholds:
    """The operator-approved acceptance bar (values unchanged from the v0.1 proposal)."""

    suggestion_precision_min: float = 0.75  # overall; per-category reported with counts
    coverage_min: float = 0.85  # tracks receiving >= 1 usable tag
    batch_completion_min: float = 1.0  # no mid-batch crash/abort (gating)
    taxonomy_conformance_min: float = 1.0  # applied/suggested ids valid, genre depth <= 2
    source_writes_max: int = 0  # writes under the protected source root
    corruption_incidents_max: int = 0  # failed writes/undos on working copies
    undo_success_min: float = 1.0  # undo restores prior state, every sampled case


DEFAULT_THRESHOLDS = Thresholds()
