"""Tag suggestions: the engine's output value object.

A suggestion is a *claim* about a track, never a write. It is immutable and
self-describing: every suggestion says which tag it proposes, how confident the
provider is, which provider produced it, and why (evidence). Evaluation and the
review UI both consume this same object.

See CONTRACTS.md, "Engine contract".
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TagSuggestion:
    """One proposed taxonomy tag for one track.

    Parameters
    ----------
    tag_id:
        A tag id that must exist in the taxonomy version pinned for the run.
        The provider does not get to invent tags outside the taxonomy.
    confidence:
        Provider confidence in ``[0.0, 1.0]``. Required: a provider that cannot
        estimate confidence must say so explicitly (e.g. ``0.0``) rather than
        omit it.
    source:
        Stable identifier of the provider that produced the suggestion, e.g.
        ``"metadata.filename"`` or ``"metadata.embedded"``. Source is stored and
        logged so evaluation can compare providers.
    evidence:
        Human-readable, specific justification (``"ID3 TCON='Alt. Rock'"``,
        ``"filename artist/album/01 - Title.mp3"``). Never empty: an unexplained
        suggestion is not reviewable.

    The type is hashable, so a suggestion can be kept in sets or emitted to a
    log without a mutable alias.
    """

    tag_id: str
    confidence: float
    source: str
    evidence: str

    def __post_init__(self) -> None:
        for name in ("tag_id", "source", "evidence"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string")
            object.__setattr__(self, name, value.strip())
        confidence = self.confidence
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
            raise TypeError(f"confidence must be a number, got {type(confidence).__name__}")
        if not math.isfinite(confidence) or not 0.0 <= float(confidence) <= 1.0:
            raise ValueError(
                f"confidence must be between 0.0 and 1.0, got {confidence!r}"
            )
        object.__setattr__(self, "confidence", float(confidence))
