"""Synthetic planning calls test mechanics, never scientific improvement."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

PLUGIN = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(PLUGIN / "cli"), str(PLUGIN / "tests")]
from stage3_plan.contracts import Stage3Error, canonical_bytes  # noqa: E402
from stage3_plan.intake import admit_intake, project_intake  # noqa: E402
from stage3_plan.native import NativePlanner  # noqa: E402
from stage3_plan.planner import draft_synthetic_plan as draft_plan  # noqa: E402
from stage3_plan.storage import inspect_package  # noqa: E402
from stage3_plan_fixtures import make_intake, make_plan  # noqa: E402


class Stage3GenerationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.plan = make_plan()
        self.intake = make_intake(self.plan)
        self.config = {"model": "synthetic-model", "reasoning": "medium"}
        self.calls = []

    def callback(self, **request):
        self.calls.append(request)
        return {
            "raw_response": canonical_bytes(self.plan),
            "provenance": {
                "kind": "synthetic-injected-callback",
                "execution_authorized": False,
            },
        }

    def draft(self, **kwargs):
        return draft_plan(
            self.intake,
            self.root / "plan",
            self.callback,
            configuration=self.config,
            plan_id=self.plan["plan_id"],
            **kwargs,
        )

    def test_actual_callback_varies_with_admitted_direction(self):
        procedures = []
        for index, topic in enumerate(
            ("numeric", "observational", "qualitative", "theory")
        ):
            self.plan = make_plan(topic, index + 1, shared_path=True)
            self.intake = make_intake(self.plan)
            saved = draft_plan(
                self.intake,
                self.root / topic,
                self.callback,
                configuration=self.config,
                plan_id=self.plan["plan_id"],
            )
            actual = saved["artifacts"]["plan.json"]
            self.assertEqual(actual, self.plan)
            self.assertIn(self.plan["questions"][0]["text"], self.calls[-1]["prompt"])
            procedures.append(actual["designs"][0]["procedure"])
            self.assertFalse(saved["manifest"]["execution_authorized"])
        self.assertEqual(len(self.calls), 4)
        self.assertEqual(len(set(procedures)), 4)

    def test_resume_no_reexecution_and_changed_inputs_reject(self):
        saved = self.draft()
        sha = saved["manifest"]["manifest_sha256"]
        replay = self.draft(resume_manifest_sha256=sha)
        self.assertEqual(replay["resume_action"], "verified-replay-no-generation")
        self.assertEqual(len(self.calls), 1)
        self.intake["unresolved"] = ["A newly changed access condition."]
        with self.assertRaisesRegex(Stage3Error, "changed"):
            self.draft(resume_manifest_sha256=sha)
        self.assertEqual(len(self.calls), 1)

    def test_invalid_response_and_failure_remain_inspectable(self):
        for index, response in enumerate(
            (b"invalid JSON", b'{"execution_authorized":true}')
        ):
            target = self.root / str(index)
            callback = Mock(
                request_context={"kind": "synthetic-injected-callback"},
                return_value={
                    "raw_response": response,
                    "provenance": {"kind": "synthetic"},
                },
            )
            with self.assertRaisesRegex(Stage3Error, "retained"):
                draft_plan(
                    self.intake,
                    target,
                    callback,
                    configuration=self.config,
                    plan_id=self.plan["plan_id"],
                )
            manifest = json.loads((target / "manifest.json").read_bytes())
            saved = inspect_package(target, manifest["manifest_sha256"])
            self.assertEqual(saved["manifest"]["state"], "failed")
            self.assertIn("failure.json", saved["artifacts"])
            self.assertEqual((target / "raw-response.json").read_bytes(), response)
            self.assertEqual(callback.call_count, 1)

    def test_callback_exception_is_not_empty_success_or_retry(self):
        callback = Mock(
            request_context={"kind": "synthetic-injected-callback"},
            side_effect=RuntimeError("synthetic transport failure"),
        )
        target = self.root / "failed"
        with self.assertRaisesRegex(Stage3Error, "synthetic transport failure"):
            draft_plan(
                self.intake,
                target,
                callback,
                configuration=self.config,
                plan_id=self.plan["plan_id"],
            )
        self.assertEqual(callback.call_count, 1)
        self.assertEqual(
            json.loads((target / "failure.json").read_bytes())["error_class"],
            "RuntimeError",
        )
        with self.assertRaisesRegex(Stage3Error, "exists"):
            draft_plan(
                self.intake,
                target,
                callback,
                configuration=self.config,
                plan_id=self.plan["plan_id"],
            )
        self.assertEqual(callback.call_count, 1)

    def test_manifest_external_pin_and_artifact_producer_bound(self):
        saved = self.draft()
        target = self.root / "plan"
        with self.assertRaises(Stage3Error):
            inspect_package(target, "b" * 64)
        (target / "plan.json").write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(Stage3Error, "hash mismatch"):
            inspect_package(target, saved["manifest"]["manifest_sha256"])

    def test_runtime_bytes_bound(self):
        saved = self.draft()
        producer = saved["artifacts"]["request.json"]["producer_sha256"]
        self.assertEqual(len(producer), 64)
        original = Path.read_bytes

        def changed_dependency(path):
            if path.name == "model_calls.py":
                return b"synthetic changed native dependency bytes"
            return original(path)

        with patch.object(Path, "read_bytes", changed_dependency):
            with self.assertRaises(Stage3Error):
                self.draft(resume_manifest_sha256=saved["manifest"]["manifest_sha256"])

    def test_native_adapter_preserves_configuration_and_stage3_identity(self):
        adapter = NativePlanner(
            codex="host-codex",
            codex_home=self.root / "home",
            capture_dir=self.root / "native",
            timeout_seconds=30,
        )
        with patch(
            "stage1_eval.model_calls.call_model_v31",
            return_value=(self.plan, {"original": "primitive"}),
        ) as call:
            response = adapter(
                prompt="Synthetic planning context",
                schema_path=PLUGIN / "schemas/stage3-research-plan.v1.schema.json",
                output_dir=self.root / "output",
                configuration=self.config,
            )
        self.assertEqual(call.call_count, 1)
        self.assertEqual(call.call_args.kwargs["model"], self.config["model"])
        self.assertEqual(
            call.call_args.kwargs["execution_policy"][
                "max_transient_transport_retries"
            ],
            0,
        )
        self.assertEqual(call.call_args.kwargs["execution_policy"]["tools"], "none")
        self.assertFalse(call.call_args.kwargs["resume_verified"])
        self.assertEqual(
            response["provenance"]["operation"], "stage3.scientific-plan.v1"
        )
        self.assertEqual(
            response["provenance"]["primitive_provenance"], {"original": "primitive"}
        )

    def test_native_archive_replays_and_rejects_tamper_without_process(self):
        home = self.root / "isolated-home"
        home.mkdir()
        adapter = NativePlanner(
            codex=sys.executable,
            codex_home=home,
            capture_dir=self.root / "native-archive",
            timeout_seconds=30,
        )

        def synthetic_process(command, **kwargs):
            Path(command[command.index("-o") + 1]).write_bytes(
                canonical_bytes(self.plan)
            )
            self.assertIn("--ignore-user-config", command)
            self.assertIn("shell_tool", command)
            self.assertIn("multi_agent", command)
            self.assertIn('web_search="disabled"', command)
            self.assertIn('approval_policy="never"', command)
            events = [
                {
                    "type": "item.completed",
                    "item": {
                        "type": "agent_message",
                        "text": canonical_bytes(self.plan).decode(),
                    },
                },
                {"type": "turn.completed"},
            ]
            return subprocess.CompletedProcess(
                command, 0, b"\n".join(canonical_bytes(e) for e in events), b""
            )

        with patch(
            "stage1_eval.model_calls._execute_bound_process",
            side_effect=synthetic_process,
        ) as process:
            saved = draft_plan(
                self.intake,
                self.root / "native-plan",
                adapter,
                configuration=self.config,
                plan_id=self.plan["plan_id"],
            )
            replay = inspect_package(
                self.root / "native-plan", saved["manifest"]["manifest_sha256"]
            )
            self.assertEqual(replay["artifacts"]["plan.json"], self.plan)
            self.assertEqual(process.call_count, 1)
            archive = self.root / "native-archive/stage3-plan.model-call"
            record = json.loads(
                next(archive.glob("attempt-*.record.json")).read_bytes()
            )
            (archive / record["files"]["stdout"]["path"]).write_bytes(b"tampered")
            with self.assertRaises(Exception):
                inspect_package(
                    self.root / "native-plan", saved["manifest"]["manifest_sha256"]
                )
            self.assertEqual(process.call_count, 1)

    def test_legacy_or_advice_cannot_be_promoted_by_planner(self):
        self.intake["legacy_candidates"] = [{"reason": "legacy-unstructured"}]
        with self.assertRaisesRegex(Stage3Error, "legacy"):
            self.draft()
        self.assertEqual(self.calls, [])
        with self.assertRaises(Stage3Error):
            project_intake(
                {
                    "execution_authorized": False,
                    "decision": {"kind": "pending", "selected": []},
                },
                "a" * 64,
            )
        bogus = self.root / "transport"
        bogus.mkdir()
        (bogus / "MANIFEST.json").write_text("{}", encoding="utf-8")
        with self.assertRaises(Exception):
            admit_intake(bogus, bogus, expected_manifest_sha256="a" * 64)

    def test_public_draft_cannot_accept_a_projected_dict_as_admission(self):
        from stage3_plan.planner import draft_plan as selected_draft

        callback = Mock(request_context={"kind": "synthetic"})
        with self.assertRaises((TypeError, ValueError)):
            selected_draft(
                self.intake,
                self.root,
                expected_manifest_sha256="a" * 64,
                output_dir=self.root / "unadmitted",
                callback=callback,
                configuration=self.config,
                plan_id=self.plan["plan_id"],
            )
        self.assertEqual(callback.call_count, 0)
        saved = self.draft()
        self.assertEqual(
            saved["artifacts"]["request.json"]["admission_scope"], "synthetic-test"
        )


if __name__ == "__main__":
    unittest.main()
