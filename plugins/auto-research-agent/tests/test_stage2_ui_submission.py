"""Synthetic UI provenance tests; fixtures never establish actual human identity."""

# ruff: noqa: E402 -- repository package and existing authored offline fixture.
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import unittest

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent / "cli"), str(HERE)]
import test_stage2_delivery as fixtures
from stage2_common import Stage2Error, canonical_hash
from stage2_workflow import inspect_workflow
from stage2_workflow.interaction import record_interaction
from stage2_workflow.planning_handoff import (
    inspect_planning_handoff,
    prepare_planning_handoff,
)
from stage2_workflow.ui_submission import UI_MESSAGE_FILE, read_ui_submission


class UISubmissionTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.Stage2DeliveryTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.delivery = self.f.root / "ui-delivery"
        reviews, resolutions = self.f._complete_inputs()
        self.manifest = self.f._build(self.delivery, reviews, resolutions)
        candidate = self.f.packet["candidates"][0]
        self.decision = dict(
            actor="synthetic-ui-principal",
            kind="select",
            user_text="Select the displayed synthetic direction for planning.",
            selected=[
                dict(
                    candidate_id=candidate["candidate_id"],
                    candidate_version=candidate["version"],
                )
            ],
            conditions=["Preserve the displayed unknowns."],
            unresolved=["Access remains unknown."],
            rationale="Synthetic UI explicitly confirms the displayed version.",
            scope_or_resource_change=False,
        )
        self.submission = dict(
            kind="Stage2ProjectHostUserSubmission",
            schema_version="1.0.0",
            project_ref="synthetic-project",
            input_version=1,
            principal="synthetic-bearer-principal",
            request_sha256="a" * 64,
            received_at="2026-10-22T00:00:00+00:00",
            confirmed=True,
            decision=deepcopy(self.decision),
            workflow_manifest_sha256=self.manifest["workflow_manifest_sha256"],
            workflow_head_sha256=self.manifest["workflow_head_sha256"],
            snapshot_sha256=self.manifest["snapshot_sha256"],
            delivery_manifest_sha256=self.manifest["manifest_sha256"],
        )
        self.message = self.f.root / "actual-synthetic-ui-request.json"
        self.interaction = self.f.root / "ui-interaction"
        self.package = self.f.root / "ui-planning"
        self.save()

    def save(self):
        self.message.write_bytes(json.dumps(self.submission).encode("utf-8"))
        return hashlib.sha256(self.message.read_bytes()).hexdigest()

    def record(self, **options):
        return record_interaction(
            self.f.workflow,
            self.delivery,
            self.manifest["manifest_sha256"],
            self.decision,
            self.message,
            0,
            "ui-choice",
            self.interaction,
            inspect_workflow(self.f.workflow)["head_sha256"],
            input_origin=options.get("input_origin", "projecthost-ui-submission"),
            expected_message_sha256=options.get("receipt", self.save()),
            expected_project_ref=options.get("project_ref", "synthetic-project"),
            expected_input_version=options.get("input_version", 1),
        )

    def prepare(self):
        self.record()
        return prepare_planning_handoff(
            self.delivery,
            self.interaction,
            expected_delivery_manifest_sha256=self.manifest["manifest_sha256"],
            expected_interaction_file_sha256=hashlib.sha256(
                (self.interaction / "interaction.json").read_bytes()
            ).hexdigest(),
            output_dir=self.package,
        )

    def inspect(self, digest):
        return inspect_planning_handoff(
            self.package, self.delivery, expected_manifest_sha256=digest
        )

    def refresh_manifest(self):
        path = self.package / "planning_manifest.json"
        manifest = json.loads(path.read_bytes())
        for row in manifest["files"]:
            data = (self.package / row["path"]).read_bytes()
            row.update(sha256=hashlib.sha256(data).hexdigest(), size=len(data))
        manifest["files"].sort(key=lambda row: row["path"])
        manifest["manifest_sha256"] = canonical_hash(
            {k: v for k, v in manifest.items() if k != "manifest_sha256"}
        )
        path.write_text(json.dumps(manifest), encoding="utf-8")
        return manifest["manifest_sha256"]

    def test_ui_roundtrip_is_honest_versioned_and_execution_false(self):
        result = self.prepare()
        checked = self.inspect(result["manifest"]["manifest_sha256"])
        handoff = checked["handoff"]
        self.assertEqual(handoff["schema_version"], "1.1.0")
        self.assertEqual(handoff["input_origin"]["kind"], "projecthost-ui-submission")
        self.assertEqual(handoff["input_origin"]["human_identity"], "not-established")
        self.assertFalse(handoff["execution_authorized"])
        self.assertNotIn("native_user_message_sha256", handoff)
        self.assertEqual(
            (self.package / UI_MESSAGE_FILE).read_bytes(), self.message.read_bytes()
        )
        self.assertFalse((self.package / "native-user-message.jsonl").exists())
        self.assertEqual(handoff["decision"], self.decision)
        self.assertEqual(handoff["evaluation_packet"], self.f.packet)

    def test_same_request_replay_does_not_append_another_human_action(self):
        self.record()
        state = inspect_workflow(self.f.workflow)
        original = (self.interaction / "interaction.json").read_bytes()
        self.assertTrue(self.record()["reuse"])
        self.assertEqual(
            inspect_workflow(self.f.workflow)["head_sha256"], state["head_sha256"]
        )
        self.assertEqual((self.interaction / "interaction.json").read_bytes(), original)

    def test_wrong_receipt_or_native_origin_never_creates_an_interaction(self):
        for options in [dict(receipt="0" * 64), dict(input_origin="native-codex")]:
            with self.subTest(options=options), self.assertRaises(Stage2Error):
                self.record(**options)
            self.assertFalse(self.interaction.exists())
        self.assertEqual(
            inspect_workflow(self.f.workflow)["head_sha256"],
            self.f.state["head_sha256"],
        )

    def test_displayed_workflow_snapshot_and_delivery_pins_are_required(self):
        original = deepcopy(self.submission)
        for field in [
            "workflow_manifest_sha256",
            "workflow_head_sha256",
            "snapshot_sha256",
            "delivery_manifest_sha256",
        ]:
            self.submission = deepcopy(original)
            self.submission[field] = "0" * 64
            with (
                self.subTest(field=field),
                self.assertRaisesRegex(Stage2Error, "submission-binding-mismatch"),
            ):
                self.record()
            self.assertFalse(self.interaction.exists())

    def test_rehashed_submission_tampering_does_not_pass_receiver(self):
        self.prepare()
        path = self.package / UI_MESSAGE_FILE
        saved = path.read_bytes()
        for field in ["project_ref", "principal", "input_version"]:
            value = json.loads(saved)
            value[field] = 2 if field == "input_version" else "foreign-project-or-user"
            path.write_text(json.dumps(value), encoding="utf-8")
            digest = self.refresh_manifest()
            with self.subTest(field=field), self.assertRaises(Stage2Error):
                self.inspect(digest)
        self.assertFalse(
            json.loads((self.package / "planning_handoff.json").read_bytes())[
                "execution_authorized"
            ]
        )

    def test_stale_candidate_version_is_rejected_before_recording(self):
        self.decision["selected"][0]["candidate_version"] += 1
        self.submission["decision"] = deepcopy(self.decision)
        with self.assertRaises(Stage2Error):
            self.record()
        self.assertFalse(self.interaction.exists())

    def test_initial_wrong_project_is_rejected_before_recording(self):
        self.submission["project_ref"] = "another-synthetic-project"
        with self.assertRaisesRegex(Stage2Error, "submission-binding-mismatch"):
            self.record()
        self.assertFalse(self.interaction.exists())
        self.assertEqual(
            inspect_workflow(self.f.workflow)["head_sha256"],
            self.f.state["head_sha256"],
        )

    def test_initial_stale_input_version_is_rejected_before_recording(self):
        self.submission["input_version"] = 2
        with self.assertRaisesRegex(Stage2Error, "submission-binding-mismatch"):
            self.record()
        self.assertFalse(self.interaction.exists())
        self.assertEqual(
            inspect_workflow(self.f.workflow)["head_sha256"],
            self.f.state["head_sha256"],
        )

    def test_independent_project_context_is_required_before_recording(self):
        for options in [
            dict(project_ref=None),
            dict(project_ref=""),
            dict(input_version=None),
            dict(input_version=True),
            dict(input_version=0),
        ]:
            with (
                self.subTest(options=options),
                self.assertRaisesRegex(Stage2Error, "trusted-context-required"),
            ):
                self.record(**options)
            self.assertFalse(self.interaction.exists())
        self.assertEqual(
            inspect_workflow(self.f.workflow)["head_sha256"],
            self.f.state["head_sha256"],
        )

    def test_ui_submission_cannot_be_relabelled_as_a_native_message(self):
        self.prepare()
        (self.package / UI_MESSAGE_FILE).rename(
            self.package / "native-user-message.jsonl"
        )
        path = self.package / "interaction.json"
        record = json.loads(path.read_bytes())
        record["schema_version"] = "1.0.0"
        record.pop("input_origin")
        record["record_sha256"] = canonical_hash(
            {k: v for k, v in record.items() if k != "record_sha256"}
        )
        path.write_text(json.dumps(record), encoding="utf-8")
        path = self.package / "planning_manifest.json"
        manifest = json.loads(path.read_bytes())
        manifest["schema_version"] = "1.0.0"
        for row in manifest["files"]:
            if row["path"] == UI_MESSAGE_FILE:
                row["path"] = "native-user-message.jsonl"
        path.write_text(json.dumps(manifest), encoding="utf-8")
        digest = self.refresh_manifest()
        with self.assertRaisesRegex(Stage2Error, "native-user-message"):
            self.inspect(digest)

    def test_unconfirmed_malformed_depth_or_surrogate_is_rejected(self):
        bad = deepcopy(self.submission)
        bad["confirmed"] = False
        invalid_decision = deepcopy(self.submission)
        invalid_decision["decision"] = []
        invalid_unicode = deepcopy(self.submission)
        invalid_unicode["decision"]["user_text"] = "bad \ud800"
        raws = [
            json.dumps(x).encode("utf-8")
            for x in [bad, invalid_decision, invalid_unicode]
        ]
        raws.append(("[" * 2000 + "0" + "]" * 2000).encode())
        raws.append(None)
        for raw in raws:
            with (
                self.subTest(raw_type=type(raw).__name__),
                self.assertRaises(Stage2Error),
            ):
                read_ui_submission(raw)

    def test_string_version_submission_roundtrip_preserves_typed_origin(self):
        self.submission.update(schema_version="1.1.0", input_version="20261009-A03")
        self.record(input_version="20261009-A03")
        result = prepare_planning_handoff(
            self.delivery,
            self.interaction,
            expected_delivery_manifest_sha256=self.manifest["manifest_sha256"],
            expected_interaction_file_sha256=hashlib.sha256(
                (self.interaction / "interaction.json").read_bytes()
            ).hexdigest(),
            output_dir=self.package,
        )
        checked = self.inspect(result["manifest"]["manifest_sha256"])
        self.assertEqual(
            checked["handoff"]["input_origin"]["input_version"], "20261009-A03"
        )
        self.assertEqual(
            checked["handoff"]["input_origin"]["human_identity"], "not-established"
        )
        self.assertFalse(checked["handoff"]["execution_authorized"])
        from stage3_plan.intake import admit_intake

        admitted = admit_intake(
            self.package,
            self.delivery,
            expected_manifest_sha256=result["manifest"]["manifest_sha256"],
        )
        self.assertEqual(admitted["input_origin"], checked["handoff"]["input_origin"])
        self.assertFalse(admitted["execution_authorized"])
        self.assertEqual(
            (self.package / UI_MESSAGE_FILE).read_bytes(), self.message.read_bytes()
        )

    def test_legacy_submission_does_not_silently_accept_string_version(self):
        self.submission["input_version"] = "20261009-A03"
        with self.assertRaises(Stage2Error):
            read_ui_submission(json.dumps(self.submission).encode())
        self.submission["schema_version"] = "1.1.0"
        for version in (True, 1.0, "", " ", "x" * 201, "a\0b", None):
            self.submission["input_version"] = version
            with self.subTest(version=repr(version)), self.assertRaises(Stage2Error):
                read_ui_submission(json.dumps(self.submission).encode())

    def test_expected_version_binding_requires_exact_type_and_value(self):
        raw = json.dumps(self.submission).encode()
        for expected in (True, 1.0, "1", 2):
            with self.subTest(expected=repr(expected)), self.assertRaises(Stage2Error):
                read_ui_submission(raw, expected={"input_version": expected})
        self.submission.update(schema_version="1.1.0", input_version="20261009-A03")
        raw = json.dumps(self.submission).encode()
        self.assertEqual(
            read_ui_submission(raw, expected={"input_version": "20261009-A03"})[
                "input_version"
            ],
            "20261009-A03",
        )
        with self.assertRaises(Stage2Error):
            read_ui_submission(raw, expected={"input_version": "20261009-A04"})


if __name__ == "__main__":
    unittest.main()
