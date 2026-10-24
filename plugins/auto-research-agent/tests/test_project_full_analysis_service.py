"""Source-bound semantic proposal through the real model queue; synthetic provider."""

from copy import deepcopy
import unittest
from unittest.mock import patch

from stage1_deliverable.common import canonical, sha
from stage1_deliverable.records import CLASSIFICATION, FINDINGS
from research_workspace_native import project_model as service
from research_workspace_native.project_full_analysis import (
    ANALYZE_OPERATION,
    ANALYZE_SCOPE,
)
from research_workspace_native.model_input_profile import turn_input
from research_workspace_native.session_api import SessionApiError
from test_project_stage1_records import saved_stage1_case
import test_project_stage1_delivery as delivery_fixture
import test_stage1_deliverable as package_fixture
import test_project_model_factory as factory_fixture


class FullAnalysisServiceTests(unittest.TestCase):
    def test_proposal_queue_profile_factory_replay_without_canonical_adoption(self):
        original = package_fixture.ResearchDeliverableTests.make_records
        original_submit = delivery_fixture.submit_body
        tail = "EXACT_ANALYSIS_TAIL"

        def long_records(case, raw=package_fixture.HTML, **kw):
            raw = raw.replace(
                b"</article>",
                b"<p>" + b"complete source " * 850 + tail.encode() + b"</p></article>",
            )
            return original(case, raw=raw, **kw)

        def funded(v):
            body = original_submit(v)
            body["budgets"].update(model_calls=2, seconds=120)
            return body

        with (
            patch.object(
                package_fixture.ResearchDeliverableTests,
                "make_records",
                new=long_records,
            ),
            patch.object(delivery_fixture, "submit_body", side_effect=funded),
            saved_stage1_case() as (case, fx),
        ):
            ref = fx["ref"]
            work = fx["records"]["papers"][0]["work_id"]
            state = fx["ledger"].state_hash()
            calls = []
            drafts = []

            def factory(*, context, admit, output_root):
                calls.append(context)
                child = context["saved_reading"]["reading_input"]
                row = child["full_source"]["sources"][0]
                raw = row["text"].encode()
                start = raw.index(tail.encode())
                self.assertGreater(start, 10000)
                need = child["brief"]["needs"][0]["need_id"]
                answer = dict(
                    kind="Stage1FullSourceAnalysisProposal",
                    schema_version="1.0.0",
                    reading=dict(
                        summary="Synthetic analysis; support Unknown.",
                        classification={n: "Unknown" for n in CLASSIFICATION},
                        findings={n: "Unknown" for n in FINDINGS},
                        limitations=["Scientific support unassessed."],
                        open_questions=["Applicability Unknown."],
                        evidence=[
                            dict(
                                source_id=row["source_id"],
                                text_sha256=row["text_sha256"],
                                start_byte=start,
                                end_byte=start + len(tail),
                                quote=tail,
                                claim_id=None,
                            )
                        ],
                    ),
                    screening=dict(
                        decision="pending",
                        need_ids=[need],
                        reason_code="needs-content-review",
                        rationale="Synthetic receipt only.",
                        missing_information=[
                            "Scientific relevance remains unassessed."
                        ],
                    ),
                    claims=[
                        dict(
                            claim_key="tail",
                            claim_text="Synthetic passage proposal.",
                            relation="unclear",
                            evidence_index=0,
                            section="Unknown",
                            assessment=dict(
                                reason_code="support-unassessed",
                                rationale="Synthetic receipt only.",
                            ),
                        )
                    ],
                )

                class Reader:
                    def run(inner, key, prompt, deadline):
                        self.assertEqual(prompt.count(tail), 1)
                        self.assertIn(need, prompt)
                        self.assertEqual(
                            context["input_profile"], "stage1-full-source-context-1.0"
                        )
                        event = dict(
                            unit_key=key,
                            prompt_sha256=sha(prompt.encode()),
                            source_sha256=context["source_sha256"],
                            permit_sha256=context["permit_sha256"],
                            event={},
                        )
                        self.assertTrue(admit(dict(event, phase="reserve")))
                        self.assertTrue(admit(dict(event, phase="spawn")))
                        payload = dict(
                            model=context["model"],
                            **turn_input(prompt, context["input_profile"]),
                        )
                        self.assertTrue(
                            admit(
                                dict(
                                    event,
                                    phase="action",
                                    event=dict(
                                        action=dict(
                                            method="turn/start", payload=payload
                                        )
                                    ),
                                )
                            )
                        )
                        return dict(
                            status="completed",
                            prompt_sha256=event["prompt_sha256"],
                            source_sha256=event["source_sha256"],
                            final_text=canonical(answer).decode(),
                            synthetic=True,
                        )

                    def verify_receipt(inner, receipt, **expected):
                        return receipt

                drafts.append(answer)
                return Reader()

            model = service.ProjectModelService(
                case.intake,
                provider_factory=factory,
                model="synthetic-reader",
                local_cap_seconds=30,
                clock=lambda: 1_900_000_000,
                reading_records=case.producer,
            )
            try:
                view = case.intake.read("alice-token", ref)
                preview = model.full_analysis_offer(
                    "alice-token",
                    ref,
                    work,
                    expected_input_version=view["input_version"],
                    expected_ledger_state_sha256=state,
                )
                self.assertTrue(preview["available"], preview)
                self.assertEqual(preview["operation"], ANALYZE_OPERATION)
                self.assertFalse(preview["execution_authorized"])
                self.assertEqual(calls, [])
                with self.assertRaises(SessionApiError):
                    model.full_analysis_offer(
                        "wrong-token",
                        ref,
                        work,
                        expected_input_version=view["input_version"],
                        expected_ledger_state_sha256=state,
                    )
                stale = model.full_analysis_offer(
                    "alice-token",
                    ref,
                    work,
                    expected_input_version=True,
                    expected_ledger_state_sha256=state,
                )
                self.assertFalse(stale["available"])
                auth = dict(
                    key="analysis-auth",
                    **{
                        n: view[n]
                        for n in ("revision", "input_version", "brief_sha256")
                    },
                    operation=ANALYZE_OPERATION,
                    work_ref=work,
                    snapshot_sha256=preview["snapshot_sha256"],
                    confirmed=True,
                    user_input="Analyze the complete synthetic saved source once, proposals only.",
                )
                for mutation in (dict(confirmed=False), dict(snapshot_sha256="0" * 64)):
                    bad = dict(
                        auth, **mutation, key="bad-" + sha(canonical(mutation))[:10]
                    )
                    with self.assertRaises(SessionApiError):
                        model.authorize("alice-token", ref, bad)
                    self.assertEqual(calls, [])
                auth.update(
                    {
                        n: case.intake.read("alice-token", ref)[n]
                        for n in ("revision", "input_version", "brief_sha256")
                    }
                )
                offer = model.authorize("alice-token", ref, auth)["offer"]
                self.assertEqual(offer["scope"], ANALYZE_SCOPE)
                v = case.intake.read("alice-token", ref)
                body = dict(
                    key="analysis",
                    **{n: v[n] for n in ("revision", "input_version", "brief_sha256")},
                    offer_ref=offer["offer_ref"],
                    offer_sha256=offer["offer_sha256"],
                    confirmed=True,
                )
                model.execute("alice-token", ref, body)
                worker = model._workers[(ref, body["key"])]
                worker.join(90)
                self.assertFalse(worker.is_alive())
                job = model.history("alice-token", ref)["actions"][-1]
                self.assertEqual(job["status"], "content-review-pending", job)
                self.assertNotIn("reading_draft", job)
                self.assertEqual(job["calls_reserved"], 1)
                self.assertFalse(job["analysis_draft"]["core_claims_created"])
                self.assertFalse(job["analysis_draft"]["researcher_acceptance"])
                self.assertEqual(job["analysis_draft"]["evidence_count"], 1)
                self.assertTrue(model.execute("alice-token", ref, body)["replayed"])
                self.assertEqual(len(calls), 1)
                self.assertEqual(fx["ledger"].state_hash(), state)

                boundary = factory_fixture.ProjectModelFactoryTests(
                    methodName="runTest"
                )
                boundary.setUp()
                self.addCleanup(boundary.doCleanups)
                native_factory = boundary.factory()
                original_context = deepcopy(calls[0])
                for fault in ("cross-operation", "needs", "source", "profile"):
                    with self.subTest(factory_refusal=fault):
                        context = deepcopy(original_context)
                        if fault == "cross-operation":
                            context["operation"] = "read-full-paper"
                        elif fault == "needs":
                            context["saved_reading"]["reading_input"]["brief"]["needs"][
                                0
                            ]["question"] += "changed"
                        elif fault == "source":
                            context["saved_reading"]["reading_input"]["full_source"][
                                "sources"
                            ][0]["text"] += "changed"
                        else:
                            del context["input_profile"]
                        context["source_sha256"] = sha(
                            canonical(
                                {
                                    k: v
                                    for k, v in context.items()
                                    if k != "source_sha256"
                                }
                            )
                        )
                        with (
                            patch(
                                "subprocess.Popen",
                                side_effect=AssertionError("no process"),
                            ),
                            self.assertRaises((ValueError, SessionApiError)),
                        ):
                            native_factory(
                                context=context,
                                admit=lambda event: True,
                                output_root=boundary.root / "native-units",
                            )
                        self.assertEqual(boundary.created, [])
                with patch(
                    "subprocess.Popen", side_effect=AssertionError("no process")
                ):
                    provider = native_factory(
                        context=original_context,
                        admit=lambda event: True,
                        output_root=boundary.root / "native-units",
                    )
                self.assertEqual(len(boundary.created), 1)
                native_model = boundary.created[0]
                self.assertEqual(
                    native_model.kwargs["input_profile"],
                    "stage1-full-source-context-1.0",
                )
                frozen = native_model.checked["source_root"] / "saved-reading.json"
                self.assertEqual(
                    frozen.read_bytes(),
                    canonical(original_context["saved_reading"]) + b"\n",
                )
                frozen.write_bytes(frozen.read_bytes() + b" ")
                with self.assertRaisesRegex(ValueError, "frozen model input changed"):
                    provider.run("no-resend", "synthetic", 1)
                self.assertEqual(native_model.calls, [])
                with self.assertRaises(ValueError):
                    provider.close()
                self.assertTrue(native_model.closed)
            finally:
                model.close()


if __name__ == "__main__":
    unittest.main()
