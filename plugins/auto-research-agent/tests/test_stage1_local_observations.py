"""Local cell notes retain agent identity and never become human evidence."""

from copy import deepcopy
import unittest

from research_workspace_native.project_intake import ProjectIntakeService
from research_workspace_native.project_stage1 import ProjectStage1Service
from research_workspace_native.project_stage1_local_observations import (
    ProjectStage1LocalObservationService,
)
from research_workspace_native.session_api import SessionApiError
from stage1_ledger.journal import LedgerError
from stage1_deliverable.common import sha
import test_stage1_provided_candidate as provided_fixture
from test_workspace_project_intake import authenticate


class LocalObservationTests(unittest.TestCase):
    def setUp(self):
        c = self.case = provided_fixture.ProvidedCandidateTests()
        c.setUp()
        self.addCleanup(c.tearDown)
        c.data = b'Item,Under 25 years\nIncome before taxes (in dollars),"56,107"\n'
        (c.material / "table.csv").write_bytes(c.data)
        c.admit()
        c.service.checkpoint("alice-token", c.ref, c.action_body(c.ref, "cp"))
        self.service = ProjectStage1LocalObservationService(
            c.service, agent_id="test-agent"
        )

    def body(self, key="read-cell"):
        c = self.case
        view = c.intake.read("alice-token", c.ref)
        stage = c.service.read("alice-token", c.ref)
        ledger = c.private_ledger(c.ref)
        source = ledger.candidates()[c.work]["discoveries"][0]["provided"][
            "material_ref"
        ]
        start = c.data.index(b'"56,107"')
        return dict(
            key=key,
            **{k: view[k] for k in ("revision", "input_version", "brief_sha256")},
            ledger_state_sha256=stage["ledger"]["state_sha256"],
            checkpoint_event_id=stage["checkpoint"]["event_id"],
            work_id=c.work,
            version_id=c.version,
            source_ref=source,
            material_sha256=sha(c.data),
            start_byte=start,
            end_byte=start + 8,
            quote='"56,107"',
            row=2,
            column=2,
            unit="dollars",
            note="Agent read one saved cell. No screening or scientific effect inferred.",
        )

    def test_record_reopen_same_key_has_one_receipt_and_no_core_write(self):
        c = self.case
        before = c.service.read("alice-token", c.ref)
        body = self.body()
        first = self.service.record("alice-token", c.ref, body)
        self.assertEqual(first["status"], "saved")
        obs = first["observation"]
        self.assertEqual(
            obs["operator"],
            dict(principal="alice", actor_type="agent", agent_id="test-agent"),
        )
        self.assertEqual(obs["cell"]["cell_text"], "56,107")
        self.assertEqual(obs["source"]["identity_status"], "unverified")
        self.assertFalse(
            obs["human_verification"]
            or obs["claim_evidence_created"]
            or obs["grants_stage2_admission"]
        )
        c.intake.close()
        c.intake = ProjectIntakeService(c.root, authenticate=authenticate)
        c.service = ProjectStage1Service(c.intake)
        self.service = ProjectStage1LocalObservationService(
            c.service, agent_id="test-agent"
        )
        read = self.service.read("alice-token", c.ref, body["key"])
        self.assertEqual(read["observation"], obs)
        again = self.service.record("alice-token", c.ref, body)
        self.assertTrue(again["replayed"])
        self.assertEqual(again["observation"], obs)
        import json

        rows = c.intake.db.execute(
            "SELECT receipt FROM intake_actions WHERE project=?", (c.ref,)
        ).fetchall()
        count = sum(json.loads(row[0])["kind"] == first["kind"] for row in rows)
        self.assertEqual(count, 1)
        after = c.service.read("alice-token", c.ref)
        for field in ("ledger", "checkpoint", "stage1_complete", "later_stages"):
            self.assertEqual(before[field], after[field])

    def test_wrong_project_version_hash_span_and_locator_are_refused(self):
        c = self.case
        for field, value in (
            ("input_version", 99),
            ("brief_sha256", "0" * 64),
            ("version_id", "wrong-version"),
            ("material_sha256", "0" * 64),
            ("quote", "56,108"),
            ("start_byte", 0),
            ("row", 1),
            ("column", 1),
            ("unit", "euros"),
            ("checkpoint_event_id", "e999999"),
        ):
            bad = deepcopy(self.body())
            bad[field] = value
            before = c.intake.read("alice-token", c.ref)["revision"]
            with (
                self.subTest(field=field),
                self.assertRaises((SessionApiError, LedgerError)),
            ):
                self.service.record("alice-token", c.ref, bad)
            self.assertEqual(c.intake.read("alice-token", c.ref)["revision"], before)
        other = c.new(key="second-project")
        with self.assertRaises(SessionApiError):
            self.service.record("alice-token", other, self.body())
        with self.assertRaises(SessionApiError):
            self.service.read("bob-token", c.ref, "read-cell")

    def test_request_cannot_claim_human_verification_or_reuse_key_for_other_note(self):
        c = self.case
        bad = self.body()
        bad["actor_type"] = "human"
        with self.assertRaises(SessionApiError):
            self.service.record("alice-token", c.ref, bad)
        body = self.body()
        self.service.record("alice-token", c.ref, body)
        changed = deepcopy(body)
        changed["note"] = "A different observation."
        with self.assertRaisesRegex(SessionApiError, "idempotency-payload-differs"):
            self.service.record("alice-token", c.ref, changed)

    def test_actual_material_drift_refuses_readback_and_replay(self):
        c = self.case
        body = self.body()
        self.service.record("alice-token", c.ref, body)
        ledger = c.private_ledger(c.ref)
        path = ledger.root / body["source_ref"]["path"]
        path.write_bytes(b"different bytes")
        with self.assertRaises((SessionApiError, LedgerError)):
            self.service.read("alice-token", c.ref, body["key"])
        with self.assertRaises((SessionApiError, LedgerError)):
            self.service.record("alice-token", c.ref, body)

    def test_other_agent_reads_original_author_but_cannot_reuse_write_key(self):
        c = self.case
        body = self.body()
        first = self.service.record("alice-token", c.ref, body)
        other = ProjectStage1LocalObservationService(
            c.service, agent_id="another-agent"
        )
        read = other.read("alice-token", c.ref, body["key"])
        self.assertEqual(read["observation"]["operator"]["agent_id"], "test-agent")
        self.assertEqual(read["observation"], first["observation"])
        with self.assertRaisesRegex(SessionApiError, "idempotency-payload-differs"):
            other.record("alice-token", c.ref, body)
        body["observer_agent_id"] = "forged-agent"
        with self.assertRaises(SessionApiError):
            self.service.record("alice-token", c.ref, body)
