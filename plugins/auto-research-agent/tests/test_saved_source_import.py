"""Controlled dispatch/projection tests; fixtures confer no real Core acceptance."""

import copy
import hashlib
import json
import unittest
from unittest.mock import patch

import test_stage1_stage2_handoff as legacy
from research_workspace.saved_admission import check_handoff
from stage2_common.contract import Stage2Error, canonical_hash, validate_packet
from stage2_workflow.import_stage1 import build_stage2_seed


class SavedSourceImportTests(unittest.TestCase):
    def setUp(self):
        self.fixture = legacy.Stage1Stage2HandoffTests(methodName="runTest")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        f = self.fixture
        self.note = self.save("full-note.json", {"synthetic": "Complete fixture note"})
        text = self.save("saved-text.txt", f.source_text)
        self.snapshot = self.save(
            "snapshot.json",
            {
                "rows": [
                    {
                        "work_id": "work1",
                        "version_id": "v1",
                        "source_id": "src1",
                        "extracted_text": text,
                        "full_note": self.note,
                    }
                ]
            },
        )
        self.acceptance = self.save(
            "controlled-acceptance.json", {"synthetic_only": True}
        )
        self.handoff = {
            "kind": "Stage1Handoff",
            "schema_version": "2.0.0",
            "source_mode": "saved-source-current-admission",
            "source_run_id": "synthetic-current-admission",
            "source_state_sha256": self.snapshot["sha256"],
            "snapshot_ref": self.snapshot,
            "acceptance_ref": self.acceptance,
            "project_id": "synthetic",
            "input_version": "input1",
            "deliverable_manifest_sha256": f.deliverable_manifest_sha256,
            "brief_sha256": hashlib.sha256(f.brief_path.read_bytes()).hexdigest(),
            "papers": [
                {
                    "work_id": "work1",
                    "title": f.records["papers"][0]["title"],
                    "listed_version_id": "v1",
                    "reviewed_version_id": "v1",
                }
            ],
            "comparison_dimensions": legacy.DIMENSIONS,
            "resources_preserved": {
                "queries": {"used": 72, "limit": 72},
                "acquisitions": {"used": 64, "limit": 64},
            },
            "limitations": [
                "Synthetic current admission; missing historical trace.",
                "Scientific claims remain unverified.",
            ],
            "stage1_gate": {
                "status": "ready-for-import",
                "quantity_decision": "stop-count-target-and-covered",
                "remaining": [],
            },
            "eligible_for_stage2": True,
            "stage1_completed": False,
            "stage2": {"status": "not-started", "execution_authorized": False},
        }
        check_handoff(self.handoff)
        self.save_handoff()

    def save(self, name, value):
        raw = value if isinstance(value, bytes) else json.dumps(value).encode()
        (self.fixture.root / name).write_bytes(raw)
        return {
            "path": name,
            "sha256": hashlib.sha256(raw).hexdigest(),
            "bytes": len(raw),
        }

    def save_handoff(self):
        self.fixture.handoff_path.write_text(json.dumps(self.handoff), encoding="utf-8")

    def build(self, *, trusted=True, replay=None):
        f = self.fixture
        # These stubs isolate import dispatch and the real downstream consumer.
        # Gate binding and actual prerequisite replay have separate tests/evidence.
        with (
            patch("stage2_workflow.import_stage1.deliverable_package.validate"),
            patch(
                "stage2_workflow.import_stage1._source_bytes",
                return_value=(f.source_text, f.source_result),
            ),
            patch(
                "research_workspace.saved_admission.inspect_saved_admission",
                return_value=self.handoff if replay is None else replay,
            ),
        ):
            kwargs = (
                {
                    "saved_source_root": f.root,
                    "saved_source_acceptance_sha256": self.acceptance["sha256"],
                }
                if trusted
                else {}
            )
            return build_stage2_seed(
                f.deliverable,
                f.deliverable_manifest_sha256,
                f.handoff_path,
                hashlib.sha256(f.handoff_path.read_bytes()).hexdigest(),
                f.brief_path,
                f.resources_path,
                f.output,
                **kwargs,
            )

    def test_controlled_positive_projection_retains_notes_claims_resources_and_unstarted_boundary(
        self,
    ):
        receipt = self.build()
        packet = self.fixture.packet()
        validate_packet(packet, self.fixture.output)
        self.assertEqual(receipt["schema_version"], "2.0.0")
        self.assertEqual(packet["candidates"], [])
        self.assertEqual(packet["upstream"]["stage2"], self.handoff["stage2"])
        self.assertEqual(
            packet["upstream"]["source_state_sha256"], self.snapshot["sha256"]
        )
        self.assertEqual(
            receipt["resources_preserved"], self.handoff["resources_preserved"]
        )
        self.assertEqual(receipt["candidate_count"], 0)
        self.assertFalse(receipt["stage2_execution_authorized"])
        self.assertEqual(
            receipt["note_inventory_sha256"], canonical_hash(receipt["note_inventory"])
        )
        note = receipt["note_inventory"]["work1"]
        self.assertEqual(
            hashlib.sha256(
                (self.fixture.output / note["path"]).read_bytes()
            ).hexdigest(),
            self.note["sha256"],
        )
        self.assertEqual(packet["evidence"][0]["relation"], "unverified")
        self.assertTrue(set(self.handoff["limitations"]).issubset(packet["unresolved"]))
        for field in ("literature", "evidence", "sources"):
            changed = copy.deepcopy(packet)
            changed[field][0]["version_id"] = "different-version"
            with self.subTest(field=field), self.assertRaises(Stage2Error):
                validate_packet(changed, self.fixture.output)

    def test_missing_acceptance_and_rehashed_author_written_gate_leave_no_seed(self):
        with self.assertRaisesRegex(Stage2Error, "external-Core-acceptance"):
            self.build(trusted=False)
        self.assertFalse(self.fixture.output.exists())
        blocked = copy.deepcopy(self.handoff)
        blocked["eligible_for_stage2"] = False
        blocked["stage1_gate"]["status"] = "blocked"
        with self.assertRaisesRegex(Stage2Error, "replay-mismatch"):
            self.build(replay=blocked)
        self.assertFalse(self.fixture.output.exists())

    def test_source_and_note_changes_cleanup_only_owned_seed(self):
        self.fixture.source_text = b"changed after admission"
        with self.assertRaisesRegex(Stage2Error, "projected-text-mismatch"):
            self.build()
        self.assertFalse(self.fixture.output.exists())
        self.fixture.source_text = (self.fixture.root / "saved-text.txt").read_bytes()
        (self.fixture.root / self.note["path"]).write_bytes(b"changed note")
        with self.assertRaises(Stage2Error):
            self.build()
        self.assertFalse(self.fixture.output.exists())

    def test_legacy_handoff_rejects_new_arguments(self):
        self.handoff = self.fixture.handoff
        self.save_handoff()
        with self.assertRaisesRegex(Stage2Error, "arguments-require-handoff-v2"):
            self.build()
        self.assertFalse(self.fixture.output.exists())


if __name__ == "__main__":
    unittest.main()
