"""Saved-source claims through real Core/SQLite; all sources are authored."""

from contextlib import contextmanager
from http.client import HTTPConnection
import json
import threading
import unittest
from unittest.mock import patch

from test_project_stage1_records import saved_stage1_case
from test_project_stage1_claims import reading_case, body as draft_body
import test_project_stage1_delivery as fixture_module
import test_stage1_deliverable as source_fixture
from research_workspace_native.project_saved_claims import ProjectSavedClaimService
from research_workspace_native.project_host import ProjectHost
from research_workspace_native.project_model_reading import (
    reading_prompt,
    saved_reading_snapshot,
)
from research_workspace_native.session_api import SessionApiError
from stage1_coverage.run import CoverageLedger
from stage1_ledger.validation import validate_run


@contextmanager
def saved_case(long=False):
    original = source_fixture.ResearchDeliverableTests.make_records

    def extended(case, *args, **kwargs):
        if long:
            raw = kwargs.pop("raw", source_fixture.HTML)
            raw = raw.replace(
                b"</article>",
                (
                    "<p>"
                    + "Long authored source. " * 800
                    + "中文😀 exact late passage\r\nSecond raw line</p></article>"
                ).encode("utf8"),
            )
            kwargs["raw"] = raw
        return original(case, *args, **kwargs)

    with (
        patch.object(source_fixture.ResearchDeliverableTests, "make_records", extended),
        saved_stage1_case() as (case, fixture),
    ):
        service = ProjectSavedClaimService(case.stage1, case.producer)
        work = fixture["records"]["papers"][0]["work_id"]
        yield case, fixture, service, work


def request(
    service,
    ref,
    work,
    key="manual",
    assertion="Authored reviewed assertion",
    quote=None,
):
    view = service.view("alice-token", ref, work)
    source = view["selected_source"]
    text = view["page"]["text"]
    quote = quote or text[:30]
    offset = text.index(quote)
    return dict(
        key=key,
        confirmed=True,
        work_ref=work,
        source_ref=source["source_ref"],
        offer_sha256=source["offer_sha256"],
        start_byte=len(text[:offset].encode("utf8")),
        end_byte=len(text[: offset + len(quote)].encode("utf8")),
        quote=quote,
        review=dict(
            claim_text=assertion,
            relation="supports",
            evidence_level="full-text",
            section="Authored source",
        ),
        **{
            k: view[k]
            for k in (
                "revision",
                "input_version",
                "brief_sha256",
                "ledger_state_sha256",
            )
        },
    )


class SavedClaimTests(unittest.TestCase):
    def test_six_manual_claims_reach_existing_coverage_without_model(self):
        with saved_case() as (case, f, service, work):
            ledger, ref = f["ledger"], f["ref"]
            old = ledger.events()
            claims = {}
            for field in (
                "title",
                "authors",
                "year",
                "identifier",
                "version",
                "relevance",
            ):
                result = service.claim(
                    "alice-token",
                    ref,
                    request(service, ref, work, field, "Authored review of " + field),
                )
                self.assertEqual(result["status"], "saved")
                self.assertFalse(result["stage1_complete"])
                claims[field] = result["claim_event_id"]
            snapshot = saved_reading_snapshot(case.producer, ref, work, excerpt_bytes=0)
            self.assertTrue(
                set(claims.values())
                <= {row["event_id"] for row in snapshot["existing_claims"]}
            )
            self.assertTrue(all(row["excerpt"] == "" for row in snapshot["sources"]))
            self.assertEqual(service.view("alice-token", ref, work)["model_calls"], 0)
            with self.assertRaises(SessionApiError) as refused:
                reading_prompt(snapshot)
            self.assertEqual(
                refused.exception.code,
                "reading-prompt-too-large-segmentation-unavailable",
            )
            coverage = case.stage1.read("alice-token", ref)["coverage_actions"]
            offer = next(
                o
                for o in coverage["offers"]
                if o["operation"] == "review-work" and o["document"]["work_ref"] == work
            )
            self.assertTrue(
                set(claims.values())
                <= {v["claim_ref"] for v in offer["document"]["claims"]}
            )
            bound = case.intake.read("alice-token", ref)
            review = dict(
                cluster_claims={
                    offer["document"]["clusters"][0]["cluster_id"]: claims["relevance"]
                },
                identity_status="verified",
                identity_claims={k: claims[k] for k in claims if k != "relevance"},
                closest=False,
                rationale="Explicit authored review; not a real identity attestation",
            )
            case.stage1.coverage(
                "alice-token",
                ref,
                dict(
                    key="review",
                    confirmed=True,
                    operation="review-work",
                    offer_ref=offer["offer_ref"],
                    offer_sha256=offer["offer_sha256"],
                    review=review,
                    ledger_state_sha256=ledger.state_hash(),
                    **{
                        k: bound[k]
                        for k in ("revision", "input_version", "brief_sha256")
                    },
                ),
            )
            self.assertEqual(
                len(
                    set(
                        ledger.coverage_state()
                        .evidence.current()[work]["identity_claims"]
                        .values()
                    )
                ),
                5,
            )
            self.assertEqual(ledger.events()[: len(old)], old)
            self.assertTrue(validate_run(ledger.root)["valid"])
            case.runner.assert_not_called()

    def test_replay_and_duplicate_payload_refusal(self):
        with saved_case() as (case, f, service, work):
            body = request(service, f["ref"], work)
            result = service.claim("alice-token", f["ref"], body)
            events = f["ledger"].events()
            with patch.object(
                CoverageLedger, "claim", side_effect=AssertionError("duplicate")
            ):
                replay = service.claim(
                    "alice-token", f["ref"], {**body, "revision": 999}
                )
                self.assertTrue(replay["replayed"])
                self.assertEqual(replay["claim_event_id"], result["claim_event_id"])
                with self.assertRaisesRegex(SessionApiError, "idempotency"):
                    service.claim("alice-token", f["ref"], {**body, "quote": "changed"})
                with self.assertRaisesRegex(SessionApiError, "already-recorded"):
                    service.claim(
                        "alice-token", f["ref"], request(service, f["ref"], work, "new")
                    )
            self.assertEqual(events, f["ledger"].events())

    def test_invalid_stale_foreign_and_tampered_source_before_intent(self):
        with saved_case() as (case, f, service, work):
            ref = f["ref"]
            good = request(service, ref, work)
            history = case.intake.history("alice-token", ref)
            for change in (
                {"start_byte": True},
                {"end_byte": -1},
                {"source_ref": "foreign"},
                {"offer_sha256": "0" * 64},
                {"quote": "wrong"},
                {"root": "caller"},
                {"review": {**good["review"], "section": "\ud800"}},
            ):
                with (
                    self.subTest(change=change),
                    self.assertRaises((ValueError, TypeError)),
                ):
                    service.claim("alice-token", ref, {**good, **change})
                self.assertEqual(case.intake.history("alice-token", ref), history)
            with self.assertRaises(SessionApiError):
                service.view("bob-token", ref, work)
            snapshot = service._context(ref, work, None)
            entry = snapshot["source_registry_entries"][
                snapshot["sources"][0]["source_id"]
            ]
            path = case.producer.root / entry["result_path"]
            original = path.read_bytes()
            try:
                path.write_bytes(original + b" ")
                with self.assertRaises(SessionApiError):
                    service.claim("alice-token", ref, good)
            finally:
                path.write_bytes(original)
            self.assertEqual(case.intake.history("alice-token", ref), history)

    def test_post_append_unknown_survives_true_sqlite_reopen(self):
        with saved_case() as (case, f, service, work):
            body = request(service, f["ref"], work)
            append = CoverageLedger.claim

            def fail(ledger, **kwargs):
                append(ledger, **kwargs)
                raise OSError("Authored after-append failure")

            with (
                patch.object(CoverageLedger, "claim", fail),
                self.assertRaises(SessionApiError) as error,
            ):
                service.claim("alice-token", f["ref"], body)
            self.assertEqual(error.exception.receipt["status"], "execution-unknown")
            saved = f["ledger"].events()
            case.reopen()
            reopened = ProjectSavedClaimService(case.stage1, case.producer)
            with patch.object(
                CoverageLedger, "claim", side_effect=AssertionError("resend")
            ):
                self.assertEqual(
                    reopened.claim("alice-token", f["ref"], body)["status"],
                    "execution-unknown",
                )
                with self.assertRaises(SessionApiError):
                    reopened.claim("alice-token", f["ref"], {**body, "key": "new"})
            self.assertEqual(f["ledger"].events(), saved)

    def test_pagination_past_model_excerpt_and_multibyte_quote(self):
        with saved_case(long=True) as (case, f, service, work):
            view = service.view("alice-token", f["ref"], work)
            before = case.intake.history("alice-token", f["ref"])
            while "中文😀" not in view["page"]["text"]:
                view = service.view(
                    "alice-token",
                    f["ref"],
                    work,
                    view["selected_source"]["source_ref"],
                    view["page"]["next_byte"],
                )
            self.assertGreater(view["page"]["start_byte"], 12000)
            quote = "中文😀 exact late passage"
            offset = view["page"]["start_byte"] + len(
                view["page"]["text"].split(quote)[0].encode("utf8")
            )
            body = request(service, f["ref"], work)
            body.update(
                start_byte=offset,
                end_byte=offset + len(quote.encode("utf8")),
                quote=quote,
            )
            with self.assertRaises((ValueError, UnicodeError)):
                service.claim(
                    "alice-token", f["ref"], {**body, "start_byte": offset + 1}
                )
            self.assertEqual(case.intake.history("alice-token", f["ref"]), before)
            self.assertEqual(
                service.claim("alice-token", f["ref"], body)["reading_locator"][
                    "quote"
                ],
                quote,
            )

    def test_manual_receipt_does_not_block_model_draft_claims(self):
        with reading_case() as c:
            work = c["fixture"]["records"]["papers"][0]["work_id"]
            service = ProjectSavedClaimService(
                c["case"].stage1, c["case"].producer, c["models"]
            )
            service.claim("alice-token", c["ref"], request(service, c["ref"], work))
            self.assertEqual(
                c["claims"].claim("alice-token", c["ref"], draft_body(c))["status"],
                "saved",
            )

    def test_real_http_routes_auth_and_durable_refusal(self):
        token = "authored-local-token-at-least-32-characters"
        with (
            patch.object(
                fixture_module,
                "authenticate",
                lambda t: "local-viewer" if t in {token, "alice-token"} else None,
            ),
            saved_case() as (case, f, service, work),
        ):
            host = ProjectHost(
                projects=case.intake,
                credential=token,
                stage1=case.stage1,
                files={},
                views=[],
                port=0,
            )
            host.project_saved_claims = service  # Offline fixture has no live owner.
            worker = threading.Thread(
                target=host.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True
            )
            worker.start()

            def http(tail, body=None, credential=token):
                client = HTTPConnection("127.0.0.1", host.server_port, timeout=30)
                headers = {
                    "Authorization": "Bearer " + credential,
                    "Origin": host.expected_origin,
                    "Content-Type": "application/json",
                }
                try:
                    client.request(
                        "POST" if body else "GET",
                        "/api/projects/" + f["ref"] + "/stage1/" + tail,
                        json.dumps(body).encode() if body else None,
                        headers,
                    )
                    response = client.getresponse()
                    return response.status, json.loads(response.read())
                finally:
                    client.close()

            try:
                self.assertEqual(http("source-claims/" + work)[0], 200)
                self.assertEqual(
                    http("source-claims/" + work, credential="foreign")[0], 401
                )
                bad = request(service, f["ref"], work)
                bad["offer_sha256"] = "0" * 64
                status, result = http("source-claim", bad)
                self.assertEqual(status, 409)
                self.assertEqual(result["receipt"]["status"], "known-unsent")
                good = request(service, f["ref"], work, "http-good")
                good["review"]["assessment"] = dict(
                    reason_code="located-source-support",
                    rationale="The authored passage explicitly states this assertion within the reviewed scope.",
                )
                saved = http("source-claim", good)[1]
                self.assertEqual(saved["status"], "saved")
                event = f["ledger"].event(saved["claim_event_id"])
                self.assertEqual(event["schema_version"], "1.1.0")
                self.assertEqual(event["assessment"], good["review"]["assessment"])
                self.assertTrue(http("source-claim", good)[1]["replayed"])
            finally:
                host.shutdown()
                host.server_close()
                worker.join(5)
                self.assertFalse(worker.is_alive())
            case.reopen()
            self.assertEqual(f["ledger"].event(saved["claim_event_id"]), event)
            from test_stage1_core_records import produced
            from research_workspace.delivery_review import derive_delivery_review
            from research_workspace.canonical_delivery import project_canonical_atlas
            from research_workspace_native.project_stage1_delivery import _io_root
            from stage1_deliverable.package import build
            from stage1_deliverable.common import sha

            f["checkpoint"] = f["ledger"].checkpoint()
            for records, _ in f["pairs"]:
                paper = records["papers"][0]
                reading = case.producer.derive_reading_payload(
                    f["ref"],
                    paper["work_id"],
                    classification=paper["classification"],
                    findings=paper["findings"],
                    roles=[],
                    expected_ledger_state_sha256=f["ledger"].state_hash(),
                )
                case.producer.register_reading(
                    f["ref"],
                    reading=reading,
                    expected_ledger_state_sha256=f["ledger"].state_hash(),
                )
            _, records_path, records = produced(case, f)
            self.assertEqual(records["schema_version"], "1.2.0")
            self.assertEqual(
                records["screening_library"]["counts"]["total_candidates"],
                len(f["ledger"].candidates()),
            )
            claim = next(
                c for c in records["claims"] if c["claim_id"] == event["event_id"]
            )
            self.assertEqual(claim["core_event"]["payload"], event)
            delivery_root = _io_root(case.fixture_root / "reason-package")
            receipt = build(records_path, delivery_root, sha(records_path.read_bytes()))
            index, files = project_canonical_atlas(
                delivery_root, "authored", receipt["manifest_sha256"]
            )
            self.assertIn("literature/claim_verification.json", files)
            row = next(
                c
                for c in derive_delivery_review(index)["claims"]
                if c["claim_id"] == event["event_id"]
            )
            self.assertEqual(row["assessment"], event["assessment"])
            case.runner.assert_not_called()


if __name__ == "__main__":
    unittest.main()
