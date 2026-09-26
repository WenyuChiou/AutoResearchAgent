"""Separate evaluator pins, confirmed scope, and v3.1 paired admission."""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cli"))
from stage1_ab import general, general_v31, runner  # noqa: E402
from stage1_ab.capture_v31 import capture_subject  # noqa: E402
from stage1_eval.common import EvaluationError, canonical, sha  # noqa: E402
from stage1_eval.formal import verify_binding_v31  # noqa: E402
from stage1_eval.pipeline_v31 import execution_policy  # noqa: E402
from test_research_brief import brief  # noqa: E402
from test_stage1_ab_general_v3 import runs  # noqa: E402
from test_stage1_general_eval import spec  # noqa: E402


class GeneralABV31Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.codex = self.root / "codex"
        self.codex.write_bytes(b"codex")
        self.task = self.root / "task.txt"
        self.task.write_bytes(b"Explore household consumption in a user-chosen region.")
        self.spec = spec()
        self.spec["task_sha256"] = sha(self.task.read_bytes())
        self.spec["generation"] = {"prompt_sha256": "d" * 64}
        self.prefix = [sys.executable, "-m", "research_hub"]
        self.background = self.write(
            "background.json",
            {
                "receipts": [
                    {
                        "command": self.prefix + ["search"],
                        "executable_sha256": sha(Path(sys.executable).read_bytes()),
                        "research_hub_package_sha256": "e" * 64,
                        "status": "results",
                    }
                ],
                "sources": [{"source_id": "independent-source"}],
            },
        )
        self.policy = execution_policy()
        confirmed = brief("specified", "user-chosen region")
        self.lock = {
            "kind": "Stage1ABPublicLockV3",
            "schema_version": "3.1.0",
            "execution_class": "formal",
            "evaluator_execution_policy": self.policy,
            "evaluator_bundle_sha256": self.policy["evaluator_bundle_sha256"],
            "spec_sha256": sha(canonical(self.spec)),
            "task_sha256": self.spec["task_sha256"],
            "prompt_sha256": sha(self.task.read_bytes()),
            "rubric_sha256": self.spec["rubric_sha256"],
            "background_sha256": sha(self.background.read_bytes()),
            "evaluator_runtime": {"model": "gpt-5.6-sol", "reasoning": "high"},
            "codex_runtime_sha256": "c" * 64,
            "codex_executable_sha256": sha(self.codex.read_bytes()),
            "plugin_tree_sha256": "f" * 64,
            "paired_repeats": runs(),
            "research_brief": confirmed,
            "research_brief_sha256": sha(canonical(confirmed)),
            "evaluator_research_hub_repo_path": str(self.root),
            "evaluator_research_hub_sha": "1" * 40,
            "research_hub_sha": runner.RESEARCH_HUB_SHA,
            "research_hub_package_sha256": "e" * 64,
            "hub_command_prefix": self.prefix,
            "hub_executable_sha256": sha(Path(sys.executable).read_bytes()),
        }
        self.lock_path = self.write("lock.json", self.lock)
        self.capture = self.root / "capture"
        self.capture.mkdir()
        for name in ("run.json", "attempt-01.final.txt", "attempt-01.jsonl"):
            (self.capture / name).write_bytes(b"capture")
        self.record = {
            "lock_kind": "Stage1ABPublicLockV3",
            "run_id": "a-1",
            "condition": "baseline",
            "repeat": 1,
            "series_id": "series-a",
            "lock_sha256": sha(self.lock_path.read_bytes()),
            "status": "complete",
            "attempts": [{}],
        }
        self.args = SimpleNamespace(
            execution_class="formal",
            portable_diagnostic=False,
            lock=str(self.lock_path),
            capture=str(self.capture),
            background=str(self.background),
            task=str(self.task),
            codex=str(self.codex),
            model="gpt-5.6-sol",
            reasoning="high",
            mode="evidence-audited",
        )

    def write(self, name, value):
        path = self.root / name
        path.write_bytes(canonical(value))
        return path

    def binding(self):
        with (
            patch.object(runner, "codex_runtime_sha", return_value="c" * 64),
            patch.object(runner, "tree_sha", return_value="f" * 64),
            patch(
                "stage1_eval.formal.verify_installed_from_commit",
                return_value={"python_source_sha256": "e" * 64},
            ),
        ):
            return verify_binding_v31(self.args, self.spec, self.record, self.policy)

    def test_binding_keeps_subject_and_evaluator_dependencies_distinct(self):
        binding = self.binding()
        self.assertEqual(binding["subject_research_hub_sha"], runner.RESEARCH_HUB_SHA)
        self.assertEqual(binding["evaluator_research_hub_sha"], "1" * 40)
        self.assertEqual(binding["answer_sha256"], sha(b"capture"))

    def real_capture(self, *, kind="Stage1ABPublicLockV3", bind_final=True):
        events = [
            {"type": "thread.started", "thread_id": "t"},
            {
                "type": "item.completed",
                "item": {"type": "agent_message", "text": "Original native answer"},
            },
            {"type": "turn.completed", "usage": {}},
        ]
        raw = b"".join(canonical(e) + b"\n" for e in events)
        final = (
            b"Original native answer"
            if bind_final
            else b"Unrecorded replacement answer"
        )
        (self.capture / "attempt-01.jsonl").write_bytes(raw)
        (self.capture / "attempt-01.final.txt").write_bytes(final)
        files = {"attempt-01.jsonl": sha(raw)}
        if bind_final:
            files["attempt-01.final.txt"] = sha(final)
        self.record.update(
            execution_policy=runner.SUBJECT_EXECUTION_POLICY,
            profile_probe={
                "plugin_names": []
                if kind == "Stage1ABPublicLockV3"
                else ["auto-research-agent"]
            },
            attempts=[{"files": files, "summary": runner._event_summary(raw)}],
        )
        if kind is None:
            self.record.pop("lock_kind", None)
        else:
            self.record["lock_kind"] = kind
        if kind == "Stage1ABPublicLockV3":
            lock_raw = self.lock_path.read_bytes()
            preflight = canonical(
                {
                    "valid": True,
                    "lock_sha256": sha(lock_raw),
                    "plugin_tree_sha256": self.lock["plugin_tree_sha256"],
                    "probes": {"baseline": self.record["profile_probe"]},
                }
            )
            for name, data in (
                ("attempt-01.lock.json", lock_raw),
                ("attempt-01.preflight.json", preflight),
            ):
                (self.capture / name).write_bytes(data)
                files[name] = sha(data)
            self.record["preflight_sha256"] = sha(preflight)
        (self.capture / "run.json").write_bytes(canonical(self.record))
        return self.capture

    def test_live_binding_and_pairing_reject_missing_or_legacy_capture_kind(self):
        for kind in (None, "Stage1ABPublicLock"):
            with self.subTest(kind=kind):
                capture = self.real_capture(kind=kind)
                _, self.record = capture_subject(capture, verify_runtime=True)
                with self.assertRaisesRegex(
                    EvaluationError, "frozen evaluation binding"
                ):
                    self.binding()
                with (
                    patch.object(runner, "tree_sha", return_value="f" * 64),
                    patch.object(general_v31, "_replay_result") as replay,
                ):
                    with self.assertRaisesRegex(
                        runner.ExecutionBlocked, "capture is incomplete"
                    ):
                        general_v31.paired_v31(
                            self.lock_path,
                            self.background,
                            [self.root / "unused.json"] * 6,
                            [capture] * 6,
                            self.root / "decision.json",
                        )
                    replay.assert_not_called()

    def test_real_capture_requires_final_answer_membership_before_adaptation(self):
        capture = self.real_capture(bind_final=False)
        # The low-level replay validates the listed bytes; v3.1 must additionally
        # require the selected final file, even if the manifest omitted it.
        runner.verify_capture(capture, verify_runtime=True)
        with self.assertRaisesRegex(
            EvaluationError, "final answer.*capture byte manifest"
        ):
            capture_subject(capture, verify_runtime=True)

    def test_changed_scope_version_runtime_or_package_cannot_be_rehashed_into_a_binding(
        self,
    ):
        for key, value in (
            ("research_brief_sha256", "0" * 64),
            ("hub_executable_sha256", "0" * 64),
            ("research_hub_package_sha256", "0" * 64),
            ("plugin_tree_sha256", "0" * 64),
        ):
            changed = dict(self.lock)
            changed[key] = value
            self.write("lock.json", changed)
            self.record["lock_sha256"] = sha(self.lock_path.read_bytes())
            with self.subTest(key=key), self.assertRaises(EvaluationError):
                self.binding()

    def test_portable_replay_is_never_formal_attestation(self):
        self.args.portable_diagnostic = True
        with self.assertRaisesRegex(EvaluationError, "portable"):
            self.binding()

    def test_freeze_requires_and_embeds_confirmed_brief_with_native_search_policy(self):
        probe = self.write(
            "probe.json",
            {
                "model": "gpt-5.6-sol",
                "reasoning": "high",
                "codex_version": "test-cli",
                "native_web_search": True,
                "native_capabilities": {"web": True},
                "native_capabilities_sha256": sha(
                    json.dumps({"web": True}, sort_keys=True).encode()
                ),
            },
        )
        pins = [self.write(f"pin-{i}.json", {}) for i in range(3)]
        confirmed = self.write("brief.json", self.lock["research_brief"])
        with (
            patch.object(general, "_verify_background"),
            patch.object(
                general,
                "verify_installed_from_commit",
                return_value={"python_source_sha256": "e" * 64},
            ),
            patch.object(
                general.subprocess,
                "run",
                return_value=SimpleNamespace(stdout=runner.RESEARCH_HUB_SHA),
            ),
            patch.object(
                runner,
                "_runtime_pin",
                side_effect=lambda p: ({}, sha(Path(p).read_bytes())),
            ),
            patch.object(runner, "codex_runtime_sha", return_value="c" * 64),
            patch.object(runner, "tree_sha", return_value="f" * 64),
        ):
            args = (
                self.codex,
                self.task,
                self.write("spec.json", self.spec),
                self.background,
                self.task,
                probe,
                self.root,
                pins,
                self.root / "frozen.json",
            )
            with self.assertRaisesRegex(runner.ExecutionBlocked, "confirmed brief"):
                general.freeze_v3(*args, evaluator_dependency_repo=self.root)
            frozen = general.freeze_v3(
                *args,
                evaluator_dependency_repo=self.root,
                evaluator_dependency_sha="1" * 40,
                research_brief_path=confirmed,
            )
        self.assertEqual(frozen["schema_version"], "3.1.0")
        self.assertEqual(frozen["search_observation_policy"], "native-or-cli")
        self.assertEqual(
            frozen["research_brief_sha256"], sha(canonical(self.lock["research_brief"]))
        )
        self.assertNotIn("holdout", str(frozen.keys()))

    def test_pairing_rejects_wrong_count_before_any_model_replay(self):
        with (
            patch.object(runner, "tree_sha", return_value="f" * 64),
            patch.object(general_v31, "_replay_result") as replay,
            self.assertRaisesRegex(runner.ExecutionBlocked, "exactly six"),
        ):
            general_v31.paired_v31(
                self.lock_path, self.background, [], [], self.root / "decision.json"
            )
        replay.assert_not_called()


if __name__ == "__main__":
    unittest.main()
