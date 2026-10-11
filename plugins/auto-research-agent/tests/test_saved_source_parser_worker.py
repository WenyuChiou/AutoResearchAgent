"""Offline actual SDK496 + real Windows Job tests, with authored HTTP bytes.

This proves local parser/containment boundaries only, not live HTTP acquisition,
scientific acceptance, UI wiring or a project owner's execution authorization.
"""

import atlas_test_paths  # noqa: F401
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import shutil
import tempfile
import time
import unittest

from research_hub import source_fetch_saved
from research_workspace_native.saved_source_parser_factory import (
    original_deadline_end,
    prepare_saved_parser_runtime,
)
import test_acquired_source_parser as fixtures

REPO = Path(__file__).resolve().parents[3]
DRIVER = r"""
import json, sys, types, time
from pathlib import Path
case = json.loads(Path(sys.argv[1]).read_text(encoding="utf8"))
repo = Path(case["repo"])
helper_path = repo / "plugins/auto-research-agent/cli/research_workspace_native/atlas_local_source.py"
helper = types.ModuleType("_saved_parser_raw_parent")
exec(compile(helper_path.read_bytes(), str(helper_path), "exec"), helper.__dict__)
files = helper.inventory(repo / "plugins/auto-research-agent")
loader = helper.PinnedLoader(repo, files)
helper.__file__ = str(helper_path)
sys.modules["research_workspace_native.atlas_local_source"] = helper
sys.meta_path.insert(0, loader)
from research_workspace_native.portable_source_worker_profile import prepare_source_worker_profile
from research_workspace_native.source_worker_runner import ContainedSourceJobRunner
from research_workspace_native.saved_source_parser_factory import ContainedSavedSourceParserFactory
from research_workspace_native.acquired_source_parser import parse_acquired_source
profile = prepare_source_worker_profile(repo=repo, materials_root=case["root"], runtime_sha256="1"*64)
worker = ContainedSourceJobRunner(profile.document["worker"])
args = case["arguments"]
request = args["expected_request"]
# Same original request/bindings: fixture resolver declaration becomes the
# physically pinned resolver before the authored receipt is admitted.
request["resolver_sha256"] = worker.resolver_sha256
receipt_path = Path(args["acquisition_receipt_path"])
receipt = helper.decode(receipt_path.read_bytes())
receipt["request"] = request
receipt["request_sha256"] = helper.digest(helper.canonical(request))
receipt_path.write_bytes(helper.canonical(receipt) + b"\n")
args["expected_acquisition_sha256"] = helper.digest(receipt_path.read_bytes())
before = receipt_path.read_bytes()
class OriginalDeadline:
    def __init__(self):
        from datetime import datetime, timezone
        declared = datetime.fromisoformat(request["deadline_utc"])
        self.until = time.monotonic() + (declared - datetime.now(timezone.utc)).total_seconds()
    def check(self):
        if time.monotonic() >= self.until:
            raise TimeoutError("original source deadline expired")
deadline = OriginalDeadline()
factory = ContainedSavedSourceParserFactory(worker=worker, runtime=case["runtime"])
checks = 0
def current():
    global checks
    checks += 1
    if case["mode"] == "revoked" and worker.observations and worker.observations[-1]["sdk_parse_observed"]:
        raise ValueError("authored owner revoked before publication")
parser = factory.bind(request=request, deadline=deadline, check_current=current)
args.update(deadline=deadline, parser_runner=parser, check_current=current)
try:
    result = parse_acquired_source(**args)
    observed = {"status":"returned", "result":result}
except BaseException as error:
    observed = {"status":"refused", "error":str(error), "error_type":type(error).__name__}
observed.update(observations=worker.observations, owner_checks=checks,
    original_receipt_unchanged=receipt_path.read_bytes()==before,
    source_bundle_exists=(Path(args["parser_output_dir"])/"source-acquisition-parse-bundle.json").exists())
observed["worker_stderr"] = [p.read_text(encoding="utf8",errors="replace") for p in Path(case["root"]).glob("p*/stderr.prefix")]
Path(case["result_path"]).write_text(json.dumps(observed), encoding="utf8")
"""


@unittest.skipUnless(os.name == "nt", "actual Windows Job containment")
class SavedSourceParserWorkerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixtures.AcquiredSourceParserTests.setUpClass()
        cls.evidence_root = Path(
            tempfile.mkdtemp(
                prefix="saved-parser-evidence-",
                dir=fixtures.AcquiredSourceParserTests.private_root,
            )
        ).resolve()
        cls.snapshot_repo = cls.evidence_root / "repo"
        shutil.copytree(
            REPO / "plugins/auto-research-agent",
            cls.snapshot_repo / "plugins/auto-research-agent",
            symlinks=True,
            ignore=shutil.ignore_patterns(
                "__pycache__", ".ruff_cache", ".pytest_cache"
            ),
        )
        cached_case = os.environ.get("SAVED_PARSER_RUNTIME_FIXTURE")
        if cached_case:
            # An explicit earlier complete inventory fixture. Each SDK file
            # and every used dependency still repins in the actual child.
            cls.runtime = json.loads(Path(cached_case).read_text(encoding="utf8"))[
                "runtime"
            ]
            from research_workspace_native.saved_source_parser_runtime import verify_sdk

            if (
                Path(cls.runtime["sdk_root"])
                != Path(source_fetch_saved.__file__).parent
            ):
                raise ValueError("cached fixture does not use the actual SDK")
            verify_sdk(cls.runtime)
        else:
            cls.runtime = prepare_saved_parser_runtime(
                sdk_root=Path(source_fetch_saved.__file__).parent
            )

    def setUp(self):
        self.fixture = fixtures.AcquiredSourceParserTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def run_case(self, mode):
        arguments, receipt = self.fixture.fixture()
        arguments.pop("deadline")
        arguments.pop("parser_runner")
        request = arguments["expected_request"]
        request["deadline_utc"] = (
            datetime.now(timezone.utc) + timedelta(seconds=60)
        ).isoformat()
        request["total_timeout_seconds"] = 60
        receipt["request"] = request
        self.fixture.rehash(arguments, receipt)
        root = self.fixture.root
        result_path = root / "result.json"
        case = dict(
            repo=str(self.snapshot_repo),
            root=str(root),
            mode=mode,
            runtime=self.runtime,
            arguments={
                name: str(value) if isinstance(value, Path) else value
                for name, value in arguments.items()
            },
            result_path=str(result_path),
        )
        path, script = root / "case.json", root / "driver.py"
        path.write_text(json.dumps(case), encoding="utf8")
        script.write_text(DRIVER, encoding="utf8")
        run = subprocess.run(
            [sys.executable, "-I", "-B", str(script), str(path)],
            capture_output=True,
            check=False,
            timeout=75,
        )
        self.assertEqual(run.returncode, 0, run.stderr.decode("utf8", errors="replace"))
        # Retain real stderr/control records before the generic fixture cleanup.
        shutil.copytree(
            root, self.evidence_root / (mode + "-" + root.name), symlinks=True
        )
        return json.loads(result_path.read_text(encoding="utf8")), root

    def test_actual_sdk_html_preserves_receipts_and_original_deadline_under_job(self):
        observed, root = self.run_case("available")
        self.assertEqual(observed["status"], "returned", observed)
        self.assertTrue(observed["original_receipt_unchanged"])
        self.assertTrue(observed["source_bundle_exists"])
        sdk = json.loads(
            (root / "parser-1/source-fetch-result.json").read_text(encoding="utf8")
        )
        self.assertEqual(sdk["status"], "available")
        self.assertIs(
            sdk["diagnostics"]["saved_import"]["original_http_acquisition_verified"],
            False,
        )
        self.assertEqual(
            [attempt["http_status"] for attempt in sdk["attempts"]], [None, None]
        )
        row = observed["observations"][0]
        self.assertEqual(row["operation"], "parse_saved_manifest")
        self.assertTrue(row["sdk_parse_observed"])
        self.assertFalse(row["source_acquisition_observed"])
        for field in ("containment_admitted", "leader_reaped", "tree_empty_observed"):
            self.assertIs(row["cleanup"][field], True)
        self.assertTrue(row["watchdog"]["thread_joined"])
        self.assertTrue(row["streams"]["threads_joined"])
        self.assertTrue(row["within_original_deadline"])
        self.assertGreater(observed["owner_checks"], 4)

    def test_actual_sdk_output_retained_but_owner_revocation_refuses_bundle(self):
        observed, root = self.run_case("revoked")
        self.assertEqual(observed["status"], "refused", observed)
        self.assertIn("owner revoked", observed["error"])
        self.assertTrue((root / "parser-1/source-fetch-result.json").is_file())
        self.assertFalse(observed["source_bundle_exists"])
        self.assertTrue(observed["original_receipt_unchanged"])

    def test_checker_only_deadline_and_modified_sdk_binding_refuse(self):
        with self.assertRaisesRegex(ValueError, "absolute-original-deadline"):
            original_deadline_end(fixtures.FixtureDeadline())
        changed = json.loads(json.dumps(self.runtime))
        changed["sdk_tree_sha256"] = "f" * 64
        from research_workspace_native.saved_source_parser_runtime import configuration

        with self.assertRaisesRegex(ValueError, "sdk-tree-binding"):
            configuration(changed)

    def test_reused_windows_job_watchdog_kills_hung_child_with_same_end(self):
        from research_workspace_native.source_worker_process import (
            WindowsJobProcess,
            WindowsJobWatchdog,
        )

        started = time.monotonic()
        cutoff, end = started + 0.7, started + 2
        process = WindowsJobProcess.launch(
            sys.executable,
            ["-I", "-S", "-B", "-c", "import time; time.sleep(30)"],
            str(self.fixture.root),
            dict(os.environ),
            absolute_end=cutoff,
            cleanup_end=end,
        )
        watchdog = WindowsJobWatchdog(process, cutoff, end)
        process.resume()
        while process.poll() is None and time.monotonic() < end:
            time.sleep(0.02)
        cleanup, watch = process.cleanup(end), watchdog.finish()
        for field in ("containment_admitted", "leader_reaped", "tree_empty_observed"):
            self.assertIs(cleanup[field], True, cleanup)
        self.assertTrue(watch["thread_joined"], watch)
        self.assertLess(time.monotonic() - started, 2)
        for stream in (process.stdin, process.stdout, process.stderr):
            if stream is not None:
                stream.close()


if __name__ == "__main__":
    unittest.main()
