"""Ordinary authenticated HTTP review readback using a local engineering fixture."""

# ruff: noqa: E402 -- load the plugin and the Host's readback module.
from contextlib import closing, contextmanager
from hashlib import sha256
from http.client import HTTPConnection
import json
from pathlib import Path
from sqlite3 import OperationalError
import sys
from threading import Thread
import unittest

PLUGIN = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(PLUGIN / "cli"), str(PLUGIN.parents[1] / "harness-ui")]
from research_workspace_native.project_host import ProjectHost
from research_workspace_native.project_stage3_http import ProjectStage3Http
from research_workspace_native.project_stage3_planning import (
    ProjectStage3PlanningService,
)
from stage3_plan.contracts import canonical_bytes, digest
from stage3_plan.workflow import advance_workflow
from stage3_plan_review_readback import plan_review_identity
import test_project_stage3_planning as planning_fixture
from test_stage3_plan_decision import semantic_review


class ProjectStage3HostReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture_type = planning_fixture.ProjectStage3PlanningTests
        cls.fixture_type.setUpClass()
        cls.addClassCleanup(cls.fixture_type.doClassCleanups)

    def setUp(self):
        self.fx = f = self.fixture_type()
        f.setUp()
        self.addCleanup(f.doCleanups)
        self.ref = f.f.ref
        self.route = f"/api/projects/{self.ref}/stage3/planning"
        self.binding = {self.ref: f.binding}
        transport = ProjectStage3Http(f.bridge)
        self.addCleanup(transport.close)
        options = transport.view("own", self.ref)["default_request"]
        self.plan = planning_fixture.authored_plan(
            f.admitted,
            f.selection["planning_manifest_sha256"],
            "host-plan-" + digest(options["key"]),
        )
        f.callback.return_value["raw_response"] = canonical_bytes(self.plan)
        receipt = f.bridge.prepare("own", self.ref, options)
        self.job_request = digest(
            f.journal.snapshot(f.jobs.project_id)["intents"][
                f.jobs._key(options["key"])
            ]["payload"]
        )
        self.assertEqual(receipt["request_sha256"], self.job_request)
        saved = f.bridge.run(
            "own",
            self.ref,
            dict(options, request_sha256=self.job_request, confirmed=True),
        )
        self.assertEqual(saved["outcome"], "saved")
        self.job_key = options["key"]
        self.job_pin = saved["plan_manifest_sha256"]
        self.pins = {(self.ref, self.job_key, self.job_request): self.job_pin}
        self.item = f.journal.snapshot(f.jobs.project_id)["intents"][
            f.jobs._key(self.job_key)
        ]
        self.checkpoint = self.item["evidence"]["checkpoint"]
        self.review_file = f.jobs.root / "synthetic-review.json"
        self.review_file.write_bytes(
            canonical_bytes(
                semantic_review(
                    self.plan, f.admitted, status="unknown", kind="synthetic"
                )
            )
        )
        self.review_sha = sha256(self.review_file.read_bytes()).hexdigest()
        reviewed = f.jobs.root / "reviewed.json"
        saved_review = advance_workflow(
            self.checkpoint["path"],
            expected_checkpoint_sha256=self.checkpoint["sha256"],
            action="attach-review",
            output=reviewed,
            binding={"path": str(self.review_file), "sha256": self.review_sha},
        )
        self.reviewed = {
            "path": str(reviewed),
            "sha256": saved_review["checkpoint_sha256"],
        }
        self.assertEqual(f.callback.call_count, 1)

    @contextmanager
    def host(self, reader=None):
        f = self.fx
        options = {} if reader is None else {"plan_review_reader": reader}
        service = ProjectStage3PlanningService(
            f.f.intake,
            f.choice,
            bindings=self.binding,
            saved_read_pins=self.pins,
            **options,
        )
        host = ProjectHost(
            projects=f.f.intake,
            credential=f.f.token,
            stage2_selection=f.choice,
            stage3_planning=service,
            stage3_recovery_pins=self.pins,
            files={},
            views=[],
            port=0,
        )
        worker = Thread(target=host.serve_forever)
        worker.start()
        try:
            yield host
        finally:
            host.shutdown()
            worker.join(5)
            host.server_close()
            self.assertFalse(worker.is_alive())

    def get(self, host, route=None, *, authenticated=True):
        headers = {"Origin": host.expected_origin}
        if authenticated:
            headers["Authorization"] = "Bearer " + self.fx.f.token
        with closing(
            HTTPConnection("127.0.0.1", host.server_address[1], timeout=30)
        ) as conn:
            conn.request("GET", route or self.route, headers=headers)
            res = conn.getresponse()
            return res.status, json.loads(res.read())

    def snapshot(self):
        f = self.fx
        return (
            f.journal.snapshot(f.jobs.project_id),
            f.journal.events(f.jobs.project_id),
            [
                tuple(row)
                for row in f.f.intake.db.execute(
                    "SELECT project,kind,payload FROM intake_events ORDER BY id"
                )
            ],
            [
                tuple(row)
                for row in f.f.intake.db.execute(
                    "SELECT project,key,request_hash,receipt FROM intake_actions ORDER BY project,key"
                )
            ],
            {
                path.relative_to(f.jobs.root).as_posix(): (
                    sha256(path.read_bytes()).hexdigest(),
                    path.stat().st_mtime_ns,
                )
                for path in f.jobs.root.rglob("*")
                if path.is_file()
            },
        )

    def test_ordinary_get_adds_only_current_trusted_saved_review(self):
        before = self.snapshot()
        with self.host() as host:
            status, view = self.get(host)
        self.assertEqual(status, 200)
        self.assertEqual(view["plan"], self.plan)
        self.assertEqual(
            view["plan_review"]["reason"], "stage3-plan-review-index-unconnected"
        )
        self.assertIsNone(view["plan_review"]["review"])
        self.assertIsNone(view["plan_review"]["decision"])

        from stage3_plan_review_host import Stage3PlanReviewReader

        identity = plan_review_identity(view)
        trusted = {"identity": identity, "checkpoint": self.reviewed, "decision": None}
        rows = {}
        lookups = []

        def lookup(current):
            # Only the Test Host owns this in-memory index. The HTTP client
            # always supplies the ordinary route and its authentication.
            lookups.append(current)
            row = rows.get(digest(current))
            if isinstance(row, Exception):
                raise row
            return row

        reader = Stage3PlanReviewReader(lookup)
        with self.host(reader) as host:
            for label, row, expected, reason in (
                ("missing", None, "unlinked", "stage3-plan-review-binding-unavailable"),
                (
                    "index-unavailable",
                    OperationalError("private-database"),
                    "unavailable",
                    "stage3-plan-review-index-unavailable",
                ),
                (
                    "unreviewed",
                    dict(trusted, checkpoint=self.checkpoint),
                    "bound",
                    "stage3-semantic-review-not-recorded",
                ),
                (
                    "old-plan",
                    dict(trusted, identity=dict(identity, plan_version=2)),
                    "rejected",
                    "stage3-plan-review-binding-rejected",
                ),
                (
                    "wrong-typed-input",
                    dict(trusted, identity=dict(identity, input_version=1)),
                    "rejected",
                    "stage3-plan-review-binding-rejected",
                ),
                (
                    "foreign-stored-row",
                    dict(trusted, identity=dict(identity, project_ref="other")),
                    "rejected",
                    "stage3-plan-review-binding-rejected",
                ),
                (
                    "changed-file-sha",
                    dict(trusted, checkpoint=dict(self.reviewed, sha256="0" * 64)),
                    "rejected",
                    "stage3-plan-review-binding-rejected",
                ),
                (
                    "missing-file",
                    dict(
                        trusted,
                        checkpoint=dict(
                            self.reviewed,
                            path=str(self.review_file.with_name("missing")),
                        ),
                    ),
                    "rejected",
                    "stage3-plan-review-binding-rejected",
                ),
                ("reviewed", trusted, "bound", "stage3-plan-decision-not-recorded"),
            ):
                with self.subTest(label=label):
                    rows[digest(identity)] = row
                    code, observed = self.get(host)
                    self.assertEqual(code, 200)
                    projection = observed.pop("plan_review")
                    self.assertEqual(
                        observed, {k: v for k, v in view.items() if k != "plan_review"}
                    )
                    self.assertEqual(projection["readback_status"], expected)
                    self.assertEqual(projection["reason"], reason)
                    self.assertIsNone(projection["decision"])
                    self.assertFalse(projection["execution_authorized"])
                    if label == "reviewed":
                        self.assertEqual(
                            projection["review"],
                            {
                                "sha256": self.review_sha,
                                "reviewer_kind": "synthetic",
                                "identity_authenticated": False,
                                "finding_counts": {"unknown": 5},
                            },
                        )
                        self.assertEqual(
                            projection["checkpoint_sha256"], self.reviewed["sha256"]
                        )
                    else:
                        self.assertIsNone(projection["review"])
            self.assertEqual(
                self.get(host, "/api/projects/wrong-project/stage3/planning"),
                (404, {"error": "project-unavailable"}),
            )
            self.assertEqual(self.get(host, authenticated=False)[0], 401)
            self.assertEqual(self.get(host, self.route + "?plan_version=2")[0], 404)
        with self.host(Stage3PlanReviewReader(lookup)) as reopened:
            code, result = self.get(reopened)
            self.assertEqual(code, 200)
            self.assertEqual(result["plan_review"], projection)
        self.assertEqual(lookups, [identity] * 10)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.fx.callback.call_count, 1)
