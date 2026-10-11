"""Saved canonical input reviews over real Core/SQLite and temporary HTTP."""

import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from copy import deepcopy

from test_stage1_core_records import core_case
from test_project_stage1_discovery_records import discovery_candidates
import test_project_stage1_delivery_http as delivery_http
from research_workspace_native.project_stage1_atlas import (
    ProjectStage1AtlasService,
    _source,
)
from research_workspace_native.project_stage2_context import (
    ProjectStage2InputReviewService,
)
from research_workspace_native.session_api import SessionApiError
from stage1_deliverable.common import canonical


def current(case, ref):
    state = case.intake._load("alice", ref)
    artifact = state["stage1_canonical_package"]
    return state, dict(
        input_version=state["input_version"],
        revision=state["revision"],
        artifact_ref=artifact["artifact_ref"],
        manifest_sha256=artifact["manifest_sha256"],
    )


class ProjectStage2ContextTests(unittest.TestCase):
    def test_mixed_core_library_review_reopen_and_stale_or_tampered_refusal(self):
        with core_case() as (case, fixture, _, _):
            discovery_candidates(case, fixture)
            offer = case.produce(fixture)
            ref = fixture["ref"]
            case.delivery.deliver("alice-token", ref, case.body(fixture, offer))
            case.reopen()
            atlas = ProjectStage1AtlasService(case.delivery)
            service = ProjectStage2InputReviewService(atlas)
            state, args = current(case, ref)
            context = case.delivery._context(ref)
            root = case.delivery._saved_artifact(
                "alice", state, state["stage1_canonical_package"], context
            )
            before = _source(root, args["manifest_sha256"])
            changes = case.intake.db.total_changes
            with patch.object(
                case.intake, "_perform", side_effect=AssertionError("write")
            ):
                view = atlas.read("alice-token", ref, **args)
            self.assertEqual(case.intake.db.total_changes, changes)
            value = view["stage2_input"]
            self.assertEqual(value["records_version"], "1.2.0")
            self.assertEqual(len(value["works"]), 4)
            self.assertEqual(
                value["limitations"],
                [
                    "stage1-handoff-not-eligible",
                    "stage2-canonical-consumer-unconnected",
                ],
            )
            self.assertTrue(
                any(
                    "claim-source-or-location-unavailable" in p["limitations"]
                    for p in value["works"]
                )
            )
            self.assertTrue(
                any(
                    "claim-level-needs-versioned-consumer" in p["limitations"]
                    for p in value["works"]
                )
            )
            unread = [
                p for p in value["works"] if p["reading_status"] == "discovery-only"
            ]
            self.assertEqual(len(unread), 2)
            self.assertTrue(all(p["source_ids"] == [] for p in unread))
            self.assertTrue(
                any(p["screening_status"] == "not-screened" for p in unread)
            )
            body = dict(
                key="input-review-1",
                **args,
                brief_sha256=state["briefs"][-1]["sha256"],
                context_sha256=value["context_sha256"],
                decision="request-stage2",
                user_input="Need the missing evidence; 不授予执行权限。",
                confirmed=True,
            )
            for changed in (
                dict(body, context_sha256="0" * 64),
                dict(body, revision=body["revision"] - 1),
                dict(body, permit=True),
                dict(body, decision=[]),
            ):
                with self.assertRaises(SessionApiError):
                    service.review("alice-token", ref, changed)
            with self.assertRaises(SessionApiError):
                service.review("wrong-token", ref, body)
            saved = service.review("alice-token", ref, body)
            self.assertEqual(saved["status"], "saved")
            self.assertFalse(saved["execution_authorized"])
            self.assertEqual(saved["stage2_status"], "not-started")
            case.reopen()
            atlas = ProjectStage1AtlasService(case.delivery)
            service = ProjectStage2InputReviewService(atlas)
            with patch.object(
                atlas, "read", side_effect=AssertionError("replayed work")
            ):
                replay = service.review("alice-token", ref, body)
            self.assertTrue(replay["replayed"])
            with self.assertRaisesRegex(SessionApiError, "payload-differs"):
                service.review("alice-token", ref, dict(body, decision="hold"))
            state, args = current(case, ref)
            read = atlas.read("alice-token", ref, **args)
            self.assertEqual(read["payload"], view["payload"])
            self.assertEqual(
                read["stage2_input"]["context_sha256"], value["context_sha256"]
            )
            self.assertFalse(read["stage2_input"]["review"]["stale"])
            self.assertEqual(
                read["stage2_input"]["review"]["user_input"], body["user_input"]
            )
            self.assertEqual(_source(root, args["manifest_sha256"]), before)
            self.assertNotIn("stage2_activation", state)
            forged = deepcopy(state)
            forged["stage2_input_reviews"][0]["user_input"] = "Forged approval"

            def replace(value):
                case.intake.db.execute(
                    "UPDATE intake_projects SET state=? WHERE ref=?",
                    (canonical(value).decode(), ref),
                )

            try:
                replace(forged)
                with self.assertRaisesRegex(SessionApiError, "review-history-differs"):
                    atlas.read("alice-token", ref, **args)
            finally:
                replace(state)
            tampered = root / "records.original.json"
            original = tampered.read_bytes()
            try:
                tampered.write_bytes(original + b" ")
                with self.assertRaises(SessionApiError):
                    service.review(
                        "alice-token", ref, dict(body, **args, key="tampered-review")
                    )
            finally:
                tampered.write_bytes(original)
            case.runner.assert_not_called()
            node = shutil.which("node")
            self.assertIsNotNone(node)
            with tempfile.TemporaryDirectory(prefix="stage2-input-") as directory:
                path = Path(directory) / "view.json"
                path.write_text(json.dumps(read, ensure_ascii=True), encoding="utf8")
                result = subprocess.run(
                    [
                        node,
                        str(
                            Path(__file__).parent
                            / "browser/project-stage2-input-test.cjs"
                        ),
                        str(path),
                    ],
                    capture_output=True,
                    text=True,
                    encoding="utf8",
                    timeout=30,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                print(result.stdout.strip())
            real_save = case.intake._save

            def fail_saved(current_state, kind, payload):
                if kind == "stage1-review-stage2-input-saved":
                    raise TimeoutError("authored post-work commit failure")
                return real_save(current_state, kind, payload)

            unknown = dict(body, **args, key="review-unknown")
            with patch.object(case.intake, "_save", side_effect=fail_saved):
                with self.assertRaises(SessionApiError) as error:
                    service.review("alice-token", ref, unknown)
            self.assertEqual(error.exception.receipt["status"], "execution-unknown")
            case.reopen()
            service = ProjectStage2InputReviewService(
                ProjectStage1AtlasService(case.delivery)
            )
            with patch.object(
                service.atlas, "read", side_effect=AssertionError("repeat")
            ):
                self.assertEqual(
                    service.review("alice-token", ref, unknown)["status"],
                    "execution-unknown",
                )
            saved_state, saved_args = current(case, ref)
            self.assertEqual(len(saved_state["stage2_input_reviews"]), 1)
            service.atlas.read("alice-token", ref, **saved_args)

    def test_existing_contract_http_review_requires_origin_and_recovers_without_stage2(
        self,
    ):
        fixture = delivery_http.ProjectStage1DeliveryHttpTests(methodName="runTest")
        fixture.setUpClass()
        self.addCleanup(fixture.tearDownClass)
        self.addCleanup(fixture.doCleanups)
        fixture.setUp()
        status, _ = fixture.request(fixture.base + "/stage1/deliver", fixture.body)
        self.assertEqual(status, 200)
        state = fixture.fixture.intake._load("local-viewer", fixture.saved["ref"])
        artifact = state["stage1_canonical_package"]
        route = (
            fixture.base
            + "/stage1/atlas/"
            + "/".join(
                map(
                    str,
                    (
                        state["input_version"],
                        state["revision"],
                        artifact["artifact_ref"],
                        artifact["manifest_sha256"],
                    ),
                )
            )
        )
        status, raw = fixture.request(route)
        self.assertEqual(status, 200)
        context = json.loads(raw)["stage2_input"]
        self.assertEqual(context["consumer_status"], "existing-contract")
        body = dict(
            key="http-review-1",
            revision=state["revision"],
            input_version=state["input_version"],
            brief_sha256=state["briefs"][-1]["sha256"],
            artifact_ref=artifact["artifact_ref"],
            manifest_sha256=artifact["manifest_sha256"],
            context_sha256=context["context_sha256"],
            decision="keep-stage1",
            user_input="Unknown remains Unknown.",
            confirmed=True,
        )
        target = fixture.base + "/stage1/review-stage2-input"
        self.assertEqual(
            fixture.request(target, body, origin="https://foreign.example")[0], 403
        )
        status, raw = fixture.request(target, body)
        self.assertEqual(status, 200)
        saved = json.loads(raw)
        self.assertFalse(saved["execution_authorized"])
        self.assertTrue(json.loads(fixture.request(target, body)[1])["replayed"])
        status, raw = fixture.request(fixture.base + "/history")
        self.assertEqual(status, 200)
        action = next(
            row for row in json.loads(raw)["actions"] if row["key"] == body["key"]
        )
        self.assertEqual(action["request_sha256"], saved["request_sha256"])
        self.assertEqual(fixture.request(target, dict(body, decision="hold"))[0], 409)
        fixture.fixture.runner.assert_not_called()


if __name__ == "__main__":
    unittest.main()
