"""Committed records survive registration failure without re-running a producer."""

from contextlib import contextmanager
import http.client
import json
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cli"))

from test_project_stage1_records import saved_stage1_case
from test_project_records_prepare import body, actions
from test_workspace_project_intake import bound_body
from research_workspace_native.project_records_prepare import (
    ProjectRecordsPrepareService,
)
from research_workspace_native.project_records_recovery import KIND
from research_workspace_native.project_host import ProjectHost
from research_workspace_native.session_api import SessionApiError
from stage1_deliverable.common import sha


def interrupted(case, fixture):
    service = ProjectRecordsPrepareService(case.producer)
    with patch.object(
        case.delivery,
        "register_records",
        side_effect=TimeoutError("authored registration interruption"),
    ):
        with unittest.TestCase().assertRaisesRegex(
            TimeoutError, "registration interruption"
        ):
            service.prepare("alice-token", fixture["ref"], body(case, fixture))
    return service


def recovery_body(case, fixture, service, key="recover-records"):
    offer = service.recovery.read("alice-token", fixture["ref"])["offers"][0]
    return dict(
        bound_body(case.intake.read("alice-token", fixture["ref"]), key),
        confirmed=True,
        **{name: value for name, value in offer.items() if name != "status"},
    )


class ProjectRecordsRecoveryTests(unittest.TestCase):
    def test_actual_sqlite_reopen_committed_registration_and_history_only_replay(self):
        with saved_stage1_case() as (case, fixture):
            interrupted(case, fixture)
            before, events = actions(case, fixture), fixture["ledger"].events()
            producer = next(
                row for row in before if row["kind"] == "stage1-produce-records"
            )
            path = Path(producer["records_path"])
            original = path.read_bytes()
            old_db = case.intake.db
            case.reopen()
            self.assertIsNot(case.intake.db, old_db)
            service = ProjectRecordsPrepareService(case.producer)
            request = recovery_body(case, fixture, service)
            with patch.object(
                case.producer,
                "produce_records",
                side_effect=AssertionError("producer repeated"),
            ) as produce:
                self.assertEqual(actions(case, fixture), before)
                result = service.recovery.recover(
                    "alice-token", fixture["ref"], request
                )
                self.assertEqual(result["kind"], KIND)
                self.assertEqual(result["status"], "saved")
                self.assertEqual(result["offer"]["records_sha256"], sha(original))
                after = actions(case, fixture)
                self.assertEqual(len(after), len(before) + 1)
                self.assertEqual(
                    [row for row in after if row["key"] != request["key"]], before
                )
                case.reopen()
                service = ProjectRecordsPrepareService(case.producer)
                with patch.object(
                    case.delivery,
                    "register_records",
                    side_effect=AssertionError("registration replayed"),
                ) as register:
                    replay = service.recovery.recover(
                        "alice-token", fixture["ref"], {**request, "revision": 999}
                    )
                    self.assertTrue(replay["replayed"])
                    self.assertEqual(replay["offer"], result["offer"])
                    self.assertEqual(
                        service.recovery.read("alice-token", fixture["ref"])["offers"],
                        [],
                    )
                    register.assert_not_called()
                produce.assert_not_called()
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(actions(case, fixture), after)
            self.assertEqual(fixture["ledger"].events(), events)
            case.runner.assert_not_called()

    def test_fields_identity_source_owner_and_deadline_refuse_before_intent(self):
        with saved_stage1_case() as (case, fixture):
            service = interrupted(case, fixture)
            request = recovery_body(case, fixture, service)
            before, events = actions(case, fixture), fixture["ledger"].events()
            for update in (
                {"records_path": "caller"},
                {"confirmed": 1},
                {"revision": 999},
                {"producer_request_sha256": "0" * 64},
                {"producer_key": "foreign"},
                {"records_sha256": "0" * 64},
                {"checkpoint_event_id": "old"},
                {"brief_sha256": "0" * 64},
                {"input_version": 999},
            ):
                with self.subTest(update=update), self.assertRaises(SessionApiError):
                    service.recovery.recover(
                        "alice-token", fixture["ref"], {**request, **update}
                    )
                self.assertEqual(actions(case, fixture), before)
            with self.assertRaises(SessionApiError):
                service.recovery.recover("bob-token", fixture["ref"], request)

            @contextmanager
            def lost(*_):
                raise OSError("authored owner loss")
                yield

            with (
                patch.object(case.producer, "guard", lost),
                self.assertRaisesRegex(OSError, "owner loss"),
            ):
                service.recovery.recover("alice-token", fixture["ref"], request)

            def expired():
                raise TimeoutError("authored expired deadline")

            with self.assertRaises(TimeoutError):
                service.recovery.recover(
                    "alice-token", fixture["ref"], request, check_deadline=expired
                )
            checked = []
            original_check = service.recovery._producer

            def slow_check(*args, **kwargs):
                result = original_check(*args, **kwargs)
                checked.append(True)
                return result

            def expires_during_validation():
                if checked:
                    expired()

            with (
                patch.object(service.recovery, "_producer", side_effect=slow_check),
                self.assertRaises(TimeoutError),
            ):
                service.recovery.recover(
                    "alice-token",
                    fixture["ref"],
                    request,
                    check_deadline=expires_during_validation,
                )
            self.assertEqual(len(checked), 1)
            source = fixture["pairs"][0][1] / "source/source-fetch-result.json"
            original = source.read_bytes()
            try:
                source.write_bytes(original + b" changed")
                self.assertEqual(
                    service.recovery.read("alice-token", fixture["ref"])["offers"], []
                )
                with self.assertRaises(SessionApiError):
                    service.recovery.recover("alice-token", fixture["ref"], request)
            finally:
                source.write_bytes(original)
            self.assertEqual(actions(case, fixture), before)
            self.assertEqual(fixture["ledger"].events(), events)
            case.runner.assert_not_called()

    def test_unknown_registration_reopen_remains_held_and_never_adopted(self):
        with saved_stage1_case() as (case, fixture):
            service = interrupted(case, fixture)
            request = recovery_body(case, fixture, service)
            save = case.intake._save

            def fail(current, kind, receipt):
                if kind == KIND + "-saved":
                    raise OSError("authored post-work commit interruption")
                return save(current, kind, receipt)

            with (
                patch.object(case.intake, "_save", side_effect=fail),
                self.assertRaises(SessionApiError) as failure,
            ):
                service.recovery.recover("alice-token", fixture["ref"], request)
            self.assertEqual(failure.exception.receipt["status"], "execution-unknown")
            before = actions(case, fixture)
            case.reopen()
            service = ProjectRecordsPrepareService(case.producer)
            with patch.object(
                case.delivery,
                "register_records",
                side_effect=AssertionError("uncertain registration adopted"),
            ) as register:
                replay = service.recovery.recover(
                    "alice-token", fixture["ref"], request
                )
                self.assertEqual(replay["status"], "execution-unknown")
                self.assertEqual(
                    service.recovery.read("alice-token", fixture["ref"])["status"],
                    "recovery-unavailable",
                )
                fresh = dict(
                    request,
                    **bound_body(
                        case.intake.read("alice-token", fixture["ref"]), "new-recovery"
                    ),
                )
                with self.assertRaisesRegex(SessionApiError, "unresolved"):
                    service.recovery.recover("alice-token", fixture["ref"], fresh)
                register.assert_not_called()
            self.assertEqual(actions(case, fixture), before)
            self.assertNotIn(
                "stage1_delivery_offers", case.intake._load("alice", fixture["ref"])
            )
            case.runner.assert_not_called()

    def test_partial_records_are_not_a_recovery_offer(self):
        with saved_stage1_case() as (case, fixture):
            service = ProjectRecordsPrepareService(case.producer)
            with (
                patch(
                    "research_workspace_native.project_stage1_records.os.link",
                    side_effect=OSError("authored partial write"),
                ),
                self.assertRaises(SessionApiError),
            ):
                service.prepare("alice-token", fixture["ref"], body(case, fixture))
            case.reopen()
            service = ProjectRecordsPrepareService(case.producer)
            prior = actions(case, fixture)
            self.assertEqual(
                service.recovery.read("alice-token", fixture["ref"])["status"],
                "recovery-unavailable",
            )
            self.assertEqual(
                service.recovery.read("alice-token", fixture["ref"])["offers"], []
            )
            self.assertEqual(actions(case, fixture), prior)
            case.runner.assert_not_called()

    def test_real_http_get_and_repeated_post_have_no_producer_or_core_dispatch(self):
        token = "authored-loopback-credential-at-least-32-characters"

        def authenticate(value):
            return "local-viewer" if value in (token, "alice-token") else None

        with (
            patch("test_project_stage1_delivery.authenticate", authenticate),
            saved_stage1_case() as (case, fixture),
        ):
            service = interrupted(case, fixture)
            host = ProjectHost(
                projects=case.intake,
                credential=token,
                stage1=case.stage1,
                files={},
                views=[],
                port=0,
            )
            host.project_records_prepare = (
                service  # trusted test-only object, never HTTP JSON
            )
            worker = threading.Thread(target=host.serve_forever, daemon=True)
            worker.start()

            def request(path, data=None):
                client = http.client.HTTPConnection(
                    "127.0.0.1", host.server_port, timeout=30
                )
                headers = {"Authorization": "Bearer " + token}
                if data is not None:
                    headers.update(
                        Origin=host.expected_origin,
                        **{"Content-Type": "application/json"},
                    )
                try:
                    client.request(
                        "GET" if data is None else "POST",
                        path,
                        None if data is None else json.dumps(data),
                        headers,
                    )
                    response = client.getresponse()
                    return response.status, json.loads(response.read())
                finally:
                    client.close()

            try:
                base = "/api/projects/" + fixture["ref"]
                status, overview = request(base + "/overview")
                self.assertEqual(status, 200, overview)
                self.assertEqual(
                    len(overview["stage1"]["saved_records_recovery"]["offers"]), 1
                )
                recovery = recovery_body(case, fixture, service)
                events = fixture["ledger"].events()
                with patch.object(
                    case.producer,
                    "produce_records",
                    side_effect=AssertionError("HTTP produced"),
                ) as produce:
                    status, result = request(
                        base + "/stage1/recover-delivery", recovery
                    )
                    self.assertEqual(status, 200, result)
                    self.assertEqual(result["status"], "saved")
                    after = actions(case, fixture)
                    status, replay = request(
                        base + "/stage1/recover-delivery", recovery
                    )
                    self.assertEqual(status, 200, replay)
                    self.assertTrue(replay["replayed"])
                    status, bad = request(
                        base + "/stage1/recover-delivery",
                        {**recovery, "records_sha256": "0" * 64},
                    )
                    self.assertEqual(status, 409, bad)
                    status, overview = request(base + "/overview")
                    self.assertEqual(status, 200, overview)
                    self.assertEqual(
                        overview["stage1"]["saved_records_recovery"]["offers"], []
                    )
                    descriptor = overview["stage1"]["screening_library"]
                    status, library = request(
                        base
                        + "/stage1/screening/"
                        + str(descriptor["input_version"])
                        + "/"
                        + descriptor["ledger_state_sha256"]
                        + "/0"
                    )
                    self.assertEqual(status, 200, library)
                    self.assertEqual(library["total"], 2)
                    self.assertEqual(len(library["rows"]), 2)
                    self.assertEqual(actions(case, fixture), after)
                    produce.assert_not_called()
                self.assertEqual(fixture["ledger"].events(), events)
                case.runner.assert_not_called()
            finally:
                host.shutdown()
                host.server_close()
                worker.join(3)
                self.assertFalse(worker.is_alive())


if __name__ == "__main__":
    unittest.main()
