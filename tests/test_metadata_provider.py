from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path

try:
    import mutagen  # noqa: F401
except ModuleNotFoundError:
    sys.modules["mutagen"] = types.SimpleNamespace(File=None)

from musigtagger.contracts import (
    TaxonomyLoader,
    TaxonomyVersionMismatch,
    TrackDescriptor,
)
from musigtagger.engine import MetadataSuggestionProvider


TAXONOMY_DIR = Path(__file__).resolve().parents[1] / "taxonomy"


class MetadataProviderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.taxonomy = TaxonomyLoader.load(TAXONOMY_DIR, version="1.0.0")
        cls.provider = MetadataSuggestionProvider(cls.taxonomy)

    def test_embedded_genre_alias_and_year_are_high_confidence(self) -> None:
        track = TrackDescriptor(
            path="/music/Artist/Album/01 Song.mp3",
            genre="Hip Hop",
            year=1994,
        )
        suggestions = self.provider.suggest(track)
        by_id = {suggestion.tag_id: suggestion for suggestion in suggestions}

        self.assertEqual(by_id["genre.hip-hop"].confidence, 0.95)
        self.assertEqual(by_id["genre.hip-hop"].source, "metadata.embedded")
        self.assertIn("Hip Hop", by_id["genre.hip-hop"].evidence)
        self.assertEqual(by_id["era.1990s"].confidence, 0.98)
        self.taxonomy.validate_tag_ids(by_id)

    def test_path_and_filename_matches_have_lower_confidence(self) -> None:
        track = TrackDescriptor(path="/music/Jazz/1987 - Artist - Song.flac")
        suggestions = self.provider.suggest(track)
        by_id = {suggestion.tag_id: suggestion for suggestion in suggestions}

        self.assertEqual(by_id["genre.jazz"].confidence, 0.55)
        self.assertEqual(by_id["era.1980s"].confidence, 0.65)
        self.assertEqual(by_id["era.1980s"].source, "metadata.filename")

    def test_phase1_unavailable_and_personal_facets_are_not_invented(self) -> None:
        track = TrackDescriptor(
            path="/music/Calm/Workout/Favorites/Song.ogg",
            genre="not in taxonomy",
        )
        suggestions = self.provider.suggest(track)
        self.assertEqual(suggestions, [])

    def test_ambiguous_or_unsupported_years_abstain(self) -> None:
        ambiguous = TrackDescriptor(path="/music/1987/remastered-2010/Song.mp3")
        unsupported = TrackDescriptor(path="/music/1942/Song.mp3", year=1942)
        self.assertFalse(
            any(s.tag_id.startswith("era.") for s in self.provider.suggest(ambiguous))
        )
        self.assertFalse(
            any(s.tag_id.startswith("era.") for s in self.provider.suggest(unsupported))
        )

    def test_empty_and_malformed_metadata_abstain_without_errors(self) -> None:
        for genre in (None, "", "!!!", "unknown genre"):
            with self.subTest(genre=genre):
                track = TrackDescriptor(path="/music/01 - Song.mp3", genre=genre)
                self.assertEqual(self.provider.suggest(track), [])

    def test_provider_is_deterministic_and_all_ids_conform(self) -> None:
        tracks = [
            TrackDescriptor(path="/music/Rock/1975/Song.mp3", genre="Rock", year=1975),
            TrackDescriptor(path="/music/Electronic/House/Song.flac"),
            TrackDescriptor(path="/music/unknown.ogg"),
        ]
        for track in tracks:
            with self.subTest(path=track.path):
                first = self.provider.suggest(track)
                second = self.provider.suggest(track)
                self.assertEqual(first, second)
                self.taxonomy.validate_tag_ids(s.tag_id for s in first)

    def test_refuses_any_other_taxonomy_version(self) -> None:
        old = TaxonomyLoader.load(TAXONOMY_DIR, version="0.1.0-draft")
        with self.assertRaises(TaxonomyVersionMismatch):
            MetadataSuggestionProvider(old)


if __name__ == "__main__":
    unittest.main()
