"""Stage 1 deliverables enter Stage 2 without losing source provenance."""

import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cli"))

from stage1_deliverable.common import DeliverableError, sha
from stage1_ledger.handoff import CONTRACT, DIMENSIONS
from stage2_common import (
    Stage2Error,
    canonical_hash,
    stage1_projection_hash,
    validate_packet,
)
from stage2_check import initialize_run, inspect_run
from stage2_ideation import build_research_task
from stage2_workflow import (
    add_snapshot,
    build_stage2_seed,
    initialize_workflow,
    inspect_workflow,
)


def _artifact(index):
    return {
        "kind": "ArtifactRef",
        "schema_version": "1.0.0",
        "artifact_id": f"artifact-{index}",
        "artifact_type": "checkpoint-output",
        "path": f"artifacts/{index}.json",
        "sha256": f"{index}" * 64,
        "producer": "synthetic-stage1",
        "created_at": "2026-09-29T00:00:00Z",
    }


class Stage1Stage2HandoffTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="stage1-stage2-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.deliverable = self.root / "stage1-deliverable"
        self.deliverable.mkdir()
        source_text = (
            "Synthetic households alter consumption under a declared scenario."
        )
        self.records = {
            "kind": "Stage1ResearchRecords",
            "schema_version": "1.0.0",
            "topic": "Synthetic literature task",
            "as_of": "2026-09-29T00:00:00+00:00",
            "papers": [
                {
                    "work_id": "work1",
                    "version_id": "v1",
                    "title": "Synthetic household research",
                    "authors": ["Synthetic Author"],
                    "year": 2024,
                    "venue": "Synthetic venue",
                    "doi": None,
                    "url": "https://example.org/study",
                    "evidence_level": "full-text",
                    "source_ids": ["src1"],
                    "classification": {
                        "topic_cluster": "Synthetic aging and consumption",
                        "method": "Synthetic controlled study",
                        "geography": "Unrestricted synthetic geography",
                        "population": "Synthetic households",
                        "data_type": "Synthetic text",
                        "domain": "Household consumption",
                    },
                    "roles": [
                        {
                            "role": "topic-core",
                            "reason": "The synthetic study directly covers the fixture topic.",
                            "claim_ids": ["claim1"],
                        }
                    ],
                    "findings": {
                        "question": "How does the scenario alter consumption?",
                        "data": "Synthetic household statements.",
                        "method": "Controlled illustrative comparison.",
                        "main_findings": "Consumption changes under the scenario.",
                        "limitations": "This is only a synthetic fixture.",
                        "relevance": "It exercises the Stage 1 to Stage 2 bridge.",
                        "transferability": "Scientific conclusions are not transferable.",
                    },
                    "claim_ids": ["claim1"],
                }
            ],
            "sources": [
                {
                    "source_id": "src1",
                    "work_id": "work1",
                    "version_id": "v1",
                    "result_path": "source/source-fetch-result.json",
                    "result_sha256": "c" * 64,
                    "access_note": "Synthetic source for the bridge contract.",
                }
            ],
            "claims": [
                {
                    "claim_id": "claim1",
                    "work_id": "work1",
                    "version_id": "v1",
                    "text": "Synthetic illustrative claim.",
                    "source_id": "src1",
                    "relation": "unverified",
                    "evidence_level": "full-text",
                    "locator": "characters 0:20",
                    "start": 0,
                    "end": 20,
                    "quote": source_text[:20],
                }
            ],
            "screening": [],
            "coverage": [
                {
                    "need_id": "need1",
                    "description": "Synthetic need",
                    "work_ids": ["work1"],
                    "recent_sweep": "completed",
                    "closest_work_check": "completed",
                    "unresolved": "External validity remains unknown",
                    "stop_decision": "stop",
                    "reason": "The controlled input is sufficient for a bridge test.",
                }
            ],
        }
        self.source_text = source_text.encode("utf-8")
        self.source_result = {
            "status": "available",
            "evidence_level": "full-text",
            "retrieved_at": "2026-09-29T00:00:00Z",
            "source_url": "https://example.org/study",
            "final_url": "https://example.org/study",
        }
        (self.deliverable / "provenance_manifest.json").write_text(
            json.dumps(
                {
                    "canonical_records": self.records,
                    "original_input_sha256": "d" * 64,
                }
            ),
            encoding="utf-8",
        )
        self.deliverable_manifest_sha256 = sha(
            (self.deliverable / "provenance_manifest.json").read_bytes()
        )
        self.brief_path = self.root / "brief.json"
        self.resources_path = self.root / "resources.txt"
        self.output = self.root / "stage2-seed"
        self.handoff_path = self.root / "handoff.json"
        self.brief = {
            "kind": "ResearchBrief",
            "schema_version": "1.0.0",
            "original_description": "Study aging and household consumption.",
            "needs": [
                {
                    "need_id": "consumption",
                    "question": "How do aging and household consumption interact?",
                }
            ],
            "scope_fields": [
                {
                    "field": "geography",
                    "material": False,
                    "reason": "This controlled fixture remains broad.",
                }
            ],
            "suggestions": [],
            "decisions": [],
            "previous_sha256": None,
        }
        self.brief_path.write_text(json.dumps(self.brief), encoding="utf-8")
        self.resources_path.write_text(
            "Use public sources and a bounded student compute budget.", encoding="utf-8"
        )
        self.handoff = {
            "kind": "Stage1Handoff",
            "schema_version": "1.0.0",
            "source_run_id": "stage1-synthetic",
            "source_state_sha256": "a" * 64,
            "source_mode": "offline-import",
            "input_refs": [_artifact(1), _artifact(2), _artifact(3)],
            "reuse_contract": CONTRACT,
            "input_format": "manual-paper-list",
            "comparison_dimensions": DIMENSIONS,
            "papers": [
                {
                    "work_id": "work1",
                    "candidate_event_id": "e000001",
                    "decision_event_id": "e000002",
                    "title": self.records["papers"][0]["title"],
                    "identifier": "work1",
                    "listed_version_id": "v1",
                    "reviewed_version_id": "v1",
                    "metadata_identity": "unverified",
                    "identity_review": "verified",
                    "source_ref": _artifact(4),
                }
            ],
            "manual_paper_list": '- "Synthetic household research", work1',
            "stage1_gate": {
                "kind": "GateResult",
                "schema_version": "1.0.0",
                "gate_name": "stage1-coverage",
                "outcome": "pass",
                "reasons": ["Synthetic handoff exercises the contract."],
                "blocking_items": [],
                "evidence_refs": [_artifact(1)],
            },
            "eligible_for_stage2": True,
            "stage2": {"status": "not-started", "execution_authorized": False},
        }
        self.write_handoff()

    def write_handoff(self):
        self.handoff_path.write_text(
            json.dumps(self.handoff, ensure_ascii=False), encoding="utf-8"
        )
        return sha(self.handoff_path.read_bytes())

    def build(self):
        with (
            patch(
                "stage2_workflow.import_stage1.deliverable_package.validate",
                return_value={"status": "passed"},
            ),
            patch(
                "stage2_workflow.import_stage1._source_bytes",
                return_value=(self.source_text, self.source_result),
            ),
        ):
            return build_stage2_seed(
                self.deliverable,
                self.deliverable_manifest_sha256,
                self.handoff_path,
                sha(self.handoff_path.read_bytes()),
                self.brief_path,
                self.resources_path,
                self.output,
            )

    def packet(self):
        return json.loads((self.output / "packet.json").read_text(encoding="utf-8"))

    def test_valid_handoff_initializes_stage2_with_bound_input_ref(self):
        receipt = self.build()
        packet = self.packet()
        self.assertEqual(receipt["status"], "ready-for-explicit-stage2-start")
        self.assertFalse(receipt["stage2_execution_authorized"])
        self.assertEqual(packet["schema_version"], "2.0.0")
        self.assertEqual(packet["candidates"], [])
        self.assertEqual(packet["upstream"]["included_work_ids"], ["work1"])
        self.assertEqual(packet["literature"][0]["authors"], ["Synthetic Author"])
        self.assertEqual(packet["literature"][0]["roles"][0]["role"], "topic-core")
        self.assertEqual(
            packet["literature"][0]["findings"]["main_findings"],
            "Consumption changes under the scenario.",
        )
        self.assertIn("has not yet compared", packet["comparison"])
        self.assertEqual(packet["evidence"][0]["evidence_id"], "claim1")
        self.assertEqual(
            packet["evidence"][0]["claim_text"],
            "Synthetic illustrative claim.",
        )
        validate_packet(packet, self.output)

        task = build_research_task(packet, "f" * 64)
        self.assertIn('"literature"', task["prompt"])
        self.assertIn("Synthetic Author", task["prompt"])
        self.assertIn("Consumption changes under the scenario", task["prompt"])

        run = self.root / "stage2-workflow"
        initialize_workflow(
            self.output / "packet.json",
            self.output,
            run,
            {"model": "synthetic"},
            {"budget": "bounded"},
            receipt["packet_sha256"],
        )
        state = inspect_workflow(run)
        refs = state["manifest"]["stage_run"]["input_refs"]
        self.assertEqual(len(refs), 2)
        self.assertEqual(refs[0]["artifact_type"], "stage1-stage2-source-packet")
        self.assertEqual(refs[0]["sha256"], receipt["packet_sha256"])
        self.assertEqual(refs[1]["artifact_type"], "stage1-stage2-stored-packet")
        self.assertEqual(
            refs[1]["sha256"],
            state["latest_snapshot"]["checker"]["manifest"]["stored_packet_sha256"],
        )

    def test_ineligible_or_wrong_version_handoff_fails_closed(self):
        self.handoff["eligible_for_stage2"] = False
        self.write_handoff()
        with self.assertRaisesRegex(Stage2Error, "not-eligible"):
            self.build()
        self.handoff["eligible_for_stage2"] = True
        self.handoff["papers"][0]["reviewed_version_id"] = "v2"
        self.write_handoff()
        with self.assertRaisesRegex(Stage2Error, "paper-binding-mismatch"):
            self.build()

    def test_manifest_and_source_tampering_are_rejected(self):
        with (
            patch(
                "stage2_workflow.import_stage1.deliverable_package.validate",
                side_effect=DeliverableError(
                    "package manifest differs from trusted external SHA-256"
                ),
            ),
            self.assertRaisesRegex(Stage2Error, "trusted external SHA-256"),
        ):
            build_stage2_seed(
                self.deliverable,
                "0" * 64,
                self.handoff_path,
                sha(self.handoff_path.read_bytes()),
                self.brief_path,
                self.resources_path,
                self.output,
            )
        self.build()
        packet = self.packet()
        source_path = self.output / packet["sources"][0]["path"]
        source_path.write_text("changed source", encoding="utf-8")
        with self.assertRaisesRegex(Stage2Error, "source hash mismatch"):
            validate_packet(packet, self.output)

    def test_rehashed_source_and_claim_substitution_breaks_stage1_projection(self):
        self.build()
        packet = self.packet()
        replacement = b"Replacement Stage 1 evidence bytes."
        source = packet["sources"][0]
        (self.output / source["path"]).write_bytes(replacement)
        source["sha256"] = hashlib.sha256(replacement).hexdigest()
        packet["evidence"][0]["quote"] = "Replacement"
        with self.assertRaisesRegex(Stage2Error, "source-projection-mismatch"):
            validate_packet(packet, self.output)

    def test_rehashed_literature_or_claim_rows_break_stage1_projection(self):
        self.build()
        packet = self.packet()
        packet["literature"][0]["title"] = "Substituted title"
        with self.assertRaisesRegex(Stage2Error, "literature-projection-mismatch"):
            validate_packet(packet, self.output)

        packet = self.packet()
        packet["evidence"][0]["claim_text"] = "Substituted claim interpretation."
        with self.assertRaisesRegex(Stage2Error, "evidence-projection-mismatch"):
            validate_packet(packet, self.output)

    def test_v2_init_requires_external_hash_and_rejects_fully_rehashed_substitution(
        self,
    ):
        receipt = self.build()
        with self.assertRaisesRegex(Stage2Error, "expected-packet-sha256-required"):
            initialize_workflow(
                self.output / "packet.json",
                self.output,
                self.root / "missing-external-hash",
                {"model": "synthetic"},
                {"budget": "bounded"},
            )

        packet = self.packet()
        replacement = b"Replacement Stage 1 evidence bytes."
        source = packet["sources"][0]
        (self.output / source["path"]).write_bytes(replacement)
        source["sha256"] = hashlib.sha256(replacement).hexdigest()
        packet["literature"][0]["title"] = "Substituted Stage 1 title"
        packet["evidence"][0]["claim_text"] = "Substituted Stage 1 claim."
        packet["evidence"][0]["quote"] = "Replacement"
        upstream = packet["upstream"]
        upstream["stage1_literature_sha256"] = stage1_projection_hash(
            packet["literature"]
        )
        upstream["stage1_sources_sha256"] = stage1_projection_hash(
            packet["sources"], omit={"path"}
        )
        upstream["stage1_evidence_sha256"] = stage1_projection_hash(packet["evidence"])
        unsigned = {
            key: value for key, value in upstream.items() if key != "binding_sha256"
        }
        upstream["binding_sha256"] = canonical_hash(unsigned)
        validate_packet(packet, self.output)
        substituted = self.root / "fully-rehashed-substitution.json"
        substituted.write_text(json.dumps(packet), encoding="utf-8")
        with self.assertRaisesRegex(Stage2Error, "external-packet-hash-mismatch"):
            initialize_workflow(
                substituted,
                self.output,
                self.root / "substituted-run",
                {"model": "synthetic"},
                {"budget": "bounded"},
                receipt["packet_sha256"],
            )

    def test_rehashed_brief_or_work_set_tampering_is_rejected(self):
        self.build()
        packet = self.packet()
        packet["brief"]["original_description"] = "Changed after Stage 1."
        with self.assertRaisesRegex(Stage2Error, "brief-binding-mismatch"):
            validate_packet(packet, self.output)
        packet = self.packet()
        packet["upstream"]["included_work_ids"] = ["other-work"]
        unsigned = {
            key: value
            for key, value in packet["upstream"].items()
            if key != "binding_sha256"
        }
        packet["upstream"]["binding_sha256"] = canonical_hash(unsigned)
        with self.assertRaisesRegex(Stage2Error, "literature-set-mismatch"):
            validate_packet(packet, self.output)

    def test_stage2_can_append_sources_but_cannot_rewrite_stage1_binding(self):
        receipt = self.build()
        packet = self.packet()
        run = self.root / "stage2-workflow"
        initialize_workflow(
            self.output / "packet.json",
            self.output,
            run,
            {"model": "synthetic"},
            {"budget": "bounded"},
            receipt["packet_sha256"],
        )
        state = inspect_workflow(run)
        extra = b"Later Stage 2 counterevidence."
        (self.output / "sources" / "stage2-extra.txt").write_bytes(extra)
        packet["sources"].append(
            {
                "origin": "stage2",
                "source_id": "stage2-extra",
                "work_id": "stage2-work",
                "version_id": "v1",
                "path": "sources/stage2-extra.txt",
                "sha256": hashlib.sha256(extra).hexdigest(),
                "evidence_level": "full-text",
                "access_status": "stage2-added",
                "retrieved_at": "2026-09-29T01:00:00Z",
                "source_url": "https://example.org/stage2-extra",
                "final_url": "https://example.org/stage2-extra",
                "access_note": "Explicit Stage 2 follow-up source.",
            }
        )
        validate_packet(packet, self.output)
        changed_path = self.root / "appended-packet.json"
        changed_path.write_text(json.dumps(packet), encoding="utf-8")
        add_snapshot(
            run,
            changed_path,
            self.output,
            "Append bounded Stage 2 counterevidence",
            [],
            state["head_sha256"],
        )
        state = inspect_workflow(run)
        self.assertEqual(len(state["latest_snapshot"]["packet"]["sources"]), 2)

        changed = self.packet()
        changed["upstream"]["source_run_id"] = "rewritten-stage1-run"
        unsigned = {
            key: value
            for key, value in changed["upstream"].items()
            if key != "binding_sha256"
        }
        changed["upstream"]["binding_sha256"] = canonical_hash(unsigned)
        changed_path = self.root / "changed-packet.json"
        changed_path.write_text(json.dumps(changed), encoding="utf-8")
        with self.assertRaisesRegex(Stage2Error, "upstream-stage1-binding-rewritten"):
            add_snapshot(
                run,
                changed_path,
                self.output,
                "Attempted upstream rewrite",
                [],
                state["head_sha256"],
            )

    def test_stage2_literature_cannot_reference_missing_source_or_evidence(self):
        self.build()
        packet = self.packet()
        added = json.loads(json.dumps(packet["literature"][0]))
        added.update(
            {
                "origin": "stage2",
                "work_id": "stage2-work",
                "version_id": "v1",
                "source_ids": ["missing-source"],
                "claim_ids": ["missing-evidence"],
                "roles": [],
            }
        )
        packet["literature"].append(added)
        with self.assertRaisesRegex(Stage2Error, "literature-source-binding-mismatch"):
            validate_packet(packet, self.output)

    def test_output_inside_git_is_rejected_before_source_copy(self):
        git_root = self.root / "git-root"
        git_root.mkdir()
        (git_root / ".git").mkdir()
        self.output = git_root / "private-output"
        with self.assertRaisesRegex(Stage2Error, "outside a Git checkout"):
            self.build()
        self.assertFalse(self.output.exists())

    def test_v2_workflow_inside_git_is_rejected_before_source_copy(self):
        receipt = self.build()
        git_root = self.root / "workflow-git-root"
        git_root.mkdir()
        (git_root / ".git").mkdir()
        with self.assertRaisesRegex(Stage2Error, "stage2-private-output-invalid"):
            initialize_workflow(
                self.output / "packet.json",
                self.output,
                git_root / "workflow",
                {"model": "synthetic"},
                {"budget": "bounded"},
                receipt["packet_sha256"],
            )
        self.assertFalse((git_root / "workflow").exists())

    def test_relocated_v2_checker_and_workflow_inside_git_are_rejected(self):
        receipt = self.build()
        checker = self.root / "checker"
        initialize_run(
            self.output / "packet.json",
            self.output,
            checker,
            receipt["packet_sha256"],
        )
        workflow = self.root / "workflow"
        initialize_workflow(
            self.output / "packet.json",
            self.output,
            workflow,
            {"model": "synthetic"},
            {"budget": "bounded"},
            receipt["packet_sha256"],
        )

        git_root = self.root / "relocated-git-root"
        git_root.mkdir()
        (git_root / ".git").mkdir()
        moved_checker = git_root / "checker"
        moved_workflow = git_root / "workflow"
        shutil.copytree(checker, moved_checker)
        shutil.copytree(workflow, moved_workflow)
        with self.assertRaisesRegex(Stage2Error, "stage2-private-output-invalid"):
            inspect_run(moved_checker)
        with self.assertRaisesRegex(Stage2Error, "stage2-private-output-invalid"):
            inspect_workflow(moved_workflow)
        with self.assertRaisesRegex(Stage2Error, "stage2-private-output-invalid"):
            initialize_workflow(
                self.output / "packet.json",
                self.output,
                moved_workflow,
                {"model": "synthetic"},
                {"budget": "bounded"},
                receipt["packet_sha256"],
            )

    def test_mkdir_race_does_not_delete_foreign_output(self):
        original_mkdir = Path.mkdir

        def race(path, *args, **kwargs):
            if path == self.output:
                original_mkdir(path, *args, **kwargs)
                (path / "foreign-marker.txt").write_text("foreign", encoding="utf-8")
                raise FileExistsError(str(path))
            return original_mkdir(path, *args, **kwargs)

        with (
            patch(
                "stage2_workflow.import_stage1.deliverable_package.validate",
                return_value={"status": "passed"},
            ),
            patch("pathlib.Path.mkdir", new=race),
            self.assertRaisesRegex(Stage2Error, "stage1-stage2-import-failed"),
        ):
            build_stage2_seed(
                self.deliverable,
                self.deliverable_manifest_sha256,
                self.handoff_path,
                sha(self.handoff_path.read_bytes()),
                self.brief_path,
                self.resources_path,
                self.output,
            )
        self.assertEqual(
            (self.output / "foreign-marker.txt").read_text(encoding="utf-8"),
            "foreign",
        )


if __name__ == "__main__":
    unittest.main()
