"""Exact prior local records bridge initial revisions, without native admission."""

import contextlib
import copy
import io
import json
import shutil
import unittest

import test_stage2_revision_provenance as fixtures
from stage2_common import Stage2Error
from stage2_eval import validate_action_record
from stage2_workflow import add_snapshot, initialize_workflow, inspect_workflow
from stage2_workflow.__main__ import main
from stage2_workflow.delivery import build_delivery, inspect_delivery


class ImportedHistoryDeliveryTests(unittest.TestCase):
    _write_receipt = fixtures.RevisionProvenanceTests._write_receipt
    _assessment = fixtures.RevisionProvenanceTests._assessment
    _inputs = fixtures.RevisionProvenanceTests._inputs
    _build = fixtures.RevisionProvenanceTests._build

    def setUp(self):
        fixtures.RevisionProvenanceTests.setUp(self)
        self.prior, self.prior_manifest = self._build("prior")
        self.old_workflow = self.workflow
        self.workflow = self.root / "new-workflow"
        initialize_workflow(
            self.packet_path,
            self.update,
            self.workflow,
            {},
            {"path": "policy.json", "sha256": "a" * 64},
        )
        self.state = inspect_workflow(self.workflow)
        self.bindings = [(self.prior, self.prior_manifest["manifest_sha256"])]

    def deliver(self, name="output", **options):
        batch, reviews, resolutions = self._inputs()
        return build_delivery(
            self.workflow,
            batch,
            reviews,
            resolutions,
            self.root / name,
            self.state["head_sha256"],
            record_registered_history=True,
            **options,
        )

    def read(self, name, manifest):
        return inspect_delivery(self.root / name, manifest["manifest_sha256"])

    def add_next_snapshot(self):
        current = copy.deepcopy(self.current)
        current["packet_id"] = "registered-third-versions"
        for candidate in self.current["candidates"]:
            if candidate["version"] == 2:
                revised = copy.deepcopy(candidate)
                revised.update(
                    version=3,
                    parent_version=2,
                    question=candidate["question"] + " bounded again",
                )
                current["candidates"].append(revised)
        path = self.update / "third-packet.json"
        path.write_text(json.dumps(current), encoding="utf-8")
        event = add_snapshot(
            self.workflow,
            path,
            self.update,
            "Record an actual new revision.",
            self.impact,
            self.state["head_sha256"],
        )
        self.current = current
        self.state = inspect_workflow(self.workflow, event["event_sha256"])

    def test_import_closes_real_initial_gaps_and_preserves_non_native_scope(self):
        manifest = self.deliver(imported_history_deliveries=self.bindings)
        result = self.read("output", manifest)
        selection = result["selection"]
        self.assertEqual(selection["action_record_status"], "complete")
        self.assertEqual(manifest["schema_version"], "1.4.0")
        self.assertEqual(manifest["human_selection"], "pending")
        self.assertFalse(manifest["actual_execution_attested"])
        self.assertFalse(manifest["stage3_execution_authorized"])
        validate_action_record(
            selection["action_record"], selection["evaluation_packet"]
        )

    def test_without_explicit_import_real_missing_history_stays_missing(self):
        manifest = self.deliver()
        selection = self.read("output", manifest)["selection"]
        self.assertEqual(manifest["schema_version"], "1.3.0")
        self.assertEqual(selection["action_record_status"], "unavailable")

    def test_import_and_new_registered_transitions_replay_portably(self):
        self.add_next_snapshot()
        manifest = self.deliver(imported_history_deliveries=self.bindings)
        expected = self.read("output", manifest)["selection"]
        for path in (self.old_workflow, self.workflow, self.prior, self.update):
            self.assertTrue(path.resolve().is_relative_to(self.root.resolve()))
            shutil.rmtree(path)
        result = self.read("output", manifest)["selection"]
        self.assertEqual(result, expected)
        self.assertEqual(result["action_record_status"], "complete")
        self.assertEqual(len(result["action_record"]["revision_history"]), 4)

    def test_wrong_retained_receipt_rejected_before_output_creation(self):
        with self.assertRaisesRegex(Stage2Error, "receipt-mismatch"):
            self.deliver(imported_history_deliveries=[(self.prior, "f" * 64)])
        self.assertFalse((self.root / "output").exists())

    def test_mismatching_initial_candidate_rejected_before_output_creation(self):
        changed = copy.deepcopy(self.current)
        changed["candidates"][-1]["question"] += " different"
        path = self.update / "changed-initial.json"
        path.write_text(json.dumps(changed), encoding="utf-8")
        other = self.root / "mismatching-workflow"
        initialize_workflow(
            path, self.update, other, {}, {"path": "policy.json", "sha256": "a" * 64}
        )
        self.workflow = other
        self.current = changed
        self.state = inspect_workflow(other)
        with self.assertRaisesRegex(Stage2Error, "candidate-mismatch"):
            self.deliver(imported_history_deliveries=self.bindings)
        self.assertFalse((self.root / "output").exists())

    def test_import_requires_explicit_registered_mode(self):
        batch, reviews, resolutions = self._inputs()
        with self.assertRaisesRegex(Stage2Error, "requires-registered-history"):
            build_delivery(
                self.workflow,
                batch,
                reviews,
                resolutions,
                self.root / "output",
                self.state["head_sha256"],
                imported_history_deliveries=self.bindings,
            )
        self.assertFalse((self.root / "output").exists())

    def test_invalid_import_option_rejected(self):
        with self.assertRaisesRegex(Stage2Error, "option-invalid"):
            self.deliver(imported_history_deliveries={})

    def test_duplicate_import_cannot_double_count_a_transition(self):
        with self.assertRaisesRegex(Stage2Error, "duplicate-transition"):
            self.deliver(imported_history_deliveries=self.bindings * 2)
        self.assertFalse((self.root / "output").exists())

    def test_cli_import_is_explicit_and_versioned(self):
        batch, reviews, resolutions = self._inputs()
        argv = [
            "deliver",
            "--run",
            str(self.workflow),
            "--expected-head",
            self.state["head_sha256"],
            "--output",
            str(self.root / "output"),
            "--record-registered-history",
            "--imported-history-delivery",
            str(self.prior),
            self.prior_manifest["manifest_sha256"],
        ]
        for name, value in (
            ("batch", batch),
            ("reviews", reviews),
            ("resolutions", resolutions),
        ):
            path = self.root / f"{name}.json"
            path.write_text(json.dumps(value), encoding="utf-8")
            argv.extend(["--" + name, str(path)])
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(argv), 0)
        manifest = json.loads(
            (self.root / "output/delivery_manifest.json").read_bytes()
        )
        self.assertEqual(
            self.read("output", manifest)["selection"]["action_record_status"],
            "complete",
        )


if __name__ == "__main__":
    unittest.main()
