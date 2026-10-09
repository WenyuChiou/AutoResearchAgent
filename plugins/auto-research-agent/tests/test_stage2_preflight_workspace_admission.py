# ruff: noqa: E402 -- import the repository CLI without installing a package.
"""Production capture admits only canaries authenticated by its preflight."""

import copy
import hashlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "cli"))

from stage2_common import Stage2Error
from stage2_live.controller import _ProductionAdapter
from stage2_live.workspace_admission import admit_verified_preflight_workspace


def _sha(data):
    return hashlib.sha256(data).hexdigest()


class PreflightWorkspaceAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()
        self.read_key = "probe-input/nonce.txt"
        self.write_key = "probe-output/result.txt"
        self.read_bytes = b"authenticated nonce"
        self.write_bytes = b"authenticated output"
        for key, data in (
            (self.read_key, self.read_bytes),
            (self.write_key, self.write_bytes),
        ):
            path = self.workspace / key
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        self.preflight = {
            "probe_spec": {
                "kind": "Stage2ProductionRuntimeProbeSpec",
                "schema_version": "1.2.0",
                "probes": {
                    "read": {"source_path": self.read_key},
                    "write": {
                        "output_path": self.write_key,
                        "sha256": _sha(self.write_bytes),
                    },
                },
            }
        }
        self.record = {
            "workspace_start": self._binding({self.read_key: _sha(self.read_bytes)}),
            "workspace_end": self._binding(
                {
                    self.read_key: _sha(self.read_bytes),
                    self.write_key: _sha(self.write_bytes),
                }
            ),
            "archived_files": {
                "archive/workspace-start/" + self.read_key: _sha(self.read_bytes),
                "archive/workspace-end/" + self.read_key: _sha(self.read_bytes),
                "archive/workspace-end/" + self.write_key: _sha(self.write_bytes),
            },
        }
        self.verified = (
            self.record,
            {
                "kind": "Stage2ProductionRuntimePreflight",
                "status": "passed",
                "runtime_gate": True,
                "validation_scope": "production-single",
            },
        )

    def tearDown(self):
        self.temp.cleanup()

    def _binding(self, files):
        return {
            "path": str(self.workspace.resolve()),
            "kind": "directory",
            "sha256": "f" * 64,
            "files": files,
        }

    def test_original_reproducer_now_captures_and_preserves_proven_canaries(self):
        home = self.root / "home"
        sources = self.root / "source-package"
        home.mkdir()
        sources.mkdir()
        (sources / "source.txt").write_text("source", encoding="utf-8")
        native = {
            "codex": "fixture",
            "model": "gpt-test",
            "reasoning": "high",
            "config_bindings": {},
            "policy_bindings": {},
        }
        with (
            patch(
                "stage2_live.controller.preflight_for_environment",
                return_value=self.preflight,
            ),
            patch(
                "stage2_live.controller.verify_environment_start",
                return_value=self.verified,
            ),
            patch("stage2_live.controller.verify_environment_capture"),
            patch(
                "stage2_live.controller.capture_native",
                return_value={
                    "status": "complete",
                    "record_sha256_receipt": "a" * 64,
                    "event_summary": {"thread_id": "fixture"},
                },
            ) as capture,
        ):
            _ProductionAdapter._capture(
                {"prompt": "bounded task"},
                sources,
                {"workspace": self.workspace, "home": home},
                {"native": native},
                self.root / "capture",
            )
        capture.assert_called_once()
        self.assertEqual((self.workspace / self.read_key).read_bytes(), self.read_bytes)
        self.assertEqual(
            (self.workspace / self.write_key).read_bytes(), self.write_bytes
        )
        self.assertTrue((self.workspace / "input.json").is_file())
        self.assertTrue((self.workspace / "sources/source.txt").is_file())

    def test_empty_legacy_workspace_remains_admissible(self):
        empty = self.root / "empty"
        empty.mkdir()
        admit_verified_preflight_workspace(empty, {}, None)

    def test_foreign_and_mutated_files_are_rejected(self):
        (self.workspace / "foreign.txt").write_text("foreign", encoding="utf-8")
        with self.assertRaisesRegex(Stage2Error, "must-start-empty"):
            admit_verified_preflight_workspace(
                self.workspace, self.preflight, self.verified
            )
        (self.workspace / "foreign.txt").unlink()
        (self.workspace / self.write_key).write_bytes(b"mutated")
        with self.assertRaisesRegex(Stage2Error, "hash-mismatch"):
            admit_verified_preflight_workspace(
                self.workspace, self.preflight, self.verified
            )

    def test_missing_authenticated_archive_hash_is_rejected(self):
        changed = copy.deepcopy(self.record)
        changed["archived_files"].pop("archive/workspace-end/" + self.write_key)
        with self.assertRaisesRegex(Stage2Error, "archive-mismatch"):
            admit_verified_preflight_workspace(
                self.workspace, self.preflight, (changed, self.verified[1])
            )

    def test_traversal_and_reserved_task_paths_are_rejected(self):
        for field, value in (
            (("read", "source_path"), "../nonce.txt"),
            (("read", "source_path"), "input.json"),
            (("write", "output_path"), "sources/probe.txt"),
        ):
            with self.subTest(value=value):
                changed = copy.deepcopy(self.preflight)
                changed["probe_spec"]["probes"][field[0]][field[1]] = value
                with self.assertRaisesRegex(Stage2Error, "path-(invalid|reserved)"):
                    admit_verified_preflight_workspace(
                        self.workspace, changed, self.verified
                    )

    def test_symlinked_canary_is_rejected(self):
        with patch("pathlib.Path.is_symlink", return_value=True):
            with self.assertRaisesRegex(Stage2Error, "path-symlink"):
                admit_verified_preflight_workspace(
                    self.workspace, self.preflight, self.verified
                )

    def test_nonempty_legacy_proof_is_rejected(self):
        legacy = copy.deepcopy(self.preflight)
        legacy["probe_spec"]["kind"] = "Stage2RuntimeProbeSpec"
        with self.assertRaisesRegex(Stage2Error, "proof-required"):
            admit_verified_preflight_workspace(self.workspace, legacy, self.verified)

    def test_reserved_case_and_win32_aliases_are_rejected_before_staging(self):
        for value in (
            "Sources/probe.txt",
            "SOURCES/probe.txt",
            "sources./probe.txt",
            "sources /probe.txt",
            "INPUT.JSON",
            "input.json.",
            "Input.Json ",
            ".GIT/probe.txt",
        ):
            with self.subTest(value=value):
                changed = copy.deepcopy(self.preflight)
                changed["probe_spec"]["probes"]["write"]["output_path"] = value
                with self.assertRaisesRegex(Stage2Error, "path-reserved"):
                    admit_verified_preflight_workspace(
                        self.workspace, changed, self.verified
                    )
                self.assertFalse((self.workspace / "input.json").exists())
                self.assertFalse((self.workspace / "sources").exists())


if __name__ == "__main__":
    unittest.main()
