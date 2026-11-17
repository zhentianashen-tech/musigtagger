"""Deterministic suggestions from existing metadata, filenames, and paths."""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Callable

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

# Confidence per signal, ordered strongest to weakest. The embedded tag always
# wins; free-text signals are graded by how deliberately the text was chosen
# (a genre folder beats an album name beats an artist name beats a title word).
_EMBEDDED_GENRE_CONFIDENCE = 0.95
_EMBEDDED_YEAR_CONFIDENCE = 0.98
_FOLDER_GENRE_CONFIDENCE = 0.55
_FOLDER_ORIGIN_CONFIDENCE = 0.30
_ALBUM_GENRE_CONFIDENCE = 0.60
_ALBUM_ORIGIN_CONFIDENCE = 0.30
_ARTIST_GENRE_CONFIDENCE = 0.50
_ARTIST_ORIGIN_CONFIDENCE = 0.25
_TITLE_GENRE_CONFIDENCE = 0.30
_FOLDER_YEAR_CONFIDENCE = 0.65
_ALBUM_YEAR_CONFIDENCE = 0.55
_TITLE_YEAR_CONFIDENCE = 0.40


def _normalise(value: str) -> str:
    return " ".join(_WORD_RE.sub(" ", value.casefold()).split())


def _labels(tag: TaxonomyTag) -> Iterable[str]:
    yield tag.canonical_label
    yield from tag.labels.values()
    yield from tag.aliases


def _is_generic_label(label: str, tag: TaxonomyTag) -> bool:
    """A bare single-word English canonical label such as ``pop`` or ``jazz``.

    Generic labels match only where genre vocabulary is explicit: the embedded
    GENRE field, exact matching, and folder components of the path. They are
    excluded from free-text inference over album, artist, filename, and title,
    where a single ordinary word is far more likely to be a name than a genre
    (the "Soda Pop" -> ``genre.pop`` accident).
    """
    normalised = _normalise(label)
    return (
        " " not in normalised
        and normalised.isascii()
        and normalised == _normalise(tag.canonical_label)
    )


def _contains_label(text: str, label: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(label)}(?!\w)", text) is not None


def _directory_portion(path: str) -> str:
    return path.rpartition("/")[0]


def _filename_portion(path: str) -> str:
    return path.rpartition("/")[2]


class MetadataSuggestionProvider(SuggestionProvider):
    """Map explicit metadata and conservative text patterns onto taxonomy tags.

    Signal hierarchy (strongest wins per tag; see the confidence constants):

    1. Embedded GENRE / release year — high confidence (``metadata.embedded``).
    2. Folder components of the path — user-organised vocabulary, e.g. a
       ``Jazz`` folder (``metadata.path``).
    3. Album name (``metadata.album``), artist name (``metadata.artist``),
       filename (``metadata.filename``), title (``metadata.title``) — free
       text, graded from moderate to low confidence.

    Evidence discipline: free-text inference over album, artist, filename, and
    title only uses *distinctive* labels — multi-word labels, non-English
    labels, aliases, and translations (``kpop``, ``hip hop``, ``bossa nova``,
    ``케이팝``, ``enka``). Bare single-word canonical genre labels (``pop``,
    ``jazz``, ``rock``) never fire from free text; a genre word there is much
    more likely to be part of a name. Origin is never inferred from a title.
    Facets marked unavailable for Phase 1 and the user-owned ``personal``
    facet never receive automatic suggestions. Where signals are absent or
    ambiguous the provider abstains.
    """

    def __init__(self, taxonomy: Taxonomy) -> None:
        taxonomy.require_version(PINNED_TAXONOMY_VERSION)
        self.taxonomy = taxonomy
        all_aliases: dict[str, list[tuple[str, TaxonomyTag]]] = {}
        distinctive: dict[str, list[tuple[str, TaxonomyTag]]] = {}
        for tag in taxonomy.tags:
            if tag.facet == "personal" or not taxonomy.facet(tag.facet).phase1_available:
                continue
            for raw_label in _labels(tag):
                label = _normalise(raw_label)
                if not label:
                    continue
                all_aliases.setdefault(tag.facet, []).append((label, tag))
                if not _is_generic_label(label, tag):
                    distinctive.setdefault(tag.facet, []).append((label, tag))
        # Longest first makes evidence selection stable when labels overlap.
        def by_specificity(item: tuple[str, TaxonomyTag]) -> tuple[object, ...]:
            return (-len(item[0]), item[0], item[1].id)

        self._aliases = {
            facet: tuple(sorted(values, key=by_specificity))
            for facet, values in all_aliases.items()
        }
        self._distinctive = {
            facet: tuple(sorted(values, key=by_specificity))
            for facet, values in distinctive.items()
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
                            confidence=_EMBEDDED_GENRE_CONFIDENCE,
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
                        confidence=_EMBEDDED_YEAR_CONFIDENCE,
                        source="metadata.embedded",
                        evidence=f"Embedded release year={track_descriptor.year}",
                    )
                )

        path = track_descriptor.path
        # Folder components carry organiser-chosen vocabulary: all labels.
        directory = _directory_portion(path)
        normalised_directory = _normalise(directory)
        for facet, confidence in (
            ("genre", _FOLDER_GENRE_CONFIDENCE),
            ("origin", _FOLDER_ORIGIN_CONFIDENCE),
        ):
            for label, tag in self._aliases.get(facet, ()):
                if _contains_label(normalised_directory, label):
                    add(
                        TagSuggestion(
                            tag_id=tag.id,
                            confidence=confidence,
                            source="metadata.path",
                            evidence=(
                                f"Folder {directory!r} in path {path!r} contains "
                                f"{facet} label {tag.canonical_label!r}"
                            ),
                        )
                    )

        # Album, artist, filename, and title are free text: distinctive labels
        # only. Origin from a title word is too weak to ever suggest.
        self._scan_free_text(
            _filename_portion(path),
            add,
            source="metadata.filename",
            field_label="Filename",
            confidences={"genre": _TITLE_GENRE_CONFIDENCE},
        )
        self._scan_free_text(
            track_descriptor.album,
            add,
            source="metadata.album",
            field_label="Embedded ALBUM",
            confidences={
                "genre": _ALBUM_GENRE_CONFIDENCE,
                "origin": _ALBUM_ORIGIN_CONFIDENCE,
            },
        )
        self._scan_free_text(
            track_descriptor.artist,
            add,
            source="metadata.artist",
            field_label="Embedded ARTIST",
            confidences={
                "genre": _ARTIST_GENRE_CONFIDENCE,
                "origin": _ARTIST_ORIGIN_CONFIDENCE,
            },
        )
        self._scan_free_text(
            track_descriptor.title,
            add,
            source="metadata.title",
            field_label="Embedded TITLE",
            confidences={"genre": _TITLE_GENRE_CONFIDENCE},
        )

        if not any(tag_id.startswith("era.") for tag_id in suggestions):
            for (
                text,
                field_label,
                confidence,
                source,
            ) in (
                (path, "Path", _FOLDER_YEAR_CONFIDENCE, "metadata.filename"),
                (
                    track_descriptor.album,
                    "Album",
                    _ALBUM_YEAR_CONFIDENCE,
                    "metadata.album",
                ),
                (
                    track_descriptor.title,
                    "Title",
                    _TITLE_YEAR_CONFIDENCE,
                    "metadata.title",
                ),
            ):
                if not text:
                    continue
                years = [int(value) for value in _YEAR_RE.findall(text)]
                if len(set(years)) == 1:
                    era = self._era_for_year(years[0])
                    if era is not None:
                        add(
                            TagSuggestion(
                                tag_id=era,
                                confidence=confidence,
                                source=source,
                                evidence=(
                                    f"{field_label} {text!r} contains release "
                                    f"year {years[0]}"
                                ),
                            )
                        )

        return list(suggestions.values())

    def _scan_free_text(
        self,
        text: str | None,
        add: Callable[[TagSuggestion], None],
        *,
        source: str,
        field_label: str,
        confidences: dict[str, float],
    ) -> None:
        if not text or not confidences:
            return
        normalised = _normalise(text)
        for facet, confidence in confidences.items():
            for label, tag in self._distinctive.get(facet, ()):
                if _contains_label(normalised, label):
                    add(
                        TagSuggestion(
                            tag_id=tag.id,
                            confidence=confidence,
                            source=source,
                            evidence=(
                                f"{field_label}={text!r} contains {facet} label "
                                f"{label!r}"
                            ),
                        )
                    )

    def _exact_match(self, facet: str, value: str) -> TaxonomyTag | None:
        normalised = _normalise(value)
        for label, tag in self._aliases.get(facet, ()):
            if normalised == label:
                return tag
        return None

    def _era_for_year(self, year: int) -> str | None:
        tag_id = f"era.{year // 10 * 10}s"
        return tag_id if self.taxonomy.has_tag(tag_id) else None
