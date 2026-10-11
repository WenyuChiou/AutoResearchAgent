"""All-candidate saved delivery over real Core, with zero external execution."""

from copy import deepcopy
from pathlib import Path
import unittest
from unittest.mock import patch

from test_project_stage1_records import saved_stage1_case
from research_workspace.canonical_delivery import project_canonical_atlas
from research_workspace_native.project_stage1_delivery import (
    _records_match,
    _screening_library,
)
from research_workspace_native.session_api import SessionApiError
from research_workspace_native.project_stage2 import _verified_inputs
from stage1_deliverable.common import read_json, sha
from stage1_ledger.journal import canonical


def discovery_candidates(case, fixture):
    ledger = fixture["ledger"]
    previous = set(ledger.candidates())
    coverage = ledger.coverage_state()
    planned = list(coverage.queries)[2]
    query = ledger.start_planned(planned)
    backend = ledger.start(
        "backend",
        {"input": coverage.arguments(planned)},
        backend="openalex",
        parent_id=query,
    )
    raw = [
        dict(
            title="Authored excluded discovery",
            authors=["Fixture"],
            year=2025,
            version="v1",
            url="https://example.org/excluded",
        ),
        dict(
            title="Authored unscreened discovery",
            authors=["Fixture"],
            year=2025,
            version="v1",
        ),
    ]
    output = ledger.save_bytes(canonical(raw), producer=backend)
    empty = ledger.save_bytes(b"", producer=backend)
    ledger.finish(
        backend,
        outcome="success_nonempty",
        http_status=200,
        exit_code=0,
        stdout=empty,
        stderr=empty,
        records=output,
    )
    ledger.complete_query(query)
    ledger.extract()
    new = [c for w, c in ledger.candidates().items() if w not in previous]
    excluded = next(c for c in new if c["discoveries"][-1]["record"].get("url"))
    unscreened = next(c for c in new if c != excluded)
    ledger.decide(
        excluded["work_id"],
        "exclude",
        reason="fixture-out-of-scope",
        rationale="Authored exclusion retained; not quality ranking.",
        evidence_refs=[output],
    )
    fixture["checkpoint"] = ledger.checkpoint()
    return excluded, unscreened


def produced(case, fixture):
    offer = case.produce(fixture)
    context = case.delivery._context(fixture["ref"])
    stored = context[1]["stage1_delivery_offers"][offer["offer_ref"]]
    return offer, context, Path(stored["records_path"])


class DiscoveryRecordsTests(unittest.TestCase):
    def test_mixed_library_preserves_all_candidates_package_graph_and_reopen(self):
        with saved_stage1_case() as (case, fixture):
            excluded, unscreened = discovery_candidates(case, fixture)
            events = fixture["ledger"].events()
            offer, context, path = produced(case, fixture)
            records = read_json(path)
            self.assertEqual(
                (
                    len(records["papers"]),
                    len(records["sources"]),
                    len(records["claims"]),
                    len(records["screening"]),
                ),
                (4, 2, 2, 5),
            )
            rows = {p["work_id"]: p for p in records["papers"]}
            self.assertEqual(
                rows[excluded["work_id"]]["reading_status"], "discovery-only"
            )
            self.assertIsNone(rows[unscreened["work_id"]]["url"])
            library = records["screening_library"]
            self.assertEqual(library["counts"]["not_screened"], 1)
            self.assertEqual(library["counts"]["exclude"], 1)
            self.assertEqual(library["counts"]["total_candidates"], 4)
            before = path.read_bytes()
            case.reopen()
            with patch(
                "research_workspace_native.project_stage1_records.os.link"
            ) as write:
                self.assertEqual(case.produce(fixture), offer)
                write.assert_not_called()
            self.assertEqual(path.read_bytes(), before)
            result = case.delivery.deliver(
                "alice-token", fixture["ref"], case.body(fixture, offer)
            )
            self.assertEqual(result["status"], "saved")
            saved = case.delivery._context(fixture["ref"])[1][
                "stage1_canonical_package"
            ]
            root = case.delivery._saved_artifact(
                case.intake._principal("alice-token"),
                case.delivery._context(fixture["ref"])[1],
                saved,
                case.delivery._context(fixture["ref"]),
            )
            index, files = project_canonical_atlas(
                root, fixture["ref"], saved["manifest_sha256"]
            )
            self.assertEqual(len(index["papers"]), 4)
            self.assertEqual(index["screening_library"], library)
            self.assertEqual(
                len(
                    [
                        name
                        for name in files
                        if name.startswith("wiki/") and name.endswith(".md")
                    ]
                ),
                4,
            )
            with self.assertRaisesRegex(
                SessionApiError, "stage2-canonical-records-1.2-consumer-unconnected"
            ):
                _verified_inputs(
                    context[2],
                    dict(
                        deliverable_dir=root, manifest_sha256=saved["manifest_sha256"]
                    ),
                )
            self.assertEqual(fixture["ledger"].events(), events)
            case.runner.assert_not_called()

    def test_observed_source_cannot_be_hidden_as_discovery_only(self):
        with saved_stage1_case() as (case, fixture):
            _, candidate = discovery_candidates(case, fixture)
            ledger = fixture["ledger"]
            ledger.start_source(
                work_id=candidate["work_id"],
                version_id=candidate["discoveries"][-1]["version_id"],
                source_uri="https://example.org/pending",
                tool="fixture",
                request={},
                actor="fixture",
                reason="Saved pending intent only.",
            )
            fixture["checkpoint"] = ledger.checkpoint()
            events = ledger.events()
            with self.assertRaisesRegex(
                SessionApiError, "saved-reading-current-record-required"
            ):
                case.produce(fixture)
            self.assertEqual(ledger.events(), events)
            self.assertEqual(list(case.fixture_root.glob("stage1-records-*")), [])
            case.runner.assert_not_called()

    def test_library_changes_refuse_registration_before_any_saved_action(self):
        with saved_stage1_case() as (case, fixture):
            discovery_candidates(case, fixture)
            offer, context, path = produced(case, fixture)
            records = read_json(path)
            wrong = deepcopy(records["screening_library"])
            wrong["binding"]["project_ref"] = "another-project"
            with self.assertRaisesRegex(
                SessionApiError, "stage1-screening-library-binding-differs"
            ):
                _records_match(
                    records, fixture["ledger"], path.parent, screening_library=wrong
                )
            raw_file = next(p for p in records["screening_artifacts"])
            target = path.parent / raw_file["artifact_path"]
            original = target.read_bytes()
            target.write_bytes(original + b"tampered")
            with self.assertRaisesRegex(ValueError, "screening library:.*hash differs"):
                _records_match(
                    records,
                    fixture["ledger"],
                    path.parent,
                    screening_library=_screening_library(context),
                )
            target.write_bytes(original)
            self.assertEqual(sha(target.read_bytes()), raw_file["source_ref"]["sha256"])
            case.runner.assert_not_called()


if __name__ == "__main__":
    unittest.main()
