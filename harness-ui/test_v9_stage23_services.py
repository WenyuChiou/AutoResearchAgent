"""Wiki Host composition preserves pinned selection and planning authority."""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from wiki_stage23_services import configure_services, validate_args


def options(**updates):
    values = dict(
        stage2_direct_import_config=None,
        stage2_direct_import_sha256=None,
        stage3_planning_config=None,
        stage3_planning_sha256=None,
        stage2_reading_config=None,
        stage2_reading_sha256=None,
    )
    values.update(updates)
    return SimpleNamespace(**values)


class WikiStage23ServicesTests(unittest.TestCase):
    def test_missing_pin_and_planning_without_selection_fail_closed(self):
        with self.assertRaises(ValueError):
            validate_args(options(stage2_direct_import_config="x"))
        with self.assertRaises(ValueError):
            validate_args(
                options(stage3_planning_config="x", stage3_planning_sha256="a" * 64)
            )

    def test_no_config_preserves_unconnected_services(self):
        services = {"projects": object(), "stage2": object(), "credential": "fixture"}
        configure_services(services, options())
        self.assertIsNone(services["stage2_selection"])
        self.assertIsNone(services["stage3_planning"])
        self.assertIsNone(services["stage3_recovery_pins"])
        self.assertIsNone(services["stage2_readings"])

    def test_existing_store_requests_reuse_only_direct_imports(self):
        args = options(
            existing_stage23_store=True,
            stage2_direct_import_config="source.json",
            stage2_direct_import_sha256="a" * 64,
        )
        intake, stage2 = object(), object()
        with (
            patch(
                "research_workspace_native.project_stage2_direct_config.load_direct_request_imports",
                return_value={},
            ) as imports,
            patch(
                "research_workspace_native.project_stage2_selection.ProjectStage2SelectionService"
            ),
        ):
            configure_services(
                {"projects": intake, "stage2": stage2, "credential": "fixture"}, args
            )
        imports.assert_called_once_with(
            stage2, "fixture", "source.json", "a" * 64, existing_only=True
        )

    def test_failed_http_drain_keeps_planner_and_project_open(self):
        from unittest.mock import Mock
        from run_v7 import close_services

        resources, projects = Mock(), Mock()
        host = SimpleNamespace(
            v7_native_stage1=None,
            server_close=Mock(side_effect=RuntimeError("not drained")),
        )
        with self.assertRaisesRegex(RuntimeError, "not drained"):
            close_services(
                {"planning_resources": resources, "projects": projects}, host
            )
        resources.close.assert_not_called()
        projects.close.assert_not_called()

    def test_unjoined_planning_request_keeps_journal_and_projects_open(self):
        from unittest.mock import Mock
        from run_v7 import close_services

        resources, projects = Mock(), Mock()
        host = SimpleNamespace(
            v7_native_stage1=None,
            server_close=Mock(),
            project_stage3_http=SimpleNamespace(
                close=Mock(
                    return_value={"threads_joined": False, "active_request_threads": 1}
                )
            ),
        )
        with self.assertRaisesRegex(RuntimeError, "have not drained"):
            close_services(
                {"planning_resources": resources, "projects": projects}, host
            )
        resources.close.assert_not_called()
        projects.close.assert_not_called()

    def test_stage1_cleanup_failure_does_not_skip_planner_or_intake_close(self):
        from unittest.mock import Mock
        from run_v7 import close_services

        native, resources, projects = Mock(), Mock(), Mock()
        native.close.side_effect = RuntimeError("native cleanup failed")
        host = SimpleNamespace(
            v7_native_stage1=native,
            server_close=Mock(),
            project_stage3_http=SimpleNamespace(
                close=Mock(
                    return_value={"threads_joined": True, "active_request_threads": 0}
                )
            ),
        )
        with self.assertRaisesRegex(RuntimeError, "native cleanup failed"):
            close_services(
                {"planning_resources": resources, "projects": projects}, host
            )
        resources.close.assert_called_once()
        projects.close.assert_called_once()

    def test_real_http_handler_is_drained_before_resources_close(self):
        import tempfile
        import threading
        import urllib.request
        import urllib.error
        from pathlib import Path
        from unittest.mock import patch
        import test_project_stage3_planning_config as fixture
        from research_workspace_native.http import token_authenticator
        from research_workspace_native.project_intake import ProjectIntakeService
        from research_workspace_native.project_stage2 import ProjectStage2Service
        from research_workspace_native.project_host import ProjectHost
        from run_v7 import configure_host_lifecycle, close_services

        with tempfile.TemporaryDirectory(prefix="v9-drain-") as directory:
            root = Path(directory).resolve()
            intake = ProjectIntakeService(
                root / "projects",
                authenticate=token_authenticator({fixture.TOKEN: "local-viewer"}),
            )
            project = fixture.project(intake, fixture.TOKEN, "wiki-drain")
            selection, selection_pin = fixture.write_json(
                root / "selection.json", {"schema_version": "1.0.0", "bindings": {}}
            )
            config, config_pin = fixture.write_json(
                root / "planning.json", fixture.settings(root, [project])
            )
            services = {
                "projects": intake,
                "stage2": ProjectStage2Service(intake),
                "credential": fixture.TOKEN,
            }
            configure_services(
                services,
                options(
                    selection_config=selection,
                    selection_sha256=selection_pin,
                    stage3_planning_config=config,
                    stage3_planning_sha256=config_pin,
                ),
            )
            host = ProjectHost(
                projects=intake,
                credential=fixture.TOKEN,
                stage2=services["stage2"],
                stage2_selection=services["stage2_selection"],
                stage3_planning=services["stage3_planning"],
                stage3_recovery_pins=services["stage3_recovery_pins"],
                files={},
                views=[],
                port=0,
            )
            host.v7_native_stage1 = None
            configure_host_lifecycle(host, services)
            self.assertFalse(host.daemon_threads)
            self.assertTrue(host.block_on_close)
            entered, release = threading.Event(), threading.Event()
            errors = []
            original = ProjectIntakeService.read

            def held_read(instance, *args, **kwargs):
                entered.set()
                if not release.wait(15):
                    raise RuntimeError("test handler was not released")
                return original(instance, *args, **kwargs)

            def request():
                url = (
                    host.expected_origin
                    + "/api/projects/"
                    + project["project_ref"]
                    + "/stage3/planning"
                )
                req = urllib.request.Request(
                    url,
                    headers={
                        "Origin": host.expected_origin,
                        "Authorization": "Bearer " + fixture.TOKEN,
                    },
                )
                try:
                    with urllib.request.urlopen(req, timeout=20):
                        pass
                except urllib.error.HTTPError:
                    pass  # No selection binding is intentional.
                except Exception as error:
                    errors.append(error)

            def cleanup():
                try:
                    close_services(services, host)
                except BaseException as error:
                    errors.append(error)

            server = threading.Thread(target=host.serve_forever, daemon=True)
            caller = threading.Thread(target=request, daemon=True)
            closer = threading.Thread(target=cleanup, daemon=True)
            server.start()
            try:
                with patch.object(ProjectIntakeService, "read", held_read):
                    caller.start()
                    self.assertTrue(entered.wait(10))
                    host.shutdown()
                    closer.start()
                    self.assertFalse(closer.join(timeout=0.2))
                    self.assertTrue(
                        closer.is_alive(), "cleanup must wait for the admitted handler"
                    )
                    intake.db.execute("SELECT 1")
                    release.set()
                    caller.join(20)
                    closer.join(20)
                    self.assertFalse(caller.is_alive())
                    self.assertFalse(closer.is_alive())
                    self.assertEqual(errors, [])
                    self.assertTrue(host.planning_shutdown["threads_joined"])
            finally:
                release.set()
                if server.is_alive():
                    host.shutdown()
                server.join(10)
                if caller.is_alive():
                    caller.join(20)
                if closer.is_alive():
                    closer.join(20)

    def test_active_request_longer_than_first_close_is_joined_before_release(self):
        import tempfile
        import threading
        import urllib.request
        from pathlib import Path
        import test_project_stage3_planning_config as fixture
        from research_workspace_native.http import token_authenticator
        from research_workspace_native.project_intake import ProjectIntakeService
        from research_workspace_native.project_stage2 import ProjectStage2Service
        from research_workspace_native.project_host import ProjectHost
        from run_v7 import configure_host_lifecycle, close_services

        with tempfile.TemporaryDirectory(prefix="v9-active-drain-") as directory:
            root = Path(directory).resolve()
            intake = ProjectIntakeService(
                root / "projects",
                authenticate=token_authenticator({fixture.TOKEN: "local-viewer"}),
            )
            project = fixture.project(intake, fixture.TOKEN, "wiki-active")
            selection, selection_pin = fixture.write_json(
                root / "selection.json", {"schema_version": "1.0.0", "bindings": {}}
            )
            config, config_pin = fixture.write_json(
                root / "planning.json", fixture.settings(root, [project])
            )
            services = {
                "projects": intake,
                "stage2": ProjectStage2Service(intake),
                "credential": fixture.TOKEN,
            }
            configure_services(
                services,
                options(
                    selection_config=selection,
                    selection_sha256=selection_pin,
                    stage3_planning_config=config,
                    stage3_planning_sha256=config_pin,
                ),
            )
            host = ProjectHost(
                projects=intake,
                credential=fixture.TOKEN,
                stage2=services["stage2"],
                stage2_selection=services["stage2_selection"],
                stage3_planning=services["stage3_planning"],
                stage3_recovery_pins=services["stage3_recovery_pins"],
                files={},
                views=[],
                port=0,
            )
            host.v7_native_stage1 = None
            configure_host_lifecycle(host, services)
            entered, release, first_close = (
                threading.Event(),
                threading.Event(),
                threading.Event(),
            )
            errors = []
            transport = host.project_stage3_http
            original_close = transport.close
            close_results = []

            def observed_close():
                result = original_close()
                close_results.append(result)
                if not result["threads_joined"]:
                    first_close.set()
                return result

            transport.close = observed_close

            class HeldHandler(host.RequestHandlerClass):
                def do_GET(self):
                    with transport._lock:
                        transport._active[project["project_ref"]] = (
                            ("synthetic-key", "synthetic-hash"),
                            threading.current_thread(),
                        )
                    try:
                        entered.set()
                        if not release.wait(15):
                            raise RuntimeError("test handler was not released")
                        self.send_response(204)
                        self.end_headers()
                    finally:
                        transport.finish(project["project_ref"])

            host.RequestHandlerClass = HeldHandler

            def request():
                try:
                    with urllib.request.urlopen(
                        host.expected_origin + "/synthetic", timeout=20
                    ):
                        pass
                except Exception as error:
                    errors.append(error)

            def cleanup():
                try:
                    close_services(services, host)
                except BaseException as error:
                    errors.append(error)

            server = threading.Thread(target=host.serve_forever, daemon=True)
            caller = threading.Thread(target=request, daemon=True)
            closer = threading.Thread(target=cleanup, daemon=True)
            server.start()
            try:
                caller.start()
                self.assertTrue(entered.wait(10))
                host.shutdown()
                closer.start()
                self.assertTrue(
                    first_close.wait(8),
                    "first planning close should observe the held request",
                )
                self.assertTrue(
                    closer.is_alive(),
                    "server close must wait after the first planning close",
                )
                intake.db.execute("SELECT 1")
                release.set()
                caller.join(20)
                closer.join(20)
                self.assertFalse(caller.is_alive())
                self.assertFalse(closer.is_alive())
                self.assertEqual(errors, [])
                self.assertFalse(close_results[0]["threads_joined"])
                self.assertTrue(close_results[-1]["threads_joined"])
                self.assertTrue(host.planning_shutdown["threads_joined"])
            finally:
                release.set()
                if server.is_alive():
                    host.shutdown()
                server.join(10)
                if caller.is_alive():
                    caller.join(20)
                if closer.is_alive():
                    closer.join(20)

    def test_actual_host_registers_only_the_configured_project_without_dispatch(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        import test_project_stage3_planning_config as fixture
        from research_workspace_native.http import token_authenticator
        from research_workspace_native.project_intake import ProjectIntakeService
        from research_workspace_native.project_stage2 import ProjectStage2Service
        from research_workspace_native.project_host import ProjectHost
        from research_workspace_native import (
            project_stage3_planning_config as config_module,
        )

        with tempfile.TemporaryDirectory(prefix="v9-stage23-") as directory:
            root = Path(directory).resolve()
            intake = ProjectIntakeService(
                root / "projects",
                authenticate=token_authenticator({fixture.TOKEN: "local-viewer"}),
            )
            try:
                project = fixture.project(intake, fixture.TOKEN, "wiki-fixture")
                selection, selection_pin = fixture.write_json(
                    root / "selection.json", {"schema_version": "1.0.0", "bindings": {}}
                )
                config, config_pin = fixture.write_json(
                    root / "planning.json", fixture.settings(root, [project])
                )
                services = {
                    "projects": intake,
                    "stage2": ProjectStage2Service(intake),
                    "credential": fixture.TOKEN,
                }
                args = options(
                    selection_config=selection,
                    selection_sha256=selection_pin,
                    stage3_planning_config=config,
                    stage3_planning_sha256=config_pin,
                )
                with patch.object(
                    config_module.NativePlanner,
                    "__call__",
                    side_effect=AssertionError("model forbidden"),
                ) as native:
                    configure_services(services, args)
                    host = ProjectHost(
                        projects=intake,
                        credential=fixture.TOKEN,
                        stage2=services["stage2"],
                        stage2_selection=services["stage2_selection"],
                        stage3_planning=services["stage3_planning"],
                        stage3_recovery_pins=services["stage3_recovery_pins"],
                        files={},
                        views=[],
                        port=0,
                    )
                    try:
                        self.assertEqual(
                            list(host.project_stage3_http.service.bindings),
                            [project["project_ref"]],
                        )
                        self.assertIs(host.project_stage3_http.service.intake, intake)
                        native.assert_not_called()
                    finally:
                        host.server_close()
                        services["planning_resources"].close()
                self.assertFalse((root / "capture-0").exists())
            finally:
                intake.close()

    def test_selection_config_hash_mismatch_is_rejected(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory(prefix="v9-stage23-pin-") as directory:
            path = Path(directory) / "selection.json"
            path.write_text(
                '{"schema_version":"1.0.0","bindings":{}}', encoding="utf-8"
            )
            with self.assertRaisesRegex(ValueError, "receipt differs"):
                configure_services(
                    {"projects": object(), "stage2": object(), "credential": "fixture"},
                    options(selection_config=path, selection_sha256="0" * 64),
                )

    def test_pinned_configs_reuse_same_intake_selection_and_resources(self):
        intake, stage2, selection = object(), object(), object()
        cfg, resources = object(), SimpleNamespace(service=object(), recovery_pins={})
        services = {"projects": intake, "stage2": stage2, "credential": "fixture"}
        args = options(
            stage2_direct_import_config="source.json",
            stage2_direct_import_sha256="a" * 64,
            stage3_planning_config="plan.json",
            stage3_planning_sha256="b" * 64,
        )
        with (
            patch(
                "research_workspace_native.project_stage2_direct_config.load_direct_request_imports",
                return_value={"ref": {}},
            ) as imports,
            patch(
                "research_workspace_native.project_stage2_selection.ProjectStage2SelectionService",
                return_value=selection,
            ) as select,
            patch(
                "research_workspace_native.project_stage3_planning_config.load_stage3_planning_configuration",
                return_value=cfg,
            ) as load,
            patch(
                "research_workspace_native.project_stage3_planning_config.Stage3PlanningHostResources",
                return_value=resources,
            ) as factory,
        ):
            configure_services(services, args)
        imports.assert_called_once_with(stage2, "fixture", "source.json", "a" * 64)
        select.assert_called_once_with(intake, {"ref": {}})
        load.assert_called_once_with(intake, "fixture", "plan.json", "b" * 64)
        factory.assert_called_once_with(intake, "fixture", selection, cfg)
        self.assertIs(services["stage3_planning"], resources.service)
        self.assertIs(services["planning_resources"], resources)


if __name__ == "__main__":
    unittest.main()
