"""Handler delegation with in-memory headers/streams; no socket/browser proof."""

from io import BytesIO
import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from research_workspace_native.project_stage1_source_http import handle_sources
from research_workspace_native.session_api import SessionApiError


class SourceHttpTests(unittest.TestCase):
    def handler(self, path="", *, body=None, headers=None, raw=None):
        payload = json.dumps(body or {}).encode() if raw is None else raw
        service = Mock()
        service.read.return_value = {"source_acquisition": False}
        service.history.return_value = {"jobs": []}
        service.offers.return_value = {"execution_authorized": False}
        service.authorize.return_value = {"status": "saved"}
        service.execute.return_value = {"status": "queued"}
        server = SimpleNamespace(
            authenticate=Mock(return_value="local-viewer"),
            project_stage1_sources=service,
            projects=SimpleNamespace(record_refusal=Mock(return_value=None)),
        )
        handler = SimpleNamespace(
            path="/api/projects/project-one/stage1/sources" + path,
            headers={"Content-Type": "application/json", **(headers or {})},
            rfile=BytesIO(payload),
            server=server,
            _headers=Mock(return_value=("token", len(payload))),
            _remaining=Mock(),
            _reply=Mock(),
            close_connection=False,
        )
        return handler, service

    def test_get_history_and_work_offer_only_delegate_read(self):
        for path, method, args in (
            ("", "read", ("token", "project-one")),
            ("/history", "history", ("token", "project-one")),
            ("/works/work-a", "offers", ("token", "project-one", "work-a")),
        ):
            with self.subTest(path=path):
                h, service = self.handler(path)
                h._headers.return_value = ("token", 0)
                handle_sources(h, "GET")
                getattr(service, method).assert_called_once_with(*args)
                service.authorize.assert_not_called()
                service.execute.assert_not_called()
                service.dispatch_pending.assert_not_called()
                self.assertEqual(h._reply.call_args.args[0], 200)

    def test_execute_persists_via_service_never_dispatches_in_http(self):
        body = {"key": "one", "grant_ref": "saved-grant", "confirmed": True}
        h, service = self.handler("/execute", body=body)
        handle_sources(h, "POST")
        service.execute.assert_called_once_with(
            "token", "project-one", body, check_deadline=h._remaining
        )
        service.dispatch_pending.assert_not_called()
        h._reply.assert_called_once_with(200, {"status": "queued"})

    def test_authorize_no_caller_runtime_or_permit_handling(self):
        body = {"key": "permit-one", "offer_ref": "opaque-one"}
        h, service = self.handler("/authorize", body=body)
        handle_sources(h, "POST")
        service.authorize.assert_called_once_with(
            "token", "project-one", body, check_deadline=h._remaining
        )
        service.dispatch_pending.assert_not_called()

    def test_cross_site_bad_credentials_and_disconnected_no_operation(self):
        cases = [
            ({"Sec-Fetch-Site": "cross-site"}, False, False, 403),
            ({}, True, False, 401),
            ({}, False, True, 409),
        ]
        for headers, unauthorized, absent, status in cases:
            with self.subTest(status=status):
                h, service = self.handler("/execute", headers=headers)
                if unauthorized:
                    h.server.authenticate.return_value = None
                if absent:
                    h.server.project_stage1_sources = None
                handle_sources(h, "POST")
                self.assertEqual(h._reply.call_args.args[0], status)
                service.assert_not_called()
                service.execute.assert_not_called()
                h.server.projects.record_refusal.assert_not_called()

    def test_invalid_get_post_routes_and_body_bounds_before_service(self):
        cases = [
            ("/execute", "GET", {}, 0, 400),
            ("/history", "POST", {}, 2, 404),
            ("/works/a/../b", "GET", {}, 0, 404),
            ("/authorize", "POST", {"Content-Type": "text/plain"}, 2, 415),
            ("/execute", "POST", {}, 4097, 413),
            ("/execute", "POST", {}, 0, 413),
        ]
        for path, method, headers, length, status in cases:
            with self.subTest(path=path, method=method, length=length):
                h, service = self.handler(path, headers=headers)
                h._headers.return_value = ("token", length)
                handle_sources(h, method)
                self.assertEqual(h._reply.call_args.args[0], status)
                service.authorize.assert_not_called()
                service.execute.assert_not_called()
                h.server.projects.record_refusal.assert_not_called()

    def test_malformed_duplicate_and_partial_json_before_any_refusal_unlock(self):
        for raw, length in ((b"{", 1), (b'{"a":1,"a":2}', 13), (b"{}", 3)):
            with self.subTest(raw=raw, length=length):
                h, service = self.handler("/execute", raw=raw)
                h._headers.return_value = ("token", length)
                handle_sources(h, "POST")
                self.assertEqual(h._reply.call_args.args[0], 400)
                service.execute.assert_not_called()
                h.server.projects.record_refusal.assert_not_called()

    def test_service_refusal_observes_existing_outcome_but_nondict_no_receipt(self):
        for raw, expected in ((b'{"key":"one"}', 1), (b"[]", 0)):
            with self.subTest(raw=raw):
                h, service = self.handler("/execute", raw=raw)
                service.execute.side_effect = SessionApiError("runner-unavailable")
                handle_sources(h, "POST")
                self.assertEqual(h._reply.call_args.args[0], 409)
                self.assertEqual(h.server.projects.record_refusal.call_count, expected)
                service.dispatch_pending.assert_not_called()

    def test_deadline_and_write_loss_close_no_second_operation(self):
        h, service = self.handler("/execute")
        h._remaining.side_effect = TimeoutError()
        handle_sources(h, "POST")
        self.assertTrue(h.close_connection)
        service.execute.assert_not_called()
        h, service = self.handler("/execute")
        h._reply.side_effect = OSError("response lost")
        handle_sources(h, "POST")
        self.assertTrue(h.close_connection)
        self.assertEqual(service.execute.call_count, 1)
        service.dispatch_pending.assert_not_called()


if __name__ == "__main__":
    unittest.main()
