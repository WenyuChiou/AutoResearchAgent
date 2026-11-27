"""Schema checks remember only successful results for the exact same JSON value."""

# ruff: noqa: E402 -- exercise repository CLI.
from copy import deepcopy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / "cli")]
from stage1_ledger import contracts
from stage1_ledger.journal import LedgerError

VALUE = {"kind": "Checkpoint"}


class ContractMemoTests(unittest.TestCase):
    def setUp(self):
        contracts._valid.clear()
        self.addCleanup(contracts._valid.clear)

    def fake(self, errors):
        class Validator:
            calls = 0

            def iter_errors(self, value):
                type(self).calls += 1
                return iter(errors)

        return Validator()

    def test_valid_value_is_validated_once_and_changed_value_again(self):
        validator = self.fake([])
        with patch.object(contracts, "validator", return_value=validator):
            contracts.check(VALUE, "Anything")
            contracts.check(deepcopy(VALUE), "Anything")
            self.assertEqual(type(validator).calls, 1)
            contracts.check({**VALUE, "x": 1}, "Anything")
            contracts.check(VALUE, "Other")
            self.assertEqual(type(validator).calls, 3)

    def test_failures_are_never_remembered(self):
        error = type("E", (), {"absolute_path": ["a"], "message": "bad"})()
        validator = self.fake([error])
        with patch.object(contracts, "validator", return_value=validator):
            for _ in range(2):
                with self.assertRaisesRegex(LedgerError, "schema:Anything/a: bad"):
                    contracts.check(VALUE, "Anything")
            self.assertEqual(type(validator).calls, 2)
        self.assertEqual(len(contracts._valid), 0)

    def test_unserializable_value_is_validated_every_time(self):
        validator = self.fake([])
        value = {"kind": object()}
        with patch.object(contracts, "validator", return_value=validator):
            contracts.check(value, "Anything")
            contracts.check(value, "Anything")
        self.assertEqual(type(validator).calls, 2)

    def test_real_schema_still_rejects_after_a_valid_check(self):
        # The real validator keeps rejecting an invalid value on every call.
        with self.assertRaises(LedgerError):
            contracts.check({}, "Stage1Manifest")
        with self.assertRaises(LedgerError):
            contracts.check({}, "Stage1Manifest")
        self.assertEqual(len(contracts._valid), 0)

    def test_memory_is_bounded(self):
        validator = self.fake([])
        with (
            patch.object(contracts, "validator", return_value=validator),
            patch.object(contracts, "_VALID_LIMIT", 3),
        ):
            for index in range(10):
                contracts.check({"n": index}, "Anything")
        self.assertEqual(len(contracts._valid), 3)


if __name__ == "__main__":
    unittest.main()
