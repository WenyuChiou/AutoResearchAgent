"""Ordinary authenticated HTTP, actual SDK local imports; synthetic operators only."""

import json
from pathlib import Path
import threading
from http.client import HTTPConnection
import unittest
from unittest.mock import patch

import atlas_test_paths  # noqa: F401
import test_project_stage1 as base
import test_project_stage1_fixed_replay as fixed_fixture
from test_stage1_deliverable import HTML, TITLE
from research_hub.source_fetch_saved import import_saved_public_source
from research_workspace_native.project_host import ProjectHost
from research_workspace_native.project_offline_sources import (
    OfflineSourceInputs,
    ProjectOfflineSourceService,
)
from stage1_deliverable.common import sha


class OfflineSourcesTests(unittest.TestCase):
    def setUp(self):
        self.token = "offline-authored-engineering-token-32-chars"
        self.case = fixed_fixture.FixedReplayTests()
        with patch.object(
            base,
            "authenticate",
            lambda token: (
                "local-viewer" if token in {self.token, "alice-token"} else None
            ),
        ):
            self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.case.raw = json.dumps(
            [dict(title=TITLE, authors=["Synthetic"], year=2024, version="v1")]
        ).encode()
        (self.case.inputs / "response.json").write_bytes(self.case.raw)
        for row in self.case.config["responses"]:
            row["records_sha256"] = sha(self.case.raw)
        self.case.connect()
        self.intake, self.stage1, self.ref = (
            self.case.case.intake,
            self.case.case.service,
            self.case.ref,
        )
        self.stage1.execute_query("alice-token", self.ref, self.case.body())
        ledger = self.ledger()
        work, candidate = next(iter(ledger.candidates().items()))
        self.work, self.version = work, candidate["discoveries"][-1]["version_id"]
        directory = self.case.inputs / "material"
        directory.mkdir()
        (directory / "authored.html").write_bytes(HTML)
        manifest = dict(
            schema_version="saved-public-source-input/v1",
            url="https://example.org/study",
            final_url="https://example.org/study",
            doi="",
            title=TITLE,
            raw_path="authored.html",
            raw_sha256=sha(HTML),
            content_type="text/html",
            original_acquired_at=None,
        )
        path = directory / "input.json"
        path.write_text(json.dumps(manifest), encoding="utf8")
        import_saved_public_source(
            input_manifest=path,
            expected_manifest_sha256=sha(path.read_bytes()),
            output_dir=directory / "sdk",
        )
        binding = self.intake.binding(self.ref)
        self.config = dict(
            kind="Stage1OfflineSavedSources",
            schema_version="1.0.0",
            scope="authored-engineering-only",
            project_ref=self.ref,
            input_version=1,
            brief_sha256=binding["brief_sha256"],
            plan_manifest_sha256=binding["plan_manifest_sha256"],
            materials_root=str(directory),
            runtime_sha256=sha(b"authored SDK binding"),
            sources=[
                dict(
                    work_ref=work,
                    version_id=self.version,
                    result_path="sdk/source-fetch-result.json",
                    result_sha256=sha(
                        (directory / "sdk/source-fetch-result.json").read_bytes()
                    ),
                )
            ],
        )
        self.config_path = self.case.inputs / "offline.json"
        self.config_path.write_text(json.dumps(self.config), encoding="utf8")
        self.pin = sha(self.config_path.read_bytes())
        self.host = None
        self.addCleanup(self.stop)

    def ledger(self):
        state = self.intake._load("local-viewer", self.ref)
        return self.stage1._ledger(state, self.intake.binding(self.ref))[1]

    def start(self, *, enabled=True, models=None):
        args = (
            dict(
                stage1_offline_sources_config=self.config_path,
                stage1_offline_sources_sha256=self.pin,
            )
            if enabled
            else {}
        )
        self.host = ProjectHost(
            projects=self.intake,
            credential=self.token,
            stage1=self.stage1,
            files={},
            views=[],
            models=models,
            port=0,
            **args,
        )
        self.worker = threading.Thread(
            target=self.host.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True
        )
        self.worker.start()

    def stop(self):
        if self.host is not None:
            self.host.shutdown()
            self.host.server_close()
            self.worker.join(5)
            self.assertFalse(self.worker.is_alive())
            self.host = None

    def http(self, tail, body=None, ref=None):
        client = HTTPConnection("127.0.0.1", self.host.server_port, timeout=30)
        headers = {
            "Authorization": "Bearer " + self.token,
            "Origin": f"http://127.0.0.1:{self.host.server_port}",
        }
        if body is not None:
            headers["Content-Type"] = "application/json"
        client.request(
            "POST" if body is not None else "GET",
            "/api/projects/" + (ref or self.ref) + tail,
            json.dumps(body).encode() if body is not None else None,
            headers,
        )
        response = client.getresponse()
        result = (response.status, json.loads(response.read()))
        client.close()
        return result

    def body(self, key="local-source"):
        status, offer = self.http("/stage1/sources/works/" + self.work)
        self.assertEqual(status, 200, offer)
        return {
            k: offer[k]
            for k in (
                "revision",
                "input_version",
                "brief_sha256",
                "ledger_state_sha256",
                "work_ref",
                "offer_sha256",
            )
        } | dict(key=key, confirmed=True)

    def counts(self):
        return len(self.ledger().events()), self.intake.db.execute(
            "SELECT count(*) FROM intake_actions"
        ).fetchone()[0]

    def test_normal_launcher_inert_model_broker_is_not_a_live_provider(self):
        from research_workspace_native.project_model import ProjectModelService

        disabled = ProjectModelService(self.intake)
        self.addCleanup(disabled.close)
        self.start(models=disabled)
        self.assertFalse(self.http("/models")[1]["connected"])
        status, saved = self.http("/stage1/sources/execute", self.body())
        self.assertEqual(status, 200, saved)
        self.assertEqual(saved["status"], "saved")
        self.stop()
        live = ProjectModelService(self.intake, provider_factory=lambda **kw: None)
        self.addCleanup(live.close)
        before = self.counts()
        with self.assertRaisesRegex(ValueError, "cannot compose live models"):
            self.start(models=live)
        self.assertEqual(self.counts(), before)

    def test_default_keeps_original_two_unconnected_refusals(self):
        self.start(enabled=False)
        self.assertEqual(
            self.http("/stage1/sources"),
            (409, {"error": "stage1-source-controls-unconnected"}),
        )
        self.assertEqual(
            self.http("/stage1/source-reading/" + self.work),
            (409, {"error": "stage1-reading-review-unconnected"}),
        )

    def test_ordinary_source_registration_reading_refusal_and_cold_same_key(self):
        self.start()
        body = self.body()
        status, receipt = self.http("/stage1/sources/execute", body)
        self.assertEqual(status, 200, receipt)
        self.assertEqual(receipt["status"], "saved", receipt)
        self.assertEqual(receipt["actor"], "local-viewer")
        self.assertEqual(receipt["actor_role"], "engineering-operator")
        self.assertFalse(receipt["original_http_acquisition_verified"])
        self.assertIsNone(receipt["finish"]["http_status"])
        self.assertEqual(
            self.http("/stage1/sources")[1]["sources"][0]["status"], "source-registered"
        )
        self.assertEqual(
            self.http("/stage1/source-reading/" + self.work),
            (409, {"error": "reading-work-decision-unavailable"}),
        )
        self.assertEqual(
            self.stage1.read("alice-token", self.ref)["ledger"]["counts"]["decisions"],
            0,
        )
        self.assertEqual(
            self.stage1.read("alice-token", self.ref)["ledger"]["counts"]["claims"], 0
        )
        registry = self.http("/stage1/sources")[1]["sources"][0]["registry_ref"]
        self.assertIsInstance(registry, str)
        self.assertTrue(registry)
        self.assertIsNone(receipt["original_acquired_at"])
        before = self.counts()
        self.stop()
        self.start()
        for _ in range(2):
            self.assertEqual(
                self.http("/stage1/sources")[1]["sources"][0]["registry_ref"],
                registry,
            )
        replay = self.http("/stage1/sources/execute", body)
        self.assertEqual(replay[0], 200, replay)
        self.assertTrue(replay[1]["replayed"])
        self.assertEqual(self.counts(), before)

    def changed_configuration(self, *, replace_sdk=False):
        self.start()
        original = self.body()
        status, registered = self.http("/stage1/sources/execute", original)
        self.assertEqual(status, 200, registered)
        self.ledger().decide(
            self.work,
            "pending",
            reason="fixture-unassessed",
            rationale="Synthetic isolation-test agent leaves assessment pending.",
            evidence_refs=[registered["finish"]["raw_ref"]],
            actor="synthetic-isolation-test-agent",
        )
        reading_status, reading = self.http("/stage1/source-reading/" + self.work)
        self.assertEqual(reading_status, 200, reading)
        before = self.counts()
        old_pin = self.pin
        self.stop()
        if replace_sdk:
            root = Path(self.config["materials_root"])
            changed_manifest = json.loads(
                (root / "input.json").read_text(encoding="utf8")
            )
            raw = (
                HTML
                + b"<p>Different authored engineering source, same work identity.</p>"
            )
            (root / "changed.html").write_bytes(raw)
            changed_manifest.update(raw_path="changed.html", raw_sha256=sha(raw))
            path = root / "changed-input.json"
            path.write_text(json.dumps(changed_manifest), encoding="utf8")
            import_saved_public_source(
                input_manifest=path,
                expected_manifest_sha256=sha(path.read_bytes()),
                output_dir=root / "changed-sdk",
            )
            row = self.config["sources"][0]
            old_digest = row["result_sha256"]
            row.update(
                result_path="changed-sdk/source-fetch-result.json",
                result_sha256=sha(
                    (root / "changed-sdk/source-fetch-result.json").read_bytes()
                ),
            )
            self.assertNotEqual(row["result_sha256"], old_digest)
            self.config_path.write_text(json.dumps(self.config), encoding="utf8")
        else:
            self.config_path.write_bytes(self.config_path.read_bytes() + b"\n")
        self.pin = sha(self.config_path.read_bytes())
        self.assertNotEqual(self.pin, old_pin)
        self.start()
        status, view = self.http("/stage1/sources")
        self.assertEqual(status, 200, view)
        self.assertEqual(
            view["sources"][0]["status"], "ready-for-explicit-local-import"
        )
        self.assertIsNone(view["sources"][0]["registry_ref"])
        self.assertEqual(len(view["historical_actions"]), 1)
        self.assertEqual(view["historical_actions"][0]["config_sha256"], old_pin)
        records = self.host.project_stage1_records
        self.assertEqual(
            records._entries(records._context(self.ref, self.ledger().state_hash())), []
        )
        self.assertEqual(
            self.http("/stage1/source-reading/" + self.work),
            (409, {"error": "reading-eligible-saved-source-unavailable-or-bound"}),
        )
        self.assertEqual(self.counts(), before)
        self.assertEqual(self.http("/stage1/sources/execute", original)[0], 409)

    def test_changed_config_bytes_do_not_inherit_source_or_reading(self):
        self.changed_configuration()

    def test_changed_original_and_sdk_digest_do_not_inherit_source_or_reading(self):
        self.changed_configuration(replace_sdk=True)

    def test_reading_post_replay_requires_same_offline_configuration(self):
        self.start()
        status, source = self.http("/stage1/sources/execute", self.body())
        self.assertEqual(status, 200, source)
        self.ledger().decide(
            self.work,
            "pending",
            reason="fixture-unassessed",
            rationale="Synthetic test agent leaves scientific assessment pending.",
            evidence_refs=[source["finish"]["raw_ref"]],
            actor="synthetic-test-agent",
        )
        status, view = self.http("/stage1/source-reading/" + self.work)
        self.assertEqual(status, 200, view)
        body = {
            name: view[name]
            for name in (
                "revision",
                "input_version",
                "brief_sha256",
                "ledger_state_sha256",
                "work_ref",
                "source_snapshot_sha256",
            )
        }
        body.update(
            key="synthetic-operator-reading",
            confirmed=True,
            offer_ref=view["reading_review_offer"]["offer_ref"],
            offer_sha256=view["reading_review_offer"]["offer_sha256"],
            review={
                name: view[name] for name in ("classification", "findings", "roles")
            },
        )
        status, saved = self.http("/stage1/reading-review", body)
        self.assertEqual(status, 200, saved)
        self.assertEqual(saved["status"], "saved")
        before = self.counts()
        self.stop()
        self.start()
        status, replay = self.http("/stage1/reading-review", body)
        self.assertEqual(status, 200, replay)
        self.assertTrue(replay["replayed"])
        self.assertEqual(self.counts(), before)
        self.stop()
        self.config_path.write_bytes(self.config_path.read_bytes() + b"\n")
        self.pin = sha(self.config_path.read_bytes())
        self.start()
        status, rejected = self.http("/stage1/reading-review", body)
        self.assertEqual(status, 409, rejected)
        self.assertEqual(rejected["error"], "offline-reading-configuration-differs")
        self.assertEqual(self.counts(), before)

    def test_claim_post_replay_requires_current_saved_source(self):
        from test_project_saved_claims import request as claim_request

        self.start()
        status, source = self.http("/stage1/sources/execute", self.body())
        self.assertEqual(status, 200, source)
        self.ledger().decide(
            self.work,
            "pending",
            reason="fixture-unassessed",
            rationale="Synthetic test decision, not a real research judgment.",
            evidence_refs=[source["finish"]["raw_ref"]],
            actor="synthetic-test-agent",
        )
        body = claim_request(
            self.host.project_saved_claims,
            self.ref,
            self.work,
            key="synthetic-operator-claim",
        )
        status, saved = self.http("/stage1/source-claim", body)
        self.assertEqual(status, 200, saved)
        self.assertEqual(saved["status"], "saved")
        before = self.counts()
        self.stop()
        self.start()
        status, replay = self.http("/stage1/source-claim", body)
        self.assertEqual(status, 200, replay)
        self.assertTrue(replay["replayed"])
        self.assertEqual(self.counts(), before)
        self.stop()
        self.config_path.write_bytes(self.config_path.read_bytes() + b"\n")
        self.pin = sha(self.config_path.read_bytes())
        self.start()
        status, rejected = self.http("/stage1/source-claim", body)
        self.assertEqual(status, 409, rejected)
        self.assertEqual(rejected["error"], "offline-claim-configuration-differs")
        self.assertEqual(self.counts(), before)

    def test_wrong_project_version_digest_and_live_authorization_refuse(self):
        self.start()
        body = self.body()
        events = len(self.ledger().events())
        for i, changes in enumerate(
            [
                dict(input_version="1"),
                dict(input_version=2),
                dict(brief_sha256="0" * 64),
                dict(offer_sha256="0" * 64),
                dict(confirmed=False),
                dict(work_ref="work-other"),
            ]
        ):
            status, _ = self.http(
                "/stage1/sources/execute", dict(body, **changes, key="bad-" + str(i))
            )
            self.assertIn(status, (400, 409))
            self.assertEqual(len(self.ledger().events()), events)
        self.assertEqual(self.http("/stage1/sources", ref="project-other")[0], 409)
        self.assertEqual(self.http("/stage1/sources/authorize", body)[0], 409)
        self.assertEqual(len(self.ledger().events()), events)

    def test_tampered_sdk_and_unadmitted_configuration_refuse_before_writes(self):
        service = ProjectOfflineSourceService(
            self.stage1, OfflineSourceInputs(self.config_path, self.pin)
        )
        receipt_path = (
            Path(self.config["materials_root"])
            / self.config["sources"][0]["result_path"]
        )
        before = self.counts()
        original = receipt_path.read_bytes()
        receipt_path.write_bytes(original + b" ")
        with self.assertRaises(Exception):
            service.read(self.token, self.ref)
        self.assertEqual(self.counts(), before)
        receipt_path.write_bytes(original)
        changed = dict(self.config, scope="live")
        self.config_path.write_text(json.dumps(changed), encoding="utf8")
        with self.assertRaisesRegex(
            Exception, "offline-source-engineering-admission-required"
        ):
            OfflineSourceInputs(self.config_path, sha(self.config_path.read_bytes()))

    def test_partial_core_write_remains_unknown_and_blocks_new_query(self):
        self.start()
        body = self.body()
        with patch(
            "research_workspace_native.project_offline_sources.complete_saved_sdk_import",
            side_effect=OSError("authored failure after source start"),
        ):
            status, result = self.http("/stage1/sources/execute", body)
        self.assertEqual(status, 409, result)
        actions = self.host.project_stage1_sources._actions("local-viewer", self.ref)
        self.assertEqual(actions[0]["status"], "execution-unknown")
        self.assertEqual(result["receipt"]["status"], "execution-unknown")
        self.assertEqual(result["receipt"]["key"], body["key"])
        before = self.counts()
        self.stop()
        self.start()
        self.assertEqual(
            self.http("/stage1/sources/execute", body)[1]["status"], "execution-unknown"
        )
        with self.assertRaises(Exception):
            self.stage1.execute_query(
                "alice-token", self.ref, self.case.body(1, key="after-unknown")
            )
        self.assertEqual(self.counts(), before)
