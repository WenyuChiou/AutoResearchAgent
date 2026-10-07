# ruff: noqa: E402 -- load the repository CLI and sibling fixture directly.
"""Focused tests for the native supplemental context-quality runner."""

import copy
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

PLUGIN = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(PLUGIN / "cli"), str(Path(__file__).resolve().parent)]

from stage1_eval.common import EvaluationError
from stage1_eval.model_calls import call_model_v31
from stage2_common import Stage2Error
from stage2_live.context_quality_v3 import (
    MAX_PROMPT_CHARS,
    _code_binding,
    _restore_batch,
    run_context_quality_v3,
)
from test_stage2_source_context_quality import synthetic_context_fixture


POLICY = {"max_transient_transport_retries": 0}


def _fixture():
    dataset, reference = synthetic_context_fixture()
    refs = {row["case_id"]: row for row in reference["judgments"]}
    for case in dataset["cases"]:
        expected = refs[case["case_id"]]
        case["subject_record"]["text"] = (
            "The supplied evidence supports this assessment."
            if expected["score"] == 2
            else "The subject makes a central unsupported claim."
        )
    return dataset, reference


def _value(prompt, role):
    payload = json.loads(prompt.splitlines()[-1])
    judgments = []
    for case in payload["cases"]:
        supported = "supports" in case["subject_record"]["text"]
        judgments.append(
            {
                "case_id": case["case_id"],
                "status": "scored",
                "score": 2 if supported else 0,
                "evidence_ids": [case["facts"][0]["evidence_id"]],
                "reason": "The supplied fact supports this bounded judgment.",
                "major_error": not supported,
            }
        )
    return {"kind": "Stage2RubricQualityBatchV3", "role": role, "judgments": judgments}


class Adapter:
    def __init__(self, fail_role=None):
        self.calls = []
        self.fail_role = fail_role

    def __call__(
        self, prompt, schema_path, _output, label, *, semantic_validator, **_options
    ):
        role = label.split("-", 1)[0].upper()
        self.calls.append(
            {
                "label": label,
                "prompt": prompt,
                "schema": json.loads(Path(schema_path).read_text(encoding="utf-8")),
            }
        )
        if role == self.fail_role:
            raise EvaluationError(f"{role} unavailable")
        value = _value(prompt, role)
        semantic_validator(copy.deepcopy(value))
        return value, {"execution_status": "injected", "label": label}


def _transcript(value):
    events = [
        {
            "type": "item.completed",
            "item": {"type": "agent_message", "text": json.dumps(value)},
        },
        {"type": "turn.completed"},
    ]
    return ("\n".join(json.dumps(row) for row in events) + "\n").encode()


class ContextQualityNativeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.homes = {role: self.root / f"home-{role.lower()}" for role in ("R1", "R2")}
        for path in self.homes.values():
            path.mkdir()
        self.codex = self.root / "codex"
        self.codex.write_bytes(b"synthetic executable")
        self.dataset, self.reference = _fixture()

    def invoke(self, adapter, output="out", **changes):
        options = {
            "dataset": self.dataset,
            "reference": self.reference,
            "codex": self.codex,
            "r1_home": self.homes["R1"],
            "r2_home": self.homes["R2"],
            "model": "test-model",
            "reasoning": "high",
            "execution_policy": POLICY,
            "output_dir": self.root / output,
            "call_adapter": adapter,
        }
        options.update(changes)
        return run_context_quality_v3(**options)

    def test_blind_bounded_calls_produce_24_judgments_without_readiness_claim(self):
        adapter = Adapter()
        result = self.invoke(adapter)
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["quality_report"]["designated_judgments"], 24)
        self.assertTrue(result["quality_report"]["passed"])
        self.assertEqual(result["evidence_class"], "injected-test-only")
        self.assertFalse(result["native_qa_pass"])
        self.assertFalse(result["formal_ready"])
        self.assertFalse(result["formal_quality_admission"])
        serialized = json.dumps(adapter.calls)
        for forbidden in ("polarity", "family", "positive", "negative"):
            self.assertNotIn(forbidden, serialized)
        for case in self.dataset["cases"]:
            self.assertNotIn(case["case_id"], serialized)
        self.assertTrue(
            all(len(row["prompt"]) <= MAX_PROMPT_CHARS for row in adapter.calls)
        )
        self.assertEqual(
            {row["label"].split("-", 1)[0] for row in adapter.calls}, {"r1", "r2"}
        )

    def test_alias_restoration_rejects_wrong_role_foreign_duplicate_and_evidence(self):
        adapter = Adapter()
        self.invoke(adapter)
        call = adapter.calls[0]
        payload = json.loads(call["prompt"].splitlines()[-1])
        cases = payload["cases"]
        original = self.dataset["cases"][: len(cases)]
        aliases = {
            case["case_id"]: {
                "case_id": source["case_id"],
                "evidence_ids": {
                    case["facts"][0]["evidence_id"]: source["facts"][0]["evidence_id"]
                },
            }
            for case, source in zip(cases, original, strict=True)
        }
        valid = _value(call["prompt"], "R1")
        mutations = []
        wrong_role = copy.deepcopy(valid)
        wrong_role["role"] = "R2"
        mutations.append((wrong_role, "role-or-shape"))
        foreign = copy.deepcopy(valid)
        foreign["judgments"][0]["case_id"] = "case-foreign"
        mutations.append((foreign, "case-alias"))
        duplicate = copy.deepcopy(valid)
        duplicate["judgments"][1]["case_id"] = duplicate["judgments"][0]["case_id"]
        mutations.append((duplicate, "case-alias"))
        evidence = copy.deepcopy(valid)
        evidence["judgments"][0]["evidence_ids"] = ["evidence-foreign"]
        mutations.append((evidence, "evidence-alias"))
        for value, message in mutations:
            with (
                self.subTest(message=message),
                self.assertRaisesRegex(Stage2Error, message),
            ):
                _restore_batch(value, "R1", cases, aliases, original)

    def test_failed_r2_preserves_completed_r1_without_fabricated_scores(self):
        result = self.invoke(Adapter(fail_role="R2"))
        self.assertEqual(result["status"], "incomplete")
        self.assertEqual(
            result["reviewer_status"], {"R1": "complete", "R2": "incomplete"}
        )
        self.assertEqual(len(result["roles"]["R1"]["judgments"]), 12)
        self.assertNotIn("R2", result["roles"])
        self.assertIsNone(result["quality_report"])
        self.assertTrue(result["failures"])
        self.assertTrue((self.root / "out/result.json").is_file())

    def _native_response(self, command, *, input, **_kwargs):
        prompt = input.decode()
        output = Path(command[command.index("-o") + 1])
        archive = next(
            path for path in output.parents if path.name.endswith(".model-call")
        )
        label = archive.name.removesuffix(".model-call")
        value = _value(prompt, label.split("-", 1)[0].upper())
        Path(command[command.index("-o") + 1]).write_text(
            json.dumps(value), encoding="utf-8"
        )
        return SimpleNamespace(returncode=0, stdout=_transcript(value), stderr=b"")

    def test_receipted_resume_reuses_units_and_rejects_tamper_or_changed_bindings(self):
        with mock.patch(
            "stage1_eval.model_calls._execute_bound_process",
            side_effect=self._native_response,
        ) as execute:
            first = self.invoke(call_model_v31)
        initial_calls = execute.call_count
        self.assertGreater(initial_calls, 0)
        with mock.patch("stage1_eval.model_calls._execute_bound_process") as replay:
            second = self.invoke(
                call_model_v31,
                resume=True,
                resume_receipt=first["replay_receipt"],
            )
        replay.assert_not_called()
        self.assertEqual(second["replay_receipt"], first["replay_receipt"])

        with self.assertRaisesRegex(EvaluationError, "external replay receipt"):
            self.invoke(
                call_model_v31,
                resume=True,
                resume_receipt={**first["replay_receipt"], "result_sha256": "0" * 64},
            )
        with self.assertRaisesRegex(EvaluationError, "artifact changed"):
            self.invoke(
                call_model_v31,
                resume=True,
                resume_receipt=first["replay_receipt"],
                model="changed-model",
            )
        with mock.patch(
            "stage2_live.context_quality_v3._code_binding", return_value="f" * 64
        ):
            with self.assertRaisesRegex(EvaluationError, "artifact changed"):
                self.invoke(
                    call_model_v31,
                    resume=True,
                    resume_receipt=first["replay_receipt"],
                )

        unit = self.root / "out/r1-01.unit.json"
        unit.write_bytes(unit.read_bytes() + b" ")
        with self.assertRaisesRegex(
            EvaluationError, "saved Stage 2 judge artifact changed"
        ):
            self.invoke(
                call_model_v31,
                resume=True,
                resume_receipt=first["replay_receipt"],
            )

    def test_evaluator_homes_must_not_overlap(self):
        nested = self.homes["R1"] / "nested"
        nested.mkdir()
        with self.assertRaisesRegex(EvaluationError, "must not overlap"):
            self.invoke(Adapter(), r2_home=nested)

    def test_shared_call_code_is_bound_before_resume(self):
        original = Path.read_bytes
        baseline = _code_binding()

        def changed(path):
            data = original(path)
            return data + b"# changed" if path.name == "judges.py" else data

        with mock.patch.object(Path, "read_bytes", changed):
            self.assertNotEqual(_code_binding(), baseline)

    def test_oversized_correction_is_rejected_before_dispatch(self):
        dispatched = []

        def invalid(prompt, _schema, _output, label, **_options):
            dispatched.append(label)
            value = _value(prompt, "R2" if label.startswith("r1") else "R1")
            value["judgments"][0]["reason"] = "x" * MAX_PROMPT_CHARS
            return value, {"execution_status": "injected"}

        result = self.invoke(invalid)
        self.assertEqual(result["status"], "incomplete")
        self.assertTrue(dispatched)
        self.assertFalse(any(label.endswith("-correction") for label in dispatched))
        self.assertTrue(
            all(
                "dispatch-exceeds-prompt-bound" in row["message"]
                for row in result["failures"]
            )
        )

    def test_cli_rejects_nonexternal_receipt_before_model_call(self):
        from stage2_live.__main__ import main

        args = ["calibrate-context-v3"]
        for name, value in {
            "dataset": "unused",
            "reference": "unused",
            "codex": str(self.codex),
            "r1-home": str(self.homes["R1"]),
            "r2-home": str(self.homes["R2"]),
            "model": "test-model",
            "reasoning": "high",
            "policy": "unused",
            "output": str(self.root / "out"),
            "replay-receipt-output": str(self.root / "out" / "receipt.json"),
        }.items():
            args.extend(["--" + name, value])
        with mock.patch("stage2_live.context_quality_v3.run_context_quality_v3") as run:
            self.assertEqual(main(args), 2)
            run.assert_not_called()
        args[args.index("--output") + 1] = str(self.root / "new-results" / "run")
        args[args.index("--replay-receipt-output") + 1] = str(self.root / "new-results")
        with mock.patch("stage2_live.context_quality_v3.run_context_quality_v3") as run:
            self.assertEqual(main(args), 2)
            run.assert_not_called()
        self.assertFalse((self.root / "new-results").exists())


if __name__ == "__main__":
    unittest.main()
