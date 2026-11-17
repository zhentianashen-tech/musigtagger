"""Shared contract types for Music Tagger.

Everything in this subpackage is an interface: value objects, protocols, and
validation that consumers may rely on. It contains no tagging logic and must
never perform file I/O against audio files, network I/O, or UI work.

Contract documents: ``CONTRACTS.md`` (root) and ``taxonomy/FORMAT.md``.
"""

from __future__ import annotations

from .errors import (
    ContractError,
    TaxonomyError,
    TaxonomyFormatError,
    TaxonomyValidationError,
    TaxonomyVersionAmbiguous,
    TaxonomyVersionMismatch,
    UnknownTagError,
)
from .provider import SuggestionProvider
from .suggestion import TagSuggestion
from .taxonomy import (
    SCHEMA_VERSION,
    Taxonomy,
    TaxonomyFacet,
    TaxonomyLoader,
    TaxonomyTag,
)
from .track import AudioFeatures, TrackDescriptor

__all__ = [
    "AudioFeatures",
    "ContractError",
    "SCHEMA_VERSION",
    "SuggestionProvider",
    "TagSuggestion",
    "Taxonomy",
    "TaxonomyError",
    "TaxonomyFacet",
    "TaxonomyFormatError",
    "TaxonomyLoader",
    "TaxonomyTag",
    "TaxonomyValidationError",
    "TaxonomyVersionAmbiguous",
    "TaxonomyVersionMismatch",
    "TrackDescriptor",
    "UnknownTagError",
]
