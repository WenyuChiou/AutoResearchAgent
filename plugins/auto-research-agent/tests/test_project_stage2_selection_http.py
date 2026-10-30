# ruff: noqa: E402 -- repository package test.
"""Synthetic ProjectHost UI selection: real HTTP, no human/scientific claims."""

from contextlib import redirect_stderr, redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent / "cli"), str(HERE)]
import test_project_stage2 as activation_fixture
from project_stage2_selection_fixture import Stage2SelectionFixture
from research_workspace_native.project_host import ProjectHost
import research_workspace_native.project_host as host_module
from research_workspace_native.session_api import SessionApiError
import research_workspace_native.project_stage2_selection as selection_module
from research_workspace_native.project_stage2_selection import (
    ProjectStage2SelectionService,
)


class ProjectSelectionTests(Stage2SelectionFixture):
    def setUp(self):
        self.token = "synthetic-local-token-" + "x" * 32
        original_store = activation_fixture.ProjectIntakeService

        def local_store(root, *, authenticate):
            return original_store(
                root,
                authenticate=lambda key: {
                    "own": "local-viewer",
                    self.token: "local-viewer",
                    "other": "foreign-user",
                }.get(key),
            )

        # The fixture creates a genuinely principal-bound local project; no
        # production authenticator or admission guard is bypassed.
        with patch.object(
            activation_fixture, "ProjectIntakeService", side_effect=local_store
        ):
            super().setUp()
        self.choice, _, self.workflow = self.prepare_choice(
            ProjectStage2SelectionService
        )
        self.host = ProjectHost(
            projects=self.intake,
            credential=self.token,
            stage2_selection=self.choice,
            files={},
            views=[],
            port=0,
        )
        thread = threading.Thread(target=self.host.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(
            lambda: (
                self.host.shutdown(),
                self.host.server_close(),
                thread.join(timeout=5),
            )
        )

    def request(self, path, body=None, *, token=None, origin=None, timeout=20):
        headers = {
            "Authorization": "Bearer " + (token or self.token),
            "Origin": origin or self.host.expected_origin,
        }
        raw = None
        if body is not None:
            raw = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(
            self.host.expected_origin + path, data=raw, headers=headers
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status, r.read(), dict(r.headers)
        except urllib.error.HTTPError as e:
            return e.code, e.read(), dict(e.headers)

    def selection_body(self):
        status, raw, _ = self.request("/api/projects/" + self.ref + "/stage2/selection")
        self.assertEqual(status, 200, raw)
        v = json.loads(raw)
        candidate = v["eligible"][0]
        return dict(
            key="selection-once",
            revision=v["revision"],
            input_version=v["input_version"],
            brief_sha256=v["brief_sha256"],
            delivery_manifest_sha256=v["delivery_manifest_sha256"],
            workflow_head_sha256=v["workflow_head_sha256"],
            snapshot_sha256=v["snapshot_sha256"],
            confirmed=True,
            decision=dict(
                actor="synthetic-ui-user",
                kind="select",
                user_text="I choose the displayed version for planning.",
                selected=[candidate],
                conditions=["Keep limitations"],
                unresolved=["Access unknown"],
                rationale="Synthetic HTTP selection",
                scope_or_resource_change=False,
            ),
        )

    def test_http_roundtrip_has_real_ui_receipt_and_repeat_is_idempotent(self):
        body = self.selection_body()
        path = "/api/projects/" + self.ref + "/stage2/select"
        status, raw, _ = self.request(path, body)
        self.assertEqual(status, 200, raw)
        first = json.loads(raw)
        self.assertEqual(first["status"], "saved")
        self.assertEqual(first["planning_status"], "verified")
        self.assertFalse(first["execution_authorized"])
        status, raw, _ = self.request(path, body)
        self.assertEqual(status, 200, raw)
        self.assertTrue(json.loads(raw)["replayed"])
        rows = self.intake.db.execute(
            "SELECT receipt FROM intake_actions WHERE project=? AND key=?",
            (self.ref, body["key"]),
        ).fetchall()
        self.assertEqual(len(rows), 1)
        receipt = json.loads(rows[0][0])
        self.assertEqual(
            receipt["request"]["decision"]["user_text"], body["decision"]["user_text"]
        )
        self.assertEqual(receipt["input_origin"], "projecthost-ui-submission")
        status, raw, _ = self.request("/api/projects/" + self.ref + "/stage2/selection")
        self.assertEqual(status, 200, raw)
        saved_view = json.loads(raw)
        self.assertEqual(saved_view["selection_status"], "recorded")
        self.assertEqual(
            saved_view["delivery_workflow_head_sha256"], body["workflow_head_sha256"]
        )
        self.assertEqual(
            saved_view["workflow_head_sha256"], first["workflow_head_sha256"]
        )
        self.assertNotEqual(
            saved_view["workflow_head_sha256"], body["workflow_head_sha256"]
        )

    def test_hash_stale_version_auth_and_origin_guards(self):
        path = "/api/projects/" + self.ref + "/stage2/select"
        body = self.selection_body()
        body["delivery_manifest_sha256"] = "0" * 64
        status, _, _ = self.request(path, body)
        self.assertEqual(status, 409)
        status, _, _ = self.request(path, self.selection_body(), token="wrong")
        self.assertEqual(status, 401)
        status, _, _ = self.request(
            path, self.selection_body(), origin="https://untrusted.example"
        )
        self.assertEqual(status, 403)
        status, _, _ = self.request("/api/projects/foreign-project/stage2/selection")
        self.assertNotEqual(status, 200)

    def test_selection_assets_use_original_csp(self):
        status, raw, headers = self.request("/project-stage2-selection.html")
        self.assertEqual(status, 200, raw)
        self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])
        self.assertIn(b"/project-stage2-selection.js", raw)

    def interrupted_completed_choice(self, body):
        done = False
        original = selection_module.admit_intake

        def observed(*args, **kwargs):
            nonlocal done
            value = original(*args, **kwargs)
            done = True
            return value

        def deadline():
            if done:
                raise TimeoutError("synthetic post-work deadline")

        with patch.object(selection_module, "admit_intake", side_effect=observed):
            with self.assertRaises(SessionApiError):
                self.choice.select(self.token, self.ref, body, check_deadline=deadline)

    def test_completed_choice_registration_recovery_never_records_twice(self):
        from stage2_workflow.store import inspect_workflow

        body = self.selection_body()
        with patch.object(
            selection_module,
            "record_interaction",
            wraps=selection_module.record_interaction,
        ) as recorded:
            self.interrupted_completed_choice(body)
            before = inspect_workflow(self.workflow)["head_sha256"]
            receipt = self.choice.select(self.token, self.ref, body)
            self.assertEqual(receipt["status"], "saved")
            self.assertTrue(receipt["replayed"])
            self.assertEqual(recorded.call_count, 1)
            self.assertEqual(inspect_workflow(self.workflow)["head_sha256"], before)
        failures = self.intake.db.execute(
            "SELECT payload FROM intake_events WHERE project=? AND kind='stage2-select-failed'",
            (self.ref,),
        ).fetchall()
        self.assertEqual(len(failures), 1)
        self.assertEqual(json.loads(failures[0][0])["status"], "execution-unknown")
        view = self.choice.read(self.token, self.ref)
        self.assertEqual(view["planning_status"], "verified")
        self.assertFalse(view["planning_input"]["execution_authorized"])

    def test_interrupted_choice_retained_tampering_is_rejected_without_registration(
        self,
    ):
        body = self.selection_body()
        self.interrupted_completed_choice(body)
        row = self.intake.db.execute(
            "SELECT receipt FROM intake_actions WHERE project=? AND key=?",
            (self.ref, body["key"]),
        ).fetchone()
        before = row[0]
        receipt = json.loads(before)
        ack = receipt["output_observation"]
        output = (
            self.intake._path(self.ref, ack["artifact_ref"])
            / "interaction/interaction.json"
        )
        output.write_text("{}")
        with self.assertRaises(SessionApiError):
            self.choice.select(self.token, self.ref, body)
        row = self.intake.db.execute(
            "SELECT receipt FROM intake_actions WHERE project=? AND key=?",
            (self.ref, body["key"]),
        ).fetchone()
        self.assertEqual(row[0], before)


class SelectionCliTests(unittest.TestCase):
    def config(self, temporary):
        config = Path(temporary) / "selection.json"
        raw = json.dumps({"schema_version": "1.0.0", "bindings": {}}).encode()
        config.write_bytes(raw)
        return config, hashlib.sha256(raw).hexdigest()

    def test_external_config_hash_refuses_before_listener(self):
        with tempfile.TemporaryDirectory() as temporary:
            config, _ = self.config(temporary)
            with patch.object(host_module, "ProjectHost") as constructor:
                with redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit) as failure:
                        host_module.main(
                            [
                                "--projects-root",
                                str(Path(temporary).resolve() / "projects"),
                                "--selection-config",
                                str(config),
                                "--selection-sha256",
                                "0" * 64,
                            ]
                        )
                self.assertEqual(failure.exception.code, 2)
                constructor.assert_not_called()

    def test_matching_config_bootstraps_and_closes_actual_local_listener(self):
        observed = {}

        class FiniteHost(ProjectHost):
            def serve_forever(self):
                observed["origin"] = self.expected_origin
                observed["bindings"] = self.project_stage2_selection.bindings
                observed["same_intake"] = (
                    self.project_stage2_selection.intake is self.projects
                )
                observed["port"] = self.server_address[1]

            def server_close(self):
                observed["closed"] = True
                super().server_close()

        with tempfile.TemporaryDirectory() as temporary:
            config, digest = self.config(temporary)
            output = io.StringIO()
            with patch.object(host_module, "ProjectHost", FiniteHost):
                with redirect_stdout(output):
                    host_module.main(
                        [
                            "--projects-root",
                            str(Path(temporary).resolve() / "projects"),
                            "--selection-config",
                            str(config),
                            "--selection-sha256",
                            digest,
                        ]
                    )
            self.assertEqual(
                json.loads(output.getvalue()),
                {
                    "url": observed["origin"] + "/",
                    "model_execution": "unconnected",
                    "search_execution": "unconnected",
                    "stage3_planning": "unconnected",
                    "execution_authorized": False,
                },
            )
            self.assertEqual(observed["bindings"], {})
            self.assertTrue(observed["same_intake"])
            self.assertGreater(observed["port"], 0)
            self.assertTrue(observed["closed"])


if __name__ == "__main__":
    unittest.main()
