"""Reuse a verified host context only for its exact immutable receiving inputs."""

from copy import deepcopy
from pathlib import Path
import shutil
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cli"))

from research_workspace.host_replay import resolve_host_replay
import test_stage1_host_replay as fixtures


class HostContextBindingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixtures.HostReplayTests.setUpClass()
        cls.addClassCleanup(fixtures.HostReplayTests.doClassCleanups)

    def setUp(self):
        self.fixture = fixtures.HostReplayTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.context = self.fixture.load()

    def test_same_verified_context_cannot_rebind_to_a_copied_package(self):
        fixture = self.fixture
        self.assertIs(
            resolve_host_replay(
                fixture.root, fixture.snapshot_ref, verified_host_replay=self.context
            ),
            self.context,
        )
        copied = fixture.root / "relocated"
        shutil.copytree(fixture.output, copied / "package")
        shutil.copyfile(fixture.root / "snapshot.json", copied / "snapshot.json")
        with self.assertRaisesRegex(ValueError, "snapshot package differs"):
            resolve_host_replay(
                copied, fixture.snapshot_ref, verified_host_replay=self.context
            )
        changed = deepcopy(fixture.snapshot_ref)
        changed["sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "snapshot reference differs"):
            resolve_host_replay(
                fixture.root, changed, verified_host_replay=self.context
            )

    def test_partial_or_mixed_trust_inputs_and_non_context_are_rejected(self):
        fixture = self.fixture
        explicit = dict(
            host_replay_receipt=fixture.root / "host-replay.json",
            trusted_host_replay_sha256="0" * 64,
            historical_exporter_root=fixture.old_root,
            replayer_exporter_root=fixture.replayer_root,
        )
        for kwargs in (
            {"host_replay_receipt": explicit["host_replay_receipt"]},
            dict(explicit, verified_host_replay=self.context),
            {"verified_host_replay": self.context.evidence()},
        ):
            with self.subTest(keys=sorted(kwargs)), self.assertRaises(ValueError):
                resolve_host_replay(fixture.root, fixture.snapshot_ref, **kwargs)

    def test_absent_context_retains_legacy_no_read_behavior(self):
        self.assertIsNone(resolve_host_replay(self.fixture.root / "absent", {}))
