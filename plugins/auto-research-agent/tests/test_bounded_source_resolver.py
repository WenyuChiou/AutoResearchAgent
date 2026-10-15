"""Actual disposable resolver children; authored replies, no DNS or HTTP."""

import atlas_test_paths  # noqa: F401
import multiprocessing
import time
import unittest
from unittest.mock import patch

from research_workspace_native.bounded_source_resolver import ProcessBoundedResolver
from research_workspace_native.session_api import SessionApiError
from stage1_deliverable.common import canonical


def authored_addresses(host, port, sender):
    sender.send_bytes(canonical(dict(addresses=["8.8.8.8", "2001:4860:4860::8888"])))
    sender.close()


def authored_mixed(host, port, sender):
    sender.send_bytes(canonical(dict(addresses=["8.8.8.8", "127.0.0.1"])))
    sender.close()


def stalled_child(host, port, sender):
    time.sleep(10)


def reply_then_stalled_child(host, port, sender):
    sender.send_bytes(canonical(dict(addresses=["8.8.8.8"])))
    time.sleep(10)


def malformed_child(host, port, sender):
    sender.send_bytes(b"not JSON")
    sender.close()


class ProcessBoundedResolverTests(unittest.TestCase):
    def make(self, target):
        return ProcessBoundedResolver("1" * 64, _child_target=target)

    def children(self):
        return {child.pid for child in multiprocessing.active_children()}

    def test_public_reply_child_reaped_and_next_resolution_is_new_child(self):
        before = self.children()
        resolver = self.make(authored_addresses)
        for _ in range(2):
            self.assertEqual(
                resolver.resolve("example.invalid", 443, time.monotonic() + 10),
                ("8.8.8.8", "2001:4860:4860::8888"),
            )
        self.assertEqual(len(resolver.observations), 2)
        for observation in resolver.observations:
            self.assertEqual(observation["status"], "completed")
            self.assertTrue(observation["reaped"])
            self.assertEqual(observation["child_exit_code"], 0)
            self.assertEqual(observation["cleanup_errors"], [])
        self.assertNotEqual(
            resolver.observations[0]["pid"], resolver.observations[1]["pid"]
        )
        self.assertEqual(self.children(), before)

    def test_stalled_dns_child_terminated_no_reuse_or_residual(self):
        before = self.children()
        resolver = self.make(stalled_child)
        started = time.monotonic()
        with self.assertRaises(TimeoutError):
            resolver.resolve("example.invalid", 443, started + 0.5)
        self.assertLess(time.monotonic() - started, 4)
        row = resolver.observations[0]
        self.assertEqual(row["status"], "failed-or-unknown")
        self.assertTrue(row["reaped"])
        self.assertEqual(row["cleanup_errors"], [])
        with self.assertRaisesRegex(SessionApiError, "source-resolver-unusable"):
            resolver.resolve("example.invalid", 443, time.monotonic() + 2)
        self.assertEqual(len(resolver.observations), 1)
        self.assertEqual(self.children(), before)

    def test_mixed_private_dns_reply_refused_and_reaped(self):
        resolver = self.make(authored_mixed)
        with self.assertRaisesRegex(SessionApiError, "source-resolver-private-address"):
            resolver.resolve("example.invalid", 443, time.monotonic() + 10)
        row = resolver.observations[0]
        self.assertTrue(row["reaped"])
        self.assertEqual(row["status"], "failed-or-unknown")
        self.assertNotIn("addresses", row)

    def test_readable_reply_is_not_a_completed_child_and_never_blocks_receive(self):
        before = self.children()
        resolver = self.make(reply_then_stalled_child)
        started = time.monotonic()
        with self.assertRaises(TimeoutError):
            resolver.resolve("example.invalid", 443, started + 1)
        self.assertLess(time.monotonic() - started, 4)
        row = resolver.observations[0]
        self.assertTrue(row["reaped"])
        self.assertNotIn("addresses", row)
        self.assertEqual(row["status"], "failed-or-unknown")
        with self.assertRaisesRegex(SessionApiError, "source-resolver-unusable"):
            resolver.resolve("example.invalid", 443, time.monotonic() + 1)
        self.assertEqual(self.children(), before)

    def test_malformed_child_output_not_cached_or_reused(self):
        resolver = self.make(malformed_child)
        with self.assertRaises(ValueError):
            resolver.resolve("example.invalid", 80, time.monotonic() + 10)
        self.assertTrue(resolver.observations[0]["reaped"])
        with self.assertRaisesRegex(SessionApiError, "source-resolver-unusable"):
            resolver.resolve("example.invalid", 80, time.monotonic() + 1)

    def test_literal_private_target_and_expired_deadline_do_not_spawn(self):
        resolver = self.make(authored_addresses)
        with patch.object(
            resolver._context, "Process", side_effect=AssertionError("no child")
        ):
            for target in ("127.0.0.1", "192.168.1.2", "::1"):
                with self.assertRaisesRegex(
                    SessionApiError, "source-resolver-private-address"
                ):
                    resolver.resolve(target, 443, time.monotonic() + 1)
            with self.assertRaises(TimeoutError):
                resolver.resolve("example.invalid", 443, time.monotonic() - 1)
            self.assertEqual(
                resolver.resolve("8.8.8.8", 443, time.monotonic() + 1), ("8.8.8.8",)
            )
        self.assertEqual(resolver.observations, [])

    def test_constructor_start_failure_closed_no_second_start(self):
        context = multiprocessing.get_context("spawn")
        child = context.Process(target=authored_addresses)
        resolver = ProcessBoundedResolver("1" * 64, _context=context)
        with patch.object(context, "Process", return_value=child):
            with patch.object(
                child, "start", side_effect=OSError("authored start failure")
            ):
                with self.assertRaises(OSError):
                    resolver.resolve("example.invalid", 443, time.monotonic() + 1)
        self.assertEqual(resolver.observations[0]["error_type"], "OSError")
        with self.assertRaisesRegex(SessionApiError, "source-resolver-unusable"):
            resolver.resolve("example.invalid", 443, time.monotonic() + 1)


if __name__ == "__main__":
    unittest.main()
