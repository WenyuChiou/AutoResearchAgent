"""Offline acceptance checks for binding saved-source rerun manifests."""

import sys
import unittest
from copy import deepcopy
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parents[1] / "cli"))

import test_research_workspace_saved_reader as reader_fixture
from research_workspace.projection import validate_index
from research_workspace.source_rerun import _metadata, attach_rerun
from stage1_deliverable.common import DeliverableError, canonical, sha


class SavedSourceRerunBindingTests(unittest.TestCase):
    def setUp(self):
        self.reader = reader_fixture.SavedReaderTests()
        self.reader.setUp()
        self.addCleanup(self.reader.doCleanups)
        self.root, self.digest, self.manifest = self.reader.build("binding")

    def rewrite(self, mutate):
        manifest = deepcopy(self.manifest)
        mutate(manifest)
        raw = canonical(manifest)
        (self.root / "source-rerun-manifest.json").write_bytes(raw)
        return sha(raw)

    def test_valid_attachment_preserves_the_complete_legacy_index(self):
        projected = attach_rerun(self.reader.index, self.root, self.digest)
        self.assertIs(validate_index(projected), projected)
        base = deepcopy(projected)
        base.pop("source_rerun")
        base["schema_version"] = "1.0.0"
        self.assertEqual(base, self.reader.index)
        self.assertFalse(projected["source_rerun"]["data"]["research_execution"])
        self.assertFalse(
            projected["source_rerun"]["data"]["official_stage2_import_eligible"]
        )

    def test_external_hash_and_manifest_package_version_are_required(self):
        with self.assertRaisesRegex(DeliverableError, "external rerun manifest hash"):
            attach_rerun(self.reader.index, self.root, "0" * 64)
        for key, value in (("kind", "OtherPackage"), ("schema_version", "2.0.0")):
            with self.subTest(key=key):
                digest = self.rewrite(
                    lambda manifest, key=key, value=value: manifest["data"].__setitem__(
                        key, value
                    )
                )
                with self.assertRaisesRegex(
                    DeliverableError, "unsupported source rerun"
                ):
                    attach_rerun(self.reader.index, self.root, digest)

    def test_base_source_identity_result_and_version_drift_are_rejected(self):
        cases = (
            (
                "base",
                lambda m: m["data"].__setitem__("base_index_sha256", "0" * 64),
                "base/version",
            ),
            (
                "identity",
                lambda m: m["data"]["rows"][0].__setitem__(
                    "version_id", "other-version"
                ),
                "work/source/version",
            ),
            (
                "result",
                lambda m: m["data"]["rows"][0].__setitem__(
                    "original_result_sha256", "0" * 64
                ),
                "original result differs",
            ),
            (
                "source-version",
                lambda m: m["data"]["rows"][0].__setitem__(
                    "source_version", "sha256:" + "0" * 64
                ),
                "raw version differs",
            ),
        )
        for label, mutate, error in cases:
            with self.subTest(label=label):
                digest = self.rewrite(mutate)
                with self.assertRaisesRegex(DeliverableError, error):
                    attach_rerun(self.reader.index, self.root, digest)

    def test_missing_file_and_wrong_source_hash_are_rejected(self):
        raw_path = self.manifest["data"]["rows"][0]["raw_path"]
        path = self.root / raw_path
        original = path.read_bytes()
        path.unlink()
        with self.assertRaisesRegex(DeliverableError, "rerun inventory differs"):
            attach_rerun(self.reader.index, self.root, self.digest)
        path.write_bytes(original)

        digest = self.rewrite(
            lambda manifest: manifest["data"]["rows"][0].__setitem__(
                "raw_sha256", "0" * 64
            )
        )
        with self.assertRaisesRegex(DeliverableError, "raw is not from this source"):
            attach_rerun(self.reader.index, self.root, digest)

    def test_locator_and_abstract_evidence_upgrades_are_rejected(self):
        def invalid_locator(manifest):
            row = manifest["data"]["rows"][0]
            row["reading"]["locators"][0]["end"] = row["reading"]["characters"] + 1

        digest = self.rewrite(invalid_locator)
        with self.assertRaisesRegex(DeliverableError, "rerun locator invalid"):
            attach_rerun(self.reader.index, self.root, digest)

        def abstract_upgrade(manifest):
            reading = manifest["data"]["rows"][0]["reading"]
            reading["locators"] = [
                {
                    "start": 0,
                    "end": reading["characters"],
                    "type": "text",
                    "value": "abstract",
                }
            ]
            reading["evidence_level"] = "full-text"

        digest = self.rewrite(abstract_upgrade)
        with self.assertRaisesRegex(
            DeliverableError, "abstract cannot become full-text"
        ):
            attach_rerun(self.reader.index, self.root, digest)

    def test_exact_raw_quotation_binding_is_enforced(self):
        def wrong_quotation(manifest):
            row = manifest["data"]["rows"][0]
            raw = (self.root / row["raw_path"]).read_bytes()
            start = raw.index(b"successful")
            end = start + len(b"successful")
            locator = {
                "start": 0,
                "end": row["reading"]["characters"],
                "type": "html-publication-table",
                "value": "abstract",
                "source_sha256": sha(raw),
                "fields": [
                    {
                        "field": "journal",
                        "raw_utf8_bytes": [start, end],
                        "raw_element_sha256": "0" * 64,
                        "clean_value_sha256": sha(b"successful"),
                    }
                ],
            }
            row["reading"]["locators"] = [locator]
            row["reading"]["evidence_level"] = "abstract"
            row["source_metadata"]["journal"] = "successful"
            paper = self.reader.index["papers"][0]
            row["metadata"], row["metadata_provenance"] = _metadata(
                paper,
                {
                    "bibliographic_metadata": row["source_metadata"],
                    "locators": [locator],
                },
                row["reading"]["identity_status"],
            )

        digest = self.rewrite(wrong_quotation)
        with self.assertRaisesRegex(DeliverableError, "quotation bytes differ"):
            attach_rerun(self.reader.index, self.root, digest)

    def test_research_judgment_import_and_acquisition_upgrades_are_rejected(self):
        cases = (
            ("research_execution", True),
            ("scientific_judgments_changed", True),
            ("official_stage2_import_eligible", True),
            ("new_searches", 1),
            ("new_downloads", 1),
            ("quality_score", 1),
        )
        for key, value in cases:
            with self.subTest(key=key):
                digest = self.rewrite(
                    lambda manifest, key=key, value=value: manifest["data"].__setitem__(
                        key, value
                    )
                )
                with self.assertRaisesRegex(
                    DeliverableError, "cannot promote|cannot create"
                ):
                    attach_rerun(self.reader.index, self.root, digest)


if __name__ == "__main__":
    unittest.main()
