"""Neutral fake-child setup; process import is delayed until explicit factory use."""

import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
import time
import threading

sys.path.insert(0, str(Path(__file__).parents[1] / "cli"))
from research_workspace_native.frame_journal import FrameJournal


class OwnedProcessCase(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name).resolve()
        self.cwd = self.root / "fake-only"
        self.cwd.mkdir()
        self.child = self.cwd / "app-server"
        self.child.write_text(
            "import sys\nprint('synthetic-stderr',file=sys.stderr,flush=True)\nfor line in sys.stdin.buffer:\n sys.stdout.buffer.write(b'synthetic:'+line);sys.stdout.buffer.flush()\n",
            encoding="utf8",
        )
        self.path = self.root / "synthetic-process.sqlite"
        self.store = FrameJournal(self.path)
        self.addCleanup(self.store.close)
        self.store.bind_project("alpha", "a" * 64)
        self.owner = self.store.acquire_owner("alpha", "synthetic-process")
        executable = Path(sys.executable).resolve()
        self.payload = dict(
            executable=str(executable),
            executable_sha256=hashlib.sha256(executable.read_bytes()).hexdigest(),
            cwd=str(self.cwd),
            input_version="b" * 64,
        )
        self.store.record_intent(
            "alpha",
            self.owner,
            "spawn",
            "app-server/spawn",
            self.payload,
            self.state()["revision"],
        )
        self.owned = []
        self.addCleanup(self.cleanup)

    def state(self):
        return self.store.snapshot("alpha")

    def cleanup(self):
        for channel in self.owned:
            channel.close()
            channel.reap()

    def channel(self, **changes):
        from research_workspace_native.process_channel import OwnedProcessChannel

        options = dict(
            store=self.store,
            project_id="alpha",
            owner=self.owner,
            connection_id="synthetic-epoch",
            index_sha256="a" * 64,
            input_version="b" * 64,
            intent_key="spawn",
            verify_binding=lambda: True,
            admit_spawn=lambda offer: True,
            lifetime=10,
        )
        options.update(changes)
        channel = OwnedProcessChannel(**options)
        self.owned.append(channel)
        return channel

    def channel_with_controlled_lease_expiry(self):
        """Let construction finish, then expire the actual lease without UI I/O.

        Only this channel's lease wait is controlled. Startup deadlines, source
        checks, physical fake-child cleanup and SQLite observations stay real.
        """
        from types import SimpleNamespace
        from unittest.mock import patch
        import research_workspace_native.process_channel as module

        entered, release = threading.Event(), threading.Event()
        operation_thread = threading.get_ident()
        observed_timeouts = []

        class ControlledLeaseEvent(threading.Event):
            def wait(self, timeout=None):
                if threading.get_ident() != operation_thread and not entered.is_set():
                    observed_timeouts.append(timeout)
                    entered.set()
                    release.wait(10)
                    # The test has moved this channel's lease into the past.
                    # Run the real lease timeout branch and physical cleanup.
                    return super().wait(0)
                return super().wait(timeout)

        event = ControlledLeaseEvent()
        replacement = SimpleNamespace(
            RLock=threading.RLock,
            Lock=threading.Lock,
            Event=lambda: event,
            Thread=threading.Thread,
        )
        self.addCleanup(release.set)
        with patch.object(module, "threading", replacement):
            channel = self.channel(lifetime=30)
        self.assertTrue(entered.wait(5), "lease watcher did not register")
        self.assertEqual(len(observed_timeouts), 1)
        self.assertGreater(observed_timeouts[0], 0)
        self.assertLessEqual(observed_timeouts[0], 30)

        def expire():
            channel.deadline = time.monotonic() - 1
            release.set()

        return channel, expire

    def _assert_write_lock_and_expired_journal_wait_do_not_dispatch(self):
        from unittest.mock import patch

        channel = self.channel()
        with patch.object(
            channel.process.stdin, "write", wraps=channel.process.stdin.write
        ) as write:
            channel._writes.acquire()
            try:
                with self.assertRaises(TimeoutError):
                    channel.write(b"never", 0.05)
            finally:
                channel._writes.release()
            observe = channel._observe

            def delayed(event, **payload):
                if event == "write-intent":
                    time.sleep(0.1)
                return observe(event, **payload)

            with patch.object(channel, "_observe", side_effect=delayed):
                with self.assertRaises(TimeoutError):
                    channel.write(b"never", 0.05)
            write.assert_not_called()

    def _assert_zero_timeout_consumes_already_buffered_stdout(self):
        channel = self.channel()
        channel.write(b"ready\n", 1)
        until = time.monotonic() + 2
        while channel._stdout.empty() and time.monotonic() < until:
            time.sleep(0.01)
        self.assertFalse(channel._stdout.empty(), "fake stdout was not ready")
        # A zero-time read must not wait for another thread's journal ownership.
        # Reserve the reentrant journal lock before measuring that read contract.
        self.assertTrue(self.store._lock.acquire(timeout=2), "journal was not ready")
        try:
            self.assertEqual(channel.read(262144, 0), b"synthetic:ready\n")
        finally:
            self.store._lock.release()

    def _assert_real_fake_child_recording_bootstrap_and_same_transport_handoff(
        self, *, startup_delay=0
    ):
        from research_workspace_native.bootstrap import BootstrapSession
        from research_workspace_native.controller import InjectedSessionController

        self.child.write_text(
            f"import sys,json,time\ntime.sleep({startup_delay!r})\nfor line in sys.stdin.buffer:\n m=json.loads(line);method=m['method']\n if method=='initialized':continue\n p=m['params']\n r={{'userAgent':'synthetic-server'}} if method=='initialize' else {{'requiresOpenaiAuth':True,'account':{{'type':'apiKey'}}}} if method=='account/read' else {{'thread':{{'id':'synthetic-thread'}},'cwd':p['cwd'],'model':p['model'],'approvalPolicy':p['approvalPolicy'],'sandbox':{{'type':'readOnly','networkAccess':False}}}}\n print(json.dumps({{'id':m['id'],'result':r}}),flush=True)\n",
            encoding="utf8",
        )
        # This positive handoff checks identity and shared transport, not a
        # two-second performance bound on child startup and durable journal I/O.
        channel = self.channel(lifetime=30)
        self.store.record_intent(
            "alpha",
            self.owner,
            "new-session",
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
            intent_key="new-session",
            channel=channel,
            verify_binding=lambda: True,
            admit_lifecycle=lambda offer: True,
        )
        boot.open_thread(dict(name="synthetic-client", version="1"), timeout=10)
        controller = InjectedSessionController.adopt_ready(
            boot, admit_action=lambda action: False
        )
        self.assertIs(controller.transport, boot.transport)
        self.assertEqual(self.state()["thread_id"], "synthetic-thread")
        controller.close()
        self.assertTrue(channel.reap()["leader_reaped"])
