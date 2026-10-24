"""Actual saved-source/Core/SQLite to records/package using typed run authority."""

import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import test_project_stage1_delivery as delivery_fixture
from test_project_stage1_records import saved_stage1_case
from test_workspace_project_intake import bound_body
from research_workspace_native.project_records_prepare import (
    ProjectRecordsPrepareService,
    KIND,
)
from research_workspace_native.project_run_authority import action_identity
from research_workspace_native.project_stage1_run_grant import (
    ProjectStage1RunGrantService,
    SCOPE,
)
from research_workspace_native.session_api import SessionApiError
from stage1_deliverable.common import sha


class SavedRunDeliveryTests(unittest.TestCase):
    def test_actual_saved_checkpoint_records_and_package_keep_agent_proof(self):
        original_submit = delivery_fixture.submit_body

        def funded(view):
            result = original_submit(view)
            result["budgets"]["seconds"] = 120
            return result

        with (
            patch.object(delivery_fixture, "submit_body", side_effect=funded),
            saved_stage1_case() as (case, fixture),
        ):
            intake, ref, ledger = case.intake, fixture["ref"], fixture["ledger"]
            clock = SimpleNamespace(now=1000.0)
            issuer = ProjectStage1RunGrantService(
                intake, runtime_sha256="a" * 64, clock=lambda: clock.now
            )
            grant = issuer.authorize(
                "alice-token",
                ref,
                dict(
                    bound_body(intake.read("alice-token", ref), "run-consent"),
                    confirmed=True,
                    user_input="Synthetic saved-data export only; no research or Core acceptance.",
                    scope=SCOPE,
                    operations=["records", "delivery"],
                    max_seconds=100,
                    max_actions=4,
                ),
            )

            def authorized(action, operation, body):
                token = issuer.derive(
                    "alice-token",
                    ref,
                    grant_ref=grant["grant_ref"],
                    grant_sha256=grant["grant_sha256"],
                    operation=operation,
                    identity=action_identity(action, body),
                )
                return dict(
                    body,
                    key=token.key + "-work",
                    revision=intake.read("alice-token", ref)["revision"],
                ), token

            prepare = ProjectRecordsPrepareService(case.producer)
            request, token = authorized(
                KIND,
                "records",
                dict(
                    bound_body(intake.read("alice-token", ref), "preview-records"),
                    confirmed=False,
                    ledger_state_sha256=ledger.state_hash(),
                    checkpoint_event_id=fixture["checkpoint"]["event_id"],
                ),
            )
            before = intake.history("alice-token", ref)
            for authority in [{}, False]:
                with (
                    self.subTest(authority=authority),
                    self.assertRaises(SessionApiError),
                ):
                    prepare.prepare(
                        "alice-token", ref, request, run_authorization=authority
                    )
            self.assertEqual(intake.history("alice-token", ref), before)
            events = ledger.events()
            produced = prepare.prepare(
                "alice-token", ref, request, run_authorization=token
            )
            self.assertEqual(produced["status"], "saved")
            raw = Path(produced["records_path"]).read_bytes()
            self.assertEqual(sha(raw), produced["records_sha256"])
            self.assertFalse(produced["delivery_offer"]["eligible_for_stage2"])

            def receipt(key):
                return json.loads(
                    intake.db.execute(
                        "SELECT receipt FROM intake_actions WHERE principal=? AND project=? AND key=?",
                        ("alice", ref, key),
                    ).fetchone()[0]
                )

            proof = receipt(request["key"])["request"]
            self.assertFalse(proof["confirmed"])
            self.assertEqual(proof["run_authority"]["operation"], "records")
            replay = prepare.prepare(
                "alice-token", ref, dict(request, revision=999), run_authorization=token
            )
            self.assertTrue(replay["replayed"])
            self.assertEqual(Path(produced["records_path"]).read_bytes(), raw)
            self.assertEqual(ledger.events(), events)
            offer = produced["delivery_offer"]
            delivery_body, delivery_token = authorized(
                "stage1-deliver",
                "delivery",
                dict(
                    bound_body(intake.read("alice-token", ref), "preview-delivery"),
                    confirmed=False,
                    ledger_state_sha256=ledger.state_hash(),
                    offer_ref=offer["offer_ref"],
                    offer_sha256=offer["offer_sha256"],
                ),
            )
            delivered = case.delivery.deliver(
                "alice-token", ref, delivery_body, run_authorization=delivery_token
            )
            self.assertEqual(delivered["status"], "saved")
            self.assertFalse(delivered["stage1_complete"])
            self.assertFalse(delivered["eligible_for_stage2"])
            package = case.delivery.binding(ref)
            self.assertEqual(package["manifest_sha256"], delivered["manifest_sha256"])
            self.assertFalse(receipt(delivery_body["key"])["request"]["confirmed"])
            self.assertEqual(
                receipt(delivery_body["key"])["request"]["run_authority"]["operation"],
                "delivery",
            )
            history = intake.history("alice-token", ref)
            clock.now = grant["expires_at"]
            with self.assertRaises(SessionApiError):
                prepare.prepare("alice-token", ref, request, run_authorization=token)
            self.assertEqual(intake.history("alice-token", ref), history)
            self.assertEqual(ledger.events(), events)
            case.runner.assert_not_called()

    def test_delivery_postpublication_failure_preserves_unknown_and_new_key_hold(self):
        original_submit = delivery_fixture.submit_body

        def funded(view):
            result = original_submit(view)
            result["budgets"]["seconds"] = 120
            return result

        with (
            patch.object(delivery_fixture, "submit_body", side_effect=funded),
            saved_stage1_case() as (case, fixture),
        ):
            intake, ref, ledger = case.intake, fixture["ref"], fixture["ledger"]
            clock = SimpleNamespace(now=1000.0)
            issuer = ProjectStage1RunGrantService(
                intake, runtime_sha256="a" * 64, clock=lambda: clock.now
            )
            grant = issuer.authorize(
                "alice-token",
                ref,
                dict(
                    bound_body(intake.read("alice-token", ref), "run-consent"),
                    confirmed=True,
                    user_input="Synthetic saved-data export only; no research or Core acceptance.",
                    scope=SCOPE,
                    operations=["records", "delivery"],
                    max_seconds=100,
                    max_actions=4,
                ),
            )

            def authorized(action, operation, body):
                token = issuer.derive(
                    "alice-token",
                    ref,
                    grant_ref=grant["grant_ref"],
                    grant_sha256=grant["grant_sha256"],
                    operation=operation,
                    identity=action_identity(action, body),
                )
                return dict(
                    body,
                    key=token.key + "-work",
                    revision=intake.read("alice-token", ref)["revision"],
                ), token

            prepare = ProjectRecordsPrepareService(case.producer)
            request, token = authorized(
                KIND,
                "records",
                dict(
                    bound_body(intake.read("alice-token", ref), "preview-records"),
                    confirmed=False,
                    ledger_state_sha256=ledger.state_hash(),
                    checkpoint_event_id=fixture["checkpoint"]["event_id"],
                ),
            )
            before = intake.history("alice-token", ref)
            for authority in [{}, False]:
                with (
                    self.subTest(authority=authority),
                    self.assertRaises(SessionApiError),
                ):
                    prepare.prepare(
                        "alice-token", ref, request, run_authorization=authority
                    )
            self.assertEqual(intake.history("alice-token", ref), before)
            events = ledger.events()
            produced = prepare.prepare(
                "alice-token", ref, request, run_authorization=token
            )
            self.assertEqual(produced["status"], "saved")
            raw = Path(produced["records_path"]).read_bytes()
            self.assertEqual(sha(raw), produced["records_sha256"])
            self.assertFalse(produced["delivery_offer"]["eligible_for_stage2"])

            def receipt(key):
                return json.loads(
                    intake.db.execute(
                        "SELECT receipt FROM intake_actions WHERE principal=? AND project=? AND key=?",
                        ("alice", ref, key),
                    ).fetchone()[0]
                )

            proof = receipt(request["key"])["request"]
            self.assertFalse(proof["confirmed"])
            self.assertEqual(proof["run_authority"]["operation"], "records")
            replay = prepare.prepare(
                "alice-token", ref, dict(request, revision=999), run_authorization=token
            )
            self.assertTrue(replay["replayed"])
            self.assertEqual(Path(produced["records_path"]).read_bytes(), raw)
            self.assertEqual(ledger.events(), events)
            offer = produced["delivery_offer"]
            delivery_body, delivery_token = authorized(
                "stage1-deliver",
                "delivery",
                dict(
                    bound_body(intake.read("alice-token", ref), "preview-delivery"),
                    confirmed=False,
                    ledger_state_sha256=ledger.state_hash(),
                    offer_ref=offer["offer_ref"],
                    offer_sha256=offer["offer_sha256"],
                ),
            )
            from research_workspace_native import (
                project_stage1_delivery as original_delivery,
            )

            original_build = original_delivery.package.build
            publications = []

            def fail_after_build(*args, **kwargs):
                original_build(*args, **kwargs)
                output = Path(args[1])
                publications.append(
                    (
                        output,
                        {
                            str(p.relative_to(output)): sha(p.read_bytes())
                            for p in output.rglob("*")
                            if p.is_file()
                        },
                    )
                )
                raise OSError("synthetic post-publication receipt failure")

            with patch.object(original_delivery.package, "build", new=fail_after_build):
                with self.assertRaises(SessionApiError) as failed:
                    case.delivery.deliver(
                        "alice-token",
                        ref,
                        delivery_body,
                        run_authorization=delivery_token,
                    )
            self.assertEqual(len(publications), 1)
            self.assertGreater(len(publications[0][1]), 0)
            self.assertEqual(failed.exception.receipt["status"], "execution-unknown")
            self.assertEqual(
                failed.exception.receipt["failure_phase"],
                "publication-outcome-unobserved",
            )
            from contextlib import closing
            from research_workspace_native.project_intake import ProjectIntakeService
            from research_workspace_native.project_stage1 import ProjectStage1Service
            from research_workspace_native.project_stage1_delivery import (
                ProjectStage1DeliveryService,
            )

            root, authenticate = intake.root, intake.authenticate
            intake.close()
            with closing(
                ProjectIntakeService(root, authenticate=authenticate)
            ) as reopened:
                reopened_delivery = ProjectStage1DeliveryService(
                    ProjectStage1Service(reopened)
                )
                reopened_issuer = ProjectStage1RunGrantService(
                    reopened, runtime_sha256="a" * 64, clock=lambda: clock.now
                )
                same = reopened_issuer.derive(
                    "alice-token",
                    ref,
                    grant_ref=grant["grant_ref"],
                    grant_sha256=grant["grant_sha256"],
                    operation="delivery",
                    identity=action_identity("stage1-deliver", delivery_body),
                )
                repeated = reopened_delivery.deliver(
                    "alice-token",
                    ref,
                    dict(delivery_body, revision=999),
                    run_authorization=same,
                )
                self.assertTrue(repeated["replayed"])
                self.assertEqual(repeated["status"], "execution-unknown")
                self.assertNotIn(
                    "stage1_canonical_package", reopened._load("alice", ref)
                )
                history = reopened.history("alice-token", ref)
                fresh = dict(
                    delivery_body,
                    key="genuinely-new-delivery-key",
                    confirmed=True,
                    revision=reopened.read("alice-token", ref)["revision"],
                )
                self.assertNotEqual(fresh["key"], delivery_body["key"])
                with self.assertRaisesRegex(
                    SessionApiError, "write-outcome-unobserved"
                ):
                    reopened_delivery.deliver("alice-token", ref, fresh)
                self.assertEqual(reopened.history("alice-token", ref), history)
                self.assertEqual(ledger.events(), events)
            output, pins = publications[0]
            self.assertEqual(
                {
                    str(p.relative_to(output)): sha(p.read_bytes())
                    for p in output.rglob("*")
                    if p.is_file()
                },
                pins,
            )
            self.assertEqual(len(list(output.parent.glob("s1d-*"))), 1)
            case.runner.assert_not_called()


if __name__ == "__main__":
    unittest.main()
