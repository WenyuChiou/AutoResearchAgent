"""Real brief compiler and SQLite intake tests; no native, model or search calls."""

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cli"))
from research_workspace_native.project_intake import ProjectIntakeService
from research_workspace_native.session_api import SessionApiError
from stage1_brief.brief import validate_bound_plan, validate_brief
from stage1_ledger.journal import canonical
from test_stage1_coverage import proposal


def authenticate(credential):
    return {"alice-token": "alice", "bob-token": "bob"}.get(credential)


def create_body(topic="Aircraft fault diagnosis with sensor drift"):
    return {"key": "create", "topic": topic}


def bound_body(view, key):
    return {
        "key": key,
        **{
            field: view[field]
            for field in ("revision", "input_version", "brief_sha256")
        },
    }


def submit_body(view):
    return {
        **bound_body(view, "confirm"),
        "choices": [
            {
                "field": "geography",
                "status": "not-applicable",
                "value": None,
                "reason": "Method study has no geographic boundary.",
                "user_input": "Geography is not applicable to this method study.",
            }
        ],
        "formal_target": 30,
        "priority_reading_target": 20,
        "resource_envelope": "One researcher; no paid research execution authorized yet.",
        "budgets": {
            "model_calls": 0,
            "seconds": 0,
            "search_calls": 0,
            "source_reads": 0,
            "rounds": 0,
        },
        "consent": {
            "external_search": False,
            "public_source_read": False,
            "browser_fallback": False,
        },
        "user_input": "Use 30 formal works and 20 priority readings; preserve the wider screening list.",
        "confirmed": True,
    }


def compile_body(view):
    authored = proposal()
    authored["topic"] = view["brief"]["original_description"]
    authored["concepts"][0]["terms"] = [authored["topic"]]
    authored["concepts"][1]["terms"] = ["methods", "validation"]
    for cluster in authored["clusters"]:
        cluster["question"] = "Which evidence addresses " + authored["topic"] + "?"
        cluster["query_families"][0]["adversarial_queries"] = [
            "limitations of " + authored["topic"]
        ]
    return {
        **bound_body(view, "compile"),
        "as_of": "2026-10-10",
        "request": {
            "proposal": authored,
            "query_bindings": [
                {
                    "family_id": f"family-{i}",
                    "need_ids": ["main"],
                    "purpose": "study-evidence",
                    "scope_filters": {},
                }
                for i in range(1, 5)
            ],
        },
    }


class ProjectIntakeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="project-intake-")
        self.root = Path(self.tmp.name)
        self.service = ProjectIntakeService(self.root, authenticate=authenticate)

    def tearDown(self):
        self.service.close()
        self.tmp.cleanup()

    def new(self, topic="Aircraft fault diagnosis with sensor drift", key="create"):
        body = create_body(topic)
        body["key"] = key
        receipt = self.service.create("alice-token", body)
        return self.service.read("alice-token", receipt["project_ref"])

    def confirmed(
        self, topic="Aircraft fault diagnosis with sensor drift", key="create"
    ):
        view = self.new(topic, key)
        self.service.submit("alice-token", view["project_ref"], submit_body(view))
        return self.service.read("alice-token", view["project_ref"])

    def test_two_arbitrary_topics_use_real_v11_intake_and_compiler(self):
        for key, topic in (
            ("aircraft", "Aircraft fault diagnosis with sensor drift"),
            ("music", "Polyphonic music transcription with scarce annotations"),
        ):
            with self.subTest(topic=topic):
                view = self.confirmed(topic, key)
                ref = view["project_ref"]
                self.assertEqual(view["brief"]["schema_version"], "1.1.0")
                self.assertEqual(view["brief"]["original_description"], topic)
                self.assertEqual(
                    view["intake_report"]["formal_final_count"]["target"], 30
                )
                self.assertEqual(
                    view["intake_report"]["scope"]["priority_reading_target"]["value"],
                    "20",
                )
                self.assertFalse(view["stage1_intake_ready"])
                result = self.service.compile("alice-token", ref, compile_body(view))
                binding = self.service.binding(ref)
                self.assertTrue(
                    validate_bound_plan(binding["plan_root"], binding["brief_path"])[
                        "valid"
                    ]
                )
                self.assertEqual(result["plan_execution_status"], "not-executed")
                ready = self.service.read("alice-token", ref)
                self.assertTrue(ready["stage1_intake_ready"])
                self.assertFalse(binding["execution_authorized"])
                self.assertEqual(ready["stage1_status"], "not-started")
                self.assertIsNone(ready["model_calls"])
                self.assertIsNone(ready["monetary_cost"])
                queries = (binding["plan_root"] / "query_plan.jsonl").read_text(
                    encoding="utf-8"
                )
                self.assertNotIn('"30"', queries)
                self.assertNotIn('"20"', queries)

    def test_proposed_defaults_are_pending_not_submitted_answers(self):
        view = self.new()
        self.assertEqual(view["formal_question"]["proposed_target"], 30)
        self.assertEqual(view["formal_question"]["status"], "pending")
        self.assertEqual(view["suggested_priority_target"], 30)
        self.assertEqual(
            view["intake_report"]["scope"]["priority_reading_target"]["status"],
            "pending",
        )
        self.assertIsNone(view["settings"])
        with self.assertRaises(ValueError):
            validate_brief(view["brief"], require_confirmed=True)
        with self.assertRaises(SessionApiError):
            self.service.compile("alice-token", view["project_ref"], compile_body(view))
        self.assertEqual(
            self.service.history("alice-token", view["project_ref"])["actions"][-1][
                "status"
            ],
            "failed",
        )

    def test_reopen_replay_and_get_never_produce_or_recompile(self):
        view = self.confirmed()
        ref, body = view["project_ref"], compile_body(view)
        result = self.service.compile("alice-token", ref, body)
        snapshot = sorted(
            str(path.relative_to(self.root)) for path in self.root.rglob("*.json")
        )
        self.service.close()
        self.service = ProjectIntakeService(self.root, authenticate=authenticate)
        with (
            patch(
                "research_workspace_native.project_intake.compile_confirmed",
                side_effect=AssertionError("recompiled"),
            ),
            patch(
                "research_workspace_native.project_intake.create_brief",
                side_effect=AssertionError("rewritten"),
            ),
        ):
            replay = self.service.compile("alice-token", ref, {**body, "revision": 999})
            self.assertTrue(replay["replayed"])
            self.assertEqual(
                replay["plan_manifest_sha256"], result["plan_manifest_sha256"]
            )
            self.service.read("alice-token", ref)
            self.service.list("alice-token")
            self.service.history("alice-token", ref)
        self.assertEqual(
            snapshot,
            sorted(
                str(path.relative_to(self.root)) for path in self.root.rglob("*.json")
            ),
        )

    def test_two_handles_duplicate_same_key_create_one_project(self):
        other = ProjectIntakeService(self.root, authenticate=authenticate)
        try:
            first = self.service.create("alice-token", create_body())
            with patch(
                "research_workspace_native.project_intake.create_brief",
                side_effect=AssertionError("duplicate producer"),
            ):
                second = other.create("alice-token", create_body())
            self.assertEqual(first["project_ref"], second["project_ref"])
            recovered = other.action("alice-token", "create")
            self.assertEqual(recovered["project_ref"], first["project_ref"])
            self.assertTrue(recovered["replayed"])
            self.assertEqual(len(other.list("alice-token")), 1)
            with self.assertRaisesRegex(SessionApiError, "idempotency-payload-differs"):
                other.create("alice-token", {**create_body(), "topic": "Changed topic"})
        finally:
            other.close()

    def test_draft_resources_do_not_confirm_topic_or_authorize_io(self):
        view = self.new()
        body = submit_body(view)
        body = {
            key: value
            for key, value in body.items()
            if key not in {"choices", "formal_target", "priority_reading_target"}
        }
        body["key"] = "draft-resources"
        body["budgets"]["model_calls"] = 2
        self.service.configure("alice-token", view["project_ref"], body)
        draft = self.service.read("alice-token", view["project_ref"])
        self.assertEqual(draft["formal_question"]["status"], "pending")
        self.assertEqual(
            draft["intake_report"]["scope"]["geography"]["status"], "pending"
        )
        self.assertEqual(draft["settings"]["budgets"]["model_calls"], 2)
        self.assertFalse(draft["settings"]["execution_authorized"])
        self.assertFalse(draft["stage1_intake_ready"])
        with self.assertRaises(ValueError):
            self.service.brief_binding(view["project_ref"], require_confirmed=True)

    def test_shared_reservation_failure_rolls_back_budget_and_intent(self):
        view = self.new()
        body = bound_body(view, "reserve")

        def refuse(state, _, __):
            state["test_budget"] = 1
            raise SessionApiError("budget-refused")

        with self.assertRaisesRegex(SessionApiError, "budget-refused"):
            self.service._perform(
                "alice",
                view["project_ref"],
                "test",
                body,
                lambda *_: self.fail("unexpected work"),
                reserve=refuse,
            )
        self.assertNotIn(
            "test_budget", self.service._load("alice", view["project_ref"])
        )
        self.assertEqual(
            self.service.read("alice-token", view["project_ref"])["revision"],
            view["revision"],
        )
        with self.assertRaises(SessionApiError):
            self.service.action(
                "alice-token", "reserve", project_ref=view["project_ref"]
            )

    def test_source_revision_and_cross_project_mismatches_reject_before_producer(self):
        first = self.new(key="one")
        second = self.new("Coral reef disease surveillance", key="two")
        body = submit_body(first)
        with patch(
            "research_workspace_native.project_intake.create_brief",
            side_effect=AssertionError("unexpected producer"),
        ):
            for ref, change in (
                (first["project_ref"], {"revision": 99}),
                (first["project_ref"], {"input_version": 2}),
                (first["project_ref"], {"brief_sha256": "0" * 64}),
                (second["project_ref"], {}),
            ):
                with (
                    self.subTest(ref=ref, change=change),
                    self.assertRaises(SessionApiError),
                ):
                    self.service.submit("alice-token", ref, {**body, **change})
        self.assertEqual(
            len(self.service.history("alice-token", first["project_ref"])["actions"]), 1
        )

    def test_authentication_and_client_owned_runtime_fields_rejected(self):
        view = self.new()
        for credential in ("bob-token", None, "wrong"):
            with (
                self.subTest(credential=credential),
                self.assertRaises(SessionApiError),
            ):
                self.service.read(credential, view["project_ref"])
        for field in ("root", "owner", "epoch", "thread", "rpc", "permit", "principal"):
            with self.subTest(field=field), self.assertRaises(SessionApiError):
                self.service.create("alice-token", {**create_body(), field: "caller"})
        self.assertEqual(self.service.list("bob-token"), [])

    def test_new_input_version_preserves_old_bytes_and_requires_new_answers(self):
        view = self.confirmed()
        ref = view["project_ref"]
        self.service.compile("alice-token", ref, compile_body(view))
        view = self.service.read("alice-token", ref)
        bound = self.service.binding(ref)
        old = bound["brief_path"].read_bytes()
        old_path = bound["brief_path"]
        revision = {
            **bound_body(view, "revise"),
            "topic": "Coral reef disease surveillance",
        }
        self.service.revise("alice-token", ref, revision)
        fresh = self.service.read("alice-token", ref)
        self.assertEqual(fresh["input_version"], 2)
        self.assertEqual(old_path.read_bytes(), old)
        self.assertEqual(fresh["formal_question"]["status"], "pending")
        self.assertIsNone(fresh["settings"])
        self.assertIsNone(fresh["plan"])
        self.assertFalse(fresh["stage1_intake_ready"])
        self.assertEqual(
            [
                row["input_version"]
                for row in self.service.history("alice-token", ref)["versions"]
            ],
            [1, 1, 2],
        )
        with self.assertRaises(SessionApiError):
            self.service.submit("alice-token", ref, submit_body(view))

    def test_scope_settings_and_consents_do_not_create_execution_authority(self):
        view = self.new()
        body = submit_body(view)
        body["budgets"].update(
            model_calls=10, seconds=600, search_calls=20, source_reads=40, rounds=2
        )
        body["consent"].update(
            external_search=True, public_source_read=True, browser_fallback=True
        )
        self.service.submit("alice-token", view["project_ref"], body)
        output = self.service.read("alice-token", view["project_ref"])
        self.assertFalse(output["execution_authorized"])
        self.assertFalse(output["settings"]["execution_authorized"])
        self.assertEqual(
            output["later_stages"],
            {str(i): {"status": "planned", "connected": False} for i in range(3, 7)},
        )

    def test_plan_wrong_topic_and_hidden_scope_narrowing_are_retained_failures(self):
        view = self.confirmed()
        for key, mutation in (("wrong-topic", "topic"), ("wrong-scope", "scope")):
            body = compile_body(self.service.read("alice-token", view["project_ref"]))
            body["key"] = key
            if mutation == "topic":
                body["request"]["proposal"]["topic"] = "Unrelated research"
            else:
                body["request"]["query_bindings"][0]["scope_filters"] = {
                    "geography": "United States"
                }
            with self.assertRaises(SessionApiError):
                self.service.compile("alice-token", view["project_ref"], body)
        history = self.service.history("alice-token", view["project_ref"])
        self.assertEqual(
            [row["status"] for row in history["actions"]][-2:], ["failed", "failed"]
        )
        self.assertIsNone(self.service.read("alice-token", view["project_ref"])["plan"])

    def test_formal_and_priority_counts_never_narrow_search_queries(self):
        view = self.confirmed()
        body = compile_body(view)
        body["request"]["query_bindings"][0]["scope_filters"] = {
            "priority_reading_target": "20"
        }
        with self.assertRaises(SessionApiError) as error:
            self.service.compile("alice-token", view["project_ref"], body)
        self.assertIn(
            "intake-count-is-not-query-filter", error.exception.receipt["error"]
        )

    def test_unknown_durable_intent_replays_without_io_after_reopen(self):
        view = self.new()
        ref = view["project_ref"]
        body = submit_body(view)
        semantic = {key: value for key, value in body.items() if key != "revision"}
        from stage1_deliverable.common import sha

        request_hash = sha(canonical({"kind": "submit", "body": semantic}))
        receipt = {
            "project_ref": ref,
            "key": body["key"],
            "kind": "submit",
            "request_sha256": request_hash,
            "status": "intent-recorded",
            "recorded_at": "2026-10-10T00:00:00Z",
        }
        self.service.db.execute(
            "INSERT INTO intake_actions VALUES(?,?,?,?,?)",
            ("alice", ref, body["key"], request_hash, canonical(receipt).decode()),
        )
        self.service.close()
        self.service = ProjectIntakeService(self.root, authenticate=authenticate)
        with patch(
            "research_workspace_native.project_intake.create_brief",
            side_effect=AssertionError("resend"),
        ):
            replay = self.service.submit("alice-token", ref, body)
        self.assertEqual(replay["status"], "execution-unknown")
        self.assertTrue(replay["replayed"])
        self.assertIsNone(self.service.read("alice-token", ref)["settings"])

    def test_expired_mutation_does_not_reserve_or_produce(self):
        def expired():
            raise TimeoutError("deadline")

        with (
            patch(
                "research_workspace_native.project_intake.create_brief",
                side_effect=AssertionError("expired producer"),
            ),
            self.assertRaises(TimeoutError),
        ):
            self.service.create("alice-token", create_body(), check_deadline=expired)
        self.assertEqual(self.service.list("alice-token"), [])

    def test_exact_stale_refusal_survives_reopen_and_never_executes(self):
        view = self.new()
        ref = view["project_ref"]
        body = {**submit_body(view), "revision": 999}
        with self.assertRaisesRegex(SessionApiError, "stale-revision") as error:
            self.service.submit("alice-token", ref, body)
        receipt = self.service.record_refusal(
            "alice-token", body["key"], ref, "submit", body, error.exception.code
        )
        self.assertEqual(receipt["status"], "known-unsent")
        self.assertEqual(receipt["project_ref"], ref)
        self.assertEqual(receipt["kind"], "submit")
        self.assertFalse(receipt["execution_authorized"])
        self.service.close()
        self.service = ProjectIntakeService(self.root, authenticate=authenticate)
        with patch(
            "research_workspace_native.project_intake.create_brief",
            side_effect=AssertionError("refused intent re-executed"),
        ):
            replay = self.service.submit(
                "alice-token", ref, {**body, "revision": view["revision"]}
            )
        self.assertEqual(replay["status"], "known-unsent")
        self.assertTrue(replay["replayed"])
        self.assertEqual(replay["request_sha256"], receipt["request_sha256"])
        with self.assertRaisesRegex(SessionApiError, "idempotency-payload-differs"):
            self.service.submit("alice-token", ref, {**body, "formal_target": 31})
        retained = self.service.record_refusal(
            "alice-token",
            body["key"],
            ref,
            "submit",
            {**body, "formal_target": 31},
            "idempotency-payload-differs",
        )
        self.assertEqual(retained["status"], "known-unsent")
        self.assertEqual(retained["request_sha256"], receipt["request_sha256"])
        self.assertIsNone(self.service.read("alice-token", ref)["settings"])

    def test_refusal_never_overwrites_saved_failed_or_unknown_intents(self):
        view = self.new()
        ref = view["project_ref"]
        body = submit_body(view)
        original = self.service.submit("alice-token", ref, body)
        changed = {**body, "formal_target": 31}
        with self.assertRaisesRegex(SessionApiError, "idempotency-payload-differs"):
            self.service.submit("alice-token", ref, changed)
        returned = self.service.record_refusal(
            "alice-token",
            body["key"],
            ref,
            "submit",
            changed,
            "idempotency-payload-differs",
        )
        self.assertEqual(returned["status"], "saved")
        self.assertEqual(returned["request_sha256"], original["request_sha256"])
        self.assertEqual(returned["brief_sha256"], original["brief_sha256"])
        self.assertEqual(len(self.service.history("alice-token", ref)["actions"]), 2)

        bad = compile_body(self.service.read("alice-token", ref))
        bad["request"]["proposal"]["topic"] = "Unrelated topic"
        with self.assertRaises(SessionApiError) as error:
            self.service.compile("alice-token", ref, bad)
        failed = error.exception.receipt
        returned = self.service.record_refusal(
            "alice-token", bad["key"], ref, "compile", bad, error.exception.code
        )
        self.assertEqual(returned["status"], "failed")
        self.assertEqual(returned["error"], failed["error"])
        self.assertEqual(returned["request_sha256"], failed["request_sha256"])

    def test_invalid_or_unauthorized_refusal_cannot_create_unlock_evidence(self):
        view = self.new()
        ref = view["project_ref"]
        body = submit_body(view)
        for modified in (
            {**body, "owner": "caller"},
            {**body, "key": "wrong"},
            {**body, "brief_sha256": "broken"},
            {**body, "revision": True},
        ):
            self.assertIsNone(
                self.service.record_refusal(
                    "alice-token",
                    body["key"],
                    ref,
                    "submit",
                    modified,
                    "stale-revision",
                )
            )
        with self.assertRaises(SessionApiError):
            self.service.record_refusal(
                "bob-token", body["key"], ref, "submit", body, "stale-revision"
            )
        self.assertEqual(len(self.service.history("alice-token", ref)["actions"]), 1)
        with self.assertRaises(SessionApiError):
            self.service.action("alice-token", body["key"], project_ref=ref)

    def test_post_work_deadline_keeps_output_unknown_and_does_not_reproduce(self):
        calls = []

        def deadline():
            calls.append(1)
            if len(calls) == 3:
                raise TimeoutError("expired after output")

        body = create_body()
        with self.assertRaises(SessionApiError) as error:
            self.service.create("alice-token", body, check_deadline=deadline)
        receipt = error.exception.receipt
        self.assertEqual(receipt["status"], "execution-unknown")
        self.assertEqual(receipt["failure_phase"], "post-work-before-commit")
        self.assertIn("brief_sha256", receipt["output_observation"])
        self.assertEqual(len(list(self.root.rglob("brief-*.json"))), 1)
        returned = self.service.record_refusal(
            "alice-token", body["key"], None, "create", body, error.exception.code
        )
        self.assertEqual(returned["status"], "execution-unknown")
        self.service.close()
        self.service = ProjectIntakeService(self.root, authenticate=authenticate)
        with patch(
            "research_workspace_native.project_intake.create_brief",
            side_effect=AssertionError("uncertain output re-created"),
        ):
            replay = self.service.create("alice-token", body)
        self.assertEqual(replay["status"], "execution-unknown")
        self.assertEqual(replay["output_observation"], receipt["output_observation"])
        self.assertEqual(len(list(self.root.rglob("brief-*.json"))), 1)

    def test_extension_pre_intent_refusals_bind_operation_and_survive_reopen(self):
        view = self.new()
        ref = view["project_ref"]
        shapes = {
            "model-authorization": dict(
                operation="plan-search",
                user_input="Authorize one source-bound content planning unit.",
                confirmed=True,
            ),
            "stage1-initialize": dict(
                offer_ref="stage1-init-ref", offer_sha256="1" * 64, confirmed=True
            ),
            "stage1-plan-query": dict(
                ledger_state_sha256="2" * 64,
                query_ref="query-ref",
                query_sha256="3" * 64,
                confirmed=True,
            ),
            "stage1-execute-query": dict(
                ledger_state_sha256="2" * 64,
                query_ref="query-ref",
                query_sha256="3" * 64,
                confirmed=True,
            ),
            "stage1-checkpoint": dict(ledger_state_sha256="2" * 64, confirmed=True),
            "stage1-export": dict(ledger_state_sha256="2" * 64, confirmed=True),
        }
        expected = {}
        for kind, extra in shapes.items():
            body = dict(bound_body(view, kind), **extra, revision=999)
            with self.assertRaisesRegex(SessionApiError, "stale-revision") as failure:
                self.service._perform(
                    "alice",
                    ref,
                    kind,
                    body,
                    lambda *_: self.fail("refused extension dispatched"),
                )
            receipt = self.service.record_refusal(
                "alice-token", kind, ref, kind, body, failure.exception.code
            )
            self.assertEqual(receipt["status"], "known-unsent")
            self.assertEqual(receipt["kind"], kind)
            self.assertEqual(receipt["project_ref"], ref)
            expected[kind] = receipt["request_sha256"]
            self.assertIsNone(
                self.service.record_refusal(
                    "alice-token",
                    kind,
                    ref,
                    kind,
                    {**body, "permit": "caller"},
                    "refused",
                )
            )
        self.service.close()
        self.service = ProjectIntakeService(self.root, authenticate=authenticate)
        for kind, digest in expected.items():
            recovered = self.service.action("alice-token", kind, project_ref=ref)
            self.assertEqual(recovered["status"], "known-unsent")
            self.assertEqual(recovered["request_sha256"], digest)

    def test_saved_source_tamper_is_not_accepted_as_current_binding(self):
        view = self.confirmed()
        bound = self.service.brief_binding(view["project_ref"], require_confirmed=True)
        value = json.loads(bound["brief_path"].read_bytes())
        value["original_description"] = "Tampered topic"
        bound["brief_path"].write_bytes(canonical(value) + b"\n")
        with self.assertRaisesRegex(SessionApiError, "intake-source-bytes-differ"):
            self.service.read("alice-token", view["project_ref"])

    def test_one_broken_project_does_not_hide_other_projects(self):
        broken = self.new(key="broken")
        healthy = self.new("Coral reef disease surveillance", key="healthy")
        source = self.service.brief_binding(broken["project_ref"])["brief_path"]
        source.unlink()
        summaries = {
            row["project_ref"]: row for row in self.service.list("alice-token")
        }
        self.assertEqual(
            summaries[broken["project_ref"]]["status"], "source-binding-failed"
        )
        self.assertEqual(
            summaries[healthy["project_ref"]]["topic"],
            "Coral reef disease surveillance",
        )
        self.assertFalse(summaries[broken["project_ref"]]["stage1_intake_ready"])


if __name__ == "__main__":
    unittest.main()
