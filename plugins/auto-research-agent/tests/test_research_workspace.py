"""Neutral offline delivery fixtures; no frozen paper identities or live calls."""

from pathlib import Path
from copy import deepcopy
import inspect
import sys
import unittest
from unittest.mock import patch

import test_stage1_deliverable as fixture

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cli"))
from research_workspace.projection import project_package, validate_index  # noqa: E402
from research_workspace import projection  # noqa: E402
from stage1_deliverable.common import (  # noqa: E402
    DeliverableError,
    canonical,
    inventory,
    read_json,
    sha,
    write_json,
)


class WorkspaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture.ResearchDeliverableTests.setUpClass()

    def setUp(self):
        self.fixture = fixture.ResearchDeliverableTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root / "delivery"
        self.root.mkdir()
        self.fixture.output = self.root / "deliverable"
        self.records = self.fixture.make_records()
        self.records["papers"][0]["classification"]["method"] = "Unknown"
        self.records["papers"][0]["roles"] = [
            {"role": role, "reason": "Synthetic role evidence", "claim_ids": ["claim1"]}
            for role in ("topic-core", "comparator")
        ]
        delivery = self.fixture.output
        archive = delivery / "sources/src1"
        archive.mkdir(parents=True)
        receipt_path = self.fixture.inputs / "source/source-fetch-result.json"
        receipt = read_json(receipt_path)
        (archive / "original.json").write_bytes(receipt_path.read_bytes())
        mapping = fixture.sources.artifact_map(receipt)
        for original, relative in mapping.items():
            target = archive / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(Path(original).read_bytes())
        attempts = [
            {
                "source_id": "src1",
                "work_id": "work1",
                "version_id": "v1",
                "attempt": attempt["sequence"],
                "archive_path": "sources/src1/" + mapping[attempt["raw_path"]],
                "paper_path": None,
                "sha256": attempt["raw_sha256"],
                "state": receipt["status"],
                "source_version": receipt["source_version"],
            }
            for attempt in receipt["attempts"]
        ]
        write_json(delivery / "records.original.json", self.records)
        for name, rows in (
            ("papers.jsonl", self.records["papers"]),
            ("paper_manifest.jsonl", attempts),
        ):
            (delivery / name).write_bytes(
                b"".join(canonical(row) + b"\n" for row in rows)
            )
        (delivery / "search_and_screening.csv").write_bytes(
            b"query,status\r\nsynthetic,pending\r\n"
        )
        write_json(
            delivery / "provenance_manifest.json",
            {
                "kind": "Stage1ResearchDeliverable",
                "schema_version": "1.0.0",
                "canonical_records": self.records,
                "original_input_sha256": sha(
                    (delivery / "records.original.json").read_bytes()
                ),
                "files": inventory(delivery),
            },
        )
        self.readiness = {
            "status": "partial-review-only",
            "stage2_execution_authorized": False,
        }
        write_json(self.root / "stage2_readiness.json", self.readiness)
        self.rebind()

    def rebind(self):
        files = inventory(self.root)
        files.pop("package_manifest.json", None)
        write_json(
            self.root / "package_manifest.json",
            {
                "kind": "Stage1PrivateDeliveryPackageManifest",
                "schema_version": "1.0.0",
                "files": {
                    name: {"sha256": digest, "bytes": (self.root / name).stat().st_size}
                    for name, digest in files.items()
                },
                "stage2_readiness_sha256": sha(
                    (self.root / "stage2_readiness.json").read_bytes()
                ),
            },
        )
        self.digest = sha((self.root / "package_manifest.json").read_bytes())

    def project(self, **kwargs):
        return project_package(self.root, "neutral-project", self.digest, **kwargs)

    def test_deterministic_lossless_projection_and_multiple_roles(self):
        result = self.project()
        self.assertEqual(canonical(result), canonical(self.project()))
        for field in ("papers", "claims", "screening", "coverage"):
            self.assertEqual(result[field], self.records[field])
        self.assertEqual(result["readiness"], self.readiness)
        self.assertEqual(
            [(row["stage"], row["execution_enabled"]) for row in result["stages"]],
            [(i, False) for i in range(1, 7)],
        )
        self.assertEqual(
            [edge["type"] for edge in result["edges"]],
            ["claim-source", "role-claim", "role-claim"],
        )
        self.assertEqual(result["edges"][0]["relation"], "unverified")
        self.assertTrue(
            all(
                edge["provenance"]["sha256"] == result["provenance"]["records_sha256"]
                for edge in result["edges"]
            )
        )
        self.assertIn(
            {"pointer": "/papers/0/classification/method", "status": "stated-unknown"},
            result["missing_fields"],
        )
        self.assertEqual(result["supplement"]["top3_status"], "pending")
        self.assertEqual(
            result["bibliography"]["all_bibtex"],
            result["bibliography"]["entries"][0]["bibtex"],
        )
        self.assertEqual(
            result["search"][0]["text"],
            (self.fixture.output / "search_and_screening.csv").read_bytes().decode(),
        )
        self.assertEqual(
            result["provenance"]["validation"]["semantic_replay"], "not-performed"
        )

    def test_external_hash_extra_file_and_tampered_source_fail_closed(self):
        with self.assertRaisesRegex(DeliverableError, "external package hash"):
            project_package(self.root, "neutral-project", "0" * 64)
        extra = self.root / "extra.txt"
        extra.write_text("not declared", encoding="utf-8")
        with self.assertRaisesRegex(DeliverableError, "inventory"):
            self.project()
        extra.unlink()
        text = next(self.fixture.output.glob("sources/*/extracted/*"))
        text.write_text("altered evidence", encoding="utf-8")
        with self.assertRaisesRegex(DeliverableError, "inventory"):
            self.project()

    def test_outer_manifest_is_parsed_from_the_hash_checked_snapshot(self):
        path = self.root / "package_manifest.json"
        approved = path.read_bytes()
        manifest = read_json(path)
        original_sha = projection.sha
        replaced = False

        def replace_after_hash(raw):
            nonlocal replaced
            digest = original_sha(raw)
            if raw == approved and not replaced:
                path.write_bytes(approved.replace(b"Stage1Private", b"Unapproved"))
                replaced = True
            return digest

        try:
            with patch.object(projection, "sha", side_effect=replace_after_hash):
                result, _, _ = projection._package(self.root, self.digest)
            self.assertTrue(replaced)
            self.assertEqual(result, manifest)
        finally:
            path.write_bytes(approved)

    def test_transient_document_replacement_cannot_escape_final_inventory(self):
        path = self.fixture.output / "search_and_screening.csv"
        approved = path.read_bytes()
        unapproved = b"query,status\r\nunapproved,complete\r\n"
        original_read = Path.read_bytes
        replaced = False

        def transient_read(current):
            nonlocal replaced
            caller = inspect.currentframe().f_back.f_code.co_name
            if current == path and caller in {"documents", "bound_read"}:
                current.write_bytes(unapproved)
                replaced = True
                try:
                    return original_read(current)
                finally:
                    current.write_bytes(approved)
            return original_read(current)

        with patch.object(Path, "read_bytes", transient_read):
            with self.assertRaisesRegex(DeliverableError, "artifact hash mismatch"):
                self.project()
        self.assertTrue(replaced)
        self.assertEqual(path.read_bytes(), approved)
        self.assertEqual(self.project()["search"][0]["text"], approved.decode())

    def test_each_consumed_artifact_is_checked_after_inventory(self):
        paths = [
            "deliverable/provenance_manifest.json",
            "deliverable/records.original.json",
            "deliverable/papers.jsonl",
            "deliverable/paper_manifest.jsonl",
            "deliverable/sources/src1/original.json",
            "stage2_readiness.json",
        ]
        paths += [
            path.relative_to(self.root).as_posix()
            for path in self.fixture.output.glob("sources/*/extracted/*")
        ]
        original_reader = projection._bound_reader
        for relative in paths:
            with self.subTest(relative=relative):
                path = self.root / relative
                approved = path.read_bytes()
                replaced = []

                def replace_at_consumption(root, files):
                    read = original_reader(root, files)

                    def bound_read(name):
                        if name != relative or replaced:
                            return read(name)
                        path.write_bytes(approved + b"unapproved")
                        replaced.append(name)
                        try:
                            return read(name)
                        finally:
                            path.write_bytes(approved)

                    return bound_read

                with patch.object(
                    projection, "_bound_reader", side_effect=replace_at_consumption
                ):
                    with self.assertRaisesRegex(
                        DeliverableError, "artifact hash mismatch"
                    ):
                        self.project()
                self.assertEqual(replaced, [relative])
                self.assertEqual(path.read_bytes(), approved)

    def test_rehashed_wrong_work_version_and_quote_are_rejected(self):
        original = self.fixture.output / "records.original.json"
        manifest_path = self.fixture.output / "provenance_manifest.json"
        for field, value in (
            ("version_id", "wrong-version"),
            ("quote", "wrong quotation"),
        ):
            with self.subTest(field=field):
                records = read_json(original)
                records["claims"][0][field] = value
                write_json(original, records)
                manifest = read_json(manifest_path)
                manifest["canonical_records"] = records
                manifest["original_input_sha256"] = sha(original.read_bytes())
                manifest["files"] = inventory(self.fixture.output)
                write_json(manifest_path, manifest)
                self.rebind()
                with self.assertRaises(DeliverableError):
                    self.project()
                write_json(original, self.records)

    def test_external_replay_is_not_called_and_source_git_is_rejected(self):
        with patch("stage1_deliverable.package.validate") as external:
            for mode in ("semantic-replay", "trust-me"):
                with self.assertRaisesRegex(
                    DeliverableError, "unknown validation mode"
                ):
                    self.project(validation_mode=mode)
            external.assert_not_called()
        (self.root / ".git").mkdir()
        with self.assertRaisesRegex(DeliverableError, "outside a Git"):
            self.project()

    def test_schema_and_equal_title_projects_do_not_enable_execution(self):
        first = self.project()
        second = project_package(self.root, "another-project", self.digest)
        self.assertEqual(first["topic"], second["topic"])
        self.assertNotEqual(first["project_id"], second["project_id"])
        self.assertNotEqual(sha(canonical(first)), sha(canonical(second)))
        self.assertEqual(first["papers"], second["papers"])
        validate_index(first)
        self.assertEqual(first["evaluations"], {"status": "not-provided", "items": []})
        self.assertIsNone(first["native_session"]["thread_id"])
        for row in first["stages"]:
            self.assertTrue(row["purpose"])
            self.assertTrue(row["required_inputs"])
            self.assertTrue(row["expected_deliverables"])
            self.assertEqual(row["allowed_execution_actions"], [])
            if row["stage"] >= 3:
                self.assertEqual(row["support_status"], "reserved")
                self.assertIsNone(row["adapter"])
        for mutation in ("execution", "unknown-field", "score", "version"):
            with self.subTest(mutation=mutation):
                changed = deepcopy(first)
                if mutation == "execution":
                    changed["stages"][0]["execution_enabled"] = True
                elif mutation == "unknown-field":
                    changed["accepted_by"] = "invented-approval"
                elif mutation == "score":
                    changed["evaluations"]["items"] = [{"score": 0}]
                else:
                    changed["schema_version"] = "future-unreviewed"
                with self.assertRaises(DeliverableError):
                    validate_index(changed)

    def test_ui_types_unique_stages_and_bound_bibliography_are_required(self):
        original = self.project()
        for mutation in (
            "authors",
            "authors-type",
            "stages",
            "bib-missing",
            "bib-hash",
            "bib-entry",
            "bib-all",
        ):
            with self.subTest(mutation=mutation):
                changed = deepcopy(original)
                if mutation == "authors":
                    del changed["papers"][0]["authors"]
                elif mutation == "authors-type":
                    changed["papers"][0]["authors"] = "Unstructured author"
                elif mutation == "stages":
                    changed["stages"][1] = deepcopy(changed["stages"][0])
                elif mutation == "bib-missing":
                    changed["bibliography"]["entries"] = []
                elif mutation == "bib-hash":
                    changed["bibliography"]["records_sha256"] = "0" * 64
                elif mutation == "bib-entry":
                    changed["bibliography"]["entries"][0]["bibtex"] = "altered"
                else:
                    changed["bibliography"]["all_bibtex"] = "altered"
                with self.assertRaises(DeliverableError):
                    validate_index(changed)


if __name__ == "__main__":
    unittest.main()
