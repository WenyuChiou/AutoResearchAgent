"""Offline raw-frame proof for bounded full stage prompts; no native/model I/O."""

import time
import unittest

from stage_model_fixtures import StageModelFixture


class StageModelPromptBoundTests(StageModelFixture):
    def test_trusted_32k_boundary_remains_byte_exact(self):
        prompt = "文" * 10922 + "xx"
        self.assertEqual(len(prompt.encode("utf8")), 32768)
        model = self.model(trusted_stage_unit=True)
        receipt = model.run("boundary-stage", prompt, time.monotonic() + 10)
        self.assertEqual(receipt["status"], "completed", receipt)
        self.verify(model, receipt, prompt)
        starts = [
            m
            for m in self.runtime.channel.messages()
            if m.get("method") == "turn/start"
        ]
        self.assertEqual(starts[0]["params"]["input"][0]["text"], prompt)
        self.assertEqual(len(self.calls), 1)

    def test_trusted_stage_prompt_preserves_full_utf8_and_replays_without_resend(self):
        prompt = "Source evidence and extraction schema\n" + "文" * 7180
        self.assertGreater(len(prompt.encode("utf8")), 16384)
        model = self.model(trusted_stage_unit=True)
        receipt = model.run("full-stage", prompt, time.monotonic() + 10)
        self.assertEqual(receipt["status"], "completed", receipt)
        self.verify(model, receipt, prompt)
        spec = self.runtime.spec
        self.assertEqual(spec["kind"], "NativeStageUnitRuntimeSpec")
        self.assertEqual(spec["limits"]["max_text_bytes"], 32768)
        self.assertEqual(spec["limits"]["max_starts"], 1)
        starts = [
            m
            for m in self.runtime.channel.messages()
            if m.get("method") == "turn/start"
        ]
        self.assertEqual(starts[0]["params"]["input"][0]["text"], prompt)
        self.assertTrue(
            model.run("full-stage", prompt, time.monotonic() + 10)["replayed"]
        )
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(sum(e["phase"] == "reserve" for e in self.events), 1)

    def test_overflow_invalid_utf8_and_truthy_optin_reject_before_reservation(self):
        model = self.model(trusted_stage_unit=True)
        for prompt in ("x" * 32769, "文" * 10923, "\ud800", "\x00" * 12000):
            with (
                self.subTest(bytes=len(prompt)),
                self.assertRaises((ValueError, UnicodeError)),
            ):
                model.run("overflow", prompt, time.monotonic() + 10)
        self.assertEqual(self.calls, [])
        self.assertEqual(self.events, [])
        with self.assertRaises(ValueError):
            self.model(trusted_stage_unit=1)

    def test_ordinary_model_prompt_keeps_16k_limit(self):
        model = self.model()
        with self.assertRaises(ValueError):
            model.run("ordinary-overflow", "x" * 16385, time.monotonic() + 10)
        self.assertEqual(self.calls, [])
        self.assertEqual(self.events, [])


if __name__ == "__main__":
    unittest.main()
