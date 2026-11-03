"""Owned loopback HTTP material tests; no production Host or model calls."""

import base64
import hashlib
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "plugins/auto-research-agent/cli"))

# These test-owned imports require the checkout's CLI path configured above.
from materials_http import install_materials  # noqa: E402
from research_workspace_native.session_api import SessionApiError  # noqa: E402
from research_workspace_native.project_stage3_http import handle_planning  # noqa: E402


def synthetic_payload(size):
    pattern = '界😀"\\\n'.encode("utf8")
    return pattern * (size // len(pattern)) + b"x" * (size % len(pattern))


class MaterialRequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if handle_planning(self, "GET") is False:
            self._reply(404, {"error": "unknown-test-route"})

    def do_POST(self):
        if handle_planning(self, "POST") is False:
            self._reply(404, {"error": "unknown-test-route"})

    def _headers(self, method):
        token = self.headers.get("Authorization", "").removeprefix("Bearer ")
        length = int(self.headers.get("Content-Length", "0"))
        if length > 262144:
            raise SessionApiError("owned-test-request-too-large", 413)
        return token, length

    def _remaining(self):
        return 30

    def _reply(self, status, body):
        data = json.dumps(body, ensure_ascii=True).encode("utf8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


class MaterialsHttpHarness:
    """Serve the actual material routes against a new test-owned SQLite store."""

    def __init__(self, root, *, transport=None, project_owners=None):
        self.root = Path(root).resolve()
        self.host = ThreadingHTTPServer(("127.0.0.1", 0), MaterialRequestHandler)
        self.host.authenticate = lambda token: {
            "owned": "owned-principal",
            "foreign": "foreign-principal",
        }.get(token)
        self.host.project_stage3_http = transport
        self.host.views = []
        self.project_reads = []

        def read(credential, ref):
            self.project_reads.append((credential, ref))
            if ref not in {"authored-ref", "foreign-ref"}:
                raise SessionApiError("project-not-found", 404)
            if project_owners is not None and project_owners.get(ref) != credential:
                raise SessionApiError("project-owner-differs", 403)
            return {"project_ref": ref}

        self.store = install_materials(
            self.host, SimpleNamespace(read=read), self.root, self.root / "incoming"
        )
        self.thread = threading.Thread(
            target=self.host.serve_forever, kwargs={"poll_interval": 0.01}
        )
        self.thread.start()
        self.closed = False

    def close(self):
        if self.closed:
            return
        self.closed = True
        self.host.shutdown()
        self.host.server_close()
        self.thread.join(5)
        if self.thread.is_alive():
            raise AssertionError("owned material HTTP server did not stop")

    def request(self, operation, body=None, *, credential="owned"):
        connection = HTTPConnection(*self.host.server_address, timeout=30)
        data = None if body is None else json.dumps(body).encode("utf8")
        try:
            connection.request(
                "GET" if body is None else "POST",
                operation if operation.startswith("/") else "/api/v9/" + operation,
                body=data,
                headers={
                    "Authorization": "Bearer " + credential,
                    "Content-Type": "application/json",
                },
            )
            response = connection.getresponse()
            payload = response.read()
            return response.status, payload
        finally:
            connection.close()

    def post(self, operation, body, *, credential="owned"):
        status, data = self.request(operation, body, credential=credential)
        value = json.loads(data)
        if status != 200:
            raise AssertionError((operation, status, value))
        return value

    def start_body(self, data, *, name="materials.txt", project_ref="authored-ref"):
        return dict(
            project_ref=project_ref,
            stage=3,
            name=name,
            bytes=len(data),
            sha256=hashlib.sha256(data).hexdigest(),
            purpose="stage3-planning-material",
        )

    def chunk(self, identity, data, offset, *, credential="owned"):
        return self.post(
            "upload/chunk",
            dict(
                id=identity,
                offset=offset,
                base64=base64.b64encode(data).decode("ascii"),
            ),
            credential=credential,
        )

    def upload(
        self, data, *, name="materials.txt", project_ref="authored-ref", finish=True
    ):
        item = self.post(
            "upload/start", self.start_body(data, name=name, project_ref=project_ref)
        )
        stop = len(data) if finish else min(len(data) - 1, 128 * 1024)
        for offset in range(item["received"], stop, 128 * 1024):
            item = self.chunk(
                item["id"], data[offset : min(offset + 128 * 1024, stop)], offset
            )
        return self.post("upload/finish", {"id": item["id"]}) if finish else item


class Stage3MaterialCapacityTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve() / "materials"
        self.http = MaterialsHttpHarness(self.root)
        self.addCleanup(self.http.close)

    def test_upload_resume_preserves_identity_purpose_and_exact_bytes(self):
        data = synthetic_payload(300000)
        body = self.http.start_body(data)
        item = self.http.post("upload/start", body)
        first = self.http.chunk(item["id"], data[:131072], 0)
        self.http.close()
        self.http = MaterialsHttpHarness(self.root)
        self.addCleanup(self.http.close)
        resumed = self.http.post("upload/start", body)
        self.assertEqual(resumed, first)
        self.assertEqual(self.http.chunk(item["id"], data[:131072], 0), resumed)
        for offset in range(resumed["received"], len(data), 131072):
            self.http.chunk(item["id"], data[offset : offset + 131072], offset)
        saved = self.http.post("upload/finish", {"id": item["id"]})
        self.assertEqual(self.http.post("upload/start", body), saved)
        self.assertEqual(self.http.post("upload/finish", {"id": saved["id"]}), saved)
        status, readback = self.http.request("files/" + saved["id"])
        self.assertEqual((status, readback), (200, data))
        self.assertEqual(saved["sha256"], hashlib.sha256(readback).hexdigest())
        generic = self.http.post(
            "upload/start",
            {key: value for key, value in body.items() if key != "purpose"},
        )
        self.assertNotEqual(generic["id"], saved["id"])
        self.assertFalse(saved["execution_authorized"])

    def test_existing_128mib_limit_rejects_oversize_before_registration(self):
        before = self.http.store.catalog()
        body = self.http.start_body(b"a")
        body["bytes"] = 128 * 1024 * 1024 + 1
        status, payload = self.http.request("upload/start", body)
        self.assertEqual(status, 409)
        self.assertEqual(json.loads(payload)["error"], "file-exceeds-128MiB")
        self.assertEqual(self.http.store.catalog(), before)
        self.assertEqual(list((self.root / "files").iterdir()), [])

    def test_abort_removes_incomplete_chunks_and_retains_aborted_identity(self):
        data = synthetic_payload(4000)
        item = self.http.upload(data, finish=False)
        aborted = self.http.post("upload/abort", {"id": item["id"]})
        self.assertEqual((aborted["status"], aborted["received"]), ("aborted", 0))
        self.assertEqual(self.http.post("upload/abort", {"id": item["id"]}), aborted)
        with self.http.store.connect() as db:
            self.assertEqual(
                db.execute(
                    "SELECT COUNT(*) FROM chunks WHERE id=?", (item["id"],)
                ).fetchone()[0],
                0,
            )
        self.assertEqual(self.http.store.catalog()["materials"], [aborted])
        status, _ = self.http.request("upload/finish", {"id": item["id"]})
        self.assertEqual(status, 409)
        self.assertEqual(list((self.root / "files").iterdir()), [])

    def test_authenticated_material_routes_enforce_stored_project_owner_and_hide_foreign_catalog(
        self,
    ):
        self.http.close()
        self.http = MaterialsHttpHarness(
            self.root,
            project_owners={"authored-ref": "owned", "foreign-ref": "foreign"},
        )
        self.addCleanup(self.http.close)
        data = synthetic_payload(4000)
        complete = self.http.upload(data, name="owned-complete.txt")
        incomplete = self.http.upload(data, name="owned-incomplete.txt", finish=False)
        foreign = self.http.post(
            "upload/start",
            self.http.start_body(data, project_ref="foreign-ref"),
            credential="foreign",
        )
        self.http.chunk(foreign["id"], data[:100], 0, credential="foreign")
        self.http.post("upload/abort", {"id": foreign["id"]}, credential="foreign")
        self.http.post(
            "draft",
            dict(id=foreign["id"], revision=0, target_stage=3, note="Foreign draft"),
            credential="foreign",
        )
        self.http.post(
            "draft",
            dict(id=complete["id"], revision=0, target_stage=3, note="Owned draft"),
        )
        cases = (
            ("files/" + complete["id"], None),
            (
                "upload/chunk",
                dict(
                    id=incomplete["id"],
                    offset=incomplete["received"],
                    base64=base64.b64encode(data[incomplete["received"] :]).decode(
                        "ascii"
                    ),
                    project_ref="foreign-ref",
                ),
            ),
            ("upload/finish", dict(id=complete["id"], project_ref="foreign-ref")),
            ("upload/abort", dict(id=incomplete["id"], project_ref="foreign-ref")),
        )
        before = self.http.store.catalog()
        for operation, body in cases:
            with self.subTest(operation=operation):
                reads = len(self.http.project_reads)
                status, payload = self.http.request(
                    operation, body, credential="foreign"
                )
                self.assertEqual(status, 403)
                self.assertEqual(json.loads(payload)["error"], "project-owner-differs")
                self.assertIn(
                    ("foreign", "authored-ref"), self.http.project_reads[reads:]
                )
                self.assertEqual(self.http.store.catalog(), before)
        self.assertEqual(self.http.request("files/" + complete["id"]), (200, data))
        for credential, expected_ref in (
            ("owned", "authored-ref"),
            ("foreign", "foreign-ref"),
        ):
            status, payload = self.http.request("materials", credential=credential)
            self.assertEqual(status, 200, "both independent principals authenticate")
            catalog = json.loads(payload)
            self.assertTrue(catalog["materials"])
            self.assertTrue(catalog["drafts"])
            for section in ("materials", "operations", "drafts"):
                self.assertTrue(
                    all(row["project_ref"] == expected_ref for row in catalog[section])
                )
            if credential == "foreign":
                self.assertEqual(len(catalog["operations"]), 1)
                self.assertEqual(catalog["operations"][0]["upload_id"], foreign["id"])
            else:
                self.assertEqual(catalog["operations"], [])

    def test_explicit_canceled_upload_restart_retains_abort_history_and_rejects_stale_abort(
        self,
    ):
        data = synthetic_payload(4000)
        body = self.http.start_body(data)
        item = self.http.upload(data, finish=False)
        self.assertEqual(item["upload_attempt"], 1)
        abort = {"id": item["id"], "expected_generation": 1}
        aborted = self.http.post("upload/abort", abort)
        history = self.http.store.catalog()["operations"]
        self.assertEqual(len(history), 1)
        self.assertEqual(
            {
                key: history[0][key]
                for key in (
                    "kind",
                    "upload_id",
                    "project_ref",
                    "upload_attempt",
                    "received",
                    "sha256",
                )
            },
            dict(
                kind="manual-upload-abort",
                upload_id=item["id"],
                project_ref="authored-ref",
                upload_attempt=1,
                received=item["received"],
                sha256=body["sha256"],
            ),
        )
        self.assertFalse(history[0]["execution_authorized"])
        self.assertEqual(self.http.post("upload/abort", abort), aborted)
        self.assertEqual(self.http.store.catalog()["operations"], history)
        self.assertEqual(self.http.post("upload/start", body), aborted)
        restart = {**body, "restart_aborted": True}
        restarted = self.http.post("upload/start", restart)
        self.assertEqual(
            (
                restarted["id"],
                restarted["status"],
                restarted["received"],
                restarted["upload_attempt"],
            ),
            (item["id"], "uploading", 0, 2),
        )
        self.assertEqual(self.http.post("upload/start", restart), restarted)
        self.http.close()
        self.http = MaterialsHttpHarness(self.root)
        self.addCleanup(self.http.close)
        self.assertEqual(self.http.post("upload/start", restart), restarted)
        before = self.http.store.catalog()
        status, payload = self.http.request("upload/abort", abort)
        self.assertEqual(status, 409)
        self.assertEqual(json.loads(payload)["error"], "upload-generation-differs")
        self.assertEqual(self.http.store.catalog(), before)
        prefix = self.http.chunk(item["id"], data[:2000], 0)
        self.assertEqual(self.http.post("upload/start", restart), prefix)
        self.http.chunk(item["id"], data[2000:], 2000)
        saved = self.http.post("upload/finish", {"id": item["id"]})
        self.assertEqual(
            (saved["id"], saved["status"], saved["upload_attempt"]),
            (item["id"], "registered", 2),
        )
        self.assertEqual(self.http.request("files/" + item["id"]), (200, data))
        self.assertEqual(self.http.store.catalog()["operations"], history)

    def test_atomic_publication_recovers_after_registry_write_interruption(self):
        data = synthetic_payload(4000)
        item = self.http.post("upload/start", self.http.start_body(data))
        self.http.chunk(item["id"], data, 0)
        original_put = self.http.store._put

        def fail_registration(table, identity, value):
            if table == "materials" and value.get("status") == "registered":
                raise OSError("authored interruption after atomic publication")
            return original_put(table, identity, value)

        with patch.object(self.http.store, "_put", fail_registration):
            status, payload = self.http.request("upload/finish", {"id": item["id"]})
        self.assertEqual(status, 409)
        self.assertIn("authored interruption", json.loads(payload)["error"])
        path = self.root / "files" / (item["id"] + ".bin")
        self.assertEqual(path.read_bytes(), data)
        self.assertEqual(
            self.http.store.catalog()["materials"][0]["status"], "uploading"
        )
        self.http.close()
        self.http = MaterialsHttpHarness(self.root)
        self.addCleanup(self.http.close)
        saved = self.http.post("upload/finish", {"id": item["id"]})
        self.assertEqual(saved["status"], "registered")
        self.assertEqual(self.http.request("files/" + item["id"]), (200, data))
        self.assertEqual(list(path.parent.iterdir()), [path])

    def test_finalization_never_overwrites_conflicting_published_bytes(self):
        data = b"An authored complete file."
        item = self.http.post("upload/start", self.http.start_body(data))
        self.http.chunk(item["id"], data, 0)
        path = self.root / "files" / (item["id"] + ".bin")
        path.write_bytes(b"Conflicting existing bytes.")
        status, payload = self.http.request("upload/finish", {"id": item["id"]})
        self.assertEqual(status, 409)
        self.assertEqual(json.loads(payload)["error"], "material-file-conflict")
        self.assertEqual(path.read_bytes(), b"Conflicting existing bytes.")
        self.assertEqual(
            self.http.store.catalog()["materials"][0]["status"], "uploading"
        )


class Stage3MaterialNodeTests(unittest.TestCase):
    def test_complete_file_controls_and_versioned_requests(self):
        node = shutil.which("node")
        self.assertIsNotNone(node, "Node is required for material UI integration")
        result = subprocess.run(
            [node, "--test", str(REPO / "harness-ui/test_v9_stage3_materials.cjs")],
            cwd=REPO,
            capture_output=True,
            text=True,
            encoding="utf8",
            timeout=30,
        )
        print(result.stdout, end="")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
