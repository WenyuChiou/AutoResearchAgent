"""Discovery rounds, saved appearances and legacy export compatibility."""

from copy import deepcopy
import csv
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest

from openpyxl import load_workbook

sys.path.insert(0, str(Path(__file__).parents[1] / "cli"))

from research_workspace.delivery_review import delivery_review_files
from research_workspace.original_record_recovery import attach_original_records
from research_workspace.retrieval_trace import work_trace
from stage1_deliverable.common import DeliverableError, sha
from test_saved_source_reassessment import review_case


class RetrievalTraceTests(unittest.TestCase):
    def test_first_unknown_round_is_not_replaced_by_later_known_round(self):
        discoveries = [
            dict(
                discovery_id="first",
                version_id="v1",
                query_id="q1",
                attempt_id="a1",
                round_number=None,
                completion_created_at="2026-10-01T00:00:00Z",
                candidate_discovery_order_in_run=1,
            ),
            dict(
                discovery_id="later",
                version_id="v2",
                query_id="q2",
                attempt_id="a2",
                round_number=3,
                completion_created_at="2026-10-02T00:00:00Z",
                candidate_discovery_order_in_run=8,
            ),
        ]
        counts = dict(
            discoveries=2,
            distinct_queries=2,
            discovery_producing_backend_attempts=2,
            query_backend_attempts=3,
            recorded_rounds=1,
            round_ids_known=False,
        )
        index = dict(
            screening_library=dict(
                rows=[
                    dict(
                        work_id="synthetic",
                        discoveries=list(reversed(discoveries)),
                        counts=counts,
                    )
                ]
            )
        )
        original = deepcopy(index)
        result = work_trace(index, "synthetic")
        self.assertEqual(result["first_discovery"], discoveries[0])
        self.assertEqual(result["counts"], counts)
        self.assertIsNone(result["search_attempts_until_first_discovery"])
        self.assertEqual(result["identity_scope"], "work-all-recorded-versions")
        self.assertEqual(index, original)

    def test_saved_batches_are_not_rounds_and_missing_is_not_zero(self):
        observations = [
            dict(
                observation_ref=f"o{n}",
                batch_ref=b,
                url_observed="https://example.org/work",
            )
            for n, b in enumerate(["saved-007", "saved-001", "saved-007"])
        ]
        mappings = [
            dict(
                observation_ref=f"o{n}",
                decision="include",
                linked_work_id="synthetic",
                linked_version_id="current-v2",
                mapping_basis="work URL only",
            )
            for n in [2, 0, 1]
        ]
        index = dict(
            papers=[dict(work_id="synthetic", version_id="current-v2")],
            original_record_recovery=dict(
                payload=dict(
                    new_candidate_screening=dict(
                        observations=observations, value=dict(rows=mappings)
                    )
                )
            ),
        )
        result = work_trace(index, "synthetic")
        self.assertEqual(result["saved_observation_count"], 3)
        self.assertEqual(result["distinct_saved_batch_count"], 2)
        self.assertEqual(result["first_saved_batch_by_inventory_order"], "saved-007")
        self.assertIsNone(result["first_discovery"])
        self.assertIsNone(result["counts"])
        self.assertEqual(
            result["observations"][0]["mapping_pointer"].rsplit("/", 1)[1], "1"
        )
        mappings[0].update(
            decision="duplicate",
            repeat_of="o0",
            linked_work_id="forged",
            linked_version_id="forged",
        )
        self.assertEqual(work_trace(index, "synthetic")["saved_observation_count"], 3)
        mappings[0].update(decision="exclude", linked_work_id="synthetic")
        self.assertEqual(work_trace(index, "synthetic")["saved_observation_count"], 2)
        mappings[0].update(decision="include", linked_version_id="forged")
        with self.assertRaisesRegex(DeliverableError, "work/version differs"):
            work_trace(index, "synthetic")
        mappings.pop(0)
        absent = work_trace(index, "not-in-saved-scope")
        self.assertIsNone(absent["saved_observation_count"])
        self.assertEqual(absent["status"], "not-recorded")

    def test_long_duplicate_chain_uses_include_anchor_without_recursion(self):
        observations = [
            dict(
                observation_ref=f"o{n}",
                batch_ref="batch",
                url_observed="https://example.org/work",
            )
            for n in range(1500)
        ]
        mappings = [
            dict(
                observation_ref="o0",
                decision="include",
                linked_work_id="synthetic",
                linked_version_id="v1",
                mapping_basis="URL only",
            )
        ]
        mappings.extend(
            dict(
                observation_ref=f"o{n}",
                decision="duplicate",
                repeat_of=f"o{n - 1}",
                linked_work_id="forged",
                linked_version_id="forged",
            )
            for n in range(1, 1500)
        )
        index = dict(
            papers=[dict(work_id="synthetic", version_id="v1")],
            original_record_recovery=dict(
                payload=dict(
                    new_candidate_screening=dict(
                        observations=list(reversed(observations)),
                        value=dict(rows=mappings),
                    )
                )
            ),
        )
        result = work_trace(index, "synthetic")
        self.assertEqual(result["saved_observation_count"], 1500)
        first = result["observations"][0]
        self.assertEqual(first["linked_version_id"], "v1")
        self.assertTrue(first["mapping_pointer"].endswith("/0"))
        self.assertTrue(first["observation_review_pointer"].endswith("/1499"))

    def test_known_round_and_failed_attempt_counts_keep_distinct_meanings(self):
        from test_project_stage1_library import ProjectStage1LibraryTests

        case = ProjectStage1LibraryTests("runTest")
        case.setUp()
        try:
            library = case.library.read(case.token, case.ref)["projection"]
            work = case.work_by_name["retained"]
            bound = next(r for r in library["rows"] if r["work_id"] == work)
            result = work_trace(dict(screening_library=library), work)
            first = min(
                bound["discoveries"],
                key=lambda d: d["candidate_discovery_order_in_run"],
            )
            self.assertEqual(
                result["first_discovery"]["round_number"], first["round_number"]
            )
            self.assertEqual(result["counts"]["distinct_queries"], 2)
            self.assertEqual(result["counts"]["query_backend_attempts"], 2)
            self.assertEqual(len(library["query_history"]), 3)
            self.assertEqual(
                result["query_history_scope"], "discovery-producing-queries-for-work"
            )
            self.assertIsNone(result["search_attempts_until_first_discovery"])
        finally:
            case.doCleanups()

    def test_conflicting_formatter_flags_are_refused(self):
        from research_workspace.academic_screening import derive_academic_screening
        from test_research_workspace_view import fixture_index

        for flags in (
            {"include_original_records": False},
            {"include_new_reviews": False},
        ):
            with self.assertRaisesRegex(ValueError, "current review contract"):
                derive_academic_screening(
                    fixture_index(), include_retrieval_trace=True, **flags
                )

    def test_new_view_binds_trace_source_without_recovery_and_old_view_replays(self):
        from research_workspace.view import write_workspace
        from research_workspace.final_delivery import _view
        from test_research_workspace_view import fixture_index
        from stage1_deliverable.common import canonical

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "view"
            index = fixture_index()
            reference = Path(__file__).parents[1] / "references/research-workspace"
            write_workspace(index, reference, root)
            manifest = json.loads((root / "view-manifest.json").read_bytes())
            self.assertEqual(
                manifest["adapter_sources"]["retrieval_trace.py"],
                sha(
                    (
                        Path(__file__).parents[1]
                        / "cli/research_workspace/retrieval_trace.py"
                    ).read_bytes()
                ),
            )
            _view(root, sha((root / "view-manifest.json").read_bytes()))
            for name, raw in delivery_review_files(
                index, contract="S1-DELIVERY-REVIEW-1.3.0"
            ).items():
                (root / name).write_bytes(raw)
                manifest["files"][name] = sha(raw)
            manifest["delivery_review_contract"] = "S1-DELIVERY-REVIEW-1.3.0"
            (root / "view-manifest.json").write_bytes(canonical(manifest))
            _view(root, sha((root / "view-manifest.json").read_bytes()))

    def test_new_trace_exports_and_four_legacy_formatters_keep_exact_bytes(self):
        with tempfile.TemporaryDirectory() as folder:
            index, pin = review_case(Path(folder))
            index = attach_original_records(index, folder, pin)
            before = deepcopy(index)
            baseline = json.loads(
                (
                    Path(__file__).parent
                    / "fixtures/retrieval-trace-legacy-exports.json"
                ).read_bytes()
            )
            for contract, expected in baseline.items():
                self.assertEqual(
                    {
                        n: sha(v)
                        for n, v in delivery_review_files(
                            index, contract=contract
                        ).items()
                    },
                    expected,
                )
            files = delivery_review_files(index)
            result = json.loads(files["literature/academic_screening.json"])
            self.assertEqual(result["contract_version"], "S1-SCREENING-READMODEL-1.4.0")
            trace = result["rows"][0]["retrieval_trace"]
            self.assertEqual(trace["status"], "not-recorded")
            csv_rows = list(
                csv.DictReader(
                    io.StringIO(
                        files["literature/academic_screening.csv"].decode("utf-8-sig")
                    )
                )
            )
            self.assertEqual(json.loads(csv_rows[0]["retrieval_trace"]), trace)
            book = load_workbook(
                io.BytesIO(files["literature/academic_screening.xlsx"]), read_only=True
            )
            values = list(book["AcademicScreening"].values)
            self.assertEqual(
                json.loads(values[1][values[0].index("retrieval_trace")]), trace
            )
            self.assertIn(
                "actual-search-rounds-not-recorded",
                files["literature/academic_screening.md"].decode(),
            )
            claims = json.loads(files["literature/claim_verification.json"])["rows"]
            self.assertEqual(
                claims[0]["current_assertion"],
                "The source reports the saved exact passage for this case.",
            )
            self.assertEqual(index, before)


if __name__ == "__main__":
    unittest.main()
