"""A repository native-run pilot keeps its controlled corpus and gates honest."""

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


PLUGIN = Path(__file__).resolve().parents[1]
BUILDER = PLUGIN / "references/research-workspace/examples/build-stage-run-case.py"


def load_builder():
    spec = importlib.util.spec_from_file_location(
        "native_stage_run_case_example", BUILDER
    )
    module = importlib.util.module_from_spec(spec)
    previous = list(sys.path)
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path[:] = previous
    return module


class NativeStageRunCaseTests(unittest.TestCase):
    def test_actual_ledger_packet_and_both_views_share_exact_source_identities(self):
        builder = load_builder()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve() / "case"
            popen, commands = subprocess.Popen, []

            def readonly_git_only(command, *args, **kwargs):
                commands.append(command)
                self.assertEqual(Path(command[0]).stem, "git")
                self.assertIn("rev-parse", command)
                return popen(command, *args, **kwargs)

            with patch("subprocess.Popen", side_effect=readonly_git_only):
                case = builder.build(root)
            self.assertTrue(commands)
            packet = json.loads((root / "packet.json").read_bytes())
            ledger = builder.Ledger(case["stage1_ledger_root"])
            self.assertTrue(builder.validate_run(ledger.root)["valid"])
            self.assertEqual(packet["candidates"], [])
            self.assertEqual(len(packet["sources"]), 2)
            self.assertEqual(
                case["packet_sha256"], builder.sha((root / "packet.json").read_bytes())
            )
            self.assertFalse(case["canonical_stage1_to_stage2_lineage"])
            self.assertFalse(case["stage1_complete"])
            self.assertFalse(case["execution_authorized"])
            self.assertEqual(
                (case["native_calls"], case["model_calls"], case["search_calls"]),
                (0, 0, 0),
            )
            self.assertNotEqual(case["stage1_next_allowed_action"], "stop-sufficient")
            self.assertEqual(case["stage1_gate"]["outcome"], "review-required")
            self.assertIn(
                "recorded-backend-failures-require-review",
                case["stage1_gate"]["blocking_items"],
            )
            index = json.loads(
                (root / "views/stage1/workspace-index.json").read_bytes()
            )
            other = json.loads(
                (root / "views/stage2/workspace-index.json").read_bytes()
            )
            self.assertEqual(index, other)
            self.assertEqual(index["native_session"]["status"], "not-connected")
            self.assertEqual(index["provenance"]["package_manifest_sha256"], "0" * 64)
            for source, binding, paper in zip(
                packet["sources"], case["paper_bindings"], index["papers"]
            ):
                self.assertEqual(
                    (source["work_id"], source["version_id"]),
                    (paper["work_id"], paper["version_id"]),
                )
                self.assertEqual(source["source_id"], binding["source_id"])
                raw = (Path(case["source_root"]) / source["path"]).read_bytes()
                self.assertEqual(raw, ledger.read_ref(binding["source_ref"]))
                self.assertEqual(builder.sha(raw), source["sha256"])
                self.assertEqual(
                    builder.sha(raw), case["source_bindings"][source["path"]]
                )
                self.assertIn(paper["title"].encode(), raw)
                self.assertIsNone(paper["url"])
                self.assertIsNone(paper["doi"])
            finished = [
                row["payload"]
                for row in ledger.events()
                if row["payload"]["kind"] == "ActionFinished"
            ]
            self.assertEqual(len(finished), 1)
            self.assertEqual(finished[0]["outcome"], "partial_failure")
            self.assertIsNone(finished[0]["http_status"])

    def test_existing_output_refused_before_fixture_writes_and_keeps_old_bytes(self):
        builder = load_builder()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve() / "case"
            root.mkdir()
            sentinel = root / "case.json"
            sentinel.write_bytes(b"old immutable case")
            with patch.object(builder, "write_stage2_fixture") as write:
                with self.assertRaises(FileExistsError):
                    builder.build(root)
                write.assert_not_called()
            self.assertEqual(sentinel.read_bytes(), b"old immutable case")

    def test_git_output_refused_before_any_fixture_or_native_call(self):
        builder = load_builder()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            (root / ".git").mkdir()
            with patch.object(builder, "write_stage2_fixture") as write:
                with self.assertRaisesRegex(ValueError, "Git"):
                    builder.build(root / "new-case")
                write.assert_not_called()
            self.assertFalse((root / "new-case").exists())


if __name__ == "__main__":
    unittest.main()
