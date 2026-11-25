"""Ordinary HTTP error replies retain native outcomes; no external execution."""

from http.client import HTTPConnection
import json
import threading
import unittest
from unittest.mock import patch

import test_project_stage1 as base
import test_project_stage1_fixed_replay as fixed_fixture
from research_workspace_native.project_host import ProjectHost


class ProjectHostErrorReceiptTests(unittest.TestCase):
    def setUp(self):
        self.token = "host-error-shape-engineering-token-32-chars"
        self.case = fixed_fixture.FixedReplayTests()
        with patch.object(
            base,
            "authenticate",
            lambda token: (
                "local-viewer" if token in {self.token, "alice-token"} else None
            ),
        ):
            self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.host = ProjectHost(
            projects=self.case.case.intake,
            credential=self.token,
            stage1=self.case.case.service,
            files={},
            views=[],
            port=0,
        )
        self.worker = threading.Thread(
            target=self.host.serve_forever,
            kwargs={"poll_interval": 0.02},
            daemon=True,
        )
        self.worker.start()
        self.addCleanup(self.stop)

    def stop(self):
        self.host.shutdown()
        self.host.server_close()
        self.worker.join(5)
        self.assertFalse(self.worker.is_alive())

    def snapshot(self):
        intake = self.case.case.intake
        state = intake._load("local-viewer", self.case.ref)
        ledger = self.case.case.service._ledger(state, intake.binding(self.case.ref))[1]
        return (
            ledger.state_hash(),
            len(ledger.events()),
            intake.db.execute("SELECT count(*) FROM intake_actions").fetchone()[0],
            intake.db.execute("SELECT count(*) FROM intake_events").fetchone()[0],
        )

    def post(self, body):
        client = HTTPConnection("127.0.0.1", self.host.server_port, timeout=10)
        try:
            client.request(
                "POST",
                "/api/projects/" + self.case.ref + "/stage1/execute-query",
                body=json.dumps(body).encode(),
                headers={
                    "Authorization": "Bearer " + self.token,
                    "Origin": self.host.expected_origin,
                    "Content-Type": "application/json",
                },
            )
            response = client.getresponse()
            return response.status, json.loads(response.read())
        finally:
            client.close()

    def test_no_valid_key_returns_client_error_without_receipt_or_writes(self):
        body = self.case.body()
        missing = {k: v for k, v in body.items() if k != "key"}
        before = self.snapshot()
        for name, request in (
            ("list-key", dict(body, key=[])),
            ("object-key", dict(body, key={})),
            ("missing-key", missing),
            ("list-body", []),
            ("null-body", None),
            ("string-body", "invalid"),
            ("integer-body", 1),
        ):
            with self.subTest(name=name):
                status, rejected = self.post(request)
                self.assertEqual(status, 400, rejected)
                self.assertIn(
                    rejected["error"],
                    {"project-input-rejected", "intake-fields-invalid"},
                )
                self.assertIsNone(rejected.get("receipt"))
                self.assertEqual(self.snapshot(), before)

    def test_legal_envelope_keeps_readable_known_unsent_and_same_key(self):
        body = dict(self.case.body(key="unconfirmed"), confirmed=False)
        before = self.snapshot()
        status, rejected = self.post(body)
        self.assertEqual(status, 400, rejected)
        receipt = rejected["receipt"]
        self.assertEqual(receipt["status"], "known-unsent")
        self.assertEqual(receipt["key"], body["key"])
        after = self.snapshot()
        self.assertEqual(after[:2], before[:2])
        self.assertEqual(after[2:], (before[2] + 1, before[3] + 1))
        self.assertEqual(
            self.case.case.intake.history(self.token, self.case.ref)["actions"][-1][
                "key"
            ],
            body["key"],
        )
        status, replay = self.post(body)
        self.assertEqual(status, 400, replay)
        self.assertEqual(replay["receipt"]["status"], "known-unsent")
        self.assertTrue(replay["receipt"]["replayed"])
        self.assertEqual(self.snapshot(), after)

    def test_saved_outcome_wins_over_later_invalid_confirmation(self):
        body = self.case.body(key="saved-first")
        status, saved = self.post(body)
        self.assertEqual(status, 200, saved)
        self.assertEqual(saved["status"], "saved")
        before = self.snapshot()
        status, rejected = self.post(dict(body, confirmed=False))
        self.assertEqual(status, 400, rejected)
        self.assertEqual(rejected["receipt"]["status"], "saved")
        self.assertEqual(rejected["receipt"]["request_sha256"], saved["request_sha256"])
        self.assertEqual(self.snapshot(), before)

    def test_written_unknown_wins_over_later_invalid_confirmation(self):
        body = self.case.body(key="unknown-first")
        with patch.object(
            base.CoverageLedger, "extract", side_effect=OSError("after recorded query")
        ):
            with self.assertRaises(Exception):
                self.case.case.service.execute_query("alice-token", self.case.ref, body)
        unknown = self.case.case.intake.action(
            self.token, body["key"], project_ref=self.case.ref
        )
        self.assertEqual(unknown["status"], "execution-unknown")
        before = self.snapshot()
        status, rejected = self.post(dict(body, confirmed=False))
        self.assertEqual(status, 400, rejected)
        self.assertEqual(rejected["receipt"]["status"], "execution-unknown")
        self.assertEqual(
            rejected["receipt"]["request_sha256"], unknown["request_sha256"]
        )
        self.assertEqual(self.snapshot(), before)
