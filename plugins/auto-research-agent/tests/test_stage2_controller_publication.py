"""Controller publication recovery never redispatches accepted synthetic units."""

# ruff: noqa: E402 -- repository packages and authored offline fixtures.
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent / "cli"), str(HERE)]
import test_stage2_controller as fixtures
from stage2_workflow.store import inspect_workflow
import stage2_workflow.delivery as delivery
import stage2_workflow.atomic_delivery as atomic


class ControllerPublicationTests(unittest.TestCase):
    setUp = fixtures.Stage2ControllerTests.setUp
    _spec = fixtures.Stage2ControllerTests._spec
    run_controller = fixtures.Stage2ControllerTests.run_controller

    def assert_replay(self, adapter):
        calls = list(adapter.calls)
        before = inspect_workflow(self.run)
        result = self.run_controller(adapter)
        self.assertEqual(adapter.calls, calls)
        self.assertEqual(inspect_workflow(self.run), before)
        self.assertTrue(all(unit["replayed"] for unit in result["units"]))
        self.assertEqual(result["status"], "awaiting-human")
        self.assertTrue(result["synthetic_test_only"])
        self.assertFalse(result["stage3_execution_authorized"])
        self.assertFalse(result["stage2_complete"])

    def test_manifest_write_interruption_recovers_from_same_controller(self):
        adapter = fixtures.SyntheticAdapter()
        write = delivery._write_new

        def interrupted(path, value):
            if Path(path).name == delivery.MANIFEST:
                raise OSError("synthetic manifest interruption")
            return write(path, value)

        with patch.object(delivery, "_write_new", side_effect=interrupted):
            with self.assertRaisesRegex(OSError, "synthetic manifest"):
                self.run_controller(adapter)
        self.assertFalse(self.delivery.exists())
        self.assert_replay(adapter)

    def test_sealed_unpublished_package_is_reused_without_any_new_unit(self):
        adapter = fixtures.SyntheticAdapter()
        with patch.object(
            atomic, "_publish", side_effect=OSError("synthetic rename interruption")
        ):
            with self.assertRaisesRegex(OSError, "synthetic rename"):
                self.run_controller(adapter)
        self.assertFalse(self.delivery.exists())
        with patch.object(
            delivery,
            "build_delivery",
            side_effect=AssertionError("sealed builder must not rerun"),
        ):
            self.assert_replay(adapter)


if __name__ == "__main__":
    unittest.main()
