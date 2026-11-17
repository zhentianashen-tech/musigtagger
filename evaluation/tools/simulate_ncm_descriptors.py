"""Diagnostic: provider output if the NCM metadata-bearing library were frozen.

Builds TrackDescriptors from the real NCM metadata (title/artist/album, no
genre/date — NCM carries neither) and calls the pure provider. This isolates
"what would preserving metadata buy us?" from the conversion itself.
"""

import json
from collections import Counter
from pathlib import Path

from musigtagger.contracts import TaxonomyLoader, TrackDescriptor
from musigtagger.engine import MetadataSuggestionProvider

WORK = Path(__file__).resolve().parent
NCM = json.loads((WORK / "ncm-metadata.json").read_text(encoding="utf-8"))

tax = TaxonomyLoader.load("/tmp/musi13/taxonomy", version="1.0.0")
provider = MetadataSuggestionProvider(tax)

rows = []
for t in NCM["tracks"]:
    stem = t["file"].rsplit(".", 1)[0]
    descriptor = TrackDescriptor(
        path=f"/test-data/music-working/eval-converted/{stem}.mp3",
        title=t["title"],
        artist=t["artist"],
        album=t["album"],
        genre=None,
        year=None,
        duration_seconds=(t["duration_ms"] or 0) / 1000,
        format="mp3",
    )
    suggestions = [
        {"tag_id": s.tag_id, "confidence": s.confidence, "source": s.source, "evidence": s.evidence}
        for s in provider.suggest(descriptor)
    ]
    rows.append(
        {
            "ncm_file": t["file"],
            "title": t["title"],
            "artist": t["artist"],
            "album": t["album"],
            "suggestions": suggestions,
        }
    )

summary = {
    "descriptors": len(rows),
    "unique_works": len({r["title"] for r in rows}),
    "tracks_with_suggestion": sum(1 for r in rows if r["suggestions"]),
    "total_suggestions": sum(len(r["suggestions"]) for r in rows),
    "by_tag": dict(Counter(s["tag_id"] for r in rows for s in r["suggestions"])),
    "by_source": dict(Counter(s["source"] for r in rows for s in r["suggestions"])),
    "note": (
        "NCM metadata has title/artist/album but no genre and no release date. The provider "
        "consumes only descriptor.genre, descriptor.year and the path, so the metadata-bearing "
        "library yields the same 5 path-word suggestions as the tagless FLAC set."
    ),
}
dest = WORK / "eval-run" / "provider-on-ncm-metadata.json"
dest.write_text(json.dumps({"summary": summary, "tracks": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(summary, ensure_ascii=False, indent=2))
