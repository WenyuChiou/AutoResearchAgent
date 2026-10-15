"""Pure saved-input guard and actual Stage1/Stage2 offline producer tests."""

import atlas_test_paths  # noqa: F401 -- standalone discovery needs the local CLI.

from pathlib import Path
import io
import os
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from research_workspace_native import stage_inputs as mod
from research_workspace_native.session_api import SessionApiError
from stage1_ledger.validation import validate_run
from stage1_deliverable.common import DeliverableError
from test_stage1_ledger import fixture
import test_stage2_completion as completion_fixture


class StageInputTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.inputs = {"1": None, "2": None}

    def produce(self, stage, action):
        files = mod.snapshot_inputs(self.inputs)
        output = self.root / "result"
        output.mkdir()
        binding = dict(inputs=self.inputs, source_sha256=mod.source_digest(files))
        return mod.produce_stage_result(
            binding,
            dict(stage=stage, action=action, request={}),
            output,
            dict(intents={}),
        )

    def test_actual_checkpoint_copy_preserves_original_and_replays_valid(self):
        ledger, _, _, _ = fixture(self.root / "ledger")
        self.inputs["1"] = dict(ledger_root=str(ledger.root))
        before = mod.source_digest(mod.snapshot_inputs(self.inputs))
        result = self.produce(1, "checkpoint-stage1")
        self.assertTrue(result["ledger_valid"])
        self.assertTrue(validate_run(self.root / "result/stage1/ledger_root")["valid"])
        self.assertEqual(
            result["handoff"]["stage2"],
            dict(status="not-started", execution_authorized=False),
        )
        self.assertEqual(mod.source_digest(mod.snapshot_inputs(self.inputs)), before)

    def test_actual_completion_missing_assessment_is_not_zero_or_permission(self):
        case = completion_fixture.Stage2CompletionTests("runTest")
        case.setUp()
        self.addCleanup(case.doCleanups)
        case.deliver()
        self.inputs["2"] = dict(
            delivery_root=str(case.delivery),
            delivery_manifest_sha256=case.manifest["manifest_sha256"],
            evaluation_root=None,
            evaluation_manifest_sha256=None,
        )
        result = self.produce(2, "inspect-stage2")["completion"]
        self.assertEqual(result, case.inspect())
        self.assertEqual(result["assessment_status"], "missing")
        self.assertIsNone(result["assessment_dimensions"])
        self.assertFalse(result["stage3_execution_authorized"])

    def test_bounds_missing_and_manifest_pair_refuse_without_native_calls(self):
        missing = self.produce(1, "checkpoint-stage1")
        self.assertEqual(missing["readiness"]["status"], "missing")
        with self.assertRaises(SessionApiError):
            mod.snapshot_inputs({1: {}, 2: None})
        source = self.root / "source"
        source.mkdir()
        (source / "large.txt").write_bytes(b"abc")
        with patch.object(mod, "MAX_BYTES", 2):
            with self.assertRaises(SessionApiError):
                mod.snapshot_inputs({1: dict(ledger_root=str(source)), 2: None})
        with self.assertRaises(SessionApiError):
            mod.snapshot_inputs(
                {
                    1: None,
                    2: dict(
                        delivery_root=str(source),
                        delivery_manifest_sha256="a" * 64,
                        evaluation_root=None,
                        evaluation_manifest_sha256="b" * 64,
                    ),
                }
            )

    def test_reparse_child_is_rejected_before_descent_or_bytes_read(self):
        source = self.root / "source"
        child = source / "linked-directory"
        child.mkdir(parents=True)
        payload = child / "outside.txt"
        payload.write_bytes(b"outside bytes")
        original_lstat, original_open = os.lstat, Path.open
        opened = []
        reparse_paths = []

        def attributes(path, *args, **kwargs):
            info = original_lstat(path, *args, **kwargs)
            if Path(path) == child:
                reparse_paths.append(Path(path))
                return SimpleNamespace(st_mode=info.st_mode, st_file_attributes=0x400)
            return info

        def observe(path, *args, **kwargs):
            opened.append(Path(path))
            return original_open(path, *args, **kwargs)

        with (
            patch.object(os, "lstat", side_effect=attributes),
            patch.object(Path, "open", autospec=True, side_effect=observe),
        ):
            with self.assertRaises(DeliverableError):
                mod.snapshot_inputs({1: dict(ledger_root=str(source)), 2: None})
        self.assertIn(child, reparse_paths)
        self.assertNotIn(payload, opened)

    def test_size_race_still_uses_remaining_budget_plus_one_read(self):
        source = self.root / "source"
        source.mkdir()
        payload = source / "small.txt"
        payload.write_bytes(b"x")
        reads = []

        class GrownFile(io.BytesIO):
            def read(self, count=-1):
                reads.append(count)
                return super().read(count)

        original_open = Path.open

        def grown(path, *args, **kwargs):
            if Path(path) == payload:
                return GrownFile(b"0123456789")
            return original_open(path, *args, **kwargs)

        with (
            patch.object(mod, "MAX_BYTES", 4),
            patch.object(Path, "open", autospec=True, side_effect=grown),
        ):
            with self.assertRaises(SessionApiError):
                mod.snapshot_inputs({1: dict(ledger_root=str(source)), 2: None})
        self.assertEqual(reads, [5])

    def test_chunked_snapshot_preserves_small_empty_and_multi_chunk_bytes(self):
        source = self.root / "source"
        source.mkdir()
        raw = bytes(range(256)) * 1024 + b"end"
        (source / "a.bin").write_bytes(raw)
        (source / "b.empty").touch()
        (source / "c.txt").write_bytes(b"small")
        binding = {1: dict(ledger_root=str(source)), 2: None}
        with patch.object(mod, "MAX_BYTES", len(raw) + 5):
            observed = mod.snapshot_inputs(binding)
        self.assertEqual(
            observed,
            {
                "stage1/ledger_root/a.bin": raw,
                "stage1/ledger_root/b.empty": b"",
                "stage1/ledger_root/c.txt": b"small",
            },
        )
        with patch.object(mod, "MAX_BYTES", len(raw) + 4):
            with self.assertRaisesRegex(SessionApiError, "input-file-bound"):
                mod.snapshot_inputs(binding)
        with patch.object(mod, "MAX_FILES", 2):
            with self.assertRaisesRegex(SessionApiError, "input-snapshot-bound"):
                mod.snapshot_inputs(binding)

    def test_short_snapshot_reads_reach_eof_with_fresh_raw_hash(self):
        source = self.root / "source"
        source.mkdir()
        path = source / "bytes"
        raw = b"short stream" * 20000
        path.write_bytes(raw)
        requests = []

        class ShortReader(io.BytesIO):
            def read(self, count=-1):
                requests.append(count)
                return super().read(min(count, 17))

        original = Path.open

        def opened(value, *args, **kwargs):
            return (
                ShortReader(raw) if value == path else original(value, *args, **kwargs)
            )

        binding = {1: dict(ledger_root=str(source)), 2: None}
        with patch.object(Path, "open", autospec=True, side_effect=opened):
            observed = mod.snapshot_inputs(binding)
        self.assertEqual(observed, {"stage1/ledger_root/bytes": raw})
        self.assertLessEqual(max(requests), 64 * 1024)
        path.write_bytes(b"modified" + raw[8:])
        self.assertNotEqual(
            mod.source_digest(mod.snapshot_inputs(binding)), mod.source_digest(observed)
        )

    def test_growth_after_stat_stops_at_remaining_total_plus_one(self):
        source = self.root / "source"
        source.mkdir()
        (source / "a.bin").write_bytes(b"first")
        grown_path = source / "b.bin"
        grown_path.write_bytes(b"x")
        reads, observed = [], []

        class GrowingReader(io.BytesIO):
            def read(self, count=-1):
                reads.append(count)
                raw = super().read(min(count, 3))
                observed.append(len(raw))
                return raw

        original = Path.open

        def opened(value, *args, **kwargs):
            return (
                GrowingReader(b"grown past the initial size")
                if value == grown_path
                else original(value, *args, **kwargs)
            )

        with (
            patch.object(mod, "MAX_BYTES", 10),
            patch.object(Path, "open", autospec=True, side_effect=opened),
        ):
            with self.assertRaisesRegex(SessionApiError, "input-snapshot-bound"):
                mod.snapshot_inputs({1: dict(ledger_root=str(source)), 2: None})
        self.assertEqual(sum(observed), 6)
        self.assertEqual(reads, [6, 3])

    def test_sqlite_reparse_sidecar_refuses_before_readonly_connect(self):
        database = self.root / "saved.sqlite3"
        database.write_bytes(b"not needed for zero-connect proof")
        sidecar = self.root / "saved.sqlite3-wal"
        sidecar.write_bytes(b"outside WAL bytes")
        original_lstat = os.lstat
        reparse_paths = []

        def attributes(path, *args, **kwargs):
            info = original_lstat(path, *args, **kwargs)
            if Path(path) == sidecar:
                reparse_paths.append(Path(path))
                return SimpleNamespace(st_mode=info.st_mode, st_file_attributes=0x400)
            return info

        with (
            patch.object(os, "lstat", side_effect=attributes),
            patch.object(
                mod.sqlite3, "connect", side_effect=AssertionError("must not connect")
            ) as connection,
        ):
            with self.assertRaises(DeliverableError):
                mod.preflight_storage([], database)
        self.assertIn(sidecar, reparse_paths)
        connection.assert_not_called()


if __name__ == "__main__":
    unittest.main()
