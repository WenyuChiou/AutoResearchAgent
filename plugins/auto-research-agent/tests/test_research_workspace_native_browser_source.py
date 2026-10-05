"""Import-only candidate binding regressions; no browser, server, or native calls."""

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

HELPER = Path(__file__).parent / "browser/native-session/candidate_source.py"
spec = importlib.util.spec_from_file_location("candidate_source_contract", HELPER)
contract = importlib.util.module_from_spec(spec)
spec.loader.exec_module(contract)


class CandidateSourceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.repo = self.root / "candidate"
        self.make_candidate(self.repo)

    def make_candidate(self, root):
        names = set(contract.BASE + contract.SCOPE)
        for name in names:
            base = root / "plugins/auto-research-agent"
            base /= "tests" if name in contract.HELPERS else "cli"
            relative = Path(*name.split("."))
            path = base / relative
            path = (
                path / "__init__.py"
                if name in contract.PACKAGES
                else path.with_suffix(".py")
            )
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('VALUE = "neutral candidate"\n', encoding="utf-8")

    def run_child(self, before="", after="", *, repo=None, scope=True):
        script = f"""
import importlib.util, json, sys
from pathlib import Path
spec = importlib.util.spec_from_file_location('candidate_source', {str(HELPER)!r})
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)
{before}
bound = helper.load_candidate({str(repo or self.repo)!r}, {scope!r})
{after}
print(json.dumps(bound.receipt()))
"""
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        return subprocess.run(
            [sys.executable, "-B", "-X", "utf8", "-c", script],
            capture_output=True,
            text=True,
            timeout=20,
            env=env,
        )

    def fallback(self):
        foreign = self.root / "foreign"
        self.make_candidate(foreign)
        cli = foreign / "plugins/auto-research-agent/cli"
        tests = foreign / "plugins/auto-research-agent/tests"
        return f"sys.path[:0] = [{str(cli)!r}, {str(tests)!r}]"

    def test_complete_candidate_has_exact_actual_origins_and_hashes(self):
        result = self.run_child(before=self.fallback())
        self.assertEqual(result.returncode, 0, result.stderr)
        receipt = json.loads(result.stdout)
        self.assertEqual(Path(receipt["repo"]), self.repo)
        self.assertEqual(set(receipt["modules"]), set(contract.BASE + contract.SCOPE))
        for record in receipt["modules"].values():
            source = Path(record["path"])
            self.assertTrue(source.is_relative_to(self.repo))
            self.assertEqual(
                record["sha256"], hashlib.sha256(source.read_bytes()).hexdigest()
            )

    def test_missing_root_and_partial_candidate_never_use_fallback(self):
        before = self.fallback()
        result = self.run_child(before, repo=self.root / "missing")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("FileNotFoundError", result.stderr)
        source = (
            self.repo
            / "plugins/auto-research-agent/cli/research_workspace_native/session_api.py"
        )
        source.unlink()
        result = self.run_child(before)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("missing or ambiguous candidate module", result.stderr)

    def test_preloaded_foreign_module_is_rejected_before_candidate_import(self):
        result = self.run_child(
            self.fallback() + "\nimport research_workspace_native.session_api"
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("already loaded", result.stderr)

    def test_package_path_expansion_and_origin_replacement_are_rejected(self):
        package = (
            self.repo
            / "plugins/auto-research-agent/cli/research_workspace_native/__init__.py"
        )
        package.write_text('__path__.append("foreign")\n', encoding="utf-8")
        result = self.run_child()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("origin or bytes differ", result.stderr)
        package.write_text("", encoding="utf-8")
        result = self.run_child(
            after="sys.modules['research_workspace_native.session_api'].__file__ = 'foreign.py'"
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("origin or bytes differ", result.stderr)

    def test_changed_source_bytes_fail_post_import_verification(self):
        result = self.run_child(
            after="""
source = Path(sys.modules['research_workspace_native.session_api'].__file__)
source.write_bytes(b'VALUE = "drift"\\n')
"""
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("origin or bytes differ", result.stderr)

    def test_source_snapshots_ignore_stale_bytecode(self):
        source = (
            self.repo
            / "plugins/auto-research-agent/cli/research_workspace_native/session_api.py"
        )
        result = self.run_child(
            before=f"""
import py_compile
source = Path({str(source)!r})
source.write_text('VALUE = "foreign cached!!!"\\n', encoding='utf-8')
py_compile.compile(str(source), doraise=True, invalidation_mode=py_compile.PycInvalidationMode.UNCHECKED_HASH)
source.write_text('VALUE = "neutral candidate"\\n', encoding='utf-8')
""",
            after="assert sys.modules['research_workspace_native.session_api'].VALUE == 'neutral candidate'",
        )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
