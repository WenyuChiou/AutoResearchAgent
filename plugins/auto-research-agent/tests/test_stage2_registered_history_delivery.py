"""Opt-in registered history reaches delivery without native or human claims."""

import contextlib
import copy
import io
import json
import shutil
import unittest

import test_stage2_revision_provenance as history_fixtures
from stage2_common import Stage2Error
from stage2_workflow import add_snapshot, inspect_workflow
from stage2_workflow.delivery import build_delivery, inspect_delivery
from stage2_workflow.__main__ import main


class RegisteredHistoryDeliveryTests(unittest.TestCase):
    setUp = history_fixtures.RevisionProvenanceTests.setUp
    _write_receipt = history_fixtures.RevisionProvenanceTests._write_receipt
    _assessment = history_fixtures.RevisionProvenanceTests._assessment
    _inputs = history_fixtures.RevisionProvenanceTests._inputs

    def _deliver(self, output, **options):
        batch, reviews, resolutions = self._inputs()
        return build_delivery(
            self.workflow,
            batch,
            reviews,
            resolutions,
            output,
            self.state["head_sha256"],
            record_registered_history=True,
            **options,
        )

    def test_table_only_bridge_and_revision_replay_after_original_removal(self):
        self.current = copy.deepcopy(self.current)
        self.current["packet_id"] = "table-only-bridge"
        self.current["comparison"] += " Registered comparison clarification."
        path = self.update / "bridge.json"
        path.write_text(json.dumps(self.current), encoding="utf-8")
        event = add_snapshot(
            self.workflow,
            path,
            self.update,
            "Clarify the comparison only.",
            self.impact,
            self.state["head_sha256"],
        )
        self.state = inspect_workflow(self.workflow, event["event_sha256"])
        output = self.root / "recorded-delivery"
        manifest = self._deliver(output)
        self.assertTrue(self.workflow.resolve().is_relative_to(self.root.resolve()))
        shutil.rmtree(self.workflow)
        selection = inspect_delivery(output, manifest["manifest_sha256"])["selection"]
        self.assertEqual(selection["action_record_status"], "complete")
        self.assertEqual(manifest["schema_version"], "1.3.0")
        self.assertEqual(manifest["human_selection"], "pending")
        self.assertFalse(manifest["actual_execution_attested"])
        self.assertFalse(manifest["stage3_execution_authorized"])

    def test_authenticated_receipts_cannot_be_silently_replaced(self):
        with self.assertRaisesRegex(Stage2Error, "mixed-provenance"):
            self._deliver(
                self.root / "invalid", source_update_receipts=[("x", "a" * 64)]
            )
        with self.assertRaisesRegex(Stage2Error, "mixed-provenance"):
            self._deliver(self.root / "invalid-guard", guard_bundles={})
        self.assertFalse((self.root / "invalid").exists())

    def test_cli_records_explicit_non_native_scope(self):
        batch, reviews, resolutions = self._inputs()
        argv = [
            "deliver",
            "--run",
            str(self.workflow),
            "--expected-head",
            self.state["head_sha256"],
            "--output",
            str(self.root / "cli-output"),
            "--record-registered-history",
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
            (self.root / "cli-output/delivery_manifest.json").read_bytes()
        )
        self.assertEqual(
            manifest["revision_provenance_scope"], "registered-content-history-only"
        )


if __name__ == "__main__":
    unittest.main()
