"""Real temporary HTTP/SQLite/Core calls with synthetic, never launched runtime."""

import atlas_test_paths  # noqa: F401

from copy import deepcopy
from contextlib import closing
import http.client
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from planned_query_fixture import QueryCase, get_source_proof, saved_pin
from research_workspace_native.project_host import ProjectHost
from research_workspace_native.project_intake import ProjectIntakeService
from research_workspace_native.project_stage1 import ProjectStage1Service
from research_workspace_native.project_stage1_queries import ProjectStage1QueryService
from stage1_coverage.run import CoverageLedger
from stage1_deliverable.common import canonical, sha
from stage1_ledger.validation import validate_run
from stage1_retrieval.runtime_identity import verify_identity
import stage1_retrieval.runner as runner
from test_workspace_project_intake import bound_body, compile_body, submit_body


DEFAULT = object()


class ProjectStage1QueryHttpTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="q-http-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.pin = saved_pin(self.root)
        self.token = "synthetic-http-query-token-at-least-32-characters"
        self.children, self.probes, self.traffic, self.observations = [], [], [], []
        self.host = self.host_worker = self.bridge = self.intake = None
        self.probe_patch = patch(
            "stage1_retrieval.runtime_identity.verify_identity",
            side_effect=self.pure_identity,
        )
        self.probe_patch.start()
        self.addCleanup(self.probe_patch.stop)
        self.addCleanup(self.close)
        self.addCleanup(self.save_trace)
        self.open()
        created = self.post(
            "/api/projects",
            {
                "key": "create",
                "topic": "Polyphonic music transcription with scarce annotations",
            },
        )
        self.ref = created["project_ref"]
        self.base = "/api/projects/" + self.ref
        view = self.get(self.base)
        confirmation = submit_body(view)
        confirmation["resource_envelope"] = (
            "Offline test: two sealed synthetic attempts, no source reads or model calls."
        )
        confirmation["budgets"].update(search_calls=2, seconds=100, rounds=1)
        confirmation["consent"]["external_search"] = True
        self.post(self.base + "/confirm", confirmation)
        self.post(self.base + "/compile", compile_body(self.get(self.base)))
        self.assertIs(type(self.get(self.base)["input_version"]), int)

    def authenticate(self, credential):
        return "local-viewer" if credential == self.token else None

    def open(self):
        self.intake = ProjectIntakeService(
            self.root / "projects", authenticate=self.authenticate
        )
        self.stage1 = ProjectStage1Service(self.intake, backends=["openalex"], limit=3)
        proof = get_source_proof()
        self.bridge = ProjectStage1QueryService(
            self.stage1,
            runtime_pin=deepcopy(self.pin),
            execution_source_root=proof["repo"],
            execution_source_sha256=sha(canonical(proof["files"])),
            verify_source=lambda _: get_source_proof(),
            admit=lambda _: True,
            caps=dict(
                max_attempts=2,
                max_reserved_seconds=100,
                max_results=3,
                validity_seconds=600,
            ),
            backends=["openalex"],
        )
        self.host = ProjectHost(
            projects=self.intake,
            credential=self.token,
            stage1=self.stage1,
            files={},
            views=[],
            port=0,
        )
        self.host_worker = threading.Thread(target=self.host.serve_forever, daemon=True)
        self.host_worker.start()

    def close(self):
        if self.host is not None:
            self.host.shutdown()
            self.host.server_close()
            self.host_worker.join(3)
            self.assertFalse(self.host_worker.is_alive())
            self.host = None
        if self.bridge is not None:
            self.bridge.close()
            self.bridge = None
        if self.intake is not None:
            self.intake.close()
            self.intake = None

    def save_trace(self):
        directory = os.environ.get("PROJECT_QUERY_HTTP_TRACE_DIR")
        if directory:
            path = Path(directory) / (self._testMethodName + ".http.json")
            path.write_bytes(
                canonical(
                    dict(
                        kind="offline-temporary-http-transcript",
                        test=self.id(),
                        account_credentials_used=False,
                        traffic=self.traffic,
                        before_io_observations=self.observations,
                    )
                )
                + b"\n"
            )

    def state_on_disk(self):
        with closing(
            sqlite3.connect(self.root / "projects/project-intake.sqlite")
        ) as db:
            raw = db.execute(
                "SELECT state FROM intake_projects WHERE ref=?", (self.ref,)
            ).fetchone()[0]
            actions = db.execute(
                "SELECT receipt FROM intake_actions WHERE project=? ORDER BY rowid",
                (self.ref,),
            ).fetchall()
        return json.loads(raw), [json.loads(row[0]) for row in actions]

    def pure_identity(self, pin, **options):
        if options.get("probe"):
            self.probes.append(deepcopy(options))
            state, actions = self.state_on_disk()
            job = next(iter(state["stage1_query_jobs"].values()))
            self.assertEqual(job["status"], "dispatching")
            self.assertEqual(
                state["stage1_query_budget"], dict(probes=1, attempts=0, seconds=30)
            )
            self.assertEqual(actions[-1]["status"], "saved")
            self.assertEqual(actions[-1]["kind"], "stage1-query-bootstrap")
            self.observations.append(
                dict(
                    phase="before-Core.create-probe",
                    job=deepcopy(job),
                    budget=deepcopy(state["stage1_query_budget"]),
                    action_status=actions[-1]["status"],
                )
            )
        return verify_identity(pin)

    def request(
        self, path, body=None, *, origin=DEFAULT, token=DEFAULT, discard_response=False
    ):
        client = http.client.HTTPConnection(
            "127.0.0.1", self.host.server_port, timeout=30
        )
        headers = {
            "Host": self.host.expected_host,
            "Authorization": "Bearer " + (self.token if token is DEFAULT else token),
        }
        if body is not None:
            headers.update(
                Origin=self.host.expected_origin if origin is DEFAULT else origin,
                **{"Content-Type": "application/json"},
            )
        raw = None if body is None else canonical(body)
        if raw is not None:
            headers["Content-Length"] = str(len(raw))
        entry = dict(
            method="GET" if body is None else "POST",
            path=path,
            headers=deepcopy(headers),
            body=deepcopy(body),
        )
        self.traffic.append(entry)
        try:
            client.request(entry["method"], path, raw, headers)
            response = client.getresponse()
            entry.update(
                response_status=response.status,
                response_headers=response.getheaders(),
                response_body_observed=not discard_response,
            )
            if discard_response:
                response.close()
                return response.status, None
            data = response.read()
            entry["response_body_sha256"] = sha(data)
            if response.getheader("Content-Type", "").startswith("application/json"):
                entry["response_body"] = json.loads(data)
            return response.status, data
        finally:
            client.close()

    def get(self, path):
        status, raw = self.request(path)
        self.assertEqual(status, 200, raw)
        return json.loads(raw)

    def post(self, path, body):
        status, raw = self.request(path, body)
        self.assertEqual(status, 200, raw)
        return json.loads(raw)

    def query_view(self):
        return self.get(self.base + "/stage1")["query_execution"]

    def offered(self, name, key):
        offer = self.query_view()[name]
        self.assertIsNotNone(offer, self.query_view())
        body = dict(
            bound_body(self.get(self.base), key),
            offer_ref=offer["offer_ref"],
            offer_sha256=offer["offer_sha256"],
            confirmed=True,
        )
        if name == "authorization_offer":
            body["user_input"] = (
                "Authorize only this saved plan: two bounded synthetic attempts, three results, no source reading or model execution."
            )
        return body

    def authorize(self):
        self.authorization_body = self.offered("authorization_offer", "authorize")
        return self.post(self.base + "/stage1/query-authorize", self.authorization_body)

    def bootstrap(self):
        self.authorize()
        self.bootstrap_body = self.offered("bootstrap_offer", "bootstrap")
        queued = self.post(self.base + "/stage1/query-bootstrap", self.bootstrap_body)
        self.assertEqual(queued["query_status"], "bootstrap-queued")
        self.bridge.workers[self.ref].join(30)
        self.assertFalse(self.bridge.workers[self.ref].is_alive())
        view = self.query_view()
        self.assertEqual(view["status"], "completed", view)
        self.assertEqual(len(self.probes), 1)
        return view

    def no_probe(self):
        return QueryCase.no_probe(self)

    def fake_runner(self, mode="rows"):
        return QueryCase.fake_runner(self, mode)

    def block_external(self):
        original = runner.subprocess

        def refused(*args, **kwargs):
            self.fail("unexpected external runner child")

        return patch.object(
            runner,
            "subprocess",
            SimpleNamespace(
                Popen=refused,
                DEVNULL=original.DEVNULL,
                TimeoutExpired=original.TimeoutExpired,
            ),
        )

    def wait_query(self, body):
        service = self.bridge.services[self.ref]
        service._workers[self.ref].join(30)
        self.assertFalse(service._workers[self.ref].is_alive())
        history = service.view(self.token, self.ref)["history"]
        return next(
            row
            for row in history
            if row.get("method") == "stage1/planned-query"
            and row["request"]["key"]
            == "project-"
            + self.intake.action(self.token, body["key"], project_ref=self.ref)[
                "request_sha256"
            ]
        )

    def test_constructors_get_and_served_buttons_have_zero_execution(self):
        with (
            patch(
                "stage1_retrieval.runner.verify_identity",
                side_effect=AssertionError("GET probe"),
            ),
            self.block_external(),
        ):
            for path in (
                self.base,
                self.base + "/overview",
                self.base + "/contract",
                self.base + "/history",
                self.base + "/stage1",
                self.base + "/stage1/offers",
            ):
                self.get(path)
            status, raw = self.request("/projects.html")
            self.assertEqual(status, 200, raw)
            for button in (
                "query-authorize",
                "query-bootstrap",
                "query-execute",
                "query-restore-owner",
            ):
                self.assertIn(('id="' + button + '"').encode(), raw)
            self.assertEqual(
                sha(raw), self.host.host_binding["served_files"]["/projects.html"]
            )
        state, actions = self.state_on_disk()
        self.assertNotIn("stage1_query_authorization", state)
        self.assertNotIn("stage1_query_jobs", state)
        self.assertEqual(len(actions), 2)
        self.assertEqual(self.probes, [])
        self.assertEqual(self.children, [])

    def test_strict_fields_origin_and_credentials_reject_without_reservation(self):
        body = self.offered("authorization_offer", "reject")
        before = self.state_on_disk()
        with self.no_probe(), self.fake_runner():
            for field, value in (
                ("ledger_root", str(self.root)),
                ("runtime_pin", self.pin),
                ("permit_path", str(self.root / "permit.json")),
                ("execution_source_root", str(self.root)),
                ("principal", "local-viewer"),
                ("caps", self.bridge.config["caps"]),
            ):
                status, raw = self.request(
                    self.base + "/stage1/query-authorize", {**body, field: value}
                )
                self.assertEqual(status, 400, raw)
            status, raw = self.request(
                self.base + "/stage1/query-authorize",
                body,
                origin="https://unrelated.example",
            )
            self.assertEqual(status, 403, raw)
            status, raw = self.request(
                self.base + "/stage1/query-authorize",
                body,
                token="wrong-synthetic-credential",
            )
            self.assertEqual(status, 401, raw)
        self.assertEqual(self.state_on_disk(), before)
        self.assertEqual(self.probes, [])
        self.assertEqual(self.children, [])

    def test_authorization_is_explicit_persisted_and_same_key_replays_after_reopen(
        self,
    ):
        initial = self.query_view()
        self.assertFalse(initial["execution_authorized"])
        self.assertEqual(
            initial["authorization_offer"]["document"]["limits"]["max_attempts"], 2
        )
        result = self.authorize()
        self.assertEqual(result["query_status"], "permission-saved-not-executed")
        state, actions = self.state_on_disk()
        authority = state["stage1_query_authorization"]
        permit = authority["permit"]
        raw = self.intake._path(self.ref, authority["path"]).read_bytes()
        self.assertEqual(sha(raw), result["permit_sha256"])
        self.assertEqual(json.loads(raw), permit)
        self.assertEqual(permit["user_input"], self.authorization_body["user_input"])
        self.assertIs(type(permit["binding"]["project_input_version"]), int)
        self.assertEqual(
            permit["binding"]["project_input_version"],
            self.get(self.base)["input_version"],
        )
        self.assertEqual(
            state["stage1_query_budget"], dict(probes=0, attempts=0, seconds=0)
        )
        self.assertEqual(actions[-1]["status"], "saved")
        self.close()
        self.open()
        replay = self.post(
            self.base + "/stage1/query-authorize", self.authorization_body
        )
        self.assertTrue(replay["replayed"])
        self.assertEqual(replay["permit_sha256"], result["permit_sha256"])
        self.assertEqual(self.probes, [])
        self.assertEqual(self.children, [])
        self.assertEqual(
            self.state_on_disk()[0]["stage1_query_budget"], state["stage1_query_budget"]
        )

    def test_bootstrap_commits_budget_and_dispatch_before_pure_probe(self):
        view = self.bootstrap()
        state, actions = self.state_on_disk()
        job = next(iter(state["stage1_query_jobs"].values()))
        self.assertEqual(job["status"], "completed")
        self.assertEqual(
            state["stage1_query_budget"], dict(probes=1, attempts=0, seconds=30)
        )
        registration = job["registration"]
        self.assertEqual(registration["registration_kind"], "project-intake")
        self.assertIs(type(registration["project_input_version"]), int)
        self.assertEqual(
            registration["input_version"], self.get(self.base)["brief_sha256"]
        )
        self.assertEqual(
            registration["input_version"], view["query_history"]["input_version"]
        )
        for name in ("ledger_root", "parent_ledger_root"):
            self.assertTrue(validate_run(registration[name])["valid"])
        self.assertEqual(
            self.get(self.base + "/stage1")["ledger"]["source_mode"], "research-hub-cli"
        )
        self.assertEqual(len(self.observations), 1)
        self.assertEqual(self.children, [])
        self.assertEqual(actions[-1]["status"], "saved")
        before = self.state_on_disk()
        replay = self.post(self.base + "/stage1/query-bootstrap", self.bootstrap_body)
        self.assertTrue(replay["replayed"])
        self.assertEqual(self.state_on_disk(), before)
        self.assertEqual(len(self.probes), 1)

    def test_execute_real_runner_imports_actual_core_bytes_after_durable_reservation(
        self,
    ):
        self.bootstrap()
        body = self.offered("query_offer", "execute")
        service = self.bridge.services[self.ref]
        original_admit = self.bridge.admit

        def admitted(event):
            state, actions = self.state_on_disk()
            self.assertEqual(
                state["stage1_query_budget"], dict(probes=1, attempts=1, seconds=62)
            )
            if event["phase"] != "before-bootstrap-probe":
                query_history = service.view(self.token, self.ref)
                self.assertEqual(query_history["budget"], dict(attempts=1, seconds=32))
                self.assertEqual(query_history["history"][-1]["status"], "dispatching")
                with closing(sqlite3.connect(service.store.path)) as db:
                    query_disk = json.loads(
                        db.execute(
                            "SELECT state FROM projects WHERE id=?",
                            (service._projects[self.ref]["pid"],),
                        ).fetchone()[0]
                    )
                self.assertEqual(
                    query_disk["query_budget"], dict(attempts=1, seconds=32)
                )
                self.assertEqual(
                    next(iter(query_disk["intents"].values()))["status"], "dispatching"
                )
                self.observations.append(
                    dict(
                        phase="before-real-runner-or-fake-Popen",
                        project_budget=deepcopy(state["stage1_query_budget"]),
                        query_budget=query_history["budget"],
                        query_status=query_history["history"][-1]["status"],
                        action_status=actions[-1]["status"],
                        query_sqlite_status="dispatching",
                    )
                )
            return original_admit(event)

        self.bridge.admit = admitted
        with self.no_probe(), self.fake_runner():
            queued = self.post(self.base + "/stage1/query-execute", body)
            row = self.wait_query(body)
        self.assertEqual(queued["query_status"], "dispatch-unobserved")
        self.assertEqual(row["status"], "completed", row)
        self.assertEqual(row["outcome"], "observed")
        self.assertEqual(row["result"]["backend_outcome"], "success_nonempty")
        self.assertEqual(len(self.children), 1)
        self.assertGreaterEqual(len(self.observations), 3)
        root = service._projects[self.ref]["item"]["ledger_root"]
        ledger = CoverageLedger(root)
        report = validate_run(root)
        self.assertTrue(report["valid"], report)
        self.assertEqual(len(ledger.candidates()), 1)
        finished = ledger.event(row["result"]["backend_result_id"], "ActionFinished")
        self.assertEqual(finished["execution_ref"], row["result"]["execution_ref"])
        self.assertIsNotNone(finished["execution_ref"])
        self.assertTrue((Path(root) / finished["execution_ref"]["path"]).is_file())
        self.assertFalse(self.get(self.base + "/stage1")["stage1_complete"])

    def test_response_body_loss_get_replay_and_explicit_owner_restore_do_not_repeat_io(
        self,
    ):
        self.bootstrap()
        body = self.offered("query_offer", "lost-response")
        with self.no_probe(), self.fake_runner():
            status, raw = self.request(
                self.base + "/stage1/query-execute", body, discard_response=True
            )
            self.assertEqual(status, 200)
            self.assertIsNone(raw)
            row = self.wait_query(body)
        self.assertEqual(row["status"], "completed", row)
        before = self.state_on_disk()[0]["stage1_query_budget"]
        event_count = len(
            CoverageLedger(
                self.bridge.services[self.ref]._projects[self.ref]["item"][
                    "ledger_root"
                ]
            ).events()
        )
        with (
            patch(
                "stage1_retrieval.runner.verify_identity",
                side_effect=AssertionError("replay probe"),
            ),
            self.block_external(),
        ):
            history = self.get(self.base + "/history")
            self.assertTrue(
                any(
                    action["key"] == body["key"] and action["status"] == "saved"
                    for action in history["actions"]
                )
            )
            recovered = next(
                action
                for action in self.get(self.base + "/stage1/actions")["actions"]
                if action["key"] == body["key"]
            )
            self.assertEqual(recovered["status"], "saved")
            replay = self.post(self.base + "/stage1/query-execute", body)
            self.assertTrue(replay["replayed"])
            self.close()
            self.open()
            self.assertEqual(self.query_view()["status"], "owner-reopen-required")
            self.assertEqual(self.bridge.services, {})
            replay = self.post(self.base + "/stage1/query-execute", body)
            self.assertTrue(replay["replayed"])
            self.assertEqual(self.bridge.services, {})
            restore = self.offered("owner_offer", "restore")
            restored = self.post(self.base + "/stage1/query-restore-owner", restore)
            self.assertEqual(restored["query_status"], "owner-restored-history-only")
            self.assertEqual(restored["actual_search_attempts"], 0)
            self.assertEqual(
                self.bridge.services[self.ref].view(self.token, self.ref)["history"],
                [row],
            )
            repeat_restore = self.post(
                self.base + "/stage1/query-restore-owner", restore
            )
            self.assertTrue(repeat_restore["replayed"])
        self.assertEqual(self.state_on_disk()[0]["stage1_query_budget"], before)
        ledger = CoverageLedger(
            self.bridge.services[self.ref]._projects[self.ref]["item"]["ledger_root"]
        )
        self.assertEqual(len(ledger.events()), event_count)
        self.assertEqual(len(self.probes), 1)
        self.assertEqual(len(self.children), 1)

    def test_query_route_path_injection_origin_and_stale_offer_do_not_spend_budget(
        self,
    ):
        self.bootstrap()
        body = self.offered("query_offer", "blocked-query")
        before = self.state_on_disk()[0]["stage1_query_budget"]
        with self.no_probe(), self.fake_runner():
            for modified, origin, expected in (
                ({**body, "ledger_root": str(self.root)}, DEFAULT, 400),
                ({**body, "query": "caller chosen search"}, DEFAULT, 400),
                (body, "https://unrelated.example", 403),
                (
                    {**body, "key": "stale-query", "offer_sha256": "0" * 64},
                    DEFAULT,
                    409,
                ),
            ):
                status, raw = self.request(
                    self.base + "/stage1/query-execute", modified, origin=origin
                )
                self.assertEqual(status, expected, raw)
        self.assertEqual(self.state_on_disk()[0]["stage1_query_budget"], before)
        self.assertEqual(
            self.bridge.services[self.ref].view(self.token, self.ref)["history"], []
        )
        self.assertEqual(self.children, [])
        self.assertEqual(len(self.probes), 1)

    def test_owned_local_plan_checkpoint_and_export_share_durable_query_history(self):
        self.bootstrap()
        service = self.bridge.services[self.ref]
        budget = self.state_on_disk()[0]["stage1_query_budget"]
        with self.block_external():
            view = self.get(self.base + "/stage1")
            query = view["queries"][0]
            body = dict(
                bound_body(self.get(self.base), "local-plan"),
                ledger_state_sha256=view["ledger"]["state_sha256"],
                query_ref=query["query_ref"],
                query_sha256=query["query_sha256"],
                confirmed=True,
            )
            planned = self.post(self.base + "/stage1/plan-query", body)
            self.assertEqual(planned["status"], "saved")
            for operation in ("checkpoint", "export"):
                view = self.get(self.base + "/stage1")
                body = dict(
                    bound_body(self.get(self.base), "local-" + operation),
                    ledger_state_sha256=view["ledger"]["state_sha256"],
                    confirmed=True,
                )
                observed = self.post(self.base + "/stage1/" + operation, body)
                self.assertEqual(observed["status"], "saved")
                replay = self.post(self.base + "/stage1/" + operation, body)
                self.assertTrue(replay["replayed"])
            rows = service.view(self.token, self.ref)["history"]
            self.assertEqual(len(rows), 3)
            self.assertCountEqual(
                [row["request"]["operation"] for row in rows],
                ["stage1-plan-query", "stage1-checkpoint", "stage1-export"],
            )
            saved_events = [
                event
                for event in service.store.events(service._projects[self.ref]["pid"])
                if event["kind"] == "saved-ledger-observation"
            ]
            self.assertEqual(
                [event["payload"]["request"]["operation"] for event in saved_events],
                ["stage1-plan-query", "stage1-checkpoint", "stage1-export"],
            )
            self.assertTrue(
                all(
                    row["status"] == "completed" and row["outcome"] == "observed"
                    for row in rows
                )
            )
            self.assertTrue(all(row["core_observation"]["valid"] for row in rows))
            self.assertEqual(
                service.view(self.token, self.ref)["budget"],
                dict(attempts=0, seconds=0),
            )
            self.assertIsNotNone(self.query_view()["query_offer"])
        self.assertEqual(self.state_on_disk()[0]["stage1_query_budget"], budget)
        self.assertEqual(self.children, [])
        self.assertEqual(len(self.probes), 1)


if __name__ == "__main__":
    unittest.main()
