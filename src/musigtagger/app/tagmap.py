"""The taxonomy-tag → audio-tag-field projection (application layer).

The taxonomy decides *which* tags exist and what their canonical labels are; the
application decides how to place them in the file. This module is that one
mapping table, kept pure (no I/O) so it can be reviewed and tested on its own.

MVP mapping
-----------
=================  ==========================  ==========================
facet              ID3v2 frame                 Vorbis comment key
=================  ==========================  ==========================
genre              ``TCON``                    ``GENRE``
mood               ``TXXX:MOOD``               ``MOOD``
era                ``TXXX:ERA``                ``ERA``
activity           ``TXXX:ACTIVITY``           ``ACTIVITY``
origin             ``TXXX:ORIGIN``             ``ORIGIN``
personal           ``TXXX:PERSONAL``           ``PERSONAL``
=================  ==========================  ==========================

Rationale:

* **Genre is the only facet with a universally standard field** (``TCON`` /
  ``GENRE``), so it uses it.
* Every other facet is written to a namespaced field. ``era`` is the important
  case: ``era.1990s`` is a decade, not a date, so writing it into ``TDRC`` (the
  standard recording-date frame) would corrupt the file's date semantics. The
  same reasoning applies to ``mood`` (``TMOO`` exists only in ID3v2.4, while
  libraries here are usually v2.3) and to ``activity``/``origin``/``personal``,
  which have no standard field at all.
* Values are always **canonical labels**, never tag ids (``"Hip-hop"``, not
  ``"genre.hip-hop"``), so a human and a downstream player see real words.
  Round-tripping back to ids is the provider's job, using the taxonomy aliases.

Multiple tags in one facet are written as multiple values (``TCON`` supports
multi-value text; Vorbis allows repeated keys). ``TXXX`` frames are single-value
per description, so several values are joined with ``"; "``.

Projecting a facet to standard fields (``TMOO``, ``TDRC``) is a product decision
that belongs to the leader/designer, not the application layer: it changes what
a tag *means*. Until that decision exists, this table is the whole projection.
"""

from __future__ import annotations

from typing import Iterable, Mapping

from ..contracts import TaxonomyTag

FAMILY_ID3 = "id3"
FAMILY_VORBIS = "vorbis"
FAMILIES = (FAMILY_ID3, FAMILY_VORBIS)

#: facet -> {family -> field name}. ``TXXX:<DESC>`` is a user-defined ID3 frame.
FACET_FIELDS: dict[str, dict[str, str]] = {
    "genre": {FAMILY_ID3: "TCON", FAMILY_VORBIS: "GENRE"},
    "mood": {FAMILY_ID3: "TXXX:MOOD", FAMILY_VORBIS: "MOOD"},
    "era": {FAMILY_ID3: "TXXX:ERA", FAMILY_VORBIS: "ERA"},
    "activity": {FAMILY_ID3: "TXXX:ACTIVITY", FAMILY_VORBIS: "ACTIVITY"},
    "origin": {FAMILY_ID3: "TXXX:ORIGIN", FAMILY_VORBIS: "ORIGIN"},
    "personal": {FAMILY_ID3: "TXXX:PERSONAL", FAMILY_VORBIS: "PERSONAL"},
}

#: File formats this Phase 1 write path understands, mapped to tag families.
FORMAT_FAMILIES: dict[str, str] = {
    "mp3": FAMILY_ID3,
    "flac": FAMILY_VORBIS,
    "ogg": FAMILY_VORBIS,
    "oga": FAMILY_VORBIS,
    "opus": FAMILY_VORBIS,
}

TXXX_PREFIX = "TXXX:"
TXXX_SEPARATOR = "; "


class UnsupportedFacetError(Exception):
    """A taxonomy facet has no agreed field projection (needs a decision)."""

    def __init__(self, facet: str) -> None:
        self.facet = facet
        super().__init__(
            f"facet {facet!r} has no agreed tag-field projection; this is a "
            "product decision (taxonomy/leader), not something the write path "
            "may invent"
        )


class UnsupportedFormatError(Exception):
    """The file format has no supported tag family in Phase 1."""

    def __init__(self, format_name: str | None) -> None:
        self.format_name = format_name
        super().__init__(
            f"format {format_name!r} is not writable by this Phase 1 tag path; "
            "supported: mp3 (ID3v2), flac/ogg (Vorbis comments)"
        )


def family_for_format(format_name: str | None) -> str:
    """Return the tag family for a scanner format name, or raise."""
    if not format_name:
        raise UnsupportedFormatError(format_name)
    family = FORMAT_FAMILIES.get(format_name.strip().lower())
    if family is None:
        raise UnsupportedFormatError(format_name)
    return family


def field_for(facet: str, family: str) -> str:
    try:
        return FACET_FIELDS[facet][family]
    except KeyError:
        if facet not in FACET_FIELDS:
            raise UnsupportedFacetError(facet) from None
        raise ValueError(f"unknown tag family {family!r}") from None


def managed_fields(family: str) -> tuple[str, ...]:
    """Every field this application owns for a tag family."""
    fields = {FACET_FIELDS[facet][family] for facet in FACET_FIELDS}
    return tuple(sorted(fields))


def project(
    tags: Iterable[TaxonomyTag],
    family: str,
) -> dict[str, list[str]]:
    """Project taxonomy tags to fields and canonical-label values.

    Deterministic: tags are processed in id order, and values keep that order.
    """
    grouped: dict[str, list[str]] = {}
    for tag in sorted(tags, key=lambda item: item.id):
        field = field_for(tag.facet, family)
        grouped.setdefault(field, []).append(tag.canonical_label)
    if family == FAMILY_ID3:
        for field, values in grouped.items():
            if field.startswith(TXXX_PREFIX) and len(values) > 1:
                grouped[field] = [TXXX_SEPARATOR.join(values)]
    return grouped


def empty_projection(family: str) -> dict[str, list[str]]:
    """A projection with every managed field empty (used to clear a facet set)."""
    return {field: [] for field in managed_fields(family)}


def normalise_fields(
    fields: Mapping[str, Iterable[str]],
    *,
    family: str,
) -> dict[str, list[str]]:
    """Return a comparable view of fields: managed keys only, stripped values.

    This is how the write path compares "what I intended to write" with "what
    mutagen reads back", without depending on frame ordering or extra fields a
    user might already have.
    """
    normalised: dict[str, list[str]] = {}
    for field in managed_fields(family):
        values: list[str] = []
        for value in fields.get(field, []) or []:
            if isinstance(value, str):
                text = value.strip()
                if text:
                    values.append(text)
        normalised[field] = values
    return normalised
