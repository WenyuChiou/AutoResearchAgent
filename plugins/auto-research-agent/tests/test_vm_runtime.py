"""Offline protected runtime tests: synthetic ELF and explicit Linux metadata."""

from pathlib import Path
import stat
import struct
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cli"))
from stage1_ab import runner, vm_runtime as runtime  # noqa: E402


def elf(*, interpreter=False, dependencies=()):
    data = bytearray(512)
    data[:7] = b"\x7fELF\x02\x01\x01"
    struct.pack_into("<HHI", data, 16, 3, 62, 1)
    struct.pack_into("<Q", data, 32, 64)
    struct.pack_into("<HHH", data, 52, 64, 56, 2 + int(interpreter))
    struct.pack_into("<IIQQQQQQ", data, 64, 1, 5, 0, 0, 0, 512, 512, 4096)
    struct.pack_into(
        "<IIQQQQQQ", data, 120, 2, 6, 256, 0, 0, (len(dependencies) + 1) * 16, 128, 8
    )
    for index, tag in enumerate(dependencies):
        struct.pack_into("<qQ", data, 256 + index * 16, tag, 1)
    if interpreter:
        struct.pack_into("<IIQQQQQQ", data, 176, 3, 4, 400, 0, 0, 10, 10, 1)
    return bytes(data)


class ProtectedRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.binary = Path(self.temp.name).resolve() / "codex"
        self.binary.write_bytes(elf())
        self.overrides = {}
        patcher = patch.object(runtime, "file_capabilities", return_value=b"")
        patcher.start()
        self.addCleanup(patcher.stop)

    def metadata(self, path, *args, **kwargs):
        return SimpleNamespace(
            **{
                "st_uid": 0,
                "st_gid": 0,
                "st_mode": (stat.S_IFREG if path == self.binary else stat.S_IFDIR)
                | 0o755,
                "st_dev": 1,
                "st_ino": len(str(path)),
                **self.overrides.get(path, {}),
            }
        )

    def context(self):
        # Windows cannot supply real Linux ownership. Only metadata is synthetic;
        # exact bytes are read and ELF-parsed from a real, never executed file.
        return patch.object(Path, "lstat", autospec=True, side_effect=self.metadata)

    def test_immutable_static_pie_and_loader_environment(self):
        with self.context():
            accepted = runtime.inventory(self.binary)
            self.assertEqual(accepted["sha256"], runner.sha(self.binary.read_bytes()))
            self.assertEqual(len(accepted["nodes"]), 1 + len(self.binary.parents))
            env = {
                "LD_PRELOAD": "/home/subject/evil.so",
                "LD_LIBRARY_PATH": "/tmp",
                "LD_AUDIT": "evil",
                "GLIBC_TUNABLES": "x",
                "HOME": "/home/subject",
            }
            runtime.before_exec(str(self.binary), accepted, env)
            self.assertEqual(env, {"HOME": "/home/subject"})

    def test_subject_owned_writable_binary_parent_and_ancestor_rejected(self):
        for path in (self.binary, *self.binary.parents):
            for override in (
                {"st_uid": 1000},
                {
                    "st_mode": (stat.S_IFREG if path == self.binary else stat.S_IFDIR)
                    | 0o775
                },
                {"st_mode": stat.S_IFLNK | 0o777},
            ):
                with self.subTest(path=path, override=override), self.context():
                    self.overrides = {path: override}
                    with self.assertRaises(runner.ExecutionBlocked):
                        runtime.inventory(self.binary)

    def test_script_package_interpreter_and_dynamic_payload_rejected(self):
        for data in (
            b"#!/usr/bin/node\nrequire('./subject-owned-package')",
            elf(interpreter=True),
            *[
                elf(dependencies=(tag,))
                for tag in (1, 15, 29, 0x7FFFFFFD, 0x7FFFFFFF, 0x6FFFFEFB, 0x6FFFFEFC)
            ],
        ):
            with self.subTest(data=data[:20]), self.context():
                self.binary.write_bytes(data)
                with self.assertRaises(runner.ExecutionBlocked):
                    runtime.inventory(self.binary)

    def test_signed_inventory_cannot_be_refreshed_or_command_substituted(self):
        with self.context():
            accepted = runtime.inventory(self.binary)
            for altered in (None, {}, {**accepted, "sha256": "changed"}):
                with self.assertRaises(runner.ExecutionBlocked):
                    runtime.before_exec(str(self.binary), altered, {})
            with self.assertRaises(runner.ExecutionBlocked):
                runtime.before_exec(str(self.binary.parent / "other"), accepted, {})
            self.overrides = {self.binary.parent: {"st_ino": 99999}}
            with self.assertRaises(runner.ExecutionBlocked):
                runtime.before_exec(str(self.binary), accepted, {})
            self.overrides = {}
            self.binary.write_bytes(elf() + b"changed")
            with self.assertRaises(runner.ExecutionBlocked):
                runtime.before_exec(str(self.binary), accepted, {})

    def test_malformed_elf_and_relative_paths_fail_closed(self):
        for data in (elf()[:200], b"plain text", elf(dependencies=(1,))):
            with self.assertRaises(runner.ExecutionBlocked):
                runtime.static_elf(data)
        with self.assertRaises(runner.ExecutionBlocked):
            runtime.inventory("codex")

    def test_privilege_bits_and_capabilities_rejected(self):
        for mode in (0o104755, 0o102755):
            self.overrides = {self.binary: {"st_mode": mode}}
            with self.context(), self.assertRaises(runner.ExecutionBlocked):
                runtime.inventory(self.binary)
        self.overrides = {}
        with (
            self.context(),
            patch.object(runtime, "file_capabilities", return_value=b"capability"),
            self.assertRaises(runner.ExecutionBlocked),
        ):
            runtime.inventory(self.binary)

    def test_probe_refuses_before_any_process_and_preserves_local_default(self):
        with (
            patch.object(runner, "_assert_host_isolation"),
            patch("stage1_ab.vm_guest.native_options", return_value=({}, {})),
            patch.object(runner.subprocess, "run") as process,
        ):
            with self.assertRaisesRegex(runner.ExecutionBlocked, "missing accepted"):
                runner.probe_profile(
                    "codex",
                    self.temp.name,
                    self.temp.name,
                    False,
                    "absent",
                    native_user="subject",
                )
            process.assert_not_called()

    def test_probe_rechecks_between_version_and_login(self):
        with (
            patch.object(runner, "_assert_host_isolation"),
            patch("stage1_ab.vm_guest.native_options", return_value=({}, {})),
            patch.object(
                runtime,
                "before_exec",
                side_effect=[None, runner.ExecutionBlocked("changed after version")],
            ),
            patch.object(
                runner.subprocess,
                "run",
                return_value=SimpleNamespace(returncode=0, stdout="codex", stderr=""),
            ) as process,
        ):
            with self.assertRaisesRegex(
                runner.ExecutionBlocked, "changed after version"
            ):
                runner.probe_profile(
                    "codex",
                    self.temp.name,
                    self.temp.name,
                    False,
                    "absent",
                    native_user="subject",
                    protected_runtime={"accepted": True},
                )
            self.assertEqual(process.call_count, 1)
            self.assertEqual(process.call_args.args[0], ["codex", "--version"])

    def test_functional_diagnostic_rechecks_before_model_process(self):
        import base64

        with (
            patch("stage1_ab.vm_guest.native_options", return_value=({}, {})),
            patch(
                "stage1_ab.vm_subject.call",
                return_value=base64.b64encode(b"synthetic skill").decode(),
            ),
            patch.object(
                runtime,
                "before_exec",
                side_effect=runner.ExecutionBlocked("changed before diagnostic"),
            ),
            patch.object(runner.subprocess, "run") as process,
        ):
            with self.assertRaisesRegex(
                runner.ExecutionBlocked, "changed before diagnostic"
            ):
                runner._functional_skill_smoke(
                    "codex",
                    {},
                    self.binary,
                    native_user="diagnostic",
                    protected_runtime={"accepted": True},
                )
            process.assert_not_called()


if __name__ == "__main__":
    unittest.main()
