"""Versioned taxonomy data: value objects, validation, and the loader.

The taxonomy is data, not code. It is owned by the Tag Taxonomy Designer, read
by everyone else, and pinned by version for every run. This module defines the
in-memory shape, enforces structural integrity, and loads/serialises the
versioned document described in ``taxonomy/FORMAT.md``.

Nothing here changes the taxonomy at runtime: there is no mutation API.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Iterable, Mapping, Sequence

from .errors import (
    TaxonomyError,
    TaxonomyFormatError,
    TaxonomyValidationError,
    TaxonomyVersionAmbiguous,
    TaxonomyVersionMismatch,
    UnknownTagError,
)

#: Version of the *data format*, not of the taxonomy vocabulary. Bumping this
#: means the loader/schema changed; adding vocabulary bumps the taxonomy
#: ``version`` only. Taxonomy v1.0.0 must load with no change to this number.
SCHEMA_VERSION = 1

_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z][0-9A-Za-z.-]*)?$")
_FACET_ID_RE = re.compile(r"^[a-z][a-z0-9-]*$")
_TAG_ID_RE = re.compile(r"^[a-z][a-z0-9-]*(?:\.[a-z0-9][a-z0-9-]*)+$")

_SUPPORTED_SUFFIXES = (".json", ".yaml", ".yml")


def _normalise_text(value: Any, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{where} must be a non-empty string")
    return value.strip()


def _optional_text(value: Any, where: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{where} must be a string or null")
    return value.strip() or None


def _as_bool(value: Any, where: str, default: bool) -> bool:
    if value is None:
        return default
    if not isinstance(value, bool):
        raise ValueError(f"{where} must be a boolean")
    return value


@dataclass(frozen=True, slots=True)
class TaxonomyFacet:
    """One independent tagging dimension (genre, mood, ...)."""

    id: str
    label: str
    description: str = ""
    phase1_available: bool = True
    hierarchy: bool = False
    max_depth: int = 1
    open_set: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not _FACET_ID_RE.match(self.id):
            raise ValueError(
                f"facet id {self.id!r} must match {_FACET_ID_RE.pattern}"
            )
        if not isinstance(self.label, str) or not self.label.strip():
            raise ValueError(f"facet {self.id!r} has an empty label")
        if not isinstance(self.description, str):
            raise TypeError(f"facet {self.id!r} description must be a string")
        for name in ("phase1_available", "hierarchy", "open_set"):
            if not isinstance(getattr(self, name), bool):
                raise TypeError(f"facet {self.id!r} {name} must be a boolean")
        if isinstance(self.max_depth, bool) or not isinstance(self.max_depth, int):
            raise TypeError(f"facet {self.id!r} max_depth must be an integer")
        if self.max_depth < 1:
            raise ValueError(f"facet {self.id!r} max_depth must be >= 1")
        if not self.hierarchy and self.max_depth != 1:
            raise ValueError(
                f"facet {self.id!r} is flat but declares max_depth={self.max_depth}"
            )
        if self.open_set and self.hierarchy:
            raise ValueError(f"facet {self.id!r} is open_set and cannot be hierarchical")
        object.__setattr__(self, "label", self.label.strip())

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "description": self.description,
            "phase1_available": self.phase1_available,
            "hierarchy": self.hierarchy,
            "max_depth": self.max_depth,
            "open_set": self.open_set,
        }


@dataclass(frozen=True, slots=True)
class TaxonomyTag:
    """A single canonical tag inside a facet."""

    id: str
    facet: str
    canonical_label: str
    labels: Mapping[str, str] = field(default_factory=dict)
    aliases: tuple[str, ...] = ()
    parent: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not _TAG_ID_RE.match(self.id):
            raise ValueError(f"tag id {self.id!r} must match {_TAG_ID_RE.pattern}")
        if not isinstance(self.facet, str) or not _FACET_ID_RE.match(self.facet):
            raise ValueError(f"tag {self.id!r} has an invalid facet {self.facet!r}")
        if not self.id.startswith(f"{self.facet}."):
            raise ValueError(
                f"tag id {self.id!r} must be namespaced under its facet "
                f"({self.facet!r} + '.')"
            )
        object.__setattr__(
            self, "canonical_label", _normalise_text(self.canonical_label, "canonical_label")
        )

        labels = dict(self.labels)
        clean_labels: dict[str, str] = {}
        for language, label in labels.items():
            clean_labels[_normalise_text(language, f"tag {self.id!r} label language")] = (
                _normalise_text(label, f"tag {self.id!r} label for {language!r}")
            )
        if not clean_labels:
            raise ValueError(f"tag {self.id!r} must declare at least one label variant")
        object.__setattr__(self, "labels", MappingProxyType(clean_labels))

        if isinstance(self.aliases, str):
            raise TypeError(f"tag {self.id!r} aliases must be a sequence, not a string")
        aliases: list[str] = []
        seen_aliases: set[str] = set()
        for alias in self.aliases:
            clean = _normalise_text(alias, f"tag {self.id!r} alias")
            key = clean.casefold()
            if key == self.canonical_label.casefold():
                raise ValueError(
                    f"tag {self.id!r} alias {clean!r} duplicates its canonical label"
                )
            if key in seen_aliases:
                raise ValueError(f"tag {self.id!r} repeats alias {clean!r}")
            seen_aliases.add(key)
            aliases.append(clean)
        object.__setattr__(self, "aliases", tuple(aliases))

        parent = _optional_text(self.parent, f"tag {self.id!r} parent")
        object.__setattr__(self, "parent", parent)

    def display_label(self, language: str | None = None, *, fallback: bool = True) -> str:
        """Return the label variant for ``language``, falling back to canonical."""
        if language is not None:
            label = self.labels.get(language)
            if label is not None:
                return label
        if fallback:
            return self.canonical_label
        raise KeyError(
            f"tag {self.id!r} has no label for language {language!r}"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "facet": self.facet,
            "canonical_label": self.canonical_label,
            "labels": dict(self.labels),
            "aliases": list(self.aliases),
            "parent": self.parent,
        }


@dataclass(frozen=True, slots=True)
class Taxonomy:
    """A validated, immutable taxonomy snapshot.

    ``version`` is the value consumers must persist and pin (see CONTRACTS.md).
    """

    version: str
    name: str
    facets: tuple[TaxonomyFacet, ...]
    tags: tuple[TaxonomyTag, ...]
    canonical_label_policy: str = "native-original-language"
    schema_version: int = SCHEMA_VERSION
    description: str = ""
    _facets_by_id: Mapping[str, TaxonomyFacet] = field(
        init=False, repr=False, compare=False
    )
    _tags_by_id: Mapping[str, TaxonomyTag] = field(
        init=False, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        if not isinstance(self.version, str) or not _VERSION_RE.match(self.version):
            raise ValueError(
                f"taxonomy version {self.version!r} must look like "
                "'MAJOR.MINOR.PATCH[-suffix]'"
            )
        object.__setattr__(self, "name", _normalise_text(self.name, "taxonomy name"))
        if not isinstance(self.description, str):
            raise TypeError("taxonomy description must be a string")
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError(
                f"unsupported taxonomy schema_version {self.schema_version!r}; "
                f"this loader understands {SCHEMA_VERSION}"
            )
        if not isinstance(self.canonical_label_policy, str) or not (
            self.canonical_label_policy.strip()
        ):
            raise ValueError("canonical_label_policy must be a non-empty string")

        facets = tuple(self.facets)
        tags = tuple(self.tags)
        if not facets:
            raise TaxonomyValidationError("taxonomy must define at least one facet")
        if not tags:
            raise TaxonomyValidationError("taxonomy must define at least one tag")
        object.__setattr__(self, "facets", facets)
        object.__setattr__(self, "tags", tags)

        facets_by_id: dict[str, TaxonomyFacet] = {}
        for facet in facets:
            if facet.id in facets_by_id:
                raise TaxonomyValidationError(
                    f"duplicate facet id {facet.id!r}"
                )
            facets_by_id[facet.id] = facet
        tags_by_id: dict[str, TaxonomyTag] = {}
        for tag in tags:
            if tag.id in tags_by_id:
                raise TaxonomyValidationError(f"duplicate tag id {tag.id!r}")
            tags_by_id[tag.id] = tag
        object.__setattr__(self, "_facets_by_id", MappingProxyType(facets_by_id))
        object.__setattr__(self, "_tags_by_id", MappingProxyType(tags_by_id))

        problems = _collect_problems(facets_by_id, tags_by_id)
        if problems:
            raise TaxonomyValidationError("invalid taxonomy", problems=problems)

    # -- lookups ---------------------------------------------------------

    @property
    def facet_ids(self) -> tuple[str, ...]:
        return tuple(self._facets_by_id)

    def facet(self, facet_id: str) -> TaxonomyFacet:
        try:
            return self._facets_by_id[facet_id]
        except KeyError as exc:
            raise KeyError(f"unknown facet {facet_id!r}") from exc

    def has_facet(self, facet_id: str) -> bool:
        return facet_id in self._facets_by_id

    def tag(self, tag_id: str) -> TaxonomyTag:
        try:
            return self._tags_by_id[tag_id]
        except KeyError as exc:
            raise UnknownTagError([tag_id], taxonomy_version=self.version) from exc

    def has_tag(self, tag_id: str) -> bool:
        return tag_id in self._tags_by_id

    def tags_in_facet(self, facet_id: str) -> tuple[TaxonomyTag, ...]:
        if facet_id not in self._facets_by_id:
            raise KeyError(f"unknown facet {facet_id!r}")
        return tuple(tag for tag in self.tags if tag.facet == facet_id)

    def phase1_facets(self) -> tuple[TaxonomyFacet, ...]:
        return tuple(facet for facet in self.facets if facet.phase1_available)

    def __len__(self) -> int:
        return len(self.tags)

    # -- contract helpers -------------------------------------------------

    def unknown_tag_ids(self, tag_ids: Iterable[str]) -> tuple[str, ...]:
        """Return the ids in ``tag_ids`` that are not in this taxonomy."""
        if isinstance(tag_ids, str):
            raise TypeError("unknown_tag_ids expects an iterable of tag ids, not a string")
        unknown = [tag_id for tag_id in tag_ids if tag_id not in self._tags_by_id]
        return tuple(sorted(set(unknown)))

    def validate_tag_ids(self, tag_ids: Iterable[str]) -> None:
        """Raise :class:`UnknownTagError` if any reference is outside this version."""
        unknown = self.unknown_tag_ids(tag_ids)
        if unknown:
            raise UnknownTagError(unknown, taxonomy_version=self.version)

    def require_version(self, expected: str) -> None:
        """Raise unless this snapshot is exactly the pinned version."""
        if self.version != expected:
            raise TaxonomyVersionMismatch(expected, [self.version])

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "version": self.version,
            "name": self.name,
            "description": self.description,
            "canonical_label_policy": self.canonical_label_policy,
            "facets": [facet.to_dict() for facet in self.facets],
            "tags": [tag.to_dict() for tag in self.tags],
        }


def _collect_problems(
    facets: Mapping[str, TaxonomyFacet],
    tags: Mapping[str, TaxonomyTag],
) -> list[str]:
    problems: list[str] = []
    canonical_by_facet: dict[str, dict[str, str]] = {}
    alias_by_facet: dict[str, dict[str, str]] = {}

    # Pass 1: facet references, canonical-label uniqueness, alias uniqueness.
    for tag in tags.values():
        facet = facets.get(tag.facet)
        if facet is None:
            problems.append(f"tag {tag.id!r} references unknown facet {tag.facet!r}")
            continue

        canonical = canonical_by_facet.setdefault(tag.facet, {})
        canonical_key = tag.canonical_label.casefold()
        previous = canonical.get(canonical_key)
        if previous is not None and previous != tag.id:
            problems.append(
                f"tags {previous!r} and {tag.id!r} in facet {tag.facet!r} "
                f"share canonical label {tag.canonical_label!r}"
            )
        canonical[canonical_key] = tag.id

        aliases = alias_by_facet.setdefault(tag.facet, {})
        for alias in tag.aliases:
            alias_key = alias.casefold()
            previous = aliases.get(alias_key)
            if previous is not None and previous != tag.id:
                problems.append(
                    f"alias {alias!r} maps to both {previous!r} and {tag.id!r} "
                    f"in facet {tag.facet!r}"
                )
            aliases[alias_key] = tag.id

    # Pass 2: aliases may not shadow another tag's canonical label, whichever
    # order the two tags appear in.
    for facet_id, aliases in alias_by_facet.items():
        canonical = canonical_by_facet.get(facet_id, {})
        for alias_key, tag_id in aliases.items():
            canonical_owner = canonical.get(alias_key)
            if canonical_owner is not None and canonical_owner != tag_id:
                problems.append(
                    f"tag {tag_id!r} alias {alias_key!r} collides with the "
                    f"canonical label of {canonical_owner!r}"
                )

    # Pass 3: parent relationships, depth, and cycles.
    for tag in tags.values():
        facet = facets.get(tag.facet)
        if facet is None:
            continue
        if tag.parent is None:
            continue
        if not facet.hierarchy:
            problems.append(
                f"tag {tag.id!r} has parent {tag.parent!r} but facet "
                f"{tag.facet!r} is flat"
            )
            continue
        parent = tags.get(tag.parent)
        if parent is None:
            problems.append(f"tag {tag.id!r} has unknown parent {tag.parent!r}")
            continue
        if parent.facet != tag.facet:
            problems.append(
                f"tag {tag.id!r} parent {tag.parent!r} is in facet {parent.facet!r}"
            )
            continue

    # Depth and cycle checks are separate from the parent-existence pass so
    # every problem in a broken file is reported at once.
    for tag in tags.values():
        facet = facets.get(tag.facet)
        if facet is None:
            continue
        depth = 1
        seen = {tag.id}
        current = tag
        while current.parent is not None:
            parent = tags.get(current.parent)
            if parent is None:
                break
            depth += 1
            if parent.id in seen:
                problems.append(f"tag {tag.id!r} is part of a parent cycle")
                break
            seen.add(parent.id)
            current = parent
        if depth > facet.max_depth:
            problems.append(
                f"tag {tag.id!r} is at depth {depth}, exceeding facet "
                f"{facet.id!r} max_depth={facet.max_depth}"
            )

    return problems


# ---------------------------------------------------------------------------
# Parsing / loading
# ---------------------------------------------------------------------------


def _require_mapping(value: Any, where: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TaxonomyFormatError(f"{where} must be an object")
    return value


def _require_list(value: Any, where: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise TaxonomyFormatError(f"{where} must be a list")
    return value


def _parse_facet(raw: Any, source: str, index: int) -> TaxonomyFacet:
    where = f"{source}: facets[{index}]"
    data = _require_mapping(raw, where)
    try:
        facet = TaxonomyFacet(
            id=data.get("id"),  # type: ignore[arg-type]
            label=data.get("label"),  # type: ignore[arg-type]
            description=data.get("description", "") or "",
            phase1_available=_as_bool(
                data.get("phase1_available"), f"{where}.phase1_available", True
            ),
            hierarchy=_as_bool(data.get("hierarchy"), f"{where}.hierarchy", False),
            max_depth=data.get("max_depth", 1),
            open_set=_as_bool(data.get("open_set"), f"{where}.open_set", False),
        )
    except (TypeError, ValueError) as exc:
        raise TaxonomyFormatError(f"{where}: {exc}") from exc
    return facet


def _parse_label_map(raw: Any, where: str) -> dict[str, str]:
    data = _require_mapping(raw, where)
    labels: dict[str, str] = {}
    for language, label in data.items():
        if not isinstance(language, str) or not language.strip():
            raise TaxonomyFormatError(f"{where} keys must be non-empty language tags")
        if not isinstance(label, str) or not label.strip():
            raise TaxonomyFormatError(
                f"{where}[{language!r}] must be a non-empty string"
            )
        labels[language] = label
    return labels


def _parse_tag(raw: Any, source: str, index: int) -> TaxonomyTag:
    where = f"{source}: tags[{index}]"
    data = _require_mapping(raw, where)
    aliases = data.get("aliases", [])
    alias_values = _require_list(aliases, f"{where}.aliases")
    if not all(isinstance(alias, str) for alias in alias_values):
        raise TaxonomyFormatError(f"{where}.aliases must be strings")
    try:
        return TaxonomyTag(
            id=data.get("id"),  # type: ignore[arg-type]
            facet=data.get("facet"),  # type: ignore[arg-type]
            canonical_label=data.get("canonical_label"),  # type: ignore[arg-type]
            labels=_parse_label_map(data.get("labels", {}), f"{where}.labels"),
            aliases=tuple(alias_values),
            parent=data.get("parent"),
        )
    except (TypeError, ValueError) as exc:
        raise TaxonomyFormatError(f"{where}: {exc}") from exc


def _parse_document(document: Any, *, source: str) -> Taxonomy:
    data = _require_mapping(document, source)
    schema_version = data.get("schema_version")
    if isinstance(schema_version, bool) or schema_version != SCHEMA_VERSION:
        raise TaxonomyFormatError(
            f"{source}: unsupported schema_version {schema_version!r}; "
            f"expected {SCHEMA_VERSION}"
        )
    version = data.get("version")
    if not isinstance(version, str) or not _VERSION_RE.match(version):
        raise TaxonomyFormatError(
            f"{source}: version must look like 'MAJOR.MINOR.PATCH[-suffix]'"
        )
    name = data.get("name")
    if not isinstance(name, str) or not name.strip():
        raise TaxonomyFormatError(f"{source}: name must be a non-empty string")
    description = data.get("description", "")
    if not isinstance(description, str):
        raise TaxonomyFormatError(f"{source}: description must be a string")
    policy = data.get("canonical_label_policy", "native-original-language")
    if not isinstance(policy, str) or not policy.strip():
        raise TaxonomyFormatError(
            f"{source}: canonical_label_policy must be a non-empty string"
        )

    raw_facets = _require_list(data.get("facets"), f"{source}: facets")
    raw_tags = _require_list(data.get("tags"), f"{source}: tags")
    facets = tuple(
        _parse_facet(raw, source, index) for index, raw in enumerate(raw_facets)
    )
    tags = tuple(_parse_tag(raw, source, index) for index, raw in enumerate(raw_tags))

    try:
        return Taxonomy(
            version=version,
            name=name,
            description=description,
            facets=facets,
            tags=tags,
            canonical_label_policy=policy,
            schema_version=schema_version,
        )
    except TaxonomyValidationError as exc:
        raise TaxonomyValidationError(
            f"{source}: {exc.base_message}", problems=exc.problems
        ) from exc
    except (TypeError, ValueError) as exc:
        raise TaxonomyValidationError(f"{source}: {exc}") from exc


class TaxonomyLoader:
    """Loads and serialises taxonomy documents.

    Consumers must pin a version through :meth:`load`. ``load_file`` exists for
    tooling and tests; application code should use ``load(directory,
    version=...)`` so an accidental taxonomy upgrade cannot change behaviour.
    """

    @classmethod
    def load_file(cls, path: str | Path) -> Taxonomy:
        path = Path(path)
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise TaxonomyError(f"taxonomy file not found: {path}") from exc
        except OSError as exc:
            raise TaxonomyError(f"cannot read taxonomy file {path}: {exc}") from exc

        suffix = path.suffix.lower()
        if suffix == ".json":
            try:
                document = json.loads(text)
            except json.JSONDecodeError as exc:
                raise TaxonomyFormatError(
                    f"{path}: invalid JSON at line {exc.lineno}, "
                    f"column {exc.colno}: {exc.msg}"
                ) from exc
        elif suffix in (".yaml", ".yml"):
            try:
                import yaml  # type: ignore[import-not-found]
            except ImportError as exc:  # pragma: no cover - depends on extras
                raise TaxonomyFormatError(
                    f"{path}: reading YAML taxonomies requires PyYAML; "
                    "install 'musigtagger[yaml]' or commit the taxonomy as JSON"
                ) from exc
            try:
                document = yaml.safe_load(text)
            except Exception as exc:  # noqa: BLE001 - yaml error types vary
                raise TaxonomyFormatError(f"{path}: invalid YAML: {exc}") from exc
        else:
            raise TaxonomyFormatError(
                f"{path}: unsupported taxonomy file type {suffix!r}; "
                f"expected one of {', '.join(_SUPPORTED_SUFFIXES)}"
            )
        return _parse_document(document, source=str(path))

    @classmethod
    def _taxonomy_files(cls, directory: Path) -> tuple[Path, ...]:
        if not directory.is_dir():
            raise TaxonomyError(f"taxonomy directory not found: {directory}")
        return tuple(
            sorted(
                path
                for path in directory.iterdir()
                if path.is_file()
                and path.suffix.lower() in _SUPPORTED_SUFFIXES
                and path.stem.startswith("taxonomy-")
            )
        )

    @classmethod
    def available_versions(cls, directory: str | Path) -> tuple[str, ...]:
        """Return the versions of every taxonomy document in ``directory``."""
        return tuple(
            cls.load_file(path).version
            for path in cls._taxonomy_files(Path(directory))
        )

    @classmethod
    def load(cls, directory: str | Path, *, version: str) -> Taxonomy:
        """Load the taxonomy document in ``directory`` whose version is ``version``.

        ``version`` is keyword-only and required: pinning is part of the
        contract, not an optional convenience.
        """
        directory = Path(directory)
        available: list[str] = []
        matches: list[tuple[Path, Taxonomy]] = []
        for path in cls._taxonomy_files(directory):
            taxonomy = cls.load_file(path)
            available.append(taxonomy.version)
            if taxonomy.version == version:
                matches.append((path, taxonomy))
        if not matches:
            raise TaxonomyVersionMismatch(version, available)
        if len(matches) > 1:
            raise TaxonomyVersionAmbiguous(
                version, [str(path) for path, _ in matches]
            )
        return matches[0][1]

    @classmethod
    def dumps(cls, taxonomy: Taxonomy) -> str:
        """Serialise ``taxonomy`` to canonical JSON text."""
        return json.dumps(
            taxonomy.to_dict(), indent=2, ensure_ascii=False, sort_keys=False
        ) + "\n"

    @classmethod
    def dump(cls, taxonomy: Taxonomy, path: str | Path) -> None:
        """Write ``taxonomy`` as canonical JSON (regardless of file suffix)."""
        Path(path).write_text(cls.dumps(taxonomy), encoding="utf-8")
