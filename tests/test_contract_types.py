"""Contract value types: validation, immutability, and the provider protocol."""

from __future__ import annotations

import unittest
from dataclasses import FrozenInstanceError

from musigtagger.contracts import (
    AudioFeatures,
    SuggestionProvider,
    TagSuggestion,
    TrackDescriptor,
)


class TrackDescriptorTests(unittest.TestCase):
    def test_minimal_descriptor_defaults(self) -> None:
        track = TrackDescriptor(path="/music/a.mp3")
        self.assertEqual(track.path, "/music/a.mp3")
        self.assertIsNone(track.title)
        self.assertIsNone(track.features)

    def test_full_descriptor(self) -> None:
        features = AudioFeatures(tempo_bpm=128.0, energy=0.8, key="C#")
        track = TrackDescriptor(
            path="/music/artist/album/01 - Song.flac",
            title="Song",
            artist="Artist",
            album="Album",
            genre="Alt. Rock",
            year=1997,
            duration_seconds=243.5,
            format="flac",
            features=features,
        )
        self.assertEqual(track.features, features)
        self.assertEqual(track.duration_seconds, 243.5)

    def test_descriptor_is_immutable(self) -> None:
        track = TrackDescriptor(path="/music/a.mp3")
        with self.assertRaises(FrozenInstanceError):
            track.title = "changed"  # type: ignore[misc]

    def test_descriptor_is_hashable(self) -> None:
        self.assertEqual(
            hash(TrackDescriptor(path="/music/a.mp3")),
            hash(TrackDescriptor(path="/music/a.mp3")),
        )

    def test_rejects_blank_path(self) -> None:
        with self.assertRaises(ValueError):
            TrackDescriptor(path="   ")

    def test_rejects_negative_duration(self) -> None:
        with self.assertRaises(ValueError):
            TrackDescriptor(path="/a.mp3", duration_seconds=-1)

    def test_rejects_non_finite_duration(self) -> None:
        with self.assertRaises(ValueError):
            TrackDescriptor(path="/a.mp3", duration_seconds=float("nan"))

    def test_rejects_bad_year(self) -> None:
        with self.assertRaises(ValueError):
            TrackDescriptor(path="/a.mp3", year=0)
        with self.assertRaises(TypeError):
            TrackDescriptor(path="/a.mp3", year="1999")  # type: ignore[arg-type]

    def test_rejects_wrong_feature_type(self) -> None:
        with self.assertRaises(TypeError):
            TrackDescriptor(path="/a.mp3", features={"tempo": 120})  # type: ignore[arg-type]


class AudioFeaturesTests(unittest.TestCase):
    def test_unit_interval_validation(self) -> None:
        for field_name in ("energy", "valence", "danceability"):
            for bad in (-0.1, 1.1, float("nan"), float("inf")):
                with self.subTest(field=field_name, value=bad):
                    with self.assertRaises(ValueError):
                        AudioFeatures(**{field_name: bad})  # type: ignore[arg-type]

    def test_tempo_must_be_positive(self) -> None:
        with self.assertRaises(ValueError):
            AudioFeatures(tempo_bpm=0)

    def test_extra_is_frozen(self) -> None:
        features = AudioFeatures(extra={"spectral_centroid": 1234.5})
        with self.assertRaises(TypeError):
            features.extra["x"] = 1  # type: ignore[index]

    def test_bool_is_not_a_number(self) -> None:
        with self.assertRaises(TypeError):
            AudioFeatures(energy=True)  # type: ignore[arg-type]


class TagSuggestionTests(unittest.TestCase):
    def test_valid_suggestion(self) -> None:
        suggestion = TagSuggestion(
            tag_id="genre.hip-hop",
            confidence=0.72,
            source="metadata.embedded",
            evidence="Vorbis GENRE='Hip Hop'",
        )
        self.assertEqual(suggestion.confidence, 0.72)
        self.assertEqual(suggestion.source, "metadata.embedded")

    def test_confidence_boundaries_are_inclusive(self) -> None:
        for value in (0, 0.0, 1, 1.0):
            with self.subTest(value=value):
                self.assertEqual(
                    TagSuggestion(
                        tag_id="era.1990s",
                        confidence=value,
                        source="metadata.embedded",
                        evidence="DATE=1994",
                    ).confidence,
                    float(value),
                )

    def test_confidence_out_of_range_rejected(self) -> None:
        for value in (-0.01, 1.01, float("nan"), float("inf")):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    TagSuggestion(
                        tag_id="era.1990s",
                        confidence=value,
                        source="s",
                        evidence="e",
                    )

    def test_confidence_must_be_numeric(self) -> None:
        for value in ("0.5", None, True):
            with self.subTest(value=value):
                with self.assertRaises(TypeError):
                    TagSuggestion(
                        tag_id="era.1990s",
                        confidence=value,  # type: ignore[arg-type]
                        source="s",
                        evidence="e",
                    )

    def test_required_fields_are_non_empty(self) -> None:
        for field in ("tag_id", "source", "evidence"):
            with self.subTest(field=field):
                kwargs = {
                    "tag_id": "era.1990s",
                    "confidence": 0.5,
                    "source": "metadata.embedded",
                    "evidence": "DATE=1994",
                }
                kwargs[field] = "  "
                with self.assertRaises(ValueError):
                    TagSuggestion(**kwargs)  # type: ignore[arg-type]

    def test_values_are_stripped(self) -> None:
        suggestion = TagSuggestion(
            tag_id="  era.1990s  ",
            confidence=0.5,
            source=" metadata.embedded ",
            evidence=" DATE=1994 ",
        )
        self.assertEqual(suggestion.tag_id, "era.1990s")
        self.assertEqual(suggestion.source, "metadata.embedded")
        self.assertEqual(suggestion.evidence, "DATE=1994")

    def test_suggestion_is_immutable_and_hashable(self) -> None:
        suggestion = TagSuggestion(
            tag_id="era.1990s", confidence=0.5, source="s", evidence="e"
        )
        with self.assertRaises(FrozenInstanceError):
            suggestion.tag_id = "era.2000s"  # type: ignore[misc]
        self.assertIn(suggestion, {suggestion})


class _DummyProvider:
    def suggest(self, track_descriptor: TrackDescriptor) -> list[TagSuggestion]:
        return [
            TagSuggestion(
                tag_id="genre.rock",
                confidence=0.5,
                source="dummy",
                evidence=f"path={track_descriptor.path}",
            )
        ]


class ProviderProtocolTests(unittest.TestCase):
    def test_structural_conformance(self) -> None:
        self.assertIsInstance(_DummyProvider(), SuggestionProvider)

    def test_suggest_returns_suggestions_for_descriptor(self) -> None:
        provider = _DummyProvider()
        suggestions = provider.suggest(TrackDescriptor(path="/music/a.mp3"))
        self.assertEqual([s.tag_id for s in suggestions], ["genre.rock"])


if __name__ == "__main__":
    unittest.main()
