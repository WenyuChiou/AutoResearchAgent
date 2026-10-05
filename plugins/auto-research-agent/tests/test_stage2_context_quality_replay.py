# ruff: noqa: E402 -- load repository CLI and sibling fixtures directly.
"""Synthetic mechanics for read-only supplemental context-QA replay."""

import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

PLUGIN = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(PLUGIN / "cli"), str(Path(__file__).resolve().parent)]

from stage2_common import Stage2Error
from stage2_live.context_quality_replay import verify_context_quality_v3
from stage2_live.context_quality_v3 import run_context_quality_v3
from stage2_live.native import codex_runtime_sha
from test_stage2_source_context_quality import synthetic_context_fixture


POLICY = {"max_transient_transport_retries": 0}


def _fixture():
    dataset, reference = synthetic_context_fixture()
    refs = {row["case_id"]: row for row in reference["judgments"]}
    for case in dataset["cases"]:
        case["subject_record"]["text"] = (
            "The supplied evidence supports this assessment."
            if refs[case["case_id"]]["score"] == 2
            else "The subject makes a central unsupported claim."
        )
    return dataset, reference


def _value(prompt, role, mutation=None):
    payload = next(
        json.loads(line) for line in prompt.splitlines() if line.startswith('{"cases":')
    )
    judgments = []
    for case in payload["cases"]:
        supported = "supports" in case["subject_record"]["text"]
        judgments.append(
            {
                "case_id": case["case_id"],
                "status": "scored",
                "score": 2 if supported else 0,
                "evidence_ids": [case["facts"][0]["evidence_id"]],
                "reason": "Synthetic mechanics-only reviewer explanation.",
                "major_error": not supported,
            }
        )
    value = {"kind": "Stage2RubricQualityBatchV3", "role": role, "judgments": judgments}
    if mutation is not None:
        mutation(value)
    return value


def _transcript(value):
    events = [
        {
            "type": "item.completed",
            "item": {"type": "agent_message", "text": json.dumps(value)},
        },
        {"type": "turn.completed"},
    ]
    return ("\n".join(json.dumps(row) for row in events) + "\n").encode()


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class ContextQualityReplayTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.homes = {role: self.base / f"home-{role.lower()}" for role in ("R1", "R2")}
        for path in self.homes.values():
            path.mkdir()
        self.codex = self.base / "codex"
        self.codex.write_bytes(b"synthetic executable; never invoked")
        self.dataset, self.reference = _fixture()
        self.config = {
            "codex": str(self.codex),
            "runtime_sha256": codex_runtime_sha(self.codex),
            "model": "synthetic-test-model",
            "reasoning": "high",
            "homes": {role: str(path) for role, path in self.homes.items()},
            "policy": POLICY,
        }
        self.out, self.receipt, self.dispatches = self._produce("saved")

    def _response(self, mutations=None):
        mutations = mutations or {}

        def respond(command, *, input, **_kwargs):
            output = Path(command[command.index("-o") + 1])
            archive = next(
                path for path in output.parents if path.name.endswith(".model-call")
            )
            label = archive.name.removesuffix(".model-call")
            value = _value(
                input.decode(), label.split("-", 1)[0].upper(), mutations.get(label)
            )
            output.write_text(json.dumps(value), encoding="utf-8")
            return SimpleNamespace(returncode=0, stdout=_transcript(value), stderr=b"")

        return respond

    def _produce(self, name, mutations=None):
        output = self.base / name
        with mock.patch(
            "stage1_eval.model_calls.subprocess.run",
            side_effect=self._response(mutations),
        ) as dispatch:
            result = run_context_quality_v3(
                self.dataset,
                self.reference,
                codex=self.codex,
                r1_home=self.homes["R1"],
                r2_home=self.homes["R2"],
                model=self.config["model"],
                reasoning=self.config["reasoning"],
                execution_policy=POLICY,
                output_dir=output,
            )
        self.assertGreater(dispatch.call_count, 0)
        return output, result["replay_receipt"], dispatch.call_count

    def _fresh(self, name):
        # A copied directory changes the frozen native command's output path.
        # Produce each tamper fixture at its original retained path instead.
        target, receipt, _ = self._produce(name)
        self.receipt = receipt
        return target

    def _verify(self, root=None, receipt=None, **changes):
        values = {
            "dataset": self.dataset,
            "reference": self.reference,
            "expected_config": self.config,
        }
        values.update(changes)
        return verify_context_quality_v3(
            root or self.out, receipt or self.receipt, **values
        )

    def test_authenticates_recomputes_and_never_dispatches_or_writes(self):
        before_env = dict(os.environ)
        before = {
            p.relative_to(self.out): _sha(p) for p in self.out.rglob("*") if p.is_file()
        }
        with mock.patch("stage1_eval.model_calls.subprocess.run") as dispatch:
            verified = self._verify()
        dispatch.assert_not_called()
        after = {
            p.relative_to(self.out): _sha(p) for p in self.out.rglob("*") if p.is_file()
        }
        self.assertEqual(before, after)
        self.assertEqual(before_env, dict(os.environ))
        self.assertEqual(verified["actual_model_attempts"], self.dispatches)
        self.assertEqual(verified["quality_report"]["designated_judgments"], 24)
        self.assertTrue(verified["authenticated"])
        self.assertTrue(verified["qa_pass"])
        self.assertFalse(verified["formal_ready"])
        self.assertEqual(verified["cost"], "unknown")

    def test_changed_inputs_config_runtime_or_code_binding_fail(self):
        dataset = copy.deepcopy(self.dataset)
        dataset["cases"][0]["subject_record"]["text"] += " changed"
        reference = copy.deepcopy(self.reference)
        reference["judgments"][0]["reason"] += " changed"
        changed_model = {**self.config, "model": "changed-model"}
        changed_runtime = {**self.config, "runtime_sha256": "0" * 64}
        cases = (
            ({"dataset": dataset}, "request|fingerprint"),
            ({"reference": reference}, "request|fingerprint"),
            ({"expected_config": changed_model}, "request|fingerprint"),
            ({"expected_config": changed_runtime}, "runtime-mismatch"),
        )
        for changes, message in cases:
            with (
                self.subTest(changes=tuple(changes)),
                self.assertRaisesRegex(Stage2Error, message),
            ):
                self._verify(**changes)
        with (
            mock.patch(
                "stage2_live.context_quality_replay._code_binding",
                return_value="f" * 64,
            ),
            self.assertRaisesRegex(Stage2Error, "request|fingerprint"),
        ):
            self._verify()

    def test_result_receipt_and_rehashed_outcomes_fail_closed(self):
        with self.assertRaisesRegex(Stage2Error, "result-receipt"):
            self._verify(receipt={**self.receipt, "result_sha256": "0" * 64})

        root = self._fresh("result-tamper")
        result_path = root / "result.json"
        value = json.loads(result_path.read_bytes())
        value["formal_ready"] = 0
        result_path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
        receipt = {**self.receipt, "result_sha256": _sha(result_path)}
        with self.assertRaisesRegex(Stage2Error, "result-recomputation"):
            self._verify(root, receipt)

    def test_rehashed_unit_and_native_archive_tamper_fail(self):
        root = self._fresh("unit-tamper")
        label = next(iter(self.receipt["unit_receipts"]))
        unit_path = root / f"{label}.unit.json"
        unit = json.loads(unit_path.read_bytes())
        unit["value"]["judgments"][0]["reason"] += " forged"
        unit_path.write_text(json.dumps(unit, sort_keys=True), encoding="utf-8")
        result_path = root / "result.json"
        result = json.loads(result_path.read_bytes())
        result["unit_receipts"][label] = _sha(unit_path)
        result_path.write_text(json.dumps(result, sort_keys=True), encoding="utf-8")
        receipt = {
            "result_sha256": _sha(result_path),
            "unit_receipts": dict(result["unit_receipts"]),
        }
        with self.assertRaisesRegex(Stage2Error, "value-mismatch"):
            self._verify(root, receipt)

        root = self._fresh("archive-tamper")
        archive_file = next(
            (root / f"{label}.model-call").glob("attempt-*.output.json")
        )
        archive_file.write_bytes(archive_file.read_bytes() + b" ")
        with self.assertRaises(Exception):
            self._verify(root)

    def test_unit_coverage_mode_inventory_and_missing_evidence_fail(self):
        receipt = copy.deepcopy(self.receipt)
        receipt["unit_receipts"].pop(next(iter(receipt["unit_receipts"])))
        with self.assertRaisesRegex(Stage2Error, "receipt-shape"):
            self._verify(receipt=receipt)

        root = self._fresh("injected-mode")
        request = json.loads((root / "request.json").read_bytes())
        request["mode"] = "injected-test"
        (root / "request.json").write_text(json.dumps(request), encoding="utf-8")
        with self.assertRaisesRegex(Stage2Error, "request-bytes"):
            self._verify(root)

        root = self._fresh("extra")
        (root / "unexpected.json").write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(Stage2Error, "inventory"):
            self._verify(root)

        root = self._fresh("missing")
        label = next(iter(self.receipt["unit_receipts"]))
        (root / f"{label}.schema.json").unlink()
        with self.assertRaisesRegex(Stage2Error, "missing-replay-file"):
            self._verify(root)

        root = self._fresh("extra-correction")
        (root / f"{label}-correction.model-call").mkdir()
        with self.assertRaisesRegex(Stage2Error, "unexpected-replay-correction"):
            self._verify(root)

    def test_sidecar_tamper_is_not_hidden_by_valid_archive_or_rehashed_result(self):
        label = next(iter(self.receipt["unit_receipts"]))
        path = self.out / f"{label}.jsonl"
        path.write_bytes(path.read_bytes() + b"forged display transcript")
        with self.assertRaisesRegex(Stage2Error, "sidecar-mismatch"):
            self._verify()

    def test_authentic_correction_attempt_is_retained_and_replayed(self):
        def foreign_evidence(value):
            value["judgments"][0]["evidence_ids"] = ["foreign-case-evidence"]

        output, receipt, calls = self._produce("corrected", {"r1-01": foreign_evidence})
        with mock.patch("stage1_eval.model_calls.subprocess.run") as dispatch:
            verified = self._verify(output, receipt)
        dispatch.assert_not_called()
        self.assertTrue(verified["qa_pass"])
        self.assertEqual(verified["actual_model_attempts"], calls)
        self.assertEqual(calls, self.dispatches + 1)
        self.assertIn("correction", verified["archive_sha256s"]["r1-01"])

    def test_symlink_root_is_rejected_when_platform_allows_it(self):
        link = self.base / "linked"
        try:
            link.symlink_to(self.out, target_is_directory=True)
        except OSError as error:
            self.skipTest(f"directory symlink unavailable: {error}")
        with self.assertRaisesRegex(Stage2Error, "regular-directory"):
            self._verify(link)

    def test_null_failure_and_boundary_score_are_recomputed(self):
        def null_first(value):
            value["judgments"][0].update(
                status="evaluator_failure",
                score=None,
                major_error=None,
                evidence_ids=[],
                reason="Synthetic evaluator failure retained as unknown.",
            )

        output, receipt, _ = self._produce("null", {"r2-01": null_first})
        verified = self._verify(output, receipt)
        self.assertFalse(verified["qa_pass"])
        self.assertIsNone(verified["roles"]["R2"]["judgments"][0]["score"])
        self.assertEqual(verified["quality_report"]["overall"]["matched"], 23)
        family = self.dataset["cases"][0]["family"]
        self.assertEqual(
            verified["quality_report"]["per_family"][family]["percent"], 87.5
        )


if __name__ == "__main__":
    unittest.main()
