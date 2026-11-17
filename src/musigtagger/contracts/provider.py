"""The provider interface every suggestion source implements.

Phase 1 ships a metadata provider (filenames + embedded tags). Phase 2 adds an
audio-analysis provider and Phase 3 a network-enrichment provider. All three
implement this exact protocol; adding a provider kind must not change the
engine/application interface.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .suggestion import TagSuggestion
from .track import TrackDescriptor


@runtime_checkable
class SuggestionProvider(Protocol):
    """Pure function from a track descriptor to zero or more suggestions.

    Contract (enforced by review and by the engine's conformance tests, not by
    the type system):

    * **Pure.** ``suggest`` must not read or write audio files, touch the
      network, write the database, or emit logs from inside the call. All I/O
      and event emission happens in the caller around the provider (see
      CONTRACTS.md, observability).
    * **Deterministic** for the same descriptor and pinned taxonomy version.
      If a provider cannot be deterministic it must not be used in Phase 1.
    * **Read-only.** The descriptor is an immutable value object; the provider
      returns suggestions and nothing else.
    * **Taxonomy-bound.** Every returned ``tag_id`` must exist in the pinned
      taxonomy version. Callers validate before persisting; providers should
      validate in their own tests.
    * **Honest confidence.** Low-information sources return low confidence
      rather than padding results.
    * **No UI concerns.** Ordering, grouping, filtering, and rendering belong to
      the review application, not the provider.

    Implementations do not need to inherit from this class; structural typing is
    deliberate so the engine can accept third-party providers.
    """

    def suggest(self, track_descriptor: TrackDescriptor) -> list[TagSuggestion]:
        """Return suggestions for ``track_descriptor`` (possibly an empty list)."""
        ...
