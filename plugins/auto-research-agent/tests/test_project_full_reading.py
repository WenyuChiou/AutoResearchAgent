from copy import deepcopy
import unittest
from unittest.mock import patch
from stage1_deliverable.common import canonical, sha
from stage1_deliverable.records import CLASSIFICATION, FINDINGS
from test_project_stage1_records import saved_stage1_case
import test_project_stage1_delivery as delivery_fixture
import test_stage1_deliverable as package_fixture
import test_project_model_factory as factory_fixture
from research_workspace_native.session_api import SessionApiError
from research_workspace_native.model_input_profile import turn_input
import test_project_model_reading as reading_fixture
from research_workspace_native import project_full_reading as reading
from research_workspace_native import project_model as service


class FullReadingServiceTests(unittest.TestCase):
    def test_full_saved_tail_flows_through_auth_queue_and_draft_without_core_claims(
        self,
    ):
        original = package_fixture.ResearchDeliverableTests.make_records

        def long_records(case, raw=package_fixture.HTML, **kw):
            raw = raw.replace(
                b"</article>",
                b"<p>"
                + b"saved whole source " * 850
                + b"FULL_SOURCE_AFTER_TAIL</p></article>",
            )
            return original(case, raw=raw, **kw)

        original_submit = delivery_fixture.submit_body

        def funded(v):
            b = original_submit(v)
            b["budgets"].update(model_calls=2, seconds=120)
            return b

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
            called = []
            before = fx["ledger"].state_hash()

            def factory(*, context, admit, output_root):
                called.append(context)
                self.assertEqual(
                    context["input_profile"], "stage1-full-source-context-1.0"
                )
                snap = context["saved_reading"]["full_source"]
                row = snap["sources"][0]
                raw = row["text"].encode("utf8")
                quote = "FULL_SOURCE_AFTER_TAIL"
                start = raw.index(quote.encode())
                self.assertGreater(start, 10000)
                answer = dict(
                    summary="Synthetic full saved text draft; applicability Unknown.",
                    classification={n: "Unknown" for n in CLASSIFICATION},
                    findings={n: "Unknown" for n in FINDINGS},
                    limitations=["Scientific support unassessed."],
                    open_questions=["Applicability Unknown."],
                    evidence=[
                        dict(
                            source_id=row["source_id"],
                            text_sha256=row["text_sha256"],
                            start_byte=start,
                            end_byte=start + len(quote),
                            quote=quote,
                            claim_id=None,
                        )
                    ],
                )

                class Reader:
                    def run(inner, key, prompt, deadline):
                        self.assertIn(quote, prompt)
                        self.assertGreater(len(prompt.encode()), 10000)
                        event = dict(
                            unit_key=key,
                            prompt_sha256=sha(prompt.encode()),
                            source_sha256=context["source_sha256"],
                            permit_sha256=context["permit_sha256"],
                            event={},
                        )
                        self.assertTrue(admit(dict(event, phase="reserve")))
                        self.assertTrue(admit(dict(event, phase="spawn")))
                        scopes = [
                            dict(
                                source_id=row["source_id"],
                                source_observation_scope=row[
                                    "source_observation_scope"
                                ],
                            )
                            for row in context["saved_reading"]["saved_reading"][
                                "sources"
                            ]
                        ]
                        self.assertIn(canonical(scopes).decode("utf8"), prompt)
                        self.assertIn(
                            "Complete saved text is not proof of a complete publication",
                            prompt,
                        )
                        payload = dict(
                            model=context["model"],
                            **turn_input(prompt, context["input_profile"]),
                        )
                        for fault in (
                            "tail",
                            "missing-context",
                            "instruction",
                            "extra-context",
                            "model",
                        ):
                            changed = deepcopy(payload)
                            if fault == "tail":
                                last = sorted(changed["additionalContext"])[-1]
                                changed["additionalContext"][last]["value"] += "changed"
                            elif fault == "missing-context":
                                del changed["additionalContext"]
                            elif fault == "instruction":
                                changed["input"][0]["text"] += "changed"
                            elif fault == "extra-context":
                                changed["additionalContext"]["foreign"] = dict(
                                    kind="untrusted", value="extra"
                                )
                            else:
                                changed["model"] = "foreign-model"
                            with (
                                self.subTest(action_refusal=fault),
                                self.assertRaisesRegex(
                                    SessionApiError, "model-native-prompt-differs"
                                ),
                            ):
                                admit(
                                    dict(
                                        event,
                                        phase="action",
                                        event=dict(
                                            action=dict(
                                                method="turn/start", payload=changed
                                            )
                                        ),
                                    )
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
                preview = model.full_reading_offer(
                    "alice-token",
                    ref,
                    work,
                    expected_input_version=view["input_version"],
                    expected_ledger_state_sha256=before,
                )
                self.assertTrue(preview["available"], preview)
                self.assertEqual(called, [])
                self.assertEqual(fx["ledger"].state_hash(), before)
                auth = dict(
                    key="full-reading-auth",
                    **{
                        n: view[n]
                        for n in ("revision", "input_version", "brief_sha256")
                    },
                    operation=reading.FULL_READ_OPERATION,
                    work_ref=work,
                    snapshot_sha256=preview["snapshot_sha256"],
                    confirmed=True,
                    user_input="Read the saved complete synthetic source once; no scientific acceptance.",
                )
                for change in ({"confirmed": False}, {"snapshot_sha256": "0" * 64}):
                    with self.subTest(authorization=change):
                        rejected = dict(auth, **change)
                        rejected["key"] = "rejected-" + sha(canonical(change))[:12]
                        with self.assertRaises(SessionApiError):
                            model.authorize("alice-token", ref, rejected)
                        self.assertEqual(called, [])
                        self.assertEqual(fx["ledger"].state_hash(), before)
                auth.update(
                    {
                        n: case.intake.read("alice-token", ref)[n]
                        for n in ("revision", "input_version", "brief_sha256")
                    }
                )
                with patch.object(model, "reading_records", None):
                    with self.assertRaises(SessionApiError) as unavailable:
                        model.authorize(
                            "alice-token",
                            ref,
                            dict(auth, key="unconnected-source-owner"),
                        )
                    self.assertEqual(
                        unavailable.exception.code, "intake-operation-failed"
                    )
                    self.assertEqual(
                        unavailable.exception.__cause__.code,
                        "reading-records-unconnected",
                    )
                auth.update(
                    {
                        n: case.intake.read("alice-token", ref)[n]
                        for n in ("revision", "input_version", "brief_sha256")
                    }
                )
                offer = model.authorize("alice-token", ref, auth)["offer"]
                self.assertEqual(offer["scope"], reading.FULL_READ_SCOPE)
                v = case.intake.read("alice-token", ref)
                body = dict(
                    key="full-reading",
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
                self.assertFalse(job["reading_draft"]["core_claims_created"])
                self.assertFalse(job["reading_draft"]["researcher_acceptance"])
                self.assertEqual(job["calls_reserved"], 1)
                self.assertEqual(len(called), 1)
                self.assertTrue(model.execute("alice-token", ref, body)["replayed"])
                self.assertEqual(len(called), 1)
                self.assertEqual(fx["ledger"].state_hash(), before)
                # Exercise the actual production factory with only its StageModel seam
                # replaced: no account probe, process, SDK call or model execution.
                boundary = factory_fixture.ProjectModelFactoryTests(
                    methodName="runTest"
                )
                boundary.setUp()
                self.addCleanup(boundary.doCleanups)
                native_factory = boundary.factory()
                original_context = deepcopy(called[0])
                for name in (
                    "profile",
                    "prompt",
                    "snapshot",
                    "source-bytes",
                    "legacy-profile",
                ):
                    with self.subTest(factory_refusal=name):
                        context = deepcopy(original_context)
                        if name == "profile":
                            context["input_profile"] = "legacy"
                        elif name == "prompt":
                            context["prompt_sha256"] = "0" * 64
                        elif name == "snapshot":
                            context["snapshot_sha256"] = "0" * 64
                        elif name == "source-bytes":
                            context["saved_reading"]["full_source"]["sources"][0][
                                "text"
                            ] += "changed"
                            context["snapshot_sha256"] = sha(
                                canonical(context["saved_reading"])
                            )
                        else:
                            context["operation"] = "read-paper"
                        context["source_sha256"] = sha(
                            canonical(
                                {
                                    k: v
                                    for k, v in context.items()
                                    if k != "source_sha256"
                                }
                            )
                        )
                        with patch(
                            "subprocess.Popen", side_effect=AssertionError("no process")
                        ):
                            with self.assertRaises((ValueError, SessionApiError)):
                                native_factory(
                                    context=context,
                                    admit=lambda event: True,
                                    output_root=boundary.root / "native-units",
                                )
                        self.assertEqual(boundary.created, [])
                        self.assertFalse(
                            (boundary.root / "project-model-input").exists()
                        )
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

    def test_unconnected_records_are_typed_before_intake_access(self):
        with self.assertRaisesRegex(SessionApiError, "reading-records-unconnected"):
            reading.saved_full_reading_snapshot(None, "project", "work")

    def test_legacy_native_action_still_uses_exact_prompt_and_no_extra_context(self):
        original_admit = service.ProjectModelService._admit
        observed = []

        def checked(model, principal, ref, key, offer, event):
            result = original_admit(model, principal, ref, key, offer, event)
            if event["phase"] == "spawn":
                self.assertNotIn("input_profile", offer["context"])
                payload = dict(
                    model=offer["context"]["model"], **turn_input(offer["prompt"])
                )
                self.assertEqual(payload["input"][0]["text"], offer["prompt"])
                injected = dict(
                    payload,
                    additionalContext={
                        "foreign": dict(kind="untrusted", value="extra")
                    },
                )
                with self.assertRaisesRegex(
                    SessionApiError, "model-native-prompt-differs"
                ):
                    original_admit(
                        model,
                        principal,
                        ref,
                        key,
                        offer,
                        dict(
                            event,
                            phase="action",
                            event=dict(
                                action=dict(method="turn/start", payload=injected)
                            ),
                        ),
                    )
                self.assertTrue(
                    original_admit(
                        model,
                        principal,
                        ref,
                        key,
                        offer,
                        dict(
                            event,
                            phase="action",
                            event=dict(
                                action=dict(method="turn/start", payload=payload)
                            ),
                        ),
                    )
                )
                observed.append(True)
            return result

        fixture = reading_fixture.SavedReadingTests(
            methodName="test_shared_queue_reserves_once_and_publishes_only_verified_reading_draft"
        )
        self.addCleanup(fixture.doCleanups)
        with patch.object(service.ProjectModelService, "_admit", new=checked):
            fixture.test_shared_queue_reserves_once_and_publishes_only_verified_reading_draft()
        self.assertEqual(observed, [True])


if __name__ == "__main__":
    unittest.main()
