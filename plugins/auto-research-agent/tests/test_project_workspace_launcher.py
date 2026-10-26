"""Offline launcher/source-loader tests; no Codex process or model is invoked."""

import hashlib
import json
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

PLUGIN = Path(__file__).resolve().parents[1]
EXAMPLES = PLUGIN / "references/research-workspace/examples"
SCRIPT = EXAMPLES / "run-project-workspace.py"
LAUNCHER = runpy.run_path(str(SCRIPT))
HELPER = PLUGIN / "cli/research_workspace_native/atlas_local_source.py"


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


class ProjectWorkspaceLauncherTests(unittest.TestCase):
    def setUp(self):
        # Generic path/source cases use CI TEMP; test the Windows short-root
        # policy separately rather than assuming CI provides a short TEMP.
        self.path_policy = patch.dict(
            LAUNCHER["inspect_inputs"].__globals__,
            windows_root_preflight=lambda root, **kwargs: None,
        )
        self.path_policy.start()
        self.temp = tempfile.TemporaryDirectory(prefix="up-launch-")
        self.root = Path(self.temp.name).resolve()
        # Minimal synthetic source tree tests bootstrap only, not a Stage facade.
        self.repo = self.root / "download"
        self.plugin = self.repo / "plugins/auto-research-agent"
        self.helper = (
            self.plugin / "cli/research_workspace_native/atlas_local_source.py"
        )
        self.helper.parent.mkdir(parents=True)
        (self.helper.parent / "__init__.py").write_bytes(b"")
        shutil.copyfile(HELPER, self.helper)
        self.script = (
            self.plugin / "references/research-workspace/examples" / SCRIPT.name
        )
        self.script.parent.mkdir(parents=True)
        shutil.copyfile(SCRIPT, self.script)
        self.args = LAUNCHER["parser"]().parse_args(
            [
                "--repo",
                str(self.repo),
                "--source-helper-sha256",
                sha(self.helper.read_bytes()),
                "--projects-root",
                str(self.root / "projects"),
                "--check-only",
            ]
        )

    def tearDown(self):
        self.temp.cleanup()
        self.path_policy.stop()

    def inspect(self):
        # Selected repository must have this launcher's exact bytes.
        return LAUNCHER["inspect_inputs"](self.args)

    def worker(self, code, *args):
        return subprocess.run(
            [sys.executable, "-B", "-X", "utf8", "-c", code, *map(str, args)],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf8",
            timeout=40,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )

    def actual_private_temp(self):
        # A production Windows preflight needs a genuinely short physical path.
        # Each folder is uniquely ours and TemporaryDirectory removes only it.
        directory = Path(tempfile.gettempdir()).anchor if os.name == "nt" else None
        return tempfile.TemporaryDirectory(prefix="ara-pw-", dir=directory)

    def test_default_preflight_never_creates_store_or_selects_model(self):
        checked = self.inspect()
        self.assertEqual(checked["root"], self.root / "projects")
        self.assertIsNone(checked["executable"])
        self.assertFalse(checked["root"].exists())
        self.args.model = "caller-model"
        with self.assertRaisesRegex(ValueError, "enable-content-model"):
            self.inspect()
        self.assertFalse(checked["root"].exists())

    def test_source_job_cap_remains_bounded_before_store_creation(self):
        self.assertEqual(self.args.source_cap_seconds, 60)
        for cap in (0, 301, True):
            with self.subTest(cap=cap):
                self.args.source_cap_seconds = cap
                with self.assertRaisesRegex(ValueError, "source cap"):
                    self.inspect()
                self.assertFalse((self.root / "projects").exists())
        self.args.source_cap_seconds = 120
        self.assertEqual(self.inspect()["root"], self.root / "projects")
        self.assertFalse((self.root / "projects").exists())

    def test_complete_runtime_inventory_has_room_and_keeps_exact_byte_pin(self):
        value = dict(
            kind="ProjectStage1QueryRuntime",
            schema_version="1.0.0",
            pin={
                "code_identity": {
                    "files": {str(i).zfill(80): "a" * 64 for i in range(1000)}
                }
            },
            caps=dict(
                max_attempts=3,
                max_reserved_seconds=200,
                max_results=20,
                validity_seconds=600,
            ),
            backends=["openalex"],
        )
        path = self.root / "runtime.json"
        raw = json.dumps(value).encode("utf8")
        self.assertGreater(len(raw), 65536)
        path.write_bytes(raw)
        load = LAUNCHER["query_runtime_config"]
        self.assertEqual(load(path, sha(raw)), value)
        path.write_bytes(raw + b"\n")
        with self.assertRaisesRegex(ValueError, "bytes differ"):
            load(path, sha(raw))
        self.assertFalse((self.root / "projects").exists())

    def test_helper_launcher_and_views_require_exact_external_bytes(self):
        self.helper.write_bytes(self.helper.read_bytes() + b"\n# changed\n")
        with self.assertRaisesRegex(ValueError, "helper bytes differ"):
            self.inspect()
        self.args.source_helper_sha256 = sha(self.helper.read_bytes())
        original = self.script.read_bytes()
        self.script.write_bytes(original + b"\n# changed\n")
        with self.assertRaisesRegex(ValueError, "launcher must match"):
            self.inspect()
        self.script.write_bytes(original)
        config = self.root / "views.json"
        config.write_text('{"views":[]}', encoding="utf8")
        self.args.views_config = config
        with self.assertRaisesRegex(ValueError, "external configuration"):
            self.inspect()
        self.args.views_sha256 = "0" * 64
        with self.assertRaisesRegex(ValueError, "views config bytes differ"):
            self.inspect()
        self.args.views_sha256 = sha(config.read_bytes())
        self.inspect()

    def test_private_root_rejects_repo_overlap_git_ancestors_and_files(self):
        self.args.projects_root = self.repo / "private"
        with self.assertRaisesRegex(ValueError, "must not overlap"):
            self.inspect()
        self.args.projects_root = self.root / "projects"
        (self.root / ".git").write_text("gitdir: elsewhere", encoding="utf8")
        with self.assertRaisesRegex(ValueError, "outside every Git"):
            self.inspect()
        (self.root / ".git").unlink()
        self.args.projects_root.write_text("not a directory", encoding="utf8")
        with self.assertRaisesRegex(ValueError, "must be a directory"):
            self.inspect()

    def test_windows_sqlite_prefix_checked_before_writes(self):
        check = LAUNCHER["windows_root_preflight"]
        check(Path("D:/rp/projects"), platform="win32")
        with self.assertRaisesRegex(ValueError, "too long"):
            check(Path("D:/" + "a" * 70), platform="win32")
        check(Path("/" + "a" * 70), platform="linux")
        check(Path("D:/rp/projects"), platform="win32", model=True)
        with self.assertRaisesRegex(ValueError, "runtime SQLite layout"):
            check(Path("D:/" + "a" * 42), platform="win32", model=True)

    def test_content_model_requires_explicit_own_home_and_native_executable(self):
        self.args.enable_content_model = True
        with self.assertRaisesRegex(ValueError, "are explicit"):
            self.inspect()
        home = self.root / "own-home"
        home.mkdir()
        (home / "config.toml").write_text('model = "own-model"\n', encoding="utf8")
        executable = self.root / "codex.exe"
        executable.write_bytes(b"synthetic-unexecuted-executable")
        self.args.model, self.args.codex, self.args.codex_home = (
            "own-model",
            str(executable),
            home,
        )
        self.assertEqual(self.inspect()["executable"], executable)
        wrapper = self.root / "codex.cmd"
        wrapper.write_bytes(b"must never run this wrapper")
        self.args.codex = str(wrapper)
        with self.assertRaisesRegex(ValueError, "shell wrappers"):
            self.inspect()
        self.assertFalse((self.root / "projects").exists())

    def test_fresh_process_check_only_is_zero_process_zero_store(self):
        code = """
import runpy, sys, subprocess
from unittest.mock import patch
ns = runpy.run_path(sys.argv[1])
ns['inspect_inputs'].__globals__['windows_root_preflight'] = lambda root, **kwargs: None
with patch('subprocess.Popen', side_effect=AssertionError('native process forbidden')):
    ns['main'](sys.argv[2:])
assert not any(n.startswith('research_workspace_native') for n in sys.modules)
"""
        result = self.worker(
            code,
            self.script,
            "--repo",
            self.repo,
            "--source-helper-sha256",
            self.args.source_helper_sha256,
            "--projects-root",
            self.root / "projects",
            "--check-only",
        )
        self.assertEqual((result.returncode, result.stderr), (0, ""))
        receipt = json.loads(result.stdout)
        self.assertEqual(receipt["model_calls"], 0)
        self.assertEqual(receipt["native_calls"], 0)
        self.assertEqual(receipt["content_model"], "disabled")
        self.assertFalse((self.root / "projects").exists())

    def test_stage1_run_flag_groups_fail_before_store_creation(self):
        request = self.root / "run.json"
        request.write_text("{}", encoding="utf8")
        pin = sha(request.read_bytes())
        cases = (
            ({"stage1_run_request": request}, "external SHA256"),
            ({"stage1_run_request_sha256": pin}, "external SHA256"),
            (
                {
                    "stage1_run_request": request,
                    "stage1_run_request_sha256": pin,
                },
                "enable-stage1-run",
            ),
            ({"enable_stage1_run": True}, "model and public source"),
            (
                {"enable_stage1_run": True, "enable_content_model": True},
                "model and public source",
            ),
            (
                {"enable_stage1_run": True, "enable_public_sources": True},
                "model and public source",
            ),
            (
                {
                    "stage1_run_request": request,
                    "stage1_run_request_sha256": pin,
                    "enable_stage1_run": True,
                    "enable_content_model": True,
                    "enable_public_sources": True,
                    "prepare_only": True,
                },
                "prepare-only",
            ),
        )
        for changes, message in cases:
            with self.subTest(changes=changes):
                args = LAUNCHER["parser"]().parse_args(
                    [
                        "--repo",
                        str(self.repo),
                        "--source-helper-sha256",
                        self.args.source_helper_sha256,
                        "--projects-root",
                        str(self.root / "projects"),
                        "--check-only",
                    ]
                )
                for key, value in changes.items():
                    setattr(args, key, value)
                with self.assertRaisesRegex(ValueError, message):
                    LAUNCHER["inspect_inputs"](args)
                self.assertFalse((self.root / "projects").exists())

    def test_full_source_flag_groups_refuse_before_store_or_bootstrap(self):
        request = self.root / "full-source-run.json"
        request.write_text("{}", encoding="utf8")
        pin = sha(request.read_bytes())
        notes = self.root / "notes"
        notes.mkdir()
        valid = dict(
            enable_stage1_run=True,
            enable_content_model=True,
            enable_public_sources=True,
            enable_stage1_full_source=True,
            stage1_full_notes_root=notes,
            stage1_run_request=request,
            stage1_run_request_sha256=pin,
        )
        cases = (
            (
                dict(enable_stage1_full_source=True),
                "full-source analysis and notes root",
            ),
            (
                dict(stage1_full_notes_root=notes),
                "full-source analysis and notes root",
            ),
            (
                dict(
                    enable_stage1_full_source=True,
                    stage1_full_notes_root=notes,
                ),
                "full-source analysis requires",
            ),
            (
                {
                    **valid,
                    "stage1_run_request": None,
                    "stage1_run_request_sha256": None,
                },
                "full-source analysis requires",
            ),
            (
                {**valid, "stage1_full_notes_root": self.root / "missing"},
                "existing full-source notes directory",
            ),
            (
                {**valid, "stage1_full_notes_root": request},
                "existing full-source notes directory",
            ),
            (
                {**valid, "stage1_full_notes_root": self.root},
                "separate from the project store",
            ),
        )
        for changes, message in cases:
            with self.subTest(changes=changes):
                args = type(self.args)(**vars(self.args))
                for key, value in changes.items():
                    setattr(args, key, value)
                with self.assertRaisesRegex(ValueError, message):
                    LAUNCHER["inspect_inputs"](args)
                self.assertFalse((self.root / "projects").exists())

    def test_stage1_run_request_pin_tamper_and_size_fail_before_bootstrap(self):
        request = self.root / "run.json"
        request.write_text('{"kind":"ProjectStage1RunRequest"}', encoding="utf8")
        base = [
            "--repo",
            str(self.repo),
            "--source-helper-sha256",
            self.args.source_helper_sha256,
            "--projects-root",
            str(self.root / "projects"),
            "--check-only",
            "--enable-stage1-run",
            "--enable-content-model",
            "--enable-public-sources",
            "--stage1-run-request",
            str(request),
        ]
        main_globals = LAUNCHER["main"].__globals__
        with (
            patch.dict(
                main_globals,
                install_source=lambda *_: (_ for _ in ()).throw(
                    AssertionError("raw bootstrap forbidden")
                ),
            ),
            patch("subprocess.Popen", side_effect=AssertionError("process forbidden")),
        ):
            with self.assertRaisesRegex(ValueError, "SHA256 invalid"):
                LAUNCHER["main"](base + ["--stage1-run-request-sha256", "x"])
            original_pin = sha(request.read_bytes())
            request.write_bytes(request.read_bytes() + b" ")
            with self.assertRaisesRegex(ValueError, "bytes differ"):
                LAUNCHER["main"](base + ["--stage1-run-request-sha256", original_pin])
            request.write_bytes(b"x" * 16385)
            with self.assertRaisesRegex(ValueError, "file bound exceeded"):
                LAUNCHER["main"](
                    base + ["--stage1-run-request-sha256", sha(request.read_bytes())]
                )
        self.assertFalse((self.root / "projects").exists())

    def test_fresh_check_only_validates_full_stage1_run_configuration_without_calls(
        self,
    ):
        runtime = self.root / "runtime.json"
        runtime.write_text(
            json.dumps(
                dict(
                    kind="ProjectStage1QueryRuntime",
                    schema_version="1.0.0",
                    pin={"runtime": "synthetic-unexecuted"},
                    caps=dict(
                        max_attempts=1,
                        max_reserved_seconds=60,
                        max_results=1,
                        validity_seconds=60,
                    ),
                    backends=["openalex"],
                )
            ),
            encoding="utf8",
        )
        materials = self.root / "materials"
        materials.mkdir()
        home = self.root / "own-home"
        home.mkdir()
        (home / "config.toml").write_text(
            'model = "synthetic-unexecuted"\n', encoding="utf8"
        )
        executable = self.root / "codex.exe"
        executable.write_bytes(b"synthetic-unexecuted-codex")
        code = """
import json, runpy, subprocess, sys
from unittest.mock import patch
ns = runpy.run_path(sys.argv[1])
ns['inspect_inputs'].__globals__['windows_root_preflight'] = lambda root, **kwargs: None
with patch('subprocess.Popen', side_effect=AssertionError('native process forbidden')):
    assert ns['main'](sys.argv[2:]) == 0
"""
        result = self.worker(
            code,
            self.script,
            "--repo",
            self.repo,
            "--source-helper-sha256",
            self.args.source_helper_sha256,
            "--projects-root",
            self.root / "projects",
            "--stage1-query-runtime",
            runtime,
            "--stage1-query-runtime-sha256",
            sha(runtime.read_bytes()),
            "--stage1-materials-root",
            materials,
            "--enable-public-sources",
            "--enable-content-model",
            "--model",
            "synthetic-unexecuted",
            "--codex",
            executable,
            "--codex-home",
            home,
            "--enable-stage1-run",
            "--check-only",
        )
        self.assertEqual((result.returncode, result.stderr), (0, ""))
        receipt = json.loads(result.stdout)
        self.assertEqual((receipt["native_calls"], receipt["model_calls"]), (0, 0))
        self.assertTrue(receipt["stage1_run_grant_configuration"])
        self.assertEqual(receipt["status"], "filesystem-and-raw-loader-preflight-only")
        self.assertFalse((self.root / "projects").exists())

    def test_loader_raw_compiles_owned_bytes_and_rejects_preloaded_origin(self):
        (self.plugin / "cli/owned_probe.py").write_text(
            "VALUE = 'raw-source'\n", encoding="utf8"
        )
        cache = self.plugin / "cli/__pycache__"
        cache.mkdir()
        (cache / "owned_probe.cpython-311.pyc").write_bytes(b"stale/invalid-pyc")
        code = """
import runpy, sys
ns = runpy.run_path(sys.argv[1]); args = ns['parser']().parse_args(sys.argv[2:])
ns['inspect_inputs'].__globals__['windows_root_preflight'] = lambda root, **kwargs: None
source, files = ns['install_source'](ns['inspect_inputs'](args))
assert source.__spec__.origin == source.__file__
assert source.__spec__.loader is source.__loader__
assert source.__loader__ in sys.meta_path
assert source.__spec__.name == 'research_workspace_native.atlas_local_source'
assert source.__package__ == 'research_workspace_native'
import owned_probe
assert owned_probe.VALUE == 'raw-source'
assert type(owned_probe.__loader__).__name__ == 'PinnedLoader'
print('raw-source-only')
"""
        tail = [
            self.script,
            "--repo",
            self.repo,
            "--source-helper-sha256",
            self.args.source_helper_sha256,
            "--projects-root",
            self.root / "projects",
        ]
        result = self.worker(code, *tail)
        self.assertEqual(
            (result.returncode, result.stdout.strip(), result.stderr),
            (0, "raw-source-only", ""),
        )
        preload = code.replace(
            "source, files = ns['install_source']",
            "sys.modules['owned_probe'] = object()\nsource, files = ns['install_source']",
        )
        rejected = self.worker(preload, *tail)
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("owned modules already loaded", rejected.stderr)
        self.assertFalse((self.root / "projects").exists())

    def test_real_copied_services_prepare_only_raw_bootstrap_no_native_process(self):
        code = """
import runpy, sys, subprocess
from pathlib import Path
from unittest.mock import patch
ns = runpy.run_path(sys.argv[1])
original = subprocess.Popen
def git_only(command, *args, **kwargs):
    assert isinstance(command, (list, tuple)) and Path(command[0]).name.lower() in ('git', 'git.exe'), command
    return original(command, *args, **kwargs)
with patch('subprocess.Popen', side_effect=git_only):
    assert ns['main'](sys.argv[2:]) == 0
"""
        with self.actual_private_temp() as folder:
            result = self.worker(
                code,
                SCRIPT,
                "--projects-root",
                Path(folder).resolve() / "p",
                "--source-helper-sha256",
                sha(HELPER.read_bytes()),
                "--prepare-only",
            )
            self.assertEqual((result.returncode, result.stderr), (0, ""))
            receipt = json.loads(result.stdout)
            self.assertEqual(receipt["status"], "prepared-only")
            self.assertEqual(receipt["content_model"], "disabled")
            self.assertEqual((receipt["native_calls"], receipt["model_calls"]), (0, 0))
            self.assertTrue((Path(folder) / "p/project-intake.sqlite").is_file())

    def test_real_default_portal_http_create_and_stage_reads_zero_native_model(self):
        code = """
import http.client, json, runpy, sys, threading, subprocess
from pathlib import Path
from unittest.mock import patch
ns = runpy.run_path(sys.argv[1]); args = ns['parser']().parse_args(sys.argv[2:])
checked = ns['inspect_inputs'](args); ns['install_source'](checked)
original = subprocess.Popen
def git_only(command, *args, **kwargs):
    assert isinstance(command, (list, tuple)) and Path(command[0]).name.lower() in ('git', 'git.exe'), command
    return original(command, *args, **kwargs)
with patch('subprocess.Popen', side_effect=git_only):
    services = ns['prepare'](args, checked)
    host = services['host_type'](**{k: services[k] for k in (
        'projects', 'models', 'stage1', 'stage2', 'credential', 'files', 'views')},
        host='127.0.0.1', port=0)
    thread = threading.Thread(target=host.serve_forever, daemon=True); thread.start()
    client = http.client.HTTPConnection(*host.server_address, timeout=10)
    headers = {'Authorization': 'Bearer ' + services['credential'],
        'Origin': host.expected_origin, 'Content-Type': 'application/json'}
    try:
        client.request('GET', '/'); response = client.getresponse()
        assert response.status == 200; assert b'projects.js' in response.read()
        client.request('POST', '/api/projects', json.dumps({
            'key':'offline-create', 'topic':'Researcher topic; no saved case adoption'}), headers)
        response = client.getresponse(); created = json.loads(response.read())
        assert response.status == 200; assert created['status'] == 'saved'
        ref = created['project_ref']
        values = {}
        for operation in ('models', 'stage1', 'stage2', 'contract'):
            client.request('GET', '/api/projects/' + ref + '/' + operation, headers=headers)
            response = client.getresponse(); values[operation] = json.loads(response.read())
            assert response.status == 200, (operation, values[operation])
        assert values['models']['connected'] is False
        assert values['models']['research_execution_connected'] is False
        assert values['models']['calls_reserved'] == 0
        client.request('GET', '/api/projects/' + ref + '/models/native', headers=headers)
        response = client.getresponse(); native = json.loads(response.read())
        assert response.status == 200; assert native['connected'] is False
        assert services['models']._providers == {}
        assert services['models']._workers == {}
        print(json.dumps({'http_status':200, 'project_created':True,
            'stage_reads':list(values), 'native_calls':0, 'model_calls':0}))
    finally:
        client.close(); host.shutdown(); thread.join(timeout=5); host.server_close()
        services['models'].close(); services['projects'].close()
"""
        with self.actual_private_temp() as folder:
            result = self.worker(
                code,
                SCRIPT,
                "--projects-root",
                Path(folder).resolve() / "p",
                "--source-helper-sha256",
                sha(HELPER.read_bytes()),
            )
            self.assertEqual((result.returncode, result.stderr), (0, ""))
            receipt = json.loads(result.stdout)
            self.assertEqual(
                receipt["stage_reads"], ["models", "stage1", "stage2", "contract"]
            )
            self.assertEqual((receipt["native_calls"], receipt["model_calls"]), (0, 0))


if __name__ == "__main__":
    unittest.main()
