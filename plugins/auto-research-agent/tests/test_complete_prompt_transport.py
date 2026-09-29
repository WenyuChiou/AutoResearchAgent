"""Lossless transport and staged admission; synthetic evidence only."""

import unittest
from pathlib import Path
from unittest.mock import patch

import test_complete_judging as fixtures
from stage1_eval import complete_judging as complete
from stage1_eval import pipeline_v31
from stage1_eval.common import EvaluationError, canonical, read_json
from stage1_eval.prompt_transport import decode, encode, render


class CompletePromptTransportTests(unittest.TestCase):
    def test_lossless_json_types_unicode_text_and_references(self):
        original = {
            "duplicate": [{"text": "Unicode 中\r\nTAIL CONTRARY", "value": None}] * 3,
            "types": [True, 1, 1.0, False, 0, 0.0, [], {}, "", (1, 2)],
        }
        encoded = encode(original)
        self.assertEqual(canonical(decode(encoded)), canonical(original))
        self.assertIn("TAIL CONTRARY", render("", original))
        self.assertEqual(
            sum(
                node == ["value", "Unicode 中\r\nTAIL CONTRARY"]
                for node in encoded["nodes"]
            ),
            1,
        )

    def test_omission_alias_collision_and_reference_tampering(self):
        original = {
            "work": "work-18",
            "unknown": "source-unavailable",
            "contrary": ["TAIL CONTRARY", "TAIL CONTRARY"],
        }
        for change in ("omit", "alias", "duplicate-key", "forward", "unused", "tamper"):
            with self.subTest(change=change):
                encoded = encode(original)
                if change == "omit":
                    encoded["nodes"][-1].pop()
                elif change == "alias":
                    encoded["nodes"][-1][-1] = True
                elif change == "duplicate-key":
                    encoded["keys"][0][1] = encoded["keys"][0][0]
                elif change == "forward":
                    encoded["nodes"][-1][-1] = encoded["root"]
                elif change == "unused":
                    encoded["keys"].append(["unused"])
                else:
                    encoded["nodes"][0][1] = "MISSING CONTRARY"
                with self.assertRaises(EvaluationError):
                    decode(encoded)
        with self.assertRaises(EvaluationError):
            render("", {"invalid": float("nan")})

    def test_rehashed_transport_cannot_replace_the_original_logical_input(self):
        original = {"contrary": "tail finding", "unknown": "source-unavailable"}
        changed = {"contrary": "", "unknown": "source-unavailable"}
        valid_but_wrong = encode(changed)
        original_encode = encode

        def substitute(value):
            return valid_but_wrong if value == original else original_encode(value)

        with patch("stage1_eval.prompt_transport.encode", side_effect=substitute):
            with self.assertRaisesRegex(EvaluationError, "lost input"):
                render("", original)

    def fixture(self, count):
        fixture = fixtures.CompleteJudgingTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.representative_audits(work_count=count)
        return fixture

    def test_twelve_to_eighteen_work_full_role_roundtrip_and_replay(self):
        for count in (12, 15, 18):
            with self.subTest(work_count=count):
                fixture = self.fixture(count)
                with patch(
                    "stage1_eval.model_calls.subprocess.run",
                    side_effect=fixture.respond,
                ):
                    result = fixture.invoke()
                self.assertEqual(
                    len(result["selected"]["content"]["core_assessments"]), count
                )
                self.assertEqual(len(result["selected"]["content"]["criteria"]), 7)
                for role in ("r1", "r2", "adj"):
                    for suffix in ("", "-review", "-criteria"):
                        receipt = read_json(
                            fixture.root
                            / f"complete/content/content-{role}-preflight{suffix}.json"
                        )
                        self.assertEqual(receipt["sizing"], "exact-validated-inputs")
                        self.assertFalse(receipt["role_complete"])
                        self.assertFalse(receipt["score_awarded"])
                        self.assertEqual(receipt["status"], "passed")
                with patch("stage1_eval.model_calls.subprocess.run") as calls:
                    self.assertEqual(fixture.invoke(replay_only=True), result)
                calls.assert_not_called()

    def test_late_stage_oversize_keeps_core_archives_without_final_score(self):
        fixture = self.fixture(18)
        prepare = complete._prepare_call

        def larger_review(*args, **kwargs):
            prepared = prepare(*args, **kwargs)
            if args[2] == "review":
                prepared["prompt_bytes"] = complete.MAX_COMPLETE_PROMPT_BYTES + 1
            return prepared

        with (
            patch.object(complete, "_prepare_call", side_effect=larger_review),
            patch(
                "stage1_eval.model_calls.subprocess.run", side_effect=fixture.respond
            ) as calls,
        ):
            with self.assertRaisesRegex(EvaluationError, "no evidence was omitted"):
                fixture.invoke()
        self.assertEqual(calls.call_count, 5)
        root = fixture.root / "complete"
        self.assertEqual(
            len(list((root / "content/model-logs").glob("*.model-call"))), 5
        )
        receipt = read_json(root / "content/content-r1-preflight-review.json")
        self.assertEqual(receipt["status"], "failed")
        self.assertFalse(receipt["score_awarded"])
        self.assertFalse((root / "result.json").exists())

    def test_execution_policy_and_bundle_bind_transport_and_limits(self):
        policy = pipeline_v31.execution_policy()
        self.assertEqual(
            policy["complete_judging"]["prompt_byte_limit"],
            complete.MAX_COMPLETE_PROMPT_BYTES,
        )
        self.assertEqual(
            policy["complete_judging"]["execution_version"],
            complete.COMPLETE_EXECUTION_VERSION,
        )
        original_read = Path.read_bytes
        before = pipeline_v31.bundle_sha_v31()

        def changed(path):
            raw = original_read(path)
            return (
                raw + b"\n# synthetic binding mutation\n"
                if path.name == "prompt_transport.py"
                else raw
            )

        with patch.object(Path, "read_bytes", changed):
            self.assertNotEqual(pipeline_v31.bundle_sha_v31(), before)


if __name__ == "__main__":
    unittest.main()
