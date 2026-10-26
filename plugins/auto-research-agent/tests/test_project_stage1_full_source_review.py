"""Three exact Core review regressions; authored sources and local SQLite only."""

from contextlib import contextmanager
from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import test_project_stage1_full_source_adapter as adapter_fixture
import test_project_agent_coverage as coverage_fixture
from research_workspace_native.project_stage1_full_source import (
    ProjectStage1FullSourceAdapter,
)
from research_workspace_native.project_stage1_run_grant import (
    ProjectStage1RunGrantService,
)
from research_workspace_native.session_api import SessionApiError
from stage1_deliverable.common import DeliverableError, canonical, sha


class FullSourceReviewTests(unittest.TestCase):
    factory = adapter_fixture.FullSourceAdapterTests.factory
    setUp = adapter_fixture.FullSourceAdapterTests.setUp
    case = adapter_fixture.FullSourceAdapterTests.case

    @contextmanager
    def isolated_case(self, **options):
        with TemporaryDirectory(prefix="full-source-review-") as directory:
            with patch.object(self, "root", Path(directory).resolve()):
                with self.case(**options) as run:
                    yield run

    @contextmanager
    def undecided_source_case(self, *, calls):
        with self.isolated_case(calls=calls) as run:
            ledger = run.saved["ledger"]
            prior = ledger.coverage_state().evidence.decisions
            for work, decision in prior.items():
                ledger.decide(
                    work,
                    "exclude",
                    reason="authored-budget-isolation",
                    rationale="Exclude the old fixture works to isolate two new discoveries.",
                    evidence_refs=decision["evidence_refs"],
                )
            before = set(ledger.candidates())
            plan = ledger.coverage_state()
            planned = list(plan.queries)[2]
            query = ledger.start_planned(planned)
            backend = ledger.start(
                "backend",
                {"input": plan.arguments(planned)},
                backend="openalex",
                parent_id=query,
            )
            titles = [f"New undecided authored source {i}" for i in range(2)]
            metadata = ledger.save_bytes(
                canonical(
                    [
                        dict(
                            title=title,
                            authors=["Synthetic Author"],
                            year=2025,
                            version="v1",
                        )
                        for title in titles
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
                records=metadata,
            )
            ledger.complete_query(query)
            ledger.extract()
            works = sorted(set(ledger.candidates()) - before)
            self.assertEqual(len(works), 2)
            for index, work in enumerate(works):
                candidate = ledger.candidates()[work]
                version = candidate["discoveries"][-1]["version_id"]
                # Bind the SDK's actual authored HTML to this candidate's title.
                title = candidate["discoveries"][-1]["record"]["title"]
                source = ledger.start_source(
                    work_id=work,
                    version_id=version,
                    source_uri="https://example.org/study",
                    tool="research_hub.source_fetch",
                    request={"public_only": True},
                    actor="fixture",
                    reason="Authored undecided source fixture; no external I/O.",
                )
                run.case.inputs = run.case.fixture_root / f"undecided-{index}"
                run.case.inputs.mkdir()
                fixture = adapter_fixture.source_fixture
                records = fixture.ResearchDeliverableTests.make_records(
                    run.case,
                    raw=fixture.HTML.replace(fixture.TITLE.encode(), title.encode()),
                    title=title,
                )
                path = run.case.inputs / records["sources"][0]["result_path"]
                receipt = json.loads(path.read_bytes())
                raw = ledger.save_bytes(
                    Path(receipt["raw_path"]).read_bytes(), producer=source
                )
                text = ledger.save_bytes(
                    Path(receipt["extracted_text_path"]).read_bytes(), producer=source
                )
                ledger.finish_source(
                    attempt_id=source,
                    outcome="available",
                    observed_at=receipt["retrieved_at"].replace("+00:00", "Z"),
                    http_status=200,
                    resolved_uri=receipt["final_url"],
                    raw_ref=raw,
                    text_ref=text,
                    extraction={"method": "research_hub", "version": "fixture"},
                    reason="Real parser and physical bytes; no scientific acceptance.",
                )
                run.case.producer.register_source(
                    run.ref,
                    source_id=source,
                    result_path=path,
                    expected_result_sha256=sha(path.read_bytes()),
                    access_note=records["sources"][0]["access_note"],
                    expected_ledger_state_sha256=ledger.state_hash(),
                )
            self.assertTrue(
                all(
                    work not in ledger.coverage_state().evidence.decisions
                    for work in works
                )
            )
            yield run, works

    def test_undecided_budget_stops_before_authorization_and_funded_run_enters(self):
        for calls in (1, 2):
            with (
                self.subTest(calls=calls),
                self.undecided_source_case(calls=calls) as (
                    run,
                    works,
                ),
            ):
                before = run.case.intake.history("alice-token", run.ref)
                preflight = run.adapter.preflight("alice-token", run.ref)
                result = run.host.continue_stage1(
                    "alice-token",
                    run.ref,
                    run_id="undecided-call-budget",
                    deadline=time.monotonic() + 120,
                    max_actions=2,
                )
                rows = run.case.intake.db.execute(
                    "SELECT receipt FROM intake_actions WHERE principal=? AND project=?",
                    ("alice", run.ref),
                ).fetchall()
                permissions = [
                    r
                    for row in rows
                    if (r := json.loads(row[0]))["kind"] == "model-authorization"
                ]
                facts = dict(
                    calls=calls,
                    lower_bound=preflight["required_call_lower_bound"],
                    status=result["status"],
                    reason=result.get("reason"),
                    action_count=result["action_count"],
                    model_authorizations=len(permissions),
                    jobs=run.model.read("alice-token", run.ref)["job_count"],
                )
                if calls == 1:
                    self.assertEqual(
                        facts,
                        dict(
                            calls=1,
                            lower_bound=2,
                            status="partial",
                            reason="remaining-model-call-budget-insufficient",
                            action_count=0,
                            model_authorizations=0,
                            jobs=0,
                        ),
                    )
                    self.assertEqual(
                        before, run.case.intake.history("alice-token", run.ref)
                    )
                else:
                    self.assertEqual(preflight["required_call_lower_bound"], 2, facts)
                    self.assertEqual(len(permissions), 1, facts)
                    self.assertFalse(permissions[0]["request"]["confirmed"])
                    decisions = run.saved["ledger"].coverage_state().evidence.decisions
                    self.assertTrue(
                        all(
                            decisions[work]["new_decision"] == "pending"
                            for work in works
                        ),
                        facts,
                    )
                    self.assertEqual(facts["action_count"], 2, facts)
                self.assertEqual(self.assertions, [])
                self.assertEqual(facts["jobs"], 0)
                self.assertEqual(preflight["remaining_model_calls"], calls)
                self.assertFalse(result["stage2_started"])

    def test_publication_rechecks_new_root_and_ancestor_git_directory_or_gitfile(self):
        for ancestor in (False, True):
            for gitfile in (False, True):
                with (
                    self.subTest(ancestor=ancestor, gitfile=gitfile),
                    self.isolated_case() as run,
                ):
                    marker = (run.output.parent if ancestor else run.output) / ".git"
                    if gitfile:
                        marker.write_text("gitdir: authored-missing-metadata\n")
                    else:
                        marker.mkdir()
                    with (
                        patch.object(run.adapter, "read", return_value={"notes": [{}]}),
                        patch.object(
                            run.adapter,
                            "_saved",
                            return_value=(None,) * 5
                            + ([({}, {"authored": "source-bearing note"})],),
                        ),
                        self.assertRaises(DeliverableError),
                    ):
                        run.adapter._save_projection(
                            "alice-token", run.ref, {"status": "partial"}
                        )
                    self.assertEqual(list(run.output.glob("*.md")), [])
                    self.assertEqual(list(run.output.glob("*.json")), [])
                    self.assertEqual(self.assertions, [])

    def test_include_coverage_registration_and_notes_bind_current_reading(self):
        # Reuse the real saved analysis1.1/adoption/coverage/registration services.
        # This slice uses its authored provider, not native I/O or the AutoDriver.
        captured = {}
        original = ProjectStage1RunGrantService.authorize

        def authorize(issuer, credential, ref, body):
            body = deepcopy(body)
            body["operations"].append("analyze-full-paper")
            grant = original(issuer, credential, ref, body)
            captured.update(issuer=issuer, grant=grant)
            return grant

        with (
            patch.object(ProjectStage1RunGrantService, "authorize", new=authorize),
            coverage_fixture.agent_coverage_run() as run,
        ):
            issuer, grant = captured["issuer"], captured["grant"]
            run.model.run_grants = issuer
            output = self.root / "include-notes"
            output.mkdir()
            adapter = ProjectStage1FullSourceAdapter(
                SimpleNamespace(
                    projects=run.case.intake,
                    project_stage1=run.case.delivery.stage1,
                    project_models=run.model,
                    project_stage1_records=run.case.producer,
                    project_stage1_sources=None,
                ),
                "alice-token",
                run.ref,
                run_grants=issuer,
                grant_ref=grant["grant_ref"],
                grant_sha256=grant["grant_sha256"],
                output_root=output,
            )
            helper = coverage_fixture.AgentCoverageTests("runTest")
            adoption_body, adoption = helper._adopt(run)
            self.assertFalse(
                adapter.read("alice-token", run.ref)["automatically_recorded"][0][
                    "reading_registration_complete"
                ]
            )
            coverage_body, _, coverage = helper._review(run, adoption_body, adoption)
            self.assertFalse(
                adapter.read("alice-token", run.ref)["automatically_recorded"][0][
                    "reading_registration_complete"
                ]
            )
            body, token = run.derived(
                "stage1-agent-reading",
                "records",
                dict(
                    adoption_key=coverage_body["key"],
                    adoption_request_sha256=coverage["request_sha256"],
                    reading_sha256=coverage["reading_sha256"],
                ),
            )
            registered = run.coverage.register(
                "alice-token", run.ref, body, run_authorization=token
            )
            self.assertEqual(
                registered["registry_entry"]["payload"], coverage["reading"]
            )
            self.assertNotEqual(adoption["reading_sha256"], coverage["reading_sha256"])
            before = run.case.intake.history("alice-token", run.ref)
            progress = adapter.read("alice-token", run.ref)
            row = progress["automatically_recorded"][0]
            self.assertTrue(row["reading_registration_complete"], progress)
            self.assertEqual(row["review_event_id"], coverage["event_id"])
            self.assertFalse(row["human_acceptance"])
            self.assertFalse(row["scientific_acceptance"])
            note = adapter.note_by_hash(
                "alice-token", run.ref, progress["notes"][0]["sha256"]
            )
            self.assertEqual(sha(note["text"].encode()), note["sha256"])
            self.assertIn('"decision": "include"', note["text"])
            companion = adapter._save_projection(
                "alice-token", run.ref, {"status": "partial"}
            )
            self.assertEqual(
                json.loads(Path(companion["path"]).read_bytes())["progress"], progress
            )
            self.assertEqual(before, run.case.intake.history("alice-token", run.ref))
            self.assertEqual(len(run.calls), 1)

            saved, unresolved = adapter.queue._actions(
                "alice", run.ref, run.case.intake.binding(run.ref)
            )
            for field in ("model_job_sha256", "reading_sha256"):
                changed = deepcopy(saved)
                receipt = next(
                    r for r in changed if r["kind"] == "stage1-agent-coverage"
                )
                receipt[field] = "0" * 64
                with (
                    self.subTest(field=field),
                    patch.object(
                        adapter.queue, "_actions", return_value=(changed, unresolved)
                    ),
                    self.assertRaises(SessionApiError),
                ):
                    adapter.read("alice-token", run.ref)
            changed = deepcopy(saved)
            receipt = next(r for r in changed if r["kind"] == "stage1-agent-coverage")
            receipt["request"]["adoption_key"] = "another-adoption"
            receipt["request_sha256"] = sha(
                canonical(dict(kind=receipt["kind"], body=receipt["request"]))
            )
            with patch.object(
                adapter.queue, "_actions", return_value=(changed, unresolved)
            ):
                self.assertFalse(
                    adapter.read("alice-token", run.ref)["automatically_recorded"][0][
                        "reading_registration_complete"
                    ]
                )
            self.assertEqual(before, run.case.intake.history("alice-token", run.ref))
            self.assertEqual(len(run.calls), 1)

    def test_excluded_candidates_do_not_exhaust_calls_and_shortfall_still_stops(self):
        for calls in (2, 1):
            with self.subTest(calls=calls), self.isolated_case(calls=calls) as run:
                ledger = run.saved["ledger"]
                original = set(ledger.candidates())
                plan = ledger.coverage_state()
                planned = list(plan.queries)[2]
                query = ledger.start_planned(planned)
                backend = ledger.start(
                    "backend",
                    {"input": plan.arguments(planned)},
                    backend="openalex",
                    parent_id=query,
                )
                records = ledger.save_bytes(
                    canonical(
                        [
                            dict(
                                title=f"Excluded authored fixture {i:02d}",
                                authors=["Synthetic Author"],
                                year=2025,
                                version="v1",
                            )
                            for i in range(40)
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
                for work in set(ledger.candidates()) - original:
                    ledger.decide(
                        work,
                        "exclude",
                        reason="authored-excluded",
                        rationale="Authored exclusion only; no scientific judgment.",
                        evidence_refs=[records],
                    )
                self.assertEqual(len(ledger.candidates()), 42)
                before = run.case.intake.history("alice-token", run.ref)
                check = run.adapter.preflight("alice-token", run.ref)
                self.assertEqual(check["required_call_lower_bound"], 2, check)
                self.assertEqual(check["remaining_model_calls"], calls)
                self.assertEqual(check["feasible_by_call_lower_bound"], calls == 2)
                with patch(
                    "research_workspace_native.project_stage1_auto.ProjectStage1AutoDriver.run",
                    return_value={"status": "authored-driver-boundary"},
                ) as driver:
                    result = run.host.continue_stage1(
                        "alice-token",
                        run.ref,
                        run_id="excluded-budget",
                        deadline=time.monotonic() + 60,
                        max_actions=8,
                    )
                if calls == 2:
                    driver.assert_called_once()
                    self.assertEqual(result["status"], "authored-driver-boundary")
                else:
                    driver.assert_not_called()
                    self.assertEqual(result["status"], "partial")
                    self.assertEqual(
                        result["reason"], "remaining-model-call-budget-insufficient"
                    )
                    self.assertEqual(result["action_count"], 0)
                self.assertEqual(
                    before, run.case.intake.history("alice-token", run.ref)
                )
                self.assertEqual(self.assertions, [])
                self.assertEqual(run.model.read("alice-token", run.ref)["job_count"], 0)
