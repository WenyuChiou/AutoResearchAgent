"""Real loopback/SQLite and saved-input producers; no native/model execution."""

from copy import deepcopy
import http.client
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from research_workspace.atlas import atlas_files
from research_workspace_native.atlas_host import AtlasHandler, AtlasHost
from research_workspace_native.harness_host import create_harness_operations
from stage1_deliverable.common import canonical, sha
from test_workspace_atlas import payload


class HarnessHostTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="harness-host-")
        self.addCleanup(temporary.cleanup)
        self.root, self.token = Path(temporary.name).resolve(), "local-" + "t" * 40
        value = payload()
        # Saved file bytes and canonical input identity are distinct bindings.
        self.raw = canonical(value["index"]) + b"\n"
        projection = atlas_files(value)
        self.files = {"/views/alpha/" + name: raw for name, raw in projection.items()}
        self.files["/views/alpha/workspace-index.json"] = self.raw
        self.views = [
            dict(
                ref="alpha",
                project_id=value["index"]["project_id"],
                index_sha256=sha(self.raw),
                url="/views/alpha/atlas.html",
                fixture=True,
                label="Synthetic case",
                manifest_sha256="a" * 64,
            )
        ]
        self.service = create_harness_operations(
            self.files, self.views, self.root / "ops", self.token
        )
        self.addCleanup(self.service.close)
        self.server = AtlasHost(
            files=self.files,
            views=self.views,
            credential=self.token,
            harness_ops=self.service,
        )
        worker = threading.Thread(target=self.server.serve_forever, daemon=True)
        worker.start()

        def stop():
            self.server.shutdown()
            self.server.server_close()
            worker.join(2)
            self.assertFalse(worker.is_alive())

        self.addCleanup(stop)

    def call(
        self, path="/api/harness/projects/alpha", method="GET", body=None, headers=None
    ):
        defaults = {"Authorization": "Bearer " + self.token}
        if method == "POST":
            defaults.update(
                Origin=self.server.expected_origin,
                **{"Content-Type": "application/json"},
            )
        defaults.update(headers or {})
        raw = json.dumps(body).encode() if isinstance(body, dict) else body
        client = http.client.HTTPConnection(
            "127.0.0.1", self.server.server_port, timeout=3
        )
        try:
            client.request(method, path, body=raw, headers=defaults)
            response = client.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            client.close()

    def request(self, action="validate-index", key="one"):
        status, _, raw = self.call()
        self.assertEqual(status, 200)
        view = json.loads(raw)
        return dict(
            action=action,
            key=key,
            index_sha256=view["index_sha256"],
            expected_revision=view["revision"],
        )

    def post(self, request):
        return self.call("/api/harness/projects/alpha/actions", "POST", request)

    def test_snapshot_bootstrap_asset_order_default_passive_and_close_ownership(self):
        original = deepcopy(self.files)
        with patch.object(
            self.service, "_produce", wraps=self.service._produce
        ) as producer:
            status, _, raw = self.call("/host-bootstrap/alpha.js")
            self.assertEqual(status, 200)
            marker = b"window.WORKSPACE_HARNESS="
            config = json.loads(raw.split(marker)[1].split(b";\n")[0])
            self.assertEqual(
                config,
                dict(enabled=True, project_ref="alpha", index_sha256=sha(self.raw)),
            )
            self.assertIn(b'"enabled": false', raw)  # Native remains disabled.
            status, _, html = self.call("/views/alpha/atlas.html")
            self.assertEqual(status, 200)
            self.assertLess(
                html.index(b"/host-bootstrap/"), html.index(b"/harness-panel.js")
            )
            self.assertLess(
                html.index(b"/harness-panel.js"), html.index(b"/host-panel.js")
            )
            self.call()
            self.assertEqual(producer.call_count, 0)
        self.assertEqual(self.files, original)
        self.server.shutdown()
        self.server.server_close()
        self.assertTrue(self.service._closed)
        self.server.server_close()

    def test_actual_selection_idempotent_replay_refresh_and_source_not_mutated(self):
        request = self.request("derive-literature-selection")
        with patch.object(
            self.service, "_produce", wraps=self.service._produce
        ) as producer:
            status, _, raw = self.post(request)
            self.assertEqual(status, 200)
            row = json.loads(raw)
            self.assertEqual(
                row["result"]["counts"],
                dict(screened=2, pending=2, included=0, excluded=0),
            )
            self.assertFalse(row["model_execution"])
            self.assertFalse(row["scientific_admission"])
            self.assertEqual(json.loads(self.post(request)[2]), row)
            self.assertEqual(
                json.loads(self.call("/api/harness/projects/alpha/actions/one")[2]), row
            )
            self.assertEqual(json.loads(self.call()[2])["history"], [row])
            self.assertEqual(producer.call_count, 1)
            changed = dict(request, action="export-selection")
            self.assertEqual(self.post(changed)[0], 409)
            self.assertEqual(producer.call_count, 1)
        self.assertEqual(self.files["/views/alpha/workspace-index.json"], self.raw)

    def test_exports_bearer_fixed_names_exact_hash_and_changed_file_rejected(self):
        status, _, raw = self.post(self.request("export-selection"))
        self.assertEqual(status, 200)
        row = json.loads(raw)
        self.assertEqual(len(row["artifacts"]), 7)
        item = next(
            f for f in row["artifacts"] if f["name"] == "literature/screening.bib"
        )
        path = (
            "/api/harness/projects/alpha/artifacts/one/"
            + item["name"]
            + "?sha256="
            + item["sha256"]
        )
        status, headers, data = self.call(path)
        self.assertEqual(
            (status, sha(data), len(data)), (200, item["sha256"], item["size"])
        )
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        self.assertIn("attachment", headers["Content-Disposition"])
        self.assertEqual(self.call(path, headers={"Authorization": ""})[0], 401)
        self.assertEqual(self.call(path + "&token=secret")[0], 400)
        self.assertEqual(self.call(path.replace(item["sha256"], "0" * 64))[0], 409)
        saved = self.root / "ops" / "alpha" / row["output_ref"] / item["name"]
        saved.write_bytes(data + b"tampered")
        self.assertEqual(self.call(path)[0], 409)

    def test_safety_headers_fields_refs_json_and_stale_revision_have_zero_work(self):
        request = self.request()
        with patch.object(
            self.service, "_produce", wraps=self.service._produce
        ) as producer:
            for headers in (
                {"Host": "evil.test"},
                {"Origin": "null"},
                {"Authorization": "Bearer wrong"},
                {"Sec-Fetch-Site": "cross-site"},
            ):
                self.assertIn(
                    self.call(
                        "/api/harness/projects/alpha/actions", "POST", request, headers
                    )[0],
                    (401, 403),
                )
            self.assertEqual(self.call("/api/harness/projects/missing")[0], 404)
            self.assertEqual(self.post(dict(request, root="C:/unexpected"))[0], 400)
            self.assertEqual(
                self.post(
                    dict(request, expected_revision=request["expected_revision"] + 1)
                )[0],
                409,
            )
            self.assertEqual(self.post(dict(request, index_sha256="0" * 64))[0], 409)
            self.assertEqual(
                self.call(
                    "/api/harness/projects/alpha/actions",
                    "POST",
                    b'{"key":"one","key":"two"}',
                )[0],
                400,
            )
            self.assertEqual(
                self.call("/api/harness/projects/alpha", body=b"x")[0], 400
            )
            self.assertEqual(producer.call_count, 0)
            history = json.loads(self.call()[2])
            self.assertEqual(history["history_count"], 1)
            self.assertEqual(history["history"][0]["status"], "rejected-known-unsent")

    def test_stale_http_receipt_and_get_bind_same_unsent_request(self):
        stale = self.request(key="stale-tab")
        self.assertEqual(self.post(self.request(key="other-tab"))[0], 200)
        before = json.loads(self.call()[2])
        with patch.object(
            self.service, "_produce", wraps=self.service._produce
        ) as producer:
            status, _, raw = self.post(stale)
            self.assertEqual(status, 409)
            error = json.loads(raw)
            self.assertEqual(error["error"], "stale-revision")
            receipt = error["receipt"]
            self.assertEqual(receipt["status"], "rejected-known-unsent")
            self.assertEqual(receipt["request"], stale)
            self.assertEqual(
                receipt["request_sha256"],
                sha(canonical(dict(project_ref="alpha", **stale))),
            )
            self.assertEqual(
                receipt["rejection"]["observed_revision"], before["revision"]
            )
            status, _, raw = self.call("/api/harness/projects/alpha/actions/stale-tab")
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(raw), receipt)
            status, _, raw = self.post(stale)
            self.assertEqual(status, 409)
            self.assertEqual(json.loads(raw)["receipt"], receipt)
            status, _, raw = self.post(
                dict(stale, expected_revision=before["revision"] + 1)
            )
            self.assertEqual(status, 409)
            self.assertNotIn("receipt", json.loads(raw))
            producer.assert_not_called()

    @unittest.skipUnless(shutil.which("node"), "Node.js is unavailable")
    def test_actual_http_refusal_recovers_in_real_ui_without_post(self):
        stale = self.request(key="old-tab")
        self.assertEqual(self.post(self.request(key="other-tab"))[0], 200)
        self.assertEqual(self.post(stale)[0], 409)
        final = json.loads(self.call()[2])
        fixture = self.root / "actual-refusal.json"
        fixture.write_text(
            json.dumps(dict(final=final, pending=stale, expected_records=2)),
            encoding="utf-8",
        )
        source = Path(__file__).with_name("test_harness_panel.cjs")
        panel = (
            source.parent.parent / "cli/research_workspace_native/web/harness-panel.js"
        )
        result = subprocess.run(
            [shutil.which("node"), str(source), str(panel), str(fixture)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(
            "actual offline Harness producer/refusal receipts accepted", result.stdout
        )

    def test_response_loss_recovery_is_get_only_and_deadline_is_server_owned(self):
        request = self.request()
        execute, reply = self.service.execute, AtlasHandler._reply
        observed = []

        def record(*args, **kwargs):
            observed.append(kwargs["deadline"] - time.monotonic())
            return execute(*args, **kwargs)

        def lose(handler, status, result):
            if (
                status == 200
                and isinstance(result, dict)
                and result.get("key") == "one"
            ):
                handler.close_connection = True
            else:
                reply(handler, status, result)

        with (
            patch.object(self.service, "execute", side_effect=record),
            patch.object(
                self.service, "_produce", wraps=self.service._produce
            ) as producer,
        ):
            with patch.object(AtlasHandler, "_reply", new=lose):
                with self.assertRaises(http.client.RemoteDisconnected):
                    self.post(request)
            status, _, raw = self.call("/api/harness/projects/alpha/actions/one")
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(raw)["status"], "completed")
            self.assertEqual(producer.call_count, 1)
        self.assertTrue(0 < observed[0] <= self.server.timeout_seconds)

    def test_failed_constructor_does_not_take_service_ownership_or_accept_ref_alias(
        self,
    ):
        views = deepcopy(self.views)
        views[0]["project_id"] = "another-project"
        with self.assertRaisesRegex(ValueError, "binding differs"):
            AtlasHost(
                files=self.files,
                views=views,
                credential=self.token,
                harness_ops=self.service,
            )
        self.assertFalse(self.service._closed)
        self.assertEqual(self.service.view(self.token, "alpha")["history_count"], 0)
        changed = dict(self.files)
        changed["/views/alpha/workspace-index.json"] += b"\n"
        with self.assertRaisesRegex(ValueError, "snapshot binding differs"):
            AtlasHost(
                files=changed,
                views=self.views,
                credential=self.token,
                harness_ops=self.service,
            )
        with self.assertRaises(FileExistsError):
            create_harness_operations(
                self.files, self.views, self.root / "ops", self.token
            )


if __name__ == "__main__":
    unittest.main()
