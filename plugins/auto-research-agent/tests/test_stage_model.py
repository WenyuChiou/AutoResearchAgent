"""Real SQLite/bootstrap with injected channel only; no native/model calls."""

import time
import unittest
from unittest.mock import patch
from research_workspace_native.project_model_factory import _CheckedSource
from research_workspace_native.process_deadline import SessionLeaseExpired
from stage_model_fixtures import StageModelFixture


class StageModelTests(StageModelFixture):
    def test_source_check_batches_origins_and_still_refuses_changed_input_bytes(self):
        model = self.model()
        calls = []
        model.checked["source"] = _CheckedSource(lambda: calls.append(1))
        model._check_source()
        self.assertEqual(len(calls), 2)
        model.checked["index_path"].write_bytes(b"changed input")
        with self.assertRaises(ValueError):
            model._check_source()
        self.assertEqual(len(calls), 4)
        self.assertEqual(self.calls, [])

    def test_expiry_during_source_check_refuses_admission_before_any_io(self):
        model = self.model()
        self.events.clear()
        with patch(
            "research_workspace_native.stage_model.time.monotonic", side_effect=[0, 2]
        ):
            with self.assertRaises(SessionLeaseExpired):
                model._gate({}, 1, "reserve", {})
        self.assertEqual(self.events, [])
        self.assertEqual(self.calls, [])

    def test_complete_raw_frame_terminal_reconstruction_and_no_resend(self):
        model = self.model()
        receipt = model.run(
            "unit-1", "interpret the controlled sources", time.monotonic() + 10
        )
        self.assertEqual(receipt["status"], "completed", receipt)
        result = self.verify(model, receipt)
        self.assertEqual(
            result["final_text"], "Synthetic controlled source interpretation."
        )
        self.assertEqual(
            (result["thread_id"], result["turn_id"], result["usage"]),
            ("fake-thread", "fake-turn", None),
        )
        self.assertFalse(result["authenticated_process"])
        self.assertTrue(
            model.run(
                "unit-1", "interpret the controlled sources", time.monotonic() + 10
            )["replayed"]
        )
        reopened = self.model()
        self.assertTrue(
            reopened.run(
                "unit-1", "interpret the controlled sources", time.monotonic() + 10
            )["replayed"]
        )
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(sum(e["phase"] == "reserve" for e in self.events), 1)
        with self.assertRaises(ValueError):
            model.run("unit-1", "changed payload", time.monotonic() + 10)


if __name__ == "__main__":
    unittest.main()
