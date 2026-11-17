"""Music Tagger.

Phase 1 is a metadata-only, local-only tagger: existing filenames and embedded
tags are turned into taxonomy suggestions, a human reviews them in a local web
app, and the application layer (the only writer) applies accepted tags with a
mandatory backup and undo.

This package currently contains **only the shared contract layer and the repo
scaffold**. It deliberately has no suggestion logic, no tag writing, and no UI.
Those live in the engine and application packages that build on these contracts.

The contract documents are authoritative:

* ``CONTRACTS.md``  - taxonomy, engine, application and observability contracts.
* ``taxonomy/FORMAT.md`` - the versioned taxonomy data format.
"""

from __future__ import annotations

__version__ = "0.1.0"

__all__ = ["__version__"]
