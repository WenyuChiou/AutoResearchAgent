"""Versioned full-source transport with real SQLite and synthetic native I/O."""

import json
import time
from unittest.mock import patch

from stage_model_fixtures import StageModelFixture
from research_workspace_native.model_input_profile import (
    FULL_SOURCE_PROFILE,
    FULL_SOURCE_INPUT_BYTES,
    FULL_SOURCE_SPEC,
)
from research_workspace_native.runtime_spec import _load
from research_workspace_native.session_api import _bounded_text_inputs
from stage1_deliverable.common import canonical, sha
from native_process_channel_fixtures import OwnedProcessCase
from research_workspace_native.transport import JsonRpcTransport
from research_workspace_native.model_input_profile import preflight_wire


class FullSourceTransportTests(StageModelFixture):
    def full_model(self):
        return self.model(trusted_stage_unit=True, input_profile=FULL_SOURCE_PROFILE)

    def test_long_complete_utf8_input_replays_exactly_without_resending(self):
        prompt = "Full source follows: " + "文獻\n" * 12000 + "FINAL SOURCE TAIL"
        model = self.full_model()
        receipt = model.run("full-source", prompt, time.monotonic() + 10)
        self.assertEqual(receipt["status"], "completed", receipt)
        self.verify(model, receipt, prompt)
        self.assertEqual(self.runtime.spec["kind"], FULL_SOURCE_SPEC)
        self.assertEqual(
            self.runtime.spec["limits"]["max_text_bytes"], FULL_SOURCE_INPUT_BYTES
        )
        starts = [
            m
            for m in self.runtime.channel.messages()
            if m.get("method") == "turn/start"
        ]
        payload = starts[0]["params"]
        self.assertEqual(len(payload["input"]), 1)
        fragments = payload["additionalContext"]
        self.assertGreater(len(fragments), 1)
        self.assertEqual("".join(row["value"] for row in fragments.values()), prompt)
        self.assertTrue(all(row["kind"] == "untrusted" for row in fragments.values()))
        self.assertTrue(
            all(
                0 < len(row["value"].encode("utf8")) <= 768
                for row in fragments.values()
            )
        )
        self.assertTrue(
            all(
                len(f"<external_{key}>{row['value']}</external_{key}>".encode("utf8"))
                < 1000
                for key, row in fragments.items()
            )
        )
        initialize = next(
            m
            for m in self.runtime.channel.messages()
            if m.get("method") == "initialize"
        )
        self.assertIs(initialize["params"]["capabilities"]["experimentalApi"], True)
        self.assertTrue(
            model.run("full-source", prompt, time.monotonic() + 10)["replayed"]
        )
        reopened = self.full_model()
        replay = reopened.run("full-source", prompt, time.monotonic() + 10)
        self.verify(reopened, replay, prompt)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(sum(e["phase"] == "reserve" for e in self.events), 1)
        with self.assertRaisesRegex(ValueError, "payload differs"):
            model.run("full-source", prompt + "changed", time.monotonic() + 10)

    def test_old_profile_and_untrusted_or_unknown_profile_cannot_opt_in(self):
        with self.assertRaises(ValueError):
            self.model(input_profile=FULL_SOURCE_PROFILE)
        for value in (True, 1, "", "full-source"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.model(trusted_stage_unit=True, input_profile=value)
        with self.assertRaises(ValueError):
            _bounded_text_inputs("x" * 10001)
        self.assertEqual(self.calls, [])
        self.assertEqual(self.events, [])

    def test_oversize_or_invalid_utf8_fails_before_reservation(self):
        model = self.full_model()
        for text in ("x" * (FULL_SOURCE_INPUT_BYTES + 1), "\ud800"):
            with (
                self.subTest(size=len(text)),
                self.assertRaises((ValueError, UnicodeError)),
            ):
                model.run("overflow", text, time.monotonic() + 10)
        self.assertEqual(self.calls, [])
        self.assertEqual(self.events, [])

    def test_tail_mutation_is_rejected_by_admission_and_receipt_reconstruction(self):
        prompt = "x" * 65000 + "全文尾端"
        model = self.full_model()
        receipt = model.run("tail", prompt, time.monotonic() + 10)
        self.assertEqual(receipt["status"], "completed", receipt)
        starts = [
            m
            for m in self.runtime.channel.messages()
            if m.get("method") == "turn/start"
        ]
        payload = json.loads(json.dumps(starts[0]["params"]))
        payload["additionalContext"][list(payload["additionalContext"])[-1]][
            "value"
        ] += "假"
        with self.assertRaisesRegex(ValueError, "prompt binding differs"):
            model._gate(
                {"prompt": prompt},
                time.monotonic() + 10,
                "action",
                {"action": {"method": "turn/start", "payload": payload}},
            )
        self.verify(model, receipt, prompt)
        folder = model.root / sha(b"tail")
        raw = json.loads((folder / "request.json").read_bytes())
        raw["prompt"] += "tampered"
        (folder / "request.json").write_bytes(canonical(raw))
        with self.assertRaises(ValueError):
            self.verify(model, receipt, prompt)
        self.assertEqual(len(self.calls), 1)

    def test_new_spec_keeps_one_start_and_tool_denials(self):
        model = self.full_model()
        folder = model.root / "spec"
        folder.mkdir()
        spec = model._spec(folder, time.monotonic() + 50)
        path = model.root / "test-spec.json"
        path.write_bytes(canonical(spec))
        # The real parser validates all inputs before allocating a store.
        with patch(
            "research_workspace_native.runtime_spec._file_sha",
            return_value=model.pins["executable"],
        ):
            _, _, parsed = _load(path, sha(path.read_bytes()))
        self.assertEqual(parsed["limits"]["max_starts"], 1)
        self.assertEqual(parsed["thread_config"], model.context["thread_config"])
        spec["limits"]["max_starts"] = 2
        path.write_bytes(canonical(spec))
        with self.assertRaises(ValueError):
            _load(path, sha(path.read_bytes()))
        self.assertEqual(self.calls, [])

    def test_unknown_terminal_does_not_resend_on_repeat(self):
        self.mode = "no-terminal"
        model = self.full_model()
        prompt = "x" * 12000
        receipt = model.run("unknown", prompt, time.monotonic() + 5)
        self.assertEqual(receipt["status"], "execution-unknown", receipt)
        replay = model.run("unknown", prompt, time.monotonic() + 1)
        self.assertTrue(replay["replayed"])
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(sum(e["phase"] == "reserve" for e in self.events), 1)

    def test_escaped_complete_frame_overflow_refuses_before_reservation(self):
        model = self.full_model()
        with self.assertRaisesRegex(ValueError, "wire prompt bound"):
            model.run(
                "wire-overflow",
                "x" + "\x00" * (FULL_SOURCE_INPUT_BYTES - 1),
                time.monotonic() + 10,
            )
        self.assertEqual(self.events, [])
        self.assertEqual(self.calls, [])

    def test_large_ascii_complete_input_survives_native_frame_bound(self):
        model = self.full_model()
        prompt = "x" * (224 * 1024)
        receipt = model.run("full-boundary", prompt, time.monotonic() + 15)
        self.assertEqual(receipt["status"], "completed", receipt)
        self.verify(model, receipt, prompt)
        self.assertLessEqual(max(map(len, self.runtime.channel.sent)), 262144)

    def test_wire_preflight_counts_actual_cwd_escaping_before_reservation(self):
        model = self.full_model()
        model.checked["source_root"] = '"' * 100000
        with self.assertRaisesRegex(ValueError, "wire prompt bound"):
            model.run("metadata-overflow", "x" * (224 * 1024), time.monotonic() + 10)
        self.assertEqual(self.events, [])
        self.assertEqual(self.calls, [])

    def test_full_profile_refuses_native_thread_ids_beyond_preflight_bound(self):
        from research_workspace_native.session_api import SessionApi

        model = self.full_model()
        receipt = model.run("thread-bound", "x" * 12000, time.monotonic() + 10)
        self.assertEqual(receipt["status"], "completed", receipt)
        api = SessionApi(authenticate=lambda _: "local-viewer")
        with patch.object(self.runtime.controller, "thread_id", "x" * 129):
            with self.assertRaisesRegex(ValueError, "full-source-thread-id-bound"):
                api.register(
                    "new",
                    controller=self.runtime.controller,
                    principals={"local-viewer"},
                    source_root=self.runtime.spec["source_root"],
                    index_sha256=self.runtime.spec["index_sha256"],
                    input_version=self.runtime.spec["input_version"],
                    verify_source=lambda _: True,
                    trusted_stage_unit=True,
                    input_profile=FULL_SOURCE_PROFILE,
                )

    def test_full_profile_rejects_unsupported_native_before_account_or_thread(self):
        from stage_model_fixtures import FakeChannel

        for ua in (
            "synthetic",
            "codex_cli_rs/0.153.0 (OS; x64) client",
            "codex_cli_rs/0.163.1 (OS; x64) client",
            "codex_cli_rs/0.163.0evil (OS; x64) client",
            "codex_cli_rs/0.163.0 (OS; x64)\nclient",
        ):
            with (
                self.subTest(user_agent=ua),
                patch.object(FakeChannel, "full_source_user_agent", ua),
            ):
                model = self.full_model()
                receipt = model.run(
                    "unsupported-" + str(len(self.calls)),
                    "x" * 12000,
                    time.monotonic() + 10,
                )
                self.assertNotEqual(receipt["status"], "completed", receipt)
                self.assertEqual(
                    [m.get("method") for m in self.runtime.channel.messages()],
                    ["initialize"],
                )
        self.assertEqual(sum(e["phase"] == "reserve" for e in self.events), 5)

    def test_full_profile_registration_cannot_upgrade_legacy_bootstrap(self):
        from research_workspace_native.session_api import SessionApi

        from stage_model_fixtures import FakeRuntime

        model = self.model(trusted_stage_unit=True)
        folder = model.root / "legacy-registration"
        folder.mkdir()
        spec = model._spec(folder, time.monotonic() + 20)
        path = folder / "spec.json"
        path.write_bytes(canonical(spec))
        gates = {
            name: lambda _: True
            for name in (
                "verify_source",
                "admit_spawn",
                "admit_lifecycle",
                "admit_action",
            )
        }
        self.runtime = FakeRuntime(
            (path, sha(path.read_bytes())),
            lambda _: "local-viewer",
            {spec["project_ref"]: gates},
            "complete",
        )
        self.addCleanup(self.runtime.shutdown)
        before = self.runtime.channel.messages()
        api = SessionApi(authenticate=lambda _: "local-viewer")
        with self.assertRaisesRegex(ValueError, "full-source-native-support-required"):
            api.register(
                "new",
                controller=self.runtime.controller,
                principals={"local-viewer"},
                source_root=self.runtime.spec["source_root"],
                index_sha256=self.runtime.spec["index_sha256"],
                input_version=self.runtime.spec["input_version"],
                verify_source=lambda _: True,
                trusted_stage_unit=True,
                input_profile=FULL_SOURCE_PROFILE,
            )
        self.assertEqual(self.runtime.channel.messages(), before)


class FullSourceOwnedChannelTests(OwnedProcessCase):
    def test_admitted_context_uses_real_owned_channel_and_exact_single_frame(self):
        # Real creation-owned Python echo child/SQLite, never Codex or a model.
        channel = self.channel(lifetime=30)
        events = []
        payload = preflight_wire(
            "x" * (224 * 1024), FULL_SOURCE_PROFILE, cwd="/synthetic", model="synthetic"
        )
        transport = JsonRpcTransport(
            channel,
            connection_id="synthetic-epoch",
            on_event=events.append,
            verify_binding=lambda: True,
            max_message_bytes=262144,
        )
        with patch.object(
            channel.process.stdin, "write", wraps=channel.process.stdin.write
        ) as writes:
            transport.send_request(
                "synthetic/source", payload, request_id="large", timeout=10
            )
            chunks = [call.args[0] for call in writes.call_args_list]
        expected = (
            json.dumps(
                dict(id="large", method="synthetic/source", params=payload),
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
            ).encode("utf8")
            + b"\n"
        )
        self.assertEqual(b"".join(chunks), expected)
        self.assertLessEqual(len(expected), 262144)
        self.assertEqual(events[0]["raw_utf8"].encode("utf8"), expected)
        channel.close()
        self.assertIs(channel.reap()["leader_reaped"], True)
