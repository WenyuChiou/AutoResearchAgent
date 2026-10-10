"""Offline preparation checks; only original read-only Git probes may spawn."""

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent / "cli/research_workspace_native"
REPO = ROOT.parents[3]


def raw_module(name, path):
    module = ModuleType(name)
    module.__file__ = str(path)
    exec(compile(path.read_bytes(), str(path), "exec"), module.__dict__)
    return module


prep = raw_module("offline_atlas_prepare", ROOT / "atlas_local_prepare.py")
source = raw_module(
    "offline_atlas_prepare_source",
    REPO
    / "plugins/auto-research-agent/cli/research_workspace_native/atlas_local_source.py",
)


def write(path, value):
    raw = source.canonical(value) + b"\n" if isinstance(value, dict) else value
    path.write_bytes(raw)
    return source.digest(raw)


@contextmanager
def fresh_owned_imports():
    cli = REPO / "plugins/auto-research-agent/cli"
    names = {p.stem for p in cli.glob("*.py")} | {
        p.name for p in cli.iterdir() if p.is_dir() and (p / "__init__.py").is_file()
    }

    def owned(name):
        return name.split(".")[0] in names or name == "_atlas_prepare_source"

    old = {k: v for k, v in list(sys.modules.items()) if owned(k)}
    for name in old:
        del sys.modules[name]
    meta, bytecode = sys.meta_path[:], sys.dont_write_bytecode
    try:
        yield
    finally:
        for name in list(sys.modules):
            if owned(name):
                del sys.modules[name]
        sys.modules.update(old)
        sys.meta_path[:] = meta
        sys.dont_write_bytecode = bytecode


class PortablePreparationTests(unittest.TestCase):
    def fixture(self, root):
        view = root / "view"
        view.mkdir()
        assets = {
            name: write(view / name, b"saved fixture bytes\n")
            for name in (
                "atlas.html",
                "atlas.css",
                "atlas-ui.js",
                "atlas-model.js",
                "atlas-data.js",
            )
        }
        index_sha = write(view / "workspace-index.json", {"project_id": "project-one"})
        binding_sha = write(
            view / "atlas-binding.json",
            dict(
                kind="WorkspaceEvidenceAtlas",
                project_id="project-one",
                index_sha256=index_sha,
                execution_authority=False,
                files=assets,
            ),
        )
        brief_sha = write(
            view / "brief.json",
            dict(
                kind="ResearchBrief",
                schema_version="1.0.0",
                original_description="saved fixture",
                needs=[dict(need_id="n1", question="Saved scope question?")],
                scope_fields=[
                    dict(field="geography", material=True, reason="scope pending")
                ],
            ),
        )
        manifest_sha = write(
            view / "view-manifest.json",
            dict(
                kind="WorkspaceReadOnlyView",
                index_sha256=index_sha,
                files={
                    **assets,
                    "workspace-index.json": index_sha,
                    "atlas-binding.json": binding_sha,
                    "brief.json": brief_sha,
                },
            ),
        )
        config_path = root / "host.json"
        config_sha = write(
            config_path,
            dict(
                views=[
                    dict(
                        ref="case",
                        label="Saved case",
                        manifest=(view / "view-manifest.json").as_posix(),
                        sha256=manifest_sha,
                        fixture=True,
                    )
                ]
            ),
        )
        saved = root / "saved-ledger"
        saved.mkdir()
        (saved / "record.txt").write_bytes(b"saved ledger source only\n")
        stages_path = root / "stage-inputs.json"
        stages_sha = write(
            stages_path, {"1": {"ledger_root": saved.as_posix()}, "2": None}
        )
        config = root / "config.toml"
        user_sha = write(config, b"[mcp_servers.known]\nenabled=true\n")
        executable = root / "codex.exe"
        executable_sha = write(
            executable, b"offline executable byte fixture; never run\n"
        )
        helper = (
            REPO
            / "plugins/auto-research-agent/cli/research_workspace_native/atlas_local_source.py"
        )
        return SimpleNamespace(
            repo=REPO,
            source_helper_sha256=source.digest(helper.read_bytes()),
            config=config_path,
            config_sha256=config_sha,
            stage_inputs=stages_path,
            stage_inputs_sha256=stages_sha,
            project_ref="case",
            brief="brief.json",
            model="chosen-model",
            user_config=config,
            user_config_sha256=user_sha,
            executable=executable,
            executable_sha256=executable_sha,
            output=root / "bundle",
            allow_text_session=False,
            accept_text_scope=None,
        )

    def inspect(self, args):
        actual_run, commands = subprocess.run, []
        actual_exists = Path.exists

        def fixture_exists(path):
            # Isolate the synthetic CODEX_HOME from the real user's ancestor config.
            if (
                path.name == "config.toml"
                and path.parent.name == ".codex"
                and not path.is_relative_to(args.user_config.parent)
            ):
                return False
            return actual_exists(path)

        def readonly_git(argv, *positional, **options):
            self.assertEqual(argv[0], "git")
            self.assertEqual(argv[-2:], ["rev-parse", "--show-toplevel"])
            commands.append(argv[:])
            return actual_run(argv, *positional, **options)

        with (
            fresh_owned_imports(),
            patch.dict(os.environ, {"CODEX_HOME": str(args.user_config.parent)}),
            patch.object(subprocess, "run", readonly_git),
            patch.object(Path, "exists", fixture_exists),
        ):
            checked = prep.inspect_inputs(args)
        self.assertGreater(len(commands), 0)
        return checked

    def test_default_checks_saved_inputs_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as folder:
            args = self.fixture(Path(folder).resolve())
            checked = self.inspect(args)
            self.assertEqual(len(checked["manifest"]["source_files"]), 9)
            self.assertIn("mcp_servers.known.enabled", checked["thread_config"])
            with patch.object(prep, "inspect_inputs", return_value=checked):
                result = prep.prepare(args)
            self.assertEqual(result["status"], "checked-only")
            self.assertEqual(result["files_written"], 0)
            self.assertIsNone(result["argv"])
            self.assertFalse(args.output.exists())

    def test_explicit_acceptance_is_required_before_any_inspection(self):
        args = SimpleNamespace(allow_text_session=True, accept_text_scope="yes")
        with patch.object(
            prep, "inspect_inputs", side_effect=AssertionError("not allowed")
        ):
            with self.assertRaisesRegex(ValueError, "exact limited"):
                prep.prepare(args)
            args.allow_text_session = False
            with self.assertRaisesRegex(ValueError, "explicit allow"):
                prep.prepare(args)

    def test_complete_bundle_hashes_model_paths_caps_and_argv(self):
        with tempfile.TemporaryDirectory() as folder:
            args = self.fixture(Path(folder).resolve())
            checked = self.inspect(args)
            docs = prep.bundle_documents(args, checked, 1700000000)
            spec, permit = (
                json.loads(docs[n]) for n in ("runtime-spec.json", "permit.json")
            )
            identity = {k: v for k, v in spec.items() if k != "permit_sha256"}
            self.assertEqual(
                source.digest(source.canonical(identity)),
                permit["spec_identity_sha256"],
            )
            self.assertEqual(source.digest(docs["permit.json"]), spec["permit_sha256"])
            self.assertEqual(
                source.digest(docs["byte-inventory.json"]),
                permit["source_manifest"]["sha256"],
            )
            self.assertEqual(spec["model"], "chosen-model")
            self.assertEqual(
                spec["input_path"], (args.output.parent / "view/brief.json").as_posix()
            )
            self.assertEqual(
                spec["limits"],
                dict(
                    lifetime_seconds=600,
                    max_stream_bytes=1048576,
                    max_text_bytes=4096,
                    max_starts=2,
                    timeout_seconds=30,
                ),
            )
            self.assertEqual(permit["expires_at_unix"], 1700000600)
            self.assertFalse(permit["network_access"])
            self.assertEqual(permit["sandbox"], "read-only")
            argv = json.loads(docs["launcher-argv.json"])
            self.assertIsInstance(argv, list)
            self.assertEqual(argv[0], sys.executable)
            self.assertIn("--enable-native", argv)
            self.assertEqual(
                argv[argv.index("--spec-sha256") + 1],
                source.digest(docs["runtime-spec.json"]),
            )

    def test_explicit_bundle_does_not_create_attempt_and_never_overwrites(self):
        with tempfile.TemporaryDirectory() as folder:
            args = self.fixture(Path(folder).resolve())
            checked = self.inspect(args)
            args.allow_text_session, args.accept_text_scope = (
                True,
                prep.ACCEPT_TEXT_SCOPE,
            )
            with patch.object(prep, "inspect_inputs", return_value=checked):
                result = prep.prepare(args)
                with self.assertRaises(FileExistsError):
                    prep.prepare(args)
            self.assertEqual(result["status"], "prepared-not-started")
            self.assertEqual(
                set(p.name for p in args.output.iterdir()),
                {
                    "byte-inventory.json",
                    "permit.json",
                    "runtime-spec.json",
                    "launcher-argv.json",
                },
            )
            self.assertFalse((args.output / "attempt").exists())

    def test_saved_hash_drift_refuses_before_output(self):
        with tempfile.TemporaryDirectory() as folder:
            args = self.fixture(Path(folder).resolve())
            args.stage_inputs.write_bytes(b'{"1":null,"2":null}\n')
            with self.assertRaisesRegex(ValueError, "pinned bytes differ"):
                self.inspect(args)
            self.assertFalse(args.output.exists())

    def test_brief_escape_and_source_output_overlap_refuse(self):
        with tempfile.TemporaryDirectory() as folder:
            args = self.fixture(Path(folder).resolve())
            args.brief = "../brief.json"
            with self.assertRaisesRegex(ValueError, "unsafe"):
                self.inspect(args)
            args.brief = "brief.json"
            config = json.loads(args.config.read_bytes())
            other = args.output.parent / "other-view"
            other.mkdir()
            for file in (args.output.parent / "view").iterdir():
                (other / file.name).write_bytes(file.read_bytes())
            config["views"].append(
                dict(
                    config["views"][0],
                    ref="other",
                    manifest=(other / "view-manifest.json").as_posix(),
                )
            )
            args.config_sha256 = write(args.config, config)
            args.output = other / "new-bundle"
            with self.assertRaisesRegex(ValueError, "overlap"):
                self.inspect(args)
            self.assertFalse(args.output.exists())

    def test_invalid_or_oversized_brief_refuses_before_any_output(self):
        with tempfile.TemporaryDirectory() as folder:
            args = self.fixture(Path(folder).resolve())
            brief = args.output.parent / "view/brief.json"
            manifest = args.output.parent / "view/view-manifest.json"
            for raw in (b'{"kind":"ResearchBrief"}\n', b" " * 65537):
                brief.write_bytes(raw)
                value = json.loads(manifest.read_bytes())
                value["files"]["brief.json"] = source.digest(raw)
                config = json.loads(args.config.read_bytes())
                config["views"][0]["sha256"] = write(manifest, value)
                args.config_sha256 = write(args.config, config)
                with self.assertRaises(ValueError):
                    self.inspect(args)
                self.assertFalse(args.output.exists())

    def test_inherited_config_and_unknown_mcp_name_refuse(self):
        with tempfile.TemporaryDirectory() as folder:
            args = self.fixture(Path(folder).resolve())
            args.user_config_sha256 = write(
                args.user_config, b'[mcp_servers."unsafe.name"]\nenabled=true\n'
            )
            with self.assertRaisesRegex(ValueError, "named MCP"):
                self.inspect(args)
            args.user_config_sha256 = write(args.user_config, b"[mcp_servers.known]\n")
            layer = args.output.parent / "view/.codex"
            layer.mkdir()
            (layer / "config.toml").write_bytes(b"# another configuration layer\n")
            with self.assertRaisesRegex(ValueError, "additional project"):
                self.inspect(args)

    def test_raw_helper_drift_is_rejected_before_execution(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder).resolve() / "helper.py"
            path.write_bytes(b"raise AssertionError('must not execute')\n")
            with self.assertRaisesRegex(ValueError, "binding differs"):
                prep._raw(path, hashlib.sha256(b"old bytes").hexdigest())
            with self.assertRaisesRegex(ValueError, "regular"):
                prep._raw(path.parent, "0" * 64)

    def test_missing_or_empty_user_config_never_creates_it(self):
        with tempfile.TemporaryDirectory() as folder:
            args = self.fixture(Path(folder).resolve())
            args.user_config.write_bytes(b"")
            with self.assertRaisesRegex(ValueError, "missing or empty"):
                self.inspect(args)
            self.assertEqual(args.user_config.read_bytes(), b"")
            args.user_config.unlink()
            with self.assertRaisesRegex(ValueError, "missing or empty"):
                self.inspect(args)
            self.assertFalse(args.user_config.exists())
            self.assertFalse(args.output.exists())

    def test_late_write_failure_preserves_partial_bundle_without_argv(self):
        with tempfile.TemporaryDirectory() as folder:
            args = self.fixture(Path(folder).resolve())
            checked = self.inspect(args)
            args.allow_text_session, args.accept_text_scope = (
                True,
                prep.ACCEPT_TEXT_SCOPE,
            )
            actual_open = Path.open

            def fail_permit(path, *positional, **options):
                if path == args.output / "permit.json":
                    raise OSError("test write failure")
                return actual_open(path, *positional, **options)

            with (
                patch.object(prep, "inspect_inputs", return_value=checked),
                patch.object(Path, "open", fail_permit),
            ):
                with self.assertRaises(OSError):
                    prep.prepare(args)
            self.assertTrue((args.output / "byte-inventory.json").is_file())
            self.assertFalse((args.output / "launcher-argv.json").exists())


if __name__ == "__main__":
    unittest.main()
