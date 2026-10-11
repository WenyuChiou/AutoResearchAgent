"""Fake StageModel seam only; no Codex process, account probe or model calls."""

from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cli"))

from research_workspace_native import atlas_local_source as source
from research_workspace_native.project_model_factory import (
    OwnAccountProjectModelFactory,
)
from research_workspace_native.runtime_spec import DENIED_THREAD_CONFIG
from stage1_brief.formal_target import prepare_formal_intake


REPO = Path(__file__).resolve().parents[3]


class FakeStageModel:
    def __init__(self, checked, **kwargs):
        self.checked, self.kwargs = checked, kwargs
        self.calls, self.closed = [], False

    def run(self, key, prompt, deadline):
        self.calls.append("run")
        return {"status": "completed", "synthetic": True}

    def verify_receipt(self, receipt, **expected):
        self.calls.append("verify")
        return receipt

    def status(self):
        self.calls.append("status")
        return {"active": False}

    def answer(self, body, *, pre_admission):
        self.calls.append("answer")
        return {"admission": pre_admission()}

    def interrupt(self, body, *, pre_admission):
        self.calls.append("interrupt")
        return {"admission": pre_admission()}

    def close(self):
        self.closed = True
        return {"synthetic_cleanup": True}


class ProjectModelFactoryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="project-model-factory-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.home = self.root / "account"
        self.home.mkdir()
        self.config = self.home / "config.toml"
        self.config.write_text(
            'model = "synthetic-model"\n[mcp_servers.synthetic]\ncommand = "must-not-launch"\n',
            encoding="utf8",
        )
        self.executable = self.root / "codex.exe"
        self.executable.write_bytes(b"Synthetic test executable. Never launched.")
        self.environment = patch.dict(os.environ, {"CODEX_HOME": str(self.home)})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.auth = lambda token: "local-viewer" if token == "own" else None
        self.created = []

        def fake(checked, **kwargs):
            result = FakeStageModel(checked, **kwargs)
            self.created.append(result)
            return result

        self.fake = fake
        self.context = dict(
            project_id="project-fixture",
            project_ref="project-fixture",
            input_version=1,
            model="synthetic-model",
            operation="suggest-topic",
            deny_only=True,
            trusted_stage_unit=True,
            permit_sha256="0" * 64,
        )
        self.context["brief"] = prepare_formal_intake(
            {
                "original_description": "Synthetic topic",
                "scope_fields": [
                    {
                        "field": "geography",
                        "material": True,
                        "reason": "Explicit synthetic applicability remains pending",
                    }
                ],
                "needs": [{"need_id": "n1", "question": "Synthetic question"}],
            },
            project_id="project-fixture",
            input_version=1,
            request_id="request-fixture",
        )
        self.context["brief_sha256"] = source.digest(
            source.canonical(self.context["brief"]) + b"\n"
        )
        self.context["settings"] = {
            "brief_sha256": self.context["brief_sha256"],
            "budgets": {"model_calls": 1, "seconds": 30},
        }
        self.context["source_sha256"] = source.digest(source.canonical(self.context))

    def factory(self, **kwargs):
        return OwnAccountProjectModelFactory(
            REPO,
            self.executable,
            self.config,
            self.home,
            self.auth,
            "own",
            stage_model_factory=self.fake,
            **kwargs,
        )

    def provider(self, context=None):
        return self.factory()(
            context=deepcopy(self.context if context is None else context),
            admit=lambda event: True,
            output_root=self.root / "native-units",
        )

    def test_constructor_has_zero_process_or_provider_start(self):
        with (
            patch.object(subprocess, "Popen", side_effect=AssertionError("no process")),
            patch.object(subprocess, "run", side_effect=AssertionError("no process")),
        ):
            factory = self.factory()
        self.assertEqual(self.created, [])
        self.assertEqual(factory.thread_config["mcp_servers.synthetic.enabled"], False)
        self.assertEqual(list(self.root.glob("project-model-input")), [])

    def test_frozen_snapshot_is_not_workspace_index_and_denials_are_exact(self):
        provider = self.provider()
        checked, kwargs = self.created[0].checked, self.created[0].kwargs
        index = json.loads(checked["index_path"].read_bytes())
        self.assertEqual(index["kind"], "ProjectModelInputSnapshot")
        self.assertFalse(index["canonical_workspace_index"])
        self.assertFalse(index["canonical_stage1_handoff"])
        self.assertFalse(index["execution_authorized"])
        self.assertEqual(checked["stage_inputs"], {1: None, 2: None})
        self.assertEqual(checked["input_version"], self.context["brief_sha256"])
        self.assertEqual(
            source.digest(checked["input_path"].read_bytes()), checked["input_version"]
        )
        self.assertFalse(kwargs["output_root"].is_relative_to(checked["source_root"]))
        self.assertTrue(kwargs["trusted_stage_unit"])
        self.assertTrue(
            all(
                checked["thread_config"][k] == v
                for k, v in DENIED_THREAD_CONFIG.items()
            )
        )
        self.assertTrue(kwargs["admit"]({"phase": "reserve"}))
        self.assertEqual(provider.run("k", "synthetic", 1)["synthetic"], True)
        provider.verify_receipt({"synthetic": True})
        provider.status()
        provider.answer({}, pre_admission=lambda: 1)
        provider.interrupt({}, pre_admission=lambda: 1)
        self.assertEqual(
            self.created[0].calls, ["run", "verify", "status", "answer", "interrupt"]
        )

    def test_normal_production_import_is_rejected_without_loader_or_process(self):
        with patch.object(
            subprocess, "Popen", side_effect=AssertionError("no process")
        ):
            with self.assertRaisesRegex(ValueError, "fresh raw PinnedLoader"):
                OwnAccountProjectModelFactory(
                    REPO, self.executable, self.config, self.home, self.auth, "own"
                )
        self.assertEqual(self.created, [])

    def test_user_config_executable_and_effective_home_edits_refuse_methods(self):
        provider = self.provider()
        raw = self.config.read_bytes()
        self.config.write_bytes(raw + b"\n# changed")
        for callback in (
            provider.status,
            lambda: provider.run("k", "p", 1),
            lambda: provider.answer({}, pre_admission=lambda: 1),
            lambda: provider.interrupt({}, pre_admission=lambda: 1),
        ):
            with self.assertRaisesRegex(ValueError, "pinned bytes differ"):
                callback()
        self.assertEqual(self.created[0].calls, [])
        self.config.write_bytes(raw)
        exe = self.executable.read_bytes()
        self.executable.write_bytes(exe + b"changed")
        with self.assertRaises(ValueError):
            provider.status()
        self.executable.write_bytes(exe)
        with patch.dict(os.environ, {"CODEX_HOME": str(self.root)}):
            with self.assertRaisesRegex(ValueError, "account config root changed"):
                provider.status()

    def test_input_change_refused_and_cleanup_still_attempted(self):
        provider = self.provider()
        self.created[0].checked["input_path"].write_bytes(b"changed raw brief")
        with self.assertRaisesRegex(ValueError, "frozen model input changed"):
            provider.run("k", "p", 1)
        with self.assertRaises(ValueError):
            provider.close()
        self.assertTrue(self.created[0].closed)

    def test_mixed_module_origin_and_package_paths_refused(self):
        provider = self.provider()
        module = sys.modules["research_workspace_native.stage_model"]
        with patch.object(module, "__file__", str(self.root / "foreign.py")):
            with self.assertRaisesRegex(ValueError, "owned module origin differs"):
                provider.status()
        package = sys.modules["research_workspace_native"]
        with patch.object(package, "__path__", [str(self.root)]):
            with self.assertRaisesRegex(ValueError, "owned package paths differ"):
                provider.status()

    def test_source_pass_rechecks_origins_at_both_boundaries_without_cache(self):
        self.provider()
        checked = self.created[0].checked["source"]
        original, calls = checked.verify, []

        def verify():
            calls.append(1)
            original()

        checked.verify = verify
        with checked.verification_pass() as raw:
            raw.read(self.config)
            raw.unlinked(self.config)
            self.assertEqual(len(calls), 1)
        self.assertEqual(len(calls), 2)
        module = sys.modules["research_workspace_native.stage_model"]
        with patch.object(module, "__file__", str(self.root / "foreign.py")):
            with self.assertRaisesRegex(ValueError, "owned module origin differs"):
                with checked.verification_pass():
                    self.fail("changed origin must be refused before entry")
        mutation = patch.object(module, "__file__", str(self.root / "foreign.py"))
        try:
            with self.assertRaisesRegex(ValueError, "owned module origin differs"):
                with checked.verification_pass():
                    mutation.start()
        finally:
            mutation.stop()
        with checked.verification_pass() as raw:
            raw.read(self.config)
        self.assertEqual(len(calls), 7)

    def test_context_raw_hash_or_deny_only_change_rejected_before_snapshot(self):
        for replacement in ({"brief_sha256": "1" * 64}, {"deny_only": False}):
            altered = deepcopy(self.context)
            altered.update(replacement)
            altered["source_sha256"] = source.digest(
                source.canonical(
                    {k: v for k, v in altered.items() if k != "source_sha256"}
                )
            )
            with self.assertRaises(ValueError):
                self.provider(altered)
        self.assertEqual(self.created, [])
        self.assertFalse((self.root / "project-model-input").exists())

    def test_explicit_installed_executable_own_config_and_fresh_output_required(self):
        bad = self.root / "wrapper.cmd"
        bad.write_bytes(b"must not launch")
        with self.assertRaisesRegex(ValueError, "Codex executable"):
            OwnAccountProjectModelFactory(
                REPO,
                bad,
                self.config,
                self.home,
                self.auth,
                "own",
                stage_model_factory=self.fake,
            )
        with self.assertRaisesRegex(ValueError, "own-account config"):
            OwnAccountProjectModelFactory(
                REPO,
                self.executable,
                self.config,
                self.root,
                self.auth,
                "own",
                stage_model_factory=self.fake,
            )
        with self.assertRaisesRegex(ValueError, "principal"):
            OwnAccountProjectModelFactory(
                REPO,
                self.executable,
                self.config,
                self.home,
                self.auth,
                "other",
                stage_model_factory=self.fake,
            )
        self.provider()
        with self.assertRaisesRegex(ValueError, "overlap or reuse"):
            self.provider()

    def test_fresh_raw_loader_accepts_production_constructor_without_native_start(self):
        worker = """
import os, sys
from pathlib import Path
from types import ModuleType
from unittest.mock import patch
repo, exe, config, home = (Path(value) for value in sys.argv[1:])
helper = repo / "plugins/auto-research-agent/cli/research_workspace_native/atlas_local_source.py"
raw = helper.read_bytes()
source = ModuleType("_test_raw_project_source")
source.__file__ = str(helper)
sys.modules[source.__name__] = source
exec(compile(raw, str(helper), "exec"), source.__dict__)
files = source.inventory(repo / "plugins/auto-research-agent")
loader = source.PinnedLoader(repo, files)
sys.meta_path.insert(0, loader)
from research_workspace_native.project_model_factory import OwnAccountProjectModelFactory
with patch("subprocess.Popen", side_effect=AssertionError("no native start")), patch("subprocess.run", side_effect=AssertionError("no probe")):
    value = OwnAccountProjectModelFactory(repo, exe, config, home, lambda _: "local-viewer", "test-token")
assert value.loader is loader
assert value.test_seam is False
print("raw-loader-constructor-only")
"""
        result = subprocess.run(
            [
                sys.executable,
                "-X",
                "utf8",
                "-c",
                worker,
                str(REPO),
                str(self.executable),
                str(self.config),
                str(self.home),
            ],
            capture_output=True,
            text=True,
            timeout=90,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "raw-loader-constructor-only")


if __name__ == "__main__":
    unittest.main()
