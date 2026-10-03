"""A Windows read probe must work without relaxing ConstrainedLanguage."""

import os
import copy
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cli"))
from stage2_live.preflight import (
    PreflightError,
    _allowed_read_commands,
    _read_command_path,
    _validate_probe_spec,
    read_probe_command,
)


class ConstrainedReadTests(unittest.TestCase):
    @unittest.skipUnless(os.name == "nt", "Windows PowerShell execution only")
    def test_read_preserves_nonce_in_constrained_language_and_literal_path(self):
        shell = shutil.which("pwsh") or shutil.which("powershell")
        if shell is None:
            self.skipTest("PowerShell unavailable on this Windows host")
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "probe'[1].txt"
            source.write_text("constrained-read-nonce-74fe", encoding="utf-8")
            result = subprocess.run(
                [
                    shell,
                    "-NoProfile",
                    "-Command",
                    "$ExecutionContext.SessionState.LanguageMode = 'ConstrainedLanguage'; "
                    + read_probe_command(str(source)),
                ],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), "constrained-read-nonce-74fe")

    def test_historical_read_and_cmdlet_are_exact_allowlisted_operations(self):
        allowed = _allowed_read_commands("probe'[1].txt", "windows")
        self.assertIn("[System.IO.File]::ReadAllText('probe''[1].txt')", allowed)
        self.assertNotIn("Write-Output 'fabricated nonce'", allowed)
        self.assertNotIn(read_probe_command("different.txt"), allowed)


class AbsoluteReadBindingTests(unittest.TestCase):
    def spec(self, family="windows"):
        root = "C:/frozen/workspace" if family == "windows" else "/frozen/workspace"
        return {
            "kind": "Stage2ProductionRuntimeProbeSpec",
            "schema_version": "1.1.0",
            "expected": {
                "model": "gpt-5.6-sol",
                "reasoning": "high",
                "sandbox": "workspace-write",
                "network_access": True,
            },
            "executor": {
                "shell_path": "C:/runtime/pwsh.exe"
                if family == "windows"
                else "/bin/sh",
                "shell_sha256": "a" * 64,
                "working_directory": root,
                "family": family,
            },
            "probes": {
                "read": {
                    "event_id": "read",
                    "source_path": "nested/probe.txt",
                    "command_path": root + "/nested/probe.txt",
                    "nonce": "unique-read-nonce",
                },
                "write": {
                    "event_id": "write",
                    "output_path": "result.txt",
                    "sha256": "b" * 64,
                },
                "search": {"event_id": "search"},
                "child": {"event_id": "child", "child_thread_id": "child-thread"},
            },
        }

    def test_absolute_target_matches_same_frozen_relative_source_on_both_platforms(
        self,
    ):
        for family in ("windows", "posix"):
            with self.subTest(family=family):
                spec = self.spec(family)
                self.assertTrue(_validate_probe_spec(spec))
                command = _read_command_path(spec)
                self.assertIn(
                    read_probe_command(command, family),
                    _allowed_read_commands(command, family),
                )
                self.assertNotIn(
                    read_probe_command("different.txt", family),
                    _allowed_read_commands(command, family),
                )

    def test_rejects_outside_different_drive_traversal_relative_and_foreign_paths(self):
        for family, bad_paths in (
            (
                "windows",
                (
                    "C:/foreign/nested/probe.txt",
                    "D:/frozen/workspace/nested/probe.txt",
                    "C:/frozen/workspace/nested/../probe.txt",
                    "C:nested/probe.txt",
                    "nested/probe.txt",
                    "//foreign/share/probe.txt",
                ),
            ),
            (
                "posix",
                (
                    "/foreign/nested/probe.txt",
                    "/frozen/workspace/nested/../probe.txt",
                    "nested/probe.txt",
                    "C:/frozen/workspace/nested/probe.txt",
                ),
            ),
        ):
            for command in bad_paths:
                with self.subTest(family=family, command=command):
                    spec = self.spec(family)
                    spec["probes"]["read"]["command_path"] = command
                    with self.assertRaisesRegex(
                        PreflightError, "bound workspace source"
                    ):
                        _validate_probe_spec(spec)

    def test_legacy_relative_contract_remains_exact_and_formal_does_not_opt_in(self):
        spec = self.spec()
        legacy = copy.deepcopy(spec)
        legacy["schema_version"] = "1.0.0"
        del legacy["probes"]["read"]["command_path"]
        self.assertTrue(_validate_probe_spec(legacy))
        self.assertEqual(_read_command_path(legacy), "nested/probe.txt")
        legacy["probes"]["read"]["source_path"] = "C:/frozen/workspace/nested/probe.txt"
        with self.assertRaisesRegex(PreflightError, "contained relative path"):
            _validate_probe_spec(legacy)
        spec["kind"] = "Stage2RuntimeProbeSpec"
        with self.assertRaisesRegex(PreflightError, "kind/schema_version"):
            _validate_probe_spec(spec)

    def test_missing_extra_and_mismatched_archive_paths_fail_closed(self):
        for change in ("missing-command", "extra-field", "other-source"):
            with self.subTest(change=change):
                spec = self.spec()
                if change == "missing-command":
                    del spec["probes"]["read"]["command_path"]
                elif change == "extra-field":
                    spec["probes"]["read"]["claim_passed"] = True
                else:
                    spec["probes"]["read"]["source_path"] = "other.txt"
                with self.assertRaises(PreflightError):
                    _validate_probe_spec(spec)


if __name__ == "__main__":
    unittest.main()
