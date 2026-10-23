"""Saved-cohort triage must preserve decisions, unknowns and typed identity."""

from contextlib import redirect_stdout
from copy import deepcopy
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cli"))

from research_workspace.pending_backlog import inspect_backlog, main
from stage1_deliverable.common import DeliverableError, canonical, sha


def fixture(urls=None, papers=None):
    urls = urls or ["https://doi.org/10.1234/example"]
    papers = papers or [
        {
            "work_id": "synthetic-work",
            "version_id": "saved-version-1",
            "input_version": "input-1",
            "title": "Synthetic title",
            "url": "https://example.org/paper",
            "doi": "10.1234/example",
        }
    ]
    capture, bounds = "", []
    for number, url in enumerate(urls):
        title = f"Synthetic source {number}"
        header = f"{title} {url}\n"
        start = len(capture) + len(header)
        line = len(capture.splitlines()) + 1
        quote = f"Saved synthetic research excerpt {number}."
        capture += header + quote + "\n"
        bounds.append((title, start, start + len(quote), quote, line))
    capture_hash = sha(capture.encode())
    observations, rows = [], []
    for number, (url, (title, start, end, quote, line)) in enumerate(zip(urls, bounds)):
        original = {
            "observation_ref": f"batch:header-{number}",
            "batch_ref": "batch",
            "title_observed": title,
            "url_observed": url,
            "raw_header_line": line,
            "saved_receipt_ref": {"sha256": capture_hash},
        }
        observations.append(original)
        rows.append(
            {
                "observation_ref": original["observation_ref"],
                "original_observation_sha256": sha(canonical(original)),
                "title_observed": title,
                "url_observed": url,
                "decision": "pending",
                "rationale": "Synthetic saved excerpt needs an identity and complete-source review.",
                "reason_code": "source-review-needed",
                "need_ids": ["synthetic-need"],
                "saved_evidence": {
                    "batch_ref": "batch",
                    "source_sha256": capture_hash,
                    "start": start,
                    "end": end,
                    "quote": quote,
                },
            }
        )
    observed_raw = canonical(observations).decode()
    value = {
        "kind": "NewSavedCandidateScreening",
        "scope": "saved-observations-only",
        "not_historical": True,
        "input_canonical_sha256": "a" * 64,
        "reviewed_at": "2026-01-01T00:00:00+00:00",
        "reviewer": {
            "type": "ai",
            "identity": "synthetic-fixture",
            "authenticated": False,
        },
        "observations_ref": {
            "path": "observations.json",
            "sha256": sha(observed_raw.encode()),
        },
        "captures": {"batch": {"path": "capture.txt", "sha256": capture_hash}},
        "rows": rows,
    }
    decision_raw = canonical(value).decode()
    reference = {
        "path": "decisions.json",
        "source_sha256": sha(decision_raw.encode()),
        "pointer": "",
        "value": value,
        "observations": observations,
    }
    payload = {
        "project_id": "synthetic-project",
        "input_canonical_sha256": "a" * 64,
        "new_candidate_screening": reference,
    }
    artifacts = {
        "capture.txt": capture,
        "observations.json": observed_raw,
        "decisions.json": decision_raw,
    }
    manifest = canonical(
        {"files": {name: sha(text.encode()) for name, text in artifacts.items()}}
    ).decode()
    index = {
        "project_id": "synthetic-project",
        "papers": papers,
        "sources": [],
        "original_record_recovery": {
            "payload": payload,
            "payload_sha256": sha(canonical(payload)),
            "artifacts_utf8": artifacts,
            "manifest_utf8": manifest,
            "manifest_sha256": sha(manifest.encode()),
        },
        "readiness": {
            "formal_progress": {
                "decision": "stop-count-target-and-covered",
                "target": 30,
                "qualified_coverage": True,
            }
        },
        "coverage": [
            {"stop_reason": "Quantity target met; old acquisition budget exhausted."}
        ],
    }
    return index


def inspect(index, **changes):
    raw = canonical(index)
    return inspect_backlog(
        raw,
        expected_index_sha256=sha(raw),
        project_id="synthetic-project",
        input_version="input-1",
        **changes,
    )


class PendingBacklogTests(unittest.TestCase):
    def test_original_refs_without_redundant_hash_use_pinned_manifest(self):
        index = fixture()
        recovery = index["original_record_recovery"]
        ref = recovery["payload"]["new_candidate_screening"]
        value = ref["value"]
        del value["observations_ref"]["sha256"]
        del value["captures"]["batch"]["sha256"]
        raw = canonical(value).decode()
        recovery["artifacts_utf8"]["decisions.json"] = raw
        ref["source_sha256"] = sha(raw.encode())
        manifest = canonical(
            {
                "files": {
                    name: sha(text.encode())
                    for name, text in recovery["artifacts_utf8"].items()
                }
            }
        ).decode()
        recovery["manifest_utf8"] = manifest
        recovery["manifest_sha256"] = sha(manifest.encode())
        recovery["payload_sha256"] = sha(canonical(recovery["payload"]))
        self.assertEqual(inspect(index)["counts"]["local_triage_executed"], 1)

    def test_identifier_match_does_not_certify_version_or_semantics(self):
        index = fixture()
        frozen = canonical(index)
        result = inspect(index)
        self.assertEqual(result["counts"]["saved_work_matches"], 1)
        row = result["rows"][0]
        self.assertEqual(row["status"], "saved-work-match-version-not-certified")
        self.assertEqual(
            row["saved_work_matches"],
            [{"work_id": "synthetic-work", "version_id": "saved-version-1"}],
        )
        self.assertIsNone(row["academic_decision"])
        self.assertIsNone(row["researcher_decision_required"])
        self.assertFalse(row["complete_source_read"])
        self.assertEqual(canonical(index), frozen)

    def test_external_hash_and_exact_input_type_are_required(self):
        raw = canonical(fixture())
        for pin, version in [("0" * 64, "input-1"), (sha(raw), 1), (sha(raw), True)]:
            with (
                self.subTest(pin=pin, version=version),
                self.assertRaises(DeliverableError),
            ):
                inspect_backlog(
                    raw,
                    expected_index_sha256=pin,
                    project_id="synthetic-project",
                    input_version=version,
                )
        with self.assertRaises(DeliverableError):
            inspect_backlog(
                raw,
                expected_index_sha256=sha(raw),
                project_id="wrong-project",
                input_version="input-1",
            )

    def test_rehashed_outer_index_cannot_hide_changed_capture_or_projection(self):
        for field in ("capture", "decision", "payload"):
            index = fixture()
            recovery = index["original_record_recovery"]
            if field == "capture":
                recovery["artifacts_utf8"]["capture.txt"] += "changed"
            elif field == "decision":
                recovery["payload"]["new_candidate_screening"]["value"]["rows"][0][
                    "rationale"
                ] = "Changed rationale does not match original pinned decision bytes."
                recovery["payload_sha256"] = sha(canonical(recovery["payload"]))
            else:
                recovery["payload"]["project_id"] = "other-project"
            with self.subTest(field=field), self.assertRaises(DeliverableError):
                inspect(index)

    def test_conflicting_saved_identifier_never_selects_a_work(self):
        index = fixture()
        other = deepcopy(index["papers"][0])
        other["work_id"] = "different-work"
        index["papers"].append(other)
        result = inspect(index)
        self.assertEqual(result["rows"][0]["status"], "identity-conflict")
        self.assertEqual(len(result["rows"][0]["saved_work_matches"]), 2)
        self.assertEqual(result["counts"]["academic_automatically_resolved"], 0)

    def test_arxiv_cross_version_matches_work_only(self):
        index = fixture(["https://arxiv.org/pdf/2401.12345v1.pdf"])
        index["papers"][0].update(url="https://arxiv.org/html/2401.12345v2", doi=None)
        result = inspect(index)
        self.assertEqual(result["counts"]["saved_work_matches"], 1)
        self.assertEqual(
            result["rows"][0]["identifier_matches"],
            [{"kind": "arxiv-work", "value": "2401.12345"}],
        )
        self.assertFalse(result["rows"][0]["complete_source_read"])

    def test_similar_title_and_unrelated_or_credential_url_do_not_match(self):
        index = fixture(
            [
                "https://elsewhere.org/unrelated",
                "https://name:secret@doi.org/10.1234/example",
            ]
        )
        result = inspect(index)
        self.assertEqual(result["counts"]["saved_work_matches"], 0)
        self.assertEqual(result["counts"]["original_pending"], 2)
        self.assertEqual(result["researcher_questions"], [])

    def test_pmid_and_pmcid_are_exact_and_distinct(self):
        index = fixture(
            [
                "https://pubmed.ncbi.nlm.nih.gov/12345/",
                "https://pmc.ncbi.nlm.nih.gov/articles/PMC12345/",
            ]
        )
        index["papers"][0].update(url="https://pubmed.ncbi.nlm.nih.gov/12345", doi=None)
        result = inspect(index)
        self.assertEqual(
            [bool(row["saved_work_matches"]) for row in result["rows"]], [True, False]
        )

    def test_repeated_observations_remain_distinct_and_pending(self):
        index = fixture(
            [
                "https://example.org/paper",
                "https://example.org/paper?utm_source=fixture",
            ]
        )
        result = inspect(index)
        self.assertEqual(len(result["rows"]), 2)
        self.assertEqual(
            result["rows"][1]["same_url_prior_observation"], "batch:header-0"
        )
        self.assertEqual(result["rows"][1]["status"], "repeated-observation")
        self.assertEqual(result["counts"]["academic_automatically_resolved"], 0)
        self.assertTrue(
            all(row["original_decision"] == "pending" for row in result["rows"])
        )

    def test_quantity_budget_stop_does_not_imply_marginal_sufficiency(self):
        index = fixture()
        result = inspect(index)
        self.assertEqual(
            result["recorded_stop"]["original_formal_progress"],
            index["readiness"]["formal_progress"],
        )
        self.assertIsNone(result["recorded_stop"]["new_marginal_yield"])
        self.assertFalse(result["recorded_stop"]["automatic_steps_exhausted"])
        self.assertFalse(result["recorded_stop"]["sufficient_stop_recomputed"])
        self.assertFalse(result["authority"]["eligible_for_stage2"])

    def test_duplicate_nonfinite_or_oversize_json_is_rejected(self):
        for raw in [b'{"x":1,"x":2}', b'{"x":NaN}', b" " * (32 * 1024 * 1024 + 1)]:
            with self.subTest(size=len(raw)), self.assertRaises(DeliverableError):
                inspect_backlog(
                    raw,
                    expected_index_sha256=sha(raw),
                    project_id="synthetic-project",
                    input_version="input-1",
                )

    def test_cli_writes_exclusive_private_companion_and_keeps_input(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "index.json"
            output = root / "backlog.json"
            raw = canonical(fixture())
            source.write_bytes(raw)
            argv = [
                "--index",
                str(source),
                "--expected-index-sha256",
                sha(raw),
                "--project-id",
                "synthetic-project",
                "--input-version-json",
                '"input-1"',
                "--output",
                str(output),
            ]
            with redirect_stdout(io.StringIO()):
                main(argv)
            self.assertEqual(source.read_bytes(), raw)
            saved = output.read_bytes()
            self.assertEqual(
                json.loads(saved)["calls"], {"model": 0, "query": 0, "acquisition": 0}
            )
            with self.assertRaises(FileExistsError), redirect_stdout(io.StringIO()):
                main(argv)
            self.assertEqual(output.read_bytes(), saved)
            (root / ".git").mkdir()
            argv[-1] = str(root / "unsafe.json")
            with self.assertRaises(DeliverableError), redirect_stdout(io.StringIO()):
                main(argv)
            self.assertFalse((root / "unsafe.json").exists())


if __name__ == "__main__":
    unittest.main()
