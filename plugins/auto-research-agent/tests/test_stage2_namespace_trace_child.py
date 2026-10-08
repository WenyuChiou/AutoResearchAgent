"""Private per-action trace children never widen the role's native namespace."""

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cli"))
from stage2_live import native_namespace as namespace  # noqa: E402
import test_stage2_native_namespace as namespace_fixtures  # noqa: E402


class NamespaceTraceChildTests(unittest.TestCase):
    def test_scoped_final_output_exposes_only_one_precreated_file(self):
        with tempfile.TemporaryDirectory() as root:
            base = Path(root).resolve()
            capture = base / "captures"
            own = capture / "action"
            own.mkdir(parents=True)
            sink = own / "final.txt"
            sink.write_bytes(b"")
            binding = namespace_fixtures.NativeNamespaceTests().binding()
            binding["scope"]["capture_root"] = str(capture)
            binding["trace_root"] = str(base / "trace" / "action")
            command = [binding["scope"]["codex"], "exec", "-o", str(sink)]
            with patch.object(namespace, "bind_namespace", return_value=binding):
                wrapped = namespace.wrap_namespace(command, binding, output_sink=sink)
                mounts = [
                    wrapped[i + 1]
                    for i, arg in enumerate(wrapped[:-2])
                    if arg == "--bind"
                ]
                self.assertEqual(
                    mounts,
                    [
                        binding["scope"]["home"],
                        binding["scope"]["workspace"],
                        binding["trace_root"],
                        str(sink),
                    ],
                )
                self.assertNotIn(str(capture), mounts)
                with self.assertRaisesRegex(namespace.NativeNamespaceError, "sink"):
                    namespace.wrap_namespace(command, binding)
                for invalid in (
                    own,
                    capture / "missing" / "final.txt",
                    base / "final.txt",
                ):
                    with (
                        self.subTest(invalid=str(invalid)),
                        self.assertRaises(
                            (namespace.NativeNamespaceError, OSError, ValueError)
                        ),
                    ):
                        namespace.wrap_namespace(command, binding, output_sink=invalid)
                missing = capture / "missing" / "final.txt"
                with self.assertRaises((OSError, ValueError)):
                    namespace.wrap_namespace(
                        [command[0], "exec", "-o", str(missing)],
                        binding,
                        output_sink=missing,
                    )

    def test_legacy_without_scope_rejects_opt_in_child(self):
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaisesRegex(namespace.NativeNamespaceError, "opt-in"):
                namespace.bind_namespace("codex", root, trace_root=root)

    def test_two_children_bind_independently_without_changing_base_scope(self):
        with tempfile.TemporaryDirectory() as root:
            base = Path(root).resolve()
            home, telemetry = base / "home", base / "telemetry"
            home.mkdir()
            telemetry.mkdir()
            children = [telemetry / "preflight", telemetry / "research"]
            for child in children:
                child.mkdir()
            scope = namespace_fixtures.NativeNamespaceTests().binding()["scope"]
            scope["telemetry"] = str(telemetry)
            (home / namespace.SCOPE_FILE).write_text(json.dumps(scope))
            with (
                patch.object(namespace.sys, "platform", "linux"),
                patch.object(namespace, "_validate"),
                patch.object(
                    namespace,
                    "_directory",
                    side_effect=lambda value: Path(value).resolve(),
                ),
            ):
                first = namespace.bind_namespace(
                    scope["codex"], home, trace_root=str(children[0])
                )
                second = namespace.bind_namespace(
                    scope["codex"], home, trace_root=str(children[1])
                )
                legacy = namespace.bind_namespace(scope["codex"], home)
                for invalid in (
                    str(telemetry),
                    str(home),
                    str(telemetry / ".." / "home"),
                ):
                    with (
                        self.subTest(invalid=invalid),
                        self.assertRaises(namespace.NativeNamespaceError),
                    ):
                        namespace.bind_namespace(
                            scope["codex"], home, trace_root=invalid
                        )
            self.assertEqual(first["scope"], second["scope"])
            self.assertNotEqual(first["trace_root"], second["trace_root"])
            self.assertNotIn("trace_root", legacy)
            with patch.object(namespace, "bind_namespace", return_value=first) as read:
                command = namespace.wrap_namespace([scope["codex"], "--version"], first)
            read.assert_called_once_with(
                scope["codex"],
                scope["home"],
                scope["workspace"],
                trace_root=str(children[0]),
            )
            self.assertIn(
                ["--setenv", "CODEX_ROLLOUT_TRACE_ROOT", str(children[0])],
                [command[i : i + 3] for i in range(len(command) - 2)],
            )
            mounts = [
                command[i + 1] for i, arg in enumerate(command[:-2]) if arg == "--bind"
            ]
            self.assertEqual(
                mounts, [scope["home"], scope["workspace"], str(children[0])]
            )
            self.assertNotIn(scope["capture_root"], mounts)
            self.assertNotIn(str(telemetry), mounts)
            with patch.object(namespace, "bind_namespace", return_value=second):
                with self.assertRaisesRegex(namespace.NativeNamespaceError, "changed"):
                    namespace.wrap_namespace([scope["codex"], "--version"], first)

    def test_pathlike_child_has_the_same_validated_binding_as_string(self):
        with tempfile.TemporaryDirectory() as root:
            base = Path(root).resolve()
            home = base / "home"
            home.mkdir()
            telemetry = base / "telemetry"
            telemetry.mkdir()
            child = telemetry / "action"
            child.mkdir()
            scope = namespace_fixtures.NativeNamespaceTests().binding()["scope"]
            scope["telemetry"] = str(telemetry)
            (home / namespace.SCOPE_FILE).write_text(json.dumps(scope))

            def directory(value):
                self.assertIsInstance(value, str)
                return Path(value).resolve()

            with (
                patch.object(namespace.sys, "platform", "linux"),
                patch.object(namespace, "_validate"),
                patch.object(namespace, "_directory", side_effect=directory),
            ):
                self.assertEqual(
                    namespace.bind_namespace(scope["codex"], home, trace_root=child),
                    namespace.bind_namespace(
                        scope["codex"], home, trace_root=str(child)
                    ),
                )
