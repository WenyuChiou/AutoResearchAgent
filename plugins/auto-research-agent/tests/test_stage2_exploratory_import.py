"""Exploratory intake binds a reviewed partial Stage 1 deliverable without eligibility."""

import contextlib
import copy
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cli"))

from stage1_deliverable.common import sha
from stage2_common import Stage2Error, canonical_hash
from stage2_workflow.__main__ import main
from stage2_workflow.exploratory import build_exploratory_seed
import test_stage1_stage2_handoff as handoff_fixtures


class ExploratoryImportTests(unittest.TestCase):
    def setUp(self):
        self.fixture = handoff_fixtures.Stage1Stage2HandoffTests(methodName="runTest")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.output = self.fixture.root / "exploratory-seed"
        self.acceptance_path = self.fixture.root / "exploratory-acceptance.json"
        self.acceptance = {
            "kind": "Stage2ExploratoryAcceptance",
            "schema_version": "1.0.0",
            "accepted_by": "Fixture researcher",
            "decision_source_ref": "task:T140:user-decision",
            "purpose": "exploratory-stage2-planning",
            "deliverable_manifest_sha256": (self.fixture.deliverable_manifest_sha256),
            "stage1_records_sha256": "d" * 64,
            "research_brief_sha256": canonical_hash(self.fixture.brief),
            "resources_sha256": canonical_hash(
                self.fixture.resources_path.read_text(encoding="utf-8").strip()
            ),
            "included_work_ids": ["work1"],
            "limitations": [
                "Stage 1 scientific sufficiency has not been established.",
                "The synthetic claim remains unverified.",
            ],
        }
        self.write_acceptance()

    def write_acceptance(self, *, raw=None):
        if raw is None:
            raw = json.dumps(self.acceptance, ensure_ascii=False)
        self.acceptance_path.write_text(raw, encoding="utf-8")
        return sha(self.acceptance_path.read_bytes())

    def build(self):
        validation = {"status": "passed"}
        validate_patch = patch(
            "stage2_workflow.exploratory.validate_packet",
            return_value=None,
        )
        with (
            patch(
                "stage2_workflow.exploratory.deliverable_package.validate",
                return_value=validation,
            ) as deliverable_validate,
            patch(
                "stage2_workflow.import_stage1._source_bytes",
                return_value=(self.fixture.source_text, self.fixture.source_result),
            ),
            validate_patch as packet_validate,
        ):
            receipt = build_exploratory_seed(
                self.fixture.deliverable,
                self.fixture.deliverable_manifest_sha256,
                self.acceptance_path,
                sha(self.acceptance_path.read_bytes()),
                self.fixture.brief_path,
                self.fixture.resources_path,
                self.output,
            )
        return receipt, deliverable_validate, packet_validate

    def packet(self):
        return json.loads((self.output / "packet.json").read_text(encoding="utf-8"))

    def invoke_cli(self, *args):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = main(list(args))
        return code, stdout.getvalue(), stderr.getvalue()

    def exploratory_cli_args(self, *, acceptance=None, output=None):
        return (
            "import-stage1-exploratory",
            "--deliverable",
            str(self.fixture.deliverable),
            "--deliverable-manifest-sha256",
            self.fixture.deliverable_manifest_sha256,
            "--acceptance",
            str(acceptance or self.acceptance_path),
            "--acceptance-sha256",
            sha((acceptance or self.acceptance_path).read_bytes())
            if (acceptance or self.acceptance_path).exists()
            else "0" * 64,
            "--brief",
            str(self.fixture.brief_path),
            "--resources",
            str(self.fixture.resources_path),
            "--output",
            str(output or self.output),
        )

    def test_build_binds_acceptance_and_preserves_partial_semantics(self):
        receipt, deliverable_validate, packet_validate = self.build()
        packet = self.packet()
        upstream = packet["upstream"]

        self.assertEqual(packet["schema_version"], "2.1.0")
        self.assertEqual(upstream["schema_version"], "2.0.0")
        self.assertEqual(upstream["source_run_id"], "exploratory:" + "d" * 16)
        self.assertEqual(upstream["source_state_sha256"], "d" * 64)
        self.assertIsNone(upstream["stage1_handoff_sha256"])
        self.assertFalse(upstream["eligible_for_stage2"])
        self.assertEqual(
            upstream["stage2"],
            {"status": "not-started", "execution_authorized": False},
        )
        self.assertEqual(upstream["intake_mode"], "exploratory")
        self.assertEqual(upstream["acceptance"], self.acceptance)
        self.assertEqual(upstream["acceptance_sha256"], canonical_hash(self.acceptance))
        self.assertEqual(
            upstream["acceptance_file_sha256"], sha(self.acceptance_path.read_bytes())
        )
        self.assertEqual(
            upstream["binding_sha256"],
            canonical_hash(
                {
                    key: value
                    for key, value in upstream.items()
                    if key != "binding_sha256"
                }
            ),
        )
        self.assertEqual(packet["unresolved"][-2:], self.acceptance["limitations"])
        self.assertEqual(packet["evidence"][0]["relation"], "unverified")
        self.assertEqual(packet["candidates"], [])
        self.assertEqual(deliverable_validate.call_count, 2)
        packet_validate.assert_called_once()
        self.assertEqual(
            receipt,
            {
                "kind": "Stage1Stage2ImportReceipt",
                "schema_version": "2.0.0",
                "status": "ready-for-explicit-exploratory-stage2-start",
                "intake_mode": "exploratory",
                "scientific_sufficiency": "not-established",
                "packet_path": "packet.json",
                "packet_sha256": canonical_hash(packet),
                "binding_sha256": upstream["binding_sha256"],
                "acceptance_file_sha256": sha(self.acceptance_path.read_bytes()),
                "source_count": 1,
                "evidence_count": 1,
                "candidate_count": 0,
                "stage2_execution_authorized": False,
            },
        )

    def test_build_passes_real_v21_packet_validator(self):
        with (
            patch(
                "stage2_workflow.exploratory.deliverable_package.validate",
                return_value={"status": "passed"},
            ) as deliverable_validate,
            patch(
                "stage2_workflow.import_stage1._source_bytes",
                return_value=(self.fixture.source_text, self.fixture.source_result),
            ),
        ):
            receipt = build_exploratory_seed(
                self.fixture.deliverable,
                self.fixture.deliverable_manifest_sha256,
                self.acceptance_path,
                sha(self.acceptance_path.read_bytes()),
                self.fixture.brief_path,
                self.fixture.resources_path,
                self.output,
            )
        self.assertEqual(deliverable_validate.call_count, 2)
        self.assertEqual(receipt["packet_sha256"], canonical_hash(self.packet()))

    def test_reverse_acceptance_order_is_preserved_with_deterministic_projection(self):
        paper = copy.deepcopy(self.fixture.records["papers"][0])
        paper.update(
            work_id="work2",
            title="Second synthetic household study",
            source_ids=["src2"],
            claim_ids=["claim2"],
        )
        paper["roles"][0]["claim_ids"] = ["claim2"]
        source = copy.deepcopy(self.fixture.records["sources"][0])
        source.update(source_id="src2", work_id="work2")
        claim = copy.deepcopy(self.fixture.records["claims"][0])
        claim.update(claim_id="claim2", work_id="work2", source_id="src2")
        self.fixture.records["papers"].append(paper)
        self.fixture.records["sources"].append(source)
        self.fixture.records["claims"].append(claim)
        manifest_path = self.fixture.deliverable / "provenance_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["canonical_records"] = self.fixture.records
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        self.fixture.deliverable_manifest_sha256 = sha(manifest_path.read_bytes())
        self.acceptance["deliverable_manifest_sha256"] = (
            self.fixture.deliverable_manifest_sha256
        )
        self.acceptance["included_work_ids"] = ["work2", "work1"]
        self.write_acceptance()

        self.build()
        packet = self.packet()
        self.assertEqual(packet["upstream"]["included_work_ids"], ["work2", "work1"])
        self.assertEqual(
            [row["work_id"] for row in packet["literature"]], ["work1", "work2"]
        )
        self.assertEqual(
            [row["source_id"] for row in packet["sources"]], ["src1", "src2"]
        )

    def test_cli_import_preserves_unknowns_and_reports_partial_readiness(self):
        with (
            patch(
                "stage2_workflow.exploratory.deliverable_package.validate",
                return_value={"status": "passed"},
            ) as deliverable_validate,
            patch(
                "stage2_workflow.import_stage1._source_bytes",
                return_value=(self.fixture.source_text, self.fixture.source_result),
            ),
        ):
            code, stdout, stderr = self.invoke_cli(*self.exploratory_cli_args())
        self.assertEqual((code, stderr), (0, ""))
        receipt = json.loads(stdout)
        packet = self.packet()
        self.assertEqual(deliverable_validate.call_count, 2)
        self.assertFalse(packet["upstream"]["eligible_for_stage2"])
        self.assertFalse(packet["upstream"]["stage2"]["execution_authorized"])
        self.assertEqual(packet["evidence"][0]["relation"], "unverified")
        self.assertTrue(
            any("remains unverified" in item for item in packet["unresolved"])
        )
        self.assertEqual(packet["unresolved"][-2:], self.acceptance["limitations"])
        self.assertEqual(receipt["scientific_sufficiency"], "not-established")
        self.assertEqual(receipt["intake_mode"], "exploratory")

    def test_cli_malformed_or_missing_acceptance_returns_clean_error(self):
        malformed = self.fixture.root / "malformed-acceptance.json"
        malformed.write_text('{"kind":', encoding="utf-8")
        missing = self.fixture.root / "missing-acceptance.json"
        for name, acceptance in (("malformed", malformed), ("missing", missing)):
            with self.subTest(name=name):
                output = self.fixture.root / f"{name}-cli-output"
                with patch(
                    "stage2_workflow.exploratory.deliverable_package.validate",
                    return_value={"status": "passed"},
                ):
                    code, stdout, stderr = self.invoke_cli(
                        *self.exploratory_cli_args(acceptance=acceptance, output=output)
                    )
                self.assertEqual(code, 2)
                self.assertEqual(stdout, "")
                self.assertTrue(stderr.startswith("stage2-workflow: "))
                self.assertFalse(output.exists())

        stdout, stderr = io.StringIO(), io.StringIO()
        missing_argument = self.exploratory_cli_args()
        acceptance_index = missing_argument.index("--acceptance")
        missing_argument = (
            missing_argument[:acceptance_index]
            + missing_argument[acceptance_index + 2 :]
        )
        with (
            contextlib.redirect_stdout(stdout),
            contextlib.redirect_stderr(stderr),
            self.assertRaises(SystemExit) as stopped,
        ):
            main(list(missing_argument))
        self.assertEqual(stopped.exception.code, 2)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("--acceptance", stderr.getvalue())
        self.assertFalse(self.output.exists())

    def test_cli_list_brief_returns_clean_error_without_output(self):
        self.fixture.brief_path.write_text("[]", encoding="utf-8")
        output = self.fixture.root / "list-brief-cli-output"
        with patch(
            "stage2_workflow.exploratory.deliverable_package.validate",
            return_value={"status": "passed"},
        ):
            code, stdout, stderr = self.invoke_cli(
                *self.exploratory_cli_args(output=output)
            )
        self.assertEqual(code, 2)
        self.assertEqual(stdout, "")
        self.assertIn("stage2-exploratory-brief-invalid", stderr)
        self.assertFalse(output.exists())

    def test_deliverable_directory_link_is_rejected_before_resolution(self):
        linked = self.fixture.root / "linked-deliverable"
        if os.name == "nt":
            created = subprocess.run(
                [
                    "cmd",
                    "/c",
                    "mklink",
                    "/J",
                    str(linked),
                    str(self.fixture.deliverable),
                ],
                capture_output=True,
                check=False,
                text=True,
            )
            if created.returncode != 0:
                self.skipTest("Windows junction creation is unavailable")
        else:
            try:
                linked.symlink_to(self.fixture.deliverable, target_is_directory=True)
            except (NotImplementedError, OSError):
                self.skipTest("directory symlink creation is unavailable")
        try:
            with (
                patch(
                    "stage2_workflow.exploratory.deliverable_package.validate",
                    return_value={"status": "passed"},
                ) as deliverable_validate,
                self.assertRaisesRegex(Stage2Error, "stage1-deliverable-link-rejected"),
            ):
                build_exploratory_seed(
                    linked,
                    self.fixture.deliverable_manifest_sha256,
                    self.acceptance_path,
                    sha(self.acceptance_path.read_bytes()),
                    self.fixture.brief_path,
                    self.fixture.resources_path,
                    self.output,
                )
            deliverable_validate.assert_not_called()
            self.assertFalse(self.output.exists())
        finally:
            if os.name == "nt":
                os.rmdir(linked)
            else:
                linked.unlink()

    def test_acceptance_rejects_wrong_shape_hashes_scope_and_limitations(self):
        changes = (
            ("extra", lambda value: value.update(extra="forbidden")),
            ("missing", lambda value: value.pop("accepted_by")),
            ("actor", lambda value: value.update(accepted_by="  ")),
            ("decision", lambda value: value.update(decision_source_ref="")),
            (
                "manifest",
                lambda value: value.update(deliverable_manifest_sha256="a" * 64),
            ),
            ("records", lambda value: value.update(stage1_records_sha256="a" * 64)),
            ("brief", lambda value: value.update(research_brief_sha256="a" * 64)),
            ("resources", lambda value: value.update(resources_sha256="a" * 64)),
            ("empty-scope", lambda value: value.update(included_work_ids=[])),
            (
                "duplicate-scope",
                lambda value: value.update(included_work_ids=["work1", "work1"]),
            ),
            ("unknown-scope", lambda value: value.update(included_work_ids=["work2"])),
            ("empty-limitations", lambda value: value.update(limitations=[])),
            ("non-string-limitation", lambda value: value.update(limitations=[1])),
        )
        valid_acceptance = copy.deepcopy(self.acceptance)
        for name, change in changes:
            with self.subTest(name=name):
                self.acceptance = copy.deepcopy(valid_acceptance)
                change(self.acceptance)
                self.write_acceptance()
                with self.assertRaises(Stage2Error):
                    self.build()
                self.assertFalse(self.output.exists())
        self.acceptance = valid_acceptance
        self.write_acceptance()

    def test_acceptance_file_hash_and_duplicate_keys_are_rejected(self):
        digest = self.write_acceptance()
        with self.assertRaisesRegex(Stage2Error, "acceptance-sha256-mismatch"):
            with patch(
                "stage2_workflow.exploratory.deliverable_package.validate",
                return_value={"status": "passed"},
            ):
                build_exploratory_seed(
                    self.fixture.deliverable,
                    self.fixture.deliverable_manifest_sha256,
                    self.acceptance_path,
                    "0" * 64,
                    self.fixture.brief_path,
                    self.fixture.resources_path,
                    self.output,
                )
        self.assertFalse(self.output.exists())

        raw = self.acceptance_path.read_text(encoding="utf-8")
        raw = raw[:-1] + ',"accepted_by":"duplicate"}'
        digest = self.write_acceptance(raw=raw)
        with self.assertRaisesRegex(Stage2Error, "duplicate-json-key"):
            with patch(
                "stage2_workflow.exploratory.deliverable_package.validate",
                return_value={"status": "passed"},
            ):
                build_exploratory_seed(
                    self.fixture.deliverable,
                    self.fixture.deliverable_manifest_sha256,
                    self.acceptance_path,
                    digest,
                    self.fixture.brief_path,
                    self.fixture.resources_path,
                    self.output,
                )
        self.assertFalse(self.output.exists())

    def test_acceptance_path_traversal_is_rejected_before_output_creation(self):
        traversing_path = (
            self.acceptance_path.parent / "unused" / ".." / self.acceptance_path.name
        )
        with (
            patch(
                "stage2_workflow.exploratory.deliverable_package.validate",
                return_value={"status": "passed"},
            ),
            self.assertRaisesRegex(Stage2Error, "acceptance-path-traversal"),
        ):
            build_exploratory_seed(
                self.fixture.deliverable,
                self.fixture.deliverable_manifest_sha256,
                traversing_path,
                sha(self.acceptance_path.read_bytes()),
                self.fixture.brief_path,
                self.fixture.resources_path,
                self.output,
            )
        self.assertFalse(self.output.exists())

    def test_failure_removes_only_new_output_and_preserves_preexisting_output(self):
        self.output.mkdir()
        marker = self.output / "keep.txt"
        marker.write_text("keep", encoding="utf-8")
        with self.assertRaisesRegex(Stage2Error, "output-exists"):
            self.build()
        self.assertEqual(marker.read_text(encoding="utf-8"), "keep")

        self.output = self.fixture.root / "new-exploratory-seed"
        with (
            patch(
                "stage2_workflow.exploratory.deliverable_package.validate",
                return_value={"status": "passed"},
            ),
            patch(
                "stage2_workflow.import_stage1._source_bytes",
                return_value=(self.fixture.source_text, self.fixture.source_result),
            ),
            patch(
                "stage2_workflow.exploratory.validate_packet",
                side_effect=Stage2Error("synthetic-validation-failure"),
            ),
        ):
            with self.assertRaisesRegex(Stage2Error, "synthetic-validation-failure"):
                build_exploratory_seed(
                    self.fixture.deliverable,
                    self.fixture.deliverable_manifest_sha256,
                    self.acceptance_path,
                    sha(self.acceptance_path.read_bytes()),
                    self.fixture.brief_path,
                    self.fixture.resources_path,
                    self.output,
                )
        self.assertFalse(self.output.exists())


if __name__ == "__main__":
    unittest.main()
