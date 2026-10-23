"""Native integer intake through real saved admission and the receipt 2.1 consumer.

Source/review/HTML evidence is authored synthetic fixture evidence. The native
integration uses real admission, HostReplay, import, workflow and reopen validators.
Separate private receipt-guard units use an explicitly test-only evidence context;
they do not establish admission authority. No research execution is authorized.
"""

from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cli"))

from research_workspace_native.project_intake import ProjectIntakeService
from research_workspace_native.project_stage2 import (
    ProjectStage2Service,
    _verify_import_receipt,
)
from research_workspace_native.session_api import SessionApiError
from stage1_deliverable import sources
from stage1_deliverable.common import canonical, inventory, sha
from stage2_common import canonical_hash
from stage2_workflow import inspect_workflow
import test_saved_source_stage2_intake as replay_fixture
from test_workspace_project_intake import authenticate, compile_body, submit_body


class NativeSavedHostReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        replay_fixture.SavedReplayImportIntegrationTests.setUpClass()

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="native-int-host-replay-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.store_root = self.root / "projects"
        self.intake = ProjectIntakeService(self.store_root, authenticate=authenticate)
        self.addCleanup(lambda: self.intake.close())
        created = self.intake.create(
            "alice-token",
            {"key": "create", "topic": "Synthetic household research"},
        )
        self.ref = created["project_ref"]
        view = self.intake.read("alice-token", self.ref)
        submitted = submit_body(view)
        submitted.update(
            formal_target=1,
            priority_reading_target=1,
            user_input="One authored work exercises native replay; no research authority.",
        )
        self.intake.submit("alice-token", self.ref, submitted)
        view = self.intake.read("alice-token", self.ref)
        self.intake.compile("alice-token", self.ref, compile_body(view))
        self.binding = self.intake.binding(self.ref)
        self.assertIs(type(self.binding["input_version"]), int)
        fixture = replay_fixture.SavedReplayImportIntegrationTests()
        fixture.native_binding = self.binding
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.fixture = fixture
        self.service = ProjectStage2Service(self.intake)
        self.registration = {
            "deliverable_dir": fixture.f.package,
            "expected_manifest_sha256": fixture.manifest["sha256"],
            "handoff_path": fixture.handoff_path,
            "expected_handoff_sha256": sha(fixture.handoff_path.read_bytes()),
            "resources_path": fixture.resources,
            "expected_resources_sha256": sha(fixture.resources.read_bytes()),
            "policy_ref": {
                "route": "stage2-general-v3/daily_v3",
                "execution_authorized": False,
            },
            "saved_source_root": fixture.root,
            "saved_source_acceptance_sha256": fixture.acceptance_ref["sha256"],
            **fixture.replay_args,
        }

    def activation_body(self, offer):
        view = self.intake.read("alice-token", self.ref)
        return {
            "key": "activate-real-native-int",
            "revision": view["revision"],
            "input_version": view["input_version"],
            "brief_sha256": view["brief_sha256"],
            "offer_ref": offer["offer_ref"],
            "offer_sha256": offer["offer_sha256"],
            "confirmed": True,
        }

    def test_native_integer_context_receipt_21_reopens_without_admission_stub(self):
        fixture = self.fixture
        self.assertIs(type(fixture.snapshot["input_version"]), int)
        self.assertIs(type(fixture.handoff["input_version"]), int)
        self.assertIs(type(fixture.replay["input_version"]), int)
        self.assertEqual(
            fixture.brief.read_bytes(), Path(self.binding["brief_path"]).read_bytes()
        )
        package_before = inventory(fixture.f.package)
        with patch.object(
            sources,
            "validate_archive",
            side_effect=AssertionError("no new source replay"),
        ):
            offer = self.service.register(self.ref, **self.registration)
            body = self.activation_body(offer)
            result = self.service.activate("alice-token", self.ref, body)
            receipt = result["import_receipt"]
            self.assertEqual(receipt["schema_version"], "2.1.0")
            self.assertEqual(receipt["source_canonical_records_version"], "1.0.0")
            self.assertEqual(
                receipt["host_replay"]["sha256"],
                fixture.replay_args["trusted_host_replay_sha256"],
            )
            self.assertFalse(receipt["host_replay"]["core_acceptance"])
            self.assertFalse(receipt["stage2_execution_authorized"])
            self.assertFalse(result["execution_authorized"])
            self.assertEqual(result["daily_v3"], "not-started")
            bound = self.service.binding(self.ref)
            packet = json.loads(Path(bound["packet_path"]).read_bytes())
            self.assertEqual(packet["candidates"], [])
            self.assertEqual(
                packet["upstream"]["stage2"],
                {"status": "not-started", "execution_authorized": False},
            )
            note = receipt["note_inventory"]["fixture-0"]
            self.assertRegex(note["path"], r"^notes/n\d{6}\.json$")
            note_path = bound["source_root"] / note["path"]
            original_note = note_path.read_bytes()
            self.assertEqual(
                sha(original_note), fixture.snapshot["rows"][0]["full_note"]["sha256"]
            )
            workflow = inspect_workflow(bound["packet_path"].parent.parent / "workflow")
            self.assertEqual(
                workflow["manifest"]["initial_packet_sha256"], receipt["packet_sha256"]
            )
            self.intake.close()
            self.intake = ProjectIntakeService(
                self.store_root, authenticate=authenticate
            )
            self.service = ProjectStage2Service(self.intake)
            self.assertEqual(
                self.service.binding(self.ref)["packet_sha256"],
                receipt["packet_sha256"],
            )
            replayed = self.service.activate("alice-token", self.ref, body)
            self.assertTrue(replayed["replayed"])
            self.assertEqual(replayed["import_receipt"], receipt)
            self.assertEqual(inventory(fixture.f.package), package_before)

            original_handoff = fixture.handoff_path.read_bytes()
            history = self.intake.history("alice-token", self.ref)
            for wrong_version in (
                str(self.binding["input_version"]),
                True,
                False,
                0,
                -1,
                1.0,
            ):
                with self.subTest(input_version=wrong_version):
                    handoff = deepcopy(fixture.handoff)
                    handoff["input_version"] = wrong_version
                    fixture.handoff_path.write_bytes(canonical(handoff))
                    registration = {
                        **self.registration,
                        "expected_handoff_sha256": sha(
                            fixture.handoff_path.read_bytes()
                        ),
                    }
                    with self.assertRaises((SessionApiError, ValueError)):
                        self.service.register(self.ref, **registration)
                    self.assertEqual(
                        self.intake.history("alice-token", self.ref), history
                    )
            fixture.handoff_path.write_bytes(original_handoff)
            with self.assertRaises((SessionApiError, ValueError)):
                self.service.register(
                    self.ref,
                    **{**self.registration, "trusted_host_replay_sha256": "0" * 64},
                )

            note_path.write_bytes(b"changed full note")
            with self.assertRaises(SessionApiError):
                self.service.binding(self.ref)
            note_path.write_bytes(original_note)
            self.assertEqual(
                self.service.binding(self.ref)["packet_sha256"],
                receipt["packet_sha256"],
            )

            state = self.intake._load("alice", self.ref)
            original_state = deepcopy(state)
            state["stage2_activation"]["import_receipt"]["host_replay"]["sha256"] = (
                "0" * 64
            )
            self.intake._save(state, "synthetic-receipt-tamper-only", {})
            self.intake.db.commit()
            with self.assertRaises(SessionApiError):
                self.service.binding(self.ref)
            self.intake._save(original_state, "synthetic-receipt-restore-only", {})
            self.intake.db.commit()

            view = self.intake.read("alice-token", self.ref)
            changed = submit_body(view)
            changed = {
                key: value
                for key, value in changed.items()
                if key not in {"choices", "formal_target", "priority_reading_target"}
            }
            changed.update(
                key="change-resources", resource_envelope="Changed authored resources."
            )
            self.intake.configure("alice-token", self.ref, changed)
            with self.assertRaises(SessionApiError):
                self.service.binding(self.ref)


class _TestOnlyEvidenceContext:
    """Evidence double for the private guard, never an admitted HostReplay."""

    def __init__(self, evidence):
        self._evidence = deepcopy(evidence)

    def evidence(self):
        return deepcopy(self._evidence)


class ImportReceiptGuardTests(unittest.TestCase):
    """Exercise receipt discrimination with real, small bound files only."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="receipt-guard-unit-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        note_path = self.root / "notes/n000001.json"
        note_path.parent.mkdir()
        note_path.write_bytes(canonical({"synthetic_full_note": "guard unit only"}))
        note = {
            "path": "notes/n000001.json",
            "version_id": "synthetic-version",
            "sha256": sha(note_path.read_bytes()),
        }
        snapshot = {
            "rows": [
                {
                    "work_id": "synthetic-work",
                    "version_id": note["version_id"],
                    "full_note": {
                        "path": note["path"],
                        "sha256": note["sha256"],
                        "bytes": note_path.stat().st_size,
                    },
                }
            ]
        }
        snapshot_path = self.root / "snapshot.json"
        snapshot_path.write_bytes(canonical(snapshot))
        manifest_path = self.root / "provenance_manifest.json"
        manifest_path.write_bytes(
            canonical({"canonical_records": {"schema_version": "1.0.0"}})
        )
        self.inputs = {
            "saved_source_root": self.root,
            "saved_source_acceptance_sha256": "a" * 64,
            "deliverable_dir": self.root,
            "manifest_sha256": sha(manifest_path.read_bytes()),
        }
        self.handoff = {
            "snapshot_ref": {
                "path": "snapshot.json",
                "sha256": sha(snapshot_path.read_bytes()),
                "bytes": snapshot_path.stat().st_size,
            },
            "resources_preserved": True,
        }
        notes = {"synthetic-work": note}
        self.legacy = {
            "kind": "Stage1Stage2ImportReceipt",
            "schema_version": "2.0.0",
            "status": "ready-for-explicit-stage2-start",
            "source_mode": "saved-source-current-admission",
            "saved_snapshot_sha256": self.handoff["snapshot_ref"]["sha256"],
            "Core_acceptance_sha256": self.inputs["saved_source_acceptance_sha256"],
            "resources_preserved": True,
            "note_inventory": notes,
            "note_inventory_sha256": canonical_hash(notes),
            "candidate_count": 0,
            "stage2_execution_authorized": False,
        }
        evidence = {
            "kind": "HostReplayReceipt",
            "schema_version": "1.0.0",
            "source_count": 1,
            "sha256": "b" * 64,
            "mode": "saved-offline-replay",
            "new_source_execution": False,
            "core_acceptance": False,
        }
        self.context = _TestOnlyEvidenceContext(evidence)
        self.context_inputs = {
            **self.inputs,
            "trusted_host_replay_sha256": evidence["sha256"],
        }
        self.replayed = {
            **deepcopy(self.legacy),
            "schema_version": "2.1.0",
            "host_replay": evidence,
            "source_canonical_records_version": "1.0.0",
        }

    def verify(self, receipt, inputs, context=None):
        return _verify_import_receipt(
            receipt, inputs, self.handoff, self.root, host_replay=context
        )

    def test_receipt_version_requires_matching_context_and_legacy_omissions(self):
        for receipt, inputs, context in (
            (self.legacy, self.inputs, None),
            (self.replayed, self.context_inputs, self.context),
        ):
            with self.subTest(context=context is not None):
                self.assertIsNone(self.verify(receipt, inputs, context))
                for version in ("2.0.0", "2.1.0", "2.0.1", "2.1.1"):
                    if version == receipt["schema_version"]:
                        continue
                    with self.subTest(version=version):
                        changed = {**receipt, "schema_version": version}
                        with self.assertRaisesRegex(
                            SessionApiError, "stage2-import-receipt-differs"
                        ):
                            self.verify(changed, inputs, context)
        for field, value in (
            ("host_replay", self.context.evidence()),
            ("source_canonical_records_version", "1.0.0"),
        ):
            with self.subTest(legacy_extra=field):
                with self.assertRaisesRegex(
                    SessionApiError, "stage2-import-host-replay-differs"
                ):
                    self.verify({**self.legacy, field: value}, self.inputs)
        with self.assertRaisesRegex(
            SessionApiError, "stage2-import-host-replay-differs"
        ):
            self.verify(self.legacy, self.context_inputs)

    def test_every_host_evidence_field_canonical_version_and_external_pin_are_bound(
        self,
    ):
        self.assertIsNone(self.verify(self.replayed, self.context_inputs, self.context))
        for field, value in (
            ("kind", "different-receipt"),
            ("schema_version", "1.0.1"),
            ("source_count", 2),
            ("source_count", True),
            ("sha256", "0" * 64),
            ("mode", "different-replay-mode"),
            ("new_source_execution", True),
            ("new_source_execution", 0),
            ("core_acceptance", True),
            ("core_acceptance", 0),
            ("unexpected_authority", True),
        ):
            for remove in (False, True):
                if remove and field == "unexpected_authority":
                    continue
                with self.subTest(field=field, value=value, remove=remove):
                    changed = deepcopy(self.replayed)
                    if remove:
                        del changed["host_replay"][field]
                    else:
                        changed["host_replay"][field] = value
                    with self.assertRaisesRegex(
                        SessionApiError, "stage2-import-host-replay-differs"
                    ):
                        self.verify(changed, self.context_inputs, self.context)
        for version in (None, "1.1.0", "1.2.0", "different-version"):
            with self.subTest(canonical_version=version):
                changed = {**self.replayed, "source_canonical_records_version": version}
                with self.assertRaisesRegex(
                    SessionApiError, "stage2-import-host-replay-differs"
                ):
                    self.verify(changed, self.context_inputs, self.context)
        with self.assertRaisesRegex(
            SessionApiError, "stage2-import-host-replay-differs"
        ):
            self.verify(
                self.replayed,
                {**self.context_inputs, "trusted_host_replay_sha256": "0" * 64},
                self.context,
            )


if __name__ == "__main__":
    unittest.main()
