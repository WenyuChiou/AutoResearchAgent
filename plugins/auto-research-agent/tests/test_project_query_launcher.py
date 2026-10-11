"""Pinned query launcher fixtures; no Hub, Codex, model or search execution."""

import hashlib
import json
from pathlib import Path
import runpy
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

PLUGIN = Path(__file__).resolve().parents[1]
SCRIPT = PLUGIN / "references/research-workspace/examples/run-project-workspace.py"
HELPER = PLUGIN / "cli/research_workspace_native/atlas_local_source.py"
LAUNCHER = runpy.run_path(str(SCRIPT))


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def configuration():
    return dict(
        kind="ProjectStage1QueryRuntime",
        schema_version="1.0.0",
        pin={"fixture": "saved bytes; never an executable runtime"},
        caps=dict(
            max_attempts=2, max_reserved_seconds=64, max_results=3, validity_seconds=600
        ),
        backends=["openalex"],
    )


class ProjectQueryLauncherTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="project-query-launch-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.repo = self.root / "download"
        self.plugin = self.repo / "plugins/auto-research-agent"
        self.helper = (
            self.plugin / "cli/research_workspace_native/atlas_local_source.py"
        )
        self.helper.parent.mkdir(parents=True)
        shutil.copyfile(HELPER, self.helper)
        self.script = (
            self.plugin / "references/research-workspace/examples" / SCRIPT.name
        )
        self.script.parent.mkdir(parents=True)
        shutil.copyfile(SCRIPT, self.script)
        self.config_path = self.root / "query-runtime.json"
        self.write_config(configuration())
        self.args = LAUNCHER["parser"]().parse_args(self.arguments())
        self.path_policy = patch.dict(
            LAUNCHER["inspect_inputs"].__globals__,
            windows_root_preflight=lambda root, **kwargs: None,
        )
        self.path_policy.start()
        self.addCleanup(self.path_policy.stop)

    def write_config(self, value=None, *, raw=None):
        if raw is None:
            raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode(
                "utf8"
            )
        self.config_path.write_bytes(raw)
        if hasattr(self, "args"):
            self.args.stage1_query_runtime_sha256 = sha(raw)

    def arguments(self):
        return [
            "--repo",
            str(self.repo),
            "--source-helper-sha256",
            sha(self.helper.read_bytes()),
            "--projects-root",
            str(self.root / "projects"),
            "--stage1-query-runtime",
            str(self.config_path),
            "--stage1-query-runtime-sha256",
            sha(self.config_path.read_bytes()),
        ]

    def inspect(self):
        with patch("subprocess.Popen", side_effect=AssertionError("process forbidden")):
            return LAUNCHER["inspect_inputs"](self.args)

    def worker(self, code):
        return subprocess.run(
            [
                sys.executable,
                "-B",
                "-X",
                "utf8",
                "-c",
                code,
                str(self.script),
                *self.arguments(),
            ],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf8",
            timeout=30,
        )

    def fake_services(self):
        """Exercise real raw-loader wiring with clearly synthetic service classes."""
        package = self.helper.parent
        modules = {
            "__init__.py": "CLOSED = []\n",
            "atlas_host.py": "def load_views(*args): return {}, []\n",
            "http.py": "def token_authenticator(tokens): return tokens.get\n",
            "project_host.py": "class ProjectHost: pass\n",
            "project_intake.py": (
                "from . import CLOSED\n"
                "class ProjectIntakeService:\n"
                " def __init__(self, root, **kwargs): self.root = root\n"
                " def close(self): CLOSED.append('intake')\n"
            ),
            "project_model.py": (
                "from . import CLOSED\n"
                "class ProjectModelService:\n"
                " def __init__(self, intake, **kwargs): self.intake = intake\n"
                " def close(self): CLOSED.append('models')\n"
            ),
            "project_stage1.py": (
                "class ProjectStage1Service:\n"
                " def __init__(self, intake): self.intake = intake\n"
            ),
            "project_stage2.py": (
                "class ProjectStage2Service:\n"
                " def __init__(self, intake): self.intake = intake\n"
            ),
            "project_stage1_queries.py": (
                "from . import CLOSED\n"
                "from .atlas_local_source import PinnedLoader\n"
                "class ProjectStage1QueryService:\n"
                " def __init__(self, stage1, **kwargs):\n"
                "  assert isinstance(__loader__, PinnedLoader)\n"
                "  self.stage1, self.kwargs = stage1, kwargs\n"
                "  stage1.query_service = self\n"
                " def close(self): CLOSED.append('queries')\n"
            ),
        }
        for name, text in modules.items():
            (package / name).write_text(text, encoding="utf8")

    def test_runtime_pair_and_hash_are_required_before_store_or_import(self):
        expected = self.args.stage1_query_runtime_sha256
        self.args.stage1_query_runtime_sha256 = None
        with self.assertRaisesRegex(ValueError, "required together"):
            self.inspect()
        self.args.stage1_query_runtime_sha256 = expected
        self.args.stage1_query_runtime = None
        with self.assertRaisesRegex(ValueError, "required together"):
            self.inspect()
        self.args.stage1_query_runtime = self.config_path
        for digest in ("invalid", "0" * 64):
            self.args.stage1_query_runtime_sha256 = digest
            with self.subTest(digest=digest), self.assertRaises(ValueError):
                self.inspect()
        self.assertFalse((self.root / "projects").exists())

    def test_strict_json_schema_caps_and_backends_fail_without_process(self):
        bad = []
        for key, value in (
            ("kind", "OtherRuntime"),
            ("schema_version", "2.0.0"),
            ("pin", []),
            ("backends", ["arbitrary"]),
            ("backends", ["openalex", "openalex"]),
            ("backends", []),
        ):
            item = configuration()
            item[key] = value
            bad.append(item)
        item = configuration()
        item["browser_path"] = "untrusted"
        bad.append(item)
        item = configuration()
        del item["pin"]
        bad.append(item)
        for key, value in (
            ("max_attempts", True),
            ("max_attempts", 129),
            ("max_reserved_seconds", 0),
            ("max_results", 1001),
            ("validity_seconds", 86401),
        ):
            item = configuration()
            item["caps"][key] = value
            bad.append(item)
        for item in bad:
            with self.subTest(value=item):
                self.write_config(item)
                with self.assertRaises(ValueError):
                    self.inspect()
        for raw in (
            b"{",
            b"\xff",
            b"{}" + b" " * 65536,
            b'{"kind":"first","kind":"second"}',
            b'{"pin":NaN}',
        ):
            with self.subTest(raw=raw[:40]):
                self.write_config(raw=raw)
                with self.assertRaises(ValueError):
                    self.inspect()
        self.assertFalse((self.root / "projects").exists())

    def test_fresh_check_only_pins_fake_runtime_without_owned_import_or_probe(self):
        code = """
import json, runpy, subprocess, sys
from unittest.mock import patch
ns = runpy.run_path(sys.argv[1])
ns['inspect_inputs'].__globals__['windows_root_preflight'] = lambda root, **kw: None
with patch('subprocess.Popen', side_effect=AssertionError('runtime process forbidden')):
    assert ns['main']([*sys.argv[2:], '--check-only']) == 0
assert not any(name.startswith('research_workspace_native') for name in sys.modules)
"""
        result = self.worker(code)
        self.assertEqual((result.returncode, result.stderr), (0, ""))
        receipt = json.loads(result.stdout)
        self.assertEqual((receipt["native_calls"], receipt["model_calls"]), (0, 0))
        self.assertEqual(receipt["status"], "filesystem-and-raw-loader-preflight-only")
        self.assertIn("separate UI authorization", receipt["stage1"])
        self.assertFalse(receipt["execution_authorized"])
        self.assertFalse((self.root / "projects").exists())

    def test_result_cap_matches_project_query_service_one_hundred_limit(self):
        value = configuration()
        value["caps"]["max_results"] = 100
        self.write_config(value)
        self.assertEqual(self.inspect()["query_runtime"]["value"], value)
        for maximum in (101, 1001):
            with self.subTest(maximum=maximum):
                value["caps"]["max_results"] = maximum
                self.write_config(value)
                with self.assertRaisesRegex(ValueError, "bounded.*caps"):
                    self.inspect()
        self.assertFalse((self.root / "projects").exists())

    def test_real_raw_loader_attaches_fake_bridge_and_rechecks_config_at_gates(self):
        self.fake_services()
        code = """
import hashlib, json, runpy, subprocess, sys
from pathlib import Path
from unittest.mock import patch
ns = runpy.run_path(sys.argv[1]); args = ns['parser']().parse_args(sys.argv[2:])
ns['inspect_inputs'].__globals__['windows_root_preflight'] = lambda root, **kw: None
with patch('subprocess.Popen', side_effect=AssertionError('runtime process forbidden')):
    checked = ns['inspect_inputs'](args)
    source, files = ns['install_source'](checked)
    assert 'research_workspace_native.atlas_local_source' not in sys.modules
    services = ns['prepare'](args, checked, source=source, inventory=files)
    queries = services['queries']
    assert queries is services['stage1'].query_service
    proof = queries.kwargs['verify_source']({})
    assert proof == {'repo': checked['repo'].as_posix(), 'files': files}
    assert queries.kwargs['execution_source_sha256'] == hashlib.sha256(source.canonical(files)).hexdigest()
    assert 'cli/research_workspace_native/project_stage1_queries.py' in files
    assert sys.modules['research_workspace_native.atlas_local_source'] is source
    assert queries.kwargs['admit']({}) is True
    proof['files'].clear()
    assert queries.kwargs['verify_source']({})['files'] == files
    args.stage1_query_runtime.write_bytes(args.stage1_query_runtime.read_bytes() + b' ')
    for name in ('verify_source', 'admit'):
        try: queries.kwargs[name]({})
        except ValueError as error: assert 'bytes differ' in str(error)
        else: raise AssertionError('changed config accepted at ' + name)
    queries.close(); services['models'].close(); services['projects'].close()
print('fake bridge attached; raw module identity and drift refusal verified')
"""
        result = self.worker(code)
        self.assertEqual((result.returncode, result.stderr), (0, ""))
        self.assertIn("drift refusal verified", result.stdout)
        self.assertFalse((self.root / "projects").exists())

    def test_preparation_refuses_config_drift_before_importing_owned_services(self):
        self.fake_services()
        code = """
import runpy, subprocess, sys
from unittest.mock import patch
ns = runpy.run_path(sys.argv[1]); args = ns['parser']().parse_args(sys.argv[2:])
ns['inspect_inputs'].__globals__['windows_root_preflight'] = lambda root, **kw: None
with patch('subprocess.Popen', side_effect=AssertionError('runtime process forbidden')):
    checked = ns['inspect_inputs'](args)
    source, files = ns['install_source'](checked)
    args.stage1_query_runtime.write_bytes(args.stage1_query_runtime.read_bytes() + b' ')
    try: ns['prepare'](args, checked, source=source, inventory=files)
    except ValueError as error: assert 'bytes differ' in str(error)
    else: raise AssertionError('changed config accepted during prepare')
assert not any(name.startswith('research_workspace_native') for name in sys.modules)
"""
        result = self.worker(code)
        self.assertEqual((result.returncode, result.stderr), (0, ""))
        self.assertFalse((self.root / "projects").exists())

    def test_prepare_only_main_closes_query_before_intake_with_fake_services(self):
        self.fake_services()
        code = """
import runpy, subprocess, sys
from unittest.mock import patch
ns = runpy.run_path(sys.argv[1])
ns['inspect_inputs'].__globals__['windows_root_preflight'] = lambda root, **kw: None
with patch('subprocess.Popen', side_effect=AssertionError('runtime process forbidden')):
    assert ns['main']([*sys.argv[2:], '--prepare-only']) == 0
from research_workspace_native import CLOSED
assert CLOSED == ['queries', 'models', 'intake'], CLOSED
"""
        result = self.worker(code)
        self.assertEqual((result.returncode, result.stderr), (0, ""))
        receipt = json.loads(result.stdout)
        self.assertEqual(receipt["status"], "prepared-only")
        self.assertFalse(receipt["execution_authorized"])
        self.assertFalse((self.root / "projects").exists())
