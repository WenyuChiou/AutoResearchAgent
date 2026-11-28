"""Replan-from-revision Core inputs; offline, no model or process dispatch.

The golden hashes below were computed with the planner and prompt code at
8a83c0eb (before revision input existed): extract that tree with
``git archive 8a83c0eb plugins/auto-research-agent/cli/stage3_plan`` and run the
same ``build_prompt`` / ``_planning_request`` calls. Without a revision input the
current code must reproduce those bytes exactly.
"""

import copy
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest

PLUGIN = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(PLUGIN / "cli"), str(PLUGIN / "tests")]
import test_stage3_jobs as base  # noqa: E402
from stage3_plan.contracts import Stage3Error, canonical_bytes, digest  # noqa: E402
from stage3_plan.planner import (  # noqa: E402
    _planning_request,
    draft_synthetic_plan,
    inspect_saved_plan,
)
from stage3_plan.prompts import (  # noqa: E402
    ADMITTED_ONLY,
    ADMITTED_WITH_REVISION,
    MAX_CONTEXT_BYTES,
    REVISION_INSTRUCTION,
    RevisionContextTooLarge,
    build_prompt,
    check_revision_input,
)
from stage3_plan.storage import read_json  # noqa: E402
from stage3_plan_fixtures import make_intake, make_plan  # noqa: E402

GOLDEN = {
    "1.0.0": (
        "7b090903a81f796471e6f5ea924c123815053eb53106fac1e5930b19e015997e",
        "fb35f376b17654faf873f6275e96b79696d6f444116818d3e85b444b71377d14",
    ),
    "1.1.0": (
        "d0a9c0b197a89dd39fa403479a23ca074de2562455912cf4424d14494a31eed8",
        "7291a590e80753d661d0e91f941ff4241a4fcd507cc8d62bc3e707869aa90b02",
    ),
    "1.2.0": (
        "2d25cb04e0d95b87857e518ff369ce686cd8e9355e44c7f2db4c06c4cd964b38",
        "1bf8e27450cfb4227590ece7a1f44825980247408117768b56766d0526454a6e",
    ),
}
CONFIG = {"model": "fixture-model", "reasoning": "medium"}
CONTEXT = {"kind": "fixed-callback", "timeout_seconds": 5}


def golden_intake():
    value = make_intake(make_plan("theory", question_count=2, shared_path=True))
    value["selection_conditions"] = ["Keep the stated limitation visible."]
    value["unresolved"] = ["Material access unknown."]
    return value


def revision(plan, text="Researcher comment: keep access unknown.", **changes):
    value = {
        "plan_revision_receipt_sha256": "1" * 64,
        "decision_receipt_sha256": "2" * 64,
        "parent_plan_manifest_sha256": "3" * 64,
        "parent_request_sha256": "4" * 64,
        "plan": plan,
        "changes": [
            {
                "question_ref": "q1",
                "field": "minimum_deliverable",
                "model_value": "Model text before the edit.",
                "researcher_value": "CHANGE-MARKER researcher text.",
            }
        ],
        "comments": [{"question_ref": None, "text": text}],
        **changes,
    }
    value.pop("sha256", None)
    value["sha256"] = digest(value)
    return value


def request(intake, schema, revision_input=None):
    return _planning_request(
        intake,
        CONFIG,
        CONTEXT,
        "golden-plan",
        1,
        schema,
        "synthetic-test",
        **({} if revision_input is None else {"revision_input": revision_input}),
    )


class PromptAndRequestBytesTests(unittest.TestCase):
    def test_without_revision_prompt_and_request_match_pre_change_bytes(self):
        for schema, (prompt_sha, request_sha) in GOLDEN.items():
            with self.subTest(schema=schema):
                for prompt in (
                    build_prompt(
                        golden_intake(),
                        plan_id="golden-plan",
                        version=1,
                        schema_version=schema,
                    ),
                    build_prompt(
                        golden_intake(),
                        plan_id="golden-plan",
                        version=1,
                        schema_version=schema,
                        revision_input=None,
                    ),
                ):
                    self.assertEqual(
                        hashlib.sha256(prompt.encode()).hexdigest(), prompt_sha
                    )
                value, prompt, _, _ = request(golden_intake(), schema)
                self.assertNotIn("revision_input", value)
                stable = {
                    k: v
                    for k, v in value.items()
                    if k not in ("producer_sha256", "runtime")
                }
                self.assertEqual(
                    hashlib.sha256(canonical_bytes(stable)).hexdigest(), request_sha
                )
                self.assertEqual(
                    value["prompt_sha256"], hashlib.sha256(prompt.encode()).hexdigest()
                )

    def test_revision_is_declared_as_researcher_input_and_bound_in_request(self):
        draft = {"question_plans": [{"minimum_deliverable": "DRAFT-MARKER-42"}]}
        value_in = revision(draft, text="COMMENT-MARKER-7")
        value, prompt, _, _ = request(golden_intake(), "1.1.0", value_in)
        self.assertEqual(value["revision_input"], value_in)
        self.assertIn(REVISION_INSTRUCTION, prompt)
        self.assertIn("只有 changes 和 comments 来自研究者", prompt)
        # The source rule is reworded only in the revision branch.
        self.assertIn(ADMITTED_WITH_REVISION, prompt)
        self.assertNotIn(ADMITTED_ONLY, prompt)
        head, tail = prompt.split("\nRESEARCHER_REVISION\n")
        self.assertIn("ADMITTED_CONTEXT", head)
        self.assertIn("DRAFT-MARKER-42", tail)
        self.assertIn("COMMENT-MARKER-7", tail)
        self.assertIn("CHANGE-MARKER researcher text.", tail)
        self.assertIn("Model text before the edit.", tail)
        # The declaration sits with the instructions, before the source context.
        self.assertLess(
            prompt.index(REVISION_INSTRUCTION), prompt.index("ADMITTED_CONTEXT")
        )
        self.assertEqual(
            value["prompt_sha256"], hashlib.sha256(prompt.encode()).hexdigest()
        )
        plain, plain_prompt, _, _ = request(golden_intake(), "1.1.0")
        self.assertNotEqual(plain["prompt_sha256"], value["prompt_sha256"])
        self.assertIn(ADMITTED_ONLY, plain_prompt)
        self.assertTrue(
            prompt.replace(ADMITTED_WITH_REVISION, ADMITTED_ONLY).startswith(
                plain_prompt.split("End of instructions.")[0]
            )
        )

    def test_oversized_revision_is_refused_not_trimmed(self):
        big = revision({"text": "x" * MAX_CONTEXT_BYTES})
        with self.assertRaises(RevisionContextTooLarge) as error:
            build_prompt(golden_intake(), plan_id="p", version=1, revision_input=big)
        self.assertIn(str(MAX_CONTEXT_BYTES), str(error.exception))
        self.assertIsInstance(error.exception, Stage3Error)

    def test_revision_shape_and_digest_are_checked(self):
        good = revision({"a": 1})
        check_revision_input(copy.deepcopy(good))
        bad_digest = dict(good, comments=[{"question_ref": None, "text": "edited"}])
        extra = dict(good, execution_authorized=True)
        bad_comment = revision({"a": 1}, comments=[{"text": "no question field"}])
        bad_hash = revision({"a": 1}, decision_receipt_sha256="not-a-hash")
        bad_change = revision({"a": 1}, changes=[{"question_ref": "q1"}])
        bad_value = revision(
            {"a": 1},
            changes=[
                {
                    "question_ref": "q1",
                    "field": "minimum_deliverable",
                    "model_value": None,
                    "researcher_value": "x",
                }
            ],
        )
        no_changes = {k: v for k, v in good.items() if k != "changes"}
        for value in (
            bad_digest,
            extra,
            bad_comment,
            bad_hash,
            bad_change,
            bad_value,
            no_changes,
            None,
            [],
        ):
            with self.subTest(value=value), self.assertRaises(Stage3Error):
                check_revision_input(value)


class SyntheticReplayTests(unittest.TestCase):
    def test_saved_revision_plan_replays_only_with_the_same_revision(self):
        plan = make_plan()
        intake = make_intake(plan)
        draft = revision({"draft": "kept"})
        calls = []

        def callback(**kwargs):
            calls.append(kwargs["prompt"])
            return {
                "raw_response": canonical_bytes(plan),
                "provenance": {"kind": "synthetic"},
            }

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve() / "plan"
            arguments = dict(configuration=CONFIG, plan_id=plan["plan_id"])
            saved = draft_synthetic_plan(
                intake, root, callback, revision_input=draft, **arguments
            )
            pin = saved["manifest"]["manifest_sha256"]
            self.assertEqual(read_json(root / "request.json")["revision_input"], draft)
            replay = draft_synthetic_plan(
                intake,
                root,
                callback,
                revision_input=draft,
                resume_manifest_sha256=pin,
                **arguments,
            )
            self.assertEqual(replay["resume_action"], "verified-replay-no-generation")
            for changed in (None, revision({"draft": "changed"})):
                with self.subTest(changed=changed), self.assertRaises(Stage3Error):
                    draft_synthetic_plan(
                        intake,
                        root,
                        callback,
                        revision_input=changed,
                        resume_manifest_sha256=pin,
                        **arguments,
                    )
        self.assertEqual(len(calls), 1)
        self.assertIn('"draft":"kept"', calls[0])


class ReplanJobTests(unittest.TestCase):
    setUp = base.PlanningJobTests.setUp
    tearDown = base.PlanningJobTests.tearDown
    workflow = base.PlanningJobTests.workflow
    prepare = base.PlanningJobTests.prepare
    execute = base.PlanningJobTests.execute

    def payload(self, key):
        return self.journal.snapshot("project-a")["intents"][self.jobs._key(key)][
            "payload"
        ]

    def test_only_revision_jobs_use_payload_1_1_0(self):
        self.prepare("plain")
        plain = self.payload("plain")
        self.assertEqual(plain["schema_version"], "1.0.0")
        self.assertNotIn("revision_input", plain)
        draft = revision({"draft": "kept"})
        self.prepare("revised", revision_input=draft)
        revised = self.payload("revised")
        self.assertEqual(revised["schema_version"], "1.1.0")
        self.assertEqual(revised["revision_input"], draft)
        self.assertEqual(
            {
                k: v
                for k, v in plain.items()
                if k not in ("key", "output", "schema_version")
            },
            {
                k: v
                for k, v in revised.items()
                if k not in ("key", "output", "schema_version", "revision_input")
            },
        )

    def test_revision_job_runs_once_and_every_read_recomputes_it(self):
        draft = revision({"draft": "RUN-MARKER"})
        prepared = self.prepare("revised", revision_input=draft)
        self.callback.assert_not_called()
        saved = self.execute(prepared, key="revised")
        self.assertEqual(saved["status"], "completed", saved)
        self.assertEqual(self.callback.call_count, 1)
        self.assertIn("RUN-MARKER", self.callback.call_args.kwargs["prompt"])
        self.assertIn(REVISION_INSTRUCTION, self.callback.call_args.kwargs["prompt"])
        pin = saved["result"]["plan"]["manifest_sha256"]
        again = self.jobs.inspect(
            "revised",
            expected_request_sha256=prepared["request_sha256"],
            current_checkpoint=self.checkpoint,
        )
        self.assertEqual(again["result"], saved["result"])
        read = self.jobs.inspect_saved(
            "revised",
            expected_request_sha256=prepared["request_sha256"],
            current_checkpoint=self.checkpoint,
            expected_plan_manifest_sha256=pin,
        )
        self.assertEqual(read["result"], saved["result"])
        self.assertEqual(
            self.execute(prepared, key="revised")["result"], saved["result"]
        )
        self.assertEqual(self.callback.call_count, 1)

        payload = self.payload("revised")
        forged = copy.deepcopy(payload)
        forged["revision_input"] = revision({"draft": "FORGED"})
        with self.assertRaises(Stage3Error):
            self.jobs._saved(forged, pin)
        with self.assertRaises(Stage3Error):
            inspect_saved_plan(forged, pin)
        edited = copy.deepcopy(payload)
        changes = edited["revision_input"]["changes"]
        changes[0]["researcher_value"] = "EDITED"
        edited["revision_input"] = revision(
            edited["revision_input"]["plan"], changes=changes
        )
        with self.assertRaises(Stage3Error):
            self.jobs._saved(edited, pin)
        with self.assertRaises(Stage3Error):
            inspect_saved_plan(edited, pin)
        dropped = {k: v for k, v in payload.items() if k != "revision_input"}
        with self.assertRaises(Stage3Error):
            inspect_saved_plan(dropped, pin)
        self.assertEqual(self.callback.call_count, 1)

    def test_oversized_revision_leaves_no_job(self):
        before = self.journal.snapshot("project-a")
        with self.assertRaises(RevisionContextTooLarge):
            self.prepare(
                "too-large",
                revision_input=revision({"text": "x" * MAX_CONTEXT_BYTES}),
            )
        self.assertEqual(self.journal.snapshot("project-a"), before)
        self.callback.assert_not_called()


if __name__ == "__main__":
    unittest.main()
