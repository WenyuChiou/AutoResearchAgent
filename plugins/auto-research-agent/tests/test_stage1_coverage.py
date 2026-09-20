"""Synthetic coverage plan checks; no benchmark or network inputs."""

from copy import deepcopy
from pathlib import Path
import json
import subprocess
import sys
import tempfile
import unittest

PLUGIN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN / "cli"))
from stage1_coverage.plan import compile_plan, validate_bundle
from stage1_ledger.journal import canonical, digest


def proposal():
    return dict(
        plan_id="synthetic-coverage",
        topic="Synthetic household research question",
        decomposition=dict(
            population="synthetic households",
            phenomenon="synthetic outcomes",
            method="synthetic method",
            validation="synthetic checks",
        ),
        inclusion_criteria=["addresses a declared cluster"],
        exclusion_criteria=["has no traceable source"],
        concepts=[
            dict(
                concept_id="households",
                terms=["synthetic households", "synthetic homes"],
            ),
            dict(concept_id="outcomes", terms=["synthetic outcomes"]),
        ],
        clusters=[
            dict(
                cluster_id=f"cluster-{i}",
                label=f"Synthetic cluster {i}",
                question=f"Synthetic subquestion {i}",
                min_included_works=1,
                query_families=[
                    dict(
                        family_id=f"family-{i}",
                        concept_ids=["households", "outcomes"],
                        adversarial_queries=[f"synthetic contrary evidence {i}"],
                    )
                ],
            )
            for i in range(1, 5)
        ],
        stop_policy=dict(
            max_rounds=3,
            consecutive_zero_yield_rounds=2,
            closest_min_verified=1,
            require_references=True,
            require_cited_by=True,
        ),
    )


class CoveragePlanTests(unittest.TestCase):
    def test_compile_four_clusters_recent_and_adversarial_with_full_provenance(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "plan"
            result = compile_plan(
                proposal(), root, as_of="2026-09-20", actor="synthetic-planner"
            )
            plan = json.loads((root / "coverage_plan.json").read_text(encoding="utf-8"))
            queries = [
                json.loads(line)
                for line in (root / "query_plan.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
            ]
            self.assertEqual(
                plan["recent_window"], {"from_year": 2024, "through_year": 2026}
            )
            self.assertEqual(
                result["counts"], {"clusters": 4, "families": 4, "planned_queries": 12}
            )
            self.assertEqual(
                {q["purpose"] for q in queries}, {"topical", "adversarial", "recent"}
            )
            self.assertEqual(len({q["query_id"] for q in queries}), 12)
            self.assertTrue(all(q["family_id"] and q["cluster_id"] for q in queries))
            self.assertTrue(
                all(q["execution_status"] == "not-executed" for q in queries)
            )
            self.assertTrue(validate_bundle(root)["valid"])

    def test_missing_cluster_links_duplicate_ids_and_weak_stops_fail(self):
        cases = [
            lambda p: p["clusters"][0]["query_families"][0].update(
                concept_ids=["missing"]
            ),
            lambda p: p["clusters"][1].update(cluster_id="cluster-1"),
            lambda p: p["stop_policy"].update(consecutive_zero_yield_rounds=0),
            lambda p: p["stop_policy"].update(closest_min_verified=0),
            lambda p: p["clusters"][0].update(query_families=[]),
            lambda p: p["concepts"][0].update(terms=["   "]),
        ]
        for mutate in cases:
            with (
                self.subTest(mutate=mutate),
                tempfile.TemporaryDirectory() as directory,
            ):
                value = deepcopy(proposal())
                mutate(value)
                root = Path(directory) / "plan"
                with self.assertRaises(ValueError):
                    compile_plan(value, root, as_of="2026-09-20", actor="synthetic")
                self.assertFalse(root.exists())

    def test_existing_bundle_and_tampered_query_are_not_silently_replaced(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "plan"
            compile_plan(proposal(), root, as_of="2026-09-20", actor="synthetic")
            with self.assertRaises(FileExistsError):
                compile_plan(proposal(), root, as_of="2026-09-20", actor="synthetic")
            path = root / "query_plan.jsonl"
            path.write_text("{}\n", encoding="utf-8")
            self.assertFalse(validate_bundle(root)["valid"])
            self.assertEqual(path.read_text(encoding="utf-8"), "{}\n")

    def test_rehashed_query_cannot_bypass_replay(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "plan"
            compile_plan(proposal(), root, as_of="2026-09-20", actor="synthetic")
            path = root / "query_plan.jsonl"
            queries = [
                json.loads(line)
                for line in path.read_text(encoding="utf-8").splitlines()
            ]
            queries[0]["execution_status"] = "success_nonempty"
            raw = b"".join(canonical(q) + b"\n" for q in queries)
            path.write_bytes(raw)
            manifest_path = root / "plan_manifest.json"
            manifest = json.loads(manifest_path.read_bytes())
            entry = manifest["artifacts"][1]
            entry["bytes"] = len(raw)
            entry["ref"].update(
                sha256=digest(raw), artifact_id="artifact-" + digest(raw)
            )
            manifest_path.write_bytes(canonical(manifest))
            report = validate_bundle(root)
            self.assertFalse(report["valid"])
            self.assertEqual(report["errors"], ["query-plan-replay-mismatch"])

    def test_invalid_creation_metadata_leaves_no_bundle(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "plan"
            with self.assertRaises(ValueError):
                compile_plan(
                    proposal(),
                    root,
                    as_of="2026-09-20",
                    actor="synthetic",
                    clock=lambda: "not-a-time",
                )
            self.assertFalse(root.exists())

    def test_plan_cli_does_not_mistake_planned_queries_for_executed_search(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "proposal.json"
            source.write_text(json.dumps(proposal()), encoding="utf-8")
            command = [
                sys.executable,
                str(PLUGIN / "cli/stage1_coverage"),
                "compile",
                "--input",
                str(source),
                "--output",
                str(root / "bundle"),
                "--as-of",
                "2026-09-20",
                "--actor",
                "synthetic-planner",
            ]
            result = subprocess.run(
                command, capture_output=True, text=True, encoding="utf-8"
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(
                json.loads(result.stdout)["execution_status"], "not-executed"
            )


if __name__ == "__main__":
    unittest.main()
