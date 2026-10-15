"""Real HTTP/SQLite saved-source review to package; authored sources, no model."""

from copy import deepcopy
from http.client import HTTPConnection
import json
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cli"))

import test_project_stage1_delivery as delivery_fixture
import test_stage1_deliverable as source_fixture
import test_project_stage1_records as records_fixture
from test_project_saved_claims import request as claim_body
from test_workspace_project_intake import authenticate, bound_body
from research_workspace_native.project_host import ProjectHost
from research_workspace_native.project_reading_review import (
    ProjectReadingReviewService,
)
from research_workspace_native.project_records_prepare import (
    ProjectRecordsPrepareService,
)
from research_workspace_native.project_saved_claims import ProjectSavedClaimService
from stage1_deliverable.common import sha


REPEATED = "Repeated authored 中文😀 evidence."


class ProjectSourceReadingHttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        records_fixture.SavedStage1RecordsTests.setUpClass()

    @classmethod
    def tearDownClass(cls):
        records_fixture.SavedStage1RecordsTests.tearDownClass()

    def setUp(self):
        self.token = "authored-source-reading-token-with-32-characters"
        self.case = records_fixture.SavedStage1RecordsTests(methodName="runTest")
        original = source_fixture.ResearchDeliverableTests.make_records

        def repeated(case, *args, **kwargs):
            raw = kwargs.pop("raw", source_fixture.HTML)
            kwargs["raw"] = raw.replace(
                b"</article>",
                (
                    "<p>"
                    + REPEATED
                    + " First occurrence. "
                    + REPEATED
                    + " Second occurrence.</p></article>"
                ).encode("utf8"),
            )
            return original(case, *args, **kwargs)

        def credential(token):
            return (
                "local-viewer"
                if token in {self.token, "alice-token"}
                else authenticate(token)
            )

        with (
            patch.object(delivery_fixture, "authenticate", credential),
            patch.object(
                source_fixture.ResearchDeliverableTests, "make_records", repeated
            ),
        ):
            self.case.setUp()
            self.addCleanup(self.case.doCleanups)
            self.fixture = self.case.two_sources()
        for records, directory in self.fixture["pairs"]:
            source = records["sources"][0]
            path = directory / "source/source-fetch-result.json"
            self.case.producer.register_source(
                self.fixture["ref"],
                source_id=source["source_id"],
                result_path=path,
                expected_result_sha256=sha(path.read_bytes()),
                access_note=source["access_note"],
                expected_ledger_state_sha256=self.fixture["ledger"].state_hash(),
            )
        self.base = "/api/projects/" + self.fixture["ref"]
        self.start()
        self.addCleanup(self.stop)
        self.assertEqual(self.reading_entries(), [])

    def start(self):
        self.case.intake.authenticate = lambda token: (
            "local-viewer"
            if token in {self.token, "alice-token"}
            else authenticate(token)
        )
        self.claims = ProjectSavedClaimService(self.case.stage1, self.case.producer)
        self.reading = ProjectReadingReviewService(saved_claims=self.claims)
        self.host = ProjectHost(
            projects=self.case.intake,
            credential=self.token,
            stage1=self.case.stage1,
            files={},
            views=[],
            port=0,
        )
        self.host.project_saved_claims = self.claims
        self.host.project_reading_review = self.reading
        self.host.project_records_prepare = ProjectRecordsPrepareService(
            self.case.producer
        )
        self.worker = threading.Thread(
            target=self.host.serve_forever,
            kwargs={"poll_interval": 0.05},
            daemon=True,
        )
        self.worker.start()

    def stop(self):
        if self.worker.is_alive():
            self.host.shutdown()
            self.host.server_close()
            self.worker.join(5)
        self.assertFalse(self.worker.is_alive())

    def http(self, tail, body=None, *, credential=None, origin=None):
        client = HTTPConnection("127.0.0.1", self.host.server_port, timeout=30)
        headers = {"Authorization": "Bearer " + (credential or self.token)}
        if body is not None:
            headers.update(
                Origin=origin or self.host.expected_origin,
                **{"Content-Type": "application/json"},
            )
        try:
            client.request(
                "POST" if body is not None else "GET",
                self.base + tail,
                json.dumps(body).encode("utf8") if body is not None else None,
                headers,
            )
            reply = client.getresponse()
            raw = reply.read()
            return reply.status, json.loads(raw)
        finally:
            client.close()

    def ok(self, tail, body=None):
        status, result = self.http(tail, body)
        self.assertEqual(status, 200, result)
        return result

    def reading_entries(self):
        state = self.case.intake._load("local-viewer", self.fixture["ref"])
        return [
            row
            for row in state.get("stage1_saved_registries", {}).values()
            if row["ref"].startswith("stage1-reading-registry-")
        ]

    def reading_body(self, work, key):
        view = self.ok("/stage1/source-reading/" + work)
        offer = view["reading_review_offer"]
        return dict(
            key=key,
            confirmed=True,
            offer_ref=offer["offer_ref"],
            offer_sha256=offer["offer_sha256"],
            review={
                name: deepcopy(view[name])
                for name in ("classification", "findings", "roles")
            },
            **{
                name: view[name]
                for name in (
                    "revision",
                    "input_version",
                    "brief_sha256",
                    "ledger_state_sha256",
                    "work_ref",
                    "source_snapshot_sha256",
                )
            },
        )

    def bound(self, key):
        return dict(
            bound_body(self.case.intake.read("alice-token", self.fixture["ref"]), key),
            ledger_state_sha256=self.fixture["ledger"].state_hash(),
            confirmed=True,
        )

    def test_http_saved_claim_notes_coverage_checkpoint_package_and_atlas(self):
        work = self.fixture["records"]["papers"][0]["work_id"]
        ledger = self.fixture["ledger"]
        old_events = ledger.events()
        source_view = self.claims.view("alice-token", self.fixture["ref"], work)
        text = source_view["page"]["text"]
        first = text.index(REPEATED)
        second = text.index(REPEATED, first + 1)
        claims = {}
        for field in ("title", "authors", "year", "identifier", "version", "relevance"):
            body = claim_body(
                self.claims,
                self.fixture["ref"],
                work,
                "http-" + field,
                "Authored source review of " + field,
                REPEATED,
            )
            body.update(
                start_byte=len(text[:second].encode("utf8")),
                end_byte=len(text[: second + len(REPEATED)].encode("utf8")),
            )
            result = self.ok("/stage1/source-claim", body)
            self.assertEqual(result["status"], "saved")
            claims[field] = result["claim_event_id"]
        stage = self.ok("/stage1")
        offer = next(
            row
            for row in stage["coverage_actions"]["offers"]
            if row["operation"] == "review-work" and row["document"]["work_ref"] == work
        )
        review = dict(
            identity_status="verified",
            identity_claims={
                name: claims[name] for name in claims if name != "relevance"
            },
            cluster_claims={
                offer["document"]["clusters"][0]["cluster_id"]: claims["relevance"]
            },
            closest=False,
            rationale="Explicit authored offline review; not scientific acceptance.",
        )
        self.ok(
            "/stage1/coverage",
            dict(
                self.bound("http-coverage"),
                operation="review-work",
                offer_ref=offer["offer_ref"],
                offer_sha256=offer["offer_sha256"],
                review=review,
            ),
        )
        for index, (records, _) in enumerate(self.fixture["pairs"]):
            selected = records["papers"][0]["work_id"]
            request = self.reading_body(selected, "http-notes-" + str(index))
            result = self.ok("/stage1/reading-review", request)
            self.assertEqual(result["status"], "saved")
            self.assertFalse(
                self.ok("/stage1/source-reading/" + selected)["stage1_complete"]
            )
            if selected == work:
                span = next(
                    row
                    for row in result["registry_entry"]["payload"]["claims"]
                    if row["claim_id"] == claims["title"]
                )
                self.assertEqual(span["start"], second)
                self.assertEqual(span["quote"], REPEATED)
        self.assertEqual(len(self.reading_entries()), 2)
        checkpoint = self.ok("/stage1/checkpoint", self.bound("http-checkpoint"))
        prepared = self.ok(
            "/stage1/prepare-delivery",
            dict(
                self.bound("http-prepare"),
                checkpoint_event_id=checkpoint["checkpoint_event_id"],
            ),
        )
        self.assertEqual(prepared["status"], "saved")
        self.assertFalse(prepared["delivery_offer"]["eligible_for_stage2"])
        delivered = self.ok(
            "/stage1/deliver",
            self.case.body(
                self.fixture,
                prepared["delivery_offer"],
                "http-deliver",
            ),
        )
        self.assertEqual(delivered["status"], "saved")
        self.assertFalse(delivered["stage1_complete"])
        overview = self.ok("/overview")
        artifact = overview["stage1"]["delivery"]["canonical_package"]
        self.assertEqual(artifact["manifest_sha256"], delivered["manifest_sha256"])
        project = overview["project"]
        atlas = self.ok(
            f"/stage1/atlas/{project['input_version']}/{project['revision']}"
            f"/{artifact['artifact_ref']}/{artifact['manifest_sha256']}"
        )
        self.assertEqual(atlas["schema"], "ProjectStage1AtlasView/1")
        self.assertEqual(ledger.events()[: len(old_events)], old_events)
        self.assertIn("partial", str(atlas["payload"]["index"]))
        self.assertIn("Unknown", str(atlas["payload"]["index"]))
        self.assertEqual(atlas["payload"]["index_sha256"], atlas["index_sha256"])
        contract = self.ok("/contract")
        for stage in ("3", "4", "5", "6"):
            self.assertEqual(contract["stages"][stage]["status"], "planned")
            self.assertFalse(contract["stages"][stage]["connected"])
        self.case.runner.assert_not_called()

    def test_http_reopen_same_key_history_without_registry_or_dispatch(self):
        work = self.fixture["records"]["papers"][0]["work_id"]
        request = self.reading_body(work, "http-reopen-notes")
        saved = self.ok("/stage1/reading-review", request)
        events = self.fixture["ledger"].events()
        entries = deepcopy(self.reading_entries())
        old_db = self.case.intake.db
        self.stop()
        self.case.reopen()
        self.assertIsNot(self.case.intake.db, old_db)
        self.start()
        with patch.object(
            self.case.producer,
            "register_reading",
            side_effect=AssertionError("re-register"),
        ) as register:
            result = self.ok("/stage1/reading-review", {**request, "revision": 999})
            self.assertTrue(result["replayed"])
            self.assertEqual(result["registry_entry"], saved["registry_entry"])
            status, _ = self.http(
                "/stage1/reading-review",
                {**request, "review": {**request["review"], "roles": ["changed"]}},
            )
            self.assertEqual(status, 409)
            register.assert_not_called()
        self.assertEqual(self.reading_entries(), entries)
        self.assertEqual(self.fixture["ledger"].events(), events)
        self.case.runner.assert_not_called()

    def test_http_stale_foreign_tamper_and_origin_refuse_before_registration(self):
        work = self.fixture["records"]["papers"][0]["work_id"]
        request = self.reading_body(work, "http-refusal")
        events = self.fixture["ledger"].events()
        with patch.object(
            self.case.producer,
            "register_reading",
            side_effect=AssertionError("refused registration"),
        ) as register:
            for index, change in enumerate(
                (
                    {"revision": 999},
                    {"work_ref": "foreign-work"},
                    {"source_snapshot_sha256": "0" * 64},
                    {"root": "caller-root"},
                )
            ):
                status, _ = self.http(
                    "/stage1/reading-review",
                    {**request, "key": "bad-" + str(index), **change},
                )
                self.assertIn(status, (400, 404, 409))
            self.assertEqual(
                self.http("/stage1/source-reading/" + work, credential="foreign")[0],
                401,
            )
            self.assertEqual(
                self.http(
                    "/stage1/reading-review", request, origin="https://foreign.example"
                )[0],
                403,
            )
            path = self.fixture["pairs"][0][1] / "source/source-fetch-result.json"
            raw = path.read_bytes()
            try:
                path.write_bytes(raw + b" ")
                self.assertEqual(
                    self.http("/stage1/reading-review", {**request, "key": "tampered"})[
                        0
                    ],
                    409,
                )
            finally:
                path.write_bytes(raw)
            register.assert_not_called()
        self.assertEqual(self.reading_entries(), [])
        self.assertEqual(self.fixture["ledger"].events(), events)
        self.case.runner.assert_not_called()


if __name__ == "__main__":
    unittest.main()
