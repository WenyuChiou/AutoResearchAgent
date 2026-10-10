"""Public saved-case example exercises real producers; no native/model calls."""

import importlib.util
import http.client
import io
import json
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import threading
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

PLUGIN = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(PLUGIN / "cli"), str(PLUGIN / "tests")]
from research_workspace_native.atlas_host import AtlasHost  # noqa: E402
from research_workspace_native.stage_actions import StageActions  # noqa: E402
from research_workspace_native.stage_inputs import snapshot_inputs, source_digest  # noqa: E402
from stage1_brief.brief import validate_brief  # noqa: E402
from stage1_deliverable.common import sha  # noqa: E402
from stage1_ledger.store import Ledger  # noqa: E402


def load_example():
    path = PLUGIN / "references/research-workspace/examples/build-review-fixture.py"
    spec = importlib.util.spec_from_file_location("atlas_saved_review_example", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ReviewExampleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve() / "saved-case"
        self.example = load_example()
        original = subprocess.Popen

        def allow_git_preflight(argv, *args, **kwargs):
            self.assertEqual(argv[0], "git", "no native/model/search child allowed")
            return original(argv, *args, **kwargs)

        with patch("subprocess.Popen", side_effect=allow_git_preflight) as child:
            with redirect_stdout(io.StringIO()):
                self.files, self.views = self.example.build(self.root)
        self.assertGreater(child.call_count, 0)  # Actual private-output Git guards.
        self.receipt = json.loads((self.root / "fixture-receipt.json").read_bytes())

    def host(self):
        token = secrets.token_urlsafe(32)
        stages = self.example.create_stage_actions(self.root, self.views, token)
        self.addCleanup(stages.close)
        server = AtlasHost(
            files=self.files, views=self.views, credential=token, stage_actions=stages
        )
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        self.addCleanup(worker.join, 5)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return server, stages, token

    def request(self, server, token, route, body=None):
        connection = http.client.HTTPConnection(
            "127.0.0.1", server.server_port, timeout=10
        )
        headers = {"Authorization": "Bearer " + token}
        if body is not None:
            headers.update(
                {"Content-Type": "application/json", "Origin": server.expected_origin}
            )
        try:
            connection.request(
                "GET" if body is None else "POST",
                route,
                None if body is None else json.dumps(body).encode(),
                headers,
            )
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()

    def perform(self, server, token, ref, stage, action, key, **decision):
        base = "/api/stages/projects/" + ref
        status, offer = self.request(server, token, f"{base}/offers/{stage}/{action}")
        self.assertEqual(status, 200, offer)
        body = {name: offer[name] for name in ("revision", "offer_ref", "offer_sha256")}
        body.update(
            stage=stage,
            action=action,
            key=key,
            index_sha256=offer["document"]["index_sha256"],
            input_version=offer["document"]["input_version"],
            decision=None,
            note="",
            confirmed=False,
        )
        body.update(decision)
        status, row = self.request(server, token, base + "/actions", body)
        self.assertEqual(status, 200, row)
        return body, row

    def test_saved_case_and_pending_brief_pins_are_truthful(self):
        receipt = self.receipt
        self.assertEqual(receipt["classification"], "synthetic-repository-fixture")
        for field in (
            "researcher_confirmed_intake",
            "execution_authority",
            "scientific_quality_verified",
            "native_process_started",
            "model_call_started",
            "original_stage1_lineage_attested",
        ):
            self.assertIs(receipt[field], False)
        self.assertIn("Independent", receipt["stage_cases"])
        raw = (self.root / "stage-inputs.json").read_bytes()
        self.assertEqual(sha(raw), receipt["stage_inputs_sha256"])
        self.assertEqual(
            source_digest(snapshot_inputs(json.loads(raw))),
            receipt["stage_source_sha256"],
        )
        brief = (self.root / "brief.json").read_bytes()
        self.assertEqual(sha(brief), receipt["brief_sha256"])
        self.assertFalse(
            validate_brief(json.loads(brief))["necessary_clarification_complete"]
        )
        for view in self.views:
            self.assertEqual(
                (self.root / view["ref"] / "brief.json").read_bytes(), brief
            )
            manifest = json.loads(
                (self.root / view["ref"] / "view-manifest.json").read_bytes()
            )
            self.assertNotIn("brief.json", manifest["files"])

    def test_http_actual_checkpoint_inspection_review_and_get_do_not_execute_research(
        self,
    ):
        before = source_digest(
            snapshot_inputs(json.loads((self.root / "stage-inputs.json").read_bytes()))
        )
        server, service, token = self.host()
        checkpoint = Ledger.checkpoint
        with patch.object(
            Ledger, "checkpoint", autospec=True, side_effect=checkpoint
        ) as producer:
            body, row = self.perform(
                server, token, "stage1", 1, "checkpoint-stage1", "check-one"
            )
            self.assertEqual(row["outcome"], "succeeded")
            self.assertTrue(row["result"]["ledger_valid"])
            self.assertEqual(row["result"]["readiness"]["status"], "blocked")
            self.assertIn(
                "closest-work-unverified", row["result"]["readiness"]["blockers"]
            )
            status, replay = self.request(
                server,
                token,
                "/api/stages/projects/stage1/actions",
                dict(body, revision=999),
            )
            self.assertEqual(status, 200)
            self.assertEqual(replay, row)
            self.assertEqual(producer.call_count, 1)
        _, complete = self.perform(
            server, token, "stage2", 2, "inspect-stage2", "check-two"
        )
        self.assertEqual(complete["outcome"], "succeeded")
        self.assertEqual(
            complete["result"]["readiness"], {"status": "ready", "blockers": []}
        )
        self.assertFalse(
            complete["result"]["completion"]["stage3_execution_authorized"]
        )
        _, review = self.perform(
            server,
            token,
            "stage2",
            2,
            "review-stage",
            "review-next",
            decision="request-next",
            note="Review the saved fixture.",
            confirmed=True,
        )
        self.assertEqual(
            review["result"]["next_stage_request"],
            "recorded-awaiting-execution-authority",
        )
        self.assertFalse(review["result"]["native_user_message_attested"])
        with patch.object(
            StageActions, "execute", side_effect=AssertionError("GET must not execute")
        ):
            for route in (
                "/api/stages/projects/stage2",
                "/api/stages/projects/stage2/actions/review-next",
            ):
                for _ in range(2):
                    status, saved = self.request(server, token, route)
                    self.assertEqual(status, 200, saved)
        self.assertEqual(
            source_digest(
                snapshot_inputs(
                    json.loads((self.root / "stage-inputs.json").read_bytes())
                )
            ),
            before,
        )
        bootstrap = server._assets["/views/stage2/atlas.html"]
        self.assertIn(b"/stage-panel.js", bootstrap)
        self.assertEqual(service.view(token, "stage2")["history_count"], 2)

    def test_tampered_input_recipe_is_refused_before_creating_store(self):
        path = self.root / "stage-inputs.json"
        path.write_bytes(path.read_bytes() + b"\n")
        with self.assertRaisesRegex(ValueError, "binding differs"):
            self.example.create_stage_actions(
                self.root, self.views, secrets.token_urlsafe(32)
            )
        self.assertFalse((self.root / "stage-actions.sqlite3").exists())

    def test_existing_output_cannot_overwrite_retained_results(self):
        before = (self.root / "fixture-receipt.json").read_bytes()
        with self.assertRaises(FileExistsError):
            self.example.build(self.root)
        self.assertEqual((self.root / "fixture-receipt.json").read_bytes(), before)

    def test_optional_ready_case_projects_the_same_saved_stage1_ledger(self):
        ready = self.root.parent / "ready-case"
        original = subprocess.Popen

        def only_git(argv, *args, **kwargs):
            self.assertEqual(argv[0], "git", "no native/model/search child allowed")
            return original(argv, *args, **kwargs)

        with (
            patch("subprocess.Popen", side_effect=only_git),
            redirect_stdout(io.StringIO()),
        ):
            self.files, self.views = self.example.build(
                ready, demonstrate_ready_saved_case=True
            )
        self.root = ready
        receipt = json.loads((ready / "fixture-receipt.json").read_bytes())
        self.assertTrue(
            receipt["saved_stage1_case"]["display_and_saved_input_identities_match"]
        )
        self.assertEqual(
            receipt["saved_stage1_case"]["qualified_round_yields"], [1, 0, 0]
        )
        self.assertTrue(receipt["stage2_independent_saved_case"])
        self.assertFalse(receipt["original_stage1_lineage_attested"])
        self.assertFalse(receipt["execution_authority"])
        index = json.loads((ready / "stage1/workspace-index.json").read_bytes())
        self.assertEqual(index["papers"][0]["title"], "Synthetic household record")
        ledger = Ledger(ready / "inputs/stage1-ledger")
        candidate = ledger.candidates()[index["papers"][0]["work_id"]]
        self.assertEqual(
            index["papers"][0]["title"], candidate["discoveries"][0]["record"]["title"]
        )
        for binding in receipt["saved_stage1_case"]["paper_bindings"]:
            for ref in binding["source_refs"]:
                self.assertEqual(sha(ledger.read_ref(ref)), ref["sha256"])
        server, _, token = self.host()
        _, row = self.perform(
            server, token, "stage1", 1, "checkpoint-stage1", "ready-one"
        )
        self.assertEqual(row["outcome"], "succeeded")
        self.assertEqual(
            row["result"]["readiness"],
            {
                "status": "pass",
                "blockers": [],
                "next_allowed_action": "stop-sufficient",
            },
        )
        handoff = row["result"]["handoff"]["papers"]
        self.assertEqual(
            [(p["work_id"], p["reviewed_version_id"]) for p in handoff],
            [(p["work_id"], p["version_id"]) for p in index["papers"]],
        )
        _, review = self.perform(
            server,
            token,
            "stage1",
            1,
            "review-stage",
            "ready-next",
            decision="request-next",
            note="Review this saved coverage case.",
            confirmed=True,
        )
        self.assertEqual(
            review["result"]["next_stage_request"],
            "recorded-awaiting-execution-authority",
        )
        self.assertFalse(review["execution_authorized"])
        _, stage2 = self.perform(
            server, token, "stage2", 2, "inspect-stage2", "independent-two"
        )
        self.assertEqual(stage2["result"]["readiness"]["status"], "ready")
        self.assertFalse(stage2["model_execution"])


if __name__ == "__main__":
    unittest.main()
