"""Offline byte/protocol checks only; no real or fake child is launched."""

import atlas_test_paths  # noqa: F401 -- standalone discovery needs the local CLI.

from copy import deepcopy
from pathlib import Path
from types import ModuleType, SimpleNamespace
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent / "cli/research_workspace_native"
if not ROOT.is_dir():
    ROOT = Path(__file__).resolve().parent


def raw_module(alias, path):
    if alias not in sys.modules:
        module = ModuleType(alias)
        module.__file__ = str(path)
        sys.modules[alias] = module
        exec(compile(path.read_bytes(), str(path), "exec"), module.__dict__)
    return sys.modules[alias]


source = raw_module("_atlas_local_source", ROOT / "atlas_local_source.py")
launcher = raw_module("_atlas_local_permit", ROOT / "atlas_local_permit.py")
for name in ("decode", "PinnedLoader"):
    setattr(launcher, name, getattr(source, name))


class LocalLauncherTests(unittest.TestCase):
    def authority(self):
        bound = dict(
            project_ref="case",
            project_id="project-one",
            index_sha256="1" * 64,
            input_version="2" * 64,
            source_root="C:/private/source",
            model="gpt-6-astra",
            executable="C:/bin/codex.exe",
            executable_sha256="3" * 64,
            thread_config={"web_search": "disabled"},
            limits=dict(lifetime_seconds=60, max_text_bytes=4096),
        )
        authority = launcher.PermitAuthority(
            spec=bound,
            spec_path="C:/private/spec.json",
            spec_sha256="4" * 64,
            permit_path="C:/private/permit.json",
            permit_sha256="5" * 64,
            permit=dict(max_turns=2, expires_at_unix=launcher.time.time() + 60),
            manifest={},
            repo=Path("C:/repo"),
        )
        return authority

    def event(self, authority, action):
        return dict(
            spec_sha256=authority.sha,
            permit_sha256=authority.permit_sha,
            spec=deepcopy(authority.spec),
            action=action,
        )

    def lifecycle(self, authority, method):
        params = dict(
            cwd=authority.spec["source_root"],
            model=authority.spec["model"],
            approvalPolicy="on-request",
            sandbox="read-only",
            config=authority.spec["thread_config"],
        )
        return dict(
            project_id=authority.spec["project_id"],
            index_sha256=authority.spec["index_sha256"],
            input_version=authority.spec["input_version"],
            intent_key="new-thread",
            method=method,
            params_sha256=launcher.digest(launcher.canonical(params)),
        )

    def test_spawn_exact_payload_and_epoch_not_caller_true(self):
        authority = self.authority()
        payload = {
            k: authority.spec[k]
            for k in ("executable", "executable_sha256", "input_version")
        }
        payload["cwd"] = authority.spec["source_root"]
        action = dict(
            project_id="project-one",
            index_sha256="1" * 64,
            input_version="2" * 64,
            connection_id="atlas-" + "a" * 32,
            intent_key="spawn",
            payload_sha256=launcher.digest(launcher.canonical(payload)),
            argv=[str(Path("C:/bin/codex.exe")), "app-server", "--stdio"],
        )
        with patch.object(authority, "verify", return_value=True):
            self.assertIs(
                authority.gate("admit_spawn", self.event(authority, action)), True
            )
            for key, value in (
                ("argv", ["C:/bin/codex.exe", "exec"]),
                ("project_id", "other"),
                ("connection_id", "atlas-" + "b" * 32),
                ("payload_sha256", "0" * 64),
            ):
                wrong = dict(action, **{key: value})
                with self.assertRaises(launcher.LauncherError):
                    authority.gate("admit_spawn", self.event(authority, wrong))

    def test_lifecycle_order_and_resume_rejected(self):
        authority = self.authority()
        authority.epoch = "atlas-" + "a" * 32
        with patch.object(authority, "verify", return_value=True):
            with self.assertRaises(launcher.LauncherError):
                authority.gate(
                    "admit_lifecycle",
                    self.event(authority, self.lifecycle(authority, "thread/start")),
                )
            for method in (
                "new-session",
                "initialize",
                "initialized",
                "account/read",
                "thread/start",
                "thread/start",
                "handoff",
            ):
                self.assertIs(
                    authority.gate(
                        "admit_lifecycle",
                        self.event(authority, self.lifecycle(authority, method)),
                    ),
                    True,
                )
            for method in ("thread/resume", "initialize", "turn/start"):
                with self.assertRaises(launcher.LauncherError):
                    authority.gate(
                        "admit_lifecycle",
                        self.event(authority, self.lifecycle(authority, method)),
                    )

    def test_attach_and_action_reject_cross_project_and_limit_turns(self):
        authority = self.authority()
        authority.epoch, authority.phase = "atlas-" + "a" * 32, 5
        attach = {
            k: authority.spec[k]
            for k in (
                "project_ref",
                "project_id",
                "source_root",
                "index_sha256",
                "input_version",
            )
        }
        attach.update(thread_id="native-thread", connection_id=authority.epoch)
        state = dict(thread_id="native-thread", requests={}, intents={})
        controller = SimpleNamespace(
            connection_id=authority.epoch,
            store=SimpleNamespace(snapshot=lambda _: state),
        )
        authority.runtime = SimpleNamespace(_entries=[dict(controller=controller)])
        with patch.object(authority, "verify", return_value=True):
            self.assertIs(
                authority.gate("admit_attach", self.event(authority, attach)), True
            )
            wrong = dict(attach, source_root="C:/other")
            with self.assertRaises(launcher.LauncherError):
                authority.gate("admit_attach", self.event(authority, wrong))
            action = dict(
                project_id="project-one",
                index_sha256="1" * 64,
                thread_id=authority.thread,
                connection_id=authority.epoch,
                method="turn/start",
                request_identity=None,
                request_sha256=None,
                payload=dict(
                    threadId=authority.thread,
                    cwd=authority.spec["source_root"],
                    model="gpt-6-astra",
                    input=[
                        dict(
                            type="text",
                            text="Say connected; no tools or research.",
                            text_elements=[],
                        )
                    ],
                ),
            )
            for _ in range(2):
                self.assertIs(
                    authority.gate("admit_action", self.event(authority, action)), True
                )
            with self.assertRaises(launcher.LauncherError):
                authority.gate("admit_action", self.event(authority, action))
            for method in ("thread/resume", "permissions/requestApproval", "search"):
                with self.assertRaises(launcher.LauncherError):
                    authority.gate(
                        "admit_action",
                        self.event(authority, dict(action, method=method)),
                    )

    def test_expired_gate_and_changed_binding_fail_before_action(self):
        authority = self.authority()
        for event in (
            dict(spec_sha256="wrong", spec=authority.spec),
            dict(
                spec_sha256=authority.sha, spec=dict(authority.spec, model="different")
            ),
        ):
            with self.assertRaises(launcher.LauncherError):
                authority.verify(event)
        with patch.object(
            authority, "verify", side_effect=launcher.LauncherError("lease expired")
        ):
            with self.assertRaises(launcher.LauncherError):
                authority.gate("admit_action", self.event(authority, {}))
        self.assertEqual(authority.starts, 0)

    def real_authority(self, folder):
        root = Path(folder).resolve()
        repo, source = root / "repo", root / "source"
        plugin = repo / "plugins/auto-research-agent"
        plugin.mkdir(parents=True)
        source.mkdir()
        (plugin / "owned.py").write_bytes(b"VALUE = 42\n")
        for name in ("workspace-index.json", "brief.json"):
            (source / name).write_bytes(b"{}")
        exe, config = root / "codex.exe", root / "host.json"
        exe.write_bytes(b"offline byte pin only; never launched")
        config.write_bytes(b"{}")
        manifest_path = root / "inventory.json"
        manifest = dict(
            plugin_files=launcher.inventory(plugin),
            source_files=launcher.inventory(source),
        )
        manifest_path.write_bytes(launcher.canonical(manifest))
        bound = dict(
            project_id="project-one",
            index_sha256=launcher.digest(b"{}"),
            index_path=str(source / "workspace-index.json"),
            input_version=launcher.digest(b"{}"),
            input_path=str(source / "brief.json"),
            source_root=str(source),
            executable=str(exe),
            executable_sha256=launcher.digest(exe.read_bytes()),
            limits=dict(lifetime_seconds=60),
        )
        spec_path, permit_path = root / "spec.json", root / "permit.json"
        spec_path.write_bytes(launcher.canonical(bound))
        permit = dict(
            expires_at_unix=launcher.time.time() + 60,
            user_config=dict(
                path=str(config), sha256=launcher.digest(config.read_bytes())
            ),
            host_config=dict(
                path=str(config), sha256=launcher.digest(config.read_bytes())
            ),
            source_manifest=dict(
                path=str(manifest_path),
                sha256=launcher.digest(manifest_path.read_bytes()),
            ),
        )
        permit_path.write_bytes(launcher.canonical(permit))
        return launcher.PermitAuthority(
            spec=bound,
            spec_path=spec_path,
            spec_sha256=launcher.digest(spec_path.read_bytes()),
            permit_path=permit_path,
            permit_sha256=launcher.digest(permit_path.read_bytes()),
            permit=permit,
            manifest=manifest,
            repo=repo,
        )

    def test_actual_source_drift_and_expiry_during_inventory_refuse_before_mutation(
        self,
    ):
        with tempfile.TemporaryDirectory() as folder:
            authority = self.real_authority(folder)
            event = dict(spec_sha256=authority.sha, spec=authority.spec)
            self.assertIs(authority.verify(event, full=True), True)
            clock = [authority.deadline - 1]
            actual_inventory = launcher.inventory

            def expire_inventory(path):
                value = actual_inventory(path)
                clock[0] = authority.deadline + 1
                return value

            with (
                patch.object(launcher.time, "monotonic", side_effect=lambda: clock[0]),
                patch.object(launcher, "inventory", side_effect=expire_inventory),
            ):
                with self.assertRaisesRegex(launcher.LauncherError, "expired"):
                    authority.gate("admit_spawn", self.event(authority, {}))
            self.assertEqual(
                (authority.epoch, authority.phase, authority.starts), (None, -1, 0)
            )
            (authority.repo / "plugins/auto-research-agent/owned.py").write_bytes(
                b"CHANGED = True\n"
            )
            with self.assertRaisesRegex(launcher.LauncherError, "inventory changed"):
                authority.verify(event, full=True)
            with (
                patch.object(
                    launcher.time, "monotonic", return_value=authority.deadline + 1
                ),
                patch.object(
                    launcher,
                    "pinned",
                    side_effect=AssertionError("expired must precede reads"),
                ),
            ):
                with self.assertRaisesRegex(launcher.LauncherError, "expired"):
                    authority.verify(event, full=True)

    def test_expiry_is_typed_before_reads_and_never_mutates_admission(self):
        with tempfile.TemporaryDirectory() as folder:
            authority = self.real_authority(folder)
            event = dict(spec_sha256=authority.sha, spec=authority.spec)
            for monotonic, wall in (
                (authority.deadline, authority.permit["expires_at_unix"] - 1),
                (authority.deadline - 1, authority.permit["expires_at_unix"]),
            ):
                with (
                    self.subTest(monotonic=monotonic, wall=wall),
                    patch.object(launcher.time, "monotonic", return_value=monotonic),
                    patch.object(launcher.time, "time", return_value=wall),
                    patch.object(
                        launcher, "pinned", side_effect=AssertionError("no reads")
                    ),
                ):
                    with self.assertRaises(launcher.PermitLeaseExpired):
                        authority.verify(event)
            self.assertEqual(
                (authority.epoch, authority.phase, authority.starts), (None, -1, 0)
            )

    def test_expiry_during_read_becomes_typed_passive_stop_without_authority(self):
        from research_workspace_native.process_deadline import SessionLeaseExpired

        with tempfile.TemporaryDirectory() as folder:
            authority = self.real_authority(folder)
            event = dict(spec_sha256=authority.sha, spec=authority.spec)
            clock = [authority.deadline - 1]
            original = launcher.pinned

            def expire_after_read(*args, **kwargs):
                value = original(*args, **kwargs)
                clock[0] = authority.deadline
                return value

            with (
                patch.object(launcher.time, "monotonic", side_effect=lambda: clock[0]),
                patch.object(launcher, "pinned", side_effect=expire_after_read),
            ):
                with self.assertRaises(SessionLeaseExpired):
                    authority.callbacks()["verify_source"](event)
            self.assertEqual(
                (authority.epoch, authority.phase, authority.starts), (None, -1, 0)
            )

    def test_observed_source_drift_is_not_relabelled_as_expiry(self):
        from research_workspace_native.process_deadline import SessionLeaseExpired

        with tempfile.TemporaryDirectory() as folder:
            authority = self.real_authority(folder)
            event = dict(spec_sha256=authority.sha, spec=authority.spec)
            clock = [authority.deadline - 1]
            original = launcher.pinned

            def changed_after_read(*args, **kwargs):
                if Path(args[0]) == authority.path:
                    authority.path.write_bytes(b"changed source bytes")
                    clock[0] = authority.deadline
                return original(*args, **kwargs)

            with (
                patch.object(launcher.time, "monotonic", side_effect=lambda: clock[0]),
                patch.object(launcher, "pinned", side_effect=changed_after_read),
            ):
                with self.assertRaises(launcher.LauncherError) as observed:
                    authority.callbacks()["verify_source"](event)
            self.assertNotIsInstance(observed.exception, SessionLeaseExpired)
            self.assertNotIsInstance(observed.exception, launcher.PermitLeaseExpired)
            self.assertEqual(
                (authority.epoch, authority.phase, authority.starts), (None, -1, 0)
            )


if __name__ == "__main__":
    unittest.main()
