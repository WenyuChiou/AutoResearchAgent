"""Saved reading review: real SQLite/Core and authored synthetic model/HTTP."""

from contextlib import contextmanager
from copy import deepcopy
import http.client
import json
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cli"))

import test_project_stage1_delivery as delivery_fixture
from test_project_stage1_claims import reading_case
from research_workspace_native.project_host import ProjectHost
from research_workspace_native.project_reading_review import ProjectReadingReviewService
from research_workspace_native.project_stage1_claims import ProjectStage1ClaimService
from research_workspace_native.session_api import SessionApiError
from stage1_deliverable.common import canonical, read_json, sha


def service(context):
    return ProjectReadingReviewService(context["claims"])


def body(context, key="review-reading"):
    view = service(context).view("alice-token", context["ref"], context["output_ref"])
    offer = view["reading_review_offer"]
    return dict(
        key=key,
        confirmed=True,
        offer_ref=offer["offer_ref"],
        offer_sha256=offer["offer_sha256"],
        review=dict(
            classification=deepcopy(view["draft"]["classification"]),
            findings=deepcopy(view["draft"]["findings"]),
            roles=[],
        ),
        **{
            name: view[name]
            for name in (
                "revision",
                "input_version",
                "brief_sha256",
                "ledger_state_sha256",
                "output_ref",
                "draft_sha256",
            )
        },
    )


def actions(context):
    return context["case"].intake.history("alice-token", context["ref"])["actions"]


class ProjectReadingReviewTests(unittest.TestCase):
    def test_saved_unknown_and_all_current_claims_keep_original_core_history(self):
        with reading_case(pending=True) as c:
            ledger = c["ledger"]
            old_claim = next(
                row["payload"]
                for row in ledger.events()
                if row["payload"]["kind"] == "ClaimEvidence"
            )
            pending = ledger.claim(
                work_id=old_claim["work_id"],
                version_id=old_claim["version_id"],
                claim_text="Unknown: explicit synthetic pending observation",
                relation="pending",
                evidence_level="unavailable",
                locator=None,
                source_ref=deepcopy(old_claim["source_ref"]),
                verifier=dict(actor="fixture", actor_type="human", method="synthetic"),
            )
            before = ledger.events()
            request = body(c)
            result = service(c).review("alice-token", c["ref"], request)
            self.assertEqual(result["status"], "saved")
            raw_receipt = (
                c["case"]
                .intake.db.execute(
                    "SELECT receipt FROM intake_actions WHERE principal=? AND project=? AND key=?",
                    ("alice", c["ref"], request["key"]),
                )
                .fetchone()
            )
            saved_receipt = json.loads(raw_receipt[0])
            semantic = {
                name: value for name, value in request.items() if name != "revision"
            }
            self.assertEqual(saved_receipt["request"], semantic)
            self.assertEqual(
                result["request_sha256"],
                sha(
                    canonical(
                        dict(
                            kind="stage1-reading-registry",
                            body=semantic,
                        )
                    )
                ),
            )
            self.assertNotIn("entry_sha256", saved_receipt["request"])
            entry = result["registry_entry"]
            reading = entry["payload"]
            self.assertEqual(reading["schema_version"], "1.1.0")
            self.assertEqual(reading["findings"]["main_findings"], "Unknown")
            self.assertEqual(reading["roles"], [])
            required = {
                row["payload"]["event_id"]
                for row in before
                if row["payload"]["kind"] == "ClaimEvidence"
                and (row["payload"]["work_id"], row["payload"]["version_id"])
                == (reading["work_id"], reading["version_id"])
            }
            self.assertEqual({row["claim_id"] for row in reading["claims"]}, required)
            span = next(row for row in reading["claims"] if row["claim_id"] == pending)
            self.assertEqual(
                [span[name] for name in ("start", "end", "quote")], [None] * 3
            )
            self.assertEqual(ledger.events(), before)
            context = c["case"].producer._context(c["ref"], ledger.state_hash())
            self.assertIn(entry, c["case"].producer._entries(context))
            self.assertEqual(len(c["called"]), 1)
            c["case"].runner.assert_not_called()

    def test_same_key_history_changed_payload_and_duplicate_entry_new_key(self):
        with reading_case() as c:
            api, request = service(c), body(c)
            result = api.review("alice-token", c["ref"], request)
            before = actions(c)
            with patch.object(api, "view", side_effect=AssertionError("replay read")):
                replay = api.review(
                    "alice-token", c["ref"], {**request, "revision": 999}
                )
                self.assertTrue(replay["replayed"])
                self.assertEqual(replay["registry_entry"], result["registry_entry"])
                changed = deepcopy(request)
                changed["review"]["findings"]["main_findings"] = "Changed annotation"
                with self.assertRaisesRegex(SessionApiError, "idempotency"):
                    api.review("alice-token", c["ref"], changed)
            duplicate = body(c, "different-key-same-entry")
            with self.assertRaisesRegex(SessionApiError, "entry-already-registered"):
                api.review("alice-token", c["ref"], duplicate)
            self.assertEqual(actions(c), before)
            context = c["case"].producer._context(c["ref"], c["ledger"].state_hash())
            c["case"].producer._entries(context)
            self.assertEqual(len(c["called"]), 1)

    def test_source_draft_ledger_owner_and_caller_envelopes_fail_before_intent(self):
        with reading_case() as c:
            api, request = service(c), body(c)
            baseline, events = actions(c), c["ledger"].events()
            for update in (
                {"root": "caller-path"},
                {"confirmed": 1},
                {"input_version": 999},
                {"offer_sha256": "0" * 64},
                {"review": {**request["review"], "source_path": "caller"}},
            ):
                with self.subTest(update=update), self.assertRaises(SessionApiError):
                    api.review("alice-token", c["ref"], {**request, **update})
                self.assertEqual(actions(c), baseline)
            with self.assertRaises(SessionApiError):
                api.review("bob-token", c["ref"], request)
            actor = c["case"].intake._principal("alice-token")
            job = c["models"]._job(actor, c["ref"], "reading-job")
            folder = c["models"]._runtime_folder(actor, c["ref"], job)
            source = c["fixture"]["records"]["sources"][0]
            sdk = read_json(c["fixture"]["path"].parent / source["result_path"])
            for path in (
                folder / "reading-draft.json",
                Path(sdk["extracted_text_path"]),
            ):
                raw = path.read_bytes()
                try:
                    path.write_bytes(raw + b" altered")
                    with (
                        self.subTest(path=path.name),
                        self.assertRaises(SessionApiError),
                    ):
                        api.review("alice-token", c["ref"], request)
                finally:
                    path.write_bytes(raw)
                self.assertEqual(actions(c), baseline)

            @contextmanager
            def lost_owner(*_):
                raise SessionApiError("synthetic-saved-owner-lost")
                yield  # pragma: no cover - contextmanager's generator contract

            with patch.object(c["case"].producer, "guard", lost_owner):
                with self.assertRaisesRegex(SessionApiError, "owner-lost"):
                    api.review("alice-token", c["ref"], request)
            self.assertEqual(actions(c), baseline)
            self.assertEqual(c["ledger"].events(), events)
            old = next(
                row["payload"]
                for row in events
                if row["payload"]["kind"] == "ClaimEvidence"
            )
            c["ledger"].claim(
                **{
                    name: deepcopy(old[name])
                    for name in (
                        "work_id",
                        "version_id",
                        "claim_text",
                        "relation",
                        "evidence_level",
                        "locator",
                        "source_ref",
                        "verifier",
                    )
                }
            )
            drifted = c["ledger"].events()
            with self.assertRaises(SessionApiError):
                api.review("alice-token", c["ref"], request)
            self.assertEqual(actions(c), baseline)
            self.assertEqual(c["ledger"].events(), drifted)

    def test_draft_drift_after_records_guard_refuses_before_saved_intent(self):
        with reading_case() as c:
            api, request = service(c), body(c)
            intake = c["case"].intake
            baseline, events = actions(c), c["ledger"].events()
            state = deepcopy(intake._load("alice", c["ref"]))
            job = c["models"]._job("alice", c["ref"], "reading-job")
            folder = c["models"]._runtime_folder("alice", c["ref"], job)
            source = c["fixture"]["records"]["sources"][0]
            sdk = read_json(c["fixture"]["path"].parent / source["result_path"])
            source_bytes = {
                name: Path(sdk[name]).read_bytes()
                for name in ("raw_path", "extracted_text_path")
            }
            original_guard = c["case"].producer.guard
            for name in ("reading-draft.json", "output.txt"):
                path = folder / name
                original_bytes = path.read_bytes()
                entered = []

                @contextmanager
                def mutate_after_guard(*args):
                    with original_guard(*args) as check:
                        entered.append(name)
                        if len(entered) == 1:
                            # The first guard belongs to pure payload derivation.
                            # Drift only after the actual save guard is acquired.
                            yield check
                            return
                        path.write_bytes(original_bytes + b" synthetic late drift")
                        try:
                            yield check
                        finally:
                            path.write_bytes(original_bytes)

                with (
                    self.subTest(artifact=name),
                    patch.object(c["case"].producer, "guard", mutate_after_guard),
                ):
                    with self.assertRaisesRegex(SessionApiError, "artifact-differs"):
                        api.review("alice-token", c["ref"], request)
                self.assertEqual(entered, [name, name])
                self.assertEqual(actions(c), baseline)
                self.assertEqual(intake._load("alice", c["ref"]), state)
                self.assertEqual(c["ledger"].events(), events)
                self.assertEqual(path.read_bytes(), original_bytes)
                for field, observed in source_bytes.items():
                    self.assertEqual(Path(sdk[field]).read_bytes(), observed)
            self.assertEqual(len(c["called"]), 1)
            c["case"].runner.assert_not_called()

    def test_same_deadline_refuses_at_entry_and_before_registry_intent(self):
        with reading_case() as c:
            api, request = service(c), body(c)
            baseline, events = actions(c), c["ledger"].events()

            def expired():
                raise TimeoutError("synthetic reading review deadline expired")

            with self.assertRaises(TimeoutError):
                api.review("alice-token", c["ref"], request, check_deadline=expired)
            self.assertEqual(actions(c), baseline)
            entered = []
            original = c["case"].producer._register

            def register(*args, **kwargs):
                entered.append(True)
                return original(*args, **kwargs)

            def deadline():
                if entered:
                    expired()

            with patch.object(c["case"].producer, "_register", side_effect=register):
                with self.assertRaises(TimeoutError):
                    api.review(
                        "alice-token", c["ref"], request, check_deadline=deadline
                    )
            self.assertEqual(len(entered), 1)
            self.assertEqual(actions(c), baseline)
            self.assertEqual(c["ledger"].events(), events)

    def test_precommit_unknown_survives_sqlite_reopen_and_never_rewrites(self):
        with reading_case() as c:
            api, request = service(c), body(c)
            intake = c["case"].intake
            original = intake._save
            events = c["ledger"].events()

            def saved_sql_then_fail(state, kind, receipt):
                original(state, kind, receipt)
                if kind == "stage1-reading-registry-saved":
                    raise OSError("synthetic failure after saved SQL before commit")

            with patch.object(intake, "_save", side_effect=saved_sql_then_fail):
                with self.assertRaises(SessionApiError) as failed:
                    api.review("alice-token", c["ref"], request)
            receipt = failed.exception.receipt
            self.assertEqual(receipt["status"], "execution-unknown")
            self.assertEqual(receipt["failure_phase"], "post-work-before-commit")
            self.assertIn("registry_entry", receipt["output_observation"])
            c["models"].close()
            c["case"].reopen()
            reopened = c["new_models"]()
            try:
                claims = ProjectStage1ClaimService(
                    c["case"].stage1, reopened, c["case"].producer
                )
                api = ProjectReadingReviewService(claims)
                baseline = actions(c)
                with (
                    patch.object(
                        api, "view", side_effect=AssertionError("replay source read")
                    ),
                    patch.object(
                        c["case"].producer,
                        "register_reading",
                        side_effect=AssertionError("resave"),
                    ) as write,
                ):
                    replay = api.review(
                        "alice-token", c["ref"], {**request, "revision": 999}
                    )
                    self.assertTrue(replay["replayed"])
                    self.assertEqual(replay["status"], "execution-unknown")
                    self.assertEqual(
                        replay["request_sha256"], receipt["request_sha256"]
                    )
                    current = c["case"].intake.read("alice-token", c["ref"])
                    with self.assertRaisesRegex(SessionApiError, "unresolved"):
                        api.review(
                            "alice-token",
                            c["ref"],
                            {
                                **request,
                                "key": "new-key-after-unknown",
                                "revision": current["revision"],
                            },
                        )
                    write.assert_not_called()
                self.assertEqual(actions(c), baseline)
                self.assertEqual(c["ledger"].events(), events)
                self.assertEqual(len(c["called"]), 1)
                c["case"].runner.assert_not_called()
            finally:
                reopened.close()

    def test_real_http_auth_origin_host_and_explicit_review_only(self):
        token = "local-reading-review-token-with-at-least-32-characters"
        with (
            patch.object(
                delivery_fixture,
                "authenticate",
                lambda value: (
                    "local-viewer" if value in {"alice-token", token} else None
                ),
            ),
            reading_case() as c,
        ):
            host = worker = None
            try:
                host = ProjectHost(
                    projects=c["case"].intake,
                    stage1=c["case"].stage1,
                    models=c["models"],
                    credential=token,
                    files={},
                    views=[],
                    port=0,
                )
                # Test-only injection: this saved-Core fixture has no live query owner.
                host.project_stage1_claims = c["claims"]
                host.project_reading_review = service(c)
                worker = threading.Thread(
                    target=host.serve_forever,
                    kwargs={"poll_interval": 0.05},
                    daemon=True,
                )
                worker.start()

                def request(path, value=None, headers=None):
                    supplied = {"Authorization": "Bearer " + token}
                    if value is not None:
                        supplied.update(
                            Origin=host.expected_origin,
                            **{"Content-Type": "application/json"},
                        )
                    supplied.update(headers or {})
                    client = http.client.HTTPConnection(
                        "127.0.0.1", host.server_port, timeout=30
                    )
                    try:
                        client.request(
                            "POST" if value is not None else "GET",
                            path,
                            json.dumps(value).encode("utf8")
                            if value is not None
                            else None,
                            supplied,
                        )
                        response = client.getresponse()
                        return response.status, response.read()
                    finally:
                        client.close()

                base = "/api/projects/" + c["ref"] + "/stage1/"
                baseline, events = actions(c), c["ledger"].events()
                status, raw = request(base + "reading/" + c["output_ref"])
                self.assertEqual(status, 200, raw)
                self.assertIn("reading_review_offer", json.loads(raw))
                value = body(c)
                for headers in (
                    {"Authorization": "Bearer wrong"},
                    {"Origin": "https://foreign.example"},
                    {"Host": "foreign.example"},
                ):
                    with self.subTest(headers=headers):
                        status, raw = request(base + "reading-review", value, headers)
                        self.assertIn(status, (401, 403), raw)
                status, raw = request(
                    base + "reading-review", {**value, "root": "caller-path"}
                )
                self.assertEqual(status, 400, raw)
                self.assertEqual(actions(c), baseline)
                self.assertEqual(c["ledger"].events(), events)
                status, raw = request(base + "reading-review", value)
                self.assertEqual(status, 200, raw)
                self.assertEqual(json.loads(raw)["status"], "saved")
                with patch.object(
                    c["case"].producer,
                    "register_reading",
                    side_effect=AssertionError("HTTP resend"),
                ) as write:
                    status, raw = request(base + "reading-review", value)
                    self.assertEqual(status, 200, raw)
                    self.assertTrue(json.loads(raw)["replayed"])
                    write.assert_not_called()
                self.assertEqual(c["ledger"].events(), events)
                self.assertEqual(len(c["called"]), 1)
                c["case"].runner.assert_not_called()
            finally:
                if host is not None:
                    if worker is not None:
                        host.shutdown()
                    host.server_close()
                if worker is not None:
                    worker.join(3)
                    self.assertFalse(worker.is_alive())


if __name__ == "__main__":
    unittest.main()
