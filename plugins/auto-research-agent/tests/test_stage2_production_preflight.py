"""Production-scope Stage 2 runtime preflight contract tests."""

# ruff: noqa: E402 -- import the repository CLI and sibling fixture directly.

import copy
from pathlib import Path
import sys
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "cli"))

from stage2_live.preflight import PreflightError
import test_stage2_preflight as fixture_module
import test_stage2_codemode_preflight as decoder_fixtures


class Stage2ProductionPreflightTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixture_module.Stage2PreflightTests(
            methodName="test_positive_fixture_binds_real_events_contexts_and_bytes"
        )
        self.fixture.setUp()
        self.spec = copy.deepcopy(self.fixture.spec)
        self.spec["kind"] = "Stage2ProductionRuntimeProbeSpec"
        del self.spec["probes"]["isolation"]
        events, sessions = decoder_fixtures.Stage2ProductionChildWitnessTests(
            methodName="test_child_requires_matching_host_link_lineage_and_result"
        ).fixture()
        for event in events:
            payload = event["payload"]
            if payload.get("call_id") == "spawn":
                payload["call_id"] = "child-1"
            if payload.get("item", {}).get("id") == "spawn":
                payload["item"]["id"] = "child-1"
        import json

        primary = self.fixture.sessions / "primary.jsonl"
        rows = [json.loads(line) for line in primary.read_text().splitlines()]
        self.fixture.write_jsonl("primary.jsonl", rows + events)
        self.fixture.write_jsonl("child.jsonl", sessions[0][1])

    def tearDown(self):
        self.fixture.tearDown()

    def test_four_capabilities_pass_without_sentinels_or_inventory(self):
        report = self.fixture.inspect(self.spec, inventory_receipt=None)

        self.assertEqual(report["kind"], "Stage2ProductionRuntimePreflight")
        self.assertEqual(report["validation_scope"], "production-single")
        self.assertEqual(report["filesystem_read_isolation"], "not-assessed")
        self.assertEqual(report["quality_improvement"], "not-established")
        self.assertFalse(report["formal_ready"])
        self.assertTrue(report["runtime_gate"])
        self.assertEqual(
            set(report["capabilities"]), {"read", "write", "search", "child"}
        )
        self.assertTrue(
            all(row["status"] == "passed" for row in report["capabilities"].values())
        )
        self.assertEqual(
            report["observations"],
            [f"inventory-{name}-unknown" for name in sorted(report["inventory"])],
        )

    def test_legacy_probe_still_rejects_missing_sentinels(self):
        legacy = copy.deepcopy(self.fixture.spec)
        del legacy["probes"]["isolation"]
        with self.assertRaisesRegex(PreflightError, "exact capability probes"):
            self.fixture.inspect(legacy)

    def test_denied_read_and_requested_policy_mismatch_block(self):
        self.fixture.write_sessions(read_output="Permission denied by sandbox policy")
        denied = self.fixture.inspect(self.spec, inventory_receipt=None)
        self.assertFalse(denied["runtime_gate"])
        self.assertIn("read-capability-failed", denied["blockers"])

        self.fixture.write_sessions()
        self.fixture.record["stable_request_binding"]["policy_bindings"] = {
            "sandbox": "read-only",
            "network_access": True,
        }
        mismatch = self.fixture.inspect(self.spec, inventory_receipt=None)
        self.assertFalse(mismatch["runtime_gate"])
        self.assertIn("requested-sandbox-mismatch", mismatch["blockers"])

    def test_supplied_inventory_hash_mismatch_is_an_error(self):
        receipt = copy.deepcopy(self.fixture.inventory_receipt)
        receipt["entries"]["instructions"]["sha256"] = "0" * 64
        with self.assertRaisesRegex(PreflightError, "raw-response hash differs"):
            self.fixture.inspect(self.spec, inventory_receipt=receipt)

    def test_rejected_child_lineage_cannot_fall_back_to_text_link(self):
        import json

        path = self.fixture.sessions / "child.jsonl"
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        rows[0]["payload"]["source"]["subagent"]["thread_spawn"]["parent_thread_id"] = (
            "foreign-parent"
        )
        self.fixture.write_jsonl("child.jsonl", rows)
        report = self.fixture.inspect(self.spec, inventory_receipt=None)
        self.assertFalse(report["runtime_gate"])
        self.assertIn("child-link-mismatch", report["blockers"])

    def test_supplied_instruction_owner_mismatch_is_rejected(self):
        receipt = copy.deepcopy(self.fixture.inventory_receipt)
        receipt["entries"]["instructions"].update(
            self.fixture.write_raw(
                "instructions.json",
                {
                    "result": {
                        "thread": {"id": "foreign-thread"},
                        "instructionSources": [],
                    }
                },
            )
        )
        with self.assertRaisesRegex(PreflightError, "thread mismatch"):
            self.fixture.inspect(self.spec, inventory_receipt=receipt)

    def test_missing_instruction_owner_is_unknown_and_bad_subagent_is_typed(self):
        import json

        report = self.fixture.inspect(self.spec)
        self.assertTrue(report["runtime_gate"])
        self.assertEqual(report["inventory"]["instructions"]["status"], "unknown")
        path = self.fixture.sessions / "child.jsonl"
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        rows[0]["payload"]["source"]["subagent"] = "wrong-shape"
        self.fixture.write_jsonl("child.jsonl", rows)
        with self.assertRaisesRegex(PreflightError, "subagent metadata"):
            self.fixture.inspect(self.spec, inventory_receipt=None)


if __name__ == "__main__":
    unittest.main()
