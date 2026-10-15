"""Saved Core coverage through the project API; no external or model calls."""

from copy import deepcopy
import unittest
from unittest.mock import patch

import test_project_stage1 as stage_tests
from test_stage1_ledger import SYNTHETIC
from test_workspace_project_intake import compile_body, submit_body
from research_workspace_native.project_intake import ProjectIntakeService
from research_workspace_native.project_stage1 import ProjectStage1Service
from research_workspace_native.session_api import SessionApiError
from stage1_coverage.run import CoverageLedger
from stage1_ledger.journal import canonical
from stage1_ledger.validation import validate_run


class ProjectCoverageTests(unittest.TestCase):
    def setUp(self):
        self.case = stage_tests.ProjectStage1Tests()
        self.case.setUp()
        self.addCleanup(self.case.tearDown)
        view = self.case.intake.create(
            "alice-token", dict(key="create", topic="Synthetic saved RL evidence")
        )
        self.ref = view["project_ref"]
        view = self.case.intake.read("alice-token", self.ref)
        body = submit_body(view)
        body["budgets"]["rounds"] = 3
        self.case.intake.submit("alice-token", self.ref, body)
        compiled = compile_body(self.case.intake.read("alice-token", self.ref))
        compiled["request"]["proposal"]["clusters"] = compiled["request"]["proposal"][
            "clusters"
        ][:1]
        compiled["request"]["query_bindings"] = compiled["request"]["query_bindings"][
            :1
        ]
        self.case.intake.compile("alice-token", self.ref, compiled)
        self.case.initialize(self.ref)
        self.ledger = self.case.private_ledger(self.ref)
        self.serial = 0

    def offer(self, operation, target=None):
        rows = self.case.service.read("alice-token", self.ref)["coverage_actions"][
            "offers"
        ]
        return next(
            r
            for r in rows
            if r["operation"] == operation
            and (target is None or target in r["document"].values())
        )

    def body(self, operation, review, target=None):
        self.serial += 1
        offer = self.offer(operation, target)
        return dict(
            self.case.action_body(self.ref, "coverage-" + str(self.serial)),
            operation=operation,
            offer_ref=offer["offer_ref"],
            offer_sha256=offer["offer_sha256"],
            review=deepcopy(review),
        )

    def submit(self, operation, review, target=None):
        return self.case.service.coverage(
            "alice-token", self.ref, self.body(operation, review, target)
        )

    def observe(self, planned, *, rows=(), operation=None):
        query = (
            self.ledger.start_planned(planned)
            if operation is None
            else self.ledger.start_expansion(operation, self.work, self.version)
        )
        arguments = self.ledger.event(query, "ActionStarted")["arguments"]
        backend = self.ledger.coverage_state().backends_for(arguments)[0]
        attempt = self.ledger.start(
            "backend", {"variant": "base"}, backend=backend, parent_id=query
        )
        raw = self.ledger.save_bytes(canonical(list(rows)), producer=attempt)
        stderr = self.ledger.save_bytes(b"", producer=attempt)
        self.ledger.finish(
            attempt,
            outcome="success_nonempty" if rows else "success_empty",
            http_status=200,
            exit_code=0,
            stdout=raw,
            stderr=stderr,
            records=raw,
        )
        complete = self.ledger.complete_query(query)
        self.ledger.extract()
        return complete

    def seed(self):
        self.first_planned = next(iter(self.ledger.coverage_state().queries))
        completed = self.observe(self.first_planned, rows=[SYNTHETIC])
        candidate = next(iter(self.ledger.candidates().values()))
        self.work, self.version = candidate["work_id"], candidate["version_ids"][0]
        imported = self.ledger.start_source_import(
            work_id=self.work,
            version_id=self.version,
            source_uri="https://example.invalid/synthetic",
            actor="synthetic-fixture",
            reason="Saved synthetic source, no network",
        )
        source = self.ledger.save_bytes(
            b"Synthetic household record", producer=imported
        )
        self.ledger.decide(
            self.work,
            "include",
            reason="scope-match",
            rationale="Synthetic saved fixture",
            evidence_refs=[source],
        )
        self.claims = {}
        for field in ("title", "authors", "year", "identifier", "version", "relevance"):
            self.claims[field] = self.ledger.claim(
                work_id=self.work,
                version_id=self.version,
                claim_text="Synthetic evidence for " + field,
                relation="supports",
                evidence_level="full_text",
                locator=dict(section="fixture", quote="Synthetic household record"),
                source_ref=source,
                verifier=dict(
                    actor="synthetic-fixture",
                    method="saved-text-review",
                    actor_type="agent",
                ),
            )
        return completed

    def review(self, verified=True):
        return dict(
            cluster_claims={
                c["cluster_id"]: self.claims["relevance"]
                for c in self.ledger.coverage_state().plan["proposal"]["clusters"]
            },
            identity_status="verified" if verified else "unverifiable",
            identity_claims={
                k: self.claims[k] if verified else None
                for k in ("title", "authors", "year", "identifier", "version")
            },
            closest=verified,
            rationale="Synthetic explicit researcher review",
        )

    def test_real_core_reviews_rounds_and_checkpoint_without_external_permission(self):
        completed = self.seed()
        receipt = self.submit(
            "receipt", dict(truncated=None, note="Observation unknown"), completed
        )
        self.assertFalse(receipt["stage1_complete"])
        self.assertIsNone(self.ledger.coverage_state().receipts[completed]["truncated"])
        self.submit(
            "receipt",
            dict(truncated=False, note="Synthetic complete observation"),
            completed,
        )
        self.submit("review-work", self.review(), self.work)
        for operation in ("references", "cited-by"):
            event = self.observe(None, operation=operation)
            self.submit(
                "receipt",
                dict(truncated=False, note="Synthetic complete expansion"),
                event,
            )
        for number in range(1, 4):
            if number > 1:
                self.submit("open-round", {})
            for planned in self.ledger.coverage_state().queries:
                if number == 1 and planned == self.first_planned:
                    continue
                event = self.observe(planned)
                self.submit(
                    "receipt",
                    dict(truncated=False, note="Synthetic complete query"),
                    event,
                )
            self.submit("close-round", {})
        report = validate_run(self.ledger.root)
        self.assertTrue(report["valid"], report)
        self.assertEqual(report["coverage"]["blockers"], [])
        self.submit(
            "human-action",
            dict(
                action="accept-stop",
                cluster_id=None,
                user_input="Synthetic explicit stop review",
            ),
        )
        checkpoint = self.case.service.checkpoint(
            "alice-token", self.ref, self.case.action_body(self.ref, "checkpoint")
        )
        self.assertEqual(checkpoint["next_allowed_action"], "stop-sufficient")
        self.assertFalse(checkpoint["stage1_complete"])
        view = self.case.service.read("alice-token", self.ref)
        self.assertFalse(view["coverage_actions"]["grants_external_permission"])
        self.assertEqual(view["evaluation_status"], "not-scored")
        self.assertIsNone(view["canonical_package"])
        self.case.runner.assert_not_called()

    def test_invalid_or_stale_offer_rejected_before_intent_and_gate_not_overridden(
        self,
    ):
        self.seed()
        body = self.body("review-work", self.review())
        original = self.ledger.state_hash()
        for change in (
            dict(review={**body["review"], "root": "caller"}),
            dict(review={**body["review"], "identity_claims": {}}),
            dict(
                review={
                    **body["review"],
                    "cluster_claims": {"foreign": self.claims["relevance"]},
                }
            ),
            dict(
                review={
                    **body["review"],
                    "identity_claims": {
                        k: self.claims["relevance"]
                        for k in body["review"]["identity_claims"]
                    },
                }
            ),
            dict(offer_sha256="0" * 64),
            dict(root="caller"),
        ):
            with (
                self.subTest(change=change),
                self.assertRaises((SessionApiError, ValueError)),
            ):
                self.case.service.coverage("alice-token", self.ref, {**body, **change})
            self.assertEqual(self.ledger.state_hash(), original)
        with self.assertRaisesRegex(SessionApiError, "intake-action-unavailable"):
            self.case.intake.action("alice-token", body["key"], project_ref=self.ref)
        self.submit("review-work", self.review(False))
        with self.assertRaises(SessionApiError):
            self.case.service.coverage("alice-token", self.ref, body)
        self.submit(
            "human-action",
            dict(
                action="accept-stop",
                cluster_id=None,
                user_input="Synthetic acceptance cannot create coverage",
            ),
        )
        current = self.case.service.read("alice-token", self.ref)
        self.assertTrue(current["coverage_actions"]["blockers"])
        self.assertFalse(current["stage1_complete"])

    def test_sqlite_reopen_same_key_no_extra_core_write_or_changed_payload(self):
        body = self.body("close-round", {})
        first = self.case.service.coverage("alice-token", self.ref, body)
        before = self.ledger.state_hash()
        self.case.intake.close()
        self.case.intake = ProjectIntakeService(
            self.case.root, authenticate=stage_tests.authenticate
        )
        self.case.service = ProjectStage1Service(
            self.case.intake, query_runner=self.case.runner
        )
        with patch.object(
            CoverageLedger, "close_round", side_effect=AssertionError("duplicate write")
        ):
            replay = self.case.service.coverage(
                "alice-token", self.ref, {**body, "revision": 999}
            )
            self.assertTrue(replay["replayed"])
            self.assertEqual(replay["event_id"], first["event_id"])
            with self.assertRaises(SessionApiError):
                self.case.service.coverage(
                    "alice-token", self.ref, {**body, "review": {"changed": True}}
                )
        self.assertEqual(self.ledger.state_hash(), before)

    def test_after_core_write_failure_remains_unknown_and_no_resend(self):
        body = self.body("close-round", {})
        original = CoverageLedger.close_round

        def failed(ledger):
            original(ledger)
            raise OSError("synthetic failure after Core write")

        with (
            patch.object(CoverageLedger, "close_round", failed),
            self.assertRaises(SessionApiError),
        ):
            self.case.service.coverage("alice-token", self.ref, body)
        before = self.ledger.state_hash()
        self.assertEqual(
            self.case.intake.action("alice-token", body["key"], project_ref=self.ref)[
                "status"
            ],
            "execution-unknown",
        )
        with patch.object(
            CoverageLedger, "close_round", side_effect=AssertionError("duplicate write")
        ):
            replay = self.case.service.coverage("alice-token", self.ref, body)
            self.assertEqual(replay["status"], "execution-unknown")
            new_body = self.body("open-round", {})
            with self.assertRaisesRegex(
                SessionApiError, "stage1-coverage-write-outcome-unobserved"
            ):
                self.case.service.coverage("alice-token", self.ref, new_body)
            with self.assertRaisesRegex(
                SessionApiError, "stage1-coverage-write-outcome-unobserved"
            ):
                self.case.service.checkpoint(
                    "alice-token",
                    self.ref,
                    self.case.action_body(self.ref, "late-checkpoint"),
                )
        self.assertTrue(
            self.case.service.read("alice-token", self.ref)["coverage_actions"]["held"]
        )
        self.assertEqual(self.ledger.state_hash(), before)

    def test_confirmed_round_budget_and_bounded_offers_preserve_unknown(self):
        self.seed()
        from research_workspace_native import project_stage1_coverage as coverage

        with patch.object(coverage, "MAX_OFFERS", 1):
            view = self.case.service.read("alice-token", self.ref)["coverage_actions"]
            self.assertEqual(len(view["offers"]), 1)
            self.assertEqual(view["omitted_work_count"], 1)
            self.assertGreater(view["omitted_action_count"], 0)
        with patch.object(coverage, "MAX_OFFER_BYTES", 1):
            view = self.case.service.read("alice-token", self.ref)["coverage_actions"]
            self.assertEqual(view["offers"], [])
            self.assertGreater(view["omitted_action_count"], 0)
        self.submit("close-round", {})
        with patch.object(coverage, "offers", wraps=coverage.offers):
            # Simulate a smaller already-confirmed local budget at this pure offer boundary.
            binding = deepcopy(self.case.intake.binding(self.ref))
            binding["settings"]["budgets"]["rounds"] = 1
            state = self.case.intake._load("alice", self.ref)
            run = state["stage1_runs"][state["stage1_active"]]
            view = coverage.offers(
                self.ledger, binding, run, validate_run(self.ledger.root)
            )
            self.assertFalse(
                any(r["operation"] == "open-round" for r in view["offers"])
            )
        self.case.runner.assert_not_called()

    def test_deadline_after_validation_prevents_core_write(self):
        from research_workspace_native import project_stage1_coverage as coverage

        before = self.ledger.state_hash()
        for expire_on_prepare in (1, 2):
            body = self.body("close-round", {})
            count = 0
            expired = False
            original = coverage.prepare

            def prepare(*args, **kwargs):
                nonlocal count, expired
                result = original(*args, **kwargs)
                count += 1
                expired = count == expire_on_prepare
                return result

            def deadline():
                if expired:
                    raise TimeoutError("synthetic absolute HTTP deadline")

            with (
                patch.object(coverage, "prepare", prepare),
                patch.object(
                    CoverageLedger,
                    "close_round",
                    side_effect=AssertionError("late write"),
                ),
                self.assertRaises((TimeoutError, SessionApiError)),
            ):
                self.case.service.coverage(
                    "alice-token", self.ref, body, check_deadline=deadline
                )
            self.assertEqual(self.ledger.state_hash(), before)
            if expire_on_prepare == 1:
                with self.assertRaises(SessionApiError):
                    self.case.intake.action(
                        "alice-token", body["key"], project_ref=self.ref
                    )
            else:
                self.assertEqual(
                    self.case.intake.action(
                        "alice-token", body["key"], project_ref=self.ref
                    )["status"],
                    "execution-unknown",
                )


if __name__ == "__main__":
    unittest.main()
