"""The standalone pilot launcher admits only explicit, unchanged saved inputs."""

import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch


PLUGIN = Path(__file__).resolve().parents[1]
EXAMPLES = PLUGIN / "references/research-workspace/examples"


def example(name, alias):
    spec = importlib.util.spec_from_file_location(alias, EXAMPLES / name)
    module = importlib.util.module_from_spec(spec)
    previous = list(sys.path)
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path[:] = previous
    return module


class NativeStagePilotLauncherTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.launch = example("run-stage-pilot.py", "stage_pilot_launch_test")
        builder = example("build-stage-run-case.py", "stage_pilot_builder_test")
        builder.build(self.root / "case")
        self.case_path = self.root / "case/case.json"
        self.case = json.loads(self.case_path.read_bytes())
        self.args = SimpleNamespace(
            accept_scope=self.launch.SCOPE,
            max_calls=8,
            max_seconds=900,
            permission_id="explicit-owner-approved-pilot",
            model="own-model",
            case=self.case_path,
            case_sha256=self.launch._sha(self.case_path.read_bytes()),
            repo=PLUGIN.parents[1],
            output=self.root / "p",
            port=0,
        )

    def save_case(self):
        self.case_path.write_bytes(self.launch._canonical(self.case))
        self.args.case_sha256 = self.launch._sha(self.case_path.read_bytes())

    def assert_preparation_refused(self, message):
        with patch.object(self.launch, "_inspect") as inspect:
            with patch("subprocess.Popen") as spawn:
                with self.assertRaisesRegex(ValueError, message):
                    self.launch.prepare(self.args)
                inspect.assert_not_called()
                spawn.assert_not_called()
        self.assertFalse(self.args.output.exists())

    def test_pinned_existing_corpus_checked_without_process_or_output(self):
        with patch("subprocess.Popen") as spawn:
            case, paths, repo, output = self.launch.case_inputs(self.args)
            spawn.assert_not_called()
        self.assertEqual(case["source_bindings"], self.case["source_bindings"])
        self.assertEqual(paths["packet_path"], Path(self.case["packet_path"]))
        self.assertEqual(repo, PLUGIN.parents[1])
        self.assertEqual(output, self.args.output)
        self.assertFalse(output.exists())
        self.assertFalse(case["canonical_stage1_to_stage2_lineage"])

    def test_changed_corpus_wrong_external_pin_and_changed_digest_fail_before_prepare(
        self,
    ):
        self.args.case_sha256 = "0" * 64
        self.assert_preparation_refused("case bytes differ")
        self.args.case_sha256 = self.launch._sha(self.case_path.read_bytes())
        source = Path(self.case["source_root"]) / "source-1.txt"
        original = source.read_bytes()
        source.write_bytes(original + b" changed")
        self.assert_preparation_refused("exact two-source")
        source.write_bytes(original)
        self.case["source_binding_sha256"] = "0" * 64
        self.save_case()
        self.assert_preparation_refused("source digest differs")

    def test_all_case_views_stay_inside_exact_case_and_keep_saved_bindings(self):
        config_path = Path(self.case["host_config_path"])
        config = json.loads(config_path.read_bytes())
        config["views"][1]["manifest"] = (self.root / "outside.json").as_posix()
        (self.root / "outside.json").write_bytes(b"not a case view")
        config["views"][1]["sha256"] = self.launch._sha(b"not a case view")
        self.case["view_manifests"]["stage2"] = config["views"][1]
        raw = self.launch._canonical(config)
        config_path.write_bytes(raw)
        self.case["host_config_sha256"] = self.launch._sha(raw)
        self.save_case()
        self.assert_preparation_refused("view outside")

    def test_scope_budget_and_explicit_permission_fail_before_prepare(self):
        for field, value, message in (
            ("max_calls", 9, "max calls"),
            ("max_seconds", 901, "max seconds"),
            ("permission_id", "", "permission reference"),
            ("accept_scope", "", "scope required"),
        ):
            previous = getattr(self.args, field)
            setattr(self.args, field, value)
            self.assert_preparation_refused(message)
            setattr(self.args, field, previous)
        self.args.output.mkdir()
        sentinel = self.args.output / "old.txt"
        sentinel.write_bytes(b"old immutable attempt")
        with patch.object(self.launch, "_inspect") as inspect:
            with self.assertRaisesRegex(ValueError, "new private output"):
                self.launch.prepare(self.args)
            inspect.assert_not_called()
        self.assertEqual(sentinel.read_bytes(), b"old immutable attempt")

    def test_prepare_only_never_starts_server_or_process_and_preserves_attestation(
        self,
    ):
        self.args.output.mkdir()
        service = Mock()
        service.permit = {"source_sha256": self.case["source_binding_sha256"]}
        service.permit_sha = "1" * 64
        self.args.prepare_only = True
        checked = {"index_sha256": self.case["index_sha256"]}
        with patch.object(self.launch, "parser") as parser:
            parser.return_value.parse_args.return_value = self.args
            with patch.object(
                self.launch,
                "prepare",
                return_value=(
                    checked,
                    service,
                    {},
                    [],
                    "memory-only-credential",
                    self.args.output,
                ),
            ):
                with patch("subprocess.Popen") as spawn:
                    self.assertEqual(self.launch.main([]), 0)
                    spawn.assert_not_called()
        service.close.assert_called_once_with()
        receipt = json.loads((self.args.output / "launch-receipt.json").read_bytes())
        self.assertEqual(receipt["native_calls"], 0)
        self.assertNotIn("url", receipt)
        self.assertEqual(receipt["permission_id"], self.args.permission_id)
        self.assertFalse(receipt["canonical_stage1_handoff"])
        self.assertNotIn("memory-only-credential", json.dumps(receipt))

    def test_windows_long_output_refused_before_prepare_process_and_writes(self):
        self.args.output = self.root / ("long-output-" + "x" * 60)
        original = self.launch.windows_output_preflight
        with patch.object(
            self.launch,
            "windows_output_preflight",
            side_effect=lambda output: original(output, platform="win32"),
        ):
            self.assert_preparation_refused("Windows SQLite output path is too long")
        # Platforms with a different SQLite path limit retain their existing guard.
        self.launch.windows_output_preflight(self.args.output, platform="linux")
        self.assertFalse(self.args.output.exists())

    def test_windows_path_bound_includes_owner_sidecar_and_utf16_units(self):
        suffix = (
            "/models/"
            + "0" * 64
            + "/native.sqlite3.owner-"
            + "0" * 64
            + ".sqlite3-journal"
        )
        root = "C:/" if sys.platform == "win32" else "/"
        safe = Path(root + "x" * (239 - len(suffix) - len(root)))
        self.launch.windows_output_preflight(safe, platform="win32")
        with self.assertRaisesRegex(ValueError, "under 240"):
            self.launch.windows_output_preflight(
                Path(str(safe) + "x"), platform="win32"
            )
        # An astral character takes two Windows path units despite one Python character.
        with self.assertRaisesRegex(ValueError, "under 240"):
            self.launch.windows_output_preflight(
                Path(str(safe)[:-1] + "\U0001f4da"), platform="win32"
            )


if __name__ == "__main__":
    unittest.main()
