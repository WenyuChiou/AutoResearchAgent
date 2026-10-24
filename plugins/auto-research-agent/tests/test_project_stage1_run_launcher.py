"""Original driver uses actual owner queue, Core and SQLite; authored model output only."""

import contextlib
import io
import time
import json
from pathlib import Path
import runpy
import tempfile
from hashlib import sha256
from types import MethodType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import test_project_stage1_run_grant as grant_cases

from analysis_run_fixture import analysis_run_fixture
from research_workspace_native.project_host import ProjectHost
from research_workspace_native.project_records_prepare import (
    ProjectRecordsPrepareService,
)
from research_workspace_native.project_stage1_run_grant import (
    ProjectStage1RunGrantService,
    STORE,
)
from research_workspace_native.session_api import SessionApiError


class WholeRunContinuationTests(unittest.TestCase):
    def test_original_host_continues_saved_model_adoption_and_registry_once(self):
        with analysis_run_fixture() as run:
            host = SimpleNamespace(
                projects=run.case.intake,
                project_stage1=run.case.delivery.stage1,
                project_models=run.model,
                project_stage2=None,
                project_stage1_delivery=run.case.delivery,
                project_records_prepare=ProjectRecordsPrepareService(run.case.producer),
                project_stage1_records=run.case.producer,
                project_stage1_sources=None,
                project_expansions=None,
                project_stage1_source_dispatcher=None,
            )
            for name in ("overview", "stage1_view", "continue_stage1"):
                setattr(host, name, MethodType(getattr(ProjectHost, name), host))
            clock = SimpleNamespace(now=1_900_000_000)
            issuer = ProjectStage1RunGrantService(
                run.case.intake, runtime_sha256="a" * 64, clock=lambda: clock.now
            )
            grant_ref, row = next(
                iter(run.case.intake._load("alice", run.ref)[STORE].items())
            )
            calls = len(run.calls)

            def advance():
                return host.continue_stage1(
                    "alice-token",
                    run.ref,
                    run_id="saved-whole-run",
                    deadline=time.monotonic() + 90,
                    max_actions=1,
                    run_grants=issuer,
                    grant_ref=grant_ref,
                    grant_sha256=row["sha256"],
                )

            launcher = runpy.run_path(
                str(
                    Path(__file__).resolve().parents[1]
                    / "references/research-workspace/examples/run-project-workspace.py"
                )
            )
            with tempfile.TemporaryDirectory(prefix="s1-run-request-") as directory:
                request_path = Path(directory).resolve() / "request.json"
                request = dict(
                    kind="ProjectStage1RunRequest",
                    schema_version="1.0.0",
                    project_ref=run.ref,
                    run_id="saved-whole-run",
                    slice_max_actions=1,
                    resume=dict(grant_ref=grant_ref, grant_sha256=row["sha256"]),
                )
                raw = json.dumps(request).encode()
                request_path.write_bytes(raw)
                args = SimpleNamespace(
                    stage1_run_request=request_path,
                    stage1_run_request_sha256=sha256(raw).hexdigest(),
                )
                services = dict(
                    stage1_run_grants=issuer,
                    projects=run.case.intake,
                    credential="alice-token",
                )
                first = launcher["run_requested_stage1"](args, host, services)["result"]
                history = run.case.intake.history("alice-token", run.ref)
                for cap in (True, 0, row["document"]["max_actions"] + 1):
                    request["slice_max_actions"] = cap
                    raw = json.dumps(request).encode()
                    request_path.write_bytes(raw)
                    args.stage1_run_request_sha256 = sha256(raw).hexdigest()
                    with self.assertRaisesRegex(ValueError, "cannot expand"):
                        launcher["run_requested_stage1"](args, host, services)
                self.assertEqual(
                    history, run.case.intake.history("alice-token", run.ref)
                )
                request_path.write_bytes(raw + b"\n")
                with self.assertRaisesRegex(ValueError, "changed"):
                    launcher["run_requested_stage1"](args, host, services)
            self.assertEqual(first["action_count"], 1, first)
            self.assertEqual(first["actions"][0]["status"], "saved", first)
            self.assertEqual(first["actions"][0]["kind"], "reading", first)
            self.assertEqual(
                run.case.intake.action(
                    "alice-token", first["actions"][0]["key"], project_ref=run.ref
                )["kind"],
                "stage1-agent-analysis",
                first,
            )
            second = advance()
            self.assertEqual(second["action_count"], 1, second)
            self.assertEqual(second["actions"][0]["status"], "saved", second)
            self.assertTrue(
                second["actions"][0]["key"].startswith("stage1-reading-registry-")
            )
            self.assertEqual(len(run.calls), calls)
            self.assertNotEqual(first["actions"][0]["key"], second["actions"][0]["key"])
            self.assertFalse(second["stage1_complete"])
            self.assertFalse(second["stage2_started"])
            history = run.case.intake.history("alice-token", run.ref)
            clock.now = row["document"]["expires_at"]
            with self.assertRaises(SessionApiError):
                advance()
            self.assertEqual(history, run.case.intake.history("alice-token", run.ref))
            self.assertEqual(len(run.calls), calls)


class LauncherBoundaryTests(unittest.TestCase):
    def test_invalid_new_slice_does_not_persist_authority(self):
        launcher = runpy.run_path(
            str(
                Path(__file__).resolve().parents[1]
                / "references/research-workspace/examples/run-project-workspace.py"
            )
        )
        host = SimpleNamespace(
            continue_stage1=Mock(side_effect=AssertionError("execution forbidden"))
        )
        for index, cap in enumerate((True, 0, 5)):
            with self.subTest(cap=cap):
                case = grant_cases.RunGrantTests(
                    "test_budget_alone_is_not_whole_run_authority"
                )
                case.setUp()
                self.addCleanup(case.doCleanups)
                services = dict(
                    stage1_run_grants=case.service,
                    projects=case.intake,
                    credential="alice-token",
                )
                request = dict(
                    kind="ProjectStage1RunRequest",
                    schema_version="1.0.0",
                    project_ref=case.ref,
                    run_id="red-cap",
                    slice_max_actions=cap,
                    authorization=case.body(key="invalid-cap-" + str(index)),
                )
                raw = json.dumps(request).encode()
                path = case.root / ("cap-" + str(index) + ".json")
                path.write_bytes(raw)
                args = SimpleNamespace(
                    stage1_run_request=path,
                    stage1_run_request_sha256=sha256(raw).hexdigest(),
                )
                history = case.intake.history("alice-token", case.ref)
                state = case.intake._load("alice", case.ref)
                with self.assertRaisesRegex(ValueError, "cannot expand"):
                    launcher["run_requested_stage1"](args, host, services)
                self.assertEqual(history, case.intake.history("alice-token", case.ref))
                self.assertEqual(state, case.intake._load("alice", case.ref))
        host.continue_stage1.assert_not_called()

    def test_interrupted_run_exits_partial_and_closes_once(self):
        directory = tempfile.TemporaryDirectory(prefix="launcher-interrupted-")
        self.addCleanup(directory.cleanup)
        root = Path(directory.name).resolve()
        for explicit, expected in ((True, 2), (False, 0)):
            with self.subTest(explicit=explicit):
                launcher = runpy.run_path(
                    str(
                        Path(__file__).resolve().parents[1]
                        / "references/research-workspace/examples/run-project-workspace.py"
                    )
                )
                host = Mock(expected_origin="http://127.0.0.1:1")
                host.serve_forever.side_effect = KeyboardInterrupt
                services = {
                    key: Mock()
                    for key in (
                        "projects",
                        "models",
                        "stage1",
                        "stage2",
                        "files",
                        "views",
                    )
                }
                services.update(
                    credential="alice-token",
                    stage1_materials_root=None,
                    stage1_sources=None,
                    stage1_source_dispatcher=None,
                    host_type=Mock(return_value=host),
                )
                replacements = dict(
                    inspect_inputs=Mock(
                        return_value=dict(
                            query_runtime=None, stage1_materials_root=None
                        )
                    ),
                    install_source=Mock(return_value=(None, {})),
                    prepare=Mock(return_value=services),
                    run_requested_stage1=Mock(side_effect=KeyboardInterrupt),
                )
                argv = [
                    "--source-helper-sha256",
                    "a" * 64,
                    "--projects-root",
                    str(root),
                ]
                if explicit:
                    argv += [
                        "--stage1-run-request",
                        str(root / "request.json"),
                        "--stage1-run-request-sha256",
                        "b" * 64,
                    ]
                with (
                    patch.dict(launcher["main"].__globals__, replacements),
                    contextlib.redirect_stdout(io.StringIO()),
                ):
                    result = launcher["main"](argv)
                self.assertEqual(result, expected)
                host.server_close.assert_called_once_with()
                services["models"].close.assert_called_once_with()
                services["projects"].close.assert_called_once_with()
                if not explicit:
                    replacements["run_requested_stage1"].assert_not_called()


if __name__ == "__main__":
    unittest.main()
