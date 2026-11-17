"""Phase 1 scanning, metadata suggestions, and batch orchestration."""

from .events import JsonlEventLogger
from .metadata import MetadataSuggestionProvider, PINNED_TAXONOMY_VERSION
from .network import (
    CachedLookup,
    MusicBrainzHttpTransport,
    MusicBrainzReleaseYearProvider,
    NetworkLookupError,
    NETWORK_YEAR_CONFIDENCE,
    ReleaseDateCache,
)
from .runner import BatchSuggestionResult, SuggestionRunner, TrackSuggestions
from .scanner import LibraryScanner, ScanBatchResult, ScanFailure

__all__ = [
    "BatchSuggestionResult",
    "CachedLookup",
    "JsonlEventLogger",
    "LibraryScanner",
    "MetadataSuggestionProvider",
    "MusicBrainzHttpTransport",
    "MusicBrainzReleaseYearProvider",
    "NETWORK_YEAR_CONFIDENCE",
    "NetworkLookupError",
    "PINNED_TAXONOMY_VERSION",
    "ReleaseDateCache",
    "ScanBatchResult",
    "ScanFailure",
    "SuggestionRunner",
    "TrackSuggestions",
]
