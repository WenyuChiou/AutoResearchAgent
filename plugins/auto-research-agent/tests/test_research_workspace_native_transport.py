"""Synthetic byte-channel app-server fixtures; never launch Codex or a model."""

import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).parents[1] / "cli"))
from research_workspace_native.transport import (  # noqa: E402
    DispatchUnknown,
    JsonRpcTransport,
    TransportError,
)


class FakeServer:
    def __init__(self, respond=lambda message: []):
        self.respond, self.input, self.output = respond, b"", b""
        self.messages, self.closed = [], False

    def feed(self, message):
        self.output += json.dumps(message, ensure_ascii=False).encode() + b"\n"

    def write(self, data, timeout):
        self.input += data
        while b"\n" in self.input:
            raw, self.input = self.input.split(b"\n", 1)
            message = json.loads(raw)
            self.messages.append(message)
            for reply in self.respond(message):
                self.feed(reply)
        return len(data)

    def read(self, size, timeout):
        if not self.output:
            if self.closed:
                return b""
            raise TimeoutError
        chunk, self.output = self.output[: min(size, 3)], self.output[min(size, 3) :]
        return chunk

    def close(self):
        self.closed = True


class NativeTransportTests(unittest.TestCase):
    def make(self, channel=None, sink=None, **bounds):
        channel = channel or FakeServer()
        events = []
        transport = JsonRpcTransport(
            channel,
            connection_id="fixture-epoch",
            on_event=sink or events.append,
            verify_binding=lambda: True,
            **bounds,
        )
        self.addCleanup(transport.close)
        return transport, channel, events

    def test_initialize_persists_before_write_and_does_not_start_a_turn(self):
        channel = FakeServer(
            lambda row: (
                [{"id": row["id"], "result": {"synthetic": True}}]
                if "id" in row
                else []
            )
        )
        transport, _, events = self.make(channel)
        transport.initialize({"name": "fixture", "version": "1"}, request_id=0)
        self.assertEqual(
            [row["method"] for row in channel.messages], ["initialize", "initialized"]
        )
        self.assertEqual(
            [row["direction"] for row in events], ["outgoing", "incoming", "outgoing"]
        )

        def reject(_):
            raise OSError("fixture persistence failed")

        rejected, untouched, _ = self.make(sink=reject)
        with self.assertRaisesRegex(TransportError, "before dispatch"):
            rejected.send_request("thread/start", {}, request_id=0)
        self.assertEqual(untouched.messages, [])

    def test_interleaved_messages_preserve_typed_ids_and_directions(self):
        transport, channel, events = self.make()
        for request_id in (1, "1"):
            transport.send_request(
                "thread/read", {"threadId": "t"}, request_id=request_id
            )
        params = dict(threadId="t", turnId="u", itemId="i", approvalId="a")
        native = dict(
            id=1, method="item/commandExecution/requestApproval", params=params
        )
        channel.feed(native)
        channel.feed({"method": "item/agentMessage/delta", "params": {"delta": "研究"}})
        channel.feed({"id": "1", "result": {"typed": "string"}})
        channel.feed({"id": 1, "result": {"typed": "integer"}})
        self.assertEqual(transport.wait_response(1)["result"], {"typed": "integer"})
        self.assertEqual(transport.wait_response("1")["result"], {"typed": "string"})
        binding = transport.pending_requests()[0]
        transport.answer(1, {"decision": "decline"}, binding=binding)
        self.assertEqual(
            channel.messages[-1], {"id": 1, "result": {"decision": "decline"}}
        )
        with self.assertRaises(TransportError):
            transport.answer(1, {"decision": "accept"}, binding=binding)
        channel.feed(
            {
                "method": "serverRequest/resolved",
                "params": {"threadId": "t", "requestId": 1},
            }
        )
        transport.poll(1)
        self.assertEqual(transport.pending_requests(), [])
        self.assertTrue(any("研究" in row["raw_utf8"] for row in events))
        channel.feed(native)
        with self.assertRaises(DispatchUnknown):
            transport.poll(1)

    def test_questions_and_file_decisions_bind_exact_payload_and_epoch(self):
        for method, result in (
            (
                "item/tool/requestUserInput",
                {"answers": {"q": {"answers": ["Actual answer"]}}},
            ),
            ("item/fileChange/requestApproval", {"decision": "cancel"}),
        ):
            with self.subTest(method=method):
                transport, channel, _ = self.make()
                params = dict(
                    threadId="t", turnId="u", itemId="i", questions=[{"id": "q"}]
                )
                channel.feed(dict(id="native", method=method, params=params))
                transport.poll(1)
                binding = transport.pending_requests()[0]
                with self.assertRaisesRegex(TransportError, "binding"):
                    transport.answer(
                        "native", result, binding=dict(binding, connection_id="stale")
                    )
                transport.answer("native", result, binding=binding)
                self.assertEqual(channel.messages[-1]["id"], "native")

    def test_resume_no_reexecution_after_disconnect_timeout_or_partial_write(self):
        for closed in (False, True):
            transport, channel, _ = self.make()
            transport.send_request("turn/start", {"threadId": "t"}, request_id=9)
            channel.closed = closed
            with self.assertRaises(DispatchUnknown):
                transport.wait_response(9, timeout=0.001)
            with self.assertRaises(DispatchUnknown):
                transport.send_request("turn/start", {"threadId": "t"}, request_id=10)
            self.assertEqual(len(channel.messages), 1)

        class Partial(FakeServer):
            def write(self, data, timeout):
                if self.input:
                    raise TimeoutError
                self.input = data[:2]
                return 2

        transport, channel, _ = self.make(Partial())
        with self.assertRaises(DispatchUnknown):
            transport.send_request("turn/start", {}, request_id=1)
        self.assertEqual(channel.input, b'{"')

    def test_bad_frames_and_bounds_fail_closed(self):
        frames = [
            b'{"id":1,"id":1,"result":{}}\n',
            b'{"id":true,"result":{}}\n',
            b'{"id":9223372036854775808,"result":{}}\n',
            b'{"id":1,"result":{"overflow":1e1000}}\n',
            b'{"id":1,"result":{},"error":{}}\n',
            b'{"id":2,"result":{}}\n',
            b"x" * 128,
        ]
        for frame in frames:
            transport, channel, _ = self.make(max_message_bytes=128)
            transport.send_request("thread/read", {}, request_id=1)
            channel.output = frame
            with self.assertRaises(DispatchUnknown):
                transport.wait_response(1, timeout=1)
            self.assertTrue(channel.closed)

    def test_invalid_outgoing_payload_leaves_no_phantom_request(self):
        transport, channel, _ = self.make()
        with self.assertRaises(TransportError):
            transport.send_request("thread/read", {"value": float("nan")}, request_id=1)
        self.assertEqual(
            (transport.pending, transport.used, channel.messages), ({}, set(), [])
        )
        transport.send_request("thread/read", {}, request_id=1)
        for timeout in (float("inf"), float("nan"), -1):
            transport, channel, _ = self.make()
            with self.assertRaises(TransportError):
                transport.send_request("thread/read", {}, request_id=1, timeout=timeout)
            self.assertEqual(channel.messages, [])

    def test_native_identity_and_rpc_id_rejection_precede_answer_bytes(self):
        for request_id in (True, 1.5, 2**63, -(2**63) - 1):
            transport, channel, _ = self.make()
            with self.assertRaises(TransportError):
                transport.send_request("thread/read", {}, request_id=request_id)
            self.assertEqual(channel.messages, [])
        identity = {"threadId": "t", "turnId": "u", "itemId": "i"}
        variants = [
            ("item/commandExecution/requestApproval", dict(identity, **change))
            for change in (
                {"threadId": ""},
                {"turnId": 1},
                {"itemId": None},
                {"approvalId": []},
            )
        ]
        variants.append(
            (
                "item/tool/requestUserInput",
                dict(identity, questions=[{"id": "same"}, {"id": "same"}]),
            )
        )
        for method, params in variants:
            transport, channel, _ = self.make()
            channel.feed({"id": "native", "method": method, "params": params})
            with self.assertRaises(DispatchUnknown):
                transport.poll(1)
            self.assertEqual(channel.messages, [])

    def test_incoming_persistence_timeout_is_not_an_idle_timeout(self):
        def sink(row):
            if row["direction"] == "incoming":
                raise TimeoutError("fixture durable write timed out")

        transport, channel, _ = self.make(sink=sink)
        transport.send_request("thread/read", {}, request_id=1)
        channel.feed({"id": 1, "result": {}})
        with self.assertRaises(DispatchUnknown):
            transport.poll(1)


if __name__ == "__main__":
    unittest.main()
