"""Synthetic broker regressions; no native process or model is started."""

import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cli"))
from research_workspace_native.stage_run_service import StageRunService
from research_workspace_native.session_api import SessionApiError
from stage1_deliverable.common import sha


class Pipeline:
    def __init__(self, max_calls=8):
        self.position, self.pending = 0, False
        self.history = []
        self.source_sha, self.max_calls = "b" * 64, max_calls

    def next_task(self):
        return dict(
            task_sha256=str(self.position).zfill(64),
            prompt="bounded text",
            phase="source-review",
            schema=None,
            unit_key=f"unit-{self.position}",
        )

    def begin_task(self, digest):
        if digest != self.next_task()["task_sha256"] or self.pending:
            raise ValueError("stale task")
        self.pending = True

    def accept(self, digest, receipt):
        self.pending = False
        self.position += 1
        self.history.append(dict(status="accepted"))
        return self.view()

    def view(self):
        return dict(status="ready", history=self.history)


class Model:
    def __init__(self, service, *, fail=False, barrier=None):
        self.service, self.fail, self.barrier = service, fail, barrier
        self.writes = 0

    def run(self, key, prompt, deadline):
        event = dict(
            unit_key=key,
            prompt_sha256=sha(prompt.encode()),
            source_sha256="b" * 64,
            permit_sha256=self.service.permit_sha,
        )
        self.service.admit(dict(event, phase="reserve"))
        self.service.admit(dict(event, phase="action"))
        self.writes += 1
        if self.barrier is not None:
            self.barrier.wait(5)
        if self.fail:
            raise TimeoutError("synthetic response loss")
        return {"key": key}

    def verify_receipt(self, receipt, **_):
        return dict(final_text="Synthetic completed content")


class StageRunServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.permit = self.root / "permit.json"
        self.value = dict(
            kind="NativeStagePilotPermit",
            schema_version="1.0.0",
            project_id="test-pilot",
            source_sha256="b" * 64,
            case_sha256="c" * 64,
            output_root=str(self.root / "budget"),
            model="test-only",
            max_calls=8,
            max_seconds=900,
            execution_scope="repository-saved-content-only",
            external_search=False,
            frozen_subjects=False,
            permission_id="explicit-test-only",
        )
        self.instances = []

    def tearDown(self):
        for service in self.instances:
            service.close()
        self.temp.cleanup()

    def service(self, **changes):
        value = dict(self.value, **changes)
        raw = json.dumps(value).encode()
        if not self.permit.exists():
            self.permit.write_bytes(raw)
        value = json.loads(self.permit.read_bytes())
        service = StageRunService(
            self.permit,
            sha(self.permit.read_bytes()),
            pipeline=Pipeline(value["max_calls"]),
            authenticate=lambda token: "local-viewer" if token == "secret" else None,
        )
        self.instances.append(service)
        return service

    def action(self, service, key):
        view = service.view("secret", service.ref)
        return dict(
            key=key,
            revision=view["revision"],
            task_sha256=view["next_task"]["task_sha256"],
            confirmed=True,
        )

    def test_two_tabs_same_key_and_refresh_have_one_write(self):
        service = self.service()
        model = Model(service)
        service.attach_model(model)
        body = self.action(service, "same-key")
        service.execute("secret", service.ref, body)
        service.wait()
        old = service.execute("secret", service.ref, body)
        for _ in range(3):
            view = service.view("secret", service.ref)
        self.assertEqual((model.writes, view["budget"]["reserved"]), (1, 1))
        self.assertEqual(old["status"], "validated")
        self.assertNotIn("prompt", view["jobs"][0]["task"])
        with self.assertRaises(SessionApiError):
            service.execute("secret", service.ref, dict(body, task_sha256="d" * 64))

    def test_halved_budget_cannot_be_reset_by_reopen(self):
        service = self.service(max_calls=2)
        model = Model(service)
        service.attach_model(model)
        for key in ("first", "second"):
            service.execute("secret", service.ref, self.action(service, key))
            service.wait()
        with self.assertRaises(SessionApiError):
            service.execute("secret", service.ref, self.action(service, "third"))
        service.close()
        reopened = self.service()
        self.assertEqual(reopened.view("secret", reopened.ref)["budget"]["reserved"], 2)
        self.assertFalse(reopened.view("secret", reopened.ref)["ready"])

    def test_expired_http_admission_and_wrong_project_dispatch_nothing(self):
        service = self.service()
        model = Model(service)
        service.attach_model(model)
        body = self.action(service, "no-dispatch")
        for token, ref in (("wrong", service.ref), ("secret", "other-project")):
            with self.assertRaises(SessionApiError):
                service.execute(token, ref, body)
        with self.assertRaises(SessionApiError):
            service.execute("secret", service.ref, body, pre_dispatch=lambda: False)
        self.assertEqual((model.writes, service._row()["calls"]), (0, 0))

    def test_unknown_result_blocks_new_key_without_repeat(self):
        service = self.service()
        model = Model(service, fail=True)
        service.attach_model(model)
        body = self.action(service, "lost-response")
        service.execute("secret", service.ref, body)
        service.wait()
        self.assertEqual(
            service.execute("secret", service.ref, body)["status"], "failed-or-unknown"
        )
        with self.assertRaises(SessionApiError):
            service.execute("secret", service.ref, self.action(service, "new-key"))
        self.assertEqual(model.writes, 1)

    def test_exclusive_owner_and_bound_permit(self):
        service = self.service()
        with self.assertRaises(Exception):
            self.service()
        self.permit.write_bytes(b"changed")
        with self.assertRaises(SessionApiError):
            service.execute("secret", service.ref, self.action(service, "changed"))

    def test_recover_intent_before_dispatch_is_unknown_and_no_model(self):
        service = self.service()
        with service.store._edit(
            service.pid, service.owner, None, "test-crash-intent", {}
        ) as state:
            state["stage_pilot"]["jobs"]["abandoned"] = {
                "status": "intent-recorded",
                "task": {},
            }
        service.close()
        reopened = self.service()
        view = reopened.view("secret", reopened.ref)
        self.assertEqual(view["jobs"][0]["status"], "execution-unknown")
        self.assertFalse(view["ready"])
        self.assertEqual(view["budget"]["reserved"], 0)

    def test_actual_elapsed_budget_blocks_later_phase(self):
        service = self.service(max_seconds=1)
        model = Model(service)
        service.attach_model(model)
        service.execute("secret", service.ref, self.action(service, "first"))
        service.wait()
        service._mono_deadline = 0
        self.assertFalse(service.view("secret", service.ref)["ready"])
        with self.assertRaises(SessionApiError):
            service.execute("secret", service.ref, self.action(service, "expired"))
        self.assertEqual(model.writes, 1)

    def test_running_worker_disables_other_tabs(self):
        service = self.service()
        release = threading.Event()
        model = Model(service, barrier=release)
        service.attach_model(model)
        body = self.action(service, "running")
        service.execute("secret", service.ref, body)
        self.assertFalse(service.view("secret", service.ref)["ready"])
        with self.assertRaises(SessionApiError):
            service.execute("secret", service.ref, dict(body, key="other-tab"))
        release.set()
        service.wait()


if __name__ == "__main__":
    unittest.main()
