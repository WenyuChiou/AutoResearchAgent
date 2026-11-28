"""The saved-ledger replay in a read is a local verification the request clock skips."""

# ruff: noqa: E402 -- exercise the CLI package from the tests directory.
from pathlib import Path
import sys
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / "cli")]
from research_workspace_native import project_stage1
from stage1_retrieval import verification_clock


class LedgerReplayClockTests(unittest.TestCase):
    def test_ledger_replay_is_excluded_from_the_business_deadline(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "ledger"
            root.mkdir()
            manifest = b'{"manifest": true}'
            (root / "run_manifest.json").write_bytes(manifest)
            binding = {name: name + "-value" for name in project_stage1.BINDING_FIELDS}
            binding["settings"] = {"authored": "settings"}
            run = {
                "binding": project_stage1._basis(binding),
                "path": "ledger",
                "manifest_sha256": project_stage1.sha(manifest),
            }
            state = {
                "stage1_active": "r1",
                "stage1_runs": {"r1": run},
                "project_ref": "project-x",
            }
            service = SimpleNamespace(
                intake=SimpleNamespace(_path=lambda ref, rel: Path(raw) / rel)
            )

            def replay(path):
                time.sleep(0.2)  # reading and hashing the saved ledger
                return {"valid": True}

            meter = verification_clock.Meter()
            with (
                mock.patch.object(project_stage1, "validate_run", replay),
                mock.patch.object(
                    project_stage1,
                    "CoverageLedger",
                    lambda path: SimpleNamespace(root=Path(path)),
                ),
                verification_clock.metering(meter),
            ):
                project_stage1.ProjectStage1Service._ledger(service, state, binding)
                skipped = verification_clock.excluded()
            self.assertGreaterEqual(skipped, 0.15)


if __name__ == "__main__":
    unittest.main()
