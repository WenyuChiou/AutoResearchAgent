"""Real SQLite/bootstrap with injected channel only; no native/model calls."""

import time
import unittest
from stage_model_fixtures import StageModelFixture


class StageModelTests(StageModelFixture):
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
