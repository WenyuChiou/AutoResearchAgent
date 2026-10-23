"""Real model queue/intake with a synthetic provider; no native research calls."""

from contextlib import contextmanager
from copy import deepcopy
import unittest
from unittest.mock import patch

from research_workspace_native.project_model import ProjectModelService
from research_workspace_native.project_run_authority import action_identity
from research_workspace_native.project_stage1_run_grant import (
    ProjectStage1RunGrantService,
    SCOPE,
)
from research_workspace_native.model_input_profile import turn_input
from research_workspace_native.session_api import SessionApiError
from stage1_deliverable.common import canonical, sha
from stage1_deliverable.records import CLASSIFICATION, FINDINGS
from test_project_stage1_records import saved_stage1_case
from test_workspace_project_intake import bound_body
import test_project_stage1_delivery as delivery_fixture


@contextmanager
def setup_case(block_phase=None, *, consent_override=None):
    original = delivery_fixture.submit_body

    def funded(view):
        body = original(view)
        body["budgets"].update(model_calls=2, seconds=120)
        return body

    with (
        patch.object(delivery_fixture, "submit_body", side_effect=funded),
        saved_stage1_case() as (case, fx),
    ):
        now = [1_900_000_000.0]
        issuer = ProjectStage1RunGrantService(
            case.intake, runtime_sha256="a" * 64, clock=lambda: now[0]
        )
        ref = fx["ref"]
        consent = (
            "Run this synthetic analysis within the saved limits; do not accept science."
            if consent_override is None
            else consent_override
        )
        grant = issuer.authorize(
            "alice-token",
            ref,
            {
                **bound_body(case.intake.read("alice-token", ref), "whole-run"),
                "confirmed": True,
                "user_input": consent,
                "scope": SCOPE,
                "operations": ["analyze-full-paper"],
                "max_seconds": 100,
                "max_actions": 8,
            },
        )
        phases = []
        calls = []

        def factory(*, context, admit, output_root):
            calls.append(context)
            source = context["saved_reading"]["reading_input"]["full_source"][
                "sources"
            ][0]
            text = source["text"]
            quote = text[-32:]
            raw = text.encode("utf8")
            answer = dict(
                kind="Stage1FullSourceAnalysisProposal",
                schema_version="1.0.0",
                reading=dict(
                    summary="Synthetic observation; semantic support Unknown.",
                    classification={k: "Unknown" for k in CLASSIFICATION},
                    findings={k: "Unknown" for k in FINDINGS},
                    limitations=["Unassessed."],
                    open_questions=["Unknown."],
                    evidence=[
                        dict(
                            source_id=source["source_id"],
                            text_sha256=source["text_sha256"],
                            start_byte=len(raw) - len(quote.encode("utf8")),
                            end_byte=len(raw),
                            quote=quote,
                            claim_id=None,
                        )
                    ],
                ),
                screening=dict(
                    decision="pending",
                    need_ids=[
                        context["saved_reading"]["reading_input"]["brief"]["needs"][0][
                            "need_id"
                        ]
                    ],
                    reason_code="needs-review",
                    rationale="Authored source retained; confirmed need remains Unknown.",
                    missing_information=["Relevance."],
                ),
                claims=[
                    dict(
                        claim_key="tail",
                        claim_text="Authored text contains this passage.",
                        relation="unclear",
                        evidence_index=0,
                        section="Unknown",
                        assessment=dict(
                            reason_code="unassessed",
                            rationale="Exact text; meaning unassessed.",
                        ),
                    )
                ],
            )

            class Reader:
                def run(self, key, prompt, deadline):
                    event = dict(
                        unit_key=key,
                        prompt_sha256=sha(prompt.encode()),
                        source_sha256=context["source_sha256"],
                        permit_sha256=context["permit_sha256"],
                        event={},
                    )
                    for phase in ["reserve", "spawn", "action"]:
                        if block_phase == phase:
                            now[0] = 1_900_000_100.0
                        extra = (
                            dict(
                                action=dict(
                                    method="turn/start",
                                    payload=dict(
                                        model=context["model"],
                                        **turn_input(prompt, context["input_profile"]),
                                    ),
                                )
                            )
                            if phase == "action"
                            else {}
                        )
                        admit(dict(event, phase=phase, event=extra))
                        phases.append(phase)
                    return dict(
                        status="completed",
                        prompt_sha256=event["prompt_sha256"],
                        source_sha256=event["source_sha256"],
                        final_text=canonical(answer).decode(),
                        synthetic=True,
                    )

                def verify_receipt(self, receipt, **expected):
                    return receipt

            return Reader()

        model = ProjectModelService(
            case.intake,
            provider_factory=factory,
            model="synthetic-run",
            clock=lambda: now[0],
            local_cap_seconds=30,
            reading_records=case.producer,
            run_grants=issuer,
        )

        def derived(action, extra):
            body = {
                **bound_body(case.intake.read("alice-token", ref), "draft"),
                "confirmed": False,
                **extra,
            }
            token = issuer.derive(
                "alice-token",
                ref,
                grant_ref=grant["grant_ref"],
                grant_sha256=grant["grant_sha256"],
                operation="analyze-full-paper",
                identity=action_identity(action, body),
            )
            body.update(
                key=token.key + "-work",
                revision=case.intake.read("alice-token", ref)["revision"],
            )
            return body, token

        try:
            yield (
                case,
                fx,
                model,
                issuer,
                grant,
                consent,
                derived,
                now,
                calls,
                phases,
                factory,
            )
        finally:
            model.close()


def authorize(case, fx, model, consent, derived):
    ref = fx["ref"]
    work = fx["records"]["papers"][0]["work_id"]
    preview = model.full_analysis_offer(
        "alice-token",
        ref,
        work,
        expected_input_version=case.intake.read("alice-token", ref)["input_version"],
        expected_ledger_state_sha256=fx["ledger"].state_hash(),
    )
    return derived(
        "model-authorize",
        dict(
            operation="analyze-full-paper",
            user_input=consent,
            work_ref=work,
            snapshot_sha256=preview["snapshot_sha256"],
        ),
    )


class ModelRunTests(unittest.TestCase):
    def test_derived_authorize_execute_replay_and_saved_permit_binding(self):
        with setup_case() as (
            case,
            fx,
            model,
            issuer,
            grant,
            consent,
            derived,
            now,
            calls,
            phases,
            factory,
        ):
            ref = fx["ref"]
            body, token = authorize(case, fx, model, consent, derived)
            for credential, proof in [("bob-token", token), ("alice-token", {})]:
                with self.assertRaises(SessionApiError):
                    model.authorize(credential, ref, body, run_authorization=proof)
            with self.assertRaises(SessionApiError):
                model.authorize("alice-token", ref, body)
            saved = model.authorize("alice-token", ref, body, run_authorization=token)
            self.assertEqual(saved["status"], "saved", saved)
            self.assertTrue(saved.get("connected"), saved)
            durable = __import__("json").loads(
                case.intake.db.execute(
                    "SELECT receipt FROM intake_actions WHERE principal=? AND project=? AND key=?",
                    ("alice", ref, body["key"]),
                ).fetchone()[0]
            )
            self.assertFalse(durable["request"]["confirmed"])
            self.assertEqual(durable["request"]["run_user_input"], consent)
            self.assertTrue(
                model.authorize("alice-token", ref, body, run_authorization=token)[
                    "replayed"
                ]
            )
            offer = saved["offer"]
            state = case.intake._load("alice", ref)
            authorization = state["model_operations"]["authorizations"][body["key"]]
            path = case.intake._path(ref, authorization["artifact"]["path"])
            permit = __import__("json").loads(path.read_text())
            self.assertEqual(permit["schema_version"], "1.1.0")
            forged = deepcopy(permit)
            forged["work_ref"] = "different-work"
            bad = path.parent / "forged-run-permit.json"
            raw = canonical(forged) + b"\n"
            bad.write_bytes(raw)
            with self.assertRaises(SessionApiError):
                model.register(
                    ref,
                    operation="analyze-full-paper",
                    permit_path=bad,
                    permit_sha256=sha(raw),
                )
            model.run_grants = None
            with self.assertRaises(SessionApiError):
                model.register(
                    ref,
                    operation="analyze-full-paper",
                    permit_path=path,
                    permit_sha256=authorization["artifact"]["sha256"],
                )
            model.run_grants = issuer
            rb, rt = derived(
                "model-execute",
                dict(offer_ref=offer["offer_ref"], offer_sha256=offer["offer_sha256"]),
            )
            result = model.execute("alice-token", ref, rb, run_authorization=rt)
            self.assertEqual(result["status"], "saved", result)
            worker = model._workers[(ref, rb["key"])]
            worker.join(90)
            self.assertFalse(worker.is_alive())
            job = model._job("alice", ref, rb["key"])
            self.assertEqual(job["status"], "content-review-pending", job)
            self.assertEqual(phases, ["reserve", "spawn", "action"])
            self.assertEqual(len(calls), 1)
            self.assertTrue(
                model.execute("alice-token", ref, rb, run_authorization=rt)["replayed"]
            )
            self.assertEqual(model.read("alice-token", ref)["calls_reserved"], 1)
            now[0] = 1_900_000_100.0
            with self.assertRaises(SessionApiError):
                model._guard(
                    ref, state["model_operations"]["offers"][offer["offer_ref"]]
                )
            now[0] = 1_900_000_050.0
            with self.assertRaises(SessionApiError):
                model._guard(
                    ref, state["model_operations"]["offers"][offer["offer_ref"]]
                )

    def test_maximum_consent_connects_compact_permit_and_reopens_original_receipt(self):
        with setup_case(consent_override="x" * 8192) as data:
            case, fx, model, issuer, _, consent, derived, *_ = data
            ref = fx["ref"]
            body, token = authorize(case, fx, model, consent, derived)
            result = model.authorize("alice-token", ref, body, run_authorization=token)
            self.assertEqual(result["status"], "saved", result)
            self.assertTrue(result.get("connected"), result)
            state = case.intake._load("alice", ref)
            artifact = state["model_operations"]["authorizations"][body["key"]][
                "artifact"
            ]
            path = case.intake._path(ref, artifact["path"])
            raw = path.read_bytes()
            permit = __import__("json").loads(raw)
            self.assertLessEqual(len(raw), 16384)
            self.assertNotIn("user_input", permit["run_request"])
            self.assertNotIn("run_user_input", permit["run_request"])
            self.assertNotIn("revision", permit["run_request"])
            row = case.intake.db.execute(
                "SELECT receipt FROM intake_actions WHERE principal=? AND project=? AND key=?",
                ("alice", ref, body["key"]),
            ).fetchone()
            receipt = __import__("json").loads(row[0])
            self.assertEqual(receipt["request"]["user_input"], consent)
            self.assertEqual(receipt["request"]["run_user_input"], consent)
            self.assertEqual(
                issuer._grant("alice", ref, token.grant_ref, token.grant_sha256)[1][
                    "user_input"
                ],
                consent,
            )
            model.register(
                ref,
                operation="analyze-full-paper",
                permit_path=path,
                permit_sha256=artifact["sha256"],
            )
            forged = deepcopy(permit)
            forged["run_request"]["snapshot_sha256"] = "f" * 64
            wrong = path.parent / "wrong-compact-proof.json"
            changed = canonical(forged) + b"\n"
            wrong.write_bytes(changed)
            with self.assertRaises(SessionApiError):
                model.register(
                    ref,
                    operation="analyze-full-paper",
                    permit_path=wrong,
                    permit_sha256=sha(changed),
                )
            receipt["request"]["run_user_input"] = "changed original consent"
            case.intake.db.execute(
                "UPDATE intake_actions SET receipt=? WHERE principal=? AND project=? AND key=?",
                (canonical(receipt).decode(), "alice", ref, body["key"]),
            )
            with self.assertRaises(SessionApiError):
                model.register(
                    ref,
                    operation="analyze-full-paper",
                    permit_path=path,
                    permit_sha256=artifact["sha256"],
                )

    def test_malformed_permit_versions_and_action_keys_have_typed_refusals(self):
        with setup_case() as data:
            case, fx, model, _, _, consent, derived, *_ = data
            ref = fx["ref"]
            body, token = authorize(case, fx, model, consent, derived)
            result = model.authorize("alice-token", ref, body, run_authorization=token)
            self.assertTrue(result.get("connected"), result)
            state = case.intake._load("alice", ref)
            artifact = state["model_operations"]["authorizations"][body["key"]][
                "artifact"
            ]
            path = case.intake._path(ref, artifact["path"])
            permit = __import__("json").loads(path.read_text())
            for name, values in [
                ("schema_version", [[], {}]),
                ("action_key", [None, [], {}]),
            ]:
                for index, value in enumerate(values):
                    with self.subTest(field=name, value=value):
                        forged = deepcopy(permit)
                        if name == "schema_version":
                            forged.pop("run_request")
                            forged[name] = value
                        else:
                            forged["run_request"]["run_authority"][name] = value
                        raw = canonical(forged) + b"\n"
                        wrong = path.parent / (name + str(index) + ".json")
                        wrong.write_bytes(raw)
                        with self.assertRaises(SessionApiError):
                            model.register(
                                ref,
                                operation="analyze-full-paper",
                                permit_path=wrong,
                                permit_sha256=sha(raw),
                            )

    def test_malformed_saved_action_keys_refuse_before_owner_lookup(self):
        from research_workspace_native.project_model_run import saved

        for value in (None, [], {}):
            with self.subTest(value=value), self.assertRaises(SessionApiError):
                saved(
                    None,
                    "alice",
                    "project",
                    {
                        "confirmed": False,
                        "key": "invalid-work",
                        "run_authority": {"action_key": value},
                    },
                    action="model-authorize",
                    operation="analyze-full-paper",
                )

    def test_expiry_at_each_provider_phase_refuses_without_turn_start_or_refund(self):
        for blocked in ["reserve", "spawn", "action"]:
            with (
                self.subTest(phase=blocked),
                setup_case(blocked) as (
                    case,
                    fx,
                    model,
                    issuer,
                    grant,
                    consent,
                    derived,
                    now,
                    calls,
                    phases,
                    _,
                ),
            ):
                ref = fx["ref"]
                body, token = authorize(case, fx, model, consent, derived)
                saved = model.authorize(
                    "alice-token", ref, body, run_authorization=token
                )
                self.assertTrue(saved.get("connected"), saved)
                offer = saved["offer"]
                rb, rt = derived(
                    "model-execute",
                    dict(
                        offer_ref=offer["offer_ref"], offer_sha256=offer["offer_sha256"]
                    ),
                )
                model.execute("alice-token", ref, rb, run_authorization=rt)
                worker = model._workers[(ref, rb["key"])]
                worker.join(90)
                self.assertFalse(worker.is_alive())
                job = model._job("alice", ref, rb["key"])
                self.assertNotEqual(job["status"], "content-review-pending", job)
                self.assertNotIn(blocked, phases)
                self.assertNotIn("action", phases)
                self.assertEqual(model.read("alice-token", ref)["calls_reserved"], 1)
                self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
