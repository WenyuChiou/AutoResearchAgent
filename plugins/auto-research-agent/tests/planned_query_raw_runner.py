"""Test-only fresh raw-loader process; never launches Hub, Codex or models."""

import argparse
import hashlib
import subprocess
from pathlib import Path
import re
import shutil
import sys
import tempfile
import types
import unittest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--test", action="append", required=True)
    args = parser.parse_args()
    if not all(re.fullmatch(r"[A-Za-z0-9_.]{1,200}", name) for name in args.test):
        raise ValueError("test selector required")
    repo = Path(__file__).resolve().parents[3]
    tests = repo / "plugins/auto-research-agent/tests"
    with tempfile.TemporaryDirectory(prefix="pq-raw-") as temporary:
        snapshot = Path(temporary).resolve()
        plugin = snapshot / "plugins/auto-research-agent"
        shutil.copytree(
            repo / "plugins/auto-research-agent/cli",
            plugin / "cli",
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
        shutil.copytree(
            repo / "plugins/auto-research-agent/schemas", plugin / "schemas"
        )
        files = {
            "cli/" + p.relative_to(plugin / "cli").as_posix(): hashlib.sha256(
                p.read_bytes()
            ).hexdigest()
            for p in (plugin / "cli").rglob("*")
            if p.is_file()
        }
        helper = types.ModuleType("research_workspace_native.atlas_local_source")
        helper.__file__ = str(
            plugin / "cli/research_workspace_native/atlas_local_source.py"
        )
        exec(
            compile(Path(helper.__file__).read_bytes(), helper.__file__, "exec"),
            helper.__dict__,
        )
        loader = helper.PinnedLoader(snapshot, files)
        sys.meta_path.insert(0, loader)
        sys.modules[helper.__name__] = helper
        sys.path[:0] = [str(plugin / "cli"), str(tests), str(tests)]
        import planned_query_fixture

        planned_query_fixture.RAW_SOURCE_PROOF = {"repo": str(snapshot), "files": files}
        suite = unittest.defaultTestLoader.loadTestsFromNames(args.test)
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        return int(not result.wasSuccessful())


def run_cases(module, testcase):
    command = [
        sys.executable,
        "-I",
        "-B",
        "-X",
        "utf8",
        str(Path(__file__).resolve()),
        "--test",
        module,
    ]
    result = subprocess.run(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=240,
        shell=False,
    )
    log = result.stdout.decode("utf8", errors="replace")
    testcase.assertEqual(result.returncode, 0, log)
    testcase.assertRegex(
        log, r"Ran [1-9][0-9]* tests?", "inner scenarios must actually run"
    )


if __name__ == "__main__":
    raise SystemExit(main())
