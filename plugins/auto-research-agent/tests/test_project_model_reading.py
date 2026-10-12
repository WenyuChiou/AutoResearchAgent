"""Actual saved Core/source replay plus synthetic model queue; no live I/O."""

from copy import deepcopy
import http.client
import json
import os
from pathlib import Path
import sys
import threading
import time
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cli"))

from research_workspace_native.project_model import ProjectModelService
from research_workspace_native.project_host import ProjectHost
from research_workspace_native.project_model_factory import (
    OwnAccountProjectModelFactory,
)
from research_workspace_native.project_model_reading import (
    reading_prompt,
    saved_reading_snapshot,
    validate_reading_draft,
)
from research_workspace_native.session_api import SessionApiError
from stage1_deliverable.common import canonical, sha
from stage1_deliverable.records import CLASSIFICATION, FINDINGS
import test_project_stage1_delivery as delivery_fixture
from test_project_stage1_records import saved_stage1_case


def draft(snapshot):
    source = snapshot["sources"][0]
    claim = snapshot["existing_claims"][0]
    quote = claim["locator"]["quote"]
    start = source["excerpt"].encode("utf8").index(quote.encode("utf8"))
    return dict(
        summary="Saved text supports the quoted paper assertion; applicability Unknown.",
        classification={name: "Unknown" for name in CLASSIFICATION},
        findings={name: "Unknown" for name in FINDINGS},
        limitations=["Scientific support is unassessed."],
        open_questions=["Does this transfer to the confirmed project?"],
        evidence=[
            dict(
                source_id=source["source_id"],
                text_sha256=source["text_sha256"],
                start_byte=start,
                end_byte=start + len(quote.encode("utf8")),
                quote=quote,
                claim_id=claim["event_id"],
            )
        ],
    )


class SavedReadingTests(unittest.TestCase):
    def test_reading_before_first_checkpoint_preserves_eligible_saved_sources(self):
        with saved_stage1_case(checkpoint=False) as (case, fixture):
            ledger, ref = fixture["ledger"], fixture["ref"]
            self.assertFalse(
                any(row["payload"]["kind"] == "Checkpoint" for row in ledger.events())
            )
            work = fixture["records"]["papers"][0]["work_id"]
            snapshot = saved_reading_snapshot(case.producer, ref, work)
            self.assertIsNone(snapshot["checkpoint"])
            original = canonical(snapshot)
            prompt = reading_prompt(snapshot)
            visible = json.loads(
                prompt.split("BEGIN SAVED INPUT JSON\n", 1)[1].rsplit(
                    "\nEND SAVED INPUT JSON", 1
                )[0]
            )
            self.assertLessEqual(len(prompt.encode("utf8")), 10000)
            self.assertIsNone(visible["checkpoint"])
            self.assertEqual(visible["context_projection"]["excluded_metadata"], [])
            self.assertEqual(
                {k: v for k, v in visible.items() if k != "context_projection"},
                snapshot,
            )
            self.assertEqual(canonical(snapshot), original)
            factory = Mock(side_effect=AssertionError("model launch"))
            model = ProjectModelService(
                case.intake,
                provider_factory=factory,
                model="synthetic-reader",
                reading_records=case.producer,
            )
            self.addCleanup(model.close)
            view = case.intake.read("alice-token", ref)
            preview = model.reading_offer(
                "alice-token",
                ref,
                work,
                expected_input_version=view["input_version"],
                expected_ledger_state_sha256=ledger.state_hash(),
            )
            self.assertTrue(preview["available"], preview)
            self.assertEqual(preview["snapshot_sha256"], sha(original))
            self.assertEqual(
                view["revision"], case.intake.read("alice-token", ref)["revision"]
            )
            factory.assert_not_called()

    def test_oversized_prompt_is_unavailable_and_authorization_keeps_no_permit(self):
        original = delivery_fixture.submit_body

        def funded(view):
            body = original(view)
            body["budgets"].update(model_calls=2, seconds=60)
            return body

        with (
            patch.object(delivery_fixture, "submit_body", side_effect=funded),
            saved_stage1_case() as (case, fixture),
        ):
            ref = fixture["ref"]
            work = fixture["records"]["papers"][0]["work_id"]
            snapshot = saved_reading_snapshot(case.producer, ref, work)
            # Authored prompt-size fault at the saved-snapshot seam. Production
            # source/registry verification is unchanged; no model is launched.
            original_source = snapshot["sources"][0]
            snapshot["sources"] = []
            for number in range(1):
                source = deepcopy(original_source)
                source.update(
                    source_id="authored-size-source-" + str(number),
                    excerpt="字" * 3800,
                    excerpt_end_byte=11400,
                    text_bytes=11400,
                    entire_text_in_prompt=True,
                )
                snapshot["sources"].append(source)
            self.assertTrue(
                all(
                    len(row["excerpt"].encode("utf8")) <= 12000
                    for row in snapshot["sources"]
                )
            )
            self.assertLess(len(canonical(snapshot)), 48000)
            self.assertLess(len(canonical(snapshot)), 32768)
            with self.assertRaises(SessionApiError) as blocked:
                reading_prompt(snapshot)
            self.assertEqual(
                blocked.exception.code,
                "reading-prompt-too-large-segmentation-unavailable",
            )
            factory = Mock(side_effect=AssertionError("model launch"))
            model = ProjectModelService(
                case.intake,
                provider_factory=factory,
                model="synthetic-reader",
                reading_records=case.producer,
            )
            self.addCleanup(model.close)
            view = case.intake.read("alice-token", ref)
            before = fixture["ledger"].state_hash()
            permits_before = sorted(case.intake.root.rglob("content-permit-*.json"))
            with patch.object(model, "_reading_snapshot", return_value=snapshot):
                preview = model.reading_offer(
                    "alice-token",
                    ref,
                    work,
                    expected_input_version=view["input_version"],
                    expected_ledger_state_sha256=before,
                )
                self.assertFalse(preview["available"])
                self.assertEqual(preview["blocked_reason"], blocked.exception.code)
                self.assertEqual(
                    case.intake.read("alice-token", ref)["revision"], view["revision"]
                )
                body = dict(
                    key="authored-oversized-reading",
                    **{
                        name: view[name]
                        for name in ("revision", "input_version", "brief_sha256")
                    },
                    operation="read-paper",
                    work_ref=work,
                    snapshot_sha256=sha(canonical(snapshot)),
                    confirmed=True,
                    user_input="Authored prompt-size regression; no execution.",
                )
                with self.assertRaises(SessionApiError) as refused:
                    model.authorize("alice-token", ref, body)
                self.assertEqual(refused.exception.code, "intake-operation-failed")
                receipt = refused.exception.receipt
                self.assertEqual(receipt["status"], "failed")
                self.assertIn(blocked.exception.code, receipt["error"])
                saved = case.intake._load("alice", ref)
                self.assertEqual(
                    saved.get("model_operations", {}).get("offers", {}), {}
                )
                self.assertEqual(
                    sorted(case.intake.root.rglob("content-permit-*.json")),
                    permits_before,
                )
                replay = model.authorize("alice-token", ref, body)
                self.assertTrue(replay["replayed"])
                self.assertEqual(replay["request_sha256"], receipt["request_sha256"])
            factory.assert_not_called()
            self.assertEqual(fixture["ledger"].state_hash(), before)

    def test_snapshot_replays_actual_saved_source_and_preserves_unknown_without_mutation(
        self,
    ):
        with saved_stage1_case() as (case, fixture):
            paper = fixture["records"]["papers"][0]
            before = fixture["ledger"].state_hash()
            revision = case.intake.read("alice-token", fixture["ref"])["revision"]
            snapshot = saved_reading_snapshot(
                case.producer, fixture["ref"], paper["work_id"]
            )
            source = snapshot["sources"][0]
            self.assertEqual(
                source["text_sha256"],
                sha(fixture["ledger"].read_ref(source["text_ref"])),
            )
            saved_bytes = canonical(snapshot)
            prompt = reading_prompt(snapshot)
            self.assertIn("Synthetic", prompt)
            self.assertLessEqual(len(prompt.encode("utf8")), 10000)
            visible = json.loads(
                prompt.split("BEGIN SAVED INPUT JSON\n", 1)[1].rsplit(
                    "\nEND SAVED INPUT JSON", 1
                )[0]
            )
            self.assertEqual(
                {
                    k: v
                    for k, v in visible.items()
                    if k not in {"checkpoint", "context_projection"}
                },
                {k: v for k, v in snapshot.items() if k != "checkpoint"},
            )
            self.assertEqual(
                visible["checkpoint"]["saved_checkpoint_sha256"],
                sha(canonical(snapshot["checkpoint"])),
            )
            self.assertEqual(
                visible["context_projection"]["excluded_metadata"],
                ["checkpoint.created_at", "checkpoint.stage_result"],
            )
            self.assertFalse(
                visible["context_projection"]["source_or_claim_text_truncated"]
            )
            self.assertEqual(canonical(snapshot), saved_bytes)
            checked = validate_reading_draft(canonical(draft(snapshot)), snapshot)
            self.assertEqual(checked["draft"]["findings"]["main_findings"], "Unknown")
            self.assertFalse(checked["core_claims_created"])
            self.assertFalse(checked["scientific_acceptance"])
            self.assertEqual(before, fixture["ledger"].state_hash())
            self.assertEqual(
                revision, case.intake.read("alice-token", fixture["ref"])["revision"]
            )

    def test_source_tamper_and_invented_or_wrong_quote_spans_refuse(self):
        with saved_stage1_case() as (case, fixture):
            work = fixture["records"]["papers"][0]["work_id"]
            snapshot = saved_reading_snapshot(case.producer, fixture["ref"], work)
            good = draft(snapshot)
            for change, code in (
                (
                    {"start_byte": good["evidence"][0]["start_byte"] + 1},
                    "reading-draft-quote-differs",
                ),
                (
                    {"claim_id": "invented-claim"},
                    "reading-draft-existing-claim-differs",
                ),
                ({"text_sha256": "0" * 64}, "reading-draft-source-differs"),
            ):
                bad = deepcopy(good)
                bad["evidence"][0].update(change)
                with self.assertRaisesRegex(SessionApiError, code):
                    validate_reading_draft(canonical(bad), snapshot)
            path = fixture["path"].parent / "source/source-fetch-result.json"
            path.write_bytes(path.read_bytes() + b" ")
            with self.assertRaises(ValueError):
                saved_reading_snapshot(case.producer, fixture["ref"], work)

    def test_consumed_reading_permits_are_unavailable_after_success_or_unknown_failure(
        self,
    ):
        original = delivery_fixture.submit_body

        def funded(view):
            body = original(view)
            body["budgets"].update(model_calls=2, seconds=60)
            return body

        for fails in (False, True):
            with (
                self.subTest(fails=fails),
                patch.object(delivery_fixture, "submit_body", side_effect=funded),
                saved_stage1_case() as (case, fixture),
            ):
                ref = fixture["ref"]
                work = fixture["records"]["papers"][0]["work_id"]
                called = []

                def factory(*, context, admit, output_root):
                    called.append(context)

                    class Reader:
                        def run(inner, key, prompt, deadline):
                            event = dict(
                                unit_key=key,
                                prompt_sha256=sha(prompt.encode("utf8")),
                                source_sha256=context["source_sha256"],
                                permit_sha256=context["permit_sha256"],
                                event={},
                            )
                            admit(dict(event, phase="reserve"))
                            admit(dict(event, phase="spawn"))
                            if fails:
                                raise RuntimeError("Synthetic post-reservation failure")
                            return dict(
                                status="completed",
                                prompt_sha256=event["prompt_sha256"],
                                source_sha256=event["source_sha256"],
                                final_text=canonical(
                                    draft(context["saved_reading"])
                                ).decode("utf8"),
                                synthetic=True,
                            )

                        def verify_receipt(inner, receipt, **expected):
                            return receipt

                    return Reader()

                model = ProjectModelService(
                    case.intake,
                    provider_factory=factory,
                    model="synthetic-reader",
                    local_cap_seconds=5,
                    clock=lambda: 1_900_000_000,
                    reading_records=case.producer,
                )
                try:
                    snapshot = saved_reading_snapshot(case.producer, ref, work)
                    view = case.intake.read("alice-token", ref)
                    authorization_body = dict(
                        key="spent-reading-authorization",
                        **{
                            name: view[name]
                            for name in ("revision", "input_version", "brief_sha256")
                        },
                        operation="read-paper",
                        work_ref=work,
                        snapshot_sha256=sha(canonical(snapshot)),
                        confirmed=True,
                        user_input="Read this saved synthetic source once.",
                    )
                    authorized = model.authorize("alice-token", ref, authorization_body)
                    offer = authorized["offer"]
                    self.assertTrue(
                        model.offers("alice-token", ref)["offers"][0]["available"]
                    )
                    view = case.intake.read("alice-token", ref)
                    body = dict(
                        key="spent-reading",
                        **{
                            name: view[name]
                            for name in ("revision", "input_version", "brief_sha256")
                        },
                        offer_ref=offer["offer_ref"],
                        offer_sha256=offer["offer_sha256"],
                        confirmed=True,
                    )
                    model.execute("alice-token", ref, body)
                    stop = time.monotonic() + 5
                    while time.monotonic() < stop:
                        job = model.history("alice-token", ref)["actions"][-1]
                        if job["status"] in {
                            "content-review-pending",
                            "validation-failed",
                            "failed-or-unknown",
                        }:
                            break
                        time.sleep(0.01)
                    self.assertEqual(
                        job["status"],
                        "failed-or-unknown" if fails else "content-review-pending",
                        job,
                    )
                    spent = model.offers("alice-token", ref)["offers"][0]
                    self.assertFalse(spent["available"])
                    self.assertEqual(
                        spent["blocked_reason"], "model-permit-call-budget-exhausted"
                    )
                    self.assertEqual(job["calls_reserved"], 1)
                    self.assertTrue(model.execute("alice-token", ref, body)["replayed"])
                    self.assertEqual(len(called), 1)
                    if not fails:
                        view = case.intake.read("alice-token", ref)
                        fresh = model.authorize(
                            "alice-token",
                            ref,
                            dict(
                                authorization_body,
                                key="fresh-reading-authorization",
                                revision=view["revision"],
                            ),
                        )["offer"]
                        available = {
                            row["offer_ref"]: row["available"]
                            for row in model.offers("alice-token", ref)["offers"]
                        }
                        self.assertEqual(
                            available,
                            {offer["offer_ref"]: False, fresh["offer_ref"]: True},
                        )
                        self.assertEqual(len(called), 1)
                finally:
                    model.close()

    def test_shared_queue_reserves_once_and_publishes_only_verified_reading_draft(self):
        original = delivery_fixture.submit_body
        host_token = "reading-http-fixture-token-with-more-than-32-characters"

        def funded(view):
            body = original(view)
            body["budgets"].update(model_calls=2, seconds=60)
            return body

        with (
            patch.object(delivery_fixture, "submit_body", side_effect=funded),
            patch.object(
                delivery_fixture,
                "authenticate",
                side_effect=lambda token: (
                    "local-viewer" if token in {"alice-token", host_token} else None
                ),
            ),
        ):
            with saved_stage1_case() as (case, fixture):
                ref = fixture["ref"]
                work = fixture["records"]["papers"][0]["work_id"]
                called = []

                def factory(*, context, admit, output_root):
                    self.assertFalse(case.intake.db.in_transaction)
                    called.append(context)

                    class Reader:
                        def run(inner, key, prompt, deadline):
                            event = dict(
                                unit_key=key,
                                prompt_sha256=sha(prompt.encode("utf8")),
                                source_sha256=context["source_sha256"],
                                permit_sha256=context["permit_sha256"],
                                event={},
                            )
                            admit(dict(event, phase="reserve"))
                            admit(dict(event, phase="spawn"))
                            return dict(
                                status="completed",
                                prompt_sha256=event["prompt_sha256"],
                                source_sha256=event["source_sha256"],
                                final_text=canonical(
                                    draft(context["saved_reading"])
                                ).decode("utf8"),
                                synthetic=True,
                            )

                        def verify_receipt(inner, receipt, **expected):
                            return receipt

                    return Reader()

                model = ProjectModelService(
                    case.intake,
                    provider_factory=factory,
                    model="synthetic-reader",
                    reading_records=case.producer,
                )
                try:
                    view = case.intake.read("alice-token", ref)
                    preview = model.reading_offer(
                        "alice-token",
                        ref,
                        work,
                        expected_input_version=view["input_version"],
                        expected_ledger_state_sha256=fixture["ledger"].state_hash(),
                    )
                    self.assertTrue(preview["available"])
                    self.assertFalse(preview["execution_authorized"])
                    self.assertEqual(
                        view["revision"],
                        case.intake.read("alice-token", ref)["revision"],
                    )
                    stale = model.reading_offer(
                        "alice-token",
                        ref,
                        work,
                        expected_input_version=view["input_version"],
                        expected_ledger_state_sha256="0" * 64,
                    )
                    self.assertFalse(stale["available"])
                    self.assertEqual(
                        stale["blocked_reason"], "reading-library-snapshot-stale"
                    )
                    host = ProjectHost(
                        projects=case.intake,
                        credential=host_token,
                        models=model,
                        stage1=case.stage1,
                        files={},
                        views=[],
                        port=0,
                    )
                    worker = threading.Thread(target=host.serve_forever, daemon=True)
                    worker.start()
                    try:
                        library = host.project_stage1_library.read("alice-token", ref)
                        row_index = next(
                            index
                            for index, row in enumerate(library["projection"]["rows"])
                            if row["work_id"] == work
                        )
                        path = f"/api/projects/{ref}/stage1/screening-detail/{view['input_version']}/{fixture['ledger'].state_hash()}/{library['projection_sha256']}/{row_index}"
                        client = http.client.HTTPConnection(
                            "127.0.0.1", host.server_port, timeout=10
                        )
                        try:
                            client.request(
                                "GET",
                                path,
                                headers={"Authorization": "Bearer " + host_token},
                            )
                            response = client.getresponse()
                            detail = json.loads(response.read())
                            self.assertEqual(response.status, 200, detail)
                            self.assertEqual(detail["reading_offer"], preview)
                            self.assertEqual(called, [])
                        finally:
                            client.close()
                    finally:
                        host.shutdown()
                        host.server_close()
                        worker.join(3)
                    authorized = model.authorize(
                        "alice-token",
                        ref,
                        dict(
                            key="reading-authorization",
                            **{
                                name: view[name]
                                for name in (
                                    "revision",
                                    "input_version",
                                    "brief_sha256",
                                )
                            },
                            operation="read-paper",
                            work_ref=work,
                            snapshot_sha256=preview["snapshot_sha256"],
                            confirmed=True,
                            user_input="Read this saved synthetic source once.",
                        ),
                    )
                    self.assertEqual(called, [])
                    self.assertEqual(authorized["offer"]["work_ref"], work)
                    view = case.intake.read("alice-token", ref)
                    body = dict(
                        key="saved-reading",
                        **{
                            name: view[name]
                            for name in ("revision", "input_version", "brief_sha256")
                        },
                        offer_ref=authorized["offer"]["offer_ref"],
                        offer_sha256=authorized["offer"]["offer_sha256"],
                        confirmed=True,
                    )
                    before = fixture["ledger"].state_hash()
                    queued = model.execute("alice-token", ref, body)
                    stop = time.monotonic() + 5
                    while time.monotonic() < stop:
                        job = model.history("alice-token", ref)["actions"][-1]
                        if job["status"] in {
                            "content-review-pending",
                            "validation-failed",
                            "failed-or-unknown",
                        }:
                            break
                        time.sleep(0.01)
                    self.assertEqual(job["status"], "content-review-pending", job)
                    self.assertGreater(job["reading_draft"]["evidence_count"], 0)
                    self.assertFalse(job["reading_draft"]["core_claims_created"])
                    replay = model.execute("alice-token", ref, body)
                    self.assertTrue(replay["replayed"])
                    self.assertEqual(queued["request_sha256"], replay["request_sha256"])
                    self.assertEqual(len(called), 1)
                    self.assertEqual(
                        model.read("alice-token", ref)["calls_reserved"], 1
                    )
                    self.assertEqual(before, fixture["ledger"].state_hash())
                    factory_root = case.root / "reading-factory"
                    factory_root.mkdir()
                    own_home = factory_root / "account"
                    own_home.mkdir()
                    config = own_home / "config.toml"
                    config.write_text('model = "synthetic-reader"\n', encoding="utf8")
                    executable = factory_root / "codex.exe"
                    executable.write_bytes(b"Synthetic executable; never launched.")
                    prepared = []

                    def fake_stage(checked, **kwargs):
                        prepared.append(checked)
                        return object()

                    with patch.dict(os.environ, {"CODEX_HOME": str(own_home)}):
                        import planned_query_fixture

                        proof = getattr(planned_query_fixture, "RAW_SOURCE_PROOF", None)
                        owned_repo = (
                            Path(proof["repo"])
                            if proof is not None
                            else Path(__file__).resolve().parents[3]
                        )
                        own_factory = OwnAccountProjectModelFactory(
                            owned_repo,
                            executable,
                            config,
                            own_home,
                            case.intake.authenticate,
                            "alice-token",
                            stage_model_factory=fake_stage,
                        )
                        native = own_factory(
                            context=called[0],
                            admit=lambda event: True,
                            output_root=factory_root / "native",
                        )
                        saved_input = prepared[0]["source_root"] / "saved-reading.json"
                        self.assertEqual(
                            json.loads(saved_input.read_bytes()),
                            called[0]["saved_reading"],
                        )
                        saved_input.write_bytes(saved_input.read_bytes() + b" ")
                        with self.assertRaisesRegex(
                            ValueError, "frozen model input changed"
                        ):
                            native.status()
                finally:
                    model.close()


if __name__ == "__main__":
    unittest.main()
