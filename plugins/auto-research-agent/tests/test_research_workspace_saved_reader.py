"""Offline reader regressions for rerunning complete saved-source archives."""

import json
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path


sys.path.insert(0, str(Path(__file__).parents[1] / "cli"))

import test_research_workspace_view as view_fixture
from research_workspace.source_rerun import attach_rerun, build_rerun
from stage1_deliverable.common import DeliverableError, canonical, sha
from stage1_deliverable.sources import receipt_digest


PARSER = b"""from dataclasses import dataclass

@dataclass
class Item:
    text: str
    evidence_level: str
    observed_title: str
    observed_doi: str
    locators: list
    diagnostics: dict
    bibliographic_metadata: dict

def _extract_html(raw, url):
    text = "Evidence saved full text"
    return Item(text, "full-text", "Evidence", "10.1000/synthetic",
                [{"start": 0, "end": len(text), "type": "text", "value": "body"}],
                {"parser": "synthetic-local"},
                {"title": "Evidence", "doi": "10.1000/synthetic", "volume": "7"})

def _extract_pdf(raw):
    raise RuntimeError("PDF is outside this synthetic fixture")

def _identity(expected_doi, expected_title, observed_doi, observed_title):
    return "consistent" if expected_title == observed_title else "mismatch"
"""


def receipt(source_id, raw, *, status, http_status, attempts=1):
    url = f"https://example.test/{source_id}"
    rows = []
    if attempts == 2:
        rows.append(
            {
                "sequence": 1,
                "purpose": "synthetic redirect",
                "url": url,
                "final_url": url + "/moved",
                "requested_at": "2026-10-06T00:00:00Z",
                "received_at": "2026-10-06T00:00:01Z",
                "http_status": 302,
                "content_type": "text/html",
                "outcome": "redirect",
                "response_bytes": 0,
                "response_truncated": False,
                "raw_path": None,
                "raw_sha256": None,
                "error": None,
            }
        )
    rows.append(
        {
            "sequence": len(rows) + 1,
            "purpose": "synthetic saved response",
            "url": url,
            "final_url": url + "/final",
            "requested_at": "2026-10-06T00:00:02Z",
            "received_at": "2026-10-06T00:00:03Z",
            "http_status": http_status,
            "content_type": "text/html",
            "outcome": status,
            "response_bytes": len(raw),
            "response_truncated": False,
            "raw_path": "saved.html",
            "raw_sha256": sha(raw),
            "error": None,
        }
    )
    value = {
        "schema_version": "source-fetch-result/v1",
        "request": {
            "operation": "fetch",
            "doi": None,
            "url": url,
            "title": source_id,
            "output_dir": f"/synthetic/{source_id}",
            "public_only": True,
        },
        "receipt_sha256": "",
        "status": status,
        "evidence_level": "metadata",
        "source_url": url,
        "final_url": url + "/final",
        "retrieved_at": "2026-10-06T00:00:03Z",
        "expected_identity": {"doi": None, "title": source_id},
        "observed_identity": {"doi": None, "title": None},
        "identity_status": "unverified",
        "source_version": "sha256:" + sha(raw),
        "attempts": rows,
        "raw_path": "saved.html",
        "raw_sha256": sha(raw),
        "extracted_text_path": None,
        "extracted_text_sha256": None,
        "locators": [],
        "errors": [],
        "output_dir": f"/synthetic/{source_id}",
    }
    value["receipt_sha256"] = receipt_digest(value)
    return value


class SavedReaderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(
            prefix="saved-reader-", dir=Path(tempfile.gettempdir()).resolve()
        )
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.package = self.root / "package"
        self.package.mkdir()
        self.parser = self.root / "parser.py"
        self.parser.write_bytes(PARSER)
        self.parser_sha = sha(PARSER)
        self.raw = {
            "source-0": b"<html><body>successful saved response</body></html>",
            "source-1": b"<html><body>forbidden saved response</body></html>",
        }
        self.index = view_fixture.fixture_index()
        receipts = (
            receipt(
                "source-0",
                self.raw["source-0"],
                status="available",
                http_status=200,
                attempts=2,
            ),
            receipt(
                "source-1", self.raw["source-1"], status="paywalled", http_status=403
            ),
        )
        self.index["sources"] = []
        for number, saved in enumerate(receipts):
            archive = self.package / "deliverable/sources" / f"source-{number}"
            archive.mkdir(parents=True)
            (archive / "original.json").write_bytes(canonical(saved))
            (archive / "saved.html").write_bytes(self.raw[f"source-{number}"])
            self.index["sources"].append(
                {
                    "source_id": f"source-{number}",
                    "work_id": f"fixture-{number}",
                    "version_id": f"version-{number}",
                    "receipt": saved,
                    "result_sha256": sha(canonical(saved)),
                }
            )

    def build(self, name="rerun"):
        output = self.root / name
        digest = build_rerun(
            self.index, self.package, output, self.parser, self.parser_sha
        )
        manifest = json.loads((output / "source-rerun-manifest.json").read_bytes())
        return output, digest, manifest

    def test_success_and_non200_preserve_saved_attempt_history(self):
        output, digest, manifest = self.build()
        attach_rerun(self.index, output, digest)
        self.assertEqual(digest, sha(canonical(manifest)))
        success, inaccessible = manifest["data"]["rows"]
        self.assertEqual(
            success["original_attempts"],
            self.index["sources"][0]["receipt"]["attempts"],
        )
        self.assertEqual(success["reading"]["status"], "extracted")
        self.assertEqual(success["metadata"]["doi"], "10.1000/synthetic")
        self.assertEqual(success["metadata"]["volume"], "7")
        self.assertEqual(inaccessible["reading"]["status"], "inaccessible")
        self.assertEqual(inaccessible["reading"]["error"]["type"], "PermissionError")

    def test_parser_hash_is_pinned_before_reading_sources(self):
        with self.assertRaisesRegex(DeliverableError, "parser hash differs"):
            build_rerun(
                self.index,
                self.package,
                self.root / "wrong-parser",
                self.parser,
                "0" * 64,
            )

    def test_changed_saved_source_bytes_are_rejected(self):
        path = self.package / "deliverable/sources/source-0/saved.html"
        path.write_bytes(b"changed after receipt")
        with self.assertRaisesRegex(DeliverableError, "raw source hash differs"):
            build_rerun(
                self.index,
                self.package,
                self.root / "changed-source",
                self.parser,
                self.parser_sha,
            )


def _bind_history(reader):
    source = reader.index["sources"][0]
    saved = source["receipt"]
    saved["receipt_sha256"] = receipt_digest(saved)
    original = canonical(saved)
    (reader.package / "deliverable/sources/source-0/original.json").write_bytes(
        original
    )
    source["result_sha256"] = sha(original)


def _offline_reader(test_case):
    reader = SavedReaderTests()
    reader.setUp()
    test_case.addCleanup(reader.doCleanups)
    source = reader.index["sources"][0]
    acquisition = source["receipt"]["attempts"][-1]
    offline = deepcopy(acquisition)
    offline.update(
        sequence=acquisition["sequence"] + 1,
        purpose="offline-parser-replay",
        http_status=None,
        outcome="parsed",
        raw_path="replay.html",
    )
    source["receipt"]["attempts"].append(offline)
    (reader.package / "deliverable/sources/source-0/replay.html").write_bytes(
        reader.raw["source-0"]
    )
    _bind_history(reader)
    return reader


class OfflineHistoryTests(unittest.TestCase):
    def test_offline_history_replays_matching_actual_body_without_new_access(self):
        for level in ["full-text", "abstract"]:
            with self.subTest(level=level):
                offline_reader = _offline_reader(self)
                reader = offline_reader
                parser = PARSER.replace(b'"full-text"', f'"{level}"'.encode())
                reader.parser.write_bytes(parser)
                reader.parser_sha = sha(parser)
                before = deepcopy(reader.index)
                output, digest, manifest = reader.build()
                attached = attach_rerun(reader.index, output, digest)
                assert attached["source_rerun"]["data"] == manifest["data"]
                row = manifest["data"]["rows"][0]
                assert row["reading"]["status"] == "extracted"
                assert row["reading"]["evidence_level"] == level
                assert (
                    row["original_attempts"]
                    == before["sources"][0]["receipt"]["attempts"]
                )
                assert row["selected_sequence"] == 3
                assert row["acquisition_sequence"] == 2
                assert row["original_attempts"][-1]["http_status"] is None
                assert reader.index == before
                assert (
                    manifest["data"]["new_searches"]
                    == manifest["data"]["new_downloads"]
                    == 0
                )
                assert manifest["data"]["scientific_judgments_changed"] is False
                assert manifest["data"]["quality_score"] is None

    def test_offline_history_rejects_unmatched_or_unusable_acquisition(self):
        for field, value in [
            ("raw_sha256", "0" * 64),
            ("final_url", "https://example.test/other"),
            ("response_bytes", 1),
            ("response_truncated", True),
            ("outcome", "redirect"),
            ("purpose", "offline-parser-replay"),
        ]:
            with self.subTest(field=field, value=value):
                offline_reader = _offline_reader(self)
                reader = offline_reader
                reader.index["sources"][0]["receipt"]["attempts"][-2][field] = value
                _bind_history(reader)
                output, digest, manifest = reader.build()
                attach_rerun(reader.index, output, digest)
                reading = manifest["data"]["rows"][0]["reading"]
                assert reading["status"] == "failed-engineering"
                assert (
                    "no matching successful saved acquisition"
                    in reading["error"]["message"]
                )
                assert reading["characters"] == 0

    def test_offline_history_without_original_acquisition_fails_engineering(self):
        offline_reader = _offline_reader(self)
        reader = offline_reader
        reader.index["sources"][0]["receipt"]["attempts"] = [
            reader.index["sources"][0]["receipt"]["attempts"][-1]
        ]
        _bind_history(reader)
        output, digest, manifest = reader.build()
        attach_rerun(reader.index, output, digest)
        assert manifest["data"]["rows"][0]["reading"]["status"] == "failed-engineering"

    def test_offline_history_checks_actual_acquisition_archive_bytes(self):
        offline_reader = _offline_reader(self)
        reader = offline_reader
        (reader.package / "deliverable/sources/source-0/saved.html").write_bytes(
            b"altered acquisition"
        )
        output, digest, manifest = reader.build()
        attach_rerun(reader.index, output, digest)
        reading = manifest["data"]["rows"][0]["reading"]
        assert reading["status"] == "failed-engineering"
        assert "acquisition bytes differ" in reading["error"]["message"]

    def test_offline_history_missing_acquisition_archive_fails_engineering(self):
        offline_reader = _offline_reader(self)
        reader = offline_reader
        before = deepcopy(reader.index)
        archive = reader.package / "deliverable/sources/source-0"
        (archive / "saved.html").unlink()
        assert (archive / "replay.html").is_file()
        output, digest, manifest = reader.build()
        attach_rerun(reader.index, output, digest)
        row = manifest["data"]["rows"][0]
        reading = row["reading"]
        assert reading["status"] == "failed-engineering"
        assert reading["error"]["type"] == "ValueError"
        assert "acquisition archive could not be read" in reading["error"]["message"]
        assert reading["characters"] == 0 and reading["text_sha256"] is None
        assert "extracted_path" not in row
        assert row["selected_sequence"] == 3
        assert row["original_attempts"] == before["sources"][0]["receipt"]["attempts"]
        assert reader.index == before

    def test_offline_history_does_not_override_latest_actual_failure(self):
        for saved_body in [False, True]:
            with self.subTest(saved_body=saved_body):
                offline_reader = _offline_reader(self)
                reader = offline_reader
                latest = deepcopy(reader.index["sources"][0]["receipt"]["attempts"][-1])
                latest.update(
                    sequence=4,
                    purpose="synthetic actual response",
                    http_status=403 if saved_body else None,
                    outcome="http-error" if saved_body else "network-error",
                    raw_path="replay.html" if saved_body else None,
                    raw_sha256=sha(reader.raw["source-0"]) if saved_body else None,
                )
                reader.index["sources"][0]["receipt"]["attempts"].append(latest)
                _bind_history(reader)
                output, digest, manifest = reader.build()
                attach_rerun(reader.index, output, digest)
                row = manifest["data"]["rows"][0]
                assert row["reading"]["status"] == "inaccessible"
                assert row["reading"]["characters"] == 0
                assert "extracted_path" not in row
                assert row["original_attempts"][-1] == latest

    def test_offline_history_rejects_rehashed_acquisition_sequence(self):
        for sequence in [1, 3, 99]:
            with self.subTest(sequence=sequence):
                offline_reader = _offline_reader(self)
                reader = offline_reader
                output, _, manifest = reader.build()
                manifest["data"]["rows"][0]["acquisition_sequence"] = sequence
                raw = canonical(manifest)
                (output / "source-rerun-manifest.json").write_bytes(raw)
                with self.assertRaisesRegex(
                    DeliverableError, "acquisition attempt differs"
                ):
                    attach_rerun(reader.index, output, sha(raw))


if __name__ == "__main__":
    unittest.main()
