"""Actual local HTTP, SQLite and brief compiler; no process/model/search calls."""

import http.client
from contextlib import nullcontext
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / "cli"))
from research_workspace_native.http import token_authenticator
from research_workspace_native.atlas_host import AtlasHost
from research_workspace_native import project_host
from research_workspace_native.project_contract import measurement
from research_workspace_native.project_host import ProjectHost
from research_workspace_native.project_intake import ProjectIntakeService
from research_workspace_native.project_stage1 import ProjectStage1Service
from research_workspace_native.project_stage1_queries import ProjectStage1QueryService
from research_workspace_native.project_stage1_records import ProjectStage1RecordsService
from stage1_deliverable.common import sha
from test_workspace_project_intake import compile_body, submit_body


class ProjectHostConstructionTests(unittest.TestCase):
    def test_missing_or_unreadable_asset_does_not_allocate_or_take_ownership(self):
        token = "local-project-test-token-with-at-least-32-characters"
        real_init, real_read = AtlasHost.__init__, Path.read_bytes
        with tempfile.TemporaryDirectory(prefix="project-construction-") as root:
            projects = ProjectIntakeService(
                Path(root).resolve(),
                authenticate=token_authenticator({token: "local-viewer"}),
            )
            try:
                for filename in (
                    "projects.html",
                    "projects.js",
                    "projects.css",
                    "projects-library.js",
                    "projects-coverage.js",
                    "projects-expansions.js",
                    "projects-reading.js",
                    "projects-saved-claims.js",
                    "projects-atlas.js",
                    "projects-progress.js",
                    "projects-stages.js",
                    "projects-stages.css",
                    "project-operations.js",
                    "project-operations.css",
                ):
                    for error in (FileNotFoundError, PermissionError):
                        with self.subTest(filename=filename, error=error.__name__):
                            allocated = []

                            def capture_init(host, *args, **options):
                                real_init(host, *args, **options)
                                allocated.append(host)

                            def fail_asset(path):
                                if path == project_host.ASSETS / filename:
                                    raise error("injected project asset read failure")
                                return real_read(path)

                            try:
                                with (
                                    patch.object(AtlasHost, "__init__", capture_init),
                                    patch.object(Path, "read_bytes", fail_asset),
                                    self.assertRaises(error),
                                ):
                                    ProjectHost(
                                        projects=projects,
                                        credential=token,
                                        files={},
                                        views=[],
                                        port=0,
                                    )
                            finally:
                                # The old constructor leaks these allocated hosts.
                                for host in allocated:
                                    host.server_close()
                            self.assertEqual(allocated, [])
                            self.assertEqual(projects.list(token), [])
            finally:
                projects.close()


class ProjectHostTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="project-http-")
        self.token = "local-project-test-token-with-at-least-32-characters"
        self.projects = ProjectIntakeService(
            Path(self.tmp.name).resolve(),
            authenticate=token_authenticator({self.token: "local-viewer"}),
        )
        self.host = ProjectHost(
            projects=self.projects,
            credential=self.token,
            stage1=ProjectStage1Service(self.projects),
            files={},
            views=[],
            port=0,
        )
        self.worker = threading.Thread(target=self.host.serve_forever, daemon=True)
        self.worker.start()

    def tearDown(self):
        self.host.shutdown()
        self.host.server_close()
        self.worker.join(3)
        self.assertFalse(self.worker.is_alive())
        self.projects.close()
        self.tmp.cleanup()

    def request(self, path, body=None, *, headers=None, raw=None):
        supplied = {"Authorization": "Bearer " + self.token}
        if body is not None or raw is not None:
            supplied.update(
                {
                    "Content-Type": "application/json",
                    "Origin": self.host.expected_origin,
                }
            )
        supplied.update(headers or {})
        client = http.client.HTTPConnection(
            "127.0.0.1", self.host.server_port, timeout=5
        )
        try:
            client.request(
                "POST" if body is not None or raw is not None else "GET",
                path,
                body=json.dumps(body).encode() if body is not None else raw,
                headers=supplied,
            )
            response = client.getresponse()
            data = response.read()
            return response.status, data
        finally:
            client.close()

    def post(self, path, body):
        code, raw = self.request(path, body)
        self.assertEqual(code, 200, raw)
        return json.loads(raw)

    def get(self, path):
        code, raw = self.request(path)
        self.assertEqual(code, 200, raw)
        return json.loads(raw)

    def new(self, topic="Polyphonic music transcription"):
        receipt = self.post(
            "/api/projects",
            {
                "key": "create-" + str(len(self.projects.list(self.token))),
                "topic": topic,
            },
        )
        ref = receipt["project_ref"]
        return ref, self.get("/api/projects/" + ref)

    def test_inline_frame_policy_is_limited_to_project_pages_and_keeps_admission(self):
        changes = self.projects.db.total_changes
        for route, frame, ancestor in (
            ("/", True, "none"),
            ("/projects.html", True, "none"),
            ("/projects-panel.html", True, "self"),
            ("/project-atlas.html", False, "self"),
            ("/project-atlas-child.js", False, "none"),
            ("/projects.js", False, "none"),
        ):
            with self.subTest(route=route):
                client = http.client.HTTPConnection(
                    "127.0.0.1", self.host.server_port, timeout=5
                )
                try:
                    client.request("GET", route)
                    response = client.getresponse()
                    raw = response.read()
                    self.assertEqual(response.status, 200, raw)
                    policy = response.getheader("Content-Security-Policy")
                    self.assertEqual("frame-src 'self'" in policy, frame)
                    self.assertIn("frame-ancestors '" + ancestor + "'", policy)
                    self.assertNotIn(self.token.encode(), raw)
                finally:
                    client.close()
                for headers in (
                    {"Origin": "https://foreign.invalid"},
                    {"Host": "foreign.invalid"},
                    {"Sec-Fetch-Site": "cross-site"},
                ):
                    self.assertEqual(self.request(route, headers=headers)[0], 403)
        self.assertEqual(self.projects.db.total_changes, changes)
        self.assertEqual(self.projects.list(self.token), [])

    def test_two_topics_real_confirm_compile_and_common_stage_metrics(self):
        for topic in (
            "Polyphonic music transcription",
            "Aircraft sensor drift diagnosis",
        ):
            ref, view = self.new(topic)
            path = "/api/projects/" + ref
            self.post(path + "/confirm", submit_body(view))
            confirmed = self.get(path)
            self.post(path + "/compile", compile_body(confirmed))
            contract = self.get(path + "/contract")
            self.assertEqual(contract["kind"], "HarnessUiProjectView")
            self.assertEqual(
                contract["identity"]["brief_sha256"], self.get(path)["brief_sha256"]
            )
            self.assertTrue(contract["stages"]["1"]["intake"]["readiness"])
            self.assertFalse(contract["stages"]["1"]["accepted"])
            self.assertFalse(contract["stages"]["2"]["connected"])
            self.assertIsNone(
                contract["stages"]["1"]["metrics"]["actual_model_calls"]["value"]
            )
            for number in ("3", "4", "5", "6"):
                self.assertEqual(contract["stages"][number]["status"], "planned")
                self.assertFalse(contract["stages"][number]["connected"])
            self.assertEqual(self.get(path)["brief"]["original_description"], topic)
        self.assertEqual(len(self.get("/api/projects")), 2)

    def test_create_response_loss_recovery_has_same_key_and_no_duplicate(self):
        ref, _ = self.new()
        with patch(
            "research_workspace_native.project_intake.create_brief",
            side_effect=AssertionError("read produced"),
        ):
            saved = self.get("/api/projects/actions/create-0")["action"]
            self.assertEqual(saved["project_ref"], ref)
            self.assertEqual(saved["status"], "saved")
            self.get("/api/projects/" + ref + "/history")
        self.assertEqual(len(self.get("/api/projects")), 1)

    def test_known_unsent_rejection_is_durable_and_existing_receipts_not_replaced(self):
        ref, view = self.new()
        body = submit_body(view)
        body["revision"] = 900
        status, raw = self.request("/api/projects/" + ref + "/confirm", body)
        self.assertEqual(status, 409)
        rejected = json.loads(raw)["receipt"]
        self.assertEqual(rejected["status"], "known-unsent")
        self.assertEqual(rejected["project_ref"], ref)
        self.assertEqual(rejected["key"], body["key"])
        self.assertEqual(
            self.get("/api/projects/" + ref + "/history")["actions"][-1]["status"],
            "known-unsent",
        )
        replay = self.post("/api/projects/" + ref + "/confirm", body)
        self.assertEqual(replay["status"], "known-unsent")
        self.assertEqual(
            self.get("/api/projects/" + ref)["brief_sha256"], view["brief_sha256"]
        )

    def test_version_change_keeps_old_plan_and_resets_readiness(self):
        ref, view = self.new()
        path = "/api/projects/" + ref
        self.post(path + "/confirm", submit_body(view))
        self.post(path + "/compile", compile_body(self.get(path)))
        current = self.get(path)
        binding = {
            name: current[name]
            for name in ("revision", "input_version", "brief_sha256")
        }
        self.post(
            path + "/revise",
            dict(key="new-topic", topic="Music annotation costs", **binding),
        )
        changed = self.get(path)
        self.assertEqual(changed["input_version"], 2)
        self.assertFalse(changed["stage1_intake_ready"])
        self.assertEqual(len(self.get(path + "/history")["versions"]), 3)
        self.assertIsNone(changed["plan"])

    def test_host_origin_auth_fields_duplicate_json_and_unconnected_rejected(self):
        ref, view = self.new()
        for headers, expected in (
            ({"Origin": "null"}, 403),
            ({"Authorization": "Bearer invalid"}, 401),
            ({"Host": "attacker.example"}, 403),
        ):
            self.assertEqual(
                self.request("/api/projects", headers=headers)[0], expected
            )
        body = submit_body(view)
        body["owner"] = "caller-owned"
        status, raw = self.request("/api/projects/" + ref + "/confirm", body)
        self.assertEqual(status, 400)
        self.assertIsNone(json.loads(raw).get("receipt"))
        self.assertEqual(
            self.request("/api/projects", raw=b'{"key":"a","key":"b","topic":"x"}')[0],
            400,
        )
        self.assertEqual(
            self.request("/api/projects/" + ref + "/models/offers")[0], 409
        )
        self.assertEqual(self.request("/api/projects/" + ref + "/stage2")[0], 409)
        self.assertEqual(
            self.request("/api/projects/" + ref + "/stage3", {"key": "run"})[0], 404
        )

    def test_served_portal_hashes_and_bootstrap_credential_boundary(self):
        binding = self.get("/host-binding.json")
        self.assertFalse(binding["project_stage1_saved_records"])
        self.assertFalse(binding["project_stage1_source_acquisition"])
        self.assertFalse(binding["project_stage1_automatic_reading"])
        for path in (
            "/",
            "/projects.html",
            "/projects.js",
            "/projects.css",
            "/projects-saved-claims.js",
        ):
            status, raw = self.request(path)
            self.assertEqual(status, 200)
            self.assertEqual(sha(raw), binding["served_files"][path])
            self.assertNotIn(self.token.encode(), raw)
        status, raw = self.request("/project-bootstrap.js")
        self.assertEqual(status, 200)
        self.assertIn(self.token.encode(), raw)
        self.assertEqual(
            self.request(
                "/project-bootstrap.js", headers={"Origin": "https://external.example"}
            )[0],
            403,
        )

    def test_saved_records_host_requires_attached_same_intake_typed_query_owner(self):
        stage1 = self.host.project_stage1
        queries = object.__new__(ProjectStage1QueryService)
        queries.stage1, queries.intake = stage1, self.projects
        for attached, owner_stage, owner_intake in (
            (None, stage1, self.projects),
            (object(), stage1, self.projects),
            (queries, object(), self.projects),
            (queries, stage1, object()),
        ):
            stage1.query_service = attached
            queries.stage1, queries.intake = owner_stage, owner_intake
            with (
                self.subTest(owner=attached),
                patch.object(
                    ProjectStage1QueryService, "create_records_service"
                ) as factory,
                self.assertRaisesRegex(
                    ValueError,
                    r"trusted query owner|^project-expansion-query-owner-required$",
                ),
            ):
                ProjectHost(
                    projects=self.projects,
                    credential=self.token,
                    stage1=stage1,
                    stage1_materials_root="never-resolved-by-host",
                    files={},
                    views=[],
                    port=0,
                )
            factory.assert_not_called()
        self.assertEqual(self.projects.list(self.token), [])

    def test_saved_records_host_passes_exact_delivery_and_root_without_reader(self):
        stage1 = self.host.project_stage1
        queries = object.__new__(ProjectStage1QueryService)
        queries.stage1, queries.intake = stage1, self.projects
        stage1.query_service = queries
        materials = tempfile.TemporaryDirectory(prefix="project-host-materials-")
        self.addCleanup(materials.cleanup)
        root = Path(materials.name).resolve()
        created = []

        def construct(owner, delivery, *, materials_root):
            # Only the host forwarding boundary uses a synthetic guard here.
            # The actual query-owner guard has its own real SQLite tests.
            self.assertIs(owner, queries)
            self.assertIs(delivery.stage1, stage1)
            self.assertIs(delivery.intake, self.projects)
            self.assertEqual(materials_root, root)
            records = ProjectStage1RecordsService(
                delivery,
                materials_root=root,
                mutation_guard=lambda *args: nullcontext(),
            )
            created.append(records)
            return records

        configured = None
        try:
            with patch.object(
                ProjectStage1QueryService,
                "create_records_service",
                autospec=True,
                side_effect=construct,
            ) as factory:
                configured = ProjectHost(
                    projects=self.projects,
                    credential=self.token,
                    stage1=stage1,
                    stage1_materials_root=root,
                    files={},
                    views=[],
                    port=0,
                )
            factory.assert_called_once_with(
                queries, configured.project_stage1_delivery, materials_root=root
            )
            self.assertIs(configured.project_stage1_records, created[0])
            binding = json.loads(configured._assets["/host-binding.json"])
            self.assertTrue(binding["project_stage1_saved_records"])
            self.assertFalse(binding["project_stage1_source_acquisition"])
            self.assertFalse(binding["project_stage1_automatic_reading"])
            self.assertFalse(list(root.iterdir()))
            self.assertEqual(self.projects.list(self.token), [])
        finally:
            if configured is not None:
                configured.server_close()

    def test_stage1_real_http_ledger_gate_and_export_are_not_stage_completion(self):
        ref, view = self.new()
        path = "/api/projects/" + ref
        self.post(path + "/confirm", submit_body(view))
        self.post(path + "/compile", compile_body(self.get(path)))
        current = self.get(path)
        identity = {
            name: current[name]
            for name in ("revision", "input_version", "brief_sha256")
        }
        offer = self.get(path + "/stage1")["initialization_offer"]
        self.post(
            path + "/stage1/initialize",
            dict(
                identity,
                key="ledger-init",
                confirmed=True,
                offer_ref=offer["offer_ref"],
                offer_sha256=offer["offer_sha256"],
            ),
        )
        snapshot = self.get(path + "/overview")
        self.assertEqual(snapshot["stage1"]["stage1_status"], "offline-ledger-active")
        self.assertFalse(snapshot["stage1"]["stage1_complete"])
        progress = snapshot["stage1"]["progress"]
        self.assertEqual(
            progress["binding"],
            {
                name: snapshot["project"][name]
                for name in ("project_ref", "revision", "input_version", "brief_sha256")
            },
        )
        self.assertFalse(progress["research_complete"])
        for action in ("checkpoint", "export"):
            current, stage = self.get(path), self.get(path + "/stage1")
            identity = {
                name: current[name]
                for name in ("revision", "input_version", "brief_sha256")
            }
            receipt = self.post(
                path + "/stage1/" + action,
                dict(
                    identity,
                    key="ledger-" + action,
                    confirmed=True,
                    ledger_state_sha256=stage["ledger"]["state_sha256"],
                ),
            )
            self.assertEqual(receipt["status"], "saved")
        self.assertIsNone(self.get(path + "/stage1")["canonical_package"])
        contract = self.get(path + "/contract")
        self.assertFalse(contract["stages"]["1"]["accepted"])

    def test_extra_read_suffixes_rejected_and_overview_does_not_produce(self):
        ref, _ = self.new()
        for suffix in ("history/offers", "contract/actions", "overview/native"):
            self.assertEqual(
                self.request("/api/projects/" + ref + "/" + suffix)[0], 400
            )
        with patch(
            "research_workspace_native.project_intake.create_brief",
            side_effect=AssertionError("GET produced"),
        ):
            snapshot = self.get("/api/projects/" + ref + "/overview")
            self.assertEqual(snapshot["project"]["project_ref"], ref)
            self.assertIsNone(snapshot["models"])
            progress = snapshot["stage1"]["progress"]
            self.assertEqual(progress["kind"], "ProjectStage1Progress")
            self.assertFalse(progress["research_complete"])
            self.assertEqual(len(progress["phases"]), 7)
            self.assertEqual(progress["next_action"]["target"], "scope")

    def test_measurement_does_not_turn_unknown_into_zero(self):
        self.assertIsNone(measurement("calls")["value"])
        with self.assertRaises(ValueError):
            measurement("calls", value=0)
        with self.assertRaises(ValueError):
            measurement("calls", value=True, status="recorded")
        for value in (float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                measurement("seconds", value=value, status="recorded")


if __name__ == "__main__":
    unittest.main()
