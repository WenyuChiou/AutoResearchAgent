"""Actual parser/configuration/factory CLI composition; no scientific execution."""

# ruff: noqa: E402 -- use the existing standalone CLI test convention.
from contextlib import ExitStack, contextmanager, redirect_stderr, redirect_stdout
from copy import deepcopy
from functools import partial
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import test_project_stage3_planning_config as fixture
import test_project_stage123_controller_e2e as upstream
import test_project_stage3_host_e2e as http_fixture
from project_stage3_host_e2e_fixture import EvidenceDirectory
from test_project_stage3_planning import authored_plan
from research_workspace_native import project_host
from research_workspace_native.journal import Journal
from research_workspace_native.project_intake import ProjectIntakeService
from research_workspace_native.project_stage2_selection import (
    ProjectStage2SelectionService,
)
from research_workspace_native.project_stage3_planning_config import (
    Stage3PlanningHostResources,
)
from research_workspace_native.project_stage2_controller import (
    ProjectStage2ControllerDriver,
)
from stage1_deliverable import sources
from stage3_plan.contracts import Stage3Error, canonical_bytes, digest
from stage3_plan.jobs import POLICY, PlanningJobs
from stage3_plan.storage import read_json


@contextmanager
def running_cli(case, arguments):
    """Observe real main construction and serve the original authenticated Host."""
    created, errors, ready, output = {}, [], threading.Event(), io.StringIO()
    original_host = project_host.ProjectHost
    original_serve = original_host.serve_forever
    evidence_output = sys.stdout

    def construct(*args, **kwargs):
        created.update(kwargs)
        created["host"] = original_host(*args, **kwargs)
        return created["host"]

    def serve(host):
        ready.set()
        original_serve(host, poll_interval=0.02)

    def main():
        try:
            project_host.main(arguments)
        except BaseException as error:
            errors.append(error)
            ready.set()

    with (
        patch.object(project_host, "ProjectHost", side_effect=construct),
        patch.object(original_host, "serve_forever", serve),
        redirect_stdout(output),
    ):
        thread = threading.Thread(target=main, name="authored-real-cli-main")
        thread.start()
        try:
            case.assertTrue(ready.wait(15), "Actual CLI did not become ready")
            if errors:
                raise errors[0]
            connection = SimpleNamespace(
                host=created["host"],
                seed=SimpleNamespace(credential=created["credential"]),
                timings=[],
                intake=created["projects"],
                service=created["stage3_planning"],
                thread=thread,
                startup=json.loads(output.getvalue().splitlines()[0]),
            )
            connection.request = partial(
                http_fixture.HostConnection.request, connection
            )
            yield connection
        finally:
            if "host" in created and ready.is_set():
                created["host"].shutdown()
            thread.join(timeout=40)
            case.assertFalse(thread.is_alive(), "Actual CLI/worker did not join")
            if os.environ.get("STAGE3_E2E_EVIDENCE_ROOT") and "host" in created:
                lines = output.getvalue().splitlines()
                receipt = dict(
                    kind="AuthoredStage3CLILifecycleReceipt",
                    argv=arguments,
                    startup=json.loads(lines[0]) if lines else None,
                    http_timings=getattr(locals().get("connection"), "timings", []),
                    actual_main_thread_joined=not thread.is_alive(),
                    listener_closed=created["host"].socket.fileno() == -1,
                    main_errors=[repr(e) for e in errors],
                    execution_authorized=False,
                )
                target = Path(created["projects"].root) / (
                    "cli-lifecycle-" + str(time.time_ns()) + ".json"
                )
                fixture.write_json(target, receipt)
                print(
                    json.dumps(dict(cli_lifecycle_receipt=str(target), **receipt)),
                    file=evidence_output,
                    flush=True,
                )
    if errors:
        raise errors[0]


class Stage3CliFailureTests(unittest.TestCase):
    def test_unconfigured_cli_and_open_do_not_dispatch(self):
        directory = str(
            Path(
                self.enterContext(
                    tempfile.TemporaryDirectory(prefix="stage3-cli-absent-")
                )
            ).resolve()
        )
        with (
            patch(
                "stage1_eval.model_calls._execute_bound_process",
                side_effect=AssertionError("No model allowed"),
            ) as process,
            patch.object(project_host.webbrowser, "open") as browser,
        ):
            with running_cli(self, ["--projects-root", directory, "--open"]) as cli:
                self.assertEqual(cli.startup["stage3_planning"], "unconnected")
                self.assertEqual(cli.startup["model_execution"], "unconnected")
                self.assertFalse(cli.startup["execution_authorized"])
                self.assertEqual(cli.request("/api/projects")[0], 200)
                browser.assert_called_once_with(cli.startup["url"])
            process.assert_not_called()

    def test_cleanup_without_primary_preserves_both_failures_and_closes_intake(self):
        directory = str(
            Path(
                self.enterContext(
                    tempfile.TemporaryDirectory(prefix="stage3-cli-two-cleanup-")
                )
            ).resolve()
        )
        original_host_close, original_intake_close = (
            project_host.ProjectHost.server_close,
            ProjectIntakeService.close,
        )
        first, second = (
            RuntimeError("authored Host close failure"),
            RuntimeError("authored intake close failure"),
        )
        closed_intakes = []

        def host_close(host):
            original_host_close(host)
            raise first

        def intake_close(intake):
            original_intake_close(intake)
            closed_intakes.append(intake)
            raise second

        with (
            patch.object(project_host.ProjectHost, "server_close", host_close),
            patch.object(ProjectIntakeService, "close", intake_close),
        ):
            with self.assertRaises(RuntimeError) as raised:
                with running_cli(self, ["--projects-root", directory]):
                    pass
        self.assertIs(raised.exception, first)
        self.assertTrue(any("intake close failure" in note for note in first.__notes__))
        self.assertEqual(len(closed_intakes), 1)
        with self.assertRaises(sqlite3.ProgrammingError):
            closed_intakes[0].db.execute("SELECT 1")

    def test_pair_mismatch_and_missing_selection_never_construct_intake_or_host(self):
        for options in (
            ["--stage3-planning-config", "absent.json"],
            ["--stage3-planning-sha256", "0" * 64],
            [
                "--stage3-planning-config",
                "absent.json",
                "--stage3-planning-sha256",
                "0" * 64,
            ],
        ):
            with (
                self.subTest(options=options),
                patch.object(project_host, "ProjectIntakeService") as intake,
                patch.object(project_host, "ProjectHost") as host,
                redirect_stderr(io.StringIO()),
            ):
                with self.assertRaises(SystemExit) as raised:
                    project_host.main(["--projects-root", "not-created", *options])
                self.assertEqual(raised.exception.code, 2)
                intake.assert_not_called()
                host.assert_not_called()

    def test_host_construction_and_cleanup_failure_still_close_real_intake(self):
        with tempfile.TemporaryDirectory(prefix="stage3-cli-cleanup-") as directory:
            root = Path(directory).resolve()
            intake = ProjectIntakeService(
                root / "projects", authenticate=lambda token: "local-viewer"
            )
            self.addCleanup(intake.close)
            view = fixture.project(intake, fixture.TOKEN, "cleanup")
            config, config_pin = fixture.write_json(
                root / "planning.json", fixture.settings(root, [view])
            )
            selection, selection_pin = fixture.write_json(
                root / "selection.json", {"schema_version": "1.0.0", "bindings": {}}
            )
            primary = RuntimeError("authored Host constructor failure")
            with (
                patch.object(project_host, "ProjectIntakeService", return_value=intake),
                patch.object(project_host, "ProjectHost", side_effect=primary),
                patch.object(
                    Journal,
                    "release_owner",
                    side_effect=RuntimeError("authored owner cleanup failure"),
                ),
            ):
                with self.assertRaises(RuntimeError) as raised:
                    project_host.main(
                        [
                            "--projects-root",
                            str(intake.root),
                            "--selection-config",
                            str(selection),
                            "--selection-sha256",
                            selection_pin,
                            "--stage3-planning-config",
                            str(config),
                            "--stage3-planning-sha256",
                            config_pin,
                        ]
                    )
            self.assertIs(raised.exception, primary)
            self.assertTrue(
                any("owner cleanup failure" in note for note in primary.__notes__)
            )
            try:
                with self.assertRaises(sqlite3.ProgrammingError):
                    intake.db.execute("SELECT 1")
            finally:
                intake.close()

    def test_configured_shutdown_drains_non_run_handler_before_closing_databases(self):
        with tempfile.TemporaryDirectory(prefix="stage3-cli-non-run-") as directory:
            root = Path(directory).resolve()
            source = ProjectIntakeService(
                root / "projects", authenticate=lambda _: "local-viewer"
            )
            try:
                view = fixture.project(source, fixture.TOKEN, "drain")
                config, pin = fixture.write_json(
                    root / "planning.json", fixture.settings(root, [view])
                )
                selection, selected = fixture.write_json(
                    root / "selection.json", {"schema_version": "1.0.0", "bindings": {}}
                )
            finally:
                source.close()
            arguments = [
                "--projects-root",
                str(root / "projects"),
                "--selection-config",
                str(selection),
                "--selection-sha256",
                selected,
                "--stage3-planning-config",
                str(config),
                "--stage3-planning-sha256",
                pin,
            ]
            entered, release, closing = (threading.Event() for _ in range(3))
            replies = []
            original_read = ProjectIntakeService.read

            def held_read(intake, *args, **kwargs):
                entered.set()
                self.assertTrue(release.wait(15), "Admitted HTTP read was not released")
                return original_read(intake, *args, **kwargs)

            with (
                patch(
                    "stage1_eval.model_calls._execute_bound_process",
                    side_effect=AssertionError("No process allowed"),
                ) as process,
                running_cli(self, arguments) as cli,
            ):
                journal = cli.service.bindings[view["project_ref"]]["jobs"].journal
                original_close = cli.host.project_stage3_http.close

                def observed_close():
                    result = original_close()
                    closing.set()
                    return result

                with (
                    patch.object(ProjectIntakeService, "read", held_read),
                    patch.object(cli.host.project_stage3_http, "close", observed_close),
                ):
                    request = threading.Thread(
                        target=lambda: replies.append(
                            cli.request("/api/projects/" + view["project_ref"])
                        ),
                        name="authored-admitted-non-run-read",
                    )
                    request.start()
                    try:
                        self.assertTrue(entered.wait(10))
                        cli.host.shutdown()
                        self.assertTrue(closing.wait(10))
                        self.assertTrue(cli.thread.is_alive())
                        journal.snapshot(view["project_id"])
                        self.assertEqual(
                            cli.intake.db.execute("SELECT 1").fetchone()[0], 1
                        )
                    finally:
                        release.set()
                        request.join(20)
                    self.assertFalse(request.is_alive())
                    self.assertEqual(replies[0][0], 200, replies)
                process.assert_not_called()
            self.assertEqual(
                cli.host.planning_shutdown,
                dict(
                    closed=True,
                    active_request_threads=0,
                    threads_joined=True,
                    automatic_retry=False,
                ),
            )
            for connection in (journal.db, cli.intake.db):
                with self.assertRaises(sqlite3.ProgrammingError):
                    connection.execute("SELECT 1")

    def test_unconfirmed_configured_handler_join_preserves_databases_and_failure(self):
        with tempfile.TemporaryDirectory(
            prefix="stage3-cli-join-failure-"
        ) as directory:
            root = Path(directory).resolve()
            intake = ProjectIntakeService(
                root / "projects", authenticate=lambda _: "local-viewer"
            )
            self.addCleanup(intake.close)
            view = fixture.project(intake, fixture.TOKEN, "join-failure")
            config, pin = fixture.write_json(
                root / "planning.json", fixture.settings(root, [view])
            )
            selection, selected = fixture.write_json(
                root / "selection.json", {"schema_version": "1.0.0", "bindings": {}}
            )
            created = {}
            original_host = project_host.ProjectHost
            original_resources = fixture.configuration.Stage3PlanningHostResources
            primary = RuntimeError("authored handler join failure")
            intake.close()

            def construct(*args, **kwargs):
                created["intake"] = kwargs["projects"]
                created["host"] = original_host(*args, **kwargs)
                return created["host"]

            def resources(*args, **kwargs):
                created["resources"] = original_resources(*args, **kwargs)
                return created["resources"]

            try:
                with (
                    patch.object(project_host, "ProjectHost", side_effect=construct),
                    patch.object(original_host, "serve_forever", return_value=None),
                    patch.object(original_host, "server_close", side_effect=primary),
                    patch.object(
                        fixture.configuration,
                        "Stage3PlanningHostResources",
                        side_effect=resources,
                    ),
                    redirect_stdout(io.StringIO()),
                ):
                    with self.assertRaises(RuntimeError) as raised:
                        project_host.main(
                            [
                                "--projects-root",
                                str(intake.root),
                                "--selection-config",
                                str(selection),
                                "--selection-sha256",
                                selected,
                                "--stage3-planning-config",
                                str(config),
                                "--stage3-planning-sha256",
                                pin,
                            ]
                        )
                self.assertIs(raised.exception, primary)
                self.assertTrue(
                    any(
                        "Journal and intake remain open" in n for n in primary.__notes__
                    )
                )
                self.assertEqual(
                    created["intake"].db.execute("SELECT 1").fetchone()[0], 1
                )
                journal = (
                    created["resources"]
                    .service.bindings[view["project_ref"]]["jobs"]
                    .journal
                )
                journal.snapshot(view["project_id"])
            finally:
                if "host" in created:
                    original_host.server_close(created["host"])
                if "resources" in created:
                    created["resources"].close()
                if "intake" in created:
                    created["intake"].close()


class Stage3CliJourneyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Reuse authored upstream construction, not its old tests or fake service.
        with ExitStack() as construction:
            evidence = os.environ.get("STAGE3_E2E_EVIDENCE_ROOT")
            if evidence:
                Path(evidence).mkdir(parents=True, exist_ok=True)
                construction.enter_context(
                    patch.object(
                        tempfile,
                        "TemporaryDirectory",
                        side_effect=lambda *a, **k: EvidenceDirectory(
                            *a, evidence_root=evidence, **k
                        ),
                    )
                )
            runtime = sources.runtime_binding()
            construction.enter_context(
                patch.object(sources, "runtime_binding", return_value=runtime)
            )
            kind = upstream.ImportedRichControllerChoiceE2ETests
            kind.setUpClass()
            cls.addClassCleanup(kind.doClassCleanups)
            cls.source = kind()
            cls.source.setUp()
            cls.addClassCleanup(cls.source.doCleanups)
            f = cls.source
            driver = ProjectStage2ControllerDriver(
                f.service,
                spec=f.spec,
                controller_dir=f.output,
                delivery_dir=f.delivery,
                prerequisite_handler=f.handler,
            )
            with patch(
                "stage2_live.controller._ProductionAdapter",
                return_value=upstream.RichSyntheticAdapter(),
            ):
                saved = driver.run("own", f.ref, key="authored-cli-source")
            if saved["status"] != "saved":
                raise AssertionError(saved)
        # Construction patches end before all actual CLI/source/archive requests.

    def arguments(self, value, version):
        f = self.source
        project = f.intake.read("own", f.ref)
        selection, selection_pin = fixture.write_json(
            f.root / ("selection-" + version + ".json"),
            {
                "schema_version": "1.0.0",
                "bindings": {
                    f.ref: dict(
                        input_version=project["input_version"],
                        brief_sha256=project["brief_sha256"],
                        workflow_root=str(f.workflow),
                        delivery_root=str(f.delivery),
                        delivery_manifest_sha256=read_json(
                            f.delivery / "delivery_manifest.json"
                        )["manifest_sha256"],
                    )
                },
            },
        )
        config, config_pin = fixture.write_json(
            f.root / ("planning-" + version + ".json"), value
        )
        return [
            "--projects-root",
            str(f.root),
            "--selection-config",
            str(selection),
            "--selection-sha256",
            selection_pin,
            "--stage3-planning-config",
            str(config),
            "--stage3-planning-sha256",
            config_pin,
        ]

    def exercise_unknown_attach(self, retained):
        """Public Journal transitions author a synthetic interrupted intent; no dispatch."""
        f, value = self.source, deepcopy(retained["configuration"])
        ref, pinned = f.ref, retained["pinned"]
        row = value["bindings"][0]
        original = Journal(value["journal_path"])
        try:
            source_item = original.snapshot(row["project_id"])["intents"][
                PlanningJobs.namespace + digest(pinned["key"])
            ]
        finally:
            original.close()
        source_digest = digest(source_item)
        output = Path(source_item["payload"]["output"]) / "plan"
        artifacts = {
            name: (output / name).read_bytes()
            for name in ("manifest.json", "plan.json", "raw-response.json")
        }
        value["journal_path"] = str(f.root / "synthetic-interrupted-attach.sqlite")
        row["recovery_pins"] = [
            dict(
                key=pinned["key"],
                request_sha256=pinned["request_sha256"],
                plan_manifest_sha256="0" * 64,
            )
        ]
        bindings = read_json(f.root / "selection-initial.json")["bindings"]
        selection = ProjectStage2SelectionService(f.intake, bindings)
        with patch(
            "stage1_eval.model_calls._execute_bound_process",
            side_effect=AssertionError("Synthetic attach must not dispatch"),
        ) as process:
            owner = Stage3PlanningHostResources(f.intake, "own", selection, value)
            try:
                jobs = owner.service.bindings[ref]["jobs"]
                key = jobs._key(pinned["key"])
                state = owner.journal.snapshot(jobs.project_id)
                if key not in state["intents"]:
                    owner.journal.record_intent(
                        jobs.project_id,
                        jobs.owner,
                        key,
                        source_item["method"],
                        deepcopy(source_item["payload"]),
                        state["revision"],
                    )
                    revision = owner.journal.snapshot(jobs.project_id)["revision"]
                    owner.journal.transition_intent(
                        jobs.project_id,
                        jobs.owner,
                        key,
                        "dispatching",
                        {"request_sha256": pinned["request_sha256"]},
                        revision,
                    )
                else:
                    self.assertIn(
                        state["intents"][key]["status"],
                        ("dispatching", "execution-unknown"),
                    )
                    self.assertEqual(
                        state["intents"][key]["payload"], source_item["payload"]
                    )
                with self.assertRaisesRegex(Stage3Error, "manifest"):
                    owner.service.recover(
                        "own", ref, pinned, expected_plan_manifest_sha256="0" * 64
                    )
            finally:
                owner.close()
            route = "/api/projects/" + ref + "/stage3/planning/recover"
            with running_cli(
                self, self.arguments(value, "synthetic-attach-wrong-pin")
            ) as cli:
                status, failure = cli.request(route, pinned)
                self.assertEqual(
                    (status, failure),
                    (400, {"error": "stage3-planning-input-rejected"}),
                )
            row["recovery_pins"][0]["plan_manifest_sha256"] = retained["manifest"]
            with running_cli(
                self, self.arguments(value, "synthetic-attach-trusted-pin")
            ) as cli:
                status, recovered = cli.request(route, pinned)
                self.assertEqual(status, 200, recovered)
                self.assertEqual(
                    recovered["plan_manifest_sha256"], retained["manifest"]
                )
                self.assertEqual(recovered["outcome"], "saved")
                for name in POLICY:
                    self.assertIs(recovered[name], False)
            process.assert_not_called()
        original = Journal(retained["configuration"]["journal_path"])
        try:
            self.assertEqual(
                digest(original.snapshot(row["project_id"])["intents"][key]),
                source_digest,
            )
        finally:
            original.close()
        self.assertEqual(
            {name: (output / name).read_bytes() for name in artifacts}, artifacts
        )
        print(
            json.dumps(
                dict(
                    synthetic_journal_intent_only=True,
                    original_completed_intent_and_plan_unchanged=True,
                    new_native_or_fixed_processes=0,
                    execution_authorized=False,
                )
            ),
            flush=True,
        )

    def test_real_cli_plan_archive_restart_recovery_and_slow_shutdown(self):
        self.exercise_cli_journey()

    def exercise_cli_journey(self, *, retained=None, skip_recovery=False):
        f = self.source
        project = f.intake.read("own", f.ref)
        value = (
            fixture.settings(f.root, [project])
            if retained is None
            else deepcopy(retained["configuration"])
        )
        route = "/api/projects/" + f.ref + "/stage3/planning"
        calls, entered, release = [], threading.Event(), threading.Event()
        slow = False

        def authored_process(command, **options):
            calls.append(list(command))
            self.assertEqual(command[0], value["bindings"][0]["native"]["codex"])
            self.assertEqual(options["timeout"], 5)
            self.assertIn('web_search="disabled"', command)
            self.assertIn('approval_policy="never"', command)
            self.assertIn("--ignore-user-config", command)
            requests = [
                read_json(p)
                for p in Path(value["bindings"][0]["jobs_root"]).rglob("request.json")
            ]
            matches = [
                r
                for r in requests
                if "intake" in r and r["plan_id"] in options["input"].decode("utf-8")
            ]
            self.assertEqual(len(matches), 1)
            request = matches[0]
            plan = authored_plan(
                request["intake"],
                request["intake"]["source_manifest_sha256"],
                request["plan_id"],
            )
            entered.set()
            if slow:
                self.assertTrue(
                    release.wait(4.5),
                    "Test provider release exceeded original five second limit",
                )
            raw = canonical_bytes(plan)
            Path(command[command.index("-o") + 1]).write_bytes(raw)
            events = [
                {
                    "type": "item.completed",
                    "item": {"type": "agent_message", "text": raw.decode()},
                },
                {"type": "turn.completed"},
            ]
            return subprocess.CompletedProcess(
                command, 0, b"\n".join(canonical_bytes(e) for e in events), b""
            )

        with patch(
            "stage1_eval.model_calls._execute_bound_process",
            side_effect=authored_process,
        ):
            if retained is None:
                with running_cli(self, self.arguments(value, "initial")) as cli:
                    self.assertEqual(cli.startup["stage3_planning"], "connected")
                    self.assertFalse(cli.startup["execution_authorized"])
                    self.assertFalse(cli.host.daemon_threads)
                    self.assertTrue(cli.host.block_on_close)
                    status, pending = cli.request(route)
                    self.assertEqual(status, 200, pending)
                    self.assertIsNone(pending["default_request"])
                    self.assertEqual(calls, [])
                    selected = http_fixture.select_current(
                        cli, SimpleNamespace(case=self, ref=f.ref, intake=cli.intake)
                    )
                    status, ready = cli.request(route)
                    self.assertEqual(status, 200, ready)
                    body = ready["default_request"]
                    self.assertEqual(
                        body["selection_request_sha256"], selected["request_sha256"]
                    )
                    status, prepared = cli.request(route + "/prepare", body)
                    self.assertEqual(status, 200, prepared)
                    self.assertEqual(calls, [])
                    pinned = dict(body, request_sha256=prepared["request_sha256"])
                    self.assertEqual(
                        cli.request(route + "/run", dict(pinned, confirmed=True))[0],
                        202,
                    )
                    self.assertTrue(entered.wait(30))
                    status, saved = cli.request(route)
                    self.assertEqual(status, 200, saved)
                    self.assertEqual(saved["job"]["outcome"], "saved", saved)
                    self.assertEqual(
                        saved["job"]["planning_status"], "needs-information"
                    )
                    for name in POLICY:
                        self.assertIs(saved[name], False)
                    self.assertTrue(saved["plan"]["condition_dispositions"])
                    self.assertTrue(saved["plan"]["unknowns"])
                    manifest = saved["job"]["plan_manifest_sha256"]
                    self.assertEqual(len(calls), 1)
                with self.assertRaises(sqlite3.ProgrammingError):
                    cli.intake.db.execute("SELECT 1")

            else:
                body, pinned, manifest = (
                    retained["body"],
                    retained["pinned"],
                    retained["manifest"],
                )
            completed_calls = len(calls)

            if not skip_recovery:
                trusted = dict(
                    key=body["key"],
                    request_sha256=pinned["request_sha256"],
                    plan_manifest_sha256=manifest,
                )
                value["bindings"][0]["recovery_pins"] = [
                    dict(trusted, plan_manifest_sha256="0" * 64)
                ]
                with running_cli(self, self.arguments(value, "wrong-pin")) as cli:
                    status, completed = cli.request(route + "/recover", pinned)
                    self.assertEqual(status, 200, completed)
                    self.assertEqual(completed["plan_manifest_sha256"], manifest)
                    self.assertEqual(len(calls), completed_calls)
                value["bindings"][0]["recovery_pins"] = [trusted]
                with running_cli(self, self.arguments(value, "trusted-restart")) as cli:
                    status, recovered = cli.request(route + "/recover", pinned)
                    self.assertEqual(status, 200, recovered)
                    self.assertEqual(recovered["outcome"], "saved", recovered)
                    self.assertEqual(len(calls), completed_calls)
                    self.assertEqual(
                        cli.request(
                            route + "/recover",
                            dict(pinned, input_version="changed-version"),
                        )[0],
                        409,
                    )

                changed = deepcopy(value)
                changed["bindings"][0]["configuration"]["reasoning"] = "low"
                with running_cli(
                    self, self.arguments(changed, "changed-context")
                ) as cli:
                    self.assertEqual(cli.request(route + "/recover", pinned)[0], 409)
                    self.assertEqual(len(calls), completed_calls)

            # A separately configured authored capture is an explicit new test
            # request, not an implicit replay of the completed first capture.
            slow_value = deepcopy(value)
            slow_value["bindings"][0]["native"]["capture_dir"] = str(
                f.root / "capture-slow-explicit"
            )
            slow = True
            entered.clear()
            try:
                with running_cli(self, self.arguments(slow_value, "slow-close")) as cli:
                    body2 = dict(body, key="explicit-slow-engineering-job")
                    status, prepared2 = cli.request(route + "/prepare", body2)
                    self.assertEqual(status, 200, prepared2)
                    pinned2 = dict(body2, request_sha256=prepared2["request_sha256"])
                    self.assertEqual(
                        cli.request(route + "/run", dict(pinned2, confirmed=True))[0],
                        202,
                    )
                    self.assertTrue(entered.wait(30))
                    began = time.monotonic()
                    cli.host.shutdown()
                    self.assertFalse(release.wait(2.1))
                    self.assertTrue(
                        cli.thread.is_alive(),
                        "CLI returned while its original worker was active",
                    )
                    self.assertEqual(cli.intake.db.execute("SELECT 1").fetchone()[0], 1)
                    binding = cli.service.bindings[f.ref]
                    binding["jobs"].journal.snapshot(project["project_id"])
                    release.set()
                self.assertGreaterEqual(time.monotonic() - began, 2.1)
                self.assertFalse(cli.thread.is_alive())
                self.assertEqual(
                    cli.host.planning_shutdown,
                    dict(
                        closed=True,
                        active_request_threads=0,
                        threads_joined=True,
                        automatic_retry=False,
                    ),
                )
                self.assertEqual(len(calls), completed_calls + 1)
                with self.assertRaises(sqlite3.ProgrammingError):
                    cli.intake.db.execute("SELECT 1")
            finally:
                release.set()
        print(
            json.dumps(
                {
                    "cli_fixed_process_responses": len(calls),
                    "real_native_processes": 0,
                    "research_calls": 0,
                    "evaluation_calls": 0,
                    "execution_authorized": False,
                }
            ),
            flush=True,
        )

        if not skip_recovery:
            self.exercise_unknown_attach(
                dict(configuration=value, body=body, pinned=pinned, manifest=manifest)
            )


if __name__ == "__main__":
    unittest.main()
