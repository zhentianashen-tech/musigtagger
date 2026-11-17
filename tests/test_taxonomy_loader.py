"""Taxonomy loader: v0 load, pinning, round-trip, v1 drop-in, and validation."""

from __future__ import annotations

import copy
import importlib.util
import json
import tempfile
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path

from musigtagger.contracts import (
    Taxonomy,
    TaxonomyError,
    TaxonomyFacet,
    TaxonomyFormatError,
    TaxonomyLoader,
    TaxonomyTag,
    TaxonomyValidationError,
    TaxonomyVersionAmbiguous,
    TaxonomyVersionMismatch,
    UnknownTagError,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
TAXONOMY_DIR = REPO_ROOT / "taxonomy"
V0_PATH = TAXONOMY_DIR / "taxonomy-0.1.0-draft.json"
V0_VERSION = "0.1.0-draft"


def _write_json(directory: Path, name: str, document: dict) -> Path:
    path = directory / name
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


class TaxonomyV0Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.taxonomy = TaxonomyLoader.load_file(V0_PATH)

    def test_reports_version_and_name(self) -> None:
        self.assertEqual(self.taxonomy.version, V0_VERSION)
        self.assertEqual(self.taxonomy.schema_version, 1)
        self.assertIn("Music Tagger", self.taxonomy.name)

    def test_covers_all_six_facets(self) -> None:
        self.assertEqual(
            set(self.taxonomy.facet_ids),
            {"genre", "mood", "era", "activity", "origin", "personal"},
        )
        self.assertEqual(
            {facet.id for facet in self.taxonomy.phase1_facets()},
            {"genre", "era", "origin", "personal"},
        )

    def test_genre_tree_is_depth_two(self) -> None:
        genre = self.taxonomy.facet("genre")
        self.assertTrue(genre.hierarchy)
        self.assertEqual(genre.max_depth, 2)
        child = self.taxonomy.tag("genre.rock.progressive-rock")
        self.assertEqual(child.parent, "genre.rock")
        self.assertEqual(self.taxonomy.tag("genre.rock").parent, None)

    def test_native_language_canonical_and_aliases(self) -> None:
        hip_hop = self.taxonomy.tag("genre.hip-hop")
        self.assertEqual(hip_hop.canonical_label, "Hip-hop")
        self.assertIn("Rap", hip_hop.aliases)
        self.assertIn("Hip Hop", hip_hop.aliases)
        self.assertEqual(hip_hop.display_label("zh"), "嘻哈")
        self.assertEqual(hip_hop.display_label("xx"), "Hip-hop")

    def test_personal_facet_is_open_and_empty(self) -> None:
        personal = self.taxonomy.facet("personal")
        self.assertTrue(personal.open_set)
        self.assertFalse(personal.hierarchy)
        self.assertEqual(self.taxonomy.tags_in_facet("personal"), ())

    def test_lookups(self) -> None:
        self.assertTrue(self.taxonomy.has_tag("era.1990s"))
        self.assertFalse(self.taxonomy.has_tag("era.1890s"))
        self.assertEqual(self.taxonomy.tag("era.1990s").canonical_label, "1990s")

    def test_unknown_tag_raises_with_ids(self) -> None:
        with self.assertRaises(UnknownTagError) as caught:
            self.taxonomy.tag("genre.not-a-tag")
        self.assertEqual(caught.exception.unknown_tag_ids, ("genre.not-a-tag",))
        self.assertEqual(caught.exception.taxonomy_version, V0_VERSION)

    def test_validate_tag_ids_accepts_known_ids(self) -> None:
        self.taxonomy.validate_tag_ids(
            ["genre.rock.progressive-rock", "era.1990s", "origin.lang-deu"]
        )

    def test_validate_tag_ids_aggregates_unknown_ids(self) -> None:
        with self.assertRaises(UnknownTagError) as caught:
            self.taxonomy.validate_tag_ids(
                ["genre.rock", "genre.nope", "mood.nope"]
            )
        self.assertEqual(
            caught.exception.unknown_tag_ids, ("genre.nope", "mood.nope")
        )

    def test_require_version(self) -> None:
        self.taxonomy.require_version(V0_VERSION)
        with self.assertRaises(TaxonomyVersionMismatch):
            self.taxonomy.require_version("1.0.0")

    def test_immutable(self) -> None:
        with self.assertRaises(FrozenInstanceError):
            self.taxonomy.version = "9.9.9"  # type: ignore[misc]

    def test_schema_targets_are_isolated_from_repo_files(self) -> None:
        # ``load`` only considers taxonomy* files, so a future schema file in
        # the same directory cannot be mistaken for a taxonomy document.
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            TaxonomyLoader.dump(self.taxonomy, directory / "taxonomy-0.1.0-draft.json")
            (directory / "taxonomy.schema.json").write_text("{}", encoding="utf-8")
            loaded = TaxonomyLoader.load(directory, version=V0_VERSION)
            self.assertEqual(loaded, self.taxonomy)


class TaxonomyRoundTripTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.taxonomy = TaxonomyLoader.load_file(V0_PATH)

    def test_json_round_trip_reports_same_version(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "taxonomy.json"
            TaxonomyLoader.dump(self.taxonomy, path)
            reloaded = TaxonomyLoader.load_file(path)
        self.assertEqual(reloaded.version, V0_VERSION)
        self.assertEqual(reloaded, self.taxonomy)
        self.assertIn("Starter vocabulary", reloaded.description)

    def test_load_directory_pins_version(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            TaxonomyLoader.dump(self.taxonomy, directory / "taxonomy-0.1.0-draft.json")
            self.assertEqual(
                TaxonomyLoader.load(directory, version=V0_VERSION), self.taxonomy
            )
            self.assertEqual(
                TaxonomyLoader.available_versions(directory), (V0_VERSION,)
            )

    def test_load_directory_rejects_missing_version(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            TaxonomyLoader.dump(self.taxonomy, directory / "taxonomy-0.1.0-draft.json")
            with self.assertRaises(TaxonomyVersionMismatch) as caught:
                TaxonomyLoader.load(directory, version="1.0.0")
        self.assertEqual(caught.exception.expected, "1.0.0")
        self.assertEqual(caught.exception.available, (V0_VERSION,))

    def test_load_directory_rejects_duplicate_version(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            TaxonomyLoader.dump(self.taxonomy, directory / "taxonomy-a.json")
            TaxonomyLoader.dump(self.taxonomy, directory / "taxonomy-b.json")
            with self.assertRaises(TaxonomyVersionAmbiguous) as caught:
                TaxonomyLoader.load(directory, version=V0_VERSION)
        self.assertEqual(caught.exception.version, V0_VERSION)
        self.assertEqual(len(caught.exception.paths), 2)

    def test_load_requires_keyword_version(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            with self.assertRaises(TypeError):
                TaxonomyLoader.load(Path(raw))  # type: ignore[call-arg]

    def test_missing_directory_raises_taxonomy_error(self) -> None:
        with self.assertRaises(TaxonomyError):
            TaxonomyLoader.load(Path("/nonexistent-taxonomy-dir"), version=V0_VERSION)

    def test_v1_document_drops_in_without_schema_change(self) -> None:
        document = copy.deepcopy(self.taxonomy.to_dict())
        document["version"] = "1.0.0"
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            _write_json(directory, "taxonomy-1.0.0.json", document)
            loaded = TaxonomyLoader.load(directory, version="1.0.0")
        self.assertEqual(loaded.version, "1.0.0")
        self.assertEqual(loaded.schema_version, 1)
        self.assertEqual(loaded.facet_ids, self.taxonomy.facet_ids)

    @unittest.skipUnless(
        importlib.util.find_spec("yaml") is not None,
        "PyYAML not installed",
    )
    def test_yaml_document_loads_when_optional_extra_is_present(self) -> None:
        import yaml

        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "taxonomy.yaml"
            path.write_text(
                yaml.safe_dump(self.taxonomy.to_dict(), sort_keys=False),
                encoding="utf-8",
            )
            loaded = TaxonomyLoader.load_file(path)
        self.assertEqual(loaded, self.taxonomy)


class TaxonomyValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.base = TaxonomyLoader.load_file(V0_PATH).to_dict()

    def _load_mutated(self, mutate) -> None:
        document = copy.deepcopy(self.base)
        mutate(document)
        with tempfile.TemporaryDirectory() as raw:
            path = _write_json(Path(raw), "taxonomy-test.json", document)
            TaxonomyLoader.load_file(path)

    def test_duplicate_tag_id(self) -> None:
        def mutate(document: dict) -> None:
            document["tags"].append(copy.deepcopy(document["tags"][0]))

        with self.assertRaises(TaxonomyValidationError):
            self._load_mutated(mutate)

    def test_unknown_facet(self) -> None:
        def mutate(document: dict) -> None:
            for tag in document["tags"]:
                if tag["id"] == "genre.pop":
                    tag["facet"] = "nope"
                    tag["id"] = "nope.pop"

        with self.assertRaises(TaxonomyValidationError) as caught:
            self._load_mutated(mutate)
        self.assertIn("unknown facet", str(caught.exception))

    def test_unknown_parent(self) -> None:
        def mutate(document: dict) -> None:
            for tag in document["tags"]:
                if tag["id"] == "genre.pop":
                    tag["parent"] = "genre.missing"

        with self.assertRaises(TaxonomyValidationError):
            self._load_mutated(mutate)

    def test_parent_outside_facet(self) -> None:
        def mutate(document: dict) -> None:
            for tag in document["tags"]:
                if tag["id"] == "genre.pop":
                    tag["parent"] = "mood.dark"

        with self.assertRaises(TaxonomyValidationError):
            self._load_mutated(mutate)

    def test_parent_in_flat_facet(self) -> None:
        def mutate(document: dict) -> None:
            for tag in document["tags"]:
                if tag["id"] == "mood.calm":
                    tag["parent"] = "mood.dark"

        with self.assertRaises(TaxonomyValidationError):
            self._load_mutated(mutate)

    def test_depth_beyond_facet_limit(self) -> None:
        def mutate(document: dict) -> None:
            document["tags"].append(
                {
                    "id": "genre.rock.punk.hardcore",
                    "facet": "genre",
                    "canonical_label": "Hardcore Punk",
                    "labels": {"en": "Hardcore Punk"},
                    "aliases": [],
                    "parent": "genre.rock.punk",
                }
            )

        with self.assertRaises(TaxonomyValidationError) as caught:
            self._load_mutated(mutate)
        self.assertIn("max_depth", str(caught.exception))

    def test_alias_collision(self) -> None:
        def mutate(document: dict) -> None:
            for tag in document["tags"]:
                if tag["id"] == "genre.pop":
                    tag["aliases"].append("Rap")

        with self.assertRaises(TaxonomyValidationError):
            self._load_mutated(mutate)

    def test_alias_shadowing_canonical_label(self) -> None:
        def mutate(document: dict) -> None:
            for tag in document["tags"]:
                if tag["id"] == "genre.pop":
                    tag["aliases"].append("Rock")

        with self.assertRaises(TaxonomyValidationError):
            self._load_mutated(mutate)

    def test_duplicate_canonical_label_in_facet(self) -> None:
        def mutate(document: dict) -> None:
            for tag in document["tags"]:
                if tag["id"] == "genre.pop":
                    tag["canonical_label"] = "Rock"
                    tag["labels"] = {"en": "Rock"}

        with self.assertRaises(TaxonomyValidationError):
            self._load_mutated(mutate)

    def test_missing_labels(self) -> None:
        def mutate(document: dict) -> None:
            document["tags"][0]["labels"] = {}

        with self.assertRaises(TaxonomyFormatError):
            self._load_mutated(mutate)

    def test_invalid_tag_id(self) -> None:
        def mutate(document: dict) -> None:
            document["tags"][0]["id"] = "genre.Bad Id"

        with self.assertRaises(TaxonomyFormatError):
            self._load_mutated(mutate)

    def test_tag_id_not_namespaced_under_facet(self) -> None:
        def mutate(document: dict) -> None:
            document["tags"][0]["id"] = "mood.rock"

        with self.assertRaises(TaxonomyFormatError):
            self._load_mutated(mutate)

    def test_empty_facets(self) -> None:
        def mutate(document: dict) -> None:
            document["facets"] = []

        with self.assertRaises(TaxonomyValidationError):
            self._load_mutated(mutate)

    def test_empty_tags(self) -> None:
        def mutate(document: dict) -> None:
            document["tags"] = []

        with self.assertRaises(TaxonomyValidationError):
            self._load_mutated(mutate)

    def test_unsupported_schema_version(self) -> None:
        def mutate(document: dict) -> None:
            document["schema_version"] = 2

        with self.assertRaises(TaxonomyFormatError):
            self._load_mutated(mutate)

    def test_bad_taxonomy_version_string(self) -> None:
        def mutate(document: dict) -> None:
            document["version"] = "one"

        with self.assertRaises(TaxonomyFormatError):
            self._load_mutated(mutate)

    def test_flat_facet_with_depth_two(self) -> None:
        def mutate(document: dict) -> None:
            for facet in document["facets"]:
                if facet["id"] == "mood":
                    facet["max_depth"] = 2

        with self.assertRaises(TaxonomyFormatError):
            self._load_mutated(mutate)

    def test_cycle_is_rejected(self) -> None:
        facets = (TaxonomyFacet(id="genre", label="Genre", hierarchy=True, max_depth=2),)
        tags = (
            TaxonomyTag(
                id="genre.a",
                facet="genre",
                canonical_label="A",
                labels={"en": "A"},
                parent="genre.b",
            ),
            TaxonomyTag(
                id="genre.b",
                facet="genre",
                canonical_label="B",
                labels={"en": "B"},
                parent="genre.a",
            ),
        )
        with self.assertRaises(TaxonomyValidationError) as caught:
            Taxonomy(version="1.0.0", name="Cycle", facets=facets, tags=tags)
        self.assertIn("cycle", str(caught.exception))

    def test_malformed_json(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "taxonomy.json"
            path.write_text("{not json", encoding="utf-8")
            with self.assertRaises(TaxonomyFormatError):
                TaxonomyLoader.load_file(path)

    def test_unsupported_suffix(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "taxonomy.txt"
            path.write_text("{}", encoding="utf-8")
            with self.assertRaises(TaxonomyFormatError):
                TaxonomyLoader.load_file(path)


if __name__ == "__main__":
    unittest.main()
