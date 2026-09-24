"""Synthetic fail-closed execution, capture integrity, and isolation tests."""

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


PLUGIN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN / "cli"))
from stage1_ab import runner  # noqa: E402
from stage1_ab import facts, packet  # noqa: E402
from validators.evaluation_plan import validate_plan  # noqa: E402


def event_bytes(terminal="turn.completed", search=None):
    events = [
        {"type": "thread.started", "thread_id": "thread-synthetic"},
        {"type": "turn.started"},
    ]
    if search:
        events.append(
            {
                "type": "item.completed",
                "item": {
                    "id": "search-1",
                    "type": "web_search",
                    "query": search,
                    "status": "completed",
                },
            }
        )
    events.append(
        {
            "type": terminal,
            **(
                {
                    "usage": {
                        "input_tokens": 3,
                        "cached_input_tokens": 0,
                        "output_tokens": 2,
                    }
                }
                if terminal == "turn.completed"
                else {}
            ),
        }
    )
    return b"".join(json.dumps(e).encode() + b"\n" for e in events)


class Result:
    def __init__(self, stdout=b"", stderr=b"", returncode=0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


class Stage1ABExecutionTests(unittest.TestCase):
    @staticmethod
    def fake_exec(responses):
        def call(command, **_kwargs):
            Path(command[command.index("-o") + 1]).write_text(
                "synthetic final answer", encoding="utf-8"
            )
            (Path(_kwargs["cwd"]) / "generated.txt").write_text(
                str(len(responses)), encoding="utf-8"
            )
            return responses.pop(0)

        return call

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.profile = self.root / "profile"
        self.workspace = self.root / "workspace"
        self.profile.mkdir()
        self.workspace.mkdir()
        self.prompt = self.root / "prompt.txt"
        self.prompt.write_bytes(b"synthetic prompt\n")
        self.output = self.root / "run"
        self.lock = self.root / "lock.json"
        self.lock.write_text(
            json.dumps(
                {
                    "kind": "Stage1ABPublicLock",
                    "prompt_sha256": runner.sha(self.prompt.read_bytes()),
                    "paired_repeats": [
                        {
                            "repeat": 1,
                            "order": ["baseline", "treatment"],
                            "baseline": {
                                "run_id": "run-a",
                                "subject_id": "subject-aaaaaaaaaaaaaaaa",
                            },
                            "treatment": {
                                "run_id": "run-b",
                                "subject_id": "subject-bbbbbbbbbbbbbbbb",
                            },
                        }
                    ],
                    "runtime": {
                        "app_version": "codex-cli 0.153.0",
                        "search_enabled": True,
                    },
                    "plugin_tree_sha256": runner.tree_sha(PLUGIN),
                    "research_hub_sha": runner.RESEARCH_HUB_SHA,
                }
            ),
            encoding="utf-8",
        )
        self.preflight = self.root / "preflight.json"
        self.preflight.write_text(
            json.dumps(
                {
                    "kind": "Stage1ABHostPreflight",
                    "valid": True,
                    "lock_sha256": runner.sha(self.lock.read_bytes()),
                    "profiles": {
                        "baseline": str(self.profile.resolve()),
                        "treatment": str(self.profile.resolve()),
                    },
                    "workspaces": {
                        "baseline": str(self.workspace.resolve()),
                        "treatment": str(self.workspace.resolve()),
                    },
                    "research_hub_sha": runner.RESEARCH_HUB_SHA,
                }
            ),
            encoding="utf-8",
        )

    def test_runtime_bytes_bound_before_launch(self):
        self.prompt.write_bytes(b"changed")
        with self.assertRaisesRegex(runner.ExecutionBlocked, "prompt changed"):
            runner.capture(
                "codex",
                self.lock,
                "baseline",
                1,
                self.profile,
                self.workspace,
                self.prompt,
                self.output,
                self.root / "private",
                self.preflight,
            )
        self.prompt.write_bytes(b"synthetic prompt\n")
        lock = runner.read_json(self.lock)
        lock["plugin_tree_sha256"] = "0" * 64
        self.lock.write_text(json.dumps(lock), encoding="utf-8")
        preflight = runner.read_json(self.preflight)
        preflight["lock_sha256"] = runner.sha(self.lock.read_bytes())
        self.preflight.write_text(json.dumps(preflight), encoding="utf-8")
        with (
            patch.object(
                runner,
                "probe_profile",
                return_value={"codex_version": "codex-cli 0.153.0"},
            ),
            self.assertRaisesRegex(runner.ExecutionBlocked, "plugin bytes"),
        ):
            runner.capture(
                "codex",
                self.lock,
                "treatment",
                1,
                self.profile,
                self.workspace,
                self.prompt,
                self.output,
                self.root / "private",
                self.preflight,
            )

    def test_private_decoy_and_extra_baseline_plugin_block_probe(self):
        private = self.root / "private"
        private.mkdir()
        with self.assertRaisesRegex(runner.ExecutionBlocked, "private answer tree"):
            runner.probe_profile("codex", self.profile, self.workspace, False, private)

        private.rmdir()
        (self.profile / "decoy.txt").write_text("secret-answer-id", encoding="utf-8")
        with self.assertRaisesRegex(
            runner.ExecutionBlocked, "private answer identifier"
        ):
            runner.probe_profile(
                "codex",
                self.profile,
                self.workspace,
                False,
                private,
                ["secret-answer-id"],
            )
        (self.profile / "decoy.txt").unlink()
        (self.workspace / "answer_key.json").write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(runner.ExecutionBlocked, "workspace is not empty"):
            runner.probe_profile("codex", self.profile, self.workspace, False, private)
        (self.workspace / "answer_key.json").unlink()
        (self.profile / "answer_key.json").write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(runner.ExecutionBlocked, "answer-like"):
            runner.probe_profile("codex", self.profile, self.workspace, False, private)
        (self.profile / "answer_key.json").unlink()
        (self.profile / "config.toml").write_text(
            "[plugins.extra]\nenabled = true\n", encoding="utf-8"
        )

        def fake(command, **kwargs):
            if command[-2:] == ["login", "status"]:
                return Result("Logged in using ChatGPT", "", 0)
            return Result("codex-cli 0.153.0", "", 0)

        with (
            patch.object(runner.subprocess, "run", side_effect=fake),
            self.assertRaisesRegex(runner.ExecutionBlocked, "extension"),
        ):
            runner.probe_profile("codex", self.profile, self.workspace, False, private)

    def test_discovered_skill_must_be_readable_by_subject_model(self):
        skill = self.root / "SKILL.md"
        skill.write_bytes(b"# Stage 1 synthetic skill\n")
        digest = runner.sha(skill.read_bytes())
        success = Result(
            json.dumps(
                {
                    "type": "item.completed",
                    "item": {"type": "agent_message", "text": digest},
                }
            ).encode()
            + b"\n"
        )
        denied = Result(
            json.dumps(
                {
                    "type": "item.completed",
                    "item": {"type": "agent_message", "text": "BLOCKED"},
                }
            ).encode()
            + b"\n"
        )
        with patch.object(runner.subprocess, "run", return_value=success):
            self.assertEqual(runner._functional_skill_smoke("codex", {}, skill), digest)
        with (
            patch.object(runner.subprocess, "run", return_value=denied),
            self.assertRaisesRegex(runner.ExecutionBlocked, "unreadable"),
        ):
            runner._functional_skill_smoke("codex", {}, skill)

    def test_capture_tamper_and_safe_resume(self):
        responses = [
            Result(event_bytes("turn.failed", "synthetic search")),
            Result(event_bytes("turn.completed", "different search")),
        ]
        with (
            patch.object(
                runner,
                "probe_profile",
                return_value={"codex_version": "codex-cli 0.153.0"},
            ),
            patch.object(
                runner.subprocess, "run", side_effect=self.fake_exec(responses)
            ),
        ):
            first = runner.capture(
                "codex",
                self.lock,
                "baseline",
                1,
                self.profile,
                self.workspace,
                self.prompt,
                self.output,
                self.root / "private",
                self.preflight,
            )
            self.assertEqual(first["status"], "failed")
            second = runner.capture(
                "codex",
                self.lock,
                "baseline",
                1,
                self.profile,
                self.workspace,
                self.prompt,
                self.output,
                self.root / "private",
                self.preflight,
                resume=True,
            )
        self.assertEqual(second["run_id"], "run-a")
        self.assertEqual(len(second["attempts"]), 2)
        self.assertEqual(second["status"], "complete")
        self.assertEqual(runner.verify_capture(self.output)["status"], "complete")
        final = self.output / "attempt-02.final.txt"
        final.write_text("tampered final", encoding="utf-8")
        with self.assertRaisesRegex(runner.ExecutionBlocked, "byte hash differs"):
            runner.verify_capture(self.output)
        final.write_text("synthetic final answer", encoding="utf-8")
        generated = self.output / "workspace/02/generated.txt"
        generated.write_text("tampered generated file", encoding="utf-8")
        with self.assertRaisesRegex(runner.ExecutionBlocked, "byte hash differs"):
            runner.verify_capture(self.output)
        generated.write_text("1", encoding="utf-8")
        with self.assertRaisesRegex(runner.ExecutionBlocked, "completed run"):
            runner.capture(
                "codex",
                self.lock,
                "baseline",
                1,
                self.profile,
                self.workspace,
                self.prompt,
                self.output,
                self.root / "private",
                self.preflight,
                resume=True,
            )
        path = self.output / "attempt-01.jsonl"
        path.write_bytes(path.read_bytes() + b"{}\n")
        with self.assertRaisesRegex(runner.ExecutionBlocked, "byte hash differs"):
            runner.verify_capture(self.output)

    def test_resume_no_reexecution_marks_recovery_incomplete(self):
        responses = [
            Result(event_bytes("turn.failed", "same search")),
            Result(event_bytes("turn.completed", "same search")),
        ]
        with (
            patch.object(
                runner,
                "probe_profile",
                return_value={"codex_version": "codex-cli 0.153.0"},
            ),
            patch.object(
                runner.subprocess, "run", side_effect=self.fake_exec(responses)
            ),
        ):
            runner.capture(
                "codex",
                self.lock,
                "baseline",
                1,
                self.profile,
                self.workspace,
                self.prompt,
                self.output,
                self.root / "private",
                self.preflight,
            )
            second = runner.capture(
                "codex",
                self.lock,
                "baseline",
                1,
                self.profile,
                self.workspace,
                self.prompt,
                self.output,
                self.root / "private",
                self.preflight,
                resume=True,
            )
        self.assertEqual(second["status"], "incomplete")

    def test_wrong_runtime_and_holdout_binding_fail_freeze(self):
        plan = json.loads(
            (PLUGIN / "evals/examples/evaluation-plan-v2.synthetic.json").read_text()
        )
        plan["execution_class"] = "formal"
        plan["subject_runtime"]["model_id"] = "wrong-model"
        path = self.root / "plan.json"
        path.write_text(json.dumps(plan), encoding="utf-8")
        with (
            patch.object(runner, "validate_plan", return_value=[]),
            self.assertRaisesRegex(runner.ExecutionBlocked, "model, reasoning"),
        ):
            runner.freeze(path, self.prompt, self.root, self.root / "lock-out.json")
        plan["subject_runtime"]["model_id"] = "gpt-5.6-sol"
        plan["bindings"]["holdout"]["path"] = "private/../escape.json"
        self.prompt.write_bytes(b"x" * 1247)
        plan["bindings"]["prompt"]["artifact"]["sha256"] = runner.sha(
            self.prompt.read_bytes()
        )
        path.write_text(json.dumps(plan), encoding="utf-8")
        with (
            patch.object(runner, "PROMPT_SHA256", runner.sha(self.prompt.read_bytes())),
            patch.object(runner, "validate_plan", return_value=[]),
            self.assertRaisesRegex(runner.ExecutionBlocked, "holdout path"),
        ):
            runner.freeze(path, self.prompt, self.root, self.root / "lock-out.json")

    def test_failure_distinct_from_empty_and_factual_source_bytes_bound(self):
        eval_root = self.root / "evals"
        private = eval_root / "private"
        private.mkdir(parents=True)
        source = private / "source.txt"
        source.write_text("synthetic evidence", encoding="utf-8")
        evidence = {
            "ev1": {
                "path": "private/source.txt",
                "sha256": runner.sha(source.read_bytes()),
                "locator": "line 1",
            }
        }
        holdout_path = PLUGIN / "evals/examples/holdout-manifest-v2.synthetic.json"
        plan_path = PLUGIN / "evals/examples/evaluation-plan-v2.synthetic.json"
        holdout = runner.read_json(holdout_path)
        annotation = {
            "evidence": evidence,
            "works": [
                {
                    "work_id": "work-1",
                    "identity_status": "correct",
                    "link_status": "correct",
                    "identity_evidence_id": "ev1",
                    "link_evidence_id": "ev1",
                    "discovery_evidence_id": "ev1",
                    "anchor_evidence_id": "ev1",
                    "cluster_evidence_id": "ev1",
                    "matched_anchor_ids": [holdout["anchors"][0]["anchor_id"]],
                    "verified_clusters": holdout["coverage_clusters"],
                    "year": 2020,
                    "recent": True,
                    "included": True,
                    "source_version": "v1",
                    "access_date": "2026-09-17",
                }
            ],
            "claims": [
                {
                    "work_id": "work-1",
                    "status": "supported",
                    "locator_evidence_id": "ev1",
                    "central_source_mismatch": False,
                }
            ],
            "decisions": [{"reason_evidence_id": "ev1"}],
            "searches": [
                {"kind": "recent", "state": "backend-failure", "evidence_id": "ev1"},
                {"kind": "closest-work", "state": "zero-results", "evidence_id": "ev1"},
            ],
            "stop_evidence_id": "ev1",
            "major_issues": [],
            "human_interventions": 0,
            "actual_cost": None,
        }
        annotation_path = private / "annotations.json"
        annotation_path.write_text(json.dumps(annotation), encoding="utf-8")
        self.output.mkdir()
        events = event_bytes()
        (self.output / "attempt-01.jsonl").write_bytes(events)
        stamp = "2026-09-17T15:01:00+00:00"
        record = {
            "run_id": "run01-b",
            "subject_id": "subject-0000000000000002",
            "condition": "treatment",
            "status": "complete",
            "attempts": [
                {
                    "started_at": stamp,
                    "ended_at": stamp,
                    "exit_code": 0,
                    "summary": runner._event_summary(events),
                    "files": {"attempt-01.jsonl": runner.sha(events)},
                }
            ],
        }
        (self.output / "run.json").write_text(json.dumps(record), encoding="utf-8")
        result = facts.make_result(
            annotation_path, holdout_path, plan_path, self.output, eval_root
        )
        self.assertEqual(result["fact_metrics"]["coverage"]["clusters_hit"], 6)
        self.assertEqual(result["fact_metrics"]["claim_support"]["supported"], 1)
        self.assertEqual(annotation["searches"][0]["state"], "backend-failure")
        source.write_text("tampered", encoding="utf-8")
        with self.assertRaisesRegex(runner.ExecutionBlocked, "byte hash differs"):
            facts.make_result(
                annotation_path, holdout_path, plan_path, self.output, eval_root
            )

    def test_blind_packet_rejects_condition_and_source_tamper(self):
        eval_root = PLUGIN / "evals"
        (eval_root / "private").mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=eval_root / "private") as directory:
            root = Path(directory)
            result = root / "result.json"
            result.write_bytes(
                (
                    eval_root / "examples/stage1-evaluation-result-v2.synthetic.json"
                ).read_bytes()
            )
            evidence = root / "evidence.json"
            evidence.write_text(
                json.dumps(
                    {"evidence_ids": ["ev-1"], "source_excerpts": ["synthetic excerpt"]}
                ),
                encoding="utf-8",
            )
            plan_path = eval_root / "examples/evaluation-plan-v2.synthetic.json"
            made = packet.make_packet(result, plan_path, evidence, root / "packet.json")
            self.assertEqual(
                packet.verify_packet(made, runner.read_json(plan_path))["hard_facts"][
                    "coverage"
                ]["clusters_total"],
                6,
            )
            evidence.write_text(
                json.dumps({"evidence_ids": ["ev-1"], "source_excerpts": ["changed"]}),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                runner.ExecutionBlocked, "source-excerpt bytes differ"
            ):
                packet.verify_packet(made, runner.read_json(plan_path))
            evidence.write_text(
                json.dumps({"evidence_ids": ["ev-1"], "source_excerpts": ["baseline"]}),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(runner.ExecutionBlocked, "condition label"):
                packet.make_packet(result, plan_path, evidence, root / "unblinded.json")

    def test_dependency_sha_bound_on_host_preflight(self):
        lock = runner.read_json(self.lock)
        lock["runtime"]["model_id"] = "gpt-5.6-sol"
        lock["runtime"]["reasoning"] = "high"
        self.lock.write_text(json.dumps(lock), encoding="utf-8")
        b_profile = self.root / "profile-b"
        t_profile = self.root / "profile-t"
        b_workspace = self.root / "workspace-b"
        t_workspace = self.root / "workspace-t"
        for path in (b_profile, t_profile, b_workspace, t_workspace):
            path.mkdir()
        proof = {
            "codex_version": "codex-cli 0.153.0",
            "model": "gpt-5.6-sol",
            "reasoning": "high",
            "native_web_search": True,
            "native_capabilities": {"webSearch": True},
            "native_capabilities_sha256": "synthetic-profile",
        }
        lock["runtime"]["tool_profile_sha256"] = "synthetic-profile"
        self.lock.write_text(json.dumps(lock), encoding="utf-8")
        with (
            patch.object(runner, "probe_profile", return_value=proof),
            patch.object(
                runner.subprocess, "run", return_value=Result("wrong-sha\n", "", 0)
            ),
            self.assertRaisesRegex(runner.ExecutionBlocked, "research-hub checkout"),
        ):
            runner.host_preflight(
                "codex",
                self.lock,
                b_profile,
                t_profile,
                b_workspace,
                t_workspace,
                self.root / "private",
                self.root,
                self.root / "report.json",
            )

    def test_experimental_formal_plan_requires_readiness_evidence(self):
        plan = json.loads(
            (PLUGIN / "evals/examples/evaluation-plan-v2.synthetic.json").read_text()
        )
        plan["execution_class"] = "formal"
        plan["bindings"]["treatment_build"]["capability_ids"] = ["cli:stage1-ab"]
        plan["bindings"]["treatment_build"]["changed_owner_paths"] = [
            "plugins/auto-research-agent/cli/stage1_ab"
        ]
        self.assertIn(
            "experimental treatment requires a formal Stage 1 readiness binding",
            validate_plan(plan),
        )
        plan["bindings"]["stage1_readiness"] = {
            "path": "evidence/stage1-south-korea-20260922/readiness-manifest.json",
            "sha256": "0" * 64,
            "research_hub_sha": runner.RESEARCH_HUB_SHA,
        }
        self.assertIn(
            "Stage 1 readiness manifest byte hash does not match", validate_plan(plan)
        )


if __name__ == "__main__":
    unittest.main()
