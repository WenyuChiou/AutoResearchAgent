"""Offline synthetic inputs exercise the real canonical import and workflow.

No real paper, search, native process, model, or scientific gate is exercised.
Only the authored HTTP source producer is mocked; package/import/checker cores
run normally, retaining unverified claims and source/version/hash provenance.
"""

from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cli"))

from research_workspace_native.project_intake import ProjectIntakeService
from research_workspace_native.project_stage2 import ProjectStage2Service
from research_workspace_native.session_api import SessionApiError
from stage1_deliverable.common import sha
from stage1_ledger.journal import LedgerError, canonical
from stage2_common import Stage2Error, canonical_hash
from stage2_workflow import build_stage2_seed
import test_research_brief as brief_fixture
import test_stage1_deliverable as package_fixture
import test_stage1_stage2_handoff as handoff_fixture


class ProjectStage2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        package_fixture.ResearchDeliverableTests.setUpClass()
        fixture = package_fixture.ResearchDeliverableTests(methodName="runTest")
        fixture.setUp()
        cls.addClassCleanup(fixture.doCleanups)
        records = fixture.make_records()
        cls.package_report = fixture.build()
        cls.deliverable = fixture.output
        cls.records = records
        handoff = handoff_fixture.Stage1Stage2HandoffTests(methodName="runTest")
        handoff.setUp()
        cls.addClassCleanup(handoff.doCleanups)
        cls.handoff = deepcopy(handoff.handoff)

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="project-stage2-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.store_root = self.root / "projects"
        self.authenticate = lambda key: "researcher" if key == "own" else "other"
        self.intake = ProjectIntakeService(
            self.store_root, authenticate=self.authenticate
        )
        self.addCleanup(lambda: self.intake.close())
        self.service = ProjectStage2Service(self.intake)
        created = self.intake.create(
            "own",
            {
                "key": "create",
                "topic": "Synthetic household research",
                "needs": [
                    {
                        "need_id": "consumption",
                        "question": "Synthetic household question",
                    }
                ],
            },
        )
        self.ref = created["project_ref"]
        state = self.intake.read("own", self.ref)
        self.resources = "Synthetic explicit resources; no actual execution authority."
        self.intake.submit(
            "own",
            self.ref,
            dict(
                key="confirm",
                revision=state["revision"],
                input_version=state["input_version"],
                brief_sha256=state["brief_sha256"],
                choices=[
                    dict(
                        field="geography",
                        status="unrestricted",
                        value=None,
                        reason="Synthetic fixture is unrestricted",
                        user_input="Keep this fixture unrestricted",
                    )
                ],
                formal_target=30,
                priority_reading_target=20,
                resource_envelope=self.resources,
                budgets=dict(
                    model_calls=0, seconds=0, search_calls=0, source_reads=0, rounds=0
                ),
                consent=dict(
                    external_search=False,
                    public_source_read=False,
                    browser_fallback=False,
                ),
                user_input="Confirm this synthetic fixture only",
                confirmed=True,
            ),
        )
        state = self.intake.read("own", self.ref)
        request = brief_fixture.search_request()
        request["proposal"]["topic"] = "Synthetic household research"
        self.intake.compile(
            "own",
            self.ref,
            dict(
                key="compile",
                revision=state["revision"],
                input_version=state["input_version"],
                brief_sha256=state["brief_sha256"],
                request=request,
                as_of="2026-10-10",
            ),
        )
        self.handoff_path = self.root / "handoff.json"
        self.resources_path = self.root / "resources.txt"
        self.handoff_path.write_bytes(canonical(self.handoff))
        self.resources_path.write_text(self.resources, encoding="utf-8")
        self.registration = dict(
            deliverable_dir=self.deliverable,
            expected_manifest_sha256=self.package_report["manifest_sha256"],
            handoff_path=self.handoff_path,
            expected_handoff_sha256=sha(self.handoff_path.read_bytes()),
            resources_path=self.resources_path,
            expected_resources_sha256=sha(self.resources_path.read_bytes()),
            policy_ref=dict(
                route="stage2-general-v3/daily_v3", execution_authorized=False
            ),
        )
        self.offer = self.service.register(self.ref, **self.registration)

    def body(self, key="activate"):
        state = self.intake.read("own", self.ref)
        return dict(
            key=key,
            revision=state["revision"],
            input_version=state["input_version"],
            brief_sha256=state["brief_sha256"],
            offer_ref=self.offer["offer_ref"],
            offer_sha256=self.offer["offer_sha256"],
            confirmed=True,
        )

    def test_real_import_workflow_preserves_full_formal_brief_and_unknowns(self):
        result = self.service.activate("own", self.ref, self.body())
        self.assertEqual(result["status"], "saved")
        self.assertEqual(result["stage2_status"], "ready-for-explicit-stage2-run")
        self.assertFalse(result["execution_authorized"])
        self.assertFalse(result["stage2_complete"])
        binding = self.service.binding(self.ref)
        packet = json.loads(binding["packet_path"].read_bytes())
        before = json.loads(self.intake.binding(self.ref)["brief_path"].read_bytes())
        self.assertEqual(packet["brief"], before)
        self.assertEqual(packet["brief"]["schema_version"], "1.1.0")
        self.assertEqual(
            packet["upstream"]["research_brief_sha256"], canonical_hash(before)
        )
        self.assertEqual(packet["candidates"], [])
        self.assertTrue(packet["unresolved"])
        source = packet["sources"][0]
        self.assertEqual(
            source["sha256"],
            sha((binding["source_root"] / source["path"]).read_bytes()),
        )
        public = self.service.read("own", self.ref)
        self.assertNotIn(str(self.root), json.dumps(public))
        self.assertTrue(
            all(not item["connected"] for item in public["later_stages"].values())
        )

    def test_reconnect_same_key_replays_with_no_import_or_second_workflow(self):
        body = self.body()
        with patch(
            "research_workspace_native.project_stage2.build_stage2_seed",
            wraps=build_stage2_seed,
        ) as core:
            first = self.service.activate("own", self.ref, body)
            self.intake.close()
            self.intake = ProjectIntakeService(
                self.store_root, authenticate=self.authenticate
            )
            self.service = ProjectStage2Service(self.intake)
            second = self.service.activate("own", self.ref, body)
            recovered = self.service.action("own", self.ref, body["key"])
            offers = self.service.offers("own", self.ref)
        self.assertEqual(core.call_count, 1)
        self.assertTrue(second["replayed"])
        self.assertTrue(recovered["replayed"])
        self.assertEqual(
            recovered["workflow_head_sha256"], first["workflow_head_sha256"]
        )
        self.assertEqual(
            offers["offers"][0]["offer_sha256"], self.offer["offer_sha256"]
        )
        self.assertEqual(first["workflow_head_sha256"], second["workflow_head_sha256"])
        with self.assertRaises(SessionApiError):
            self.service.activate("own", self.ref, self.body("another-tab-key"))

    def test_changed_key_payload_foreign_principal_and_browser_paths_rejected(self):
        body = self.body()
        self.service.activate("own", self.ref, body)
        altered = dict(body, offer_sha256="0" * 64)
        with self.assertRaisesRegex(SessionApiError, "idempotency-payload-differs"):
            self.service.activate("own", self.ref, altered)
        with self.assertRaises(SessionApiError):
            self.service.read("other", self.ref)
        with self.assertRaises(SessionApiError):
            self.service.activate(
                "own", self.ref, dict(self.body(), source_root=str(self.root))
            )

    def test_expired_transport_has_no_intent_or_output(self):
        before = self.service.history("own", self.ref)

        def expired():
            raise TimeoutError("expired transport")

        with self.assertRaises(TimeoutError):
            self.service.activate("own", self.ref, self.body(), check_deadline=expired)
        self.assertEqual(self.service.history("own", self.ref), before)
        self.assertIsNone(self.service.read("own", self.ref)["activation"])

    def test_reopened_intent_remains_unknown_and_never_calls_import(self):
        body = self.body()
        request_hash = sha(
            canonical(
                {
                    "kind": "stage2-activate",
                    "body": {
                        key: value for key, value in body.items() if key != "revision"
                    },
                }
            )
        )
        receipt = dict(
            project_ref=self.ref,
            key=body["key"],
            kind="stage2-activate",
            request_sha256=request_hash,
            status="intent-recorded",
        )
        with self.intake.db:
            self.intake.db.execute(
                "INSERT INTO intake_actions VALUES(?,?,?,?,?)",
                (
                    "researcher",
                    self.ref,
                    body["key"],
                    request_hash,
                    canonical(receipt).decode(),
                ),
            )
        self.intake.close()
        self.intake = ProjectIntakeService(
            self.store_root, authenticate=self.authenticate
        )
        self.service = ProjectStage2Service(self.intake)
        with patch(
            "research_workspace_native.project_stage2.build_stage2_seed"
        ) as core:
            result = self.service.activate("own", self.ref, body)
        core.assert_not_called()
        self.assertEqual(result["status"], "execution-unknown")
        self.assertTrue(result["replayed"])
        self.assertIsNone(self.service.read("own", self.ref)["activation"])

    def test_tampered_handoff_and_ineligible_source_keep_failure_history(self):
        self.handoff_path.write_bytes(self.handoff_path.read_bytes() + b" ")
        with self.assertRaises(SessionApiError) as failure:
            self.service.activate("own", self.ref, self.body())
        self.assertEqual(failure.exception.receipt["status"], "failed")
        self.assertEqual(
            self.service.history("own", self.ref)["actions"][-1]["status"], "failed"
        )
        ineligible = deepcopy(self.handoff)
        ineligible["eligible_for_stage2"] = False
        self.handoff_path.write_bytes(canonical(ineligible))
        with self.assertRaisesRegex(SessionApiError, "stage1-not-eligible"):
            self.service.register(
                self.ref,
                **dict(
                    self.registration,
                    expected_handoff_sha256=sha(self.handoff_path.read_bytes()),
                ),
            )

    def test_current_binding_rejects_seed_packet_and_source_edits(self):
        self.service.activate("own", self.ref, self.body())
        binding = self.service.binding(self.ref)
        packet_path = binding["packet_path"]
        raw = packet_path.read_bytes()
        packet = json.loads(raw)
        packet["comparison"] += " Edited after activation."
        packet_path.write_bytes(canonical(packet))
        with self.assertRaisesRegex(SessionApiError, "stage2-packet-bytes-differ"):
            self.service.binding(self.ref)
        packet_path.write_bytes(raw)
        source = binding["source_root"] / packet["sources"][0]["path"]
        source.write_bytes(source.read_bytes() + b"\nEdited source bytes.")
        with self.assertRaises(Stage2Error):
            self.service.binding(self.ref)

    def test_changed_intake_marks_old_offer_and_activation_stale(self):
        saved = self.service.activate("own", self.ref, self.body())
        state = self.intake.read("own", self.ref)
        self.intake.revise(
            "own",
            self.ref,
            dict(
                key="revise",
                revision=state["revision"],
                input_version=state["input_version"],
                brief_sha256=state["brief_sha256"],
                topic="A distinct synthetic household scope",
            ),
        )
        view = self.service.read("own", self.ref)
        self.assertEqual(view["offers"][0]["status"], "stale-input")
        self.assertEqual(view["activation"]["stage2_status"], "stale-input")
        self.assertFalse(view["execution_authorized"])
        history = self.service.history("own", self.ref)["actions"]
        historical = next(row for row in history if row["key"] == saved["key"])
        self.assertEqual(historical["stage2_status"], "ready-for-explicit-stage2-run")
        with self.assertRaises(LedgerError):
            self.service.binding(self.ref)

    def test_import_timeout_keeps_failed_intent_and_partial_output_without_retry(self):
        body = self.body()
        calls = 0

        def expired_after_import():
            nonlocal calls
            calls += 1
            if calls == 4:
                raise TimeoutError("Synthetic transport expired after import")

        with patch(
            "research_workspace_native.project_stage2.build_stage2_seed",
            wraps=build_stage2_seed,
        ) as core:
            with self.assertRaises(SessionApiError) as error:
                self.service.activate(
                    "own", self.ref, body, check_deadline=expired_after_import
                )
            replayed = self.service.activate("own", self.ref, body)
        self.assertEqual(core.call_count, 1)
        self.assertEqual(error.exception.receipt["status"], "failed")
        self.assertEqual(replayed["status"], "failed")
        self.assertTrue(replayed["replayed"])
        self.assertIsNone(self.service.read("own", self.ref)["activation"])
        partial = list(self.store_root.rglob("stage2-*/seed/packet.json"))
        self.assertEqual(len(partial), 1)
        self.assertFalse(partial[0].parent.parent.joinpath("workflow").exists())

    def test_historical_policy_and_invalid_deadline_are_rejected(self):
        before = self.service.history("own", self.ref)
        with self.assertRaisesRegex(SessionApiError, "stage2-daily-v3"):
            self.service.register(
                self.ref,
                **dict(self.registration, policy_ref={"route": "daily_v2"}),
            )
        with self.assertRaisesRegex(SessionApiError, "deadline-check-invalid"):
            self.service.activate("own", self.ref, self.body(), check_deadline=True)
        self.assertEqual(self.service.history("own", self.ref), before)

    def test_expiry_after_workflow_keeps_output_but_does_not_activate(self):
        body = self.body()
        calls = 0

        def expires_after_workflow():
            nonlocal calls
            calls += 1
            if calls == 5:
                raise TimeoutError("Synthetic transport expired after workflow init")

        with self.assertRaises(SessionApiError) as error:
            self.service.activate(
                "own", self.ref, body, check_deadline=expires_after_workflow
            )
        self.assertEqual(error.exception.receipt["status"], "failed")
        self.assertIsNone(self.service.read("own", self.ref)["activation"])
        self.assertEqual(
            len(
                list(self.store_root.rglob("stage2-*/workflow/workflow_manifest.json"))
            ),
            1,
        )
        self.assertEqual(
            self.service.action("own", self.ref, body["key"])["status"], "failed"
        )


if __name__ == "__main__":
    unittest.main()
