"""Real fake child + SQLite/API ownership; never actual Codex or model calls."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import json
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / "cli"))
from native_process_channel_fixtures import OwnedProcessCase
from research_workspace_native.bootstrap import BootstrapSession
from research_workspace_native.controller import InjectedSessionController
from research_workspace_native.server_owner import SessionOwners
from research_workspace_native.session_api import SessionApi

SCRIPT = """import json,sys,time
def emit(m):
 print(json.dumps(m),flush=True)
for line in sys.stdin.buffer:
 m=json.loads(line)
 method=m.get('method')
 if method=='initialized':continue
 if method=='initialize':r={'userAgent':'synthetic-fake'}
 elif method=='account/read':r={'requiresOpenaiAuth':True,'account':{'type':'apiKey'}}
 elif method=='thread/start':
  p=m['params']
  r={'thread':{'id':'synthetic-thread'},'cwd':p['cwd'],'model':p['model'],'approvalPolicy':p['approvalPolicy'],'sandbox':{'type':'readOnly','networkAccess':False}}
 elif method is None:
  emit({'method':'serverRequest/resolved','params':{'threadId':'synthetic-thread','requestId':83}})
  emit({'method':'turn/completed','params':{'threadId':'synthetic-thread','turn':{'id':'synthetic-turn','status':'completed'}}})
  continue
 else:continue
 emit({'id':m['id'],'result':r})
 if method=='thread/start':
  emit({'id':83,'method':'item/tool/requestUserInput','params':{'threadId':'synthetic-thread','turnId':'synthetic-turn','itemId':'synthetic-item','questions':[{'id':'q','question':'Synthetic scope?'}]}})
"""


class OwnersTests(OwnedProcessCase):
    def setUp(self):
        super().setUp()
        self.child.write_text(SCRIPT, encoding="utf8")
        self.api = SessionApi(
            authenticate=lambda token: "principal" if token == "token" else None
        )
        self.registry = SessionOwners(api=self.api)
        self.addCleanup(self.registry.shutdown)
        self.source_ok = True
        # Ownership assertions do not impose a two-second child-startup bound.
        # Match the existing positive bootstrap fixture's bounded setup allowance.
        self.channel_raw = self.channel(lifetime=30)
        self.store.record_intent(
            "alpha",
            self.owner,
            "session",
            "thread/start",
            dict(
                cwd=str(self.cwd),
                model="synthetic-model",
                approvalPolicy="on-request",
                sandbox="read-only",
            ),
            self.state()["revision"],
        )
        boot = BootstrapSession(
            store=self.store,
            project_id="alpha",
            owner=self.owner,
            connection_id="synthetic-epoch",
            index_sha256="a" * 64,
            input_version="b" * 64,
            intent_key="session",
            channel=self.channel_raw,
            verify_binding=lambda: True,
            admit_lifecycle=lambda offer: True,
        )
        boot.open_thread(dict(name="synthetic-client", version="1"), timeout=10)
        self.controller = InjectedSessionController.adopt_ready(
            boot, admit_action=lambda action: True
        )
        self.options = dict(
            controller=self.controller,
            owned_channel=self.channel_raw,
            principals={"principal"},
            source_root=self.cwd,
            index_sha256="a" * 64,
            input_version="b" * 64,
            verify_source=lambda binding: self.source_ok,
            admit_attach=lambda binding: True,
        )

    def register(self):
        return self.registry.register("project-ref", **self.options)

    def wait(self, predicate, timeout=3):
        until = time.monotonic() + timeout
        while time.monotonic() < until:
            if predicate():
                return
            time.sleep(0.01)
        self.fail("synthetic predicate timed out")

    def question(self):
        view = self.api.view("token", "project-ref")
        return next((q for q in view["requests"] if q["status"] == "pending"), None)

    def body(self, question):
        return dict(
            key="ui:answer.1",
            revision=self.api.view("token", "project-ref")["revision"],
            index_sha256="a" * 64,
            input_version="b" * 64,
            request_ref=question["request_ref"],
            request_sha256=question["request_sha256"],
            result={"answers": {"q": {"answers": ["Synthetic scope confirmed"]}}},
        )

    def test_get_is_passive_explicit_single_pump_receives_question_and_answer(self):
        owner = self.register()
        binding = self.registry.bindings()
        self.assertEqual(
            binding,
            {
                "project-ref": dict(
                    project_id="alpha", index_sha256="a" * 64, input_version="b" * 64
                )
            },
        )
        binding["project-ref"]["project_id"] = "altered"
        self.assertEqual(self.registry.bindings()["project-ref"]["project_id"], "alpha")
        for _ in range(3):
            self.assertEqual(self.api.view("token", "project-ref")["requests"], [])
            self.assertFalse(owner.status()["started"])
        owner.start()
        with self.assertRaises(ValueError):
            owner.start()
        self.wait(lambda: self.question() is not None)
        question = self.question()
        body = self.body(question)
        with patch.object(
            self.channel_raw.process.stdin,
            "write",
            wraps=self.channel_raw.process.stdin.write,
        ) as writes:
            result = self.api.answer("token", "project-ref", body)
            self.assertEqual(result["status"], "dispatched")
            self.wait(
                lambda: (
                    self.api.view("token", "project-ref")["requests"][0]["status"]
                    == "request-resolved"
                )
            )
            before = writes.call_count
            self.assertEqual(before, 1)
            replay = self.api.answer("token", "project-ref", body)
            self.assertTrue(replay["replayed"])
            for _ in range(3):
                self.api.view("token", "project-ref")
                self.api.action("token", "project-ref", result["action_ref"])
            self.assertEqual(writes.call_count, before)

        def terminal_saved():
            status = owner.status()
            self.assertFalse(status["failure"], status)
            return (
                self.state()["turns"].get("synthetic-turn", {}).get("status")
                == "completed"
            )

        self.wait(terminal_saved)  # Request resolution and turn terminal are separate.
        self.assertIn("synthetic-turn", self.state()["turns"])
        self.assertTrue(owner.shutdown()["leader_reaped"])
        self.assertTrue(owner.status()["cleanup_observed"])

    def test_multiple_tabs_same_key_write_once_changed_payload_refused(self):
        owner = self.register()
        owner.start()
        self.wait(lambda: self.question() is not None)
        body = self.body(self.question())
        with (
            patch.object(
                self.channel_raw.process.stdin,
                "write",
                wraps=self.channel_raw.process.stdin.write,
            ) as writes,
            ThreadPoolExecutor(max_workers=2) as pool,
        ):
            results = list(
                pool.map(
                    lambda unused: self.api.answer("token", "project-ref", body), (1, 2)
                )
            )
            self.assertEqual(writes.call_count, 1)
            self.assertEqual(sum(row["replayed"] for row in results), 1)
            changed = dict(body, result={"answers": {"q": {"answers": ["Changed"]}}})
            with self.assertRaises(ValueError):
                self.api.answer("token", "project-ref", changed)
            self.assertEqual(writes.call_count, 1)

    def test_literal_attach_binding_and_cross_registry_duplicates_refused(self):
        with self.assertRaises(ValueError):
            self.registry.register(
                "project-ref", **dict(self.options, admit_attach=lambda binding: 1)
            )
        self.assertFalse(self.channel_raw.closed)
        with self.assertRaises(ValueError):
            self.registry.register(
                "project-ref", **dict(self.options, input_version="c" * 64)
            )
        owner = self.register()
        other = SessionOwners(api=SessionApi(authenticate=lambda token: "principal"))
        self.addCleanup(other.shutdown)
        with self.assertRaises(ValueError):
            other.register("same-title-other-case", **self.options)
        self.assertFalse(owner.status()["started"])
        self.assertEqual(other.bindings(), {})

    def test_source_drift_faults_retains_unknown_and_cannot_restart(self):
        owner = self.register()
        owner.start()
        self.wait(lambda: self.question() is not None)
        self.source_ok = False
        self.wait(lambda: owner.status()["cleanup_observed"])
        self.assertTrue(self.channel_raw.closed)
        self.assertIn("pump-failed", owner.status()["failure"])
        self.assertEqual(
            next(iter(self.state()["requests"].values()))["status"], "execution-unknown"
        )
        with self.assertRaises(ValueError):
            owner.start()
        self.assertTrue(owner.shutdown()["leader_reaped"])

    def test_shutdown_no_restart_and_history_survives_sqlite_reopen(self):
        owner = self.register()
        owner.start()
        self.wait(lambda: self.question() is not None)
        receipt = self.registry.shutdown()
        self.assertTrue(receipt["project-ref"]["leader_reaped"])
        self.assertEqual(self.state()["session_service"]["status"], "stopped")
        with self.assertRaises(ValueError):
            self.registry.register("another-ref", **self.options)
        self.store.close()
        from research_workspace_native.frame_journal import FrameJournal

        reopened = FrameJournal(self.path)
        self.addCleanup(reopened.close)
        state = reopened.snapshot("alpha")
        self.assertEqual(state["session_service"]["status"], "stopped")
        self.assertEqual(
            next(iter(state["requests"].values()))["status"], "execution-unknown"
        )
        self.assertTrue(state["protocol"]["frame_seq"] > 0)

    def test_shutdown_physical_cleanup_precedes_independent_sqlite_lock(self):
        owner = self.register()
        external = sqlite3.connect(self.path, timeout=1, isolation_level=None)
        self.addCleanup(external.close)
        external.execute("BEGIN IMMEDIATE")
        try:
            with self.assertRaises(TimeoutError):
                owner.shutdown(0.1)
            self.wait(lambda: self.channel_raw.process.poll() is not None, timeout=2)
            self.assertFalse(owner.status()["cleanup_observed"])
        finally:
            external.rollback()
        self.assertTrue(owner.shutdown(3)["leader_reaped"])

    def test_failed_cleanup_does_not_claim_success_or_release_slot(self):
        owner = self.register()
        with patch.object(
            self.channel_raw,
            "reap",
            return_value=dict(leader_reaped=False, errors=["SyntheticCleanupFailure"]),
        ):
            with self.assertRaises(ValueError):
                owner.shutdown()
        self.assertIn("cleanup-unobserved", owner.status()["failure"])
        self.assertFalse(owner.status()["cleanup_observed"])
        # Register replacement cannot acquire a slot even if it uses a second API.
        other = SessionOwners(api=SessionApi(authenticate=lambda token: "principal"))
        self.addCleanup(other.shutdown)
        with self.assertRaises(ValueError):
            other.register("replacement", **self.options)
        # Cleanup fixture still physically reaps the fake child; registry failure stays saved.
        self.registry._owners.clear()

    def test_callbacks_cannot_replace_the_owned_channel_before_transfer(self):
        def attach(binding):
            self.controller.channel.channel = object()
            return True

        original = self.controller.channel.channel
        try:
            with self.assertRaises(ValueError):
                self.registry.register(
                    "project-ref", **dict(self.options, admit_attach=attach)
                )
            self.assertFalse(self.channel_raw.closed)
            self.assertEqual(self.registry.bindings(), {})
        finally:
            self.controller.channel.channel = original

    def test_pump_thread_start_failure_closes_and_cannot_restart(self):
        owner = self.register()
        original = threading.Thread.start

        def start(thread):
            if thread.name == "workspace-session-pump":
                raise RuntimeError("synthetic-thread-start-failure")
            return original(thread)

        with patch.object(threading.Thread, "start", start):
            with self.assertRaises(RuntimeError):
                owner.start()
            self.assertFalse(owner.status()["running"])
            self.assertTrue(owner.shutdown()["leader_reaped"])
        with self.assertRaises(ValueError):
            owner.start()

    def test_shutdown_waits_pending_registration_and_never_publishes_after_close(self):
        entered, release = threading.Event(), threading.Event()
        errors = []

        def verify(binding):
            entered.set()
            release.wait(3)
            return True

        def register():
            try:
                self.registry.register(
                    "project-ref", **dict(self.options, verify_source=verify)
                )
            except BaseException as error:
                errors.append(type(error).__name__)

        worker = threading.Thread(target=register)
        worker.start()
        self.assertTrue(entered.wait(1))
        try:
            with self.assertRaises(ValueError):
                self.registry.shutdown(0.1)
            self.wait(lambda: self.channel_raw.process.poll() is not None, timeout=2)
        finally:
            release.set()
            worker.join(3)
        self.assertFalse(worker.is_alive())
        self.assertEqual(len(errors), 1)
        self.assertEqual(self.registry.bindings(), {})
        self.assertEqual(self.api._projects, {})
        self.assertEqual(self.registry.shutdown(), {})

    def test_shutdown_while_store_lock_held_starts_physical_cleanup(self):
        owner = self.register()
        locked, release = threading.Event(), threading.Event()

        def holder():
            with self.store._lock:
                locked.set()
                release.wait(3)

        worker = threading.Thread(target=holder)
        worker.start()
        self.assertTrue(locked.wait(1))
        try:
            with self.assertRaises(TimeoutError):
                owner.shutdown(0.1)
            self.wait(lambda: self.channel_raw.process.poll() is not None, timeout=2)
        finally:
            release.set()
            worker.join(3)
        self.assertTrue(owner.shutdown(3)["leader_reaped"])


class OwnerStartupTests(unittest.TestCase):
    def run_owner_case(self, method, script, configure=None):
        result = unittest.TestResult()
        case = OwnersTests(method)
        if configure is not None:
            configure(case)
        with patch.dict(case.setUp.__globals__, SCRIPT=script):
            case.run(result)
        self.assertEqual(result.testsRun, 1)
        self.assertEqual(result.errors, [])
        self.assertEqual(result.failures, [])
        self.assertEqual(result.skipped, [])

    def test_slow_fake_child_preserves_attach_refusals(self):
        self.run_owner_case(
            "test_literal_attach_binding_and_cross_registry_duplicates_refused",
            "import time\ntime.sleep(2.25)\n" + SCRIPT,
        )

    def test_resolved_request_waits_for_independent_turn_terminal(self):
        terminal = "  emit({'method':'turn/completed'"
        self.assertEqual(SCRIPT.count(terminal), 1)
        repository = Path(__file__).resolve().parents[3]
        with tempfile.TemporaryDirectory(prefix="owner-terminal-gate-") as directory:
            gate = Path(directory, "release-terminal")
            self.assertFalse(gate.parent.resolve().is_relative_to(repository))
            gated = SCRIPT.replace("import json,sys,time", "import json,os,sys,time", 1)
            gate_wait = (
                f"  while not os.path.exists({json.dumps(str(gate))}):\n"
                "   time.sleep(.01)\n"
            )
            gated = gated.replace(terminal, gate_wait + terminal, 1)
            self.assertNotEqual(gated, SCRIPT)
            phases = []
            answer_barriers = []
            expected_phases = ["question", "request-resolution", "terminal"]

            def configure(case):
                original_set_up = case.setUp
                original_wait = case.wait
                original_tear_down = case.tearDown

                def request_resolved():
                    return any(
                        row["status"] == "request-resolved"
                        for row in case.state()["requests"].values()
                    )

                def set_up():
                    original_set_up()
                    original_answer = case.api.answer

                    def answer(*args, **kwargs):
                        result = original_answer(*args, **kwargs)
                        if not answer_barriers:
                            original_wait(request_resolved)
                            state = case.state()
                            self.assertNotIn("synthetic-turn", state["turns"])
                            self.assertFalse(gate.exists())
                            answer_barriers.append("resolved-before-second-wait")
                        return result

                    case.api.answer = answer

                def wait(predicate, timeout=3):
                    self.assertLess(len(phases), len(expected_phases))
                    phase = expected_phases[len(phases)]
                    phases.append(phase)
                    state = case.state()
                    if phase in {"request-resolution", "terminal"}:
                        self.assertTrue(request_resolved())
                        self.assertNotIn("synthetic-turn", state["turns"])
                        self.assertFalse(gate.exists())
                    if phase == "terminal":
                        gate.touch()
                    original_wait(predicate, timeout)
                    if phase == "request-resolution":
                        self.assertFalse(gate.exists())
                        self.assertNotIn("synthetic-turn", case.state()["turns"])
                    elif phase == "terminal":
                        self.assertEqual(
                            case.state()["turns"]["synthetic-turn"]["status"],
                            "completed",
                        )

                def tear_down():
                    gate.touch(exist_ok=True)
                    original_tear_down()

                case.setUp = set_up
                case.wait = wait
                case.tearDown = tear_down

            self.run_owner_case(
                "test_get_is_passive_explicit_single_pump_receives_question_and_answer",
                gated,
                configure,
            )
            self.assertEqual(answer_barriers, ["resolved-before-second-wait"])
            self.assertEqual(phases, expected_phases)


if __name__ == "__main__":
    unittest.main()
