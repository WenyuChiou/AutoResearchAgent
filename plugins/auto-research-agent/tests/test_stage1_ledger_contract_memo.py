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

    def test_tuple_and_list_are_never_confused(self):
        validator = self.fake([])
        with patch.object(contracts, "validator", return_value=validator):
            contracts.check({"a": [1, 2]}, "Anything")
            contracts.check({"a": (1, 2)}, "Anything")
            contracts.check({"a": (1, 2)}, "Anything")
            contracts.check({1: "x"}, "Anything")
        # the list is cached once; every tuple / non-str-key value is validated
        self.assertEqual(type(validator).calls, 4)

    def test_invalid_value_on_the_real_schema_is_never_cached(self):
        manifest = {"kind": "x"}
        real = contracts.validator("Stage1Manifest")
        with patch.object(contracts, "validator", return_value=real):
            for _ in range(2):
                with self.assertRaises(LedgerError):
                    contracts.check(manifest, "Stage1Manifest")
        self.assertEqual(len(contracts._valid), 0)

    def test_threads_share_the_memo_safely(self):
        from concurrent.futures import ThreadPoolExecutor

        validator = self.fake([])
        values = [{"n": index % 7} for index in range(200)]
        with patch.object(contracts, "validator", return_value=validator):
            with ThreadPoolExecutor(max_workers=8) as pool:
                list(pool.map(lambda v: contracts.check(v, "Anything"), values))
        self.assertEqual(len(contracts._valid), 7)
        self.assertGreaterEqual(type(validator).calls, 7)

    def test_too_deeply_nested_value_is_never_remembered(self):
        validator = self.fake([])
        deep = current = {}
        for _ in range(5000):
            current["x"] = {}
            current = current["x"]
        with patch.object(contracts, "validator", return_value=validator):
            contracts.check(deep, "Anything")
            contracts.check(deep, "Anything")
        self.assertEqual(type(validator).calls, 2)
        self.assertEqual(len(contracts._valid), 0)


if __name__ == "__main__":
    unittest.main()
