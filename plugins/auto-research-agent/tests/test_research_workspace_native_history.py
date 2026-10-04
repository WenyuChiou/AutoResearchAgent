"""Complete synthetic native-history pagination; no Codex process or model."""

import itertools
import unittest

from test_research_workspace_native_transport import FakeServer
from research_workspace_native.history import reconcile_thread
from research_workspace_native.transport import JsonRpcTransport, TransportError


def history_response(row):
    method, params = row["method"], row["params"]
    if method == "thread/read":
        result = {"thread": {"id": "t"}}
    else:
        number = 2 if "cursor" in params else 1
        data = (
            {"id": f"u{number}", "status": "completed"}
            if method == "thread/turns/list"
            else {"turnId": f"u{number}", "item": {"id": f"i{number}"}}
        )
        result = {"data": [data], "nextCursor": "next" if number == 1 else None}
    return [{"id": row["id"], "result": result}]


class NativeHistoryTests(unittest.TestCase):
    def make(self, channel):
        client = JsonRpcTransport(
            channel,
            connection_id="fixture-history",
            on_event=lambda event: None,
            verify_binding=lambda: True,
        )
        self.addCleanup(client.close)
        return client, channel, []

    def test_complete_pagination_and_repeated_cursor_rejected(self):
        transport, channel, _ = self.make(FakeServer(history_response))
        result = reconcile_thread(transport, "t", itertools.count().__next__)
        self.assertEqual([row["id"] for row in result["turns"]], ["u1", "u2"])
        self.assertEqual(len(result["items"]), 2)
        self.assertEqual(len(channel.messages), 5)

        def loop(row):
            replies = history_response(row)
            if row["method"] != "thread/read":
                replies[0]["result"]["nextCursor"] = "same"
            return replies

        transport, _, _ = self.make(FakeServer(loop))
        with self.assertRaisesRegex(TransportError, "cursor"):
            reconcile_thread(transport, "t", itertools.count().__next__)
        for bounds in ({"max_pages": 1}, {"max_records": 1}):
            transport, _, _ = self.make(FakeServer(history_response))
            with self.assertRaisesRegex(TransportError, "bound"):
                reconcile_thread(transport, "t", itertools.count().__next__, **bounds)
        for invalid in (
            {"turnId": "missing", "item": {"id": "i"}},
            {"turnId": "u1", "item": {"id": 1}},
        ):

            def bad_item(row):
                replies = history_response(row)
                if row["method"] == "thread/items/list":
                    replies[0]["result"] = {"data": [invalid], "nextCursor": None}
                return replies

            transport, _, _ = self.make(FakeServer(bad_item))
            with self.assertRaises(TransportError):
                reconcile_thread(transport, "t", itertools.count().__next__)

    def test_malformed_thread_and_incomplete_pages_fail_without_partial_result(self):
        for invalid in (None, [], {}, {"id": "other"}):
            with self.subTest(thread=invalid):

                def bad_thread(row):
                    return [{"id": row["id"], "result": {"thread": invalid}}]

                transport, channel, _ = self.make(FakeServer(bad_thread))
                with self.assertRaisesRegex(TransportError, "thread mismatch"):
                    reconcile_thread(transport, "t", itertools.count().__next__)
                self.assertEqual(len(channel.messages), 1)
        for invalid in (
            {"data": []},
            {"data": "not-a-list", "nextCursor": None},
            {"data": [], "nextCursor": 1},
        ):
            with self.subTest(page=invalid):

                def bad_page(row):
                    replies = history_response(row)
                    if row["method"] != "thread/read":
                        replies[0]["result"] = invalid
                    return replies

                transport, channel, _ = self.make(FakeServer(bad_page))
                with self.assertRaises(TransportError):
                    reconcile_thread(transport, "t", itertools.count().__next__)
                self.assertEqual(len(channel.messages), 2)

    def test_duplicate_identity_and_late_rpc_error_do_not_complete_reconciliation(self):
        for kind in ("turns", "items"):
            with self.subTest(duplicate=kind):

                def duplicate(row):
                    replies = history_response(row)
                    if row["method"] == "thread/" + kind + "/list":
                        replies[0]["result"]["data"] *= 2
                    return replies

                transport, _, _ = self.make(FakeServer(duplicate))
                with self.assertRaisesRegex(TransportError, "duplicate"):
                    reconcile_thread(transport, "t", itertools.count().__next__)

        def late_error(row):
            if row["method"] == "thread/items/list" and "cursor" in row["params"]:
                return [
                    {
                        "id": row["id"],
                        "error": {"code": -32601, "message": "unsupported"},
                    }
                ]
            return history_response(row)

        transport, channel, _ = self.make(FakeServer(late_error))
        with self.assertRaisesRegex(TransportError, "history read failed"):
            reconcile_thread(transport, "t", itertools.count().__next__)
        self.assertEqual(len(channel.messages), 5)
        self.assertTrue(
            all(
                row["method"]
                in {"thread/read", "thread/turns/list", "thread/items/list"}
                for row in channel.messages
            )
        )


if __name__ == "__main__":
    unittest.main()
