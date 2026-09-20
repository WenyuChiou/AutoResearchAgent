"""Exported evaluator inputs are self-contained, replayable and honest about gaps."""

from pathlib import Path
import json
import subprocess
import sys
import tempfile
import unittest

from test_stage1_ledger import fixture
from stage1_export.bundle import export_run, validate_export
from stage1_ledger.journal import LedgerError, canonical, digest


class Stage1ExportTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.ledger, self.refs, self.work, _ = fixture(self.root / "run")
        self.ledger.checkpoint()
        self.output = self.root / "export"

    def read(self, name):
        return json.loads((self.output / name).read_bytes())

    def test_export_preserves_failures_and_unknown_denominators_without_scores(self):
        export_run(self.ledger.root, self.output)
        inputs, efficiency = (
            self.read("metric_inputs.json"),
            self.read("efficiency.json"),
        )
        self.assertEqual(
            inputs["P3"]["works_with_trace"],
            {"n": 0, "N": 0, "ratio": None, "status": "not-applicable"},
        )
        self.assertEqual(inputs["P2"]["core_recall"]["status"], "unavailable")
        self.assertIsNone(inputs["P2"]["core_recall"]["n"])
        self.assertIsNone(inputs["P1"]["central_claim_ids"])
        self.assertEqual(
            inputs["judgment_scores"]["P1"],
            {"R1": None, "R2": None, "ADJ": None, "status": "not_scored"},
        )
        self.assertIsNone(inputs["major_error_gate"]["issues"])
        self.assertEqual(efficiency["recorded_backend_attempts"], 4)
        self.assertEqual(
            efficiency["backend_outcomes"],
            {"rate_limited": 1, "success_empty": 1, "success_nonempty": 2},
        )
        for key in [
            "tokens",
            "cost",
            "tool_calls",
            "human_interventions",
            "retries",
            "elapsed_seconds",
        ]:
            self.assertIsNone(efficiency[key])
        self.assertTrue(validate_export(self.output)["valid"])

    def test_snapshot_survives_original_change_and_excludes_unrelated_files(self):
        (self.ledger.root / "private-note.txt").write_text(
            "Unrelated synthetic note", encoding="utf-8"
        )
        before = self.ledger.state_hash()
        export_run(self.ledger.root, self.output)
        self.assertEqual(self.ledger.state_hash(), before)
        self.assertFalse((self.output / "source/private-note.txt").exists())
        self.assertFalse((self.output / "source/.writer-lock").exists())
        self.ledger.decide(
            self.work,
            "include",
            reason="scope-match",
            rationale="Synthetic update",
            evidence_refs=[self.refs[0]],
        )
        self.assertTrue(validate_export(self.output)["valid"])
        with self.assertRaisesRegex(LedgerError, "current-checkpoint-required"):
            export_run(self.ledger.root, self.root / "stale")
        self.assertFalse((self.root / "stale").exists())

    def test_repeated_export_is_reproducible_and_existing_output_is_preserved(self):
        export_run(self.ledger.root, self.output)
        second = self.root / "second"
        export_run(self.ledger.root, second)
        for name in ["metric_inputs.json", "efficiency.json", "export_manifest.json"]:
            self.assertEqual(
                (self.output / name).read_bytes(), (second / name).read_bytes()
            )
        with self.assertRaises(FileExistsError):
            export_run(self.ledger.root, self.output)
        self.assertTrue(validate_export(self.output)["valid"])

    def test_rehashed_metric_invention_is_rejected_by_recomputation(self):
        export_run(self.ledger.root, self.output)
        value = self.read("metric_inputs.json")
        value["P3"]["works_with_trace"]["n"] = 1
        data = canonical(value) + b"\n"
        (self.output / "metric_inputs.json").write_bytes(data)
        manifest = self.read("export_manifest.json")
        entry = next(e for e in manifest["files"] if e["path"] == "metric_inputs.json")
        entry.update(bytes=len(data), sha256=digest(data))
        (self.output / "export_manifest.json").write_bytes(canonical(manifest))
        report = validate_export(self.output)
        self.assertFalse(report["valid"])
        self.assertIn("metric-input-replay", " ".join(report["errors"]))

    def test_missing_source_fails_closed_and_invalid_run_is_not_exported(self):
        export_run(self.ledger.root, self.output)
        (self.output / "source" / self.refs[0]["path"]).unlink()
        self.assertFalse(validate_export(self.output)["valid"])
        (self.ledger.root / self.refs[0]["path"]).unlink()
        with self.assertRaisesRegex(LedgerError, "invalid-export-source"):
            export_run(self.ledger.root, self.root / "bad")
        self.assertFalse((self.root / "bad").exists())

    def test_cli_validates_real_export_and_rejects_unknown_manifest_version(self):
        cli = str(Path(__file__).resolve().parents[1] / "cli/stage1_export")
        result = subprocess.run(
            [
                sys.executable,
                cli,
                "create",
                "--run",
                str(self.ledger.root),
                "--output",
                str(self.output),
            ],
            capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(json.loads(result.stdout)["valid"])
        manifest = self.read("export_manifest.json")
        manifest["schema_version"] = "99.0.0"
        (self.output / "export_manifest.json").write_bytes(canonical(manifest))
        result = subprocess.run(
            [sys.executable, cli, "validate", str(self.output)], capture_output=True
        )
        self.assertEqual(result.returncode, 1)
        self.assertFalse(json.loads(result.stdout)["valid"])

    def test_pending_attempt_and_recorded_year_do_not_imply_verified_coverage(self):
        self.ledger.decide(
            self.work,
            "include",
            reason="scope-match",
            rationale="Synthetic inclusion",
            evidence_refs=[self.refs[0]],
        )
        query = self.ledger.start(
            "search", {"query": "synthetic recent", "year": "2024-2026"}
        )
        self.ledger.start(
            "backend", {"variant": "base"}, backend="synthetic", parent_id=query
        )
        self.ledger.checkpoint()
        export_run(self.ledger.root, self.output)
        inputs, efficiency = (
            self.read("metric_inputs.json"),
            self.read("efficiency.json"),
        )
        self.assertEqual(
            inputs["P3"]["works_with_trace"],
            {"n": 1, "N": 1, "ratio": 1.0, "status": "recorded"},
        )
        self.assertEqual(inputs["P2"]["recorded_recent"]["status"], "unavailable")
        self.assertEqual(inputs["P2"]["recorded_latest_year"], 2024)
        self.assertEqual(inputs["P2"]["scientific_coverage"]["status"], "unavailable")
        self.assertIsNone(inputs["P3"]["versions_with_access_date"]["n"])
        self.assertNotEqual(inputs["P3"]["stop_action"], "stop-sufficient")
        self.assertEqual(efficiency["pending_backend_attempts"], 1)
        self.assertEqual(sum(efficiency["backend_outcomes"].values()), 4)

    def test_read_only_export_rejects_incomplete_projection_and_nested_output(self):
        with self.assertRaisesRegex(LedgerError, "export-must-be-outside-source-run"):
            export_run(self.ledger.root, self.ledger.root / "export")
        projection = self.ledger.root / "candidates.jsonl"
        projection.write_bytes(b"")
        with self.assertRaisesRegex(LedgerError, "projection-incomplete"):
            export_run(self.ledger.root, self.output)
        self.assertEqual(projection.read_bytes(), b"")
        self.assertFalse(self.output.exists())
        self.assertFalse((self.ledger.root / ".writer-lock").exists())

    def test_unbound_query_year_arguments_do_not_crash_or_invent_recency(self):
        for index, year in enumerate([2026, [2024, 2026], "2026-2024", "2024-2026"]):
            with self.subTest(year=year):
                ledger = type(self.ledger).create(
                    self.root / f"year-{index}",
                    run_id="year-test",
                    objective="Synthetic query arguments",
                )
                query = ledger.start("search", {"query": "synthetic", "year": year})
                attempt = ledger.start(
                    "backend", {"variant": "base"}, backend="synthetic", parent_id=query
                )
                raw = ledger.save_bytes(b"[]", producer=attempt)
                ledger.finish(
                    attempt,
                    outcome="success_empty",
                    http_status=200,
                    exit_code=0,
                    stdout=raw,
                    stderr=raw,
                    records=raw,
                )
                ledger.complete_query(query)
                ledger.checkpoint()
                output = self.root / f"year-export-{index}"
                export_run(ledger.root, output)
                recent = json.loads((output / "metric_inputs.json").read_bytes())["P2"][
                    "recorded_recent"
                ]
                self.assertEqual(
                    recent["status"], "not-applicable" if index == 3 else "unavailable"
                )
                self.assertIsNone(recent["ratio"])


if __name__ == "__main__":
    unittest.main()
