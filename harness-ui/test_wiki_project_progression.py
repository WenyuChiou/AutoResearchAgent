"""Exercise the PR5 Host coordinator with the real intake and fixed offline steps."""

# ruff: noqa: E402 -- the plugin and Wiki use repository-local imports.
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import tempfile
from threading import Event
import unittest

PLUGIN = Path(__file__).resolve().parents[1] / "plugins" / "auto-research-agent"
sys.path[:0] = [str(PLUGIN / name) for name in ("cli", "tests")]

from research_workspace_native.http import token_authenticator
from research_workspace_native.project_host import ProjectHost
from research_workspace_native.project_intake import ProjectIntakeService
from research_workspace_native.session_api import SessionApiError
from stage1_deliverable.common import canonical, sha
from test_workspace_project_intake import compile_body, submit_body
from wiki_project_progression import STAGES, StageStep, WikiProjectProgression


TOKEN = "wiki-local-progression-fixture-token-00001"


class WikiProjectProgressionTests(unittest.TestCase):
    def setUp(self):
        path = self.enterContext(tempfile.TemporaryDirectory(prefix="pr5-"))
        self.root = Path(path).resolve()
        self.now = datetime(2026, 11, 26, tzinfo=timezone.utc)
        self.pins = {stage: sha(stage.encode()) for stage in STAGES}
        self.sources = {}
        self.connections = []
        self.grants = set()
        self.dispatched = []
        self.selectable = False
        self.during_submit = None
        self.during_grant = None
        self.reopen()
        self.ref = self.prepare("original")
        self.write_consent()

    def reopen(self):
        if hasattr(self, "host"):
            self.host.server_close()
            self.intake.close()
        self.intake = ProjectIntakeService(
            self.root / "p", authenticate=token_authenticator({TOKEN: "local-viewer"})
        )
        self.addCleanup(self.intake.close)
        self.host = ProjectHost(
            projects=self.intake, credential=TOKEN, files={}, views=[], port=0
        )
        self.addCleanup(self.host.server_close)
        # Deliberately reverse the dictionary. A Stage 3 adapter cannot jump the queue.
        self.service = WikiProjectProgression(
            self.host,
            read_consent=lambda _, ref: self.sources.get(ref),
            steps={stage: self.fixed_step(stage) for stage in reversed(STAGES)},
            clock=lambda: self.now,
        )

    def prepare(self, key):
        ref = self.intake.create(
            TOKEN, {"key": key, "topic": "Aircraft fault diagnosis with sensor drift"}
        )["project_ref"]
        view = self.intake.read(TOKEN, ref)
        self.intake.submit(TOKEN, ref, submit_body(view))
        view = self.intake.read(TOKEN, ref)
        self.intake.compile(TOKEN, ref, compile_body(view))
        self.assertTrue(self.intake.read(TOKEN, ref)["stage1_intake_ready"])
        return ref

    def result_path(self, ref, stage):
        return self.root / (ref + "-" + stage + ".json")

    def fixed_step(self, stage):
        def predecessor(token, binding):
            ref = binding["project_ref"]
            project = self.intake.read(token, ref)
            if stage == "stage1":
                return (
                    sha(canonical(project["plan"]))
                    if project["stage1_intake_ready"]
                    else None
                )
            upstream = "stage1" if stage == "stage2" else "stage2"
            path = self.result_path(ref, upstream)
            if not path.is_file() or (stage == "stage3" and not self.selectable):
                return None
            raw = path.read_bytes()
            # Stage 3 fixture requires a separate fixed named-choice marker.
            return sha(raw if stage == "stage2" else b"fixed-choice:" + raw)

        def result_bytes(binding, upstream, key):
            return canonical(
                {"binding": binding, "upstream": upstream, "key": key, "stage": stage}
            )

        def read_result(_, binding, upstream, key):
            path = self.result_path(binding["project_ref"], stage)
            if path.is_file() and path.read_bytes() == result_bytes(
                binding, upstream, key
            ):
                return sha(path.read_bytes())
            return None

        def connect(_, binding, upstream, consent_pin):
            record = (stage, binding["project_ref"], upstream, consent_pin)
            if record not in self.connections:
                self.connections.append(record)

        def spending_grant(_, binding, __, ___):
            if self.during_grant is not None:
                self.during_grant()
            if stage in self.grants:
                # Fixed, custody-checked test authority, separate from consent.
                return (stage, binding["project_ref"], binding["input_version"])
            return None

        def submit(_, binding, upstream, key, grant):
            self.assertIn(stage, self.grants)
            ref = binding["project_ref"]
            self.assertEqual(grant, (stage, ref, binding["input_version"]))
            self.dispatched.append((stage, ref, key))
            if self.during_submit is not None:
                self.during_submit()
            self.result_path(ref, stage).write_bytes(
                result_bytes(binding, upstream, key)
            )

        return StageStep(
            self.pins[stage], predecessor, read_result, connect, spending_grant, submit
        )

    def write_consent(self, **changes):
        project = self.intake.read(TOKEN, self.ref)
        value = {
            "kind": "ProjectStageProgressionConsent",
            "schema_version": "1.0.0",
            "confirmed": True,
            "expires_at": (self.now + timedelta(minutes=3)).isoformat(),
            **{
                key: project[key]
                for key in (
                    "project_ref",
                    "project_id",
                    "input_version",
                    "brief_sha256",
                )
            },
            "settings_sha256": sha(canonical(project["settings"])),
            "stages": {
                stage: {"profile_sha256": self.pins[stage], "max_dispatches": 1}
                for stage in STAGES
            },
            **changes,
        }
        raw = canonical(value)
        self.sources[self.ref] = (raw, sha(raw))

    def counts(self):
        actions = self.intake.history(TOKEN, self.ref)["actions"]
        events = self.intake.db.execute(
            "SELECT COUNT(*) FROM intake_events WHERE project=?", (self.ref,)
        ).fetchone()[0]
        return (len(actions), events, len(self.dispatched))

    def assert_refused(self, code, operation=None):
        before = self.counts()
        with self.assertRaisesRegex(SessionApiError, "^" + code + "$"):
            if operation is None:
                self.service.advance(TOKEN, self.ref)
            else:
                operation()
        self.assertEqual(self.counts(), before)
        self.assertEqual(self.connections, [])

    def test_read_is_inert_and_consent_cannot_spend(self):
        before = self.counts()
        row = self.service.read(TOKEN, self.ref)
        self.assertEqual(row["status"], "not-started")
        self.assertFalse(row["execution_authorized"])
        self.assertEqual(self.connections, [])
        for _ in range(2):
            row = self.service.advance(TOKEN, self.ref)
            self.assertEqual(row["status"], "waiting-for-spending-grant")
            self.assertEqual(row["stage"], "stage1")
            self.assertFalse(row["execution_authorized"])
        self.assertEqual(len(self.connections), 1)
        self.assertEqual(self.counts(), before)

    def test_no_consent_or_expired_consent_cannot_even_connect(self):
        self.sources.clear()
        self.assert_refused("stage-progression-consent-required")
        self.write_consent(expires_at=self.now.isoformat())
        self.assert_refused("stage-progression-consent-expired")

    def test_project_without_current_compiled_scope_stays_read_only(self):
        created = self.intake.create(
            TOKEN, {"key": "not-confirmed", "topic": "Scope pending"}
        )
        ref = created["project_ref"]
        before = self.intake.history(TOKEN, ref)
        for operation in (self.service.read, self.service.advance):
            self.assertEqual(
                operation(TOKEN, ref)["status"], "waiting-for-project-scope"
            )
        self.assertEqual(self.intake.history(TOKEN, ref), before)
        self.assertEqual(self.connections, [])
        self.assertEqual(self.dispatched, [])

    def test_wrong_binding_including_bool_and_same_topic_project(self):
        other = self.prepare("other")
        for changed in (
            {"project_ref": other},
            {"project_id": other},
            {"input_version": True},
            {"input_version": 2},
            {"brief_sha256": "a" * 64},
            {"settings_sha256": "a" * 64},
        ):
            with self.subTest(changed=changed):
                self.write_consent(**changed)
                self.assert_refused("stage-progression-consent-binding-differs")
        self.assert_refused(
            "unauthorized", lambda: self.service.advance("wrong", self.ref)
        )

    def test_tampered_duplicate_malformed_and_uncovered_consent(self):
        raw, pin = self.sources[self.ref]
        self.sources[self.ref] = (raw + b" ", pin)
        self.assert_refused("stage-progression-consent-digest-differs")
        duplicate = b'{"confirmed":true,"confirmed":true,' + raw[1:]
        self.sources[self.ref] = (duplicate, sha(duplicate))
        self.assert_refused("stage-progression-consent-invalid")
        self.write_consent(expires_at="2026-11-26T00:00:00")
        self.assert_refused("stage-progression-consent-invalid")
        for stages in (
            {},
            {"stage1": {"profile_sha256": "a" * 64, "max_dispatches": 1}},
            {"stage1": {"profile_sha256": self.pins["stage1"], "max_dispatches": True}},
            {"stage1": {"profile_sha256": self.pins["stage1"], "max_dispatches": 2}},
        ):
            with self.subTest(stages=stages):
                self.write_consent(stages=stages)
                self.assert_refused("stage-progression-consent-stage-not-covered")

    def test_fixed_two_boundaries_and_cold_reopen_zero_growth_after_expiry(self):
        before = self.counts()
        self.grants.update(STAGES)
        first = self.service.advance(TOKEN, self.ref)
        self.assertEqual(
            (first["status"], first["stage"]), ("waiting-for-predecessor", "stage3")
        )
        self.assertEqual(list(first["stages"]), ["stage1", "stage2"])
        after_s2 = self.counts()
        self.assertEqual(after_s2, (before[0] + 2, before[1] + 4, 2))
        self.assertEqual(self.service.advance(TOKEN, self.ref), first)
        self.assertEqual(self.counts(), after_s2)
        self.selectable = True
        final = self.service.advance(TOKEN, self.ref)
        self.assertEqual(final["status"], "saved")
        self.assertEqual(list(final["stages"]), list(STAGES))
        self.assertFalse(final["execution_authorized"])
        saved = self.counts()
        self.assertEqual(saved, (before[0] + 3, before[1] + 6, 3))
        self.now += timedelta(days=1)
        self.grants.clear()
        self.reopen()
        self.assertEqual(self.service.read(TOKEN, self.ref), final)
        self.assertEqual(self.service.advance(TOKEN, self.ref), final)
        self.assertEqual(self.counts(), saved)
        print(
            f"PR5 ledger actions/events/fixed jobs {before} -> {after_s2} -> {saved} -> {self.counts()}"
        )

    def test_parallel_advances_share_one_attempt(self):
        in_worker, finish = Event(), Event()
        self.grants.add("stage1")

        def block():
            in_worker.set()
            self.assertTrue(finish.wait(10))

        self.during_submit = block
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(self.service.advance, TOKEN, self.ref)
            try:
                self.assertTrue(in_worker.wait(10))
                second = pool.submit(self.service.advance, TOKEN, self.ref)
                self.assertEqual(second.result(timeout=5)["status"], "in-progress")
            finally:
                finish.set()
            self.assertEqual(
                first.result(timeout=5)["status"], "waiting-for-spending-grant"
            )
        self.assertEqual(len(self.dispatched), 1)

    def test_unknown_intent_is_visible_after_restart_and_reissue_never_resends(self):
        self.grants.add("stage1")

        def crash():
            raise RuntimeError("fixed handoff response lost")

        self.during_submit = crash
        with self.assertRaisesRegex(RuntimeError, "fixed handoff response lost"):
            self.service.advance(TOKEN, self.ref)
        before = self.counts()
        self.reopen()
        self.now += timedelta(days=1)
        self.write_consent()
        for operation in (self.service.read, self.service.advance):
            unknown = operation(TOKEN, self.ref)
            self.assertEqual(unknown["status"], "execution-unknown")
            self.assertEqual(unknown["key"], self.dispatched[0][2])
        self.assertEqual(self.counts(), before)

    def test_consent_rechecked_after_grant_before_adapter_dispatch(self):
        self.grants.add("stage1")

        def expire():
            self.now += timedelta(days=1)

        self.during_grant = expire
        before = self.counts()
        with self.assertRaisesRegex(
            SessionApiError, "stage-progression-consent-expired"
        ):
            self.service.advance(TOKEN, self.ref)
        self.assertEqual(self.counts(), before)
        self.assertEqual(self.service.read(TOKEN, self.ref)["status"], "not-started")


if __name__ == "__main__":
    unittest.main()
