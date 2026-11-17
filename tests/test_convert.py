"""Batch conversion step: persistent output tree, source safety, isolation."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from musigtagger.app.config import AppConfig, ProtectedPathError
from musigtagger.app.convert import (
    ConversionError,
    ConversionService,
    ConverterUnavailableError,
    EngineNcmConverter,
    UnsupportedOutputError,
    load_converter,
    sniff_audio_suffix,
)

from support import TAXONOMY_DIR, TAXONOMY_VERSION


class FakeNcmConverter:
    """Writes a decoy audio stream based on the fixture's marker."""

    def __init__(self, fail_on: set[str] | None = None) -> None:
        self.fail_on = set(fail_on or ())

    def __call__(self, source: str | Path, destination: str | Path) -> Path:
        source = Path(source)
        destination = Path(destination)
        if source.name in self.fail_on:
            raise RuntimeError("simulated decoder failure")
        data = source.read_bytes()
        if data.startswith(b"NCMFLAC"):
            payload = b"fLaC" + data[len(b"NCMFLAC") :]
        elif data.startswith(b"NCMMP3"):
            payload = b"ID3\x04" + data[len(b"NCMMP3") :]
        else:
            payload = data
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(payload)
        return destination


class ConversionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = Path(tempfile.mkdtemp(prefix="musictagger-convert-"))
        self.source = self.tempdir / "source"
        self.output = self.tempdir / "converted"
        self.protected = self.tempdir / "readonly-source"
        self.protected.mkdir()
        self.source.mkdir()
        self.config = AppConfig(
            library_root=self.source,
            database_path=self.tempdir / "library.sqlite3",
            backup_root=self.tempdir / "backups",
            events_path=self.tempdir / "events.jsonl",
            taxonomy_dir=TAXONOMY_DIR,
            taxonomy_version=TAXONOMY_VERSION,
            protected_roots=(self.protected,),
        )
        self.converter = FakeNcmConverter()
        self.service = ConversionService(self.config, self.converter)

    def tearDown(self) -> None:
        import shutil

        shutil.rmtree(self.tempdir, ignore_errors=True)

    def _ncm(self, relative: str, kind: str = "flac") -> Path:
        path = self.source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        marker = b"NCMFLAC" if kind == "flac" else b"NCMMP3"
        path.write_bytes(marker + f"payload:{relative}".encode())
        return path

    def test_converts_a_tree_into_persistent_audio(self) -> None:
        first = self._ncm("album/one.ncm", "flac")
        second = self._ncm("two.ncm", "mp3")
        originals = {path: path.read_bytes() for path in (first, second)}
        (self.source / "cover.jpg").write_bytes(b"jpeg")
        hidden = self.source / ".hidden" / "ignored.ncm"
        hidden.parent.mkdir()
        hidden.write_bytes(b"NCMFLACignored")

        report = self.service.convert_tree(self.source, self.output)

        self.assertEqual(report.converted_count, 2)
        self.assertEqual(len(report.skipped), 0)
        self.assertEqual(len(report.failed), 0)
        self.assertTrue((self.output / "album" / "one.flac").is_file())
        self.assertTrue((self.output / "two.mp3").is_file())
        self.assertEqual(
            (self.output / "album" / "one.flac").read_bytes()[:4], b"fLaC"
        )
        self.assertEqual((self.output / "two.mp3").read_bytes()[:3], b"ID3")
        self.assertFalse((self.output / ".hidden").exists())
        # The source is read-only to this step: bytes and tree are unchanged.
        for path, original in originals.items():
            self.assertEqual(path.read_bytes(), original)
        self.assertEqual(
            sorted(path.name for path in self.source.iterdir()),
            [".hidden", "album", "cover.jpg", "two.ncm"],
        )
        # No temporary leftovers, and the report is persistent JSON.
        self.assertEqual(list(self.output.rglob("*.partial")), [])
        report_path = Path(report.report_path or "")
        self.assertTrue(report_path.is_file())
        payload = json.loads(report_path.read_text())
        self.assertEqual(payload["schema"], "musigtagger.conversion.v1")
        self.assertEqual(payload["counts"]["converted"], 2)

    def test_existing_outputs_are_skipped_unless_forced(self) -> None:
        self._ncm("one.ncm")
        first = self.service.convert_tree(self.source, self.output)
        self.assertEqual(first.converted_count, 1)

        second = self.service.convert_tree(self.source, self.output)
        self.assertEqual(second.converted_count, 0)
        self.assertEqual(len(second.skipped), 1)
        self.assertEqual(second.skipped[0].format, "flac")

        forced = self.service.convert_tree(self.source, self.output, force=True)
        self.assertEqual(forced.converted_count, 1)

    def test_a_failing_file_does_not_abort_the_batch(self) -> None:
        self._ncm("good.ncm")
        self._ncm("broken.ncm")
        service = ConversionService(
            self.config, FakeNcmConverter(fail_on={"broken.ncm"})
        )
        report = service.convert_tree(self.source, self.output)
        self.assertEqual(report.converted_count, 1)
        self.assertEqual(len(report.failed), 1)
        self.assertIn("simulated decoder failure", report.failed[0].error or "")
        self.assertTrue((self.output / "good.flac").is_file())
        self.assertFalse((self.output / "broken.flac").exists())
        self.assertEqual(list(self.output.rglob("*.partial")), [])

    def test_unrecognised_converter_output_is_a_per_file_failure(self) -> None:
        self._ncm("weird.ncm")

        def garbage(source, destination):
            Path(destination).write_bytes(b"not audio at all")
            return Path(destination)

        report = ConversionService(self.config, garbage).convert_tree(
            self.source, self.output
        )
        self.assertEqual(len(report.failed), 1)
        self.assertIn("not a recognised", report.failed[0].error or "")
        self.assertFalse((self.output / "weird.mp3").exists())

    def test_output_inside_source_is_refused(self) -> None:
        with self.assertRaises(ConversionError):
            self.service.convert_tree(self.source, self.source / "converted")

    def test_source_inside_output_is_refused(self) -> None:
        with self.assertRaises(ConversionError):
            self.service.convert_tree(self.source, self.tempdir)

    def test_protected_read_only_output_is_refused(self) -> None:
        with self.assertRaises(ProtectedPathError):
            self.service.convert_tree(self.source, self.protected / "converted")
        self.assertEqual(list(self.protected.iterdir()), [])

    def test_missing_source_is_refused(self) -> None:
        with self.assertRaises(ConversionError):
            self.service.convert_tree(self.tempdir / "missing", self.output)

    def test_limit_converts_a_sample_only(self) -> None:
        for index in range(5):
            self._ncm(f"{index}.ncm")
        report = self.service.convert_tree(self.source, self.output, limit=2)
        self.assertEqual(len(report.outcomes), 2)
        self.assertEqual(report.converted_count, 2)

    def test_sniffing(self) -> None:
        cases = {
            b"fLaC" + b"\x00" * 8: ".flac",
            b"ID3\x04" + b"\x00" * 8: ".mp3",
            b"\xff\xfb\x90\x00" + b"\x00" * 8: ".mp3",
            b"OggS" + b"\x00" * 8: ".ogg",
        }
        for payload, expected in cases.items():
            path = self.tempdir / "probe.bin"
            path.write_bytes(payload)
            self.assertEqual(sniff_audio_suffix(path), expected)
        path = self.tempdir / "probe.bin"
        path.write_bytes(b"garbage")
        with self.assertRaises(UnsupportedOutputError):
            sniff_audio_suffix(path)

    def test_engine_adapter_uses_the_decoded_payload_extension(self) -> None:
        class FakeTrack:
            extension = ".flac"

        class FakeModule:
            def __init__(self) -> None:
                self.written: list[Path] = []

            def decode(self, source):
                return FakeTrack()

            def convert(self, track, output):
                output = Path(output)
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_bytes(b"fLaC" + b"payload")
                self.written.append(output)
                return output

        module = FakeModule()
        self._ncm("one.ncm", "mp3")  # source marker is irrelevant to the adapter
        report = ConversionService(
            self.config, EngineNcmConverter(module)
        ).convert_tree(self.source, self.output)
        self.assertEqual(report.converted_count, 1)
        self.assertTrue((self.output / "one.flac").is_file())
        self.assertFalse((self.output / "one.mp3").exists())
        # The engine got a temporary target with the payload's suffix, not
        # the decoder-agnostic ".partial" name.
        self.assertEqual(module.written[0].suffix, ".flac")
        self.assertTrue(module.written[0].name.startswith(".one."))
        self.assertFalse(module.written[0].exists())

    def test_engine_adapter_rejects_a_module_without_the_api(self) -> None:
        with self.assertRaises(ConverterUnavailableError):
            EngineNcmConverter(object())

    def test_missing_decoder_error_is_actionable(self) -> None:
        with self.assertRaises(ConverterUnavailableError) as raised:
            load_converter("definitely.not.a.module:convert_file")
        self.assertIn("MUSI-12", str(raised.exception))

    def test_converter_spec_is_part_of_the_config(self) -> None:
        config = AppConfig.from_mapping(
            {"ncm_converter_spec": "my.module:convert"}
        )
        self.assertEqual(config.ncm_converter_spec, "my.module:convert")
