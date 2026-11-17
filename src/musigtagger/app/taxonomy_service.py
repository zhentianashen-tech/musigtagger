"""Taxonomy access for the application layer: pinned load, labels, validation.

The application never edits the taxonomy. It loads exactly the version pinned in
``library_meta('taxonomy_version')``, uses it to validate every tag it persists
or writes, and uses canonical labels as the values written to audio files.
"""

from __future__ import annotations

from pathlib import Path

from ..contracts import Taxonomy, TaxonomyLoader, TaxonomyTag

#: The vocabulary version this Phase 1 application pins. Taxonomy v1.0.0 is the
#: frozen Phase 1 document (MUSI-5); v0 remains readable for tooling but is not
#: an acceptable write target.
PHASE1_TAXONOMY_VERSION = "1.0.0"


class TaxonomyService:
    """Read-only taxonomy access keyed by the pinned version."""

    def __init__(self, taxonomy_dir: str | Path, version: str) -> None:
        self.directory = Path(taxonomy_dir)
        self.taxonomy: Taxonomy = TaxonomyLoader.load(self.directory, version=version)

    @property
    def version(self) -> str:
        return self.taxonomy.version

    def tag(self, tag_id: str) -> TaxonomyTag:
        """Return a tag, raising ``UnknownTagError`` outside the pinned version."""
        return self.taxonomy.tag(tag_id)

    def validate(self, tag_ids: list[str]) -> None:
        self.taxonomy.validate_tag_ids(tag_ids)

    def label(self, tag_id: str, language: str | None = None) -> str:
        return self.tag(tag_id).display_label(language)

    def facet_for(self, tag_id: str) -> str:
        return self.tag(tag_id).facet

    def tag_id_for_label(self, facet: str, label: str) -> str | None:
        """Resolve a canonical label or alias to a tag id, within one facet."""
        wanted = label.strip().casefold()
        for tag in self.taxonomy.tags_in_facet(facet):
            if tag.canonical_label.casefold() == wanted:
                return tag.id
            for alias in tag.aliases:
                if alias.casefold() == wanted:
                    return tag.id
        return None

    def facet_tags(self, facet: str, language: str | None = None) -> list[dict[str, str]]:
        """Enumerated choices for the edit control, ordered by label."""
        choices = [
            {"id": tag.id, "label": tag.display_label(language)}
            for tag in self.taxonomy.tags_in_facet(facet)
        ]
        choices.sort(key=lambda choice: (choice["label"].casefold(), choice["id"]))
        return choices

    def choices_for_facets(
        self, facets: list[str] | None = None, language: str | None = None
    ) -> dict[str, list[dict[str, str]]]:
        selected = facets or list(self.taxonomy.facet_ids)
        return {
            facet: self.facet_tags(facet, language)
            for facet in selected
            if self.taxonomy.has_facet(facet)
        }

    def facet_labels(self) -> dict[str, str]:
        return {facet.id: facet.label for facet in self.taxonomy.facets}
