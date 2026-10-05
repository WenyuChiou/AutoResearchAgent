"""Retained observation writes stay in the host-selected directory."""

import json
import os
from pathlib import Path
import sys
import unittest

CLI = Path(__file__).resolve().parents[1] / "cli"
sys.path.insert(0, str(CLI))

import test_stage2_runtime_observation as fixture  # noqa: E402
from stage2_live.native import CaptureError  # noqa: E402
from stage2_live.observation import (  # noqa: E402
    collect_runtime_observation,
    verify_runtime_observation,
)
from stage2_live.trace_seal_io import SealDirectory  # noqa: E402


class ObservationIOTests(unittest.TestCase):
    setUp = fixture.RuntimeObservationTests.setUp
    transport = fixture.RuntimeObservationTests.transport

    def collect(self, handle, transport=None):
        return collect_runtime_observation(
            **self.args,
            rpc_transport=transport or self.transport,
            _output_handle=handle,
        )

    def test_entered_handle_preserves_replay_and_synthetic_classification(self):
        root = self.args["output_dir"]
        root.mkdir()
        with SealDirectory(root) as handle:
            result = self.collect(handle)
        verified = verify_runtime_observation(
            root, result["record_sha256_receipt"], allow_synthetic=True
        )
        self.assertEqual(verified["status"], "observed")
        self.assertFalse(verified["formal_ready"])
        self.assertEqual(len(list(root.iterdir())), 5)
        self.assertEqual(len(self.requests), 4)

    def test_unentered_or_foreign_handle_is_rejected_before_transport(self):
        root = self.args["output_dir"]
        root.mkdir()
        with self.assertRaisesRegex(CaptureError, "handle differs"):
            self.collect(SealDirectory(root))
        with SealDirectory(root) as closed:
            pass
        with self.assertRaisesRegex(CaptureError, "handle differs"):
            self.collect(closed)
        foreign = self.root / "foreign"
        foreign.mkdir()
        with SealDirectory(foreign) as handle:
            with self.assertRaisesRegex(CaptureError, "handle differs"):
                self.collect(handle)
        self.assertEqual(self.requests, [])
        self.assertEqual(list(root.iterdir()), [])
        self.assertEqual(list(foreign.iterdir()), [])

    def test_replacement_during_transport_cannot_redirect_writes(self):
        root = self.args["output_dir"]
        parked = self.root / "parked"
        root.mkdir()
        replaced = False

        def replace(*args):
            nonlocal replaced
            if os.name == "nt":
                with self.assertRaises(PermissionError):
                    root.rename(parked)
            else:
                root.rename(parked)
                root.symlink_to(self.work, target_is_directory=True)
                replaced = True
            return self.transport(*args)

        try:
            with SealDirectory(root) as handle:
                result = self.collect(handle, replace)
            target = parked if replaced else root
            self.assertEqual(len(list(target.iterdir())), 5)
            self.assertEqual(list(self.work.iterdir()), [])
            self.assertEqual(
                verify_runtime_observation(
                    target, result["record_sha256_receipt"], allow_synthetic=True
                )["status"],
                "observed",
            )
        finally:
            if replaced:
                root.unlink()

    def test_failed_transport_preserves_error_artifacts_with_retained_handle(self):
        root = self.args["output_dir"]
        root.mkdir()

        def failure(*_):
            error = CaptureError("interrupted transport")
            error.observation_events = [{"direction": "request"}]
            error.observation_stderr = b"diagnostic"
            raise error

        with SealDirectory(root) as handle:
            with self.assertRaisesRegex(CaptureError, "interrupted"):
                self.collect(handle, failure)
        self.assertEqual(
            {path.name for path in root.iterdir()},
            {"failed-transport.json", "stderr.txt", "failure.json"},
        )
        self.assertEqual((root / "stderr.txt").read_bytes(), b"diagnostic")
        self.assertEqual(
            json.loads((root / "failure.json").read_bytes())["status"], "failed"
        )

    def test_existing_leaf_is_not_overwritten(self):
        root = self.args["output_dir"]
        root.mkdir()
        (root / "transport.json").write_bytes(b"original")
        with SealDirectory(root) as handle:
            with self.assertRaises(FileExistsError):
                self.collect(handle)
        self.assertEqual((root / "transport.json").read_bytes(), b"original")


if __name__ == "__main__":
    unittest.main()
