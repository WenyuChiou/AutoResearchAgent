"""Real saved ledger/model broker/records with authored model output; no live I/O."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import os
import sys
import time
from types import MethodType, SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cli"))

from research_workspace_native.project_host import ProjectHost
from research_workspace_native.project_model import ProjectModelService, budget_digest
from research_workspace_native.project_stage1_execution import (
    ProjectStage1ExecutionService,
)
from research_workspace_native.project_stage1_review_units import (
    IDENTITY,
    SCOPE,
    full_note,
    prompt,
    segments,
    validate_result,
)
from research_workspace_native.project_records_prepare import (
    ProjectRecordsPrepareService,
)
from research_workspace_native.session_api import SessionApiError
from stage1_deliverable.common import canonical, sha
from stage1_deliverable.records import CLASSIFICATION, FINDINGS
import test_project_stage1_delivery as delivery_fixture
import test_stage1_deliverable as source_fixture
from test_project_stage1_records import saved_stage1_case


def answer(snapshot):
    if snapshot["unit"] == "segment":
        part = snapshot["segment"]
        quote = part["text"][:24]
        claims = [
            dict(
                text="Authored fixture assertion; scientific support remains unassessed.",
                relation="partial",
                source_id=snapshot["source"]["source_id"],
                text_sha256=snapshot["source"]["text_sha256"],
                start_byte=part["start_byte"],
                end_byte=part["start_byte"] + len(quote.encode("utf8")),
                quote=quote,
            )
        ]
    else:
        claims = deepcopy(
            next((c["claims"][:1] for c in snapshot["children"] if c["claims"]), [])
        )
    modern = snapshot.get("schema_version") == "1.1.0"
    if modern and snapshot["unit"] == "segment":
        claims[0]["assessment"] = dict(
            reason_code="fixture-scope-partial",
            rationale="The authored passage addresses this assertion's local clause; it provides no evidence for extending the finding to other populations or settings.",
        )
    partial = not snapshot.get("projection", {}).get("complete", True)
    return dict(
        summary="Authored automatic reading; model semantics are synthetic.",
        classification={k: "Unknown" for k in CLASSIFICATION},
        findings={k: "Unknown" for k in FINDINGS},
        limitations=["No scientific or human acceptance."],
        claims=claims,
        decision="pending" if partial else "include",
        rationale="Synthetic model output tests source-bound production, not scientific quality.",
        cluster_claims={} if partial else {snapshot["cluster_ids"][0]: 0},
        identity_status="unverifiable",
        identity_claims={k: None for k in IDENTITY},
        closest=False,
        questions=[],
    )


class AutomaticReadingUnitTests(unittest.TestCase):
    def test_unicode_segments_cover_all_bytes_without_prefix_promotion(self):
        raw = ('字"\n\\context ' * 1400).encode("utf8")
        parts = segments(raw)
        self.assertGreater(len(parts), 10)
        self.assertEqual(b"".join(p["text"].encode("utf8") for p in parts), raw)
        self.assertEqual(parts[0]["start_byte"], 0)
        self.assertEqual(parts[-1]["end_byte"], len(raw))
        self.assertTrue(
            all(a["end_byte"] == b["start_byte"] for a, b in zip(parts, parts[1:]))
        )
        for p in parts:
            self.assertEqual(p["sha256"], sha(raw[p["start_byte"] : p["end_byte"]]))

    def snapshot(self):
        raw = "字 exact supporting passage\n".encode("utf8")
        part = segments(raw)[0]
        part["start_byte"] += 80
        part["end_byte"] += 80
        return dict(
            unit="segment",
            task_ref="task",
            work_id="work",
            version_id="version",
            source=dict(
                source_id="source", text_sha256=sha(raw), evidence_level="full-text"
            ),
            segment=part,
            cluster_ids=["cluster"],
            requested_fields=dict(
                classification=list(CLASSIFICATION), findings=list(FINDINGS)
            ),
        )

    def test_nonzero_byte_offsets_and_tampered_quotes(self):
        snapshot = self.snapshot()
        value = answer(snapshot)
        checked = validate_result(canonical(value), snapshot)
        self.assertFalse(checked["human_acceptance"])
        value["claims"][0]["start_byte"] = 0
        with self.assertRaises(SessionApiError):
            validate_result(canonical(value), snapshot)
        value = answer(snapshot)
        value["claims"][0]["quote"] = "invented quotation"
        with self.assertRaises(SessionApiError):
            validate_result(canonical(value), snapshot)

    def test_synthesis_cannot_invent_or_rewrite_child_claims(self):
        segment = self.snapshot()
        child = validate_result(canonical(answer(segment)), segment)
        snapshot = dict(
            unit="synthesis",
            task_ref="root",
            work_id="work",
            version_id="version",
            children=[dict(claims=child["review"]["claims"])],
            cluster_ids=["cluster"],
        )
        value = answer(snapshot)
        validate_result(canonical(value), snapshot)
        value["claims"][0]["text"] = (
            "A different assertion hidden behind the same quote."
        )
        with self.assertRaises(SessionApiError):
            validate_result(canonical(value), snapshot)

    def test_contrary_or_metadata_only_claim_cannot_fill_coverage(self):
        snapshot = self.snapshot()
        value = answer(snapshot)
        value["claims"][0]["relation"] = "contradicts"
        with self.assertRaises(SessionApiError):
            validate_result(canonical(value), snapshot)
        snapshot["source"]["evidence_level"] = "metadata"
        with self.assertRaises(SessionApiError):
            validate_result(canonical(answer(snapshot)), snapshot)

    def test_empty_work_is_not_full_read_and_unread_note_is_visible(self):
        with self.assertRaises(SessionApiError):
            segments(b"")
        snapshot = self.snapshot()
        note = full_note({"task": snapshot}, {})
        self.assertIn(b"NOT READ", note)
        self.assertIn(b"unverified", note)
        self.assertLessEqual(len(prompt(snapshot).encode("utf8")), 10000)


class AutomaticStage1ProductionTests(unittest.TestCase):
    def fixture(self, *, calls=32, corrupt=False, long_source=False):
        original = delivery_fixture.submit_body

        def funded(view):
            body = original(view)
            body["budgets"].update(model_calls=32, seconds=10000, search_calls=0)
            return body

        original_records = source_fixture.ResearchDeliverableTests.make_records

        def source_records(case, raw=source_fixture.HTML, **kwargs):
            if long_source:
                raw = raw.replace(
                    b"</article>",
                    ("<p>Authored full text 字 " * 65 + "</p></article>").encode(
                        "utf8"
                    ),
                )
            return original_records(case, raw=raw, **kwargs)

        from contextlib import ExitStack

        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(
            patch.object(delivery_fixture, "submit_body", side_effect=funded)
        )
        stack.enter_context(
            patch.object(
                source_fixture.ResearchDeliverableTests,
                "make_records",
                new=source_records,
            )
        )
        case, fixture = stack.enter_context(saved_stage1_case())
        calls_seen = []

        def factory(*, context, admit, output_root):
            self.assertFalse(case.intake.db.in_transaction)
            calls_seen.append(context)

            class Reader:
                def run(inner, key, text, deadline):
                    event = dict(
                        unit_key=key,
                        prompt_sha256=sha(text.encode("utf8")),
                        source_sha256=context["source_sha256"],
                        permit_sha256=context["permit_sha256"],
                        event={},
                    )
                    admit(dict(event, phase="reserve"))
                    admit(dict(event, phase="spawn"))
                    # Author the response from the exact model-visible turn,
                    # not from fields retained only in the private snapshot.
                    value = answer(json.loads(text.rsplit("\n", 1)[-1]))
                    if corrupt:
                        value["claims"][0]["quote"] = "not in saved source"
                    return dict(
                        status="completed",
                        prompt_sha256=event["prompt_sha256"],
                        source_sha256=event["source_sha256"],
                        final_text=canonical(value).decode("utf8"),
                        synthetic=True,
                    )

                def verify_receipt(inner, receipt, **expected):
                    return receipt

            return Reader()

        models = ProjectModelService(
            case.intake,
            provider_factory=factory,
            model="synthetic-reader",
            local_cap_seconds=30,
            reading_records=case.producer,
        )
        self.addCleanup(models.close)
        ref = fixture["ref"]
        binding = case.intake.binding(ref)
        root = case.root / "automatic"
        root.mkdir()
        permit = dict(
            kind="Stage1AutomaticProductionPermit",
            schema_version="1.0.0",
            permission_id="synthetic-only-parent",
            principal="alice",
            project_id=binding["project_id"],
            input_version=binding["input_version"],
            brief_sha256=binding["brief_sha256"],
            plan_manifest_sha256=binding["plan_manifest_sha256"],
            budget_sha256=budget_digest(binding),
            model="synthetic-reader",
            max_calls=calls,
            max_seconds=1000,
            expires_at=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
            allow_model_calls=True,
            allow_source_acquisition=False,
            allow_query_expansions=False,
            automatic_screening=True,
            execution_scope=SCOPE,
            external_search=False,
            frozen_subjects=False,
            stage2_execution=False,
            executor_sha256=sha(
                Path(
                    sys.modules[ProjectStage1ExecutionService.__module__].__file__
                ).read_bytes()
            ),
            review_units_sha256=sha(
                Path(sys.modules[segments.__module__].__file__).read_bytes()
            ),
        )
        path = root / "parent.json"
        path.write_bytes(canonical(permit) + b"\n")
        execution = ProjectStage1ExecutionService(
            case.stage1,
            models,
            case.producer,
            permit_path=path,
            permit_sha256=sha(path.read_bytes()),
            output_root=root,
        )
        host = SimpleNamespace(
            projects=case.intake,
            project_stage1=case.stage1,
            project_models=models,
            project_stage2=None,
            project_stage1_delivery=case.delivery,
            project_stage1_records=case.producer,
            project_records_prepare=ProjectRecordsPrepareService(case.producer),
            project_stage1_sources=None,
            project_expansions=None,
            project_stage1_execution=execution,
        )
        for name in ("overview", "stage1_view", "continue_stage1"):
            setattr(host, name, MethodType(getattr(ProjectHost, name), host))
        return case, fixture, host, execution, calls_seen

    def test_real_saved_sources_segment_review_core_append_notes_and_no_resend(self):
        case, fixture, host, execution, calls = self.fixture(long_source=True)
        original_events = deepcopy(fixture["ledger"].events())
        result = host.continue_stage1(
            "alice-token",
            fixture["ref"],
            run_id="synthetic-full-producer",
            deadline=time.monotonic() + 300,
            max_actions=64,
        )
        self.assertGreater(len(calls), 4, result)
        self.assertEqual(result["status"], "barrier", result)
        self.assertEqual(result["reason"], "saved-delivery", result)
        package = host.project_stage1_delivery.read("alice-token", fixture["ref"])[
            "canonical_package"
        ]
        self.assertIsNotNone(package, result)
        self.assertEqual(package["status"], "saved-evidence-validated")
        self.assertEqual(result["automatic_notes_companion"]["note_count"], 2)
        self.assertFalse(result["stage2_started"])
        self.assertFalse(result["scientific_acceptance"])
        self.assertTrue(all(c["operation"] == "stage1-automatic-review" for c in calls))
        self.assertEqual(
            fixture["ledger"].events()[: len(original_events)], original_events
        )
        progress = execution.read("alice-token", fixture["ref"])
        self.assertEqual(len(progress["automatically_recorded"]), 2, result)
        self.assertEqual(len(progress["automatic_pending"]), 2, result)
        self.assertTrue(
            all(
                "source-identity-unverified" in row["reason_codes"]
                for row in progress["automatic_pending"]
            )
        )
        self.assertEqual(progress["automatic_resolved"], [])
        self.assertEqual(progress["researcher_questions"], [])
        self.assertTrue(
            all(
                row["entire_extracted_text_reviewed"]
                for row in progress["automatically_recorded"]
            )
        )
        exported = execution.export_notes(
            "alice-token", fixture["ref"], case.root / "full-note-export"
        )
        self.assertEqual(exported["note_count"], 2)
        self.assertFalse(exported["stage2_started"])
        state = case.intake._load("alice", fixture["ref"])
        for applied in state["stage1_automatic_production"]["applied"].values():
            note = Path(applied["note_path"]).read_bytes()
            self.assertEqual(sha(note), applied["note_sha256"])
            self.assertNotIn(b"NOT READ", note)
            self.assertFalse(applied["human_acceptance"])
        count = len(calls)
        replay = host.continue_stage1(
            "alice-token",
            fixture["ref"],
            run_id="synthetic-full-producer",
            deadline=time.monotonic() + 30,
            max_actions=64,
        )
        self.assertEqual(replay["status"], "barrier", replay)
        self.assertEqual(replay["reason"], "saved-delivery", replay)
        self.assertEqual(
            replay["automatic_notes_companion"], result["automatic_notes_companion"]
        )
        self.assertEqual(len(calls), count, replay)
        self.assertEqual(
            execution.read("alice-token", fixture["ref"])["model_calls_reserved"], count
        )
        evidence = os.environ.get("STAGE1_EXECUTION_EVIDENCE_DIR")
        if evidence:
            target = Path(evidence)
            target.mkdir(parents=True, exist_ok=False)
            observed = dict(
                kind="SyntheticStage1AutomaticCompositionObservation",
                evidence_scope="synthetic-only",
                result=result,
                model_calls=count,
                root_live_model_search_source_calls=0,
                package=package,
                notes_companion=exported,
                resumed=replay,
                original_events_retained=len(original_events),
                actual_semantic_model=False,
                scientific_acceptance=False,
                formal_stage2_executed=False,
            )
            (target / "composition.json").write_bytes(canonical(observed) + b"\n")
            for source in (case.root / "full-note-export").iterdir():
                (target / source.name).write_bytes(source.read_bytes())

    def test_parent_raw_bytes_memory_binding_and_seconds_fail_before_io(self):
        case, fixture, host, execution, calls = self.fixture()
        history = deepcopy(case.intake.history("alice-token", fixture["ref"]))
        with self.assertRaises(SessionApiError) as rejected:
            host.project_models.authorize(
                "alice-token", fixture["ref"], dict(operation="stage1-automatic-review")
            )
        self.assertEqual(
            rejected.exception.code, "automatic-stage1-trusted-delegation-required"
        )
        self.assertEqual(case.intake.history("alice-token", fixture["ref"]), history)
        with self.assertRaises(SessionApiError):
            execution.check_reservation(fixture["ref"], seconds=1001)
        original = execution.path.read_bytes()
        execution.path.write_bytes(original + b" ")
        try:
            with self.assertRaises(SessionApiError):
                execution.work_items(fixture["ref"])
        finally:
            execution.path.write_bytes(original)
        execution.permit["max_calls"] += 1
        try:
            with self.assertRaises(SessionApiError):
                execution.check_reservation(fixture["ref"])
        finally:
            execution.permit["max_calls"] -= 1
        self.assertEqual(calls, [])

    def test_new_query_candidate_gets_automatic_pending_without_model_or_human_choice(
        self,
    ):
        case, fixture, host, execution, calls = self.fixture()
        ledger = fixture["ledger"]
        coverage = ledger.coverage_state()
        query = ledger.start_planned(next(iter(coverage.queries)))
        backend = ledger.start(
            "backend",
            {"input": coverage.arguments(next(iter(coverage.queries)))},
            backend="openalex",
            parent_id=query,
        )
        records = ledger.save_bytes(
            canonical(
                [
                    dict(
                        title="New authored unassessed source",
                        authors=["Synthetic Author"],
                        year=2025,
                        version="v1",
                        doi="10.1234/automatic-new",
                    )
                ]
            ),
            producer=backend,
        )
        empty = ledger.save_bytes(b"", producer=backend)
        ledger.finish(
            backend,
            outcome="success_nonempty",
            http_status=200,
            exit_code=0,
            stdout=empty,
            stderr=empty,
            records=records,
        )
        ledger.complete_query(query)
        ledger.extract()
        candidate = next(
            row
            for row in ledger.candidates().values()
            if row["discoveries"][-1]["record"].get("doi") == "10.1234/automatic-new"
        )
        current = case.intake.read("alice-token", fixture["ref"])
        body = dict(
            key="automatic-new-pending",
            confirmed=True,
            work_ref=candidate["work_id"],
            ledger_state_sha256=ledger.state_hash(),
            **{k: current[k] for k in ("revision", "input_version", "brief_sha256")},
        )
        result = execution.prepare_candidate("alice-token", fixture["ref"], body)
        self.assertEqual(result["decision"], "pending")
        event = ledger.event(result["decision_event_id"])
        self.assertEqual(event["actor"], "ai:synthetic-reader")
        self.assertIsNone(event["authorization"])
        self.assertEqual(calls, [])

    def test_parent_budget_and_bad_evidence_never_clear_pending(self):
        case, fixture, host, execution, calls = self.fixture(calls=1, corrupt=True)
        result = host.continue_stage1(
            "alice-token",
            fixture["ref"],
            run_id="synthetic-invalid",
            deadline=time.monotonic() + 60,
            max_actions=8,
        )
        self.assertEqual(len(calls), 1, result)
        self.assertEqual(result["status"], "held", result)
        progress = execution.read("alice-token", fixture["ref"])
        self.assertEqual(progress["model_units_completed"], 0)
        self.assertEqual(len(progress["automatic_pending"]), 2)
        self.assertEqual(progress["researcher_questions"], [])
        with self.assertRaises(SessionApiError):
            execution.check_reservation(fixture["ref"])
        again = host.continue_stage1(
            "alice-token",
            fixture["ref"],
            run_id="different-key",
            deadline=time.monotonic() + 30,
            max_actions=8,
        )
        self.assertEqual(len(calls), 1, again)


if __name__ == "__main__":
    unittest.main()
