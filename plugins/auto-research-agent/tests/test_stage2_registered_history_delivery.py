"""Opt-in registered history reaches delivery without native or human claims."""

import contextlib
import copy
import hashlib
import io
import json
import shutil
import unittest

import test_stage2_revision_provenance as history_fixtures
from stage2_common import Stage2Error
from stage2_workflow import add_snapshot, inspect_workflow
from stage2_workflow.registered_history import capture_registered_history
from stage2_workflow.delivery import build_delivery, inspect_delivery
from stage2_workflow.__main__ import main


class RegisteredHistoryPriorWorkReceiptTests(unittest.TestCase):
    def _fixture(self):
        import test_stage2_prior_work_delivery as prior_work_fixtures

        fixture = prior_work_fixtures.Stage2PriorWorkDeliveryTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        return fixture, fixture._ordinary_delivery_inputs()

    def test_registered_delivery_retains_prior_work_receipts_after_original_move(self):
        fixture, (workflow, state, packet, batch) = self._fixture()
        output = fixture.root / "registered-prior-work-delivery"
        before = {
            path.relative_to(workflow): path.read_bytes()
            for path in workflow.rglob("*")
            if path.is_file()
        }
        manifest = build_delivery(
            workflow,
            batch,
            [],
            {"candidate_resolutions": [], "next_step": "Complete independent reviews."},
            output,
            state["head_sha256"],
            record_registered_history=True,
        )
        self.assertEqual(
            before,
            {
                path.relative_to(workflow): path.read_bytes()
                for path in workflow.rglob("*")
                if path.is_file()
            },
        )
        workflow.rename(fixture.root / "moved-workflow")
        fixture.sources.rename(fixture.root / "moved-sources")
        inspected = inspect_delivery(output, manifest["manifest_sha256"])
        self.assertEqual(inspected["input_packet"], packet)
        receipt = (
            output
            / "registered_history/workflow/snapshots/000001/checker"
            / "prior_work_receipts"
            / fixture.receipt_path
        )
        self.assertEqual(
            receipt.read_bytes(),
            (fixture.root / "moved-sources" / fixture.receipt_path).read_bytes(),
        )
        self.assertFalse(manifest["stage3_execution_authorized"])

    def test_registered_history_copies_each_snapshots_receipt_dependencies(self):
        fixture, (workflow, state, packet, _) = self._fixture()
        current = copy.deepcopy(packet)
        search = current["prior_work_reviews"][0]["searches"][0]
        old_receipt = fixture.receipt_path
        new_receipt = "prior-work/updated-search.json"
        raw = json.loads((fixture.sources / old_receipt).read_bytes())
        raw["query"] = search["query"] = "A changed bounded saved query."
        encoded = json.dumps(raw).encode("utf-8")
        (fixture.sources / new_receipt).write_bytes(encoded)
        search.update(
            raw_path=new_receipt, raw_sha256=hashlib.sha256(encoded).hexdigest()
        )
        path = fixture.root / "updated-dossier.json"
        path.write_text(json.dumps(current), encoding="utf-8")
        impact = [
            {"candidate_id": key, "status": "unaffected", "reason": "Dossier only."}
            for key in sorted({row["candidate_id"] for row in packet["candidates"]})
        ]
        event = add_snapshot(
            workflow,
            path,
            fixture.sources,
            "Update the bounded dossier only.",
            impact,
            state["head_sha256"],
        )
        _, files = capture_registered_history(
            inspect_workflow(workflow, event["event_sha256"])
        )
        prefix = "registered_history/workflow/snapshots/"
        self.assertEqual(
            files[prefix + "000001/checker/prior_work_receipts/" + old_receipt],
            (fixture.sources / old_receipt).read_bytes(),
        )
        self.assertEqual(
            files[prefix + "000002/checker/prior_work_receipts/" + new_receipt],
            encoded,
        )
        self.assertNotIn(
            prefix + "000002/checker/prior_work_receipts/" + old_receipt, files
        )

    def test_registered_delivery_rejects_missing_or_changed_receipt(self):
        for changed in (False, True):
            with self.subTest(changed=changed):
                fixture, (workflow, state, _, batch) = self._fixture()
                output = fixture.root / "registered-prior-work-delivery"
                manifest = build_delivery(
                    workflow,
                    batch,
                    [],
                    {
                        "candidate_resolutions": [],
                        "next_step": "Complete independent reviews.",
                    },
                    output,
                    state["head_sha256"],
                    record_registered_history=True,
                )
                receipt = (
                    output
                    / "registered_history/workflow/snapshots/000001/checker"
                    / "prior_work_receipts"
                    / fixture.receipt_path
                )
                if changed:
                    receipt.write_bytes(b"changed saved receipt")
                else:
                    receipt.unlink()
                with self.assertRaises(Stage2Error):
                    inspect_delivery(output, manifest["manifest_sha256"])


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
