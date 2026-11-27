"""Wiki Stage 1 run-grant creation: real intake and HTTP, stub dispatch, no model or search."""

# ruff: noqa: E402 -- the plugin and Wiki use repository-local imports.
from datetime import datetime, timedelta, timezone
import hashlib
import http.client
import json
from pathlib import Path
import sys
import tempfile
from threading import Thread
from types import SimpleNamespace
import unittest

PLUGIN = Path(__file__).resolve().parents[1] / "plugins" / "auto-research-agent"
sys.path[:0] = [str(PLUGIN / name) for name in ("cli", "tests")]

from research_workspace_native.http import token_authenticator
from research_workspace_native.project_host import ProjectHost
from research_workspace_native.project_intake import ProjectIntakeService
from research_workspace_native.project_stage1_run_grant import (
    ProjectStage1RunGrantService,
)
from stage1_deliverable.common import canonical, sha
from test_workspace_project_intake import compile_body, submit_body
from wiki_project_progression_http import install_project_progression
from wiki_stage1_run_grant_http import install_stage1_run_grant


TOKEN = "wiki-local-run-grant-fixture-token-000001"
RUNTIME = "b" * 64
LIMITS = dict(model_calls=5, seconds=600, search_calls=5, source_reads=5, rounds=5)
ZERO = dict(model_calls=0, seconds=0, search_calls=0, source_reads=0, rounds=0)
BUDGETS = dict(model_calls=3, seconds=120, search_calls=3, source_reads=4, rounds=2)
WORDS = "  我授权这一轮：只在这些上限内跑 Stage 1，到了就停。 "
OPERATIONS = ["query", "source", "analyze-full-paper", "records", "delivery"]


class Fixture:
    def build(self, *, limits=LIMITS, budgets=BUDGETS, trusted=True, consent=True):
        path = self.enterContext(tempfile.TemporaryDirectory(prefix="rg-"))
        self.root = Path(path).resolve()
        self.now = [1000.0]
        self.dispatched = []
        self.intake = ProjectIntakeService(
            self.root / "p", authenticate=token_authenticator({TOKEN: "local-viewer"})
        )
        self.addCleanup(self.intake.close)
        self.host = ProjectHost(
            projects=self.intake, credential=TOKEN, files={}, views=[], port=0
        )
        self.issuer = ProjectStage1RunGrantService(
            self.intake, runtime_sha256=RUNTIME, clock=lambda: self.now[0]
        )
        if trusted:
            self.host.project_models = SimpleNamespace(run_grants=self.issuer)
        self.limits = limits
        self.host.project_stage1_delivery = SimpleNamespace(
            read=lambda _credential, _ref: {"canonical_package": None}
        )
        self.ref = self.prepare("scope", "Urban flash flood forecasting", budgets)
        self.consent = {}
        install_project_progression(
            self.host,
            read_consent=lambda _, ref: self.consent.get(ref),
            limits=limits,
            runtime_sha256=RUNTIME,
            dispatch=lambda *args, **kwargs: self.dispatched.append((args, kwargs)),
        )
        install_stage1_run_grant(self.host, limits=limits, runtime_sha256=RUNTIME)
        if consent:
            self.write_consent()
        thread = Thread(target=self.host.serve_forever, kwargs=dict(poll_interval=0.05))
        thread.start()

        def stop():
            self.host.shutdown()
            thread.join(10)
            self.host.server_close()

        self.addCleanup(stop)

    def prepare(self, key, topic, budgets):
        ref = self.intake.create(TOKEN, {"key": key, "topic": topic})["project_ref"]
        view = self.intake.read(TOKEN, ref)
        body = submit_body(view)
        body["budgets"].update(budgets)
        spend = any(budgets.values())
        body["consent"].update(external_search=spend, public_source_read=spend)
        self.intake.submit(TOKEN, ref, body)
        self.intake.compile(TOKEN, ref, compile_body(self.intake.read(TOKEN, ref)))
        return ref

    def write_consent(self):
        project = self.intake.read(TOKEN, self.ref)
        value = {
            "kind": "ProjectStageProgressionConsent",
            "schema_version": "1.0.0",
            "confirmed": True,
            "expires_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
            **{
                k: project[k]
                for k in ("project_ref", "project_id", "input_version", "brief_sha256")
            },
            "settings_sha256": sha(canonical(project["settings"])),
            "stages": {"stage1": {"profile_sha256": RUNTIME, "max_dispatches": 1}},
        }
        raw = canonical(value)
        self.consent[self.ref] = (raw, sha(raw))

    def call(self, method, path, body=None):
        connection = http.client.HTTPConnection(
            "127.0.0.1", self.host.server_address[1], timeout=20
        )
        headers = {
            "Authorization": "Bearer " + TOKEN,
            "Origin": self.host.expected_origin,
        }
        raw = None
        if body is not None:
            raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        try:
            connection.request(method, path, raw, headers)
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()

    def url(self, ref=None, tail="stage1-run-grant"):
        return "/api/projects/" + (ref or self.ref) + "/" + tail

    def payload(self, ref=None, **changes):
        project = self.intake.read(TOKEN, ref or self.ref)
        return {
            "key": "run-grant-1",
            "input_version": project["input_version"],
            "brief_sha256": project["brief_sha256"],
            "plan_manifest_sha256": project["plan"]["manifest_sha256"],
            "user_input": WORDS,
            "confirmed": True,
            "operations": OPERATIONS,
            "max_seconds": 100,
            "max_actions": 4,
            **changes,
        }

    def create(self, **changes):
        return self.call("POST", self.url(), self.payload(**changes))

    def state(self):
        """Every durable byte the intake owns: rows, events, actions and lease files."""
        digest = hashlib.sha256()
        # The -shm file is SQLite's volatile wal-index: any read touches it.
        for name in sorted(
            p
            for p in self.root.rglob("*")
            if p.is_file() and not p.name.endswith("-shm")
        ):
            digest.update(name.name.encode())
            digest.update(name.read_bytes())
        rows = (
            self.intake.db.execute("SELECT COUNT(*) FROM intake_actions").fetchone()[0],
            self.intake.db.execute("SELECT COUNT(*) FROM intake_events").fetchone()[0],
        )
        return rows, digest.hexdigest(), len(self.dispatched)

    def refuse(self, status, code, *, recorded=False, **changes):
        before = self.state()
        got_status, body = self.create(**changes)
        self.assertEqual((got_status, body.get("error")), (status, code), body)
        self.assertTrue(body["reason"])
        if recorded:
            # A refusal inside the existing service keeps one failed record, never a grant.
            self.assertTrue(body["recorded_as_failed"])
            self.assertEqual(self.state()[0][0], before[0][0] + 1)
            state = self.intake._load("local-viewer", self.ref)
            self.assertNotIn("stage1_run_grants", state)
            self.assertFalse(list(self.root.rglob("stage1-run-lease-*")))
        else:
            self.assertNotIn("recorded_as_failed", body)
            self.assertEqual(self.state(), before)


class RunGrantHttpTests(Fixture, unittest.TestCase):
    def test_zero_launch_limits_always_409_without_any_write(self):
        self.build(limits=ZERO, budgets=ZERO, consent=False)
        for changes in ({}, {"user_input": ""}, {"confirmed": False}):
            self.refuse(409, "stage1-run-grant-zero-limits", **changes)
        before = self.state()
        status, body = self.call("POST", self.url(), {"anything": 1})
        self.assertEqual((status, body["error"]), (409, "stage1-run-grant-zero-limits"))
        self.assertEqual(self.state(), before)

    def test_seconds_zero_alone_also_blocks(self):
        self.build(limits=dict(LIMITS, seconds=0))
        self.refuse(409, "stage1-run-grant-zero-limits")

    def test_researcher_words_and_explicit_confirmation_are_both_required(self):
        self.build()
        base = self.payload()
        for name in ("user_input",):
            body = {k: v for k, v in base.items() if k != name}
            before = self.state()
            status, answer = self.call("POST", self.url(), body)
            self.assertEqual(
                (status, answer["error"]), (400, "stage1-run-user-words-required")
            )
            self.assertEqual(self.state(), before)
        for changes, code in (
            ({"user_input": ""}, "stage1-run-user-words-required"),
            ({"user_input": "   \n"}, "stage1-run-user-words-required"),
            ({"user_input": 7}, "stage1-run-user-words-required"),
            ({"confirmed": False}, "stage1-run-confirmation-required"),
            ({"confirmed": "true"}, "stage1-run-confirmation-required"),
            ({"confirmed": 1}, "stage1-run-confirmation-required"),
        ):
            with self.subTest(changes=changes):
                self.refuse(400, code, **changes)
        missing = {k: v for k, v in base.items() if k != "confirmed"}
        status, answer = self.call("POST", self.url(), missing)
        self.assertEqual(
            (status, answer["error"]), (400, "stage1-run-confirmation-required")
        )

    def test_no_shortcut_fields_and_every_field_is_typed(self):
        self.build()
        for extra in (
            {"scope": "stage2-research"},
            {"unlimited": True},
            {"max_history_actions": 2048},
            {"project_ref": "other"},
            {"revision": 0},
            {"budgets": LIMITS},
        ):
            with self.subTest(extra=extra):
                self.refuse(400, "stage1-run-grant-fields-invalid", **extra)
        for changes in (
            {"input_version": True},
            {"input_version": "1"},
            {"input_version": 0},
            {"brief_sha256": "abc"},
            {"plan_manifest_sha256": None},
            {"max_seconds": 1.5},
            {"max_actions": True},
        ):
            with self.subTest(changes=changes):
                self.refuse(400, "stage1-run-grant-fields-invalid", **changes)

    def test_words_are_stored_verbatim_in_the_grant_record(self):
        self.build()
        status, body = self.create()
        self.assertEqual(status, 201, body)
        document = self.issuer.inspect(
            TOKEN, self.ref, body["grant_ref"], body["grant_sha256"]
        )
        self.assertEqual(document["user_input"], WORDS)
        self.assertEqual(document["authority"], "user")
        self.assertEqual(document["provenance"], "explicit-user-run-consent")
        self.assertEqual(document["max_actions"], 4)
        self.assertFalse(body["execution_authorized"])
        self.assertFalse(body["creates_lane_permits"])

    def test_limits_above_the_launch_ceiling_are_refused(self):
        self.build()
        self.refuse(409, "stage1-run-grant-over-launch-limits", max_seconds=601)
        # The project's own saved seconds still bound the grant (existing check).
        self.refuse(409, "stage1-run-budget-exceeded", max_seconds=121)
        self.refuse(400, "stage1-run-limits-invalid", max_actions=513)

    def test_project_budgets_above_launch_limits_are_refused(self):
        self.build(limits=dict(LIMITS, model_calls=1))
        self.refuse(409, "stage1-run-grant-over-launch-limits")

    def test_lanes_without_saved_consent_or_budget_are_refused(self):
        self.build(budgets=dict(BUDGETS, search_calls=0))
        self.refuse(
            409, "stage1-run-lane-not-consented"
        )  # no failed record, no revision
        status, _ = self.create(key="run-grant-2", operations=["records", "delivery"])
        self.assertEqual(status, 201)

    def test_missing_consent_flag_is_refused_without_a_record(self):
        self.build(budgets=dict(BUDGETS, model_calls=0))
        revision = self.intake.read(TOKEN, self.ref)["revision"]
        self.refuse(
            409, "stage1-run-lane-not-consented", operations=["analyze-full-paper"]
        )
        self.assertEqual(self.intake.read(TOKEN, self.ref)["revision"], revision)

    def test_project_version_scope_and_plan_must_match_the_saved_state(self):
        self.build()
        other = self.prepare("other", "Aircraft fault diagnosis", BUDGETS)
        self.refuse(409, "stage1-run-grant-project-differs", input_version=2)
        self.refuse(409, "stage1-run-grant-project-differs", brief_sha256="c" * 64)
        self.refuse(409, "stage1-run-grant-plan-differs", plan_manifest_sha256="d" * 64)
        before = self.state()
        status, body = self.call("POST", self.url(other), self.payload(self.ref))
        self.assertEqual(status, 409, body)
        self.assertIn(
            body["error"],
            ("stage1-run-grant-project-differs", "stage1-run-grant-plan-differs"),
        )
        status, body = self.call("POST", self.url("project-nope"), self.payload())
        self.assertEqual((status, body["error"]), (404, "project-unavailable"))
        self.assertEqual(self.state(), before)

    def test_unconfirmed_scope_cannot_get_a_grant(self):
        self.build()
        ref = self.intake.create(TOKEN, {"key": "bare", "topic": "Bare topic only"})[
            "project_ref"
        ]
        before = self.state()
        status, body = self.call("POST", self.url(ref), self.payload())
        self.assertEqual(
            (status, body["error"]), (409, "stage1-run-grant-scope-not-ready")
        )
        self.assertEqual(self.state(), before)

    def test_same_key_replays_the_original_without_creating_another(self):
        self.build()
        status, first = self.create()
        self.assertEqual(status, 201)
        after = self.state()
        status, again = self.create()
        self.assertEqual(status, 200)
        self.assertTrue(again["replayed"])
        self.assertFalse(first["replayed"])
        for field in ("grant_ref", "grant_sha256", "expires_at"):
            self.assertEqual(again[field], first[field])
        self.assertEqual(self.state(), after)
        self.refuse(409, "idempotency-payload-differs", user_input="另一句话")
        self.assertEqual(self.state(), after)
        # A second key for the same version is refused read-only: no failed record,
        # no revision bump, no action slot used.
        self.refuse(409, "stage1-run-grant-renewal-refused", key="run-grant-2")
        self.refuse(409, "stage1-run-grant-renewal-refused", key="run-grant-2")
        self.assertEqual(self.state(), after)
        # A reload that changes the project does not turn a saved replay into a new grant.
        self.assertEqual(self.create()[1]["grant_ref"], first["grant_ref"])

    def test_an_unsafe_request_key_is_a_field_error_not_a_record_error(self):
        self.build()
        for key in ("../x", "", "a b", 5, None, "x" * 121):
            self.refuse(400, "stage1-run-grant-fields-invalid", key=key)

    def test_replaying_a_key_after_the_project_moved_on_is_not_a_success(self):
        self.build()
        original = self.payload()
        status, first = self.create()
        self.assertEqual(status, 201)
        self.assertTrue(first["current"])
        self.assertEqual(first["binding"]["input_version"], 1)
        project = self.intake.read(TOKEN, self.ref)
        self.intake.revise(
            TOKEN,
            self.ref,
            {
                "key": "revise-v2",
                "revision": project["revision"],
                "input_version": project["input_version"],
                "brief_sha256": project["brief_sha256"],
                "topic": "Urban flash flood forecasting, second round",
            },
        )
        before = self.state()
        status, body = self.call("POST", self.url(), original)
        self.assertEqual((status, body["error"]), (409, "stage1-run-grant-stale"))
        self.assertEqual(body["grant_ref"], first["grant_ref"])
        self.assertTrue(body["reason"])
        self.assertEqual(self.state(), before)  # a stale replay writes nothing

    def test_cross_site_and_headerless_posts_are_refused_without_a_write(self):
        self.build()
        before = self.state()
        base = {
            "Authorization": "Bearer " + TOKEN,
            "Origin": self.host.expected_origin,
            "Content-Type": "application/json",
        }
        raw = json.dumps(self.payload()).encode()
        cases = (
            ({"Origin": "http://evil.example"}, 403),
            ({"Origin": None}, 403),
            ({"Sec-Fetch-Site": "cross-site"}, 403),
            ({"Sec-Fetch-Site": "same-site"}, 403),
        )
        for changes, expected in cases:
            headers = {k: v for k, v in (base | changes).items() if v is not None}
            connection = http.client.HTTPConnection(
                "127.0.0.1", self.host.server_address[1], timeout=20
            )
            try:
                connection.request("POST", self.url(), raw, headers)
                self.assertEqual(connection.getresponse().status, expected, changes)
            finally:
                connection.close()
        self.assertEqual(self.state(), before)

    def test_concurrent_different_keys_make_exactly_one_grant(self):
        self.build()
        results = []

        def post(index):
            results.append(self.create(key="run-grant-c" + str(index))[0])

        threads = [Thread(target=post, args=(i,)) for i in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(30)
        self.assertEqual(results.count(201), 1, results)
        self.assertTrue(all(code in (201, 409) for code in results), results)
        state = self.intake._load("local-viewer", self.ref)
        self.assertEqual(len(state["stage1_run_grants"]), 1)

    def test_progression_needs_the_grant_then_reaches_the_submit_branch(self):
        self.build()
        project = self.intake.read(TOKEN, self.ref)
        advance = {
            "input_version": project["input_version"],
            "brief_sha256": project["brief_sha256"],
            "confirmed": True,
        }
        status, body = self.call("POST", self.url(tail="progression"), advance)
        self.assertEqual((status, body["error"]), (409, "stage1-run-grant-unavailable"))
        self.assertEqual(self.dispatched, [])
        status, grant = self.create()
        self.assertEqual(status, 201)
        status, body = self.call("POST", self.url(tail="progression"), advance)
        self.assertEqual(status, 200, body)
        ((args, kwargs),) = self.dispatched
        self.assertEqual(args[1], self.ref)
        self.assertEqual(kwargs["grant_ref"], grant["grant_ref"])
        self.assertEqual(kwargs["grant_sha256"], grant["grant_sha256"])
        self.assertEqual(kwargs["max_actions"], 4)
        self.assertIs(kwargs["run_grants"], self.issuer)
        self.assertLessEqual(kwargs["deadline"] - __import__("time").monotonic(), 100)
        # The stub saved nothing, so the route honestly reports an unknown outcome.
        self.assertEqual(body["status"], "execution-unknown")

    def test_an_expired_grant_cannot_be_used(self):
        self.build()
        self.create()
        self.now[0] += 101
        project = self.intake.read(TOKEN, self.ref)
        status, body = self.call(
            "POST",
            self.url(tail="progression"),
            {
                "input_version": project["input_version"],
                "brief_sha256": project["brief_sha256"],
                "confirmed": True,
            },
        )
        self.assertEqual((status, body["error"]), (409, "stage1-run-grant-expired"))
        self.assertEqual(self.dispatched, [])

    def test_a_host_without_whole_run_enabled_cannot_create_a_grant(self):
        self.build(trusted=False)
        self.refuse(409, "stage1-run-grant-not-enabled")

    def test_bad_requests_are_refused_before_the_store(self):
        self.build()
        before = self.state()
        connection = http.client.HTTPConnection(
            "127.0.0.1", self.host.server_address[1], timeout=20
        )
        try:
            base = {
                "Authorization": "Bearer " + TOKEN,
                "Origin": self.host.expected_origin,
            }
            connection.request("POST", self.url(), b"{}", dict(base))
            self.assertEqual(connection.getresponse().status, 415)
        finally:
            connection.close()
        connection = http.client.HTTPConnection(
            "127.0.0.1", self.host.server_address[1], timeout=20
        )
        try:
            connection.request(
                "POST",
                self.url(),
                b"{}",
                {
                    "Authorization": "Bearer wrong",
                    "Origin": self.host.expected_origin,
                    "Content-Type": "application/json",
                },
            )
            self.assertEqual(connection.getresponse().status, 401)
        finally:
            connection.close()
        self.assertEqual(self.state(), before)


if __name__ == "__main__":
    unittest.main()
