"""Offline byte/protocol checks only; no real or fake child is launched."""

from pathlib import Path
from types import ModuleType, SimpleNamespace
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parent.parent / "cli/research_workspace_native"
if not ROOT.is_dir():
    ROOT = Path(__file__).resolve().parent


def raw_module(alias, path):
    if alias not in sys.modules:
        module = ModuleType(alias)
        module.__file__ = str(path)
        sys.modules[alias] = module
        exec(compile(path.read_bytes(), str(path), "exec"), module.__dict__)
    return sys.modules[alias]


source = raw_module("_atlas_local_source", ROOT / "atlas_local_source.py")
launcher = raw_module("offline_atlas_launcher", ROOT / "atlas_local_launcher.py")
launcher.SOURCE = source
for name in ("LauncherError", "require", "canonical", "digest", "decode"):
    setattr(launcher, name, getattr(source, name))


class LocalLauncherTests(unittest.TestCase):
    def test_scope_schema_and_bound_refuse_before_native_start(self):
        value = dict(
            kind="ResearchBrief",
            schema_version="1.0.0",
            original_description="Synthetic scope pending; no research authority.",
            needs=[dict(need_id="review", question="Inspect the saved case?")],
            scope_fields=[dict(field="geography", material=True, reason="Pending")],
            decisions=[],
            suggestions=[],
        )
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder).resolve() / "brief.json"
            permit = dict(brief_path="brief.json")
            spec = dict(source_root=path.parent.as_posix(), input_path=path.as_posix())
            with patch("subprocess.Popen", side_effect=AssertionError("no child")):
                path.write_bytes(source.canonical(value))
                spec["input_version"] = source.digest(path.read_bytes())
                launcher.validate_scope_input(spec, permit)
                for raw in (
                    b"not JSON",
                    b"{}",
                    source.canonical(dict(value, original_description="x" * 65536)),
                ):
                    path.write_bytes(raw)
                    spec["input_version"] = source.digest(raw)
                    with (
                        self.subTest(raw_bytes=len(raw)),
                        self.assertRaises(ValueError),
                    ):
                        launcher.validate_scope_input(spec, permit)

    def test_explicit_model_keeps_policy_and_resource_bindings(self):
        spec = dict(
            model="my-account-model",
            approval_policy="on-request",
            thread_config={},
            principals=["local-viewer"],
            limits=dict(max_starts=2, lifetime_seconds=600),
        )
        permit = dict(max_turns=2, lease_seconds=600)
        launcher.validate_session_policy(spec, permit)
        for model in ("gpt-6-astra", "gpt-6-sol"):
            launcher.validate_session_policy(dict(spec, model=model), permit)
        for model in (None, True, "", "a" * 129, "model\npolicy=never", "模型"):
            with self.subTest(model=model), self.assertRaises(ValueError):
                launcher.validate_session_policy(dict(spec, model=model), permit)
        for patch_value in (
            dict(approval_policy="never"),
            dict(principals=["another-user"]),
            dict(limits=dict(max_starts=3, lifetime_seconds=600)),
            dict(limits=dict(max_starts=2, lifetime_seconds=601)),
        ):
            with self.subTest(patch_value=patch_value), self.assertRaises(ValueError):
                launcher.validate_session_policy(dict(spec, **patch_value), permit)

    def test_disabled_does_not_inspect_or_compose(self):
        with patch.object(
            launcher, "preflight", side_effect=AssertionError("not allowed")
        ):
            self.assertEqual(
                launcher.launch(SimpleNamespace(enable_native=False)),
                dict(
                    status="disabled",
                    actual_codex_process_observed=False,
                    inference_attempted=False,
                ),
            )

    def test_bootstrap_raw_helpers_exact_origin_and_preloaded_or_drift_refusal(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            owned = root / "plugins/auto-research-agent/cli/research_workspace_native"
            owned.mkdir(parents=True)
            files = {}
            for name in ("source", "permit"):
                path = owned / ("atlas_local_" + name + ".py")
                path.write_bytes((ROOT / path.name).read_bytes())
                files["cli/research_workspace_native/" + path.name] = source.digest(
                    path.read_bytes()
                )
            manifest_path = root / "inventory.json"
            manifest_path.write_bytes(
                source.canonical(dict(repo_root=root.as_posix(), plugin_files=files))
            )
            permit_path = root / "permit.json"
            permit_path.write_bytes(
                source.canonical(
                    dict(
                        source_manifest=dict(
                            path=str(manifest_path),
                            sha256=source.digest(manifest_path.read_bytes()),
                        )
                    )
                )
            )
            args = SimpleNamespace(
                repo=root,
                permit=permit_path,
                permit_sha256=source.digest(permit_path.read_bytes()),
            )
            aliases = ("_atlas_local_source", "_atlas_local_permit")
            old = {name: sys.modules.pop(name, None) for name in aliases}
            previous = launcher.SOURCE, launcher.PERMIT
            try:
                paths = launcher.bootstrap(args)
                self.assertEqual(Path(launcher.SOURCE.__file__), paths[0])
                self.assertFalse((owned / "__pycache__").exists())
                with self.assertRaisesRegex(ValueError, "preloaded"):
                    launcher.bootstrap(args)
                for name in aliases:
                    sys.modules.pop(name, None)
                paths[0].write_bytes(
                    b"raise AssertionError('must not execute changed helper')\n"
                )
                with self.assertRaisesRegex(ValueError, "binding differs"):
                    launcher.bootstrap(args)
                with self.assertRaisesRegex(ValueError, "regular"):
                    launcher._raw(root, "0" * 64, 1024)
            finally:
                launcher.SOURCE, launcher.PERMIT = previous
                for name, module in old.items():
                    sys.modules.pop(name, None)
                    if module is not None:
                        sys.modules[name] = module

    def test_preflight_user_config_reads_bytes_and_refuses_drift_or_new_layer(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            cwd = root / "source"
            cwd.mkdir()
            config = root / "config.toml"
            config.write_bytes(b"[mcp_servers.known]\nenabled=true\n")
            permit = dict(
                user_config=dict(
                    path=str(config), sha256=source.digest(config.read_bytes())
                )
            )
            fixed = {"web_search": "disabled"}
            spec = dict(
                source_root=str(cwd),
                thread_config={**fixed, "mcp_servers.known.enabled": False},
            )
            validation = Mock(side_effect=lambda value: value)
            stub = SimpleNamespace(
                DENIED_THREAD_CONFIG=fixed, _thread_config=validation
            )
            actual_exists = Path.exists

            def fixture_exists(path):
                if (
                    path.name == "config.toml"
                    and path.parent.name == ".codex"
                    and not path.is_relative_to(root)
                ):
                    return False
                return actual_exists(path)

            with (
                patch.dict(launcher.os.environ, {"CODEX_HOME": str(root)}),
                patch.dict(
                    sys.modules, {"research_workspace_native.runtime_spec": stub}
                ),
                patch.object(Path, "exists", fixture_exists),
            ):
                launcher.validate_user_config(spec, permit)
                validation.assert_called_once_with(spec["thread_config"])
                with self.assertRaisesRegex(source.LauncherError, "names differ"):
                    launcher.validate_user_config(
                        dict(spec, thread_config=fixed), permit
                    )
                config.write_bytes(b"[mcp_servers.extra]\nenabled=true\n")
                with self.assertRaisesRegex(
                    source.LauncherError, "pinned bytes differ"
                ):
                    launcher.validate_user_config(spec, permit)
                config.write_bytes(b"[mcp_servers.known]\nenabled=true\n")
                layer = cwd / ".codex"
                layer.mkdir()
                (layer / "config.toml").write_bytes(b"[mcp_servers.extra]\n")
                with self.assertRaisesRegex(
                    source.LauncherError, "project configuration"
                ):
                    launcher.validate_user_config(spec, permit)

    def test_startup_and_runtime_cleanup_failure_close_all_independent_stores(self):
        with tempfile.TemporaryDirectory() as folder:
            attempt = Path(folder).resolve() / "attempt"
            authority = SimpleNamespace(
                spec=dict(
                    project_ref="case",
                    project_id="project-one",
                    index_sha256="1" * 64,
                    input_version="2" * 64,
                    limits=dict(timeout_seconds=30),
                ),
                permit={},
                starts=0,
                callbacks=lambda: {},
            )
            authority.permit.update(
                brief_path="brief.json",
                stage_inputs={"1": None, "2": None},
                stage_source_sha256="a" * 64,
            )
            runtime = SimpleNamespace(
                api=object(), shutdown=Mock(side_effect=RuntimeError("shutdown failed"))
            )
            operations, stages = (
                SimpleNamespace(close=Mock()),
                SimpleNamespace(close=Mock()),
            )
            modules = {
                "runtime_factory": dict(compose_runtime=Mock(return_value=runtime)),
                "runtime_spec": dict(_load=Mock()),
                "host_config": dict(
                    create_host=Mock(
                        side_effect=launcher.LauncherError("startup failed")
                    ),
                    HostRegistry=Mock(),
                ),
                "http": dict(token_authenticator=Mock()),
                "scope_api": dict(
                    ScopeApi=Mock(return_value=SimpleNamespace(register=Mock()))
                ),
                "harness_host": dict(
                    create_harness_operations=Mock(return_value=operations)
                ),
                "stage_actions": dict(StageActions=Mock(return_value=stages)),
            }
            stubs = {
                "research_workspace_native." + name: SimpleNamespace(**values)
                for name, values in modules.items()
            }
            args = SimpleNamespace(
                enable_native=True,
                spec=Path("spec"),
                spec_sha256="4" * 64,
                permit_sha256="5" * 64,
                port=0,
                open=False,
            )
            config = dict(files=[], views=[], server_object_requests=dict(native={}))
            with (
                patch.object(
                    launcher, "preflight", return_value=(authority, config, attempt)
                ),
                patch.dict(sys.modules, stubs),
            ):
                with self.assertRaisesRegex(launcher.LauncherError, "startup failed"):
                    launcher.launch(args)
            self.assertEqual(
                modules["host_config"]["create_host"].call_args.kwargs["timeout"], 30
            )
            runtime.shutdown.assert_called_once_with(timeout=10)
            operations.close.assert_called_once_with()
            stages.close.assert_called_once_with()
            receipt = launcher.decode((attempt / "cleanup-receipt.json").read_bytes())
            self.assertEqual(receipt["error_type"], "LauncherError")
            self.assertEqual(receipt["cleanup_status"], "unknown")
            self.assertEqual(receipt["cleanup_errors"], ["RuntimeError"])

    def test_explicit_http_timeout_preserves_default_bounds_and_expired_guard(self):
        sys.path.insert(0, str(ROOT.parent))
        from research_workspace_native.http import SessionHttpServer, SessionHandler
        from research_workspace_native.session_api import SessionApi

        api = SessionApi(authenticate=lambda _: "viewer")
        for options, expected in (({}, 5), ({"timeout": 30}, 30)):
            server = SessionHttpServer(api, **options)
            try:
                self.assertEqual(server.timeout_seconds, expected)
                self.assertEqual(
                    server.expected_origin, "http://" + server.expected_host
                )
            finally:
                server.server_close()
        for value in (0, 31, True, float("inf"), float("nan")):
            with (
                self.subTest(timeout=value),
                self.assertRaisesRegex(ValueError, "bounded timeout"),
            ):
                SessionHttpServer(api, timeout=value)
        handler = object.__new__(SessionHandler)
        handler.deadline, handler.connection = 20, SimpleNamespace(settimeout=Mock())
        with patch("research_workspace_native.http.time.monotonic", return_value=20):
            with (
                api.admission_guard(handler._remaining),
                self.assertRaises(TimeoutError),
            ):
                api._admission_check(30)
        handler.connection.settimeout.assert_not_called()


if __name__ == "__main__":
    unittest.main()
