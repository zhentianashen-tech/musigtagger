"""Deterministic suggestions from existing metadata, filenames, and paths."""

from __future__ import annotations

import re
from collections.abc import Iterable

from musigtagger.contracts import (
    SuggestionProvider,
    TagSuggestion,
    Taxonomy,
    TaxonomyTag,
    TrackDescriptor,
)

PINNED_TAXONOMY_VERSION = "1.0.0"
_WORD_RE = re.compile(r"[^\w]+", re.UNICODE)
_YEAR_RE = re.compile(r"(?<!\d)((?:19|20)\d{2})(?!\d)")


def _normalise(value: str) -> str:
    return " ".join(_WORD_RE.sub(" ", value.casefold()).split())


def _labels(tag: TaxonomyTag) -> Iterable[str]:
    yield tag.canonical_label
    yield from tag.labels.values()
    yield from tag.aliases


def _contains_label(path_text: str, label: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(label)}(?!\w)", path_text) is not None


class MetadataSuggestionProvider(SuggestionProvider):
    """Map explicit metadata and conservative path patterns onto taxonomy tags.

    Embedded genre/date matches are high-confidence. Filename/path matches are
    deliberately lower-confidence. Facets marked unavailable for Phase 1 and
    the user-owned ``personal`` facet never receive automatic suggestions.
    """

    def __init__(self, taxonomy: Taxonomy) -> None:
        taxonomy.require_version(PINNED_TAXONOMY_VERSION)
        self.taxonomy = taxonomy
        aliases: dict[str, list[tuple[str, TaxonomyTag]]] = {}
        for tag in taxonomy.tags:
            if tag.facet == "personal" or not taxonomy.facet(tag.facet).phase1_available:
                continue
            labels = {_normalise(label) for label in _labels(tag)}
            labels.discard("")
            aliases.setdefault(tag.facet, []).extend(
                (label, tag) for label in labels
            )
        # Longest first makes evidence selection stable when labels overlap.
        self._aliases = {
            facet: tuple(
                sorted(values, key=lambda item: (-len(item[0]), item[0], item[1].id))
            )
            for facet, values in aliases.items()
        }

    def suggest(self, track_descriptor: TrackDescriptor) -> list[TagSuggestion]:
        suggestions: dict[str, TagSuggestion] = {}

        def add(suggestion: TagSuggestion) -> None:
            previous = suggestions.get(suggestion.tag_id)
            if previous is None or suggestion.confidence > previous.confidence:
                suggestions[suggestion.tag_id] = suggestion

        if track_descriptor.genre:
            raw_genre = track_descriptor.genre.strip()
            candidates = [raw_genre]
            candidates.extend(
                part.strip()
                for part in re.split(r"\s*[;,/]\s*", raw_genre)
                if part.strip() and part.strip() != raw_genre
            )
            for candidate in candidates:
                match = self._exact_match("genre", candidate)
                if match is not None:
                    add(
                        TagSuggestion(
                            tag_id=match.id,
                            confidence=0.95,
                            source="metadata.embedded",
                            evidence=f"Embedded GENRE={candidate!r}",
                        )
                    )

        if track_descriptor.year is not None:
            era = self._era_for_year(track_descriptor.year)
            if era is not None:
                add(
                    TagSuggestion(
                        tag_id=era,
                        confidence=0.98,
                        source="metadata.embedded",
                        evidence=f"Embedded release year={track_descriptor.year}",
                    )
                )

        path = track_descriptor.path
        normalised_path = _normalise(path)
        for facet, confidence in (("genre", 0.55), ("origin", 0.30)):
            for label, tag in self._aliases.get(facet, ()):
                if _contains_label(normalised_path, label):
                    add(
                        TagSuggestion(
                            tag_id=tag.id,
                            confidence=confidence,
                            source="metadata.path",
                            evidence=f"Path {path!r} contains {tag.canonical_label!r}",
                        )
                    )

        if not any(tag_id.startswith("era.") for tag_id in suggestions):
            years = [int(value) for value in _YEAR_RE.findall(path)]
            if len(set(years)) == 1:
                era = self._era_for_year(years[0])
                if era is not None:
                    add(
                        TagSuggestion(
                            tag_id=era,
                            confidence=0.65,
                            source="metadata.filename",
                            evidence=f"Path {path!r} contains release year {years[0]}",
                        )
                    )

        return list(suggestions.values())

    def _exact_match(self, facet: str, value: str) -> TaxonomyTag | None:
        normalised = _normalise(value)
        for label, tag in self._aliases.get(facet, ()):
            if normalised == label:
                return tag
        return None

    def _era_for_year(self, year: int) -> str | None:
        tag_id = f"era.{year // 10 * 10}s"
        return tag_id if self.taxonomy.has_tag(tag_id) else None
