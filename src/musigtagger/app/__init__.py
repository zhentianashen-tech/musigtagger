"""Music Tagger application layer: ingestion, review, tag writes, history.

This package is the **only** layer allowed to write audio files (CONTRACTS.md
§3). It consumes the frozen contracts in :mod:`musigtagger.contracts`, persists
review state in the SQLite schema v1, and emits the §4 event stream.

Boundaries:

* Suggestion logic belongs to the engine (``SuggestionProvider``). This package
  never classifies anything; it calls a provider and stores the claims.
* Taxonomy content belongs to the designer. This package loads the pinned
  version and validates every tag it persists or writes.
* Audio-file writes exist only in :mod:`musigtagger.app.writer`,
  :mod:`musigtagger.app.backup`, and :mod:`musigtagger.app.tagio`.
"""

from __future__ import annotations

from .config import AppConfig, ProtectedPathError
from .store import LibraryStore
from .tagmap import UnsupportedFacetError

__all__ = [
    "AppConfig",
    "LibraryStore",
    "ProtectedPathError",
    "UnsupportedFacetError",
]
