"""Pre-admission receipts never turn an admitted or ambiguous operation unsent."""

import unittest

from research_workspace_native.session_api import SessionApiError
import test_native_message_api as fixtures


class KnownUnsentTests(unittest.TestCase):
    def setUp(self):
        self.case = fixtures.MessageApiTests()
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)

    def test_offer_publishes_actual_limit_without_native_io(self):
        p = self.case.project()
        before = p.store.snapshot(p.pid)["revision"]
        offer = self.case.api.offer("token-a", p.ref)
        self.assertEqual(offer["max_text_bytes"], 128)
        self.assertGreater(offer["revision"], before)
        self.assertEqual(p.channel.calls, [])
        self.assertEqual(self.case.api.offer("token-a", p.ref), offer)

    def test_text_and_stale_rejections_bind_receipt_then_allow_recovery(self):
        for changes, code in (
            ({"text": "x" * 129}, "invalid-message-text"),
            ({"text": "x" * 40000}, "action-too-large"),
            ({"stale": True}, "stale-revision"),
        ):
            with self.subTest(code=code):
                p = self.case.project(code)
                body = self.case.body(p)
                if changes.get("stale"):
                    body["revision"] -= 1
                else:
                    body.update(changes)
                before = p.store.snapshot(p.pid)
                with self.assertRaises(SessionApiError) as caught:
                    self.case.api.message("token-a", p.ref, body)
                self.assertEqual(caught.exception.code, code)
                self.assertEqual(
                    caught.exception.receipt,
                    dict(
                        schema_version="NativeKnownUnsent.v1",
                        status="known-unsent",
                        operation="message",
                        project_ref=p.ref,
                        index_sha256=p.hash,
                        input_version=p.version,
                        client_key=body["key"],
                        offer_ref=body["offer_ref"],
                        offer_sha256=body["offer_sha256"],
                    ),
                )
                self.case.assert_zero(p, before)
                body.update(text="Corrected text", revision=before["revision"])
                self.case.api.message("token-a", p.ref, body)
                self.assertEqual(len(p.channel.messages()), 1)
                self.case.api.message("token-a", p.ref, body)
                self.assertEqual(len(p.channel.messages()), 1)

    def test_unverified_source_principal_offer_and_existing_key_have_no_receipt(self):
        for kind in ("source", "principal", "offer", "admitted"):
            with self.subTest(kind=kind):
                p = self.case.project(kind)
                body = self.case.body(p)
                token = "token-a"
                if kind == "source":
                    p.source_ok = False
                elif kind == "principal":
                    token = "token-b"
                elif kind == "offer":
                    body["offer_sha256"] = "0" * 64
                else:
                    self.case.api.message(token, p.ref, body)
                    body["text"] = "Different payload with the same admitted key"
                with self.assertRaises(SessionApiError) as caught:
                    self.case.api.message(token, p.ref, body)
                self.assertIsNone(caught.exception.receipt)

    def test_deadline_and_source_recheck_never_emit_recovery_authority(self):
        p = self.case.project()
        body = self.case.body(p, text="x" * 129)
        before = p.store.snapshot(p.pid)
        calls = 0

        def deadline():
            nonlocal calls
            calls += 1
            if calls >= 3:
                raise TimeoutError("synthetic deadline expired")
            return 1

        with self.case.api.admission_guard(deadline):
            with self.assertRaises(SessionApiError) as caught:
                self.case.api.message("token-a", p.ref, body)
        self.assertIsNone(caught.exception.receipt)
        self.case.assert_zero(p, before)
        p = self.case.project("source-recheck")
        body = self.case.body(p, text="x" * 129)
        before = p.store.snapshot(p.pid)
        original = self.case.api._start_offers[p.ref]

        def revoke(binding):
            value = original(binding)
            p.source_ok = False
            return value

        self.case.api._start_offers[p.ref] = revoke
        with self.assertRaises(SessionApiError) as caught:
            self.case.api.message("token-a", p.ref, body)
        self.assertIsNone(caught.exception.receipt)
        self.case.assert_zero(p, before)


if __name__ == "__main__":
    unittest.main()
