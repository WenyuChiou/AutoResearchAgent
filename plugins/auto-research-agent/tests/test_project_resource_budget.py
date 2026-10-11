"""Actual intake/query/model causality; all SDK, network and providers are fixtures."""

import atlas_test_paths  # noqa: F401
from copy import deepcopy
from contextlib import ExitStack
from datetime import datetime, timezone
from pathlib import Path
import time
import unittest
from unittest.mock import patch

import project_stage1_query_cases as query_fixture
from research_workspace_native.project_intake import ProjectIntakeService
from research_workspace_native.project_model import ProjectModelService, budget_digest
from research_workspace_native.project_resource_budget import (
    EVENT,
    STORE,
    reserve_resource,
    resource_view,
)
from research_workspace_native.session_api import SessionApiError
from stage1_deliverable.common import canonical, sha
from test_workspace_project_intake import bound_body, compile_body, submit_body


class LocalProvider:
    def __init__(self, case, context, admit):
        self.case, self.context, self.admit = case, context, admit

    def run(self, key, prompt, deadline):
        event = dict(
            unit_key=key,
            prompt_sha256=sha(prompt.encode()),
            source_sha256=self.context["source_sha256"],
            permit_sha256=self.context["permit_sha256"],
        )
        self.admit(dict(event, phase="reserve"))
        self.admit(dict(event, phase="spawn"))
        self.case.model_writes += 1
        return dict(
            status="completed",
            prompt_sha256=event["prompt_sha256"],
            source_sha256=event["source_sha256"],
            final_text="Synthetic local prose, not researched evidence.",
            usage=None,
            cost=None,
            synthetic=True,
        )

    def verify_receipt(self, receipt, **expected):
        return receipt


class ProjectResourceBudgetTests(unittest.TestCase):
    def setUp(self):
        self.case = query_fixture.ProjectQueryCases()
        self.addCleanup(self.case.doCleanups)
        self.case.setUp()
        self.intake = self.case.intake
        self.token, self.principal = "alice-token", "alice"
        self.ref = self.intake.create(
            self.token,
            dict(key="resource-project", topic="Synthetic local resource accounting"),
        )["project_ref"]
        self.case.ref = self.ref
        body = submit_body(self.intake.read(self.token, self.ref))
        body["budgets"].update(
            seconds=180, model_calls=3, search_calls=2, source_reads=3, rounds=1
        )
        body["consent"].update(external_search=True, public_source_read=True)
        self.intake.submit(self.token, self.ref, body)
        self.intake.compile(
            self.token, self.ref, compile_body(self.intake.read(self.token, self.ref))
        )
        self.model_writes, self.factory_calls = 0, 0
        self.before_provider = None
        self.model = ProjectModelService(self.intake, provider_factory=self.factory)
        self.addCleanup(self.model.close)

    def factory(self, *, context, admit, output_root):
        self.assertFalse(self.intake.db.in_transaction)
        self.factory_calls += 1
        if self.before_provider is not None:
            self.before_provider()
        return LocalProvider(self, context, admit)

    def view(self, intake=None):
        intake = self.intake if intake is None else intake
        return resource_view(
            intake, intake._load(self.principal, self.ref), self.principal
        )

    def source(self, key, seconds, *, fail=False, lose_response=False):
        body = bound_body(self.intake.read(self.token, self.ref), key)
        finished = False

        def reserve(state, digest, principal):
            reserve_resource(
                self.intake,
                state,
                principal,
                lane="source",
                kind="stage1-source-execute",
                key=key,
                request_sha256=digest,
                seconds=seconds,
            )

        def work(state, digest, principal):
            nonlocal finished
            if fail:
                raise ValueError("Authored queued job failure; no source operation.")
            finished = True
            return dict(source_status="fixture-queued", source_executed=False)

        def check():
            if finished and lose_response:
                raise TimeoutError("Authored post-work response loss")

        return self.intake._perform(
            self.principal,
            self.ref,
            "stage1-source-execute",
            body,
            work,
            reserve=reserve,
            check_deadline=check,
        )

    def register_model(self, seconds=20):
        binding = self.intake.brief_binding(self.ref)
        permit = dict(
            kind="ProjectModelOperationPermit",
            schema_version="1.0.0",
            permission_id="synthetic-shared-resource-permit",
            principal=self.principal,
            project_id=binding["project_id"],
            input_version=binding["input_version"],
            brief_sha256=binding["brief_sha256"],
            budget_sha256=budget_digest(binding),
            operation="suggest-topic",
            model="synthetic-only",
            max_calls=3,
            max_seconds=seconds,
            expires_at=datetime.fromtimestamp(
                time.time() + 600, timezone.utc
            ).isoformat(),
            allow_model_calls=True,
            execution_scope="project-content-planning-only",
            external_search=False,
            frozen_subjects=False,
        )
        raw = canonical(permit) + b"\n"
        path = self.case.root / ("resource-permit-" + str(seconds) + ".json")
        path.write_bytes(raw)
        return self.model.register(
            self.ref,
            operation="suggest-topic",
            permit_path=path,
            permit_sha256=sha(raw),
        )

    def model_body(self, offer, key="model-one"):
        return dict(
            bound_body(self.intake.read(self.token, self.ref), key),
            offer_ref=offer["offer_ref"],
            offer_sha256=offer["offer_sha256"],
            confirmed=True,
        )

    def model_finish(self):
        self.model._workers[(self.ref, "model-one")].join(10)
        self.assertFalse(self.model._workers[(self.ref, "model-one")].is_alive())
        return self.model.history(self.token, self.ref)["actions"][-1]

    def raw_change(self, change):
        with self.intake._lock, self.intake.db:
            state = self.intake._load(self.principal, self.ref)
            change(state)
            self.intake._save(state, "authored-adversarial-resource-drift", {})

    def test_first_model_query_and_source_share_one_declared_envelope(self):
        self.source("source-one", 25.25)
        offer = self.register_model(20)
        self.model.execute(self.token, self.ref, self.model_body(offer))
        job = self.model_finish()
        self.assertEqual(job["status"], "content-review-pending", job)
        self.assertEqual(self.model_writes, 1)
        self.case.authorize()
        self.case.bootstrap()
        with self.case.fake_runner(), self.case.no_probe():
            result = self.case.queries.execute(
                self.token, self.ref, self.case.body("query_offer", "query-one")
            )
            service = self.case.queries.services[self.ref]
            service._workers[self.ref].join(30)
        self.assertEqual(
            service.get_action(self.token, self.ref, result["query_action_key"])[
                "status"
            ],
            "completed",
        )
        view = self.view()
        self.assertEqual(view["reserved"]["search_calls"], 1)
        self.assertEqual(view["reserved"]["source_reads"], 1)
        self.assertEqual(view["reserved"]["model_calls"], 1)
        self.assertAlmostEqual(
            view["reserved"]["seconds"], 25.25 + job["reservation_seconds"] + 30 + 32
        )
        self.assertIsNone(view["actual_seconds"])
        self.assertIsNone(job["usage"])
        self.assertFalse(view["automatic_refund"])

    def test_source_then_model_and_query_refuse_before_provider_or_probe(self):
        self.source("source-nearly-full", 170)
        offer = self.register_model(20)
        with self.assertRaises(SessionApiError) as error:
            self.model.execute(self.token, self.ref, self.model_body(offer))
        self.assertEqual(error.exception.code, "project-resource-budget-exhausted")
        self.assertEqual(self.factory_calls, 0)
        self.case.authorize()
        with self.case.no_probe(), self.assertRaises(SessionApiError) as error:
            self.case.queries.bootstrap(
                self.token, self.ref, self.case.body("bootstrap_offer", "bootstrap")
            )
        self.assertEqual(error.exception.code, "project-resource-budget-exhausted")
        self.assertEqual(self.view()["reserved"]["seconds"], 170)

    def test_model_then_source_refuses_and_same_key_does_not_reserve_twice(self):
        offer = self.register_model(120)
        body = self.model_body(offer)
        first = self.model.execute(self.token, self.ref, body)
        self.model_finish()
        before = self.view()
        replay = self.model.execute(self.token, self.ref, body)
        self.assertTrue(replay["replayed"])
        self.assertEqual(replay["request_sha256"], first["request_sha256"])
        self.assertEqual(self.view(), before)
        self.assertEqual(self.model_writes, 1)
        with self.assertRaises(SessionApiError) as error:
            self.source("source-too-long", 70)
        self.assertEqual(error.exception.code, "project-resource-budget-exhausted")

    def test_failed_and_unknown_reservations_survive_true_sqlite_reopen(self):
        for key, flags in (
            ("source-failed", dict(fail=True)),
            ("source-unknown", dict(lose_response=True)),
        ):
            with self.assertRaises(SessionApiError) as error:
                self.source(key, 35.25, **flags)
            self.assertEqual(
                error.exception.receipt["status"],
                "failed" if flags.get("fail") else "execution-unknown",
            )
        before = self.view()
        self.assertEqual(before["reserved"]["seconds"], 70.5)
        root, authenticate = self.intake.root, self.intake.authenticate
        self.model.close()
        self.case.queries.close()
        self.intake.close()
        reopened = ProjectIntakeService(root, authenticate=authenticate)
        self.addCleanup(reopened.close)
        snapshot = tuple(reopened.db.iterdump())
        self.assertEqual(self.view(reopened), before)
        self.assertEqual(tuple(reopened.db.iterdump()), snapshot)

    def test_bare_counters_and_orphan_shared_rows_refuse_without_repair(self):
        original = self.intake._load(self.principal, self.ref)
        for change, code in (
            (
                lambda s: s.update(stage1_source_budget=dict(fetches=1, seconds=30)),
                "project-resource-source-history-differs",
            ),
            (
                lambda s: s.update(
                    stage1_query_budget=dict(probes=1, attempts=0, seconds=30)
                ),
                "project-resource-query-history-differs",
            ),
            (
                lambda s: s.update(model_operations=dict(calls_reserved=1)),
                "project-resource-model-history-differs",
            ),
            (
                lambda s: s.update(
                    **{STORE: dict(schema_version="1.0.0", reservations={"a" * 64: {}})}
                ),
                "project-resource-intent-missing",
            ),
        ):
            self.raw_change(change)
            snapshot = tuple(self.intake.db.iterdump())
            with self.assertRaises(SessionApiError) as error:
                self.view()
            self.assertEqual(error.exception.code, code)
            self.assertEqual(tuple(self.intake.db.iterdump()), snapshot)
            with self.intake.db:
                self.intake._save(
                    deepcopy(original), "authored-reset-adversarial-fixture", {}
                )

    def test_resource_change_in_query_admission_rejects_before_backend(self):
        self.case.authorize()
        self.case.bootstrap()
        registration = next(
            iter(
                self.intake._load(self.principal, self.ref)[
                    "stage1_query_jobs"
                ].values()
            )
        )["registration"]
        journal = Path(registration["ledger_root"]) / "stage_events.jsonl"
        original_events = journal.read_bytes()
        changed = False

        def admit(event):
            nonlocal changed
            if not changed:
                changed = True
                self.raw_change(
                    lambda s: s.update(stage1_source_budget=dict(fetches=1, seconds=10))
                )
            return True

        self.case.queries.admit = admit
        with self.case.fake_runner() as runner, self.case.no_probe():
            result = self.case.queries.execute(
                self.token, self.ref, self.case.body("query_offer", "query-drift")
            )
            service = self.case.queries.services[self.ref]
            service._workers[self.ref].join(30)
            self.assertTrue(changed)
            self.assertEqual(len(self.case.children), 0)
            if hasattr(runner, "assert_not_called"):
                runner.assert_not_called()
        observation = service.get_action(
            self.token, self.ref, result["query_action_key"]
        )
        self.assertEqual(observation["status"], "completed", observation)
        self.assertEqual(observation["outcome"], "refused-known-unsent", observation)
        self.assertEqual(
            observation["error"]["code"], "project-resource-source-history-differs"
        )
        self.assertNotIn("result", observation)
        self.assertEqual(journal.read_bytes(), original_events)

    def test_resource_change_before_model_admission_rejects_zero_model_writes(self):
        offer = self.register_model(20)
        self.before_provider = lambda: self.raw_change(
            lambda s: s.update(stage1_source_budget=dict(fetches=1, seconds=10))
        )
        self.model.execute(self.token, self.ref, self.model_body(offer))
        job = self.model_finish()
        self.assertEqual(job["status"], "failed-or-unknown", job)
        self.assertEqual(self.model_writes, 0)

    def test_legacy_model_and_query_causality_is_read_without_migration(self):
        offer = self.register_model(20)
        # Reproduce the old producer shape: genuine local jobs/intents/counters,
        # with no new shared reservation event. Never delete immutable history.
        with (
            patch("research_workspace_native.project_model.reserve_resource"),
            patch("research_workspace_native.project_stage1_queries.reserve_resource"),
        ):
            self.model.execute(self.token, self.ref, self.model_body(offer))
            self.model_finish()
            self.case.authorize()
            self.case.bootstrap()
        snapshot = tuple(self.intake.db.iterdump())
        view = self.view()
        self.assertEqual(view["reserved"]["model_calls"], 1)
        self.assertEqual(view["reserved"]["seconds"], 50)
        self.assertNotIn(STORE, self.intake._load(self.principal, self.ref))
        self.assertEqual(tuple(self.intake.db.iterdump()), snapshot)

    def test_legacy_causal_overreservation_refuses_without_rewriting_history(self):
        offer = self.register_model(120)
        with patch("research_workspace_native.project_model.reserve_resource"):
            self.model.execute(self.token, self.ref, self.model_body(offer))
            self.model_finish()
        body = self.model_body(offer, "legacy-second")

        def old_reserve(state, digest, principal):
            # Reproduce only the old local reservation shape, not a provider call.
            row = state["model_operations"]
            first = row["jobs"]["model-one"]
            second = deepcopy(first)
            second.update(
                key="legacy-second", request_sha256=digest, status="execution-unknown"
            )
            row["jobs"]["legacy-second"] = second
            row["calls_reserved"] += 1
            scope = row["scopes"][str(state["input_version"])]
            scope["calls"] += 1
            scope["permits"][first["permit_sha256"]]["calls"] += 1

        self.intake._perform(
            self.principal,
            self.ref,
            "model-operation",
            body,
            lambda *_: dict(model_status="execution-unknown"),
            reserve=old_reserve,
        )
        snapshot = tuple(self.intake.db.iterdump())
        with self.assertRaises(SessionApiError) as error:
            self.view()
        self.assertEqual(
            error.exception.code, "project-resource-declared-budget-exceeded"
        )
        self.assertEqual(tuple(self.intake.db.iterdump()), snapshot)
        self.assertEqual(self.model_writes, 1)

    def test_current_resource_drift_cannot_reset_and_new_input_keeps_old_history(self):
        self.source("old-source", 50)
        offer = self.register_model(20)
        self.model.execute(self.token, self.ref, self.model_body(offer))
        self.model_finish()
        self.case.authorize()
        self.case.bootstrap()
        with self.case.fake_runner(), self.case.no_probe():
            self.case.queries.execute(
                self.token, self.ref, self.case.body("query_offer", "old-query")
            )
            self.case.queries.services[self.ref]._workers[self.ref].join(30)
        before = self.intake._load(self.principal, self.ref)
        self.raw_change(lambda s: s["settings"]["budgets"].update(seconds=1800))
        with self.assertRaises(SessionApiError) as error:
            self.view()
        self.assertEqual(error.exception.code, "project-resource-version-differs")
        with self.intake.db:
            self.intake._save(before, "authored-restore-resource-version", {})
        body = dict(
            bound_body(self.intake.read(self.token, self.ref), "new-input"),
            topic="Second independently confirmed fixture topic",
        )
        self.intake.revise(self.token, self.ref, body)
        confirm = submit_body(self.intake.read(self.token, self.ref))
        confirm["key"] = "confirm-v2"
        confirm["budgets"].update(seconds=100, source_reads=1)
        confirm["consent"]["public_source_read"] = True
        self.intake.submit(self.token, self.ref, confirm)
        current = self.view()
        self.assertEqual(current["reserved"]["seconds"], 0)
        self.assertEqual(current["remaining"]["seconds"], 100)
        self.assertEqual(
            len(self.intake._load(self.principal, self.ref)[STORE]["reservations"]), 4
        )
        self.source("new-source", 25)
        self.assertEqual(self.view()["reserved"]["seconds"], 25)
        self.assertEqual(
            self.intake._load(self.principal, self.ref)["stage1_source_budget"],
            dict(fetches=2, seconds=75),
        )
        current = self.intake._load(self.principal, self.ref)
        self.assertEqual(current["stage1_query_budget"], before["stage1_query_budget"])
        self.assertEqual(current["model_operations"], before["model_operations"])

    def test_source_row_and_counter_tamper_cannot_reduce_immutable_reservation(self):
        first = self.source("source-original", 70)

        def change(state):
            state[STORE]["reservations"][first["request_sha256"]]["seconds"] = 7
            state["stage1_source_budget"]["seconds"] = 7

        self.raw_change(change)
        snapshot = tuple(self.intake.db.iterdump())
        with self.assertRaises(SessionApiError) as error:
            self.view()
        self.assertEqual(
            error.exception.code, "project-resource-reservation-event-differs"
        )
        self.assertEqual(tuple(self.intake.db.iterdump()), snapshot)

    def test_immutable_reservation_cannot_be_removed_from_mutable_state(self):
        self.source("source-original", 35.25)
        self.raw_change(lambda state: state.pop(STORE))
        with self.assertRaises(SessionApiError) as error:
            self.view()
        self.assertEqual(
            error.exception.code, "project-resource-reservation-event-differs"
        )

    def test_late_reservation_event_cannot_reinterpret_legacy_model_history(self):
        offer = self.register_model(20)
        with patch("research_workspace_native.project_model.reserve_resource"):
            first = self.model.execute(self.token, self.ref, self.model_body(offer))
            self.model_finish()
        basis = self.view()["binding"]
        state = self.intake._load(self.principal, self.ref)
        job = state["model_operations"]["jobs"]["model-one"]
        row = dict(
            basis,
            lane="model",
            kind="model-operation",
            key="model-one",
            request_sha256=first["request_sha256"],
            seconds=job["reservation_seconds"],
            calls=1,
        )
        self.raw_change(
            lambda value: value.update(
                **{
                    STORE: dict(
                        schema_version="1.0.0",
                        reservations={first["request_sha256"]: row},
                    )
                }
            )
        )
        with self.intake.db:
            self.intake.db.execute(
                "INSERT INTO intake_events(project,kind,payload) VALUES(?,?,?)",
                (self.ref, EVENT, canonical(row).decode()),
            )
        with self.assertRaises(SessionApiError) as error:
            self.view()
        self.assertEqual(
            error.exception.code, "project-resource-reservation-transaction-differs"
        )

    def test_changed_model_offer_and_job_cannot_rebind_immutable_request(self):
        offer = self.register_model(20)
        self.model.execute(self.token, self.ref, self.model_body(offer))
        self.model_finish()

        def change(state):
            row = state["model_operations"]
            job = row["jobs"]["model-one"]
            saved_offer = row["offers"][job["offer_ref"]]
            saved_offer["context"]["max_seconds"] = 2
            saved_offer["offer_sha256"] = sha(canonical(saved_offer["context"]))
            job["offer_sha256"] = saved_offer["offer_sha256"]

        self.raw_change(change)
        with self.assertRaises(SessionApiError) as error:
            self.view()
        self.assertEqual(error.exception.code, "project-resource-model-job-differs")

    def test_legacy_query_cannot_reduce_original_immutable_permit_bytes(self):
        with patch("research_workspace_native.project_stage1_queries.reserve_resource"):
            self.case.authorize()
            self.case.bootstrap()
        state = self.intake._load(self.principal, self.ref)
        authorization = state["stage1_query_authorization"]
        permit = deepcopy(authorization["permit"])
        permit["limits"]["timeout_seconds"] = 1
        raw = canonical(permit) + b"\n"
        self.intake._path(self.ref, authorization["path"]).write_bytes(raw)
        self.raw_change(
            lambda s: s["stage1_query_authorization"].update(
                permit=permit, sha256=sha(raw)
            )
        )
        with self.assertRaises(SessionApiError) as error:
            self.view()
        self.assertEqual(error.exception.code, "project-resource-query-permit-differs")

    def test_final_inner_source_callback_cannot_bypass_resources_or_hold_service_lock(
        self,
    ):
        self.case.authorize()
        self.case.bootstrap()
        service = self.case.queries.services[self.ref]
        registration = next(
            iter(
                self.intake._load(self.principal, self.ref)[
                    "stage1_query_jobs"
                ].values()
            )
        )["registration"]
        journal = Path(registration["ledger_root"]) / "stage_events.jsonl"
        original_events = journal.read_bytes()
        calls, checks = [], []
        original_check = service._check_resources

        def verifier(event):
            if event["phase"] == "before-runner":
                calls.append(event)
                if len(calls) == 2:
                    self.raw_change(
                        lambda s: s.update(
                            stage1_source_budget=dict(fetches=1, seconds=10)
                        )
                    )
            return query_fixture.get_source_proof()

        def checker(event):
            checks.append(event)
            self.assertFalse(service._lock._is_owned())
            return original_check(event)

        service._verify_source, service._check_resources = verifier, checker
        with self.case.fake_runner(), self.case.no_probe():
            result = self.case.queries.execute(
                self.token, self.ref, self.case.body("query_offer", "last-source-drift")
            )
            service._workers[self.ref].join(30)
        observation = service.get_action(
            self.token, self.ref, result["query_action_key"]
        )
        self.assertEqual(len(calls), 2)
        self.assertEqual(len(checks), 1)
        self.assertEqual(observation["outcome"], "refused-known-unsent", observation)
        self.assertEqual(
            observation["error"]["code"], "project-resource-source-history-differs"
        )
        self.assertEqual(journal.read_bytes(), original_events)
        self.assertEqual(len(self.case.children), 0)

    def final_checker_refusal(self, mode, code):
        self.case.authorize()
        self.case.bootstrap()
        service = self.case.queries.services[self.ref]
        project = service._projects[self.ref]
        journal = Path(project["item"]["ledger_root"]) / "stage_events.jsonl"
        original_events = journal.read_bytes()
        original_check = service._check_resources
        real_monotonic, real_wall = time.monotonic, time.time
        activated, checks, thread_errors, observations = False, [], [], []
        original_edit = service.store._edit

        def observed_edit(project_id, owner, revision, kind, payload, **options):
            if kind == "query-worker-observation":
                observations.append(deepcopy(payload))
            return original_edit(project_id, owner, revision, kind, payload, **options)

        def checker(event):
            nonlocal activated
            self.assertFalse(service._lock._is_owned())
            self.assertIs(original_check(event), True)
            checks.append(event)
            if mode == "closing":
                with service._lock:
                    service._closing = True
            elif mode == "owner":
                # Genuine local owner release, not a patched snapshot. The
                # previous owner cannot save an observation after this point.
                service.store.release_owner(project["pid"], project["owner"])
            activated = True
            return True

        service._check_resources = checker
        body = self.case.body("query_offer", "checker-" + mode)
        with ExitStack() as stack:
            stack.enter_context(self.case.fake_runner())
            stack.enter_context(self.case.no_probe())
            stack.enter_context(
                patch.object(service.store, "_edit", side_effect=observed_edit)
            )
            stack.enter_context(
                patch("threading.excepthook", side_effect=thread_errors.append)
            )
            if mode == "deadline":
                stack.enter_context(
                    patch(
                        "research_workspace_native.planned_queries.time.monotonic",
                        side_effect=lambda: (
                            real_monotonic() + (1000 if activated else 0)
                        ),
                    )
                )
            elif mode == "expiry":
                stack.enter_context(
                    patch(
                        "research_workspace_native.planned_queries.time.time",
                        side_effect=lambda: (
                            project["permit"]["expires_at_unix"] + 1
                            if activated
                            else real_wall()
                        ),
                    )
                )
            result = self.case.queries.execute(self.token, self.ref, body)
            service._workers[self.ref].join(30)
            self.assertFalse(service._workers[self.ref].is_alive())
        self.assertEqual(len(checks), 1)
        self.assertEqual(len(self.case.children), 0)
        self.assertEqual(journal.read_bytes(), original_events)
        if mode == "owner":
            self.assertEqual(len(thread_errors), 1)
            self.assertEqual(type(thread_errors[0].exc_value).__name__, "JournalError")
            self.assertIn("exclusive owner required", str(thread_errors[0].exc_value))
            self.assertEqual(len(observations), 1)
            self.assertEqual(observations[0]["error"]["code"], code)
            self.assertEqual(observations[0]["outcome"], "refused-known-unsent")
            saved = service.get_action(self.token, self.ref, result["query_action_key"])
            self.assertEqual(saved["status"], "dispatching", saved)
            self.case.queries.close()
            self.case.stage1.query_service = None
            self.case.queries = self.case.bridge()
            with self.case.no_probe():
                self.case.queries.restore_owner(
                    self.token,
                    self.ref,
                    self.case.body("owner_offer", "restore-checker-owner"),
                )
                reopened = self.case.queries.services[self.ref]
                recovered = reopened.get_action(
                    self.token, self.ref, result["query_action_key"]
                )
                self.assertEqual(recovered["status"], "execution-unknown", recovered)
                self.assertTrue(
                    self.case.queries.execute(self.token, self.ref, body)["replayed"]
                )
            self.assertEqual(journal.read_bytes(), original_events)
            self.assertEqual(len(self.case.children), 0)
        else:
            self.assertEqual(thread_errors, [])
            observation = service.get_action(
                self.token, self.ref, result["query_action_key"]
            )
            self.assertEqual(observation["status"], "completed", observation)
            self.assertEqual(
                observation["outcome"], "refused-known-unsent", observation
            )
            self.assertEqual(observation["error"]["code"], code)

    def test_final_resource_checker_cannot_run_past_monotonic_deadline(self):
        self.final_checker_refusal("deadline", "query-admission-deadline-expired")

    def test_final_resource_checker_cannot_run_past_permit_expiry(self):
        self.final_checker_refusal("expiry", "query-permit-expired-during-admission")

    def test_final_resource_checker_cannot_dispatch_after_closing(self):
        self.final_checker_refusal("closing", "query-service-closing")

    def test_final_resource_checker_owner_loss_retains_unknown_without_resend(self):
        self.final_checker_refusal("owner", "query-owner-lost")
