"""Existing full-source owners and actual factory, with FakeStageModel only."""

from contextlib import ExitStack, contextmanager
from copy import deepcopy
import json
from pathlib import Path
import sys
import time
from types import MethodType, SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cli"))

from analysis_run_fixture import analysis_proposal
import test_project_model_factory as factory_fixture
import test_project_stage1_delivery as delivery_fixture
import test_stage1_deliverable as source_fixture
from test_project_stage1_records import saved_stage1_case
from test_workspace_project_intake import bound_body
from research_workspace_native.model_input_profile import turn_input
from research_workspace_native.project_host import ProjectHost
from research_workspace_native.project_model import (
    ProjectModelService,
    ANALYZE_OPERATION,
)
from research_workspace_native.project_records_prepare import (
    ProjectRecordsPrepareService,
)
from research_workspace_native.project_stage1_full_source import (
    full_analysis_note,
    full_analysis_projection,
)
from research_workspace_native.project_stage1_delivery import MAX_RECORD_BYTES
from research_workspace_native.project_stage1_run_grant import (
    ProjectStage1RunGrantService,
    SCOPE,
)
from research_workspace_native.session_api import SessionApiError
from stage1_deliverable.common import canonical, sha


class FullSourceAdapterTests(unittest.TestCase):
    factory = factory_fixture.ProjectModelFactoryTests.factory

    def setUp(self):
        factory_fixture.ProjectModelFactoryTests.setUp(self)

    @contextmanager
    def case(self, *, calls=2, text_bytes=8192, operations=None):
        original_submit = delivery_fixture.submit_body
        original_records = source_fixture.ResearchDeliverableTests.make_records

        def funded(view):
            body = original_submit(view)
            body["budgets"].update(model_calls=calls, seconds=1000)
            return body

        def records(case, raw=source_fixture.HTML, **options):
            raw = raw.replace(
                b"</article>", b"<p>" + b"Q" * text_bytes + b"</p></article>"
            )
            return original_records(case, raw=raw, **options)

        with ExitStack() as stack:
            stack.enter_context(patch.object(delivery_fixture, "submit_body", funded))
            stack.enter_context(
                patch.object(
                    source_fixture.ResearchDeliverableTests, "make_records", records
                )
            )
            case, saved = stack.enter_context(saved_stage1_case())
            self.assertions = []
            seen = self.assertions
            created = self.created

            class Reader(factory_fixture.FakeStageModel):
                def run(inner, key, prompt, deadline):
                    context = json.loads(inner.checked["config_path"].read_bytes())
                    seen.append(deepcopy(context))
                    event = dict(
                        unit_key=key,
                        prompt_sha256=sha(prompt.encode()),
                        source_sha256=context["source_sha256"],
                        permit_sha256=context["permit_sha256"],
                        event={},
                    )
                    admit = inner.kwargs["admit"]
                    admit(dict(event, phase="reserve"))
                    admit(dict(event, phase="spawn"))
                    admit(
                        dict(
                            event,
                            phase="action",
                            event=dict(
                                action=dict(
                                    method="turn/start",
                                    payload=dict(
                                        model=context["model"],
                                        **turn_input(prompt, context["input_profile"]),
                                    ),
                                )
                            ),
                        )
                    )
                    return dict(
                        status="completed",
                        prompt_sha256=event["prompt_sha256"],
                        source_sha256=context["source_sha256"],
                        final_text=canonical(analysis_proposal(context)).decode(),
                        synthetic=True,
                    )

            def fake(checked, **options):
                reader = Reader(checked, **options)
                created.append(reader)
                return reader

            self.fake = fake
            model = ProjectModelService(
                case.intake,
                provider_factory=self.factory(),
                model="synthetic-analysis",
                local_cap_seconds=30,
                clock=lambda: 1_900_000_000,
                reading_records=case.producer,
            )
            stack.callback(model.close)
            issuer = ProjectStage1RunGrantService(
                case.intake, runtime_sha256="a" * 64, clock=lambda: 1_900_000_000
            )
            model.run_grants = issuer
            ref = saved["ref"]
            grant = issuer.authorize(
                "alice-token",
                ref,
                {
                    **bound_body(
                        case.intake.read("alice-token", ref), "full-source-run"
                    ),
                    "confirmed": True,
                    "user_input": "Authored fixture run only.",
                    "scope": SCOPE,
                    "operations": ["analyze-full-paper", "agent-adoption", "records"]
                    if operations is None
                    else operations,
                    "max_seconds": 600,
                    "max_actions": 32,
                },
            )
            host = SimpleNamespace(
                projects=case.intake,
                project_stage1=case.delivery.stage1,
                project_models=model,
                project_stage2=None,
                project_stage1_delivery=case.delivery,
                project_stage1_records=case.producer,
                project_records_prepare=ProjectRecordsPrepareService(case.producer),
                project_stage1_sources=None,
                project_expansions=None,
                project_stage1_source_dispatcher=None,
                host_binding={},
                _assets={},
            )
            for name in (
                "overview",
                "stage1_view",
                "continue_stage1",
                "register_stage1_full_source",
            ):
                setattr(host, name, MethodType(getattr(ProjectHost, name), host))
            output = self.root / "full-source"
            output.mkdir()
            host.register_stage1_full_source(
                "alice-token",
                ref,
                run_grants=issuer,
                grant_ref=grant["grant_ref"],
                grant_sha256=grant["grant_sha256"],
                output_root=output,
            )
            yield SimpleNamespace(
                host=host,
                case=case,
                ref=ref,
                model=model,
                issuer=issuer,
                grant=grant,
                adapter=host.project_stage1_full_source_execution,
                output=output,
                saved=saved,
            )

    def test_producer_actual_factory_adoption_registration_notes_and_no_resend(self):
        with self.case() as run:
            result = run.host.continue_stage1(
                "alice-token",
                run.ref,
                run_id="authored-full-source",
                deadline=time.monotonic() + 600,
                max_actions=16,
            )
            self.assertNotEqual(result["status"], "failed", result)
            progress = result["automatic_production"]
            self.assertEqual(len(self.assertions), 2, result)
            self.assertEqual(len(progress["automatically_recorded"]), 2, result)
            self.assertTrue(
                all(
                    r["reading_registration_complete"]
                    for r in progress["automatically_recorded"]
                ),
                result,
            )
            self.assertEqual(len(progress["notes"]), 2)
            self.assertEqual(len(progress["researcher_questions"]), 2)
            self.assertEqual(progress["model_calls_reserved"], 2)
            saved = [
                json.loads(row[0])
                for row in run.case.intake.db.execute(
                    "SELECT receipt FROM intake_actions WHERE principal=? AND project=?",
                    ("alice", run.ref),
                ).fetchall()
            ]
            authorizations = [r for r in saved if r["kind"] == "model-authorization"]
            self.assertEqual(len(authorizations), 2)
            self.assertTrue(
                all(r["request"]["confirmed"] is False for r in authorizations)
            )
            self.assertFalse(result["stage2_started"])
            for context in self.assertions:
                self.assertEqual(context["operation"], ANALYZE_OPERATION)
                full = context["saved_reading"]["reading_input"]["full_source"]
                self.assertGreater(len(full["sources"][0]["text"].encode()), 1600)
            for row in progress["notes"]:
                note = run.adapter.note_by_hash("alice-token", run.ref, row["sha256"])
                self.assertEqual(note["bytes"], len(note["text"].encode()))
                self.assertFalse(note["human_acceptance"])
                self.assertIn("support-unassessed", note["text"])
                self.assertIn("semantic_projection_complete", note["text"])
                self.assertIn("original_source_scopes", note["text"])
                self.assertEqual(sha(note["text"].encode()), row["sha256"])
                self.assertTrue((run.output / (row["sha256"] + ".md")).is_file())
            before = run.case.intake.history("alice-token", run.ref)
            with patch.object(
                run.adapter.queue,
                "inspect",
                side_effect=AssertionError("no future model offer selection"),
            ):
                run.adapter.read("alice-token", run.ref)
            self.assertEqual(before, run.case.intake.history("alice-token", run.ref))
            with patch.object(
                run.adapter.records,
                "reading_readiness",
                return_value=dict(
                    status="held", reason="authored-held", missing_works=[]
                ),
            ):
                held = run.adapter.read("alice-token", run.ref)
            self.assertTrue(held["technical_blocked"])
            self.assertTrue(
                all(
                    not r["reading_registration_complete"]
                    for r in held["automatically_recorded"]
                )
            )
            count = len(self.assertions)
            run.host.continue_stage1(
                "alice-token",
                run.ref,
                run_id="authored-full-source",
                deadline=time.monotonic() + 60,
                max_actions=2,
            )
            self.assertEqual(len(self.assertions), count)
            adoption = next(r for r in saved if r["kind"] == "stage1-agent-analysis")
            original_receipt = run.case.intake.db.execute(
                "SELECT receipt FROM intake_actions WHERE principal=? AND project=? AND key=?",
                ("alice", run.ref, adoption["key"]),
            ).fetchone()[0]
            unobserved = dict(adoption, status="execution-unknown")
            run.case.intake.db.execute(
                "UPDATE intake_actions SET receipt=? WHERE principal=? AND project=? AND key=?",
                (canonical(unobserved).decode(), "alice", run.ref, adoption["key"]),
            )
            run.case.intake.db.commit()
            try:
                uncertain = run.adapter.read("alice-token", run.ref)
                self.assertTrue(
                    any(
                        r.get("key") == adoption["key"]
                        and r.get("status") == "execution-unknown"
                        for r in uncertain["technical_blocked"]
                    )
                )
                stopped = run.host.continue_stage1(
                    "alice-token",
                    run.ref,
                    run_id="authored-full-source",
                    deadline=time.monotonic() + 60,
                    max_actions=2,
                )
                self.assertEqual(stopped["status"], "held", stopped)
                self.assertEqual(stopped["action_count"], 0)
                self.assertEqual(len(self.assertions), count)
            finally:
                run.case.intake.db.execute(
                    "UPDATE intake_actions SET receipt=? WHERE principal=? AND project=? AND key=?",
                    (original_receipt, "alice", run.ref, adoption["key"]),
                )
                run.case.intake.db.commit()
            job = next(
                iter(
                    run.case.intake._load("alice", run.ref)["model_operations"][
                        "jobs"
                    ].values()
                )
            )
            folder = run.model._runtime_folder("alice", run.ref, job)
            (folder / "output.txt").write_bytes(b"tampered saved analysis")
            with self.assertRaises(SessionApiError):
                run.adapter.note_by_hash(
                    "alice-token", run.ref, progress["notes"][0]["sha256"]
                )
            self.assertEqual(len(self.assertions), count)

    def test_insufficient_remaining_calls_saves_partial_without_permission_or_dispatch(
        self,
    ):
        with self.case(calls=1) as run:
            before = run.case.intake.history("alice-token", run.ref)
            result = run.host.continue_stage1(
                "alice-token",
                run.ref,
                run_id="underfunded",
                deadline=time.monotonic() + 60,
                max_actions=8,
            )
            self.assertEqual(result["status"], "partial", result)
            self.assertEqual(
                result["reason"], "remaining-model-call-budget-insufficient"
            )
            self.assertEqual(self.assertions, [])
            self.assertEqual(before, run.case.intake.history("alice-token", run.ref))
            self.assertTrue(Path(result["automatic_notes_companion"]["path"]).is_file())
            self.assertFalse(result["stage1_complete"])

    def test_oversize_full_source_stops_before_model_permission_or_dispatch(self):
        with self.case(text_bytes=300_000) as run:
            result = run.host.continue_stage1(
                "alice-token",
                run.ref,
                run_id="oversize-full-source",
                deadline=time.monotonic() + 60,
                max_actions=4,
            )
            self.assertEqual(self.assertions, [])
            self.assertEqual(run.model.read("alice-token", run.ref)["job_count"], 0)
            self.assertEqual(run.model.offers("alice-token", run.ref)["offers"], [])
            self.assertEqual(
                result["automatic_production"]["automatically_recorded"], []
            )
            self.assertFalse(result["stage1_complete"])

    def test_oversize_note_refuses_without_clipping(self):
        with self.assertRaises(SessionApiError) as raised:
            full_analysis_note(dict(original="Q" * MAX_RECORD_BYTES))
        self.assertEqual(raised.exception.code, "full-source-note-too-large")

    def test_missing_full_analysis_authority_cannot_register_adapter(self):
        with self.assertRaises(SessionApiError) as raised:
            with self.case(operations=["agent-adoption", "records"]):
                self.fail("missing full-analysis authority must refuse registration")
        self.assertEqual(
            raised.exception.code, "full-source-run-operations-not-authorized"
        )
        self.assertEqual(self.assertions, [])

    def test_projection_replays_quote_reason_and_source_binding_guards(self):
        with self.case() as run:
            work = run.saved["records"]["papers"][0]["work_id"]
            snapshot = run.model._operation_reading_snapshot(
                ANALYZE_OPERATION, run.ref, work, analysis_version="1.0.0"
            )
            value = analysis_proposal(dict(saved_reading=snapshot))
            projection = full_analysis_projection(canonical(value), snapshot)
            self.assertEqual(
                projection["claims"][0]["assessment"], value["claims"][0]["assessment"]
            )
            for key in ("quote", "text_sha256"):
                changed = deepcopy(value)
                changed["reading"]["evidence"][0][key] = "invalid"
                with self.assertRaises(SessionApiError):
                    full_analysis_projection(canonical(changed), snapshot)
            changed = deepcopy(value)
            del changed["claims"][0]["assessment"]
            with self.assertRaises(SessionApiError):
                full_analysis_projection(canonical(changed), snapshot)
            self.assertEqual(self.assertions, [])

    def test_cross_project_and_expired_grant_cannot_acquire_new_authority(self):
        with self.case() as run:
            with self.assertRaises(SessionApiError):
                run.adapter.read("alice-token", "foreign-project")
            with self.assertRaises(SessionApiError):
                run.adapter.read("bad-token", run.ref)
            before = run.case.intake.history("alice-token", run.ref)
            run.issuer.clock = lambda: 2_000_000_000
            with self.assertRaises(SessionApiError):
                run.adapter.preflight("alice-token", run.ref)
            self.assertEqual(before, run.case.intake.history("alice-token", run.ref))
            self.assertEqual(self.assertions, [])
