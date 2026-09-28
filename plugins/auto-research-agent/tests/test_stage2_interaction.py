"""Synthetic user-message tests; these do not authenticate a real human."""

import json
import copy
from pathlib import Path
import sys
import unittest

PLUGIN = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(PLUGIN / "cli"), str(PLUGIN / "tests")]

from stage2_common import Stage2Error  # noqa: E402
from stage2_workflow.interaction import record_interaction  # noqa: E402
from stage2_workflow.store import inspect_workflow  # noqa: E402
import test_stage2_delivery as delivery_tests  # noqa: E402


class Stage2InteractionTests(unittest.TestCase):
    def setUp(self):
        self.fixture = delivery_tests.Stage2DeliveryTests(
            "test_full_cycle_binds_package_and_preserves_embedded_checker"
        )
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        f = self.fixture
        self.delivery = f.root / "delivery"
        reviews, resolutions = f._complete_inputs()
        self.manifest = f._build(self.delivery, reviews, resolutions)
        self.message = f.root / "message.jsonl"
        self.quote = "Choose candidate-1 version 1 for detailed planning; retain the 16-week constraint."
        self.message.write_text(
            json.dumps(
                {
                    "type": "event_msg",
                    "payload": {"type": "user_message", "message": self.quote},
                }
            ),
            encoding="utf-8",
        )
        self.decision = {
            "actor": "synthetic-user",
            "kind": "select",
            "user_text": self.quote,
            "selected": [{"candidate_id": "candidate-1", "candidate_version": 1}],
            "conditions": ["16 weeks"],
            "unresolved": [],
            "rationale": "Record the synthetic user's stated choice.",
            "scope_or_resource_change": False,
        }

    def invoke(self, *, action_id="choose-1", head=None):
        f = self.fixture
        return record_interaction(
            f.workflow,
            self.delivery,
            self.manifest["manifest_sha256"],
            self.decision,
            self.message,
            0,
            action_id,
            f.root / action_id,
            head or f.state["head_sha256"],
        )

    def test_selected_version_and_native_text_bound_without_execution_grant(self):
        result = self.invoke()
        record = result["record"]
        self.assertEqual(record["human_selection"], "recorded")
        self.assertEqual(record["decision"]["user_text"], self.quote)
        self.assertEqual(
            record["handoff"]["selected_options"][0]["candidate"]["version"], 1
        )
        self.assertFalse(record["execution_authorized"])
        self.assertFalse(record["identity_authenticated"])
        handoff = record["handoff"]
        self.assertTrue(
            all(
                (
                    self.delivery / handoff["source_base_in_delivery"] / row["path"]
                ).is_file()
                for row in handoff["sources"]
            )
        )
        state = inspect_workflow(self.fixture.workflow, result["head_sha256"])
        before = len(state["events"])
        reused = self.invoke(head=result["head_sha256"])
        self.assertTrue(reused["reuse"])
        self.assertEqual(reused["record"], record)
        self.assertEqual(len(inspect_workflow(self.fixture.workflow)["events"]), before)

    def test_clarification_invalidates_old_report_choice(self):
        self.decision.update(kind="clarify", selected=[])
        first = self.invoke(action_id="clarify-1")
        self.assertIsNone(first["record"]["handoff"])
        self.assertTrue(first["record"]["requires_new_report"])
        self.decision.update(
            kind="select",
            selected=[{"candidate_id": "candidate-1", "candidate_version": 1}],
        )
        with self.assertRaisesRegex(Stage2Error, "human-report-stale"):
            self.invoke(action_id="choose-after-clarify", head=first["head_sha256"])
        self.assertFalse((self.fixture.root / "choose-after-clarify").exists())

    def test_assistant_text_or_changed_quote_is_not_a_user_decision(self):
        self.message.write_text(
            json.dumps(
                {
                    "type": "response_item",
                    "payload": {
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "input_text", "text": self.quote}],
                    },
                }
            ),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(Stage2Error, "native-user-message-required"):
            self.invoke()
        self.message.write_text(
            json.dumps(
                {
                    "type": "event_msg",
                    "payload": {
                        "type": "user_message",
                        "message": "Please explain more.",
                    },
                }
            ),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(Stage2Error, "human-quote-mismatch"):
            self.invoke()
        self.assertEqual(
            inspect_workflow(self.fixture.workflow)["head_sha256"],
            self.fixture.state["head_sha256"],
        )

    def test_new_version_or_scope_change_requires_fresh_check(self):
        self.decision["selected"][0]["candidate_version"] = 2
        with self.assertRaisesRegex(Stage2Error, "not-current-recommendation"):
            self.invoke()
        self.decision["selected"][0]["candidate_version"] = 1
        self.decision["scope_or_resource_change"] = True
        with self.assertRaisesRegex(Stage2Error, "changed-scope-needs-recheck"):
            self.invoke()

    def test_duplicate_identity_with_different_decision_cannot_reuse(self):
        first = self.invoke()
        self.decision["conditions"].append("Changed condition")
        with self.assertRaisesRegex(Stage2Error, "input-conflict"):
            self.invoke(head=first["head_sha256"])

    def test_relabelled_old_delivery_cannot_bind_a_changed_current_packet(self):
        from stage2_workflow.delivery import inspect_delivery
        from stage2_workflow.interaction import _record

        f = self.fixture
        delivery = inspect_delivery(self.delivery, self.manifest["manifest_sha256"])
        state = copy.deepcopy(f.state)
        state["latest_snapshot"]["packet"]["candidates"][0]["question"] = (
            "New unreviewed question"
        )
        with self.assertRaisesRegex(Stage2Error, "current-packet-mismatch"):
            _record(state, delivery, self.decision, self.message.read_bytes(), 0)


if __name__ == "__main__":
    unittest.main()
