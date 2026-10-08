"""Deterministic transport tests; synthetic bindings never attest isolation."""

import copy
import hashlib
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cli"))
from stage2_live import native_namespace as namespace  # noqa: E402


class NativeNamespaceTests(unittest.TestCase):
    def binding(self):
        root = "/home/frozen/image"
        return {
            "path": "/tmp/role-home/native-namespace.json",
            "sha256": "a" * 64,
            "dispatcher_sha256": "b" * 64,
            "scope": {
                "rootfs": root,
                "bwrap": root + "/usr/local/vendor/platform/codex-resources/bwrap",
                "codex": root + "/usr/local/vendor/platform/bin/codex",
                "dns_path": "/tmp/frozen-dns",
                "home": "/tmp/role-home",
                "workspace": "/tmp/role-work",
                "telemetry": "/tmp/role-trace",
                "capture_root": "/tmp/role-capture",
            },
        }

    def test_legacy_absence_does_not_change_command_or_require_linux(self):
        with tempfile.TemporaryDirectory() as root:
            self.assertIsNone(namespace.bind_namespace("codex", root))
        command = ["codex", "exec", "--sandbox", "read-only"]
        self.assertIs(namespace.wrap_namespace(command, None), command)

    def test_empty_and_nonvector_commands_fail_before_binding_read(self):
        with patch.object(namespace, "bind_namespace") as reader:
            for command in ([], "codex exec", [None], ("codex",)):
                with (
                    self.subTest(command=command),
                    self.assertRaises(namespace.NativeNamespaceError),
                ):
                    namespace.wrap_namespace(command, self.binding())
            reader.assert_not_called()

    def test_private_mounts_are_after_redaction_and_native_flags_are_unchanged(self):
        binding = self.binding()
        command = [
            binding["scope"]["codex"],
            "exec",
            "--sandbox",
            "read-only",
            "--disable",
            "shell_tool",
        ]
        with patch.object(namespace, "bind_namespace", return_value=binding):
            actual = namespace.wrap_namespace(command, binding)
        self.assertEqual(actual[-len(command) :], command)
        mount = actual.index("--bind")
        for base in ("/home", "/root", "/mnt", "/opt", "/tmp", "/run"):
            index = next(
                i
                for i in range(len(actual) - 1)
                if actual[i : i + 2] == ["--tmpfs", base]
            )
            self.assertLess(index, mount)
        own_mounts = [
            actual[i + 1] for i, value in enumerate(actual) if value == "--bind"
        ]
        self.assertEqual(
            own_mounts,
            [
                binding["scope"][name]
                for name in ("home", "workspace", "telemetry", "capture_root")
            ],
        )
        self.assertIn("--cap-drop", actual)
        self.assertNotIn("--privileged", actual)
        ro_mounts = [
            actual[i + 1 : i + 3]
            for i, value in enumerate(actual)
            if value == "--ro-bind"
        ]
        self.assertNotIn([binding["scope"]["rootfs"]] * 2, ro_mounts)
        alias = str(Path(binding["scope"]["codex"]).parent.parent)
        self.assertIn([alias, alias], ro_mounts)
        self.assertIn([binding["path"], binding["path"]], ro_mounts)

    def test_broad_or_unrelated_executable_alias_is_rejected(self):
        for codex, bwrap in (
            ("/home/frozen/image/usr/bin/codex", "/home/frozen/image/usr/bin/bwrap"),
            (
                "/home/frozen/image/usr/local/vendor/platform/bin/codex",
                "/home/frozen/image/opt/evaluator/bwrap",
            ),
        ):
            binding = self.binding()
            binding["scope"].update(codex=codex, bwrap=bwrap)
            with (
                self.subTest(codex=codex),
                self.assertRaisesRegex(namespace.NativeNamespaceError, "vendor layout"),
            ):
                namespace.wrap_namespace([codex, "--version"], binding)

    def test_changed_scope_is_rejected_before_dispatch(self):
        old = self.binding()
        changed = copy.deepcopy(old)
        changed["sha256"] = "c" * 64
        with patch.object(namespace, "bind_namespace", return_value=changed):
            with self.assertRaisesRegex(namespace.NativeNamespaceError, "changed"):
                namespace.wrap_namespace([old["scope"]["codex"], "--version"], old)

    def test_malformed_scope_rejected_without_file_access(self):
        with patch.object(namespace, "_read") as reader:
            with self.assertRaises(namespace.NativeNamespaceError):
                namespace._validate({}, codex="x", home="y", workspace="z")
            reader.assert_not_called()

    def test_source_read_is_hash_bound(self):
        with tempfile.TemporaryDirectory() as root:
            file = Path(root) / "receipt.json"
            file.write_bytes(b"original")
            digest = hashlib.sha256(b"original").hexdigest()
            self.assertEqual(namespace._read(file, digest), (b"original", digest))
            file.write_bytes(b"changed")
            with self.assertRaisesRegex(
                namespace.NativeNamespaceError, "receipt differs"
            ):
                namespace._read(file, digest)

    def test_large_frozen_binary_uses_streaming_hash(self):
        with tempfile.TemporaryDirectory() as root:
            file = Path(root) / "large-native"
            with file.open("wb") as stream:
                stream.truncate(129 * 1024 * 1024)
            value = namespace._file_sha(file)
            self.assertEqual(len(value), 64)
            with self.assertRaisesRegex(
                namespace.NativeNamespaceError, "receipt differs"
            ):
                namespace._file_sha(file, "0" * 64)

    @unittest.skipUnless(os.name == "posix", "Unix filenames and FIFO transport")
    def test_image_file_names_do_not_use_trace_leaf_rules_and_fifo_is_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            file = Path(root) / "VERSION+release"
            file.write_bytes(b"image file")
            self.assertEqual(
                namespace._file_sha(file), hashlib.sha256(b"image file").hexdigest()
            )
            pipe = Path(root) / "pipe"
            os.mkfifo(pipe)
            with self.assertRaisesRegex(namespace.NativeNamespaceError, "not regular"):
                namespace._file_sha(pipe)

    @unittest.skipUnless(
        os.name == "posix", "Unix permission bits are part of the Linux scope"
    )
    def test_image_permissions_are_bound_in_addition_to_bytes(self):
        with tempfile.TemporaryDirectory() as root:
            file = Path(root) / "native"
            file.write_bytes(b"same bytes")
            file.chmod(0o600)
            old = namespace.image_tree_sha(root)
            file.chmod(0o700)
            self.assertNotEqual(namespace.image_tree_sha(root), old)


if __name__ == "__main__":
    unittest.main()
