"""Changing the script or installed -m package invalidates the frozen runtime."""

from pathlib import Path
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from test_retrieval_execution import runtime
from stage1_ledger.journal import LedgerError, digest
from stage1_ledger.store import Ledger
from stage1_ledger.validation import validate_run
from stage1_retrieval.runner import execute
from stage1_retrieval.runtime_identity import capture_identity, tree_files


class RuntimeIdentityTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def ledger(self, pin):
        return Ledger.create(
            self.root / "run",
            run_id="synthetic",
            objective="Synthetic runtime",
            research_hub_pin=pin,
        )

    def assert_changed(self, ledger):
        query = ledger.start("search", {"query": "synthetic", "limit": 3})
        with patch(
            "stage1_retrieval.runner.subprocess.Popen",
            side_effect=AssertionError("changed CLI must not execute"),
        ):
            with self.assertRaisesRegex(LedgerError, "runtime-code-changed"):
                execute(ledger.root, query, "openalex")
        report = validate_run(ledger.root)
        self.assertFalse(report["valid"])
        self.assertIn("runtime-code-changed", " ".join(report["errors"]))

    def test_runtime_bytes_bound_before_launch_and_on_replay(self):
        pin = runtime(self.root)
        ledger = self.ledger(pin)
        Path(pin["argv_prefix"][-1]).write_text(
            "print('rate limited')\n", encoding="utf-8"
        )
        self.assert_changed(ledger)

    def test_package_mutation_invalidates_real_python_m_environment(self):
        pin = runtime(self.root)
        environment = self.root / "environment"
        subprocess.run(
            [sys.executable, "-m", "venv", "--without-pip", str(environment)],
            check=True,
            capture_output=True,
        )
        executable = environment / (
            "Scripts/python.exe" if os.name == "nt" else "bin/python"
        )
        # Public interpreter metadata, no undocumented research-hub internals.
        site = Path(
            subprocess.check_output(
                [
                    str(executable),
                    "-I",
                    "-B",
                    "-c",
                    "import sysconfig;print(sysconfig.get_path('purelib'))",
                ],
                text=True,
            ).strip()
        )
        package = site / "synthetic_stage1_runtime"
        package.mkdir()
        (package / "__init__.py").write_bytes(b"")
        (package / "__main__.py").write_bytes(Path(pin["argv_prefix"][-1]).read_bytes())
        pin["argv_prefix"] = [str(executable), "-I", "-B", "-m", package.name]
        pin["executable_sha256"] = digest(executable.read_bytes())
        pin["code_identity"] = capture_identity(pin["argv_prefix"])
        ledger = self.ledger(pin)
        query = ledger.start("search", {"query": "synthetic", "limit": 3})
        execute(ledger.root, query, "openalex")
        ledger.complete_query(query)
        ledger.extract()
        self.assertTrue(validate_run(ledger.root)["valid"])
        (package / "__main__.py").write_text(
            "print('changed package')\n", encoding="utf-8"
        )
        self.assert_changed(ledger)

    def test_new_code_file_is_not_hidden_by_old_inventory(self):
        ledger = self.ledger(runtime(self.root))
        (self.root / "shadow.py").write_text("print('new code')\n", encoding="utf-8")
        self.assert_changed(ledger)

    def test_unbound_old_pin_and_relative_entry_are_rejected(self):
        pin = runtime(self.root)
        del pin["code_identity"]
        with self.assertRaises(LedgerError):
            self.ledger(pin)
        with self.assertRaisesRegex(LedgerError, "absolute-file"):
            capture_identity([sys.executable, "-I", "-B", "synthetic_cli.py"])

    def test_inactive_nested_installation_is_not_an_import_root(self):
        inactive = self.root / "Lib" / "site-packages"
        inactive.mkdir(parents=True)
        code = inactive / "synthetic.py"
        code.write_bytes(b"# synthetic")
        self.assertNotIn(str(code.resolve()), tree_files(self.root))
        self.assertIn(str(code.resolve()), tree_files(inactive))

    def test_file_symlinks_bind_external_target_and_target_bytes(self):
        imported = self.root / "imported"
        imported.mkdir()
        first, second = self.root / "first.py", self.root / "second.py"
        first.write_bytes(b"# original")
        second.write_bytes(first.read_bytes())
        link = imported / "linked.py"
        try:
            link.symlink_to(first)
        except OSError:
            self.skipTest("Host does not grant symlink creation")
        original = tree_files(imported)
        self.assertEqual(len(original), 1)
        self.assertIn(str(link.absolute()), original)
        link.unlink()
        link.symlink_to(second)
        retargeted = tree_files(imported)
        self.assertNotEqual(original, retargeted)
        second.write_bytes(b"# changed")
        self.assertNotEqual(retargeted, tree_files(imported))
        second.unlink()
        with self.assertRaises(OSError):
            tree_files(imported)

    def test_freeze_cli_writes_once_and_init_checks_saved_code(self):
        pin = runtime(self.root)
        del pin["code_identity"]
        request = self.root / "request.json"
        request.write_text(json.dumps(pin), encoding="utf-8")
        output = self.root / "frozen.json"
        cli = Path(__file__).resolve().parents[1] / "cli"
        argv = [
            sys.executable,
            "-m",
            "stage1_retrieval",
            "freeze-runtime",
            "--runtime",
            str(request),
            "--output",
            str(output),
        ]
        result = subprocess.run(argv, cwd=cli, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("files_sha256", json.loads(result.stdout))
        original = output.read_bytes()
        self.assertNotEqual(
            subprocess.run(argv, cwd=cli, capture_output=True).returncode, 0
        )
        self.assertEqual(output.read_bytes(), original)
        self.ledger(json.loads(original))
