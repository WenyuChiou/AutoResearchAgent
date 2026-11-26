"""Exercise the normal loopback transport with an explicit engineering application."""

# ruff: noqa: E402 -- import the verified local ProjectHost alongside the Wiki.
import base64
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import json
from pathlib import Path
import secrets
import socket
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

from materials_http import install_materials

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "plugins/auto-research-agent/cli"))
from research_workspace_native.http import token_authenticator
from research_workspace_native.project_host import ProjectHost
from research_workspace_native.project_intake import ProjectIntakeService
from research_workspace_native.project_stage1 import ProjectStage1Service
from saved_candidate_admission import ACTION, INTENT, ROUTE, SCOPE
from stage1_ledger.journal import canonical, digest


DATA = b"Local engineering fixture. No original publication was acquired."
WORK = "work-" + "3" * 64
VERSION = "version-" + "4" * 64


class EngineeringApplication(ProjectStage1Service):
    """Retain an actual ProjectIntake action, with a synthetic ledger and writer."""

    def __init__(self, projects, evidence):
        super().__init__(projects)
        self.evidence = evidence

    @staticmethod
    def ledger_state(project_ref, revision):
        return digest(canonical(["engineering", project_ref, revision]))

    def read(self, credential, project_ref):
        view = super().read(credential, project_ref)
        view["ledger"] = {
            "valid": True,
            "state_sha256": self.ledger_state(project_ref, view["revision"]),
        }
        return view

    def admit_saved_candidate(
        self, credential, project_ref, body, *, materials_root, check_deadline
    ):
        assert (materials_root / body["source_relative"]).read_bytes() == DATA
        assert body["source_project_ref"] == project_ref
        assert body["confirmed"] is True and "actor" not in body
        self.evidence["requests"].append(body.copy())
        if self.evidence.get("entered") is not None:
            self.evidence["entered"].set()
            assert self.evidence["release"].wait(10)
        if self.evidence.get("unobserved"):
            raise OSError("Isolated lost application response")

        def work(state, *_):
            if self.evidence.get("mutate_application_body"):
                # _perform has already hashed and saved the original intent.
                body.update(
                    work_id="work-" + "5" * 64, version_id="version-" + "6" * 64
                )
            result = dict(
                work_id=body["work_id"],
                version_id=body["version_id"],
                event_id="e000001",
                reused=False,
            )
            if self.evidence.get("receipt_includes_result_state"):
                revision = state["revision"] + 1
                result.update(
                    revision=revision,
                    ledger_state_sha256=self.ledger_state(project_ref, revision),
                )
            return result

        return self.intake._perform(
            self.intake._principal(credential),
            project_ref,
            ACTION,
            body,
            work,
            check_deadline=check_deadline,
        )


class SavedCandidateHttpTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="h516-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.incoming = self.root / "incoming"
        self.incoming.mkdir()
        self.token = secrets.token_urlsafe(32)
        self.provenance = {}
        self.evidence = {"requests": []}
        with self.running() as _:
            self.ref = self.create("one")
            self.other = self.create("two")
            self.material = self.upload(self.ref)
            self.binding = self.current(self.ref, self.material)
        self.provenance[self.material] = {
            "binding": {key: self.binding[key] for key in SCOPE},
            "source_uri": "https://example.invalid/authored-engineering-record",
            "original_type": "text/html",
            "record": {"title": "Synthetic work", "version": "engineering-v1"},
            "work_id": WORK,
            "version_id": VERSION,
            "reason": "Engineering-only trusted input for the transport control",
        }

    @contextmanager
    def running(self, *, writer=False, synthetic_view=True):
        self.projects = ProjectIntakeService(
            self.root / "projects",
            authenticate=token_authenticator({self.token: "local-viewer"}),
        )
        stage1 = (
            EngineeringApplication(self.projects, self.evidence)
            if synthetic_view
            else ProjectStage1Service(self.projects)
        )
        self.host = ProjectHost(
            projects=self.projects,
            credential=self.token,
            stage1=stage1,
            files={},
            views=[],
            port=0,
        )
        install_materials(
            self.host,
            self.projects,
            self.root / "materials",
            self.incoming,
            saved_candidate_application=stage1 if writer else None,
            saved_candidate_provenance=self.provenance if writer else None,
        )
        thread = threading.Thread(target=self.host.serve_forever)
        thread.start()
        try:
            yield self.host.expected_origin
        finally:
            self.host.shutdown()
            thread.join(10)
            self.assertFalse(thread.is_alive())
            self.host.server_close()
            self.projects.close()

    def http(self, path, body=None, *, token=True, as_json=True, origin=None):
        headers = {
            "Sec-Fetch-Site": "same-origin",
            "Origin": origin or self.host.expected_origin,
        }
        if token:
            headers["Authorization"] = "Bearer " + self.token
        raw = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            raw = json.dumps(body).encode("utf-8")
        request = Request(self.host.expected_origin + path, data=raw, headers=headers)
        try:
            response = urlopen(request, timeout=15)
        except HTTPError as error:
            response = error
        with response:
            data = response.read()
            return response.status, json.loads(data) if as_json else data

    def create(self, key):
        status, value = self.http(
            "/api/projects", {"key": key, "topic": "Synthetic input"}
        )
        self.assertEqual(status, 200)
        return value["project_ref"]

    def upload(self, ref, *, name="operator-copy.csv"):
        status, value = self.http(
            "/api/v9/upload/start",
            {
                "project_ref": ref,
                "name": name,
                "stage": 1,
                "bytes": len(DATA),
                "sha256": digest(DATA),
            },
        )
        self.assertEqual(status, 200)
        identity = value["id"]
        self.assertEqual(
            self.http(
                "/api/v9/upload/chunk",
                {
                    "id": identity,
                    "offset": 0,
                    "base64": base64.b64encode(DATA).decode("ascii"),
                },
            )[0],
            200,
        )
        self.assertEqual(self.http("/api/v9/upload/finish", {"id": identity})[0], 200)
        return identity

    def current(self, ref, material):
        status, view = self.http("/api/projects/" + ref + "/overview")
        self.assertEqual(status, 200)
        project = view["project"]
        ledger = view["stage1"]["ledger"]
        return dict(
            project_ref=ref,
            input_version=project["input_version"],
            revision=project["revision"],
            brief_sha256=project["brief_sha256"],
            ledger_state_sha256=ledger["state_sha256"] if ledger else None,
            material_id=material,
            material_sha256=digest(DATA),
        )

    def query(self, operation, field, value, **kwargs):
        return self.http(
            ROUTE + operation + "?" + urlencode({field: json.dumps(value)}), **kwargs
        )

    def offer(self, binding=None, **kwargs):
        return self.query(
            "offer", "binding", self.binding if binding is None else binding, **kwargs
        )

    def intent(self):
        status, answer = self.offer()
        self.assertEqual((status, answer["status"]), (200, "available"))
        self.assertEqual(answer["offer"]["operation"], "admit-saved-candidate")
        self.assertFalse(answer["offer"]["execution_authorized"])
        self.assertNotIn("confirmed", answer["offer"])
        return dict(
            {key: exposed for key, exposed in answer["offer"].items() if key in INTENT},
            confirmed=True,
        )

    def submit(self, intent, **kwargs):
        return self.http(ROUTE + "submit", intent, **kwargs)

    def recover(self, intent):
        return self.query("read", "intent", intent)

    def test_default_stage1_and_unverified_upload_remain_readable(self):
        with self.running(synthetic_view=False):
            binding = self.current(self.ref, self.material)
            status, result = self.offer(binding)
            self.assertEqual(
                (status, result["status"], result["reason"]),
                (
                    200,
                    "unavailable",
                    "saved-candidate-admission-unconnected",
                ),
            )
            self.assertTrue(
                {"source_uri", "original_type", "record"}.issubset(result["missing"])
            )
            self.assertEqual(
                self.http("/api/v9/files/" + self.material, as_json=False), (200, DATA)
            )
        with self.running(writer=True):
            material = self.upload(self.ref, name="unverified-copy.pdf")
            status, _ = self.http(
                "/api/v9/draft",
                {
                    "id": material,
                    "target_stage": 2,
                    "revision": 0,
                    "note": "Operator note mentions https://example.invalid/claimed-publication and text/html.",
                },
            )
            self.assertEqual(status, 200)
            status, result = self.offer(self.current(self.ref, material))
            self.assertEqual(
                (status, result["reason"]),
                (200, "saved-candidate-provenance-incomplete"),
            )
            self.assertTrue(
                {"source_uri", "original_type", "record"}.issubset(result["missing"])
            )
        self.assertEqual(self.evidence["requests"], [])

    def test_concurrent_same_intent_and_reopen_after_its_own_state_advance(self):
        entered, release = threading.Event(), threading.Event()
        self.evidence.update(entered=entered, release=release)
        with self.running(writer=True):
            intent = self.intent()
            self.assertEqual(self.intent(), intent)
            self.assertEqual(self.evidence["requests"], [])
            with ThreadPoolExecutor(1) as executor:
                request = executor.submit(self.submit, intent)
                try:
                    self.assertTrue(entered.wait(10))
                    self.assertEqual(
                        self.submit(intent)[1]["status"], "execution-unknown"
                    )
                    self.assertEqual(self.offer()[1]["intent"], intent)
                finally:
                    release.set()
                status, saved = request.result(timeout=10)
            self.assertEqual((status, saved["status"]), (200, "saved"))
            self.assertEqual(
                {
                    k: saved[k]
                    for k in (
                        "candidate_event_id",
                        "provenance",
                        "identity_status",
                        "screening_status",
                        "reading_evidence",
                        "execution_authorized",
                    )
                },
                {
                    "candidate_event_id": "e000001",
                    "provenance": "provided",
                    "identity_status": "unverified",
                    "screening_status": "not-screened",
                    "reading_evidence": None,
                    "execution_authorized": False,
                },
            )
            [body] = self.evidence["requests"]
            self.assertTrue(
                {"record", "source_uri", "source_relative", "work_id", "version_id"}
                <= set(body)
            )
            logged = self.projects.history(self.token, self.ref)["actions"]
            [action] = [row for row in logged if row["kind"] == ACTION]
            self.assertEqual(action["request_sha256"], intent["request_sha256"])
            expected = {
                "kind": ACTION,
                "body": {k: v for k, v in body.items() if k != "revision"},
            }
            self.assertEqual(digest(canonical(expected)), intent["request_sha256"])
            current = self.current(self.ref, self.material)
            self.assertGreater(current["revision"], self.binding["revision"])
            self.assertNotEqual(
                current["ledger_state_sha256"], self.binding["ledger_state_sha256"]
            )
            self.assertEqual(self.submit(intent)[0], 409)
        with self.running(synthetic_view=False):
            # A fresh, real baseline service has no writer and no synthetic ledger.
            current = self.current(self.ref, self.material)
            self.assertIsNone(current["ledger_state_sha256"])
            status, discovery = self.offer(current)
            self.assertEqual(
                (status, discovery["status"], discovery["intent"]),
                (200, "recovery", intent),
            )
            self.assertEqual(self.recover(intent), (200, saved))
            self.assertEqual(
                self.submit(intent),
                (409, {"error": "saved-candidate-admission-unconnected"}),
            )
        self.assertEqual(len(self.evidence["requests"]), 1)

    def test_disconnect_then_original_action_is_recoverable(self):
        entered, release = threading.Event(), threading.Event()
        self.evidence.update(entered=entered, release=release)
        with self.running(writer=True) as origin:
            intent = self.intent()
            raw = json.dumps(intent).encode("utf-8")
            address = urlsplit(origin)
            with socket.create_connection(
                (address.hostname, address.port), timeout=5
            ) as connection:
                header = (
                    f"POST {ROUTE}submit HTTP/1.1\r\nHost: {address.netloc}\r\nOrigin: {origin}\r\n"
                    f"Authorization: Bearer {self.token}\r\nContent-Type: application/json\r\n"
                    f"Content-Length: {len(raw)}\r\nConnection: close\r\n\r\n"
                )
                try:
                    connection.sendall(header.encode("ascii") + raw)
                    self.assertTrue(entered.wait(10))
                finally:
                    connection.close()
                    release.set()
        with self.running(synthetic_view=False):
            self.assertEqual(self.recover(intent)[1]["status"], "saved")
        self.assertEqual(len(self.evidence["requests"]), 1)

    def test_saved_action_may_include_its_resulting_revision_and_ledger_state(self):
        self.evidence["receipt_includes_result_state"] = True
        with self.running(writer=True):
            intent = self.intent()
            status, posted = self.submit(intent)
            self.assertEqual(status, 200)
            action = self.projects.action(
                self.token, intent["key"], project_ref=self.ref
            )
            current = self.current(self.ref, self.material)
            self.assertEqual(action["request_sha256"], intent["request_sha256"])
            self.assertEqual(action["revision"], current["revision"])
            self.assertEqual(
                action["ledger_state_sha256"], current["ledger_state_sha256"]
            )
            self.assertGreater(action["revision"], intent["revision"])
            self.assertNotEqual(
                action["ledger_state_sha256"], intent["ledger_state_sha256"]
            )
        with self.running(synthetic_view=False):
            status, reopened = self.recover(intent)
            self.assertEqual(status, 200)
        self.assertEqual(len(self.evidence["requests"]), 1)
        self.assertEqual([posted["status"], reopened["status"]], ["saved", "saved"])
        for receipt in (posted, reopened):
            self.assertEqual(receipt["revision"], intent["revision"])
            self.assertEqual(
                receipt["ledger_state_sha256"], intent["ledger_state_sha256"]
            )

    def test_mutated_application_body_does_not_authenticate_a_wrong_work_receipt(self):
        self.evidence["mutate_application_body"] = True
        with self.running(writer=True):
            intent = self.intent()
            status, posted = self.submit(intent)
            self.assertEqual(status, 200)
            action = self.projects.action(
                self.token, intent["key"], project_ref=self.ref
            )
            self.assertEqual(action["request_sha256"], intent["request_sha256"])
            self.assertEqual(action["status"], "saved")
            self.assertEqual(action["work_id"], "work-" + "5" * 64)
            self.assertEqual(action["version_id"], "version-" + "6" * 64)
        with self.running(synthetic_view=False):
            status, reopened = self.recover(intent)
            self.assertEqual(status, 200)
        self.assertEqual(len(self.evidence["requests"]), 1)
        self.assertEqual(
            [posted["status"], reopened["status"]],
            ["execution-unknown", "execution-unknown"],
        )

    def test_unknown_across_restart_only_reads_original_action(self):
        self.evidence["unobserved"] = True
        with self.running(writer=True):
            intent = self.intent()
            self.assertEqual(self.submit(intent)[1]["status"], "execution-unknown")
        with self.running(writer=True):
            self.assertEqual(self.offer()[1]["intent"], intent)
            self.assertEqual(self.recover(intent)[1]["status"], "execution-unknown")
            self.assertEqual(self.submit(intent)[1]["status"], "execution-unknown")
            self.assertEqual(
                self.submit(dict(intent, key="saved-candidate-" + "9" * 32))[0], 409
            )
            self.assertEqual(
                self.projects.history(self.token, self.ref)["actions"][-1]["kind"],
                "create",
            )
        self.assertEqual(len(self.evidence["requests"]), 1)

    def test_rejects_untrusted_parameter_and_current_project_mismatches(self):
        with self.running(writer=True):
            intent = self.intent()
            self.assertEqual(self.offer(token=False)[0], 401)
            self.assertEqual(self.submit(intent, token=False)[0], 401)
            self.assertEqual(self.submit(intent, origin="http://127.0.0.1:1")[0], 403)
            status, other = self.offer(self.current(self.other, self.material))
            self.assertEqual(
                (status, other["error"]),
                (409, "saved-candidate-material-project-differs"),
            )
            for operation, body, expected in (
                (
                    "offer",
                    dict(
                        self.binding, input_version=str(self.binding["input_version"])
                    ),
                    409,
                ),
                ("offer", dict(self.binding, ledger_state_sha256="0" * 64), 409),
                (
                    "offer",
                    dict(self.binding, revision=self.binding["revision"] + 1),
                    409,
                ),
                (
                    "submit",
                    dict(intent, input_version=str(intent["input_version"])),
                    409,
                ),
                ("submit", dict(intent, input_version=True), 400),
                ("submit", dict(intent, confirmed=False), 400),
                (
                    "submit",
                    dict(intent, source_uri="https://example.invalid/new-claim"),
                    400,
                ),
                ("submit", dict(intent, materials_root="client-path"), 400),
                ("submit", dict(intent, request_sha256="0" * 64), 409),
                ("submit", dict(intent, material_sha256="5" * 64), 409),
            ):
                with self.subTest(
                    operation=operation, expected=expected, keys=list(body)
                ):
                    call = self.offer if operation == "offer" else self.submit
                    self.assertEqual(call(body)[0], expected)
            path = self.root / "materials" / "files" / (self.material + ".bin")
            path.write_bytes(DATA + b"changed")
            self.assertEqual(self.submit(intent)[0], 409)
        self.assertEqual(self.evidence["requests"], [])

    def test_bad_receipts_do_not_promote_a_pending_or_previous_result(self):
        with self.running(writer=True):
            intent = self.intent()
            self.assertEqual(self.submit(intent)[1]["status"], "saved")
            original_action = self.projects.action(
                self.token, intent["key"], project_ref=self.ref
            )
            for invalid in (
                dict(original_action, request_sha256="0" * 64),
                dict(original_action, project_ref=self.other),
                dict(original_action, input_version=str(intent["input_version"])),
                dict(original_action, work_id="work-" + "0" * 64),
                dict(original_action, event_id="fabricated"),
                dict(original_action, execution_authorized=True),
            ):
                with self.subTest(keys=list(invalid)):
                    with patch.object(self.projects, "action", return_value=invalid):
                        status, answer = self.recover(intent)
                    self.assertEqual(
                        (status, answer["status"]), (200, "execution-unknown")
                    )
                    self.assertNotIn("candidate_event_id", answer)
            wrong_version = dict(intent, input_version=str(intent["input_version"]))
            self.assertEqual(self.recover(wrong_version)[0], 409)
            self.assertEqual(self.recover(dict(intent, brief_sha256="0" * 64))[0], 409)
            self.assertEqual(
                self.recover(dict(intent, request_sha256="0" * 64))[0], 404
            )
            path = self.root / "materials" / "files" / (self.material + ".bin")
            path.write_bytes(DATA + b"changed")
            self.assertEqual(self.recover(intent)[0], 409)
            path.write_bytes(DATA)
            self.assertEqual(self.recover(intent)[1]["status"], "saved")
        self.assertEqual(len(self.evidence["requests"]), 1)


if __name__ == "__main__":
    unittest.main()
