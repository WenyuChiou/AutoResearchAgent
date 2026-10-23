# ruff: noqa: E402 -- use the repository CLI without installing a package.
"""Action recovery must preserve operation identity without dispatching a model."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent / "cli"), str(HERE)]

from stage2_common import Stage2Error
from stage2_fixture_helpers import write_stage2_fixture
from stage2_live.controller import _execute_unit
from stage2_workflow import initialize_workflow, inspect_workflow
from stage2_workflow.store import finish_action, start_action


class Stage2ActionReplayTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        source_root = self.root / "sources"
        packet = write_stage2_fixture(source_root, candidate_count=1)
        packet_path = self.root / "packet.json"
        packet_path.write_text(json.dumps(packet), encoding="utf-8")
        self.run = self.root / "workflow"
        initialize_workflow(
            packet_path,
            source_root,
            self.run,
            {"model": "synthetic-model", "reasoning": "medium"},
            {"path": "synthetic-policy.json", "sha256": "a" * 64},
        )
        self.snapshot = inspect_workflow(self.run)["latest_snapshot"]["event"][
            "payload"
        ]["snapshot_sha256"]
        self.controller = self.root / "controller"
        (self.controller / "results").mkdir(parents=True)
        self.calls = 0

    def invoke(self):
        self.calls += 1
        return {"kind": "synthetic-original-result", "cost": None}

    def execute(self, action_id="unit-one", kind="original-kind"):
        return _execute_unit(
            self.run,
            self.controller,
            action_id,
            kind,
            {"input": "same"},
            {"model": "synthetic-model"},
            self.snapshot,
            self.invoke,
        )

    def test_completed_action_cannot_replay_as_another_operation(self):
        original = self.execute()
        before = inspect_workflow(self.run)
        result_before = before["actions"]["unit-one"]["result"]
        summary_before = (self.controller / "results/unit-one.json").read_bytes()
        with self.assertRaisesRegex(
            Stage2Error, "controller-action-binding-changed: unit-one"
        ):
            self.execute(kind="different-kind")
        after = inspect_workflow(self.run)
        self.assertEqual(original["state"], "complete")
        self.assertEqual(self.calls, 1)
        self.assertEqual(after["head_sha256"], before["head_sha256"])
        self.assertEqual(after["actions"]["unit-one"]["result"], result_before)
        self.assertEqual(
            (self.controller / "results/unit-one.json").read_bytes(), summary_before
        )

    def test_identical_completed_action_replays_without_new_invocation(self):
        original = self.execute()
        before = inspect_workflow(self.run)["head_sha256"]
        repeated = self.execute()
        self.assertEqual(
            repeated,
            {
                "state": "complete",
                "action_id": "unit-one",
                "replayed": True,
                "value": original["value"],
            },
        )
        self.assertEqual(self.calls, 1)
        self.assertEqual(inspect_workflow(self.run)["head_sha256"], before)

    def test_changed_operation_is_rejected_before_interrupted_or_failed_recovery(self):
        for terminal in (False, True):
            with self.subTest(terminal_failed=terminal):
                action_id = "failed-unit" if terminal else "interrupted-unit"
                state = inspect_workflow(self.run)
                started = start_action(
                    self.run,
                    action_id,
                    "original-kind",
                    {"input": "same"},
                    {"model": "synthetic-model"},
                    state["head_sha256"],
                )
                if terminal:
                    finish_action(
                        self.run,
                        action_id,
                        "failed",
                        {},
                        None,
                        "synthetic preserved failure",
                        started["event"]["event_sha256"],
                    )
                before = inspect_workflow(self.run)
                with self.assertRaisesRegex(
                    Stage2Error, "controller-action-binding-changed"
                ):
                    self.execute(action_id, "different-kind")
                same = self.execute(action_id)
                self.assertEqual(same["state"], "needs-recovery")
                self.assertEqual(
                    same.get("terminal_status"), "failed" if terminal else None
                )
                self.assertEqual(
                    inspect_workflow(self.run)["head_sha256"], before["head_sha256"]
                )
                self.assertEqual(
                    inspect_workflow(self.run)["actions"][action_id],
                    before["actions"][action_id],
                )
        self.assertEqual(self.calls, 0)


if __name__ == "__main__":
    unittest.main()
