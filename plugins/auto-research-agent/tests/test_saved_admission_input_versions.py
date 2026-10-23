"""Strict saved-input identities; schema/projection checks, no admission or research."""

from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cli"))

from research_workspace.saved_admission import check_handoff, check_snapshot
from research_workspace.host_replay import HostReplay
from stage1_deliverable.common import DeliverableError, sha
from stage1_ledger.handoff import DIMENSIONS

REF = {"path": "package/manifest.json", "sha256": "a" * 64, "bytes": 1}
VALID = ("20261009-A03", "1", "版本二", 1, 9)
INVALID = (1.0, 1.5, 0, -1, True, False, None, "", [], {})


def snapshot(version):
    return {
        "kind": "SavedSourceCandidateSnapshot",
        "schema_version": "1.0.0",
        "admission_id": "synthetic-type-check",
        "recorded_at": "2026-10-23T00:00:00Z",
        "project_id": "synthetic-project",
        "input_version": version,
        "source_mode": "saved-source-current-admission",
        "historical_discovery_events": None,
        "historical_trace_status": "missing",
        "bindings": {
            key: deepcopy(REF)
            for key in (
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
                "work_id": "synthetic-work",
                "version_id": "synthetic-version",
                "source_id": "synthetic-source",
                "raw_source": deepcopy(REF),
                "extracted_text": deepcopy(REF),
                "full_note": deepcopy(REF),
                "acquisition_provenance": deepcopy(REF),
                "original_acquired_at": None,
            }
        ],
    }


def handoff(version):
    return {
        "kind": "Stage1Handoff",
        "schema_version": "2.0.0",
        "source_mode": "saved-source-current-admission",
        "source_run_id": "synthetic-type-check",
        "source_state_sha256": "a" * 64,
        "snapshot_ref": deepcopy(REF),
        "acceptance_ref": None,
        "project_id": "synthetic-project",
        "input_version": version,
        "deliverable_manifest_sha256": "a" * 64,
        "brief_sha256": "b" * 64,
        "papers": [
            {
                "work_id": "synthetic-work",
                "title": "Synthetic title",
                "listed_version_id": "synthetic-version",
                "reviewed_version_id": "synthetic-version",
            }
        ],
        "comparison_dimensions": list(DIMENSIONS),
        "resources_preserved": {
            key: {"used": 0, "limit": 0} for key in ("queries", "acquisitions")
        },
        "limitations": ["Synthetic schema only", "No Core or scientific acceptance"],
        "stage1_gate": {
            "status": "blocked",
            "quantity_decision": "stop-count-target-and-covered",
            "remaining": ["not admitted"],
        },
        "eligible_for_stage2": False,
        "stage1_completed": False,
        "stage2": {"status": "not-started", "execution_authorized": False},
    }


class SavedAdmissionInputVersionTests(unittest.TestCase):
    def test_snapshot_keeps_strings_and_strict_positive_integers(self):
        for value in VALID:
            with self.subTest(value=value):
                check_snapshot(snapshot(value))
        for value in INVALID:
            with self.subTest(value=value), self.assertRaises(ValueError):
                check_snapshot(snapshot(value))

    def test_handoff_keeps_strings_and_strict_positive_integers(self):
        for value in VALID:
            with self.subTest(value=value):
                check_handoff(handoff(value))
        for value in INVALID:
            with self.subTest(value=value), self.assertRaises(ValueError):
                check_handoff(handoff(value))

    def test_rebound_context_refuses_two_matching_floats(self):
        # Isolate the post-load identity guard. This fabricated context is never
        # passed to admission/import and is not a trusted replay observation.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            for value in (*VALID, 1.0, True):
                with self.subTest(value=value):
                    raw = json.dumps(snapshot(value), ensure_ascii=False).encode()
                    (root / "snapshot.json").write_bytes(raw)
                    ref = {
                        "path": "snapshot.json",
                        "sha256": sha(raw),
                        "bytes": len(raw),
                    }
                    context = object.__new__(HostReplay)
                    context._root = root / "package"
                    context._receipt = {
                        "snapshot_ref": ref,
                        "project_id": "synthetic-project",
                        "input_version": value,
                        "canonical_manifest_sha256": "a" * 64,
                    }
                    if type(value) is float or type(value) is bool:
                        with self.assertRaisesRegex(DeliverableError, "input version"):
                            context.check_snapshot(root, ref)
                    else:
                        context.check_snapshot(root, ref)


if __name__ == "__main__":
    unittest.main()
