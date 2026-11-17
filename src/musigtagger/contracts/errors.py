"""Exceptions shared across the contract layer.

The application layer is expected to catch :class:`ContractError` (or the
narrower taxonomy errors) and translate them into a user-facing error plus a
recoverable state. None of these errors imply a partial file write.
"""

from __future__ import annotations

from typing import Iterable, Sequence


class ContractError(Exception):
    """Base class for every error defined by the shared contracts."""


class TaxonomyError(ContractError):
    """Base class for taxonomy loading and validation errors."""


class TaxonomyFormatError(TaxonomyError):
    """The taxonomy document is malformed (bad JSON/YAML, wrong shape/types)."""


class TaxonomyValidationError(TaxonomyError):
    """The taxonomy document parsed but violates a structural rule."""

    def __init__(self, message: str, *, problems: Sequence[str] = ()) -> None:
        self.base_message = message
        self.problems: tuple[str, ...] = tuple(problems)
        rendered = message
        if self.problems:
            detail = "\n".join(f"  - {problem}" for problem in self.problems)
            rendered = f"{message}:\n{detail}"
        super().__init__(rendered)


class TaxonomyVersionMismatch(TaxonomyError):
    """No taxonomy with the pinned version was found.

    Consumers must pin a version; loading "whatever is newest" is not a
    supported operation (see CONTRACTS.md, taxonomy contract).
    """

    def __init__(self, expected: str, available: Iterable[str]) -> None:
        self.expected = expected
        self.available = tuple(available)
        available_text = ", ".join(self.available) if self.available else "(none)"
        super().__init__(
            f"taxonomy version {expected!r} is not available; "
            f"available versions: {available_text}"
        )


class TaxonomyVersionAmbiguous(TaxonomyError):
    """More than one file in a taxonomy directory carries the pinned version."""

    def __init__(self, version: str, paths: Iterable[str]) -> None:
        self.version = version
        self.paths = tuple(paths)
        super().__init__(
            f"taxonomy version {version!r} is defined more than once: "
            + ", ".join(self.paths)
        )


class UnknownTagError(ContractError):
    """A tag id does not exist in the pinned taxonomy version."""

    def __init__(self, unknown_tag_ids: Iterable[str], *, taxonomy_version: str) -> None:
        self.unknown_tag_ids: tuple[str, ...] = tuple(sorted(set(unknown_tag_ids)))
        self.taxonomy_version = taxonomy_version
        super().__init__(
            "unknown tag id(s) under taxonomy "
            f"{taxonomy_version}: " + ", ".join(self.unknown_tag_ids)
        )
