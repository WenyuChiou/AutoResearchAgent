"""Actual localhost AtlasHost route plus SQLite/ledger and fake Hub child."""

import atlas_test_paths  # noqa: F401
from copy import deepcopy
import http.client
import json
import threading
import time

from stage1_deliverable.common import sha
from research_workspace_native.atlas_host import AtlasHost
from research_workspace_native.stage_actions import StageActions
from research_workspace_native.stage_inputs import snapshot_inputs, source_digest
from planned_query_fixture import QueryCase


class PlannedQueryHttpTests(QueryCase):
    def setUp(self):
        super().setUp()
        self.credential = "explicit-synthetic-token-" * 2
        self.raw = b'{"project_id":"project-a"}\n'
        self.item["index_sha256"] = sha(self.raw)
        self.permit["binding"]["index_sha256"] = self.item["index_sha256"]
        self.write_permit()
        self.query = self.service()
        self.query._auth = lambda t: (
            "researcher" if t in ("secret", self.credential) else None
        )
        inputs = {1: {"ledger_root": str(self.parent_ledger)}, 2: None}
        registrations = {
            "case": dict(
                project_id="project-a",
                index_sha256=self.item["index_sha256"],
                input_version=self.item["input_version"],
                source_sha256=source_digest(snapshot_inputs(inputs)),
                inputs=inputs,
                output_root=str(self.root / "checks"),
                principals=["researcher"],
            )
        }
        self.stages = StageActions(
            self.root / "stages.sqlite3",
            registrations=registrations,
            authenticate=self.query._auth,
            planned_queries=self.query,
        )
        self.addCleanup(self.stages.close)
        self.files = {
            "/views/case/atlas.html": b'<html lang="en"><meta content="connect-src \'none\'"><body><main id="atlas-content"><section id="atlas-stage-review"></section></main></body>',
            "/views/case/workspace-index.json": self.raw,
        }
        self.views = [
            dict(
                ref="case",
                label="Synthetic repository case",
                project_id="project-a",
                index_sha256=self.item["index_sha256"],
                manifest_sha256="a" * 64,
                fixture=True,
                url="/views/case/atlas.html",
            )
        ]
        self.host = AtlasHost(
            files=self.files,
            views=self.views,
            stage_actions=self.stages,
            credential=self.credential,
            timeout=15,
        )
        self.worker = threading.Thread(target=self.host.serve_forever, daemon=True)
        self.worker.start()
        self.addCleanup(self.stop)

    def stop(self):
        self.host.shutdown()
        self.host.server_close()
        self.worker.join(3)
        self.assertFalse(self.worker.is_alive())

    def call(
        self,
        suffix="",
        body=None,
        *,
        origin=None,
        raw=None,
        token=None,
        path=None,
        discard=False,
    ):
        connection = http.client.HTTPConnection(*self.host.server_address, timeout=15)
        headers = {"Authorization": "Bearer " + (token or self.credential)}
        if body is not None or raw is not None:
            headers.update(
                Origin=origin or self.host.expected_origin,
                **{"Content-Type": "application/json"},
            )
        try:
            connection.request(
                "POST" if body is not None or raw is not None else "GET",
                path or "/api/stages/projects/case/queries" + suffix,
                raw
                if raw is not None
                else json.dumps(body)
                if body is not None
                else None,
                headers,
            )
            if discard:
                return None
            response = connection.getresponse()
            return response.status, response.read()
        finally:
            connection.close()

    def body(self, key="action-1"):
        status, raw = self.call("/offer")
        self.assertEqual(status, 200, raw)
        offer = json.loads(raw)
        return dict(
            key=key,
            revision=offer["revision"],
            index_sha256=self.item["index_sha256"],
            input_version=self.item["input_version"],
            offer_ref=offer["offer_ref"],
            offer_sha256=offer["offer_sha256"],
            confirmed=True,
        )

    def test_actual_http_offer_execute_history_and_case_index_preserved(self):
        body = self.body()
        with self.no_probe(), self.fake_runner():
            status, raw = self.call("/actions", body)
            self.assertEqual(status, 200, raw)
            self.wait(self.query)
        row = json.loads(self.call("/actions/action-1")[1])
        self.assertEqual(row["status"], "completed")
        self.assertEqual(row["result"]["backend_outcome"], "success_nonempty")
        self.assertEqual(json.loads(self.call("/actions", body)[1]), row)
        self.assertEqual(
            json.loads(self.call()[1])["budget"], {"attempts": 1, "seconds": 32}
        )
        self.assertEqual(
            self.call(path="/views/case/workspace-index.json")[1], self.raw
        )
        self.assertEqual(len(self.children), 1)

    def test_response_close_recovers_by_get_with_no_extra_dispatch(self):
        body = self.body()
        with self.no_probe(), self.fake_runner():
            self.call("/actions", body, discard=True)
            # Wait for a saved server intent, not for a synthetic client success.
            until = time.monotonic() + 10
            while (
                not self.query.view("secret", "case")["history"]
                and time.monotonic() < until
            ):
                threading.Event().wait(0.01)
            row = self.wait(self.query)
        self.assertEqual(row["status"], "completed")
        self.assertEqual(json.loads(self.call("/actions/action-1")[1]), row)
        self.assertEqual(len(self.children), 1)

    def test_origin_credential_strict_json_and_caller_fields_refuse_zero_dispatch(self):
        body = self.body()
        self.assertEqual(
            self.call("/actions", body, origin="https://foreign.invalid")[0], 403
        )
        self.assertEqual(self.call("/actions", body, token="wrong")[0], 401)
        self.assertEqual(self.call("/actions", raw='{"key":"x","key":"y"}')[0], 400)
        self.assertEqual(self.call("/actions", dict(body, permit=True))[0], 400)
        self.assertEqual(self.call(path="/api/stages/projects/foreign/queries")[0], 404)
        self.assertEqual(self.query.view("secret", "case")["history"], [])
        self.assertEqual(self.children, [])

    def test_bootstrap_panel_is_opt_in_and_stage_mismatch_does_not_take_ownership(self):
        bootstrap = self.call(path="/host-bootstrap/case.js")[1]
        self.assertIn(b"WORKSPACE_PLANNED_QUERIES", bootstrap)
        self.assertIn(
            b"stage-query-panel.js", self.call(path="/views/case/atlas.html")[1]
        )
        self.assertIn(b"Run this one query", self.call(path="/stage-query-panel.js")[1])
        views = deepcopy(self.views)
        views[0]["index_sha256"] = "f" * 64
        with self.assertRaisesRegex(ValueError, "binding differs"):
            AtlasHost(
                files=self.files,
                views=views,
                stage_actions=self.stages,
                credential=self.credential,
            )
        self.assertFalse(self.query._closed)
        disabled = AtlasHost(files=self.files, views=self.views)
        self.addCleanup(disabled.server_close)
        self.assertEqual(disabled.query_cases, {})
        self.assertNotIn("/stage-query-panel.js", disabled._assets)
