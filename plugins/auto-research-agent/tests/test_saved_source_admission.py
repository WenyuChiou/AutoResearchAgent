"""Saved-source admission cannot inherit the legacy discovery authority."""

import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cli"))

from stage1_ledger.contracts import validator
from research_workspace.saved_admission import (
    check_snapshot,
    reconcile_rows,
    resource_totals,
    _check_acceptance,
    CORE_CHECKS,
    HTML_ACTIONS,
    PRODUCER_FILES,
    SCHEMA,
    check_note_binding,
    check_acquisition_binding,
    REQUIRED_CI_JOBS,
    inspect_saved_admission,
)


def snapshot_fixture(count=30):
    ref = {"path": "synthetic.json", "sha256": "a" * 64, "bytes": 2}
    return {
        "kind": "SavedSourceCandidateSnapshot",
        "schema_version": "1.0.0",
        "admission_id": "synthetic-current-admission",
        "recorded_at": "2026-10-10T00:00:00Z",
        "project_id": "synthetic",
        "input_version": "input1",
        "source_mode": "saved-source-current-admission",
        "historical_discovery_events": None,
        "historical_trace_status": "missing",
        "bindings": {
            name: copy.deepcopy(ref)
            for name in (
                "original_request",
                "brief",
                "resources",
                "deliverable",
                "view",
                "companion",
            )
        },
        "rows": [
            {
                "work_id": f"work{i}",
                "version_id": f"version{i}",
                "source_id": f"source{i}",
                "raw_source": copy.deepcopy(ref),
                "extracted_text": copy.deepcopy(ref),
                "full_note": copy.deepcopy(ref),
                "acquisition_provenance": copy.deepcopy(ref),
                "original_acquired_at": None,
            }
            for i in range(count)
        ],
    }


class SavedSourceAdmissionTests(unittest.TestCase):
    def test_identical_bytes_cannot_substitute_an_unqualified_source_id(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()

            def save(name, value):
                raw = json.dumps(value).encode()
                (root / name).write_bytes(raw)
                return {
                    "path": name,
                    "sha256": hashlib.sha256(raw).hexdigest(),
                    "bytes": len(raw),
                }

            snapshot = snapshot_fixture(count=1)
            row = snapshot["rows"][0]
            row["source_id"] = "unqualified-source"
            row["raw_source"] = row["extracted_text"] = row["full_note"] = save(
                "source-note.json", {"synthetic": "Complete fixture note"}
            )
            row["acquisition_provenance"] = save(
                "acquisition.json",
                {
                    "raw_sha256": row["raw_source"]["sha256"],
                    "original_acquired_at": None,
                },
            )
            proof = save("proof.json", {"synthetic_only": True})
            brief = {
                "kind": "ResearchBrief",
                "schema_version": "1.0.0",
                "project_id": "synthetic",
                "input_version": "input1",
                "original_description": "Synthetic source binding fixture.",
                "needs": [
                    {"need_id": "need1", "question": "What does this fixture bind?"}
                ],
                "scope_fields": [
                    {
                        "field": "geography",
                        "material": False,
                        "reason": "Controlled fixture.",
                    }
                ],
                "suggestions": [],
                "decisions": [],
                "previous_sha256": None,
            }
            resources = {
                "project_id": "synthetic",
                "input_version": "input1",
                "no_resource_reset": True,
                "current_round_used": {
                    "queries": 1,
                    "full_source_acquisition_attempts": 1,
                },
                "previous_cumulative_used": {
                    "queries": 0,
                    "full_source_acquisition_attempts": 0,
                },
                "total_authorized_limits": {
                    "queries": 1,
                    "full_source_acquisition_attempts": 1,
                },
            }
            paper = {
                "work_id": row["work_id"],
                "version_id": row["version_id"],
                "title": "Synthetic fixture",
                "source_ids": ["qualified-source", "unqualified-source"],
                "fresh_note": {
                    "companion_binding": {
                        "companion_manifest_sha256": proof["sha256"],
                        "sha256": row["full_note"]["sha256"],
                        "bytes": row["full_note"]["bytes"],
                    },
                    "source_qualification": {
                        "source_id": "qualified-source",
                        "raw_sha256": row["raw_source"]["sha256"],
                        "text_sha256": row["extracted_text"]["sha256"],
                    },
                },
            }
            snapshot["bindings"] = {
                "original_request": proof,
                "brief": save("brief.json", brief),
                "resources": save("resources.json", resources),
                "companion": proof,
                "view": proof,
                "deliverable": save(
                    "manifest.json", {"canonical_records": {"papers": [paper]}}
                ),
            }
            index = {
                "papers": [paper],
                "sources": [
                    {
                        "source_id": source_id,
                        "work_id": row["work_id"],
                        "version_id": row["version_id"],
                        "attempts": [
                            {"sha256": row["acquisition_provenance"]["sha256"]}
                        ],
                    }
                    for source_id in ("qualified-source", "unqualified-source")
                ],
            }
            progress = {
                "decision": "stop-count-target-and-covered",
                "target": 1,
                "note_pending_versions": 0,
                "formally_usable_work_ids": [row["work_id"]],
            }
            ref = save("snapshot.json", snapshot)
            # Isolate upstream validators already covered separately; execute every
            # new admission binding with real fixture files and identical source bytes.
            with (
                patch(
                    "research_workspace.saved_admission._view",
                    return_value=({}, index, {}),
                ),
                patch(
                    "research_workspace.saved_admission.derive_formal_readiness",
                    return_value=progress,
                ),
                patch(
                    "research_workspace.saved_admission.deliverable_package.validate"
                ),
            ):
                with self.assertRaisesRegex(ValueError, "qualification source"):
                    inspect_saved_admission(root, ref)

    def test_original_time_is_bound_without_inventing_unknown_acquisition(self):
        row = snapshot_fixture()["rows"][0]
        source = {"attempts": [{"sha256": row["acquisition_provenance"]["sha256"]}]}
        provenance = {
            "raw_sha256": row["raw_source"]["sha256"],
            "original_acquired_at": None,
        }
        check_acquisition_binding(row, source, provenance, "2026-10-10T00:00:00Z")
        for field, value in (
            ("raw_sha256", "0" * 64),
            ("original_acquired_at", "2026-10-09T00:00:00Z"),
        ):
            changed = dict(provenance, **{field: value})
            with self.assertRaises(ValueError):
                check_acquisition_binding(row, source, changed, "2026-10-10T00:00:00Z")
        row["original_acquired_at"] = provenance["original_acquired_at"] = (
            "2026-10-11T00:00:00Z"
        )
        with self.assertRaises(ValueError):
            check_acquisition_binding(row, source, provenance, "2026-10-10T00:00:00Z")

    def test_notes_bind_through_validated_companion_not_prose_schema(self):
        row = snapshot_fixture()["rows"][0]
        paper = {
            "work_id": row["work_id"],
            "version_id": row["version_id"],
            "fresh_note": {
                "companion_binding": {
                    "sha256": row["full_note"]["sha256"],
                    "bytes": row["full_note"]["bytes"],
                    "companion_manifest_sha256": "b" * 64,
                }
            },
        }
        check_note_binding(row, paper, "b" * 64)
        for field, value in (
            ("sha256", "0" * 64),
            ("bytes", 999),
            ("companion_manifest_sha256", "0" * 64),
        ):
            changed = copy.deepcopy(paper)
            changed["fresh_note"]["companion_binding"][field] = value
            with self.assertRaises(ValueError):
                check_note_binding(row, changed, "b" * 64)

    def test_new_current_snapshot_is_valid_and_legacy_rejects_it(self):
        snapshot = snapshot_fixture()
        check_snapshot(snapshot)
        self.assertTrue(list(validator("CandidateSnapshot").iter_errors(snapshot)))

    def test_fabricated_history_or_http_success_is_rejected(self):
        for key, value in (
            ("historical_discovery_events", []),
            ("http_status", 200),
            ("eligible_for_stage2", True),
            ("source_mode", "offline-import"),
        ):
            with self.subTest(key=key):
                snapshot = snapshot_fixture()
                snapshot[key] = value
                with self.assertRaises(ValueError):
                    check_snapshot(snapshot)

    def test_reconciliation_binds_each_identity_and_refuses_duplicates(self):
        snapshot = snapshot_fixture()
        papers = [
            {
                "work_id": row["work_id"],
                "version_id": row["version_id"],
                "source_ids": [row["source_id"]],
            }
            for row in snapshot["rows"]
        ]
        self.assertEqual(
            reconcile_rows(snapshot["rows"], papers, 30),
            set(p["work_id"] for p in papers),
        )
        for mutation in (
            "short",
            "work",
            "version",
            "source",
            "duplicate-work",
            "duplicate-source",
        ):
            with self.subTest(mutation=mutation):
                rows = copy.deepcopy(snapshot["rows"])
                if mutation == "short":
                    rows.pop()
                elif mutation.startswith("duplicate"):
                    field = "work_id" if mutation.endswith("work") else "source_id"
                    rows[-1][field] = rows[0][field]
                else:
                    rows[-1][mutation + "_id"] = "wrong"
                with self.assertRaises(ValueError):
                    reconcile_rows(rows, papers, 30)

    def test_resources_preserve_cumulative_use_and_reject_reset(self):
        control = {
            "no_resource_reset": True,
            "current_round_used": {
                "queries": 24,
                "full_source_acquisition_attempts": 32,
            },
            "previous_cumulative_used": {
                "queries": 48,
                "full_source_acquisition_attempts": 32,
            },
            "total_authorized_limits": {
                "queries": 72,
                "full_source_acquisition_attempts": 64,
            },
        }
        self.assertEqual(
            resource_totals(control),
            {
                "queries": {"used": 72, "limit": 72},
                "acquisitions": {"used": 64, "limit": 64},
            },
        )
        for value in (False, 0, "true"):
            changed = copy.deepcopy(control)
            changed["no_resource_reset"] = value
            with self.assertRaises(ValueError):
                resource_totals(changed)
        control["previous_cumulative_used"]["queries"] = True
        with self.assertRaises(ValueError):
            resource_totals(control)


class ExternalAcceptanceBindingTests(unittest.TestCase):
    """Controlled receipt fixtures test binding, not real Core or browser authority."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.snapshot = snapshot_fixture()
        self.snapshot["bindings"]["view"]["path"] = "view/view-manifest.json"
        self.proof = self.save("proof.bin", b"synthetic observed evidence")
        self.html_ref = self.save("view/index.html", b"<html>synthetic fixture</html>")
        self.bib = self.save(
            "view/literature/included-references.bib",
            b"@article{synthetic, title={Synthetic fixture}}",
        )
        self.download = self.save(
            "download.bib", b"@article{synthetic, title={Synthetic fixture}}"
        )
        self.view = {
            "files": {
                "index.html": self.html_ref["sha256"],
                "literature/included-references.bib": self.bib["sha256"],
            }
        }
        self.html = {
            "kind": "ActualHtmlOperationReceipt",
            "schema_version": "1.0.0",
            "snapshot_sha256": "a" * 64,
            "html_sha256": self.html_ref["sha256"],
            "operations": [
                {
                    "action": action,
                    "status": "passed",
                    "tool_action_ref": "synthetic-only-action",
                    "started_at": "2026-10-10T00:00:00Z",
                    "ended_at": "2026-10-10T00:00:01Z",
                    "evidence": [self.proof],
                }
                for action in HTML_ACTIONS
            ],
            "bibtex_download": self.download,
            "expected_bibtex": self.bib,
        }
        self.acceptance = {
            "kind": "SavedSourceAdmissionAcceptance",
            "schema_version": "1.0.0",
            "snapshot_sha256": "a" * 64,
            "project_id": "synthetic",
            "input_version": "input1",
            "contract_sha256": hashlib.sha256(SCHEMA.read_bytes()).hexdigest(),
            "producer": {
                "delivered_commit": "d" * 40,
                "reviewed_head": "c" * 40,
                "merge_parents": ["c" * 40, "b" * 40],
                "merge_tree": "e" * 40,
                "sources": {
                    name: hashlib.sha256(
                        (SCHEMA.parent.parent / name).read_bytes()
                    ).hexdigest()
                    for name in PRODUCER_FILES
                },
                "ci": [
                    {
                        "name": name,
                        "phase": phase,
                        "head_sha": "c" * 40 if phase == "pr" else "d" * 40,
                        "run_id": 1,
                        "job_id": i + 1,
                        "conclusion": "success",
                    }
                    for i, (phase, name) in enumerate(
                        [("pr", name) for name in sorted(REQUIRED_CI_JOBS)]
                        + [
                            ("post-main", name)
                            for name in sorted(REQUIRED_CI_JOBS - {"pr-contract"})
                        ]
                    )
                ],
            },
            "checks": {},
            "html": self.save("html-receipt.json", self.html),
        }
        for category in CORE_CHECKS:
            review = {
                "kind": "SavedSourceAdmissionReview",
                "category": category,
                "snapshot_sha256": "a" * 64,
                "project_id": "synthetic",
                "input_version": "input1",
                "scope": "saved-source-current-admission",
                "validator": self.proof,
                "rubric": self.proof,
                "results": [
                    {
                        "check_id": "synthetic",
                        "status": "passed",
                        "locator": "synthetic:1",
                        "reason": "Synthetic binding fixture only, no real Core verdict.",
                    }
                ],
                "outcome": "accepted",
                "observations": "Synthetic binding fixture, no real acceptance.",
                "evidence": [self.proof],
            }
            self.acceptance["checks"][category] = self.save(category + ".json", review)

    def save(self, name, value):
        raw = (
            value
            if isinstance(value, bytes)
            else json.dumps(value, sort_keys=True).encode("utf-8")
        )
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        return {
            "path": name,
            "sha256": hashlib.sha256(raw).hexdigest(),
            "bytes": len(raw),
        }

    def inspect(self, trusted=None):
        ref = self.save("acceptance.json", self.acceptance)
        return _check_acceptance(
            self.root,
            ref,
            ref["sha256"] if trusted is None else trusted,
            "a" * 64,
            self.snapshot,
            self.view,
        )

    def test_complete_bound_synthetic_receipt_and_independent_trust_pin(self):
        self.assertEqual(self.inspect(), self.acceptance)
        with self.assertRaisesRegex(ValueError, "independent external hash"):
            self.inspect(trusted="0" * 64)

    def test_stale_identity_runtime_failed_ci_and_missing_review_reject(self):
        baseline = copy.deepcopy(self.acceptance)
        for mutation in (
            "snapshot_sha256",
            "project_id",
            "input_version",
            "contract_sha256",
            "runtime",
            "failed-ci",
            "missing-review",
            "missing-post-main",
            "wrong-required-job",
            "undelivered-producer",
        ):
            with self.subTest(mutation=mutation):
                self.acceptance = copy.deepcopy(baseline)
                if mutation == "runtime":
                    self.acceptance["producer"]["sources"][PRODUCER_FILES[0]] = "0" * 64
                elif mutation == "failed-ci":
                    self.acceptance["producer"]["ci"][0]["conclusion"] = "failure"
                elif mutation == "missing-review":
                    self.acceptance["checks"].pop(CORE_CHECKS[0])
                elif mutation == "missing-post-main":
                    self.acceptance["producer"]["ci"] = self.acceptance["producer"][
                        "ci"
                    ][:4]
                elif mutation == "wrong-required-job":
                    self.acceptance["producer"]["ci"][0]["name"] = "unrelated-success"
                elif mutation == "undelivered-producer":
                    self.acceptance["producer"]["merge_parents"] = ["b" * 40, "a" * 40]
                else:
                    self.acceptance[mutation] = "wrong"
                with self.assertRaises(ValueError):
                    self.inspect()

    def test_missing_stale_unobserved_or_failed_html_reject(self):
        baseline = copy.deepcopy(self.html)
        for mutation in ("missing", "stale", "failed", "unobserved", "reversed-time"):
            with self.subTest(mutation=mutation):
                self.html = copy.deepcopy(baseline)
                if mutation == "missing":
                    self.html["operations"].pop()
                elif mutation == "stale":
                    self.html["html_sha256"] = "0" * 64
                elif mutation == "failed":
                    self.html["operations"][0]["status"] = "policy-blocked"
                elif mutation == "unobserved":
                    self.html["operations"][0]["tool_action_ref"] = ""
                else:
                    self.html["operations"][0]["ended_at"] = "2026-10-09T00:00:00Z"
                self.acceptance["html"] = self.save("html-receipt.json", self.html)
                with self.assertRaises(ValueError):
                    self.inspect()

    def test_changed_download_and_non_view_bibliography_reject(self):
        self.html["bibtex_download"] = self.save(
            "download.bib", b"changed selected set"
        )
        self.acceptance["html"] = self.save("html-receipt.json", self.html)
        with self.assertRaisesRegex(ValueError, "BibTeX download differs"):
            self.inspect()
        self.html["bibtex_download"] = self.bib
        self.html["expected_bibtex"] = self.save(
            "view/unlisted.bib", b"changed selected set"
        )
        self.acceptance["html"] = self.save("html-receipt.json", self.html)
        with self.assertRaisesRegex(ValueError, "not in validated view"):
            self.inspect()


if __name__ == "__main__":
    unittest.main()
