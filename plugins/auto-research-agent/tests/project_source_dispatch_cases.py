"""Synthetic handler plus actual Core/SQLite scheduling of a no-I/O runner.

Select only these four new methods. The two integration methods reuse the
existing authored failure runner and real reservations, not an HTTP receipt,
SDK parser, native process, live source or authenticated model.
"""

from copy import deepcopy
from io import BytesIO
import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from research_workspace_native.project_source_dispatcher import ProjectSourceDispatcher
from research_workspace_native.project_stage1_source_http import handle_sources
from project_stage1_source_cases import SourceServiceTests


class SourceDispatchHttpTests(unittest.TestCase):
    def handler(self, action, *, method="POST", service=None, dispatcher=None):
        body = {"key": "source-run", "confirmed": True}
        raw = json.dumps(body).encode()
        service = Mock() if service is None else service
        dispatcher = Mock() if dispatcher is None else dispatcher
        h = SimpleNamespace(
            path="/api/projects/project-one/stage1/sources" + action,
            headers={"Content-Type": "application/json"},
            rfile=BytesIO(raw),
            server=SimpleNamespace(
                project_stage1_sources=service,
                project_stage1_source_dispatcher=dispatcher,
                authenticate=Mock(return_value="local-viewer"),
                projects=SimpleNamespace(record_refusal=Mock()),
            ),
            _headers=Mock(
                return_value=("credential", 0 if method == "GET" else len(raw))
            ),
            _remaining=Mock(),
            _reply=Mock(),
            close_connection=False,
        )
        return h, service, dispatcher

    def test_get_and_authorize_never_submit(self):
        for route, method in (
            ("", "GET"),
            ("/history", "GET"),
            ("/works/work-a", "GET"),
            ("/authorize", "POST"),
        ):
            with self.subTest(route=route):
                h, service, dispatcher = self.handler(route, method=method)
                handle_sources(h, method)
                dispatcher.submit_saved.assert_not_called()
                service.dispatch_pending.assert_not_called()
                self.assertEqual(h._reply.call_args.args[0], 200)

    def test_saved_queue_submits_once_and_replayed_key_never_resubmits(self):
        saved = dict(
            status="saved",
            job_status="queued",
            replayed=False,
            project_ref="project-one",
            key="source-run",
            kind="stage1-source-execute",
            job_binding_sha256="1" * 64,
        )
        service, dispatcher = Mock(), Mock()
        dispatcher.submit_saved.return_value = dict(
            submitted=True, execution_observed=False
        )
        for receipt in (saved, dict(saved, replayed=True)):
            service.execute.return_value = deepcopy(receipt)
            h, _, _ = self.handler("/execute", service=service, dispatcher=dispatcher)
            handle_sources(h, "POST")
            self.assertEqual(h._reply.call_args.args[0], 200)
        dispatcher.submit_saved.assert_called_once_with(
            "credential", "project-one", "source-run", saved
        )
        self.assertEqual(service.execute.call_count, 2)
        service.dispatch_pending.assert_not_called()


class SourceDispatchCoreTests(SourceServiceTests):
    def setUp(self):
        self.dispatcher = None
        super().setUp()

    def tearDown(self):
        try:
            if self.dispatcher is not None:
                self.dispatcher.close()
        finally:
            super().tearDown()

    def dispatch(self, body):
        receipt = self.sources.execute(self.token, self.ref, body)
        self.dispatcher = ProjectSourceDispatcher(self.sources)
        result = self.dispatcher.submit_saved(
            self.token, self.ref, body["key"], receipt
        )
        self.assertTrue(result["submitted"])
        worker = self.dispatcher._workers[(self.ref, body["key"])]
        worker.join(10)
        self.assertFalse(worker.is_alive(), "authored failure runner did not finish")
        return receipt

    def test_saved_queue_background_once_same_key_keeps_one_actual_reservation(self):
        grant, _ = self.authorize()
        body = self.execute_body(grant)
        receipt = self.dispatch(body)
        self.assertFalse(receipt["replayed"])
        self.assertEqual(len(self.transport.calls), 1)
        saved = self.sources.read(self.token, self.ref)["jobs"][body["key"]]
        self.assertEqual(saved["status"], "execution-unknown")
        before = self.resources()["reserved"]
        replay = self.sources.execute(self.token, self.ref, body)
        self.assertTrue(replay["replayed"])
        again = self.dispatcher.submit_saved(self.token, self.ref, body["key"], replay)
        self.assertFalse(again["submitted"])
        self.assertEqual(len(self.transport.calls), 1)
        self.assertEqual(self.resources()["reserved"], before)

    def test_expired_saved_queue_refuses_before_runner_without_refund(self):
        grant, _ = self.authorize()
        body = self.execute_body(grant)
        receipt = self.sources.execute(self.token, self.ref, body)
        self.assertFalse(receipt["replayed"])
        before = self.resources()["reserved"]
        # Authored clock progression, never a changed resource counter or grant.
        self.now[0] += self.sources.config["caps"]["timeout_seconds"] + 1
        self.dispatcher = ProjectSourceDispatcher(self.sources)
        result = self.dispatcher.submit_saved(
            self.token, self.ref, body["key"], receipt
        )
        self.assertTrue(result["submitted"])
        worker = self.dispatcher._workers[(self.ref, body["key"])]
        worker.join(10)
        self.assertFalse(worker.is_alive())
        self.assertEqual(len(self.transport.calls), 0)
        saved = self.sources.read(self.token, self.ref)["jobs"][body["key"]]
        self.assertEqual(saved["status"], "refused-known-unsent")
        self.assertEqual(saved["failure"]["code"], "source-job-deadline-expired")
        self.assertEqual(saved["grant_ref"], grant["grant_ref"])
        self.assertEqual(self.resources()["reserved"], before)


if __name__ == "__main__":
    unittest.main()


def load_tests(loader, tests, pattern):
    return unittest.TestSuite(
        loader.loadTestsFromName(name, __import__(__name__))
        for name in [
            "SourceDispatchHttpTests.test_get_and_authorize_never_submit",
            "SourceDispatchHttpTests.test_saved_queue_submits_once_and_replayed_key_never_resubmits",
            "SourceDispatchCoreTests.test_saved_queue_background_once_same_key_keeps_one_actual_reservation",
            "SourceDispatchCoreTests.test_expired_saved_queue_refuses_before_runner_without_refund",
        ]
    )
