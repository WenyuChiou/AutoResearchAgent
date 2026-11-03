"""Synthetic project access checks over owned material HTTP sockets."""

import base64
import hashlib
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "plugins/auto-research-agent/cli"))

from materials_http import install_materials  # noqa: E402
from research_workspace_native.session_api import SessionApiError  # noqa: E402


def synthetic_payload(size):
    pattern = '界😀"\\\n'.encode("utf8")
    return pattern * (size // len(pattern)) + b"x" * (size % len(pattern))


class MaterialRequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.optional_planning("GET")

    def do_POST(self):
        self.optional_planning("POST")

    def optional_planning(self, method):
        if getattr(self.server, "project_stage3_http", None) is not None:
            from research_workspace_native.project_stage3_http import handle_planning

            if handle_planning(self, method) is not False:
                return
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
    """Actual material routes with synthetic principals and project reads."""

    def __init__(self, root, *, transport=None, project_owners=None):
        self.root = Path(root).resolve()
        self.host = ThreadingHTTPServer(("127.0.0.1", 0), MaterialRequestHandler)
        self.host.authenticate = lambda token: {
            "owned": "owned-principal",
            "foreign": "foreign-principal",
        }.get(token)
        self.host.project_stage3_http = transport
        self.host.views = []
        self.project_reads, self.read_failures = [], {}
        known = {"authored-ref", "foreign-ref"} | set(project_owners or {})

        def read(credential, ref):
            self.project_reads.append((credential, ref))
            if ref not in known:
                raise SessionApiError("project-not-found", 404)
            if project_owners is not None and project_owners.get(ref) != credential:
                raise SessionApiError("project-owner-differs", 403)
            if ref in self.read_failures:
                raise self.read_failures[ref]
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
            return response.status, response.read()
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
        self,
        data,
        *,
        name="materials.txt",
        project_ref="authored-ref",
        finish=True,
        credential="owned",
    ):
        item = self.post(
            "upload/start",
            self.start_body(data, name=name, project_ref=project_ref),
            credential=credential,
        )
        stop = len(data) if finish else min(len(data) - 1, 128 * 1024)
        for offset in range(item["received"], stop, 128 * 1024):
            item = self.chunk(
                item["id"],
                data[offset : min(offset + 128 * 1024, stop)],
                offset,
                credential=credential,
            )
        return (
            self.post("upload/finish", {"id": item["id"]}, credential=credential)
            if finish
            else item
        )


class MaterialProjectAccessTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.http = MaterialsHttpHarness(
            Path(temporary.name) / "materials",
            project_owners={
                "authored-ref": "owned",
                "unreadable-ref": "owned",
                "foreign-ref": "foreign",
            },
        )
        self.addCleanup(self.http.close)

    def synthetic_catalog_records(self, material):
        """Explicit access fixtures, not workflow outcomes or science receipts."""
        operation = dict(
            id="synthetic-op-" + material["id"],
            project_ref=material["project_ref"],
            kind="synthetic-access-fixture",
        )
        self.http.store._put("operations", operation["id"], operation)
        draft = dict(
            id=material["id"],
            project_ref=material["project_ref"],
            revision=1,
            kind="synthetic-access-fixture",
        )
        with self.http.store.connect() as db:
            db.execute(
                "INSERT INTO drafts VALUES (?,?,?)", (draft["id"], 1, json.dumps(draft))
            )

    def filtered_catalog(self, catalog, refs):
        result = dict(catalog)
        for section in ("materials", "operations", "drafts"):
            result[section] = [
                row for row in catalog[section] if row["project_ref"] in refs
            ]
        return result

    def test_stored_owner_controls_file_reads_writes_and_all_catalog_sections(self):
        data = synthetic_payload(4000)
        complete = self.http.upload(data, name="owned-complete.txt")
        incomplete = self.http.upload(data, name="owned-incomplete.txt", finish=False)
        foreign = self.http.upload(
            data, project_ref="foreign-ref", credential="foreign"
        )
        for material in (complete, foreign):
            self.synthetic_catalog_records(material)
        before = self.http.store.catalog()
        cases = (
            ("files/" + complete["id"], None),
            (
                "upload/chunk",
                dict(
                    id=incomplete["id"],
                    project_ref="foreign-ref",
                    offset=incomplete["received"],
                    base64=base64.b64encode(data[incomplete["received"] :]).decode(
                        "ascii"
                    ),
                ),
            ),
            ("upload/finish", dict(id=complete["id"], project_ref="foreign-ref")),
        )
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
        for credential, ref in (("owned", "authored-ref"), ("foreign", "foreign-ref")):
            status, payload = self.http.request("materials", credential=credential)
            self.assertEqual(status, 200, "both independent principals authenticate")
            self.assertEqual(json.loads(payload), self.filtered_catalog(before, {ref}))
        self.assertEqual(self.http.store.catalog(), before)

    def test_unreadable_owned_project_does_not_poison_readable_catalog(self):
        for ref, credential in (
            ("authored-ref", "owned"),
            ("unreadable-ref", "owned"),
            ("foreign-ref", "foreign"),
        ):
            material = self.http.upload(
                synthetic_payload(100), project_ref=ref, credential=credential
            )
            self.synthetic_catalog_records(material)
        before = self.http.store.catalog()
        expected = self.filtered_catalog(before, {"authored-ref", "unreadable-ref"})
        status, payload = self.http.request("materials")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(payload), expected)
        for failure in (
            FileNotFoundError("synthetic missing project brief"),
            OSError("synthetic unreadable project brief"),
        ):
            with self.subTest(error=type(failure).__name__):
                self.http.read_failures["unreadable-ref"] = failure
                status, payload = self.http.request("materials")
                self.assertEqual(status, 200, payload.decode("utf8"))
                self.assertEqual(
                    json.loads(payload), self.filtered_catalog(before, {"authored-ref"})
                )
                self.assertEqual(self.http.store.catalog(), before)
                del self.http.read_failures["unreadable-ref"]
                status, payload = self.http.request("materials")
                self.assertEqual(status, 200)
                self.assertEqual(json.loads(payload), expected)
                self.assertEqual(self.http.store.catalog(), before)


if __name__ == "__main__":
    unittest.main(verbosity=2)
