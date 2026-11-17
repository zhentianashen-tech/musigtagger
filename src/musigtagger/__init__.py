"""Music Tagger.

Phase 1 is a metadata-only, local-only tagger: existing filenames and embedded
tags are turned into taxonomy suggestions, a human reviews them in a local web
app, and the application layer (the only writer) applies accepted tags with a
mandatory backup and undo.

The package contains the shared contracts and the Phase 1 metadata engine.
Tag writing and UI remain in the separate application layer.

The contract documents are authoritative:

* ``CONTRACTS.md``  - taxonomy, engine, application and observability contracts.
* ``taxonomy/FORMAT.md`` - the versioned taxonomy data format.
"""

from __future__ import annotations

__version__ = "0.1.0"

__all__ = ["__version__"]
