"""Complete native-unit submissions and replay, without scientific model claims."""

import json
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

import test_criterion_execution as process_fixture
import test_source_pipeline as source_fixture
from test_judging_v31 import _packet, _evidence, _core
from stage1_eval import complete_judging as complete
from stage1_eval.common import EvaluationError, canonical, read_json, sha


class CompleteJudgingTests(unittest.TestCase):
    def setUp(self):
        self.process = process_fixture.CriterionExecutionTests()
        self.process.setUp()
        self.addCleanup(self.process.doCleanups)
        self.root, self.options = self.process.root, self.process.options
        self.packet = _packet()
        self.packet["spec"]["draft"]["needs"] = [
            {"need_id": "need-1"},
            {"need_id": "need-2"},
        ]
        self.audits = {role: {"summaries": [], "leaves": []} for role in ("r1", "r2")}
        self.prompts = []
        self.different_code = False
        self.false_major = False

    def respond(self, command, **kwargs):
        prompt = kwargs["input"].decode()
        if prompt.startswith("Evaluate the assigned Stage 1 criterion"):
            return self.process.respond(command, **kwargs)
        data, _ = json.JSONDecoder().raw_decode(prompt[prompt.index('{"unit_kind"') :])
        self.prompts.append(data)
        packet = data["packet"]
        rows = {
            "criteria": [],
            "core_assessments": [],
            "omission_assessments": [],
            "major_issues": [],
        }
        if self.false_major:
            rows["major_issues"] = [
                {
                    "issue_id": "synthetic",
                    "violation_type": "false-completion-or-failure-state",
                    "status": "confirmed",
                    "dimension": "P3",
                    "passages": [{"span_id": next(iter(packet["spans"]))}],
                    "reason": "Synthetic allegation with no contrary process evidence.",
                }
            ]
        if data["unit_kind"] == "core":
            for work in packet["assigned_work_ids"]:
                row = _core(work, "candidate")
                row["passages"] = []
                rows["core_assessments"].append(row)
        if "assigned_criterion_id" in packet:
            key = packet["assigned_criterion_id"]
            missing = (
                "identity-ambiguous"
                if self.different_code
                and Path(command[command.index("-o") + 1]).parent.name.startswith(
                    "content-r2-"
                )
                else "source-unavailable"
            )
            rows["criteria"] = [
                {
                    "criterion_id": key,
                    "status": "unverifiable",
                    "score": None,
                    "passages": [],
                    "reason": "Synthetic inaccessible source condition.",
                    "missing_evidence": ["Source unavailable"],
                    "conclusion_code": "unverifiable",
                    "missing_evidence_codes": [missing],
                }
            ]
            if key.startswith("P2"):
                rows["addressed_need_ids"] = [
                    n["need_id"] for n in packet["spec"]["draft"]["needs"]
                ]
        return self.process.fixture.completed(command, rows)

    def invoke(self, **kwargs):
        return complete.judge_packet_complete(
            self.packet,
            self.root / "complete",
            self.options,
            source_audits=self.audits,
            **kwargs,
        )

    def test_all_ten_criteria_native_archives_and_zero_call_replay(self):
        with patch(
            "stage1_eval.model_calls.subprocess.run", side_effect=self.respond
        ) as calls:
            result = self.invoke()
            self.assertGreater(calls.call_count, 20)
        self.assertEqual(
            sum(len(row["criteria"]) for row in result["selected"].values()), 10
        )
        self.assertEqual(result["adjudicated_phases"], [])
        for criterion in result["provenance"]["process"]["complete_criteria"].values():
            for role, execution in criterion["roles"].items():
                for record in [execution, *execution["nodes"].values()]:
                    manifest = record["source_audit_view_manifest"]
                    self.assertEqual(manifest["judge_role"], role.upper())
                    self.assertEqual(manifest["state"], "not-applicable")
                    self.assertEqual(manifest["audit_source_roles"], [])
        self.assertEqual(
            len([p for p in self.prompts if "assigned_criterion_id" in p["packet"]]), 14
        )
        for prompt in self.prompts:
            self.assertFalse(prompt["packet"]["judge_view_manifest"]["truncated"])
            self.assertNotIn("prior_judgments", prompt["packet"])
        for path in (self.root / "complete").rglob("*.view.json"):
            view = read_json(path)
            self.assertEqual(view["expected_span_ids"], view["planned_span_ids"])
            self.assertNotIn("submitted_span_ids", view)
        with patch("stage1_eval.model_calls.subprocess.run") as replay:
            self.assertEqual(self.invoke(replay_only=True), result)
        replay.assert_not_called()
        target = self.root / "complete/result.json"
        modified = read_json(target)
        modified["selected"]["content"]["criteria"][0]["score"] = 0
        target.write_bytes(canonical(modified))
        with patch("stage1_eval.model_calls.subprocess.run") as replay:
            with self.assertRaisesRegex(EvaluationError, "artifact changed"):
                self.invoke(replay_only=True)
        replay.assert_not_called()

    def test_content_over_old_view_limit_has_all_text_and_every_need(self):
        text = "Ordinary text. " * 4500 + "TAIL CONTRARY FINDING"
        self.packet["content_evidence"] = {"answer": _evidence(text)}
        with patch("stage1_eval.model_calls.subprocess.run", side_effect=self.respond):
            complete._content(
                self.packet, self.root / "content", self.options, self.audits, False
            )
        for prompt in self.prompts:
            self.assertEqual(
                "".join(r["text"] for r in prompt["packet"]["spans"].values()), text
            )
            self.assertIn("TAIL CONTRARY FINDING", str(prompt))
            self.assertEqual(
                [n["need_id"] for n in prompt["packet"]["spec"]["draft"]["needs"]],
                ["need-1", "need-2"],
            )

    def test_oversize_fails_before_call_instead_of_omitting_evidence(self):
        self.packet["content_evidence"] = {
            "answer": _evidence("X" * complete.MAX_COMPLETE_PROMPT_BYTES)
        }
        with patch("stage1_eval.model_calls.subprocess.run") as calls:
            with self.assertRaisesRegex(EvaluationError, "no evidence was omitted"):
                self.invoke()
        calls.assert_not_called()
        self.assertFalse((self.root / "complete/result.json").exists())

    def test_equal_null_scores_with_different_missing_codes_require_adjudication(self):
        self.different_code = True
        self.root = self.root / "r2-in-parent"
        with patch("stage1_eval.model_calls.subprocess.run", side_effect=self.respond):
            result = self.invoke()
        self.assertEqual(result["adjudicated_phases"], ["content"])

    def test_major_review_rejects_ungrounded_confirmation_and_keeps_failures(self):
        self.false_major = True
        with patch(
            "stage1_eval.model_calls.subprocess.run", side_effect=self.respond
        ) as calls:
            with self.assertRaisesRegex(EvaluationError, "contrary process evidence"):
                complete._call(
                    self.packet,
                    "process",
                    "review",
                    [],
                    None,
                    None,
                    self.root / "major",
                    "review",
                    self.options,
                    False,
                )
        self.assertEqual(calls.call_count, 2)
        self.assertEqual(
            len(list((self.root / "major/model-logs").glob("*.model-call"))), 2
        )
        self.assertFalse((self.root / "major/review.result.json").exists())

    def test_core_batches_preserve_every_work_and_missing_need_is_rejected(self):
        self.packet["extraction"]["works"] = [{"work_id": f"w{i}"} for i in range(5)]
        with patch("stage1_eval.model_calls.subprocess.run", side_effect=self.respond):
            result = self.invoke()
        self.assertEqual(len(result["selected"]["content"]["core_assessments"]), 5)
        core = [p for p in self.prompts if p["unit_kind"] == "core"]
        self.assertEqual(
            [len(p["packet"]["assigned_work_ids"]) for p in core], [4, 1, 4, 1]
        )

        def invalid(prompt, schema, root, label, options, normalize, **kwargs):
            raw = {
                "criteria": [{"criterion_id": "P2V3.SCOPE", "passages": []}],
                "core_assessments": [],
                "omission_assessments": [],
                "major_issues": [],
                "addressed_need_ids": ["need-1"],
            }
            return normalize(raw), {}

        with patch.object(complete, "run_unit", side_effect=invalid):
            with self.assertRaisesRegex(EvaluationError, "every frozen need"):
                complete._call(
                    self.packet,
                    "content",
                    "content",
                    [],
                    None,
                    None,
                    self.root / "invalid",
                    "criterion",
                    self.options,
                    False,
                    criterion="P2V3.SCOPE",
                    review={"omission_assessments": [], "major_issues": []},
                )

    def _audit_passage(self, work, leaf):
        text = f"Bound source passage for {work}, window {leaf}."
        source_version = f"source-version-{work}"
        identity = {
            "evidence_id": f"source-{work}",
            "artifact_sha256": sha(f"artifact-{work}".encode()),
            "text_sha256": sha(f"complete-source-{work}".encode()),
            "source_version": source_version,
            "work_id": work,
            "origin": "source-fetch",
            "view": "text",
            "start": 0,
            "end": len(text),
            "locator": {"page": leaf + 1},
        }
        return {
            "span_id": "span-" + sha(canonical(identity)),
            **identity,
            "text": text,
            "level": "full-text",
            "raw_source_sha256": sha(f"raw-{work}-{leaf}".encode()),
            "source_record_sha256": sha(f"record-{work}-{leaf}".encode()),
            "version_alias": f"w{int(work[1:]) + 1}:{sha(source_version.encode())[:12]}",
        }

    def representative_audits(self, *, leaves_per_work=2, reason=None):
        self.packet["extraction"]["works"] = [
            {"work_id": f"w{i:02d}"} for i in range(15)
        ]
        reason = reason or "Synthetic source observation."
        for role in ("r1", "r2"):
            for i in range(15):
                work = f"w{i:02d}"
                target = {"id": f"target-{i:02d}", "work_ids": [work]}
                verdict = (
                    "unverifiable"
                    if i == 14
                    else ("contradicted" if role == "r2" and i == 0 else "supported")
                )
                self.audits[role]["summaries"].append(
                    {
                        "target": target,
                        "verdict": verdict,
                        "unknown_reason": "source-unavailable" if i == 14 else None,
                    }
                )
                for leaf in range(leaves_per_work):
                    self.audits[role]["leaves"].append(
                        {
                            "unit_id": f"{role}-unit-{i:02d}-{leaf}",
                            "target_id": target["id"],
                            "value": {
                                "verdict": verdict,
                                "reason": reason,
                                "passages": [self._audit_passage(work, leaf)],
                            },
                        }
                    )

    def test_fifteen_work_audit_manifest_isolated_adjudicated_unknown_and_replayed(
        self,
    ):
        self.representative_audits()
        with patch("stage1_eval.model_calls.subprocess.run", side_effect=self.respond):
            result = self.invoke()
        self.assertIn("content", result["adjudicated_phases"])
        for role in ("r1", "r2", "adj"):
            preflight = read_json(
                self.root / f"complete/content/content-{role}-preflight.json"
            )
            self.assertEqual(preflight["status"], "passed")
            self.assertTrue(preflight["plans"])
            self.assertTrue(
                all(
                    row["prompt_bytes_upper_bound"] <= preflight["prompt_byte_limit"]
                    for row in preflight["plans"]
                )
            )
            self.assertFalse(preflight["score_awarded"])
        seen = {role: {"targets": set(), "units": set()} for role in ("r1", "r2")}
        for label, record in result["provenance"]["content"].items():
            manifest = record["source_audit_view_manifest"]
            role = label.split("-")[1]
            self.assertEqual(manifest["judge_role"], role.upper())
            self.assertEqual(
                manifest["audit_source_roles"],
                ["r1", "r2"] if role == "adj" else [role],
            )
            self.assertFalse(manifest["omitted"])
            self.assertFalse(manifest["truncated"])
            for source_role, view in manifest["roles"].items():
                self.assertTrue(
                    all(u.startswith(source_role + "-") for u in view["unit_ids"])
                )
                seen[source_role]["targets"].update(view["target_ids"])
                seen[source_role]["units"].update(view["unit_ids"])
                if "core" not in label:
                    self.assertEqual(len(view["target_ids"]), 15)
                    self.assertEqual(len(view["unit_ids"]), 30)
                    self.assertEqual(
                        view["unavailable_targets"],
                        [{"target_id": "target-14", "reason": "source-unavailable"}],
                    )
                    self.assertEqual(len(view["unavailable_unit_ids"]), 2)
                    self.assertEqual(view["out_of_scope_target_ids"], [])
        for role, view in seen.items():
            self.assertEqual(view["targets"], {f"target-{i:02d}" for i in range(15)})
            self.assertEqual(
                view["units"],
                {f"{role}-unit-{i:02d}-{j}" for i in range(15) for j in range(2)},
            )
        for prompt in self.prompts:
            data = prompt["packet"]
            manifest = data["judge_view_manifest"]["source_audit_view_manifest"]
            supplied = data.get("source_audit_observations")
            self.assertEqual(manifest["supplied_view_sha256"], sha(canonical(supplied)))
            if supplied is not None:
                for role, audit in supplied.items():
                    self.assertEqual(
                        manifest["roles"][role]["supplied_view_sha256"],
                        sha(canonical(audit)),
                    )
            else:
                self.assertEqual(manifest["state"], "not-applicable")
        supplied_passage = next(
            prompt["packet"]["source_audit_observations"]["r1"]["leaves"][0]["value"][
                "passages"
            ][0]
            for prompt in self.prompts
            if prompt["unit_kind"] == "core"
            and "r1" in prompt["packet"].get("source_audit_observations", {})
        )
        self.assertNotIn("text", supplied_passage)
        self.assertNotIn("source_level", supplied_passage)
        self.assertEqual(
            set(supplied_passage),
            {
                "span_id",
                "evidence_id",
                "artifact_sha256",
                "text_sha256",
                "source_version",
                "work_id",
                "origin",
                "view",
                "start",
                "end",
                "locator",
                "level",
                "raw_source_sha256",
                "source_record_sha256",
                "version_alias",
            },
        )
        self.assertTrue(
            all(
                row["score"] is None
                for row in result["selected"]["content"]["criteria"]
            )
        )
        with patch("stage1_eval.model_calls.subprocess.run") as calls:
            self.assertEqual(self.invoke(replay_only=True), result)
        calls.assert_not_called()
        path = self.root / "complete/content/content-r1-review.result.json"
        original = path.read_bytes()
        for field, changed in (
            ("supplied_view_sha256", "0" * 64),
            ("audit_source_roles", ["r2"]),
        ):
            value = json.loads(original)
            value["source_audit_view_manifest"][field] = changed
            path.write_bytes(canonical(value))
            with patch("stage1_eval.model_calls.subprocess.run") as calls:
                with self.assertRaisesRegex(EvaluationError, "artifact changed"):
                    self.invoke(replay_only=True)
            calls.assert_not_called()
            path.write_bytes(original)

        passage = self.audits["r1"]["leaves"][0]["value"]["passages"][0]
        original_passage = deepcopy(passage)
        changes = {
            "span_id": "span-" + "0" * 64,
            "evidence_id": "source-tampered",
            "artifact_sha256": "0" * 64,
            "text_sha256": "1" * 64,
            "source_version": "source-version-tampered",
            "work_id": "w99",
            "origin": "tampered-origin",
            "view": "tampered-view",
            "start": 1,
            "end": passage["end"] + 1,
            "locator": {"page": 999},
            "level": "abstract",
            "raw_source_sha256": "2" * 64,
            "source_record_sha256": "3" * 64,
            "version_alias": "w99:tampered",
        }
        for field, changed in changes.items():
            passage.clear()
            passage.update(deepcopy(original_passage))
            passage[field] = changed
            with patch("stage1_eval.model_calls.subprocess.run") as calls:
                with self.assertRaises(EvaluationError, msg=field):
                    self.invoke(replay_only=True)
            calls.assert_not_called()
        passage.clear()
        passage.update(original_passage)

    def test_fifteen_work_oversized_audit_fails_before_native_call_or_score(self):
        self.representative_audits(leaves_per_work=40, reason="X" * 400)
        with patch("stage1_eval.model_calls.subprocess.run") as calls:
            with self.assertRaisesRegex(EvaluationError, "no evidence was omitted"):
                self.invoke()
        calls.assert_not_called()
        self.assertFalse((self.root / "complete/result.json").exists())
        receipt = read_json(self.root / "complete/content/content-r1-preflight.json")
        self.assertEqual(receipt["status"], "failed")
        self.assertTrue(receipt["oversize_unit_ids"])
        self.assertFalse(receipt["score_awarded"])
        self.assertFalse((self.root / "complete/content/model-logs").exists())

    def test_unbound_or_duplicate_audit_leaves_are_not_silently_omitted(self):
        from stage1_eval.source_audit_views import _observations

        self.representative_audits()
        self.audits["r1"]["leaves"][0]["target_id"] = "foreign"
        with self.assertRaisesRegex(EvaluationError, "unbound obligations"):
            _observations(self.audits)

    def test_audit_role_isolation_and_adjudication_gate_fail_before_call(self):
        self.representative_audits()
        for role, audits, prior in (
            ("r1", self.audits, None),
            ("adj", self.audits, None),
        ):
            with patch("stage1_eval.model_calls.subprocess.run") as calls:
                with self.assertRaises(EvaluationError):
                    complete._call(
                        self.packet,
                        "content",
                        "review",
                        [],
                        prior,
                        audits,
                        self.root / role,
                        "review",
                        self.options,
                        False,
                        role=role,
                    )
            calls.assert_not_called()

    def test_pipeline_connects_original_fields_audits_all_criteria_and_aggregation(
        self,
    ):
        scenario = source_fixture.SourcePipelineTests()
        scenario.setUp()
        self.addCleanup(scenario.doCleanups)
        scenario.flow.judge.side_effect = complete.judge_packet_complete

        def native(command, **kwargs):
            prompt = kwargs["input"].decode()
            if prompt.startswith(
                ("Extract only the original", "Audit only the supplied")
            ):
                return scenario.original.respond(command, **kwargs)
            return self.respond(command, **kwargs)

        with (
            patch.object(
                source_fixture.pipeline,
                "collect_sources_v31",
                return_value=scenario.sources,
            ),
            patch(
                "stage1_eval.model_calls.subprocess.run", side_effect=native
            ) as calls,
        ):
            result = source_fixture.pipeline.evaluate_v31(scenario.flow.args)
            self.assertEqual(
                sum(len(d["criteria"]) for d in result["dimensions"].values()), 10
            )
            self.assertEqual(result["evaluator_status"], "complete")
            self.assertEqual(result["scientific_readiness_status"], "inconclusive")
            costs = read_json(Path(scenario.flow.args.output) / "model-costs.json")
            self.assertGreater(costs["attempts"], 20)
            self.assertEqual(costs["attempts_without_usage"], costs["attempts"])
            self.assertIsNone(costs["tokens"]["input_tokens"])
            scenario.flow.args.resume_verified = True
            calls.reset_mock()
            self.assertEqual(
                source_fixture.pipeline.evaluate_v31(
                    scenario.flow.args, replay_only=True
                ),
                result,
            )
            calls.assert_not_called()


if __name__ == "__main__":
    unittest.main()
