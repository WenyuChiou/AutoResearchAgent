"""Offline reader regressions for rerunning complete saved-source archives."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "cli"))

import test_research_workspace_view as view_fixture
from research_workspace.source_rerun import build_rerun
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


if __name__ == "__main__":
    unittest.main()
