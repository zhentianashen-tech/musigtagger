"""The taxonomy-tag → tag-field projection."""

from __future__ import annotations

import unittest

from musigtagger.app.tagmap import (
    FACET_FIELDS,
    FAMILY_ID3,
    FAMILY_VORBIS,
    TXXX_SEPARATOR,
    UnsupportedFacetError,
    UnsupportedFormatError,
    family_for_format,
    field_for,
    managed_fields,
    normalise_fields,
    project,
)
from musigtagger.app.taxonomy_service import TaxonomyService
from musigtagger.contracts import TaxonomyTag

from support import TAXONOMY_DIR, TAXONOMY_VERSION


def tag(tag_id: str, facet: str, label: str) -> TaxonomyTag:
    return TaxonomyTag(
        id=tag_id,
        facet=facet,
        canonical_label=label,
        labels={"en": label},
        aliases=(),
        parent=None,
    )


class FieldMappingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.taxonomy = TaxonomyService(TAXONOMY_DIR, TAXONOMY_VERSION)

    def test_genre_uses_the_standard_field(self) -> None:
        self.assertEqual(field_for("genre", FAMILY_ID3), "TCON")
        self.assertEqual(field_for("genre", FAMILY_VORBIS), "GENRE")

    def test_other_facets_use_namespaced_fields(self) -> None:
        for facet in ("mood", "era", "activity", "origin", "personal"):
            self.assertTrue(FACET_FIELDS[facet][FAMILY_ID3].startswith("TXXX:"))
            self.assertEqual(
                FACET_FIELDS[facet][FAMILY_VORBIS], facet.upper()
            )

    def test_every_taxonomy_facet_has_a_projection(self) -> None:
        for facet in self.taxonomy.taxonomy.facet_ids:
            for family in (FAMILY_ID3, FAMILY_VORBIS):
                field_for(facet, family)

    def test_unknown_facet_is_refused_not_invented(self) -> None:
        with self.assertRaises(UnsupportedFacetError):
            field_for("texture", FAMILY_ID3)

    def test_format_families(self) -> None:
        self.assertEqual(family_for_format("mp3"), FAMILY_ID3)
        self.assertEqual(family_for_format("flac"), FAMILY_VORBIS)
        self.assertEqual(family_for_format("OGG"), FAMILY_VORBIS)
        with self.assertRaises(UnsupportedFormatError):
            family_for_format("ncm")
        with self.assertRaises(UnsupportedFormatError):
            family_for_format(None)

    def test_projection_uses_canonical_labels_and_is_deterministic(self) -> None:
        tags = [
            self.taxonomy.tag("era.1990s"),
            self.taxonomy.tag("genre.hip-hop"),
        ]
        self.assertEqual(
            project(tags, FAMILY_ID3),
            {"TCON": ["Hip-hop"], "TXXX:ERA": ["1990s"]},
        )
        self.assertEqual(
            project(list(reversed(tags)), FAMILY_VORBIS),
            {"GENRE": ["Hip-hop"], "ERA": ["1990s"]},
        )

    def test_multiple_values_per_facet(self) -> None:
        tags = [
            tag("genre.rock", "genre", "Rock"),
            tag("genre.jazz", "genre", "Jazz"),
            tag("mood.calm", "mood", "Calm"),
            tag("mood.dreamy", "mood", "Dreamy"),
        ]
        id3 = project(tags, FAMILY_ID3)
        self.assertEqual(id3["TCON"], ["Jazz", "Rock"])
        self.assertEqual(id3["TXXX:MOOD"], ["Calm" + TXXX_SEPARATOR + "Dreamy"])

    def test_managed_fields_cover_both_families(self) -> None:
        self.assertIn("TCON", managed_fields(FAMILY_ID3))
        self.assertIn("TXXX:ERA", managed_fields(FAMILY_ID3))
        self.assertIn("GENRE", managed_fields(FAMILY_VORBIS))
        self.assertIn("PERSONAL", managed_fields(FAMILY_VORBIS))

    def test_normalise_limits_to_managed_fields_and_strips(self) -> None:
        normalised = normalise_fields(
            {
                "TCON": [" Hip-hop "],
                "TXXX:ERA": ["  1990s"],
                "UNRELATED": ["keep out"],
                "GENRE": ["ignored"],
            },
            family=FAMILY_ID3,
        )
        self.assertEqual(normalised["TCON"], ["Hip-hop"])
        self.assertEqual(normalised["TXXX:ERA"], ["1990s"])
        self.assertNotIn("UNRELATED", normalised)
        self.assertNotIn("GENRE", normalised)
