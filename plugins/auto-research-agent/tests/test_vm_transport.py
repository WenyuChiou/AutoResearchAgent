"""Offline guest/controller integration: real capture/observer/replay, synthetic process only."""

import copy
import json
import os
from pathlib import Path
import secrets
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cli"))
from stage1_ab import (
    observer,
    runner,
    sequence,
    vm_common as common,
    vm_controller as controller,
    vm_guest as guest,
    vm_subject,
    vm_transport,
    vm_lifecycle as lifecycle,
)  # noqa: E402


class GuestTransportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.lock_path = self.root / "lock.json"
        self.prompt = self.root / "prompt.txt"
        self.prompt.write_text("Synthetic topic; no live model.", encoding="utf-8")
        self.lock = {
            "kind": "Stage1ABPublicLockV3",
            "schema_version": "3.1.0",
            "guest_adapter": common.binding(),
            "passive_observer": observer.binding(),
            "codex_runtime_sha256": "binary-sha",
            "plugin_tree_sha256": "plugin-sha",
            "research_hub_sha": runner.RESEARCH_HUB_SHA,
            "prompt_sha256": runner.sha(self.prompt.read_bytes()),
            "execution_policy": runner.SUBJECT_EXECUTION_POLICY,
            "created_at": "2026-01-01T00:00:00+00:00",
            "search_observation_policy": "native-or-cli",
            "runtime": {
                "app_version": "codex 0.153.0",
                "model_id": "gpt-5.6-sol",
                "reasoning": "high",
                "search_enabled": True,
                "tool_profile_sha256": "tools-sha",
            },
            "treatment_runtime_pin_sha256_by_repeat": {"1": ""},
            "paired_repeats": [
                {
                    "repeat": 1,
                    "order": ["baseline", "treatment"],
                    "baseline": {"run_id": "run-a", "subject_id": "subject-a"},
                    "treatment": {"run_id": "run-b", "subject_id": "subject-b"},
                }
            ],
        }
        self.pin = self.root / "pin.json"
        self.pin.write_text("{}\n")
        self.lock["treatment_runtime_pin_sha256_by_repeat"]["1"] = runner.sha(
            self.pin.read_bytes()
        )
        runner.write_json(self.lock_path, self.lock)
        self.fixtures = {}
        slots = []
        for run in sequence.expected_runs(self.lock):
            name = run["condition"]
            root = self.root / name
            root.mkdir()
            for child in ("profile", "workspace", "native-tmp", "state"):
                (root / child).mkdir()
            key = root / "secret"
            key.write_bytes(secrets.token_bytes(32))
            key.chmod(0o600)
            config = {
                "condition": name,
                "repeat": 1,
                "codex": "synthetic-codex",
                "profile": str(root / "profile"),
                "workspace": str(root / "workspace"),
                "state_root": str(root / "state"),
                "private_root": str(root / "absent-private"),
                "lock": str(self.lock_path),
                "prompt": str(self.prompt),
                "runtime_pin": str(self.pin),
                "native_user": "synthetic-user",
                "native_tmp": str(root / "native-tmp"),
                "secret_file": str(key),
                "diagnostic": {
                    "native_user": "diagnostic",
                    "profile": str(root / "diagnostic-profile"),
                    "workspace": str(root / "diagnostic-workspace"),
                    "native_tmp": str(root / "diagnostic-tmp"),
                },
            }
            config_path = root / "config.json"
            runner.write_json(config_path, config)
            identity = {
                "guest_id": name,
                "instance_sha256": common.digest(name),
                "machine_id_sha256": common.digest(name + "-machine"),
                "config_sha256": runner.sha(config_path.read_bytes()),
                "lock_sha256": runner.sha(self.lock_path.read_bytes()),
                **run,
            }
            self.fixtures[name] = (config, identity, key.read_bytes(), config_path)
            slots.append(
                {
                    "identity": identity,
                    "secret_file": str(key),
                    "transport": {"fixture": name},
                }
            )
        self.plan_path = self.root / "controller.json"
        self.plan = {
            "kind": "Stage1GuestControllerPlan.v2",
            "lock": str(self.lock_path),
            "slots": slots,
            "registry_root": str(self.root / "controller-private"),
        }
        runner.write_json(self.plan_path, self.plan)
        self.native_calls = 0
        self.messages = []
        self.fail_next = False
        self.patches = [
            patch.object(sequence, "REGISTRY_HOME", self.root / "registries"),
            patch.object(guest, "configuration", side_effect=self.config),
            patch.object(
                guest, "native_options", return_value=({"user": 1, "group": 1}, {})
            ),
            patch.object(runner, "probe_profile", side_effect=self.probe),
            patch.object(runner, "codex_runtime_sha", return_value="binary-sha"),
            patch.object(runner, "tree_sha", return_value="plugin-sha"),
            patch.object(
                runner,
                "_runtime_pin",
                return_value=(
                    {},
                    self.lock["treatment_runtime_pin_sha256_by_repeat"]["1"],
                ),
            ),
            patch.object(os, "chown", create=True),
            patch.object(vm_subject, "call", side_effect=self.subject_helper),
            patch.object(observer, "run_observed", side_effect=self.synthetic_native),
            patch.object(lifecycle, "admit", side_effect=self.admit),
        ]
        self.real_observer = observer.run_observed
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)

    def admit(self, config, lock, identity):
        probe = self.probe(
            None,
            None,
            None,
            identity["condition"] == "treatment",
            None,
            probe_mode=lifecycle.MODE,
        )
        body = {
            "kind": "Stage1DiagnosticReceipt.v2",
            "actual_subject": identity,
            "codex_runtime_sha256": lock["codex_runtime_sha256"],
            "plugin_tree_sha256": lock["plugin_tree_sha256"],
            "matching_probe": lifecycle.relevant(probe),
            "task": lifecycle.TASK
            if identity["condition"] == "treatment"
            else "native-discovery-only-v1",
            "model_calls": int(identity["condition"] == "treatment"),
            "retired": True,
            "result": "passed",
            "functional_skill_sha256": "skill-sha",
            "initial_setup_sha256": "setup",
        }
        return {
            "kind": "Stage1GuestLifecycle.v2",
            "mode": lifecycle.MODE,
            "initial_setup_sha256": "setup",
            "diagnostic": common.sign(body, b"synthetic-key"),
        }

    def subject_helper(self, username, operation, **args):
        if operation == "workspace_env":
            return runner._research_hub_workspace_env(
                Path(args["workspace"]), args["resume"]
            )
        return vm_subject.dispatch({"operation": operation, **args})

    def config(self, path):
        for config, identity, key, cp in self.fixtures.values():
            if str(path) == str(cp):
                return config, self.lock, identity, key
        raise AssertionError("unknown synthetic guest config")

    def probe(
        self, codex, profile, workspace, expected_plugin, private_root, *args, **kwargs
    ):
        self.assertEqual(kwargs.get("probe_mode"), lifecycle.MODE)
        return {
            "codex_version": "codex 0.153.0",
            "model": "gpt-5.6-sol",
            "reasoning": "high",
            "native_web_search": True,
            "native_capabilities": {"webSearch": True, "imageGeneration": True},
            "native_capabilities_sha256": "tools-sha",
            "native_config_sha256": "settings-sha",
            "config_sha256": "own-config",
            "plugin_names": ["auto-research-agent"] if expected_plugin else [],
            "installed_plugin_sha256": "plugin-sha" if expected_plugin else None,
            "functional_skill_sha256": "skill-sha"
            if expected_plugin
            and kwargs.get("probe_mode", "functional") == "functional"
            else None,
            "installed_skill_sha256": "skill-sha" if expected_plugin else None,
        }

    def synthetic_native(self, command, *, input, env, cwd, output, **kwargs):
        self.native_calls += 1
        final = command[command.index("-o") + 1]
        failed = self.fail_next
        self.fail_next = False
        events = [
            {"type": "thread.started", "thread_id": "same-synthetic-thread"},
            {
                "type": "item.completed",
                "item": {
                    "type": "web_search",
                    "id": "search-" + str(self.native_calls),
                    "query": "synthetic query " + str(self.native_calls),
                    "status": "completed",
                },
            },
            {"type": "turn.failed"}
            if failed
            else {
                "type": "turn.completed",
                "usage": {"input_tokens": 1, "output_tokens": 1},
            },
        ]
        raw = b"".join(json.dumps(row).encode() + b"\n" for row in events)
        script = f"import sys,pathlib;sys.stdin.buffer.read();pathlib.Path({final!r}).write_text('synthetic answer');sys.stdout.buffer.write({raw!r})"
        return self.real_observer(
            [sys.executable, "-c", script],
            input=input,
            env=dict(os.environ),
            cwd=cwd,
            output=output,
        )

    def transport(self, endpoint, envelope):
        name = endpoint["fixture"]
        self.messages.append(copy.deepcopy(envelope))
        return guest.execute(self.fixtures[name][3], envelope)

    def prepare(self):
        return controller.prepare(self.plan_path, self.transport)

    def test_actual_capture_observer_transfer_and_order_without_model(self):
        state = self.prepare()
        first = controller.advance(self.plan_path, self.transport)
        second = controller.advance(self.plan_path, self.transport)
        self.assertEqual(
            [first["condition"], second["condition"]], ["baseline", "treatment"]
        )
        self.assertEqual(self.native_calls, 2)
        saved = runner.read_json(state)
        self.assertEqual(saved["next_index"], 2)
        for entry in saved["completed"]:
            self.assertEqual(
                runner.verify_capture(entry["output"], verify_runtime=False)["status"],
                "complete",
            )
        self.assertTrue(
            (
                self.root / "baseline/state/capture/attempt-01.observer/manifest.json"
            ).exists()
        )

    def test_wrong_guest_and_stale_receipt_fail_before_capture(self):
        self.prepare()

        def wrong(endpoint, envelope):
            body = copy.deepcopy(self.transport(endpoint, envelope))
            body["body"]["identity"]["guest_id"] = "other"
            return common.sign(body["body"], self.fixtures[endpoint["fixture"]][2])

        with self.assertRaisesRegex(ValueError, "wrong guest"):
            controller.advance(self.plan_path, wrong)
        self.assertEqual(self.native_calls, 1)
        with self.assertRaisesRegex(ValueError, "active guest"):
            controller.advance(self.plan_path, self.transport)
        first = controller.advance(self.plan_path, self.transport, action="fetch")
        self.assertEqual(first["status"], "complete")
        self.assertEqual(self.native_calls, 1)

    def test_duplicate_guest_request_cannot_launch_again(self):
        self.prepare()
        controller.advance(self.plan_path, self.transport)
        request = self.messages[-1]
        with self.assertRaisesRegex(ValueError, "already exists"):
            self.transport({"fixture": "baseline"}, request)
        self.assertEqual(self.native_calls, 1)

    def test_wrong_guest_request_stale_probe_and_nonce_fail_before_native(self):
        self.prepare()
        name = "baseline"
        config, identity, key, cp = self.fixtures[name]
        request = controller._request(
            self.plan["slots"][0], "capture", "a" * 64, "wrong-probe"
        )
        with self.assertRaisesRegex(ValueError, "stale guest probe"):
            guest.execute(cp, common.sign(request, key))
        request["nonce"] = "../" + "a" * 61
        with self.assertRaisesRegex(ValueError, "wrong guest"):
            guest.execute(cp, common.sign(request, key))
        request["nonce"] = secrets.token_hex(32)
        with self.assertRaisesRegex(ValueError, "authentication"):
            guest.execute(self.fixtures["treatment"][3], common.sign(request, key))
        self.assertEqual(self.native_calls, 0)

    def test_guest_lock_cannot_be_reinterpreted_as_local_pair(self):
        with self.assertRaisesRegex(ValueError, "outside controller"):
            runner.host_preflight(
                "codex",
                self.lock_path,
                "a",
                "b",
                "aw",
                "bw",
                "private",
                "hub",
                "output",
            )
        with self.assertRaisesRegex(ValueError, "authenticated single-guest"):
            runner._capture_subject(
                "codex",
                self.lock_path,
                "baseline",
                1,
                "p",
                "w",
                self.prompt,
                "o",
                "private",
                "preflight",
            )

    def test_concurrent_guest_reservation_blocks_launch(self):
        self.prepare()
        config = self.fixtures["baseline"][0]
        with sequence.exclusive(Path(config["state_root"]) / "guest"):
            with self.assertRaises(FileExistsError):
                controller.advance(self.plan_path, self.transport)
        self.assertEqual(self.native_calls, 0)
        # The failed admission remains reserved; no automatic reclaim or replacement.
        with self.assertRaisesRegex(ValueError, "active guest"):
            controller.advance(self.plan_path, self.transport)

    def test_interrupted_capture_retains_slot_and_resume_same_run(self):
        self.prepare()
        self.fail_next = True
        failed = controller.advance(self.plan_path, self.transport)
        self.assertEqual(failed["status"], "failed")
        with self.assertRaisesRegex(ValueError, "active guest"):
            controller.advance(self.plan_path, self.transport)
        resumed = controller.advance(self.plan_path, self.transport, action="resume")
        self.assertEqual(resumed["run_id"], failed["run_id"])
        self.assertEqual(len(resumed["attempts"]), 2)
        self.assertEqual(resumed["status"], "complete")

    def test_lost_response_recovers_by_fetch_without_native_reexecution(self):
        self.prepare()

        def lost(endpoint, envelope):
            self.transport(endpoint, envelope)
            raise OSError("simulated interrupted SSH")

        with self.assertRaises(OSError):
            controller.advance(self.plan_path, lost)
        controller.advance(self.plan_path, self.transport, action="fetch")
        self.assertEqual(self.native_calls, 1)

    def test_swapped_pin_probe_and_order_are_rejected(self):
        self.plan["slots"].reverse()
        self.plan_path.write_text(json.dumps(self.plan))
        with self.assertRaisesRegex(ValueError, "order"):
            self.prepare()
        self.plan["slots"].reverse()
        self.plan_path.write_text(json.dumps(self.plan))
        original = guest.collect_probe

        def bad(*args):
            value = original(*args)
            value["binding"]["treatment_runtime_pin"]["sha256"] = "swapped"
            return value

        with (
            patch.object(guest, "collect_probe", side_effect=bad),
            self.assertRaisesRegex(ValueError, "pin differs"),
        ):
            self.prepare()
        self.assertEqual(self.native_calls, 0)

    def test_no_cross_arm_or_private_payload_and_extra_fields_fail(self):
        self.prepare()
        for envelope in self.messages:
            request = envelope["body"]
            self.assertEqual(
                set(request),
                {
                    "version",
                    "action",
                    "identity",
                    "nonce",
                    "series_id",
                    "preflight_sha256",
                },
            )
            self.assertNotIn("profile", json.dumps(request))
            self.assertNotIn("answer", json.dumps(request))
            self.assertNotIn("registry", json.dumps(request))
        req = copy.deepcopy(self.messages[0]["body"])
        req["files"] = {"other-arm/answer.txt": "forbidden"}
        req["nonce"] = secrets.token_hex(32)
        with self.assertRaisesRegex(ValueError, "unexpected request fields"):
            self.transport(
                {"fixture": "baseline"}, common.sign(req, self.fixtures["baseline"][2])
            )

    def test_transferred_file_tamper_and_path_escape_fail(self):
        self.prepare()

        def tamper(endpoint, envelope):
            response = self.transport(endpoint, envelope)
            response["body"]["files"]["run.json"]["base64"] = "e30="
            return common.sign(response["body"], self.fixtures[endpoint["fixture"]][2])

        with self.assertRaisesRegex(ValueError, "transferred file hash"):
            controller.advance(self.plan_path, tamper)
        with self.assertRaisesRegex(ValueError, "unsafe transferred"):
            common.receive_capture(
                {"../private": {"sha256": "x", "base64": "e30="}}, self.root / "reject"
            )

    def test_second_controller_root_and_unauthenticated_reply_fail(self):
        self.prepare()
        altered = copy.deepcopy(self.plan)
        altered["registry_root"] = str(self.root / "second-controller")
        other = self.root / "other-plan.json"
        runner.write_json(other, altered)
        with self.assertRaisesRegex(ValueError, "already exists"):
            controller.prepare(other, self.transport)
        with self.assertRaisesRegex(ValueError, "authentication"):
            common.authenticated({"body": {}, "hmac_sha256": "0" * 64}, b"k" * 32)

    def test_transport_enforces_pinned_ssh_and_no_shell(self):
        key = self.root / "ssh-key"
        hosts = self.root / "known-hosts"
        key.write_text("synthetic key")
        hosts.write_text("synthetic host key")
        endpoint = {
            "ssh": "ssh",
            "host": "127.0.0.1",
            "port": 22240,
            "user": "operator",
            "identity_file": str(key),
            "known_hosts": str(hosts),
            "guest_python": "/opt/python",
            "guest_config": "/root/slot.json",
        }
        with patch.object(vm_transport.subprocess, "run") as run:
            run.return_value.returncode = 0
            run.return_value.stdout = b"{}"
            vm_transport.ssh(endpoint, {"synthetic": True})
            self.assertIn("StrictHostKeyChecking=yes", run.call_args.args[0])
            self.assertFalse(run.call_args.kwargs.get("shell", False))
            endpoint["guest_config"] = "/root/config;cat /secret"
            with self.assertRaisesRegex(ValueError, "unsafe SSH"):
                vm_transport.ssh(endpoint, {})


class PrivilegeBoundaryTests(unittest.TestCase):
    def test_restricted_sudo_grant_and_unknown_policy_fail_closed(self):
        from types import SimpleNamespace

        fake_os = SimpleNamespace(
            name="posix",
            geteuid=lambda: 0,
            environ={},
            uname=lambda: SimpleNamespace(nodename="vm"),
        )
        fake_pwd = SimpleNamespace(
            getpwnam=lambda name: SimpleNamespace(
                pw_uid=1000, pw_gid=1000, pw_name=name, pw_dir="/home/subject"
            )
        )
        with (
            patch.object(guest, "os", fake_os),
            patch.dict(sys.modules, {"pwd": fake_pwd}),
            patch.object(guest.subprocess, "run") as run,
        ):
            for code, out in (
                (0, b"(root) NOPASSWD: /usr/bin/python3"),
                (1, b"policy unavailable"),
            ):
                run.return_value = SimpleNamespace(
                    returncode=code, stdout=out, stderr=b""
                )
                with self.assertRaisesRegex(ValueError, "sudo grants"):
                    guest.native_options("subject")
            run.return_value = SimpleNamespace(
                returncode=1,
                stdout=b"User subject is not allowed to run sudo on vm.",
                stderr=b"",
            )
            options, _ = guest.native_options("subject")
            self.assertEqual(options, {"user": 1000, "group": 1000, "extra_groups": []})
            self.assertEqual(
                run.call_args.args[0], ["sudo", "-n", "-l", "-U", "subject"]
            )

    def test_observed_zero_status_denial_and_legacy_one_are_account_host_bound(self):
        from types import SimpleNamespace

        for user in ("s1proofactual", "s1proofdiag", "subject"):
            for code in (0, 1):
                for host in ("stage1-clean-base", "stage1-clean-base.example"):
                    with self.subTest(user=user, code=code, host=host):
                        result = SimpleNamespace(
                            returncode=code,
                            stdout=f"User {user} is not allowed to run sudo on {host}.\n".encode(),
                            stderr=b"",
                        )
                        self.assertTrue(
                            guest._sudo_policy_denies_all(
                                result, user, "stage1-clean-base.example"
                            )
                        )

    def test_sudo_denial_rejects_ambiguous_policy_account_host_and_diagnostics(self):
        from types import SimpleNamespace

        denial = b"User subject is not allowed to run sudo on vm.\n"
        grant = b"User subject may run the following commands on vm:\n (root) /usr/bin/python3\n"
        for code, stdout, stderr in (
            (0, grant, b""),
            (1, b"policy unavailable", b""),
            (2, denial, b""),
            (-9, denial, b""),
            (0, denial + grant, b""),
            (0, grant + denial, b""),
            (0, denial, grant),
            (0, denial, b"sudo: unable to resolve host vm\n"),
            (1, b"", denial),
            (0, denial.replace(b"subject", b"other"), b""),
            (0, denial.replace(b"vm.", b"other."), b""),
            (0, denial + b"\n", b""),
            (0, b" " + denial, b""),
            (0, denial + b"\x00", b""),
        ):
            with self.subTest(code=code, stdout=stdout, stderr=stderr):
                self.assertFalse(
                    guest._sudo_policy_denies_all(
                        SimpleNamespace(returncode=code, stdout=stdout, stderr=stderr),
                        "subject",
                        "vm",
                    )
                )
        result = SimpleNamespace(returncode=0, stdout=denial, stderr=b"")
        self.assertFalse(
            guest._sudo_policy_denies_all(result, "subject".replace("b", "."), "vm")
        )
        self.assertFalse(guest._sudo_policy_denies_all(result, "subject", "vm\n"))

    def test_file_helper_drops_uid_and_does_not_need_broker_directory_access(self):
        from types import SimpleNamespace

        with (
            patch.object(
                guest,
                "native_options",
                return_value=({"user": 1000, "group": 1000, "extra_groups": []}, {}),
            ),
            patch.object(vm_subject.subprocess, "run") as run,
        ):
            run.return_value = SimpleNamespace(stdout="null")
            self.assertIsNone(
                vm_subject.call("subject", "read", path="/home/subject/tmp/final")
            )
            self.assertEqual(run.call_args.kwargs["user"], 1000)
            self.assertEqual(run.call_args.kwargs["extra_groups"], [])
            self.assertIn("-c", run.call_args.args[0])
            payload = json.loads(run.call_args.kwargs["input"])
            self.assertEqual(
                payload, {"operation": "read", "path": "/home/subject/tmp/final"}
            )

    def test_observer_never_reads_subject_path_in_privileged_broker(self):
        import base64

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace, archive = root / "workspace", root / "archive"
            workspace.mkdir()
            (archive / "blobs").mkdir(parents=True)
            read = Path.read_bytes

            def guarded(path):
                if path.is_relative_to(workspace):
                    raise AssertionError("privileged read of subject-controlled path")
                return read(path)

            with (
                patch.object(
                    vm_subject,
                    "call",
                    return_value={
                        "files": {"safe.txt": base64.b64encode(b"public").decode()},
                        "errors": [{"path": "swap", "error": "Permission denied"}],
                    },
                ),
                patch.object(Path, "read_bytes", guarded),
            ):
                value = observer._snapshot(workspace, archive, read_user="subject")
            self.assertEqual(value["files"]["safe.txt"]["bytes"], 6)
            self.assertEqual(value["errors"][0]["error"], "Permission denied")
            self.assertEqual(
                [p.read_bytes() for p in (archive / "blobs").iterdir()], [b"public"]
            )

    def test_dependency_import_probe_receives_subject_uid(self):
        from types import SimpleNamespace
        from stage1_retrieval import runtime_identity

        with (
            patch.object(
                runtime_identity, "absolute", side_effect=lambda value: Path(value)
            ),
            patch.object(runtime_identity.subprocess, "run") as run,
        ):
            run.return_value = SimpleNamespace(
                stdout=json.dumps({"paths": [], "origin": None, "package": []})
            )
            runtime_identity.inspect_python(
                ["/runtime/python", "-I", "-B", "/runtime/tool.py"],
                process_options={"user": 1000, "group": 1000, "extra_groups": []},
            )
            self.assertEqual(run.call_args.kwargs["user"], 1000)
            self.assertEqual(run.call_args.kwargs["extra_groups"], [])


if __name__ == "__main__":
    unittest.main()
