"""Offline raw-frame proof for bounded full stage prompts; no native/model I/O."""

import time
import unittest

from stage_model_fixtures import StageModelFixture
from research_workspace_native.project_model import _prompt


class StageModelPromptBoundTests(StageModelFixture):
    def test_topic_preflight_rejects_before_provider_reservation(self):
        with self.assertRaisesRegex(ValueError, "model-task-prompt-too-large"):
            _prompt(
                "suggest-topic",
                {"brief": {"original_description": "x" * 10001}},
                "2026-10-12",
            )
        self.assertEqual(self.calls, [])
        self.assertEqual(self.events, [])

    def test_complete_10k_boundary_remains_byte_exact(self):
        prompt = "文" * 3333 + "x"
        self.assertEqual(len(prompt.encode("utf8")), 10000)
        model = self.model(trusted_stage_unit=True)
        receipt = model.run("boundary-stage", prompt, time.monotonic() + 10)
        self.assertEqual(receipt["status"], "completed", receipt)
        self.verify(model, receipt, prompt)
        starts = [
            m
            for m in self.runtime.channel.messages()
            if m.get("method") == "turn/start"
        ]
        self.assertEqual(
            "".join(item["text"] for item in starts[0]["params"]["input"]), prompt
        )
        self.assertEqual(
            starts[0]["params"]["input"],
            [dict(type="text", text=prompt, text_elements=[])],
        )
        self.assertEqual(len(self.calls), 1)

    def test_trusted_stage_prompt_preserves_full_utf8_and_replays_without_resend(self):
        prompt = "Source evidence and extraction schema\n" + "文" * 3000
        model = self.model(trusted_stage_unit=True)
        receipt = model.run("full-stage", prompt, time.monotonic() + 10)
        self.assertEqual(receipt["status"], "completed", receipt)
        self.verify(model, receipt, prompt)
        spec = self.runtime.spec
        self.assertEqual(spec["kind"], "NativeStageUnitRuntimeSpec")
        self.assertEqual(spec["limits"]["max_text_bytes"], 10000)
        self.assertEqual(spec["limits"]["max_starts"], 1)
        starts = [
            m
            for m in self.runtime.channel.messages()
            if m.get("method") == "turn/start"
        ]
        self.assertEqual(
            "".join(item["text"] for item in starts[0]["params"]["input"]), prompt
        )
        self.assertTrue(
            all(
                0 < len(item["text"].encode("utf8")) <= 10000
                for item in starts[0]["params"]["input"]
            )
        )
        self.assertTrue(
            model.run("full-stage", prompt, time.monotonic() + 10)["replayed"]
        )
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(sum(e["phase"] == "reserve" for e in self.events), 1)

    def test_overflow_invalid_utf8_and_truthy_optin_reject_before_reservation(self):
        model = self.model(trusted_stage_unit=True)
        for prompt in (
            "x" * 10001,
            "文" * 3334,
            "文" * 10922 + "xx",
            "\ud800",
            "\x00" * 12000,
        ):
            with (
                self.subTest(bytes=len(prompt)),
                self.assertRaises((ValueError, UnicodeError)),
            ):
                model.run("overflow", prompt, time.monotonic() + 10)
        self.assertEqual(self.calls, [])
        self.assertEqual(self.events, [])
        with self.assertRaises(ValueError):
            self.model(trusted_stage_unit=1)

    def test_ordinary_model_prompt_rejects_over_complete_10k_limit(self):
        model = self.model()
        with self.assertRaises(ValueError):
            model.run("ordinary-overflow", "x" * 10001, time.monotonic() + 10)
        self.assertEqual(self.calls, [])
        self.assertEqual(self.events, [])

    def test_admitted_ascii_payload_mutation_keeps_one_bound_start(self):
        prompt = "xY7!?" * 2000
        model = self.model(trusted_stage_unit=True)
        receipt = model.run("fragmented-ascii", prompt, time.monotonic() + 10)
        self.assertEqual(receipt["status"], "completed", receipt)
        self.verify(model, receipt, prompt)
        starts = [
            m
            for m in self.runtime.channel.messages()
            if m.get("method") == "turn/start"
        ]
        self.assertEqual(len(starts), 1)
        inputs = starts[0]["params"]["input"]
        self.assertEqual("".join(item["text"] for item in inputs), prompt)
        self.assertEqual(inputs, [dict(type="text", text=prompt, text_elements=[])])
        altered = [dict(item) for item in inputs]
        altered[0]["text"] = "z" + altered[0]["text"][1:]
        with self.assertRaisesRegex(ValueError, "unit prompt binding differs"):
            model._gate(
                {"prompt": prompt},
                time.monotonic() + 10,
                "action",
                {
                    "action": {
                        "method": "turn/start",
                        "payload": {**starts[0]["params"], "input": altered},
                    }
                },
            )
        self.assertEqual(sum(event["phase"] == "reserve" for event in self.events), 1)
        self.assertTrue(
            model.run("fragmented-ascii", prompt, time.monotonic() + 10)["replayed"]
        )
        self.assertEqual(len(self.calls), 1)


if __name__ == "__main__":
    unittest.main()
