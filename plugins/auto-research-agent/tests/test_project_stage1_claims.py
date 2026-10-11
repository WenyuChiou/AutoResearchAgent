"""Human review writes real Core claims from synthetic, saved model drafts."""

from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cli"))

import test_project_stage1_delivery as delivery_fixture
from test_project_model_reading import draft
from test_project_stage1_records import saved_stage1_case
from research_workspace_native.project_model import ProjectModelService, _output_ref
from research_workspace_native.project_model_reading import saved_reading_snapshot
from research_workspace_native.project_stage1_claims import ProjectStage1ClaimService
from research_workspace_native.session_api import SessionApiError
from stage1_coverage.run import CoverageLedger
from stage1_deliverable.common import canonical, sha
from stage1_ledger.journal import decode


@contextmanager
def reading_case(*, pending=False):
    original = delivery_fixture.submit_body

    def funded(view):
        body = original(view)
        body["budgets"].update(model_calls=2, seconds=60)
        return body

    with (
        patch.object(delivery_fixture, "submit_body", side_effect=funded),
        saved_stage1_case() as (case, fixture),
    ):
        ref = fixture["ref"]
        ledger = fixture["ledger"]
        work = fixture["records"]["papers"][0]["work_id"]
        if pending:
            ledger.decide(
                work,
                "pending",
                reason="synthetic-human-review-pending",
                rationale="Unknown: retain this work pending researcher review.",
                evidence_refs=[
                    ledger.coverage_state().evidence.claims[
                        fixture["records"]["papers"][0]["claim_ids"][0]
                    ]["source_ref"]
                ],
            )
        called = []

        def factory(*, context, admit, output_root):
            called.append(deepcopy(context))

            class Reader:
                def run(self, key, prompt, deadline):
                    event = dict(
                        unit_key=key,
                        prompt_sha256=sha(prompt.encode("utf8")),
                        source_sha256=context["source_sha256"],
                        permit_sha256=context["permit_sha256"],
                        event={},
                    )
                    admit(dict(event, phase="reserve"))
                    admit(dict(event, phase="spawn"))
                    value = draft(context["saved_reading"])
                    value["evidence"][0]["claim_id"] = None
                    value["evidence"].append(deepcopy(value["evidence"][0]))
                    return dict(
                        status="completed",
                        prompt_sha256=event["prompt_sha256"],
                        source_sha256=event["source_sha256"],
                        final_text=canonical(value).decode("utf8"),
                        synthetic=True,
                    )

                def verify_receipt(self, receipt, **expected):
                    return receipt

                def close(self):
                    pass

            return Reader()

        def new_models():
            return ProjectModelService(
                case.intake,
                provider_factory=factory,
                model="synthetic-reader",
                local_cap_seconds=5,
                clock=lambda: 1_900_000_000,
                reading_records=case.producer,
            )

        models = new_models()
        try:
            snapshot = saved_reading_snapshot(case.producer, ref, work)
            current = case.intake.read("alice-token", ref)
            authorized = models.authorize(
                "alice-token",
                ref,
                dict(
                    key="reading-authorization",
                    operation="read-paper",
                    work_ref=work,
                    snapshot_sha256=sha(canonical(snapshot)),
                    confirmed=True,
                    user_input="Read this saved synthetic source once; no real model.",
                    **{
                        k: current[k]
                        for k in ("revision", "input_version", "brief_sha256")
                    },
                ),
            )["offer"]
            current = case.intake.read("alice-token", ref)
            models.execute(
                "alice-token",
                ref,
                dict(
                    key="reading-job",
                    offer_ref=authorized["offer_ref"],
                    offer_sha256=authorized["offer_sha256"],
                    confirmed=True,
                    **{
                        k: current[k]
                        for k in ("revision", "input_version", "brief_sha256")
                    },
                ),
            )
            models._workers[(ref, "reading-job")].join(5)
            case.assertFalse(models._workers[(ref, "reading-job")].is_alive())
            job = models._job(
                models.intake._principal("alice-token"), ref, "reading-job"
            )
            case.assertEqual(job["status"], "content-review-pending", job)
            case.assertEqual(job["reading_draft"]["evidence_count"], 2)
            yield dict(
                case=case,
                fixture=fixture,
                ref=ref,
                ledger=ledger,
                models=models,
                claims=ProjectStage1ClaimService(case.stage1, models, case.producer),
                output_ref=_output_ref(job),
                called=called,
                new_models=new_models,
            )
        finally:
            models.close()


def body(context, index=0, key="claim-0", *, relation="supports"):
    view = context["claims"].view("alice-token", context["ref"], context["output_ref"])
    offer = view["offers"][index]
    return dict(
        key=key,
        confirmed=True,
        evidence_index=index,
        offer_ref=offer["offer_ref"],
        offer_sha256=offer["offer_sha256"],
        review=dict(
            claim_text="Explicit human-reviewed synthetic assertion " + str(index),
            relation=relation,
            evidence_level="full-text",
            section="Synthetic results",
        ),
        **{
            k: view[k]
            for k in (
                "revision",
                "input_version",
                "brief_sha256",
                "ledger_state_sha256",
                "output_ref",
                "draft_sha256",
            )
        },
    )


class ProjectStage1ClaimTests(unittest.TestCase):
    def history(self, context):
        return context["case"].intake.history("alice-token", context["ref"])["actions"]

    def test_two_human_reviews_preserve_old_claims_unknown_and_pending(self):
        with reading_case(pending=True) as c:
            ledger, claims = c["ledger"], c["claims"]
            before = ledger.events()
            view = claims.view("alice-token", c["ref"], c["output_ref"])
            self.assertEqual(view["draft"]["findings"]["main_findings"], "Unknown")
            self.assertEqual(ledger.events(), before)
            self.assertFalse(view["scientific_acceptance"])
            self.assertEqual(len(view["offers"]), 2)
            first = claims.claim("alice-token", c["ref"], body(c, relation="pending"))
            second = claims.claim("alice-token", c["ref"], body(c, 1, "claim-1"))
            after = ledger.events()
            self.assertEqual(after[: len(before)], before)
            self.assertEqual(len(after), len(before) + 2)
            for result, relation in ((first, "pending"), (second, "supports")):
                self.assertEqual(result["status"], "saved")
                self.assertFalse(result["reading_registration_complete"])
                self.assertFalse(result["stage1_complete"])
                self.assertFalse(result["scientific_acceptance"])
                event = ledger.event(result["claim_event_id"], "ClaimEvidence")
                self.assertEqual(event["relation"], relation)
                self.assertEqual(
                    event["verifier"],
                    dict(
                        actor="alice",
                        actor_type="human",
                        method="explicit-saved-draft-review",
                    ),
                )
                location = result["reading_locator"]
                text = ledger.read_ref(event["source_ref"]).decode("utf8")
                self.assertEqual(
                    text[location["start"] : location["end"]], location["quote"]
                )
            self.assertEqual(
                ledger.coverage_state().evidence.decisions[view["work_id"]][
                    "new_decision"
                ],
                "pending",
            )
            self.assertEqual(
                c["models"].read("alice-token", c["ref"])["calls_reserved"], 1
            )
            self.assertEqual(len(c["called"]), 1)
            c["case"].runner.assert_not_called()

    def test_same_key_history_only_changed_payload_and_new_key_duplicate_refused(self):
        with reading_case() as c:
            request = body(c)
            result = c["claims"].claim("alice-token", c["ref"], request)
            saved = c["ledger"].events()
            with patch.object(
                CoverageLedger, "claim", side_effect=AssertionError("repeat")
            ):
                replay = c["claims"].claim(
                    "alice-token",
                    c["ref"],
                    {**request, "revision": 999},
                )
                self.assertTrue(replay["replayed"])
                self.assertEqual(replay["claim_event_id"], result["claim_event_id"])
                changed = deepcopy(request)
                changed["review"]["claim_text"] += " changed"
                with self.assertRaisesRegex(SessionApiError, "idempotency"):
                    c["claims"].claim("alice-token", c["ref"], changed)
                with self.assertRaisesRegex(
                    SessionApiError, "evidence-already-reviewed"
                ):
                    c["claims"].claim("alice-token", c["ref"], body(c, key="new-key"))
            self.assertEqual(c["ledger"].events(), saved)

    def test_invalid_envelopes_offers_and_review_refuse_before_intent(self):
        with reading_case() as c:
            good = body(c)
            before, history = c["ledger"].events(), self.history(c)
            changes = (
                {"output_ref": "0" * 64},
                {"draft_sha256": "0" * 64},
                {"offer_ref": "foreign"},
                {"offer_sha256": "0" * 64},
                {"ledger_state_sha256": "0" * 64},
                {"input_version": 999},
                {"evidence_index": True},
                {"evidence_index": 2},
                {"confirmed": False},
                {"root": "caller"},
                {"review": {**good["review"], "quote": "caller"}},
                {"review": {**good["review"], "relation": "unverified"}},
                {"review": {**good["review"], "evidence_level": "scored"}},
                {"review": {**good["review"], "claim_text": "\ud800"}},
            )
            for change in changes:
                with (
                    self.subTest(change=change),
                    self.assertRaises((ValueError, TypeError)),
                ):
                    c["claims"].claim("alice-token", c["ref"], {**good, **change})
                self.assertEqual(c["ledger"].events(), before)
                self.assertEqual(self.history(c), history)
            with self.assertRaises(SessionApiError):
                c["claims"].claim("bob-token", c["ref"], good)
            self.assertEqual(self.history(c), history)

    def test_artifact_tamper_and_rehashed_illegal_span_refuse_before_intent(self):
        with reading_case() as c:
            models, case = c["models"], c["case"]
            request = body(c)
            job = models._job("alice", c["ref"], "reading-job")
            folder = models._runtime_folder("alice", c["ref"], job)
            history, events = self.history(c), c["ledger"].events()
            for name in ("output.txt", "reading-draft.json"):
                path = folder / name
                original = path.read_bytes()
                try:
                    path.write_bytes(original + b" ")
                    with (
                        self.subTest(artifact=name),
                        self.assertRaisesRegex(
                            SessionApiError,
                            "artifact-differs",
                        ),
                    ):
                        c["claims"].claim("alice-token", c["ref"], request)
                finally:
                    path.write_bytes(original)
                self.assertEqual(self.history(c), history)
                self.assertEqual(c["ledger"].events(), events)
            path = folder / "output.txt"
            raw = path.read_bytes()
            changed = decode(raw, "synthetic reading output")
            changed["evidence"][0]["start_byte"] += 1
            bad_raw = canonical(changed)
            path.write_bytes(bad_raw)
            with case.intake._lock:
                state = case.intake._load("alice", c["ref"])
                state["model_operations"]["jobs"]["reading-job"]["raw_output"].update(
                    sha256=sha(bad_raw),
                    bytes=len(bad_raw),
                )
                bad_job = state["model_operations"]["jobs"]["reading-job"]
                bad_ref = _output_ref(bad_job)
                case.intake._save(state, "synthetic-output-tamper", {})
            with self.assertRaisesRegex(SessionApiError, "reading-draft-quote-differs"):
                c["claims"].claim(
                    "alice-token",
                    c["ref"],
                    {**request, "output_ref": bad_ref},
                )
            self.assertEqual(self.history(c), history)
            self.assertEqual(c["ledger"].events(), events)

    def test_deadline_before_intent_and_after_prepare_never_append(self):
        with reading_case() as c:
            request = body(c)
            before, history = c["ledger"].events(), self.history(c)

            def expired():
                raise TimeoutError("synthetic expired HTTP deadline")

            with patch.object(
                CoverageLedger, "claim", side_effect=AssertionError("write")
            ):
                with self.assertRaises(TimeoutError):
                    c["claims"].claim(
                        "alice-token",
                        c["ref"],
                        request,
                        check_deadline=expired,
                    )
                self.assertEqual(self.history(c), history)
                prepared, late = [], []
                original = c["claims"]._prepare

                def prepare(*args, **kwargs):
                    result = original(*args, **kwargs)
                    prepared.append(True)
                    if len(prepared) == 2:
                        late.append(True)
                    return result

                def deadline():
                    if late:
                        expired()

                with patch.object(c["claims"], "_prepare", side_effect=prepare):
                    with self.assertRaises(SessionApiError) as failed:
                        c["claims"].claim(
                            "alice-token",
                            c["ref"],
                            request,
                            check_deadline=deadline,
                        )
                self.assertEqual(
                    failed.exception.receipt["status"], "execution-unknown"
                )
            self.assertEqual(c["ledger"].events(), before)

    def test_after_append_unknown_blocks_new_keys_and_survives_sqlite_reopen(self):
        with reading_case() as c:
            request = body(c)
            before = c["ledger"].events()
            original = CoverageLedger.claim

            def append_then_fail(ledger, **kwargs):
                original(ledger, **kwargs)
                raise OSError("synthetic failure after durable Core claim")

            with patch.object(CoverageLedger, "claim", append_then_fail):
                with self.assertRaises(SessionApiError) as failed:
                    c["claims"].claim("alice-token", c["ref"], request)
            receipt = failed.exception.receipt
            self.assertEqual(receipt["status"], "execution-unknown")
            self.assertEqual(receipt["failure_phase"], "core-write-outcome-unobserved")
            saved = c["ledger"].events()
            self.assertEqual(saved[: len(before)], before)
            self.assertEqual(len(saved), len(before) + 1)
            self.assertEqual(saved[-1]["payload"]["kind"], "ClaimEvidence")
            c["models"].close()
            c["case"].reopen()
            reopened = c["new_models"]()
            try:
                c["claims"] = ProjectStage1ClaimService(
                    c["case"].stage1,
                    reopened,
                    c["case"].producer,
                )
                with patch.object(
                    CoverageLedger, "claim", side_effect=AssertionError("resend")
                ):
                    replay = c["claims"].claim(
                        "alice-token",
                        c["ref"],
                        {**request, "revision": 999},
                    )
                    self.assertTrue(replay["replayed"])
                    self.assertEqual(replay["status"], "execution-unknown")
                    self.assertEqual(
                        replay["request_sha256"], receipt["request_sha256"]
                    )
                    with self.assertRaisesRegex(
                        SessionApiError, "write-outcome-unobserved"
                    ):
                        c["claims"].claim(
                            "alice-token",
                            c["ref"],
                            body(c, 1, "new-key-after-reopen"),
                        )
                self.assertEqual(c["ledger"].events(), saved)
                self.assertEqual(len(c["called"]), 1)
                self.assertEqual(
                    reopened.read("alice-token", c["ref"])["calls_reserved"],
                    1,
                )
            finally:
                reopened.close()


if __name__ == "__main__":
    unittest.main()
