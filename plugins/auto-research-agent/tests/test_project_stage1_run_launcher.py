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


class FullSourceLauncherTests(unittest.TestCase):
    """Launcher wiring only; model/provider/HTTP execution stays stubbed."""

    def launcher(self):
        return runpy.run_path(
            str(
                Path(__file__).resolve().parents[1]
                / "references/research-workspace/examples/run-project-workspace.py"
            )
        )

    def grant_case(self):
        case = grant_cases.RunGrantTests("test_budget_alone_is_not_whole_run_authority")
        case.setUp()
        self.addCleanup(case.doCleanups)
        return case

    def request_args(self, case, request, *, enabled=True):
        path = case.root / "full-source-request.json"
        raw = json.dumps(request).encode()
        path.write_bytes(raw)
        notes = case.root / "notes"
        notes.mkdir(exist_ok=True)
        return SimpleNamespace(
            stage1_run_request=path,
            stage1_run_request_sha256=sha256(raw).hexdigest(),
            enable_stage1_full_source=enabled,
            stage1_full_notes_root=notes if enabled else None,
        )

    def test_full_source_registration_precedes_continuation_and_reuses_resume(self):
        launcher, case = self.launcher(), self.grant_case()
        services = dict(
            stage1_run_grants=case.service,
            projects=case.intake,
            credential="alice-token",
        )
        request = dict(
            kind="ProjectStage1RunRequest",
            schema_version="1.0.0",
            project_ref=case.ref,
            run_id="full-source-launcher",
            slice_max_actions=1,
            authorization=case.body(key="authored-full-source-launcher"),
        )
        original_grant = None
        for enabled in (True, True, False):
            with self.subTest(enabled=enabled, resume="resume" in request):
                events = []
                host = SimpleNamespace(
                    register_stage1_full_source=Mock(
                        side_effect=lambda *a, **kw: events.append(("register", a, kw))
                    ),
                    continue_stage1=Mock(
                        side_effect=lambda *a, **kw: (
                            events.append(("continue", a, kw))
                            or {"status": "partial", "stage2_started": False}
                        )
                    ),
                )
                args = self.request_args(case, request, enabled=enabled)
                receipt = launcher["run_requested_stage1"](args, host, services)
                self.assertEqual(
                    [event[0] for event in events],
                    ["register", "continue"] if enabled else ["continue"],
                )
                grant = dict(
                    grant_ref=receipt["grant_ref"],
                    grant_sha256=receipt["grant_sha256"],
                )
                if original_grant is None:
                    original_grant = grant
                self.assertEqual(grant, original_grant)
                continuation = events[-1][2]
                self.assertIs(continuation["run_grants"], case.service)
                self.assertEqual(continuation["max_actions"], 1)
                self.assertEqual({k: continuation[k] for k in grant}, original_grant)
                self.assertGreater(continuation["deadline"] - time.monotonic(), 0)
                document = case.inspect(grant)
                self.assertLessEqual(
                    continuation["deadline"] - time.monotonic(),
                    document["expires_at"] - case.service._now(),
                )
                if enabled:
                    self.assertEqual(events[0][1], ("alice-token", case.ref))
                    self.assertEqual(
                        events[0][2],
                        dict(
                            run_grants=case.service,
                            **original_grant,
                            output_root=args.stage1_full_notes_root,
                        ),
                    )
                else:
                    host.register_stage1_full_source.assert_not_called()
                self.assertEqual(len(case.intake._load("alice", case.ref)[STORE]), 1)
                request.pop("authorization", None)
                request["resume"] = original_grant

    def test_full_source_registration_failure_never_continues(self):
        launcher, case = self.launcher(), self.grant_case()
        grant = case.authorize(key="authored-full-source-refusal")
        request = dict(
            kind="ProjectStage1RunRequest",
            schema_version="1.0.0",
            project_ref=case.ref,
            run_id="full-source-refusal",
            resume=dict(
                grant_ref=grant["grant_ref"],
                grant_sha256=grant["grant_sha256"],
            ),
        )
        args = self.request_args(case, request)
        host = SimpleNamespace(
            register_stage1_full_source=Mock(
                side_effect=ValueError("authored registration refused")
            ),
            continue_stage1=Mock(side_effect=AssertionError("continuation forbidden")),
        )
        history = case.intake.history("alice-token", case.ref)
        with self.assertRaisesRegex(ValueError, "registration refused"):
            launcher["run_requested_stage1"](
                args,
                host,
                dict(
                    stage1_run_grants=case.service,
                    projects=case.intake,
                    credential="alice-token",
                ),
            )
        host.continue_stage1.assert_not_called()
        self.assertEqual(history, case.intake.history("alice-token", case.ref))

    def test_full_source_saved_run_registers_real_adapter_before_budget_stop(self):
        import test_project_stage1_full_source_adapter as adapter_cases

        fixture = adapter_cases.FullSourceAdapterTests(
            "test_insufficient_remaining_calls_saves_partial_without_permission_or_dispatch"
        )
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        with fixture.case(calls=1) as run:
            host = SimpleNamespace(**vars(run.host))
            del host.project_stage1_full_source_execution
            host.host_binding = dict(run.host.host_binding)
            host._assets = dict(run.host._assets)
            for name in (
                "overview",
                "stage1_view",
                "continue_stage1",
                "register_stage1_full_source",
            ):
                setattr(host, name, MethodType(getattr(ProjectHost, name), host))
            request = dict(
                kind="ProjectStage1RunRequest",
                schema_version="1.0.0",
                project_ref=run.ref,
                run_id="real-full-source-launcher-budget-stop",
                slice_max_actions=1,
                resume=dict(
                    grant_ref=run.grant["grant_ref"],
                    grant_sha256=run.grant["grant_sha256"],
                ),
            )
            raw = json.dumps(request).encode()
            path = fixture.root / "full-source-launcher-request.json"
            path.write_bytes(raw)
            args = SimpleNamespace(
                stage1_run_request=path,
                stage1_run_request_sha256=sha256(raw).hexdigest(),
                enable_stage1_full_source=True,
                stage1_full_notes_root=run.output,
            )
            before = run.case.intake.history("alice-token", run.ref)
            receipt = self.launcher()["run_requested_stage1"](
                args,
                host,
                dict(
                    stage1_run_grants=run.issuer,
                    projects=run.case.intake,
                    credential="alice-token",
                ),
            )
            self.assertIsNot(host.project_stage1_full_source_execution, run.adapter)
            self.assertEqual(receipt["grant_sha256"], run.grant["grant_sha256"])
            result = receipt["result"]
            self.assertEqual(result["status"], "partial", result)
            self.assertEqual(
                result["reason"], "remaining-model-call-budget-insufficient"
            )
            self.assertFalse(result["stage1_complete"])
            self.assertEqual(fixture.assertions, [])
            self.assertEqual(before, run.case.intake.history("alice-token", run.ref))

    def test_full_source_launcher_registers_included_work_with_coverage(self):
        from copy import deepcopy
        import test_project_agent_coverage as coverage_cases
        from research_workspace_native.project_stage1_full_source import (
            ProjectStage1FullSourceAdapter,
        )

        captured = {}
        original = ProjectStage1RunGrantService.authorize

        def authorize(issuer, credential, ref, body):
            body = deepcopy(body)
            body["operations"].append("analyze-full-paper")
            grant = original(issuer, credential, ref, body)
            captured.update(issuer=issuer, grant=grant)
            return grant

        with (
            patch.object(ProjectStage1RunGrantService, "authorize", new=authorize),
            coverage_cases.agent_coverage_run() as run,
            tempfile.TemporaryDirectory(prefix="launcher-included-notes-") as directory,
        ):
            issuer, grant = captured["issuer"], captured["grant"]
            run.model.run_grants = issuer
            self.assertTrue(run.model.analysis_coverage)
            helper = coverage_cases.AgentCoverageTests("runTest")
            helper._adopt(run)
            self.assertNotIn(run.work, run.ledger.coverage_state().evidence.current())
            host = SimpleNamespace(
                projects=run.case.intake,
                project_stage1=run.case.delivery.stage1,
                project_models=run.model,
                project_stage2=None,
                project_stage1_delivery=run.case.delivery,
                project_stage1_records=run.case.producer,
                project_records_prepare=ProjectRecordsPrepareService(run.case.producer),
                project_stage1_sources=None,
                project_expansions=None,
                project_stage1_source_dispatcher=None,
                host_binding={},
                _assets={},
            )
            for name in (
                "overview",
                "stage1_view",
                "continue_stage1",
                "register_stage1_full_source",
            ):
                setattr(host, name, MethodType(getattr(ProjectHost, name), host))
            notes = Path(directory).resolve()
            request = dict(
                kind="ProjectStage1RunRequest",
                schema_version="1.0.0",
                project_ref=run.ref,
                run_id="included-full-source-launcher",
                slice_max_actions=2,
                resume=dict(
                    grant_ref=grant["grant_ref"],
                    grant_sha256=grant["grant_sha256"],
                ),
            )
            raw = json.dumps(request).encode()
            request_path = notes / "request.json"
            request_path.write_bytes(raw)
            args = SimpleNamespace(
                stage1_run_request=request_path,
                stage1_run_request_sha256=sha256(raw).hexdigest(),
                enable_stage1_full_source=True,
                stage1_full_notes_root=notes,
            )
            before_calls = len(run.calls)
            receipt = self.launcher()["run_requested_stage1"](
                args,
                host,
                dict(
                    stage1_run_grants=issuer,
                    projects=run.case.intake,
                    credential="alice-token",
                ),
            )
            adapter = host.project_stage1_full_source_execution
            self.assertIsInstance(adapter, ProjectStage1FullSourceAdapter)
            progress = adapter.read("alice-token", run.ref)
            row = next(
                item
                for item in progress["automatically_recorded"]
                if item["work_id"] == run.work
            )
            self.assertTrue(row["reading_registration_complete"], receipt)
            self.assertIn(run.work, run.ledger.coverage_state().evidence.current())
            self.assertFalse(row["human_acceptance"])
            self.assertFalse(row["scientific_acceptance"])
            note_row = next(
                item for item in progress["notes"] if item["work_id"] == run.work
            )
            note = adapter.note_by_hash("alice-token", run.ref, note_row["sha256"])
            self.assertEqual(sha256(note["text"].encode()).hexdigest(), note["sha256"])
            self.assertIn('"decision": "include"', note["text"])
            self.assertEqual(len(run.calls), before_calls)
            self.assertFalse(receipt["result"]["stage2_started"])

    def test_full_source_prepare_preserves_coverage_capable_analysis(self):
        launcher = self.launcher()

        class StopBeforeServices(Exception):
            pass

        for full_source, expected in ((False, True), (True, True)):
            with self.subTest(full_source=full_source):
                projects, issuer, factory = Mock(), Mock(), Mock()
                observed = {}

                def model_service(*args, **kwargs):
                    observed.update(kwargs)
                    raise StopBeforeServices

                args = SimpleNamespace(
                    views_config=None,
                    views_sha256=None,
                    enable_stage1_run=True,
                    enable_stage1_full_source=full_source,
                    enable_content_model=True,
                    enable_public_sources=True,
                    model="authored-no-provider-call",
                    model_cap_seconds=30,
                )
                checked = dict(
                    root=Path("authored-unopened-projects"),
                    repo=Path("authored-unopened-source"),
                    executable=Path("authored-unexecuted-codex"),
                    user_config=Path("authored-unread-config"),
                    home=Path("authored-unopened-account"),
                    source=SimpleNamespace(
                        canonical=lambda value: json.dumps(value).encode()
                    ),
                    inventory={"authored": "a" * 64},
                )
                with (
                    patch.dict("os.environ", {}),
                    patch(
                        "research_workspace_native.project_intake.ProjectIntakeService",
                        return_value=projects,
                    ),
                    patch(
                        "research_workspace_native.project_stage1_run_grant.ProjectStage1RunGrantService",
                        return_value=issuer,
                    ),
                    patch(
                        "research_workspace_native.project_model_factory.OwnAccountProjectModelFactory",
                        return_value=factory,
                    ),
                    patch(
                        "research_workspace_native.project_model.ProjectModelService",
                        side_effect=model_service,
                    ),
                    self.assertRaises(StopBeforeServices),
                ):
                    launcher["prepare"](args, checked)
                self.assertIs(observed["analysis_coverage"], expected)
                self.assertIs(observed["run_grants"], issuer)
                self.assertIs(observed["provider_factory"], factory)
                projects.close.assert_called_once()


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
