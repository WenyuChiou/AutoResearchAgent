"""Actual bounded HTTP reads over saved Core/SQLite screening, no live calls."""

import http.client
import json
from pathlib import Path
import sys
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cli"))

from research_workspace_native.project_host import ProjectHost
from stage1_deliverable.common import sha
from stage1_ledger.journal import canonical
from test_project_stage1_library import Stage1LibraryFixture, library_authenticate


OTHER_TOKEN = "other-library-test-token-with-at-least-32-characters"


class ProjectStage1LibraryHttpTests(Stage1LibraryFixture, unittest.TestCase):
    def setUp(self):
        Stage1LibraryFixture.setUp(self)
        self.addCleanup(Stage1LibraryFixture.tearDown, self)
        self.host = ProjectHost(
            projects=self.intake,
            credential=self.token,
            stage1=self.stage1,
            files={},
            views=[],
            port=0,
        )
        # Trusted test bootstrap authenticates both real intake principals.
        # Projection, Core, filesystem and SQLite operations remain unchanged.
        self.host.authenticate = library_authenticate
        self.worker = threading.Thread(target=self.host.serve_forever, daemon=True)
        self.worker.start()

    def tearDown(self):
        self.host.shutdown()
        self.host.server_close()
        self.worker.join(3)
        self.assertFalse(self.worker.is_alive())

    def request(self, path, *, method="GET", raw=None, token=None, headers=None):
        supplied = {
            "Authorization": "Bearer " + (self.token if token is None else token),
        }
        if method != "GET":
            supplied["Origin"] = self.host.expected_origin
            supplied["Content-Type"] = "application/json"
        supplied.update(headers or {})
        client = http.client.HTTPConnection(
            "127.0.0.1", self.host.server_port, timeout=60
        )
        try:
            client.request(method, path, body=raw, headers=supplied)
            response = client.getresponse()
            data = response.read()
            return response.status, json.loads(data)
        finally:
            client.close()

    def get(self, path):
        status, result = self.request(path)
        self.assertEqual(status, 200, result)
        return result

    def page_path(self, envelope, offset=0, *, expected=False):
        binding = envelope["projection"]["binding"]
        path = (
            f"/api/projects/{self.ref}/stage1/screening/"
            f"{envelope['input_version']}/{binding['ledger_state_sha256']}/{offset}"
        )
        return path + "/" + envelope["projection_sha256"] if expected else path

    def detail_path(self, envelope, index):
        binding = envelope["projection"]["binding"]
        return (
            f"/api/projects/{self.ref}/stage1/screening-detail/"
            f"{envelope['input_version']}/{binding['ledger_state_sha256']}/"
            f"{envelope['projection_sha256']}/{index}"
        )

    def assert_refused(self, path, status, code=None, **kwargs):
        actual_status, result = self.request(path, **kwargs)
        self.assertEqual(actual_status, status, result)
        if code is not None:
            self.assertEqual(result["error"], code)
        self.assertNotIn("receipt", result)
        return result

    def test_real_saved_rows_exact_detail_and_overview_descriptor_are_passive(self):
        envelope = self.library.read(self.token, self.ref)
        before = self.inventory()
        overview = self.get(f"/api/projects/{self.ref}/overview")
        descriptor = overview["stage1"]["screening_library"]
        self.assertEqual(
            {
                key: descriptor[key]
                for key in (
                    "available",
                    "project_ref",
                    "input_version",
                    "ledger_state_sha256",
                    "page_size",
                )
            },
            dict(
                available=True,
                project_ref=self.ref,
                input_version=1,
                ledger_state_sha256=self.ledger.state_hash(),
                page_size=20,
            ),
        )
        self.assertNotIn("rows", descriptor)
        page = self.get(self.page_path(envelope))
        projection = envelope["projection"]
        self.assertEqual(page["projection_sha256"], envelope["projection_sha256"])
        self.assertEqual(page["binding"], projection["binding"])
        self.assertEqual(page["counts"], projection["counts"])
        self.assertEqual(page["total"], 4)
        self.assertEqual(page["offset"], 0)
        self.assertIsNone(page["next_offset"])
        self.assertEqual(
            [
                page["counts"][key]
                for key in ("include", "exclude", "pending", "not_screened")
            ],
            [1, 1, 1, 1],
        )
        self.assertEqual(page["counts"]["core"]["discoveries"], 6)
        self.assertEqual(page["counts"]["core"]["backend_failures"], 1)
        for index, summary in enumerate(page["rows"]):
            detail = self.get(self.detail_path(envelope, index))
            row = projection["rows"][index]
            self.assertEqual(detail["index"], summary["index"])
            self.assertEqual(detail["binding"], projection["binding"])
            self.assertEqual(canonical(detail["row"]), canonical(row))
            self.assertEqual(sha(canonical(detail["row"])), sha(canonical(row)))
            self.assertEqual(summary["work_id"], row["work_id"])
            self.assertEqual(summary["selected_version_id"], row["selected_version_id"])
            self.assertEqual(summary["reading"]["complete_body_reading"], "Unknown")
            self.assertIsNone(summary["relevance"]["score"])
            self.assertFalse(detail["stage1_complete"])
            self.assertFalse(detail["execution_authorized"])
            self.assertIsNone(detail["canonical_package"])
            if row["work_id"] != self.work_by_name["retained"]:
                self.assertEqual(detail["row"]["source_attempts"], [])
                self.assertEqual(detail["row"]["claims"], [])
        self.assertEqual(self.get(self.page_path(envelope)), page)
        self.assertEqual(before, self.inventory())
        self.runner.assert_not_called()

    def test_bounded_pages_preserve_all_candidates_and_one_projection(self):
        extra = [
            dict(
                self.metadata[0],
                title=f"Authored additional candidate {i}",
                doi=f"10.5555/page-{i}",
            )
            for i in range(21)
        ]
        self.query(3, extra)
        self.ledger.checkpoint()
        envelope = self.library.read(self.token, self.ref)
        before = self.inventory()
        first = self.get(self.page_path(envelope))
        second = self.get(self.page_path(envelope, 20, expected=True))
        self.assertEqual((len(first["rows"]), len(second["rows"])), (20, 5))
        self.assertEqual((first["total"], second["total"]), (25, 25))
        self.assertEqual(first["next_offset"], 20)
        self.assertIsNone(second["next_offset"])
        self.assertEqual(first["projection_sha256"], second["projection_sha256"])
        self.assertEqual(first["binding"], second["binding"])
        all_rows = first["rows"] + second["rows"]
        self.assertEqual([r["index"] for r in all_rows], list(range(25)))
        self.assertEqual(
            [r["work_id"] for r in all_rows],
            [r["work_id"] for r in envelope["projection"]["rows"]],
        )
        self.assertEqual(first["counts"]["not_screened"], 22)
        detail = self.get(self.detail_path(envelope, 24))
        self.assertEqual(detail["row"], envelope["projection"]["rows"][24])
        self.assertEqual(detail["row"]["source_attempts"], [])
        self.assert_refused(
            self.page_path(envelope, 20), 400, "stage1-library-page-projection-required"
        )
        self.assert_refused(
            self.page_path(envelope, 1, expected=True),
            400,
            "stage1-library-page-offset-invalid",
        )
        self.assert_refused(
            self.page_path(envelope, 40, expected=True),
            404,
            "stage1-library-page-out-of-range",
        )
        self.assertEqual(before, self.inventory())
        self.runner.assert_not_called()

    def test_version_state_projection_and_detail_index_refuse_without_write(self):
        envelope = self.library.read(self.token, self.ref)
        page, detail = self.page_path(envelope), self.detail_path(envelope, 0)
        before = self.inventory()
        cases = (
            (
                page.replace("/screening/1/", "/screening/2/"),
                409,
                "stage1-library-input-version-stale",
            ),
            (
                page.replace(self.ledger.state_hash(), "0" * 64),
                409,
                "stage1-library-ledger-state-stale",
            ),
            (page + "/" + "0" * 64, 409, "stage1-library-projection-stale"),
            (
                detail.replace(envelope["projection_sha256"], "0" * 64),
                409,
                "stage1-library-projection-stale",
            ),
            (self.detail_path(envelope, 4), 404, "stage1-library-detail-out-of-range"),
            (
                page.replace("/screening/1/", "/screening/0/"),
                404,
                "unknown-project-route",
            ),
            (page + "?owner=caller", 404, "unknown-project-route"),
            (detail + "?index=1", 404, "unknown-project-route"),
            (page + "/extra", 404, "unknown-project-route"),
            (self.detail_path(envelope, -1), 404, "unknown-project-route"),
        )
        for path, status, code in cases:
            with self.subTest(path=path):
                self.assert_refused(path, status, code)
        for path in (page, detail):
            for kwargs in (dict(raw=b"{}"), dict(method="POST", raw=b"{}")):
                with self.subTest(path=path, kwargs=kwargs):
                    self.assert_refused(path, 400, "invalid-project-read", **kwargs)
        self.assertEqual(before, self.inventory())
        self.runner.assert_not_called()

    def test_real_principal_project_and_transport_security_refuse_passively(self):
        foreign = self.intake.create(
            OTHER_TOKEN, {"key": "foreign", "topic": "Another user's project"}
        )["project_ref"]
        envelope = self.library.read(self.token, self.ref)
        page, detail = self.page_path(envelope), self.detail_path(envelope, 0)
        before = self.inventory()
        for path in (page, detail):
            self.assert_refused(path, 404, "project-unavailable", token=OTHER_TOKEN)
            self.assert_refused(path, 401, "credential-rejected", token="invalid")
            self.assert_refused(
                path.replace(self.ref, foreign), 404, "project-unavailable"
            )
            self.assert_refused(
                path.replace(self.ref, "missing-project"), 404, "project-unavailable"
            )
            for headers in (
                {"Host": "attacker.example"},
                {"Origin": "null"},
                {"Origin": "https://attacker.example"},
                {"Sec-Fetch-Site": "cross-site"},
            ):
                self.assert_refused(path, 403, headers=headers)
        self.assertEqual(before, self.inventory())
        self.runner.assert_not_called()

    def test_checkpoint_journal_change_invalidates_same_state_page_and_detail(self):
        old = self.library.read(self.token, self.ref)
        self.ledger.checkpoint()
        self.assertEqual(
            old["projection"]["binding"]["ledger_state_sha256"],
            self.ledger.state_hash(),
        )
        fresh = self.library.read(self.token, self.ref)
        self.assertNotEqual(old["projection_sha256"], fresh["projection_sha256"])
        self.assertNotEqual(
            old["projection"]["binding"]["journal_sha256"],
            fresh["projection"]["binding"]["journal_sha256"],
        )
        before = self.inventory()
        self.assert_refused(
            self.page_path(old, expected=True), 409, "stage1-library-projection-stale"
        )
        self.assert_refused(
            self.detail_path(old, 0), 409, "stage1-library-projection-stale"
        )
        current = self.get(self.page_path(fresh))
        self.assertEqual(current["projection_sha256"], fresh["projection_sha256"])
        self.assertEqual(before, self.inventory())
        self.runner.assert_not_called()


if __name__ == "__main__":
    unittest.main()
