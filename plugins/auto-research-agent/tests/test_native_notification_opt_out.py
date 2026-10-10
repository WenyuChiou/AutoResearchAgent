"""Injected channels only; notification selection never filters stored frames."""

import json
import unittest

import test_research_workspace_native_bootstrap as bootstrap_fixture
import test_atlas_runtime_spec as spec_fixture


class NotificationOptOutTests(unittest.TestCase):
    def fixture(self, kind):
        case = kind()
        case.setUp()
        self.addCleanup(case.doCleanups)
        return case

    def test_exact_raw_initialize_and_final_notifications_remain_recorded(self):
        case = self.fixture(bootstrap_fixture.BootstrapTests)
        boot = case.bootstrap()
        final = dict(
            method="item/completed", params=dict(item=dict(id="final", text="done"))
        )
        terminal = dict(
            method="turn/completed",
            params=dict(turn=dict(id="turn", status="completed")),
        )
        tail = b"".join(
            json.dumps(frame).encode() + b"\n" for frame in (final, terminal)
        )
        case.responses(tail=tail)
        boot.open_thread(
            dict(name="synthetic", version="1"),
            notification_opt_out=["item/agentMessage/delta"],
        )
        initialize = json.loads(case.channel.sent[0])
        self.assertEqual(
            initialize["params"],
            dict(
                clientInfo=dict(name="synthetic", version="1"),
                capabilities=dict(
                    optOutNotificationMethods=["item/agentMessage/delta"]
                ),
            ),
        )
        self.assertNotIn("experimentalApi", initialize["params"]["capabilities"])
        self.assertEqual(boot.transport.poll(1)["message"], final)
        self.assertEqual(boot.transport.poll(1)["message"], terminal)
        incoming = [row["message"] for row in case.state()["bootstrap"]["frames"]]
        self.assertIn(final, incoming)
        self.assertIn(terminal, incoming)

    def test_default_initialize_unchanged(self):
        case = self.fixture(bootstrap_fixture.BootstrapTests)
        boot = case.bootstrap()
        case.responses()
        boot.open_thread(dict(name="synthetic", version="1"))
        self.assertEqual(
            json.loads(case.channel.sent[0])["params"],
            dict(clientInfo=dict(name="synthetic", version="1")),
        )

    def test_unsafe_options_refused_before_any_io(self):
        case = self.fixture(bootstrap_fixture.BootstrapTests)
        boot = case.bootstrap()
        before = case.state()
        for option in (
            [],
            "item/agentMessage/delta",
            ["turn/completed"],
            ["item/completed"],
            ["item/commandExecution/requestApproval"],
            ["item/reasoning/textDelta"],
            ["item/agentMessage/delta"] * 2,
        ):
            with self.subTest(option=option), self.assertRaises(ValueError):
                boot.open_thread(
                    dict(name="synthetic", version="1"), notification_opt_out=option
                )
        self.assertEqual(case.channel.sent, [])
        self.assertEqual(case.state(), before)

    def test_runtime_option_pinned_and_unsafe_spec_refused(self):
        case = self.fixture(spec_fixture.RuntimeSpecTests)
        value = {**case.spec, "notification_opt_out": ["item/agentMessage/delta"]}
        self.assertEqual(case.load(value)[2], value)
        for option in (
            None,
            [],
            ["turn/completed"],
            ["error"],
            ["item/agentMessage/delta", "item/completed"],
        ):
            with self.subTest(option=option), self.assertRaises(ValueError):
                case.load({**case.spec, "notification_opt_out": option})
        self.assertFalse(case.path.parent.joinpath("storage/new.sqlite").exists())


if __name__ == "__main__":
    unittest.main()
