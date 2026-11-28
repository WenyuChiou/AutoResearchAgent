"""One request replays one unchanged saved ledger once; nothing outlives it."""

# ruff: noqa: E402 -- exercise the CLI package from the tests directory.
from contextlib import ExitStack
import os
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / "cli")]
from research_workspace_native import planned_queries, project_stage1
from stage1_ledger import validation
from stage1_retrieval import verification_clock


class Replay:
    """Counting stand-in for the real replay (reads nothing)."""

    def __init__(self, result=None, error=None, during=None):
        self.calls = 0
        self.result = result or {"valid": True, "state_sha256": "s" * 64}
        self.error, self.during = error, during

    def __call__(self, root, *, verify_runtime=True):
        self.calls += 1
        if self.during is not None:
            self.during()
        if self.error is not None:
            raise self.error
        return dict(self.result, nested={"counts": [1, 2]})


class LedgerReplayScopeTests(unittest.TestCase):
    def setUp(self):
        raw = tempfile.TemporaryDirectory()
        self.addCleanup(raw.cleanup)
        self.base = Path(raw.name)
        self.root = self.base / "ledger"
        (self.root / "artifacts").mkdir(parents=True)
        self.manifest = b'{"manifest": true}'
        (self.root / "run_manifest.json").write_bytes(self.manifest)
        (self.root / "stage_events.jsonl").write_bytes(b'{"e": 1}\n')
        (self.root / "artifacts" / "a.json").write_bytes(b"{}")

    def patched(self, replay):
        stack = ExitStack()
        # Patch every name a read path may call, so a path that bypasses the
        # shared helper is still counted.
        for module in (validation, project_stage1, planned_queries):
            stack.enter_context(mock.patch.object(module, "validate_run", replay))
        ledger = SimpleNamespace(
            root=self.root, pending=lambda: [], events=lambda: [], event=None
        )
        stack.enter_context(
            mock.patch.object(project_stage1, "CoverageLedger", lambda path: ledger)
        )
        stack.enter_context(
            mock.patch.object(planned_queries, "CoverageLedger", lambda path: ledger)
        )
        stack.enter_context(
            mock.patch.object(
                planned_queries,
                "inspect_registration",
                lambda *a, **k: ({"ledger_root": str(self.root)}, None, None, None),
            )
        )
        stack.enter_context(
            mock.patch.object(planned_queries, "tree_sha", lambda root: "t" * 64)
        )
        return stack

    def stage1_read(self):
        """ProjectStage1Service._ledger: overview, delivery and coverage reads."""
        binding = {name: name + "-value" for name in project_stage1.BINDING_FIELDS}
        binding["settings"] = {"authored": "settings"}
        run = {
            "binding": project_stage1._basis(binding),
            "path": "ledger",
            "manifest_sha256": project_stage1.sha(self.manifest),
        }
        state = {
            "stage1_active": "r1",
            "stage1_runs": {"r1": run},
            "project_ref": "project-x",
        }
        service = SimpleNamespace(
            intake=SimpleNamespace(_path=lambda ref, rel: self.base / rel)
        )
        return project_stage1.ProjectStage1Service._ledger(service, state, binding)

    def query_read(self):
        """PlannedQueryService._saved_frontier: reading readiness, saved frontier."""
        owner = SimpleNamespace(
            _check_storage=lambda: None, _saved_owner=lambda p, saved: None
        )
        saved = {"intents": {}, "query_ledger_sha256": "t" * 64}
        return planned_queries.PlannedQueryService._saved_frontier(
            owner, "project-x", {"item": {}}, saved
        )

    def scoped(self):
        return validation.validate_run_scoped(self.root)

    def test_one_request_replays_the_ledger_once_across_read_paths(self):
        replay = Replay()
        with (
            self.patched(replay),
            verification_clock.metering(verification_clock.Meter()) as meter,
        ):
            self.stage1_read()
            self.query_read()
            self.stage1_read()
            passes = meter.snapshot()["passes"]
        self.assertEqual(replay.calls, 1)
        self.assertEqual(passes, 1)  # a reused report is not another pass

    def test_two_requests_do_not_share_a_replay(self):
        replay = Replay()
        with self.patched(replay):
            for _ in range(2):
                with verification_clock.metering(verification_clock.Meter()):
                    self.stage1_read()
                    self.stage1_read()
        self.assertEqual(replay.calls, 2)

    def test_no_active_meter_never_reuses(self):
        replay = Replay()
        with self.patched(replay):
            self.stage1_read()
            self.query_read()
            self.stage1_read()
        self.assertEqual(replay.calls, 3)
        self.assertIsNone(verification_clock.scope_store("x"))

    def test_any_ledger_change_inside_a_request_replays_again(self):
        events = self.root / "stage_events.jsonl"

        def append():
            with events.open("ab") as stream:
                stream.write(b'{"e": 2}\n')

        def touch():
            info = events.stat()
            os.utime(events, ns=(info.st_atime_ns, info.st_mtime_ns + 10**9))

        def manifest():
            (self.root / "run_manifest.json").write_bytes(b'{"manifest": 2}')

        def same_size_rewrite():
            path = self.root / "artifacts" / "a.json"
            info = path.stat()
            path.write_bytes(b"[]")
            os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns + 10**9))

        def added():
            (self.root / "artifacts" / "b.json").write_bytes(b"{}")

        for change in (append, touch, manifest, same_size_rewrite, added):
            with self.subTest(change=change.__name__):
                replay = Replay()
                with (
                    self.patched(replay),
                    verification_clock.metering(verification_clock.Meter()),
                ):
                    self.scoped()
                    self.scoped()
                    change()
                    self.scoped()
                    self.scoped()
                self.assertEqual(replay.calls, 2)

    def test_change_during_the_replay_is_not_kept(self):
        def append():
            with (self.root / "stage_events.jsonl").open("ab") as stream:
                stream.write(b'{"e": 3}\n')

        replay = Replay(during=append)
        with (
            self.patched(replay),
            verification_clock.metering(verification_clock.Meter()),
        ):
            self.scoped()
            self.scoped()
        self.assertEqual(replay.calls, 2)

    def test_failed_replays_are_never_reused(self):
        cases = (
            Replay(error=ValueError("replay crashed")),
            Replay(result={"valid": False, "errors": ["x"]}),
        )
        for replay in cases:
            with self.subTest(error=replay.error):
                with (
                    self.patched(replay),
                    verification_clock.metering(verification_clock.Meter()),
                ):
                    for _ in range(2):
                        if replay.error is None:
                            self.assertFalse(self.scoped()["valid"])
                        else:
                            with self.assertRaises(ValueError):
                                self.scoped()
                self.assertEqual(replay.calls, 2)

    def test_reused_report_is_a_private_copy(self):
        replay = Replay()
        with (
            self.patched(replay),
            verification_clock.metering(verification_clock.Meter()),
        ):
            first = self.scoped()
            first["valid"] = False
            first["nested"]["counts"].append(99)
            second = self.scoped()
            second["nested"]["counts"].append(7)
            third = self.scoped()
        self.assertEqual(replay.calls, 1)
        self.assertTrue(third["valid"])
        self.assertEqual(third["nested"], {"counts": [1, 2]})

    def test_unreadable_change_evidence_is_never_reused(self):
        (self.root / "stage_events.jsonl").unlink()
        replay = Replay()
        with (
            self.patched(replay),
            verification_clock.metering(verification_clock.Meter()),
        ):
            self.scoped()
            self.scoped()
        self.assertEqual(replay.calls, 2)


if __name__ == "__main__":
    unittest.main()
