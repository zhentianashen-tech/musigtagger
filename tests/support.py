"""Test doubles and fixtures shared by the application-layer tests.

No network, no mutagen, no audio codec: a :class:`FakeTagger` stores tags in a
deterministic trailer so the tests can exercise the real write path (backup,
temporary copy, verification, atomic replace, undo) and assert byte equality.
The real mutagen adapter is covered separately in ``test_tagio_mutagen.py``.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from musigtagger.app.config import AppConfig
from musigtagger.app.factory import AppContext, build_context
from musigtagger.app.ingest import ScanItem
from musigtagger.app.tagio import AudioProbe
from musigtagger.contracts import TagSuggestion, TrackDescriptor

REPO_ROOT = Path(__file__).resolve().parents[1]
TAXONOMY_DIR = REPO_ROOT / "taxonomy"
TAXONOMY_VERSION = "1.0.0"

MARKER = b"\n<<MUSICTAGGER-TAGS>>"


class FakeTagger:
    """A tag codec backed by a JSON trailer appended to the file.

    The write path always writes to a temporary copy whose name contains the
    target's name, so failure injection matches on the basename: register the
    target path and the temporary copy is affected too.
    """

    def __init__(self) -> None:
        self.write_error_on: set[str] = set()
        self.corrupt_on: set[str] = set()
        self.ignore_fields_on: set[str] = set()

    @staticmethod
    def _matches(path: str | Path, collection: set[str]) -> bool:
        name = Path(path).name
        return any(Path(entry).name in name for entry in collection)

    def read(self, path: str | Path) -> dict[str, list[str]]:
        data = Path(path).read_bytes()
        index = data.rfind(MARKER)
        if index < 0:
            return {}
        try:
            payload = json.loads(data[index + len(MARKER) :].decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return {}
        if not isinstance(payload, dict):
            return {}
        return {str(key): [str(value) for value in values] for key, values in payload.items()}

    def write(self, path: str | Path, fields) -> None:
        if self._matches(path, self.write_error_on):
            raise OSError("simulated write failure")
        stored = {} if self._matches(path, self.ignore_fields_on) else {
            str(key): [str(value) for value in values if str(value).strip()]
            for key, values in fields.items()
        }
        data = Path(path).read_bytes()
        index = data.rfind(MARKER)
        if index >= 0:
            data = data[:index]
        if self._matches(path, self.corrupt_on):
            data += b"CORRUPT-AUDIO"
        data += MARKER + json.dumps(stored, sort_keys=True).encode("utf-8") + b"\n"
        Path(path).write_bytes(data)

    def probe(self, path: str | Path) -> AudioProbe:
        data = Path(path).read_bytes()
        return AudioProbe(
            format="fake",
            duration_seconds=1.0 if b"CORRUPT-AUDIO" in data else 10.0,
            sample_rate=44100,
            channels=2,
            bitrate=128000,
            size_bytes=len(data),
        )

    def supports(self, path: str | Path) -> bool:
        return True


class StubScanner:
    """Descriptor builder for ``*.fake`` files in a directory tree."""

    def scan(self, root: Path):
        root = Path(root)
        if not root.is_dir():
            return
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.name.startswith("."):
                continue
            if path.suffix == ".ncm":
                yield ScanItem(
                    path=path,
                    error=(
                        "NetEase .ncm encrypted container: convert to FLAC/MP3 "
                        "first (step 0), then scan the converted tree"
                    ),
                    code="ncm_requires_conversion",
                )
                continue
            if path.suffix != ".fake":
                yield ScanItem(path=path, error="unsupported test container")
                continue
            stem = path.stem
            yield ScanItem(
                path=path,
                descriptor=TrackDescriptor(
                    path=str(path),
                    title=stem.replace("_", " "),
                    artist="Test Artist",
                    album="Test Album",
                    genre=None,
                    year=1999,
                    duration_seconds=10.0,
                    format="mp3",
                ),
                file_size_bytes=path.stat().st_size,
                mtime_ns=path.stat().st_mtime_ns,
            )


class StubProvider:
    """Deterministic provider used across tests."""

    def __init__(self, *, fail_on=None, tags=None) -> None:
        self.fail_on = set(fail_on or ())
        self.tags = tags or [
            ("genre.hip-hop", 0.9, "test.stub", "stub evidence"),
            ("era.1990s", 0.6, "test.stub", "stub evidence"),
        ]

    def suggest(self, track_descriptor: TrackDescriptor) -> list[TagSuggestion]:
        if track_descriptor.title in self.fail_on:
            raise RuntimeError("simulated provider failure")
        return [
            TagSuggestion(tag_id=tag_id, confidence=confidence, source=source, evidence=evidence)
            for tag_id, confidence, source, evidence in self.tags
        ]


def make_library(root: Path, count: int, *, content: str = "audio") -> list[Path]:
    root.mkdir(parents=True, exist_ok=True)
    paths = []
    for index in range(count):
        path = root / f"{index:03d}_track.fake"
        path.write_bytes(f"{content}-{index:03d}-".encode("utf-8") + b"\x00" * 32)
        paths.append(path)
    return paths


class AppTestCase(unittest.TestCase):
    """Base case: an isolated directory, config, and wired app context."""

    page_size = 25

    def setUp(self) -> None:
        self.tempdir = Path(tempfile.mkdtemp(prefix="musictagger-test-"))
        self.library = self.tempdir / "library"
        self.source = self.tempdir / "readonly-source"
        self.source.mkdir()
        self.tagger = FakeTagger()
        self.scanner = StubScanner()
        self.provider = StubProvider()
        self.config = AppConfig(
            library_root=self.library,
            database_path=self.tempdir / "library.sqlite3",
            backup_root=self.tempdir / "backups",
            events_path=self.tempdir / "events.jsonl",
            taxonomy_dir=TAXONOMY_DIR,
            taxonomy_version=TAXONOMY_VERSION,
            protected_roots=(self.source,),
            page_size=self.page_size,
        )
        self.context: AppContext = build_context(
            self.config,
            codec=self.tagger,
            scanner=self.scanner,
            providers=[("test.stub", self.provider)],
            run_id_factory=lambda: "run-test",
        )

    def tearDown(self) -> None:
        try:
            self.context.close()
        finally:
            shutil.rmtree(self.tempdir, ignore_errors=True)

    # helpers -----------------------------------------------------------

    def scan(self) -> object:
        return self.context.ingestion.scan(self.library)

    def review_all(self) -> int:
        return self.context.review.batch_accept(track_ids=self.all_track_ids())

    def all_track_ids(self) -> list[int]:
        return [int(row["id"]) for row in self.context.store.list_tracks(limit=1000)]

    def suggestion_rows(self, status: str | None = None):
        if status is None:
            return self.context.store.suggestions_with_status(
                ("suggested", "accepted", "edited", "rejected", "applied")
            )
        return self.context.store.suggestions_with_status((status,))

    def events(self) -> list[dict]:
        from musigtagger.app.events import read_events

        return read_events(self.config.events_path)

    def file_bytes(self, path) -> bytes:
        return Path(path).read_bytes()
