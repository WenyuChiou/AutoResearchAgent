"""Synthetic offline expansion contracts; these are not live acceptance evidence."""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from planned_query_raw_runner import run_cases


class ProjectExpansionTests(unittest.TestCase):
    def test_owned_offline_expansion_contracts(self):
        run_cases("test_project_expansions.expansion_core_suite", self)

    def test_additional_expansion_routes_and_saved_coverage(self):
        run_cases(
            "test_project_expansions.expansion_extra_suite",
            self,
            complete_plugin=True,
        )


# The source-bound child supplies this proof before loading the inner cases.
# Normal test discovery runs only the wrapper, avoiding mixed source origins.
if getattr(sys.modules.get("planned_query_fixture"), "RAW_SOURCE_PROOF", None):
    from copy import deepcopy
    from types import SimpleNamespace
    from unittest.mock import patch

    import stage1_retrieval.runner as runner
    import test_retrieval_execution as audit_fixture
    from project_stage1_query_cases import ProjectQueryCases
    from research_workspace_native.project_expansions import (
        ProjectStage1ExpansionService,
    )
    from research_workspace_native.project_intake import ProjectIntakeService
    from research_workspace_native.project_stage1 import ProjectStage1Service
    from research_workspace_native.project_resource_budget import resource_view
    from research_workspace_native.session_api import SessionApiError
    from stage1_coverage.run import CoverageLedger
    from stage1_deliverable.common import canonical, sha
    from stage1_ledger.validation import validate_run
    from test_stage1_ledger import SYNTHETIC
    from test_workspace_project_intake import (
        authenticate,
        bound_body,
        compile_body,
        submit_body,
    )

    class ExpansionCases(unittest.TestCase):
        def setUp(self):
            self.credential, self.principal = "alice-token", "alice"
            self.case = ProjectQueryCases()
            self.case.setUp()
            self.addCleanup(self.case.doCleanups)
            self.case.queries.config["caps"].update(
                max_attempts=6, max_reserved_seconds=300
            )
            created = self.case.intake.create(
                self.credential,
                dict(key="expansion-project", topic="Synthetic RL citation coverage"),
            )
            self.ref = self.case.ref = created["project_ref"]
            body = submit_body(self.case.intake.read(self.credential, self.ref))
            body["budgets"].update(seconds=300, search_calls=6, rounds=2)
            body["consent"]["external_search"] = True
            self.case.intake.submit(self.credential, self.ref, body)
            self.case.intake.compile(
                self.credential,
                self.ref,
                compile_body(self.case.intake.read(self.credential, self.ref)),
            )
            self.expansions = ProjectStage1ExpansionService(self.case.queries)
            self.serial = 0
            self.seed_record = deepcopy(SYNTHETIC)

        def body(self, offer, *, authorize=False, key=None):
            self.serial += 1
            result = dict(
                bound_body(
                    self.case.intake.read(self.credential, self.ref),
                    key or "expansion-" + str(self.serial),
                ),
                offer_ref=offer["offer_ref"],
                offer_sha256=offer["offer_sha256"],
                confirmed=True,
            )
            if authorize:
                result["user_input"] = (
                    "Authorize this exact synthetic work/version, citation direction "
                    "and Semantic Scholar attempt within the existing total budget."
                )
            return result

        def offer(self, field, operation):
            rows = self.expansions.read(self.credential, self.ref)[field]
            return next(r for r in rows if r["document"]["operation"] == operation)

        def fake_backend(self):
            original = runner.subprocess
            test = self

            class Child:
                def __init__(self, argv, **options):
                    test.assertFalse(options["shell"])
                    test.assertEqual(options["stdin"], original.DEVNULL)
                    test.case.children.append(list(argv))
                    operation = argv[len(test.case.pin["argv_prefix"])]
                    backend = (
                        "openalex" if operation == "search" else "semantic-scholar"
                    )
                    row = (
                        test.seed_record
                        if operation == "search"
                        else dict(
                            SYNTHETIC,
                            doi="10.5555/offline-" + operation,
                            title="Synthetic " + operation + " citation result",
                        )
                    )
                    with patch.object(audit_fixture, "SYNTHETIC", row):
                        audit_fixture.synthetic_audit(
                            Path(argv[argv.index("--audit-output") + 1]),
                            backend,
                            "rows",
                            argv[len(test.case.pin["argv_prefix"]) :],
                        )

                def wait(self, timeout=None):
                    return 0

            return patch.object(
                runner,
                "subprocess",
                SimpleNamespace(
                    Popen=Child,
                    DEVNULL=original.DEVNULL,
                    TimeoutExpired=original.TimeoutExpired,
                ),
            )

        def bootstrap(self, *, attempts=6):
            self.case.queries.config["caps"]["max_attempts"] = attempts
            authorization = self.case.body(
                "authorization_offer", "query-authorization", authorize=True
            )
            authorization["user_input"] = (
                f"Authorize {attempts} total offline search/citation attempts "
                "within 300 seconds; no source or model calls."
            )
            self.case.queries.authorize(self.credential, self.ref, authorization)
            self.case.bootstrap()
            self.owner = self.case.queries.services[self.ref]

        def owned(self, producer):
            self.serial += 1
            frontier = self.owner.inspect_saved(self.credential, self.ref)
            digest = sha(canonical(["synthetic-expansion-fixture", self.serial]))
            row = self.owner.mutate_saved(
                self.credential,
                self.ref,
                "fixture-" + str(self.serial),
                digest,
                frontier["tree_sha256"],
                "stage1-coverage",
                producer,
            )
            self.assertEqual(row["status"], "completed", row)
            return row["result"]

        def ledger(self):
            state = self.case.intake._load(self.principal, self.ref)
            return self.case.stage1._ledger(state, self.case.intake.binding(self.ref))[
                1
            ]

        def search(self, key="seed-search"):
            request = self.case.body("query_offer", key)
            with self.fake_backend(), self.case.no_probe():
                receipt = self.case.queries.execute(self.credential, self.ref, request)
                self.owner._workers[self.ref].join(30)
            action = self.owner.get_action(
                self.credential, self.ref, receipt["query_action_key"]
            )
            self.assertEqual(action["status"], "completed", action)
            self.assertEqual(action["result"]["backend_outcome"], "success_nonempty")
            return action

        def seed(
            self,
            *,
            attempts=6,
            verified=True,
            closest=True,
            bootstrapped=False,
            search_key="seed-search",
        ):
            if not bootstrapped:
                self.bootstrap(attempts=attempts)
            self.assertEqual(
                self.expansions.read(self.credential, self.ref)["authorization_offers"],
                [],
            )
            self.search(search_key)

            def add_review(ledger):
                candidate = next(
                    row
                    for row in ledger.candidates().values()
                    if any(
                        d["record"].get("title") == self.seed_record["title"]
                        for d in row["discoveries"]
                    )
                )
                self.work, self.version = (
                    candidate["work_id"],
                    candidate["version_ids"][0],
                )
                imported = ledger.start_source_import(
                    work_id=self.work,
                    version_id=self.version,
                    source_uri="https://example.invalid/offline-source",
                    actor="synthetic-fixture",
                    reason="Authored saved fixture; no source acquisition",
                )
                source = ledger.save_bytes(
                    b"Synthetic household record", producer=imported
                )
                ledger.decide(
                    self.work,
                    "include",
                    reason="scope-match",
                    rationale="Synthetic fixture inclusion",
                    evidence_refs=[source],
                )
                self.claims = {
                    field: ledger.claim(
                        work_id=self.work,
                        version_id=self.version,
                        claim_text="Synthetic evidence for " + field,
                        relation="supports",
                        evidence_level="full_text",
                        locator=dict(
                            section="fixture", quote="Synthetic household record"
                        ),
                        source_ref=source,
                        verifier=dict(
                            actor="synthetic-fixture",
                            method="saved-text-review",
                            actor_type="agent",
                        ),
                    )
                    for field in (
                        "title",
                        "authors",
                        "year",
                        "identifier",
                        "version",
                        "relevance",
                    )
                }
                return self.review(ledger, verified=verified, closest=closest)

            self.owned(add_review)

        def review(self, ledger, *, verified=True, closest=True):
            return dict(
                event_id=ledger.review_work(
                    work_id=self.work,
                    version_id=self.version,
                    cluster_claims={
                        c["cluster_id"]: self.claims["relevance"]
                        for c in ledger.coverage_state().plan["proposal"]["clusters"]
                    },
                    identity_status="verified" if verified else "unverifiable",
                    identity_claims={
                        k: self.claims[k] if verified else None
                        for k in ("title", "authors", "year", "identifier", "version")
                    },
                    closest=closest,
                    assessor="synthetic-fixture",
                    rationale="Authored fixture review, not scientific verification",
                )
            )

        def authorize(self, operation):
            request = self.body(
                self.offer("authorization_offers", operation), authorize=True
            )
            receipt = self.expansions.authorize(self.credential, self.ref, request)
            return request, receipt

        def execute(self, operation):
            request = self.body(self.offer("execution_offers", operation))
            with self.fake_backend(), self.case.no_probe():
                receipt = self.expansions.execute(self.credential, self.ref, request)
                self.owner._workers[self.ref].join(30)
            action = self.owner.get_action(
                self.credential, self.ref, receipt["query_action_key"]
            )
            self.assertEqual(action["status"], "completed", action)
            self.assertEqual(action["result"]["backend_outcome"], "success_nonempty")
            self.owned(
                lambda ledger: dict(
                    event_id=ledger.receipt(
                        action["result"]["query_result_id"],
                        truncated=False,
                        note="Authored offline fixture has one complete synthetic result",
                    )
                )
            )
            return request, receipt, action

        def test_get_and_grant_are_passive_and_only_current_verified_closest_is_offered(
            self,
        ):
            self.seed(verified=False, closest=False)
            with patch.object(
                runner, "execute", side_effect=AssertionError("GET dispatch")
            ):
                view = self.expansions.read(self.credential, self.ref)
                self.assertEqual(view["authorization_offers"], [])
                self.assertEqual(view["execution_offers"], [])
            self.owned(lambda ledger: self.review(ledger))
            before = self.case.queries.read(self.credential, self.ref)["budget"]
            with (
                patch(
                    "stage1_retrieval.runtime_identity.capture_identity",
                    side_effect=AssertionError("probe"),
                ),
                patch.object(
                    runner, "execute", side_effect=AssertionError("grant dispatch")
                ),
                patch.object(
                    CoverageLedger,
                    "start_expansion",
                    side_effect=AssertionError("grant Core write"),
                ),
            ):
                view = self.expansions.read(self.credential, self.ref)
                self.assertEqual(
                    {r["document"]["operation"] for r in view["authorization_offers"]},
                    {"references", "cited-by"},
                )
                request, receipt = self.authorize("references")
                replay = self.expansions.authorize(self.credential, self.ref, request)
                self.assertTrue(replay["replayed"])
                self.assertEqual(replay["request_sha256"], receipt["request_sha256"])
                self.assertEqual(
                    len(
                        self.expansions.read(self.credential, self.ref)[
                            "execution_offers"
                        ]
                    ),
                    1,
                )
            self.assertEqual(
                self.case.queries.read(self.credential, self.ref)["budget"], before
            )
            self.assertEqual(len(self.case.children), 1)

        def test_both_directions_use_original_owner_real_core_and_shared_attempt_budget(
            self,
        ):
            self.seed()
            for operation in ("references", "cited-by"):
                self.authorize(operation)
                request, _, action = self.execute(operation)
                ledger = self.ledger()
                query = ledger.event(action["result"]["query_id"], "ActionStarted")
                self.assertEqual(query["arguments"]["operation"], operation)
                self.assertEqual(
                    query["arguments"]["coverage"]["seed_work_id"], self.work
                )
                self.assertEqual(
                    query["arguments"]["coverage"]["seed_version_id"], self.version
                )
                completed = ledger.event(
                    action["result"]["query_result_id"], "QueryEvent"
                )
                self.assertEqual(completed["attempted_backends"], ["semantic-scholar"])
                self.assertTrue(action["result"]["execution_ref"])
                before = ledger.state_hash()
                with patch.object(
                    runner, "execute", side_effect=AssertionError("replay dispatch")
                ):
                    self.assertTrue(
                        self.expansions.execute(self.credential, self.ref, request)[
                            "replayed"
                        ]
                    )
                    replacement = dict(
                        request,
                        **bound_body(
                            self.case.intake.read(self.credential, self.ref),
                            "second-use-" + operation,
                        ),
                    )
                    with self.assertRaises(SessionApiError):
                        self.expansions.execute(self.credential, self.ref, replacement)
                self.assertEqual(self.ledger().state_hash(), before)
                self.assertFalse(
                    any(
                        r["document"]["operation"] == operation
                        for r in self.expansions.read(self.credential, self.ref)[
                            "authorization_offers"
                        ]
                    )
                )
            self.assertEqual(len(self.case.children), 3)
            self.assertEqual(len(self.ledger().candidates()), 3)
            self.assertEqual(
                self.case.queries.read(self.credential, self.ref)["budget"],
                dict(probes=1, attempts=3, seconds=126),
            )
            self.assertEqual(
                self.owner.view(self.credential, self.ref)["budget"],
                dict(attempts=3, seconds=96),
            )
            resource = resource_view(
                self.case.intake,
                self.case.intake._load(self.principal, self.ref),
                self.principal,
            )
            self.assertEqual(resource["reserved"]["seconds"], 126)
            self.assertEqual(resource["reserved"]["search_calls"], 3)
            self.assertTrue(validate_run(self.ledger().root)["valid"])

        def test_wrong_offer_and_grant_payload_are_rejected_before_reservation(self):
            self.seed()
            request, _ = self.authorize("references")
            execution = self.body(self.offer("execution_offers", "references"))
            before = self.case.queries.read(self.credential, self.ref)["budget"]
            frontier = self.owner.inspect_saved(self.credential, self.ref)
            for change in (
                dict(offer_sha256="0" * 64),
                dict(offer_ref="foreign-offer"),
                dict(root="caller"),
                dict(confirmed=False),
            ):
                with self.subTest(change=change), self.assertRaises(SessionApiError):
                    self.expansions.execute(
                        self.credential, self.ref, {**execution, **change}
                    )
                self.assertEqual(
                    self.case.queries.read(self.credential, self.ref)["budget"], before
                )
                self.assertEqual(
                    self.owner.inspect_saved(self.credential, self.ref), frontier
                )
            with self.assertRaises(SessionApiError):
                self.expansions.authorize(
                    self.credential, self.ref, dict(request, user_input="Changed grant")
                )
            with self.assertRaises(SessionApiError):
                self.expansions.read("bob-token", self.ref)

        def test_review_or_version_change_revokes_saved_grant_before_reservation(self):
            self.seed()
            self.authorize("references")
            request = self.body(self.offer("execution_offers", "references"))
            self.seed_record["version"] = "record-v2"
            self.search("new-version-search")
            self.assertGreater(
                len(self.ledger().candidates()[self.work]["version_ids"]), 1
            )
            before = self.case.queries.read(self.credential, self.ref)["budget"]
            with self.assertRaises(SessionApiError):
                self.expansions.execute(self.credential, self.ref, request)
            self.assertEqual(
                self.case.queries.read(self.credential, self.ref)["budget"], before
            )
            self.assertEqual(
                self.expansions.read(self.credential, self.ref)["execution_offers"], []
            )
            self.assertEqual(len(self.case.children), 2)

        def test_search_and_both_expansions_cannot_reset_total_cap(self):
            self.seed(attempts=3)
            for operation in ("references", "cited-by"):
                self.authorize(operation)
                self.execute(operation)
            before = self.case.queries.read(self.credential, self.ref)["budget"]
            self.assertEqual(before, dict(probes=1, attempts=3, seconds=126))
            self.assertIsNone(
                self.case.queries.read(self.credential, self.ref)["query_offer"]
            )
            self.assertEqual(
                self.expansions.read(self.credential, self.ref)["execution_offers"], []
            )
            self.assertEqual(
                self.expansions.read(self.credential, self.ref)["authorization_offers"],
                [],
            )
            self.assertEqual(len(self.case.children), 3)

        def test_round_change_revokes_grant_before_reservation(self):
            self.seed()
            self.authorize("references")
            request = self.body(self.offer("execution_offers", "references"))

            def next_round(ledger):
                closed = ledger.close_round()
                return dict(closed=closed, opened=ledger.open_round())

            self.owned(next_round)
            before = self.case.queries.read(self.credential, self.ref)["budget"]
            with self.assertRaises(SessionApiError):
                self.expansions.execute(self.credential, self.ref, request)
            self.assertEqual(
                self.case.queries.read(self.credential, self.ref)["budget"], before
            )
            self.assertEqual(
                self.expansions.read(self.credential, self.ref)["execution_offers"], []
            )
            self.assertEqual(len(self.case.children), 1)

        def test_unknown_worker_start_survives_true_reopen_without_resend(self):
            self.seed()
            self.authorize("references")
            request = self.body(self.offer("execution_offers", "references"))
            previous_owner = self.owner._projects[self.ref]["owner"]

            class Unstarted:
                ident = None

                def __init__(self, **kwargs):
                    pass

                def start(self):
                    raise RuntimeError("synthetic start outcome unobserved")

                def is_alive(self):
                    return False

            with (
                patch.dict(
                    self.owner.execute.__func__.__globals__,
                    threading=SimpleNamespace(Thread=Unstarted),
                ),
                self.assertRaisesRegex(
                    RuntimeError, "^synthetic start outcome unobserved$"
                ),
            ):
                self.expansions.execute(self.credential, self.ref, request)
            outer = self.case.intake.action(
                self.credential, request["key"], project_ref=self.ref
            )
            self.assertIn(outer["status"], {"failed", "execution-unknown"})
            inner_key = "project-" + outer["request_sha256"]
            inner_before = self.owner.get_action(self.credential, self.ref, inner_key)
            self.assertEqual(inner_before["status"], "execution-unknown")
            self.assertEqual(inner_before["method"], "stage1/expansion")
            self.assertEqual(
                self.owner.view(self.credential, self.ref)["budget"],
                dict(attempts=2, seconds=64),
            )
            self.assertEqual(len(self.case.children), 1)
            self.case.queries.close()
            self.case.intake.close()
            self.case.intake = ProjectIntakeService(
                self.case.root / "p", authenticate=authenticate
            )
            self.case.addCleanup(self.case.intake.close)
            self.case.stage1 = ProjectStage1Service(self.case.intake, limit=3)
            self.case.queries = self.case.bridge()
            self.case.queries.config["caps"].update(
                max_attempts=6, max_reserved_seconds=300
            )
            self.expansions = ProjectStage1ExpansionService(self.case.queries)
            with (
                patch(
                    "stage1_retrieval.runtime_identity.capture_identity",
                    side_effect=AssertionError("reopen probe"),
                ),
                patch.object(
                    CoverageLedger,
                    "start_expansion",
                    side_effect=AssertionError("reopen Core dispatch"),
                ),
                patch.object(
                    runner,
                    "execute",
                    side_effect=AssertionError("reopen command dispatch"),
                ),
            ):
                before = self.case.queries.read(self.credential, self.ref)
                self.assertEqual(before["status"], "owner-reopen-required")
                self.case.queries.restore_owner(
                    self.credential,
                    self.ref,
                    self.case.body("owner_offer", "restore-expansion-owner"),
                )
                self.owner = self.case.queries.services[self.ref]
                self.assertNotEqual(
                    self.owner._projects[self.ref]["owner"], previous_owner
                )
                replay = self.expansions.execute(self.credential, self.ref, request)
                self.assertTrue(replay["replayed"])
                self.assertEqual(replay["status"], outer["status"])
                view = self.expansions.read(self.credential, self.ref)
                self.assertEqual(view["authorization_offers"], [])
                self.assertEqual(view["execution_offers"], [])
                self.assertTrue(view.get("refusal"))
                inner = self.owner.get_action(self.credential, self.ref, inner_key)
                self.assertEqual(inner["status"], "execution-unknown")
                self.assertEqual(
                    inner["request_sha256"], inner_before["request_sha256"]
                )
            self.assertEqual(
                self.case.queries.read(self.credential, self.ref)["budget"],
                dict(probes=1, attempts=2, seconds=94),
            )
            self.assertEqual(len(self.case.children), 1)

        def test_arxiv_seed_is_supported_without_doi(self):
            self.seed_record.pop("doi")
            self.seed_record["arxiv"] = "2601.01234"
            self.seed()
            self.authorize("references")
            self.execute("references")
            self.assertEqual(self.case.children[-1][-1], "ARXIV:2601.01234")

        def test_seed_without_supported_identifier_has_no_offer(self):
            self.seed_record.pop("doi")
            self.seed()
            view = self.expansions.read(self.credential, self.ref)
            self.assertEqual(view["authorization_offers"], [])
            self.assertEqual(view["execution_offers"], [])
            self.assertEqual(len(self.case.children), 1)

        def test_completed_directions_across_rounds_need_no_new_grant(self):
            self.seed()
            for operation in ("references", "cited-by"):
                self.authorize(operation)
                self.execute(operation)

            def next_round(ledger):
                return dict(closed=ledger.close_round(), opened=ledger.open_round())

            self.owned(next_round)
            before = self.case.queries.read(self.credential, self.ref)["budget"]
            view = self.expansions.read(self.credential, self.ref)
            self.assertEqual(view["authorization_offers"], [])
            self.assertEqual(view["execution_offers"], [])
            self.assertEqual(
                self.case.queries.read(self.credential, self.ref)["budget"], before
            )
            self.assertEqual(len(self.case.children), 3)

        def test_unsupported_seed_keeps_other_current_supported_offers(self):
            self.seed_record.pop("doi")
            self.seed_record["title"] = "Synthetic unsupported citation seed"
            self.seed()
            unsupported = self.work
            self.seed_record = dict(
                SYNTHETIC, title="Synthetic supported citation seed"
            )
            self.seed(bootstrapped=True, search_key="healthy-seed-search")
            view = self.expansions.read(self.credential, self.ref)
            self.assertEqual(
                {
                    (r["document"]["work_id"], r["document"]["operation"])
                    for r in view["authorization_offers"]
                },
                {(self.work, "references"), (self.work, "cited-by")},
            )
            self.assertTrue(
                any(
                    row["work_id"] == unsupported
                    and row["code"] == "citation-seed-has-no-supported-identifier"
                    for row in view["unavailable"]
                )
            )
            self.assertEqual(len(self.case.children), 2)

        def test_real_http_expansion_routes_keep_local_viewer_auth_and_replay(self):
            from project_stage1_query_http_cases import ProjectStage1QueryHttpTests

            http = ProjectStage1QueryHttpTests()
            self.addCleanup(http.doCleanups)
            http.setUp()
            http.queries, http.body = http.bridge, http.offered
            self.case, self.ref = http, http.ref
            self.credential, self.principal = http.token, "local-viewer"
            self.expansions = ProjectStage1ExpansionService(http.bridge)
            http.bootstrap()
            self.owner = http.bridge.services[self.ref]
            self.seed(bootstrapped=True)
            before = http.state_on_disk()
            view = http.get(http.base + "/stage1")["expansion_execution"]
            authorization = self.body(
                next(
                    r
                    for r in view["authorization_offers"]
                    if r["document"]["operation"] == "references"
                ),
                authorize=True,
            )
            path = http.base + "/stage1/expansion-authorize"
            for changed, options, expected in (
                (dict(authorization, principal="caller"), {}, 400),
                (authorization, dict(origin="https://unrelated.example"), 403),
                (authorization, dict(token="wrong-synthetic-token"), 401),
            ):
                status, raw = http.request(path, changed, **options)
                self.assertEqual(status, expected, raw)
            self.assertEqual(http.state_on_disk(), before)
            first_grant = http.post(path, authorization)
            self.assertTrue(http.post(path, authorization)["replayed"])
            execution = self.body(
                http.get(http.base + "/stage1")["expansion_execution"][
                    "execution_offers"
                ][0]
            )
            with self.fake_backend(), http.no_probe():
                queued = http.post(http.base + "/stage1/expansion-execute", execution)
                self.owner._workers[self.ref].join(30)
            observed = self.owner.get_action(
                self.credential, self.ref, queued["query_action_key"]
            )
            self.assertEqual(observed["status"], "completed", observed)
            self.assertEqual(observed["result"]["backend_outcome"], "success_nonempty")
            self.assertEqual(
                queued["expansion_grant_sha256"], first_grant["permit_sha256"]
            )
            before = http.state_on_disk()
            with (
                http.block_external(),
                patch.object(
                    runner,
                    "verify_identity",
                    side_effect=AssertionError("HTTP GET probe"),
                ),
            ):
                replay = http.post(http.base + "/stage1/expansion-execute", execution)
                self.assertTrue(replay["replayed"])
                for _ in range(2):
                    http.get(http.base + "/stage1")
                    http.get(http.base + "/history")
            self.assertEqual(http.state_on_disk(), before)
            self.assertEqual(len(http.children), 2)

    EXTRA_CASES = {
        "test_completed_directions_across_rounds_need_no_new_grant",
        "test_unsupported_seed_keeps_other_current_supported_offers",
        "test_real_http_expansion_routes_keep_local_viewer_auth_and_replay",
    }

    def expansion_core_suite():
        names = unittest.defaultTestLoader.getTestCaseNames(ExpansionCases)
        return unittest.TestSuite(
            ExpansionCases(name) for name in names if name not in EXTRA_CASES
        )

    def expansion_extra_suite():
        return unittest.TestSuite(ExpansionCases(name) for name in sorted(EXTRA_CASES))


if __name__ == "__main__":
    unittest.main()
