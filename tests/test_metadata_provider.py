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

    def test_album_signal_derives_genre_where_embedded_tags_are_absent(self) -> None:
        # Regression for the MUSI-9 ground-truth pass: a real library whose
        # files carry title/artist/album but no embedded genre or date.
        track = TrackDescriptor(
            path="/music/Converted/04 - Golden.mp3",
            title="Golden",
            artist="HUNTR/X, EJAE, AUDREY NUNA",
            album="KPop Demon Hunters (Soundtrack from the Netflix Film)",
        )
        suggestions = self.provider.suggest(track)
        by_id = {suggestion.tag_id: suggestion for suggestion in suggestions}

        self.assertIn("genre.k-pop", by_id)
        self.assertEqual(by_id["genre.k-pop"].confidence, 0.60)
        self.assertEqual(by_id["genre.k-pop"].source, "metadata.album")
        self.assertIn("ALBUM", by_id["genre.k-pop"].evidence)
        self.assertIn("KPop Demon Hunters", by_id["genre.k-pop"].evidence)
        self.assertNotIn("genre.pop", by_id)
        self.assertFalse(
            any(s.tag_id.startswith("era.") for s in suggestions)
        )
        self.taxonomy.validate_tag_ids(by_id)

    def test_artist_signal_derives_genre_with_distinctive_labels(self) -> None:
        track = TrackDescriptor(
            path="/music/05 - Track.mp3",
            artist="Hip Hop All-Stars",
        )
        suggestions = self.provider.suggest(track)
        by_id = {suggestion.tag_id: suggestion for suggestion in suggestions}

        self.assertEqual(by_id["genre.hip-hop"].confidence, 0.50)
        self.assertEqual(by_id["genre.hip-hop"].source, "metadata.artist")
        self.assertIn("ARTIST", by_id["genre.hip-hop"].evidence)
        self.taxonomy.validate_tag_ids(by_id)

    def test_embedded_genre_wins_for_the_same_tag_over_weaker_signals(self) -> None:
        track = TrackDescriptor(
            path="/music/01 - Song.mp3",
            artist="Hip Hop All-Stars",
            album="KPop Demon Hunters (Soundtrack)",
            genre="Hip Hop",
        )
        by_id = {s.tag_id: s for s in self.provider.suggest(track)}

        # Same tag: the embedded genre (0.95) outranks the artist match (0.50).
        self.assertEqual(by_id["genre.hip-hop"].confidence, 0.95)
        self.assertEqual(by_id["genre.hip-hop"].source, "metadata.embedded")
        # Distinct tags from weaker signals are still emitted as candidates
        # for review, at their own confidence.
        self.assertEqual(by_id["genre.k-pop"].confidence, 0.60)
        self.assertEqual(by_id["genre.k-pop"].source, "metadata.album")

    def test_generic_single_word_labels_never_fire_from_free_text(self) -> None:
        # The reported defect: the title word "Pop" produced genre.pop.
        soda_pop = TrackDescriptor(
            path="/music/07 - Soda Pop.mp3",
            title="Soda Pop",
            artist="Soda Pop",
            album="Soda Pop (Single)",
        )
        self.assertEqual(self.provider.suggest(soda_pop), [])

        # A folder is organiser-chosen vocabulary, so the full label set
        # (including generic words) still applies there.
        folder = TrackDescriptor(path="/music/Jazz/01 - Song.mp3")
        by_id = {s.tag_id: s for s in self.provider.suggest(folder)}
        self.assertEqual(by_id["genre.jazz"].confidence, 0.55)
        self.assertEqual(by_id["genre.jazz"].source, "metadata.path")

    def test_distinctive_labels_fire_from_title_with_low_confidence(self) -> None:
        kpop_title = TrackDescriptor(
            path="/music/01 - Medley.mp3",
            title="Kpop Medley",
        )
        by_id = {s.tag_id: s for s in self.provider.suggest(kpop_title)}

        self.assertEqual(by_id["genre.k-pop"].confidence, 0.30)
        self.assertEqual(by_id["genre.k-pop"].source, "metadata.title")
        self.taxonomy.validate_tag_ids(by_id)

    def test_origin_is_never_inferred_from_title_or_filename(self) -> None:
        track = TrackDescriptor(
            path="/music/01 - Jamaica Farewell.mp3",
            title="Jamaica Farewell",
        )
        suggestions = self.provider.suggest(track)
        self.assertFalse(any(s.tag_id.startswith("origin.") for s in suggestions))

    def test_album_and_title_year_fallbacks_with_per_source_abstention(self) -> None:
        album_year = TrackDescriptor(
            path="/music/01 - Song.mp3",
            album="Greatest Hits 1987",
        )
        by_id = {s.tag_id: s for s in self.provider.suggest(album_year)}
        self.assertEqual(by_id["era.1980s"].confidence, 0.55)
        self.assertEqual(by_id["era.1980s"].source, "metadata.album")

        title_year = TrackDescriptor(
            path="/music/01 - Song.mp3",
            title="Summer 1992",
        )
        by_id = {s.tag_id: s for s in self.provider.suggest(title_year)}
        self.assertEqual(by_id["era.1990s"].confidence, 0.40)
        self.assertEqual(by_id["era.1990s"].source, "metadata.title")

        ambiguous_album = TrackDescriptor(
            path="/music/01 - Song.mp3",
            album="1987 Sessions (remastered 2010)",
        )
        self.assertFalse(
            any(
                s.tag_id.startswith("era.")
                for s in self.provider.suggest(ambiguous_album)
            )
        )

    def test_extended_signals_stay_deterministic_and_conform(self) -> None:
        tracks = [
            TrackDescriptor(
                path="/music/01 - Soda Pop.mp3",
                title="Soda Pop",
                artist="HUNTR/X",
                album="KPop Demon Hunters (Soundtrack)",
            ),
            TrackDescriptor(
                path="/music/Live in Jamaica/03 - Song.flac",
                artist="Bob's Reggae Band",
                album="Live in Jamaica",
            ),
            TrackDescriptor(path="/music/99 - Untitled.ogg"),
        ]
        for track in tracks:
            with self.subTest(path=track.path):
                first = self.provider.suggest(track)
                second = self.provider.suggest(track)
                self.assertEqual(first, second)
                self.taxonomy.validate_tag_ids(s.tag_id for s in first)

    def test_embedded_release_date_always_surfaces_an_era(self) -> None:
        # Operator requirement (2026-11-17): if any local source carries a
        # date, the provider MUST suggest an era from it. The scanner parses
        # TDRC/DATE full dates ("1994-05-01") to the descriptor year; whatever
        # the source format, the year reaching the descriptor yields era.
        from musigtagger.engine.scanner import _parse_year

        for raw in ("1994", "1994-05", "1994-05-01", "1994-05-01T12:34:56"):
            with self.subTest(date=raw):
                track = TrackDescriptor(
                    path="/music/01 - Song.mp3", year=_parse_year(raw)
                )
                by_id = {s.tag_id: s for s in self.provider.suggest(track)}
                self.assertIn("era.1990s", by_id)
                self.assertEqual(by_id["era.1990s"].confidence, 0.98)
                self.assertEqual(by_id["era.1990s"].source, "metadata.embedded")
                self.assertIn("1994", by_id["era.1990s"].evidence)
                self.taxonomy.validate_tag_ids(by_id)

    def test_refuses_any_other_taxonomy_version(self) -> None:
        old = TaxonomyLoader.load(TAXONOMY_DIR, version="0.1.0-draft")
        with self.assertRaises(TaxonomyVersionMismatch):
            MetadataSuggestionProvider(old)


if __name__ == "__main__":
    unittest.main()
