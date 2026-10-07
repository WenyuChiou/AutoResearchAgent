"""Versioned Stage 2 literature stays one primary work with bound supplements."""

import copy
import contextlib
import hashlib
import io
import json
from pathlib import Path
import sys
import unittest

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / "cli")]

from stage2_check.bibliography import build_bibliography  # noqa: E402
from stage2_check.report import _bibliography as bibliography_markdown  # noqa: E402
from stage2_check.report_html import _bibliography as bibliography_html  # noqa: E402
from stage2_common import Stage2Error, canonical_hash, validate_packet  # noqa: E402
from stage2_eval.evaluation_v3 import (  # noqa: E402
    prepare_action_view_v3,
    prepare_content_view_v3,
    validate_judge_output_v3,
)
from stage2_ideation.prompts import build_research_task  # noqa: E402
from stage2_ideation.__main__ import main as ideation_main  # noqa: E402
from stage2_ideation.tables_report import render_tables_markdown  # noqa: E402
from stage2_ideation.topic_tables import (  # noqa: E402
    TopicTableError,
    validate_research_tables,
)
from stage2_live.source_updates import prepare_source_update  # noqa: E402
from stage2_workflow.content_gate import derive_content_gate  # noqa: E402
from stage2_workflow.store import _validate_append_only  # noqa: E402
from test_stage1_stage2_handoff import Stage1Stage2HandoffTests  # noqa: E402
from test_stage2_content_gate import refresh_actions, selection  # noqa: E402
from test_stage2_evaluation_v3 import (  # noqa: E402
    action_record,
    content_assessment,
    judge,
)


class Stage2LiteratureVersionTests(unittest.TestCase):
    def setUp(self):
        self.upstream = Stage1Stage2HandoffTests()
        self.upstream.setUp()
        self.addCleanup(self.upstream.doCleanups)
        self.upstream.build()
        self.root = self.upstream.root
        self.source_root = self.upstream.output
        self.packet = self.upstream.packet()
        self.packet.update(
            schema_version="2.3.0",
            supplemental_literature=[],
            research_tables=None,
        )
        validate_packet(self.packet, self.source_root)

    def supplement(self):
        raw = b"Synthetic households are described in the updated abstract.\n"
        raw_path = self.root / "supplement-v2.txt"
        raw_path.write_bytes(raw)
        digest = hashlib.sha256(raw).hexdigest()
        source = {
            "origin": "stage2",
            "source_id": "src1-v2",
            "work_id": "work1",
            "version_id": "v2",
            "path": "sources/src1-v2.txt",
            "sha256": digest,
            "evidence_level": "abstract",
            "access_status": "stage2-added",
            "retrieved_at": "2026-10-06T00:00:00Z",
            "source_url": "https://example.org/study/v2",
            "final_url": "https://example.org/study/v2",
            "access_note": "Public updated abstract; identity matched.",
        }
        evidence = {
            "origin": "stage2",
            "evidence_id": "claim1-v2",
            "source_id": "src1-v2",
            "work_id": "work1",
            "version_id": "v2",
            "claim_text": "The updated abstract describes the population.",
            "relation": "unverified",
            "evidence_level": "abstract",
            "locator": "line 1",
            "quote": raw.decode().strip(),
        }
        literature = copy.deepcopy(self.packet["literature"][0])
        literature.update(
            origin="stage2",
            version_id="v2",
            evidence_level="abstract",
            source_ids=["src1-v2"],
            claim_ids=["claim1-v2"],
            roles=[
                {
                    "role": "topic-core",
                    "reason": "Supplemental source version only; not independent support.",
                    "claim_ids": ["claim1-v2"],
                }
            ],
        )
        return raw_path, source, evidence, literature

    def packet_with_supplement(self):
        raw_path, source, evidence, literature = self.supplement()
        packet = copy.deepcopy(self.packet)
        packet["sources"].append(source)
        packet["evidence"].append(evidence)
        packet["supplemental_literature"].append(literature)
        target = self.source_root / source["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw_path.read_bytes())
        return packet

    def test_source_update_routes_same_work_new_version_without_new_primary(self):
        raw_path, source, evidence, literature = self.supplement()
        receipt = {
            "status": "obtained",
            "url": source["source_url"],
            "retrieved_at": source["retrieved_at"],
            "raw_sha256": source["sha256"],
            "identity_status": "matched",
            "evidence_level": "abstract",
            "reason": "Captured a newer public version of the same work.",
            "action_ref": "native-call-synthetic",
        }
        impact = {
            row["candidate_id"]: {
                "status": "affected",
                "reason": "The new version requires a fresh check.",
            }
            for row in self.packet["candidates"]
        }
        result = prepare_source_update(
            self.packet,
            self.source_root,
            [
                {
                    "source": source,
                    "evidence": [evidence],
                    "literature": literature,
                    "raw_path": str(raw_path),
                    "acquisition": receipt,
                }
            ],
            [],
            impact,
            self.root / "source-update",
            expected_packet_sha256=canonical_hash(self.packet),
        )
        updated = json.loads(Path(result["packet_path"]).read_text(encoding="utf-8"))
        self.assertEqual(updated["literature"], self.packet["literature"])
        self.assertEqual(updated["supplemental_literature"], [literature])
        bibliography = build_bibliography(
            updated,
            {row["source_id"]: row for row in updated["sources"]},
            {row["evidence_id"]: row for row in updated["evidence"]},
        )
        self.assertEqual(len(bibliography["works"]), len(self.packet["literature"]))
        self.assertEqual(
            bibliography["works"][0]["supplemental_versions"][0]["support_scope"],
            "supplemental-source-version-of-same-work",
        )
        self.assertIn(
            "Supplemental source version v2 of the same work",
            bibliography["by_evidence"]["claim1-v2"][0]["reason"],
        )

        new_source = copy.deepcopy(source)
        new_source.update(
            source_id="src-new-work",
            work_id="work-new",
            version_id="v1",
            path="sources/work-new-v1.txt",
        )
        new_evidence = copy.deepcopy(evidence)
        new_evidence.update(
            evidence_id="claim-new-work",
            source_id="src-new-work",
            work_id="work-new",
            version_id="v1",
        )
        new_literature = copy.deepcopy(literature)
        new_literature.update(
            work_id="work-new",
            version_id="v1",
            source_ids=["src-new-work"],
            claim_ids=["claim-new-work"],
            roles=[],
        )
        distinct = prepare_source_update(
            self.packet,
            self.source_root,
            [
                {
                    "source": new_source,
                    "evidence": [new_evidence],
                    "literature": new_literature,
                    "raw_path": str(raw_path),
                    "acquisition": receipt,
                }
            ],
            [],
            impact,
            self.root / "distinct-work-update",
            expected_packet_sha256=canonical_hash(self.packet),
        )
        distinct_packet = json.loads(
            Path(distinct["packet_path"]).read_text(encoding="utf-8")
        )
        self.assertEqual(distinct_packet["literature"][-1], new_literature)
        self.assertEqual(distinct_packet["supplemental_literature"], [])

        source_only = copy.deepcopy(new_source)
        source_only.update(
            source_id="src-source-only",
            work_id="work-source-only",
            path="sources/source-only.txt",
        )
        source_only_result = prepare_source_update(
            self.packet,
            self.source_root,
            [
                {
                    "source": source_only,
                    "evidence": [],
                    "raw_path": str(raw_path),
                    "acquisition": receipt,
                }
            ],
            [],
            impact,
            self.root / "source-only-update",
            expected_packet_sha256=canonical_hash(self.packet),
        )
        source_only_packet = json.loads(
            Path(source_only_result["packet_path"]).read_text(encoding="utf-8")
        )
        self.assertEqual(source_only_packet["literature"], self.packet["literature"])
        self.assertEqual(source_only_packet["supplemental_literature"], [])

    def test_supplement_bindings_and_levels_fail_closed(self):
        valid = self.packet_with_supplement()
        validate_packet(valid, self.source_root)
        mutations = (
            (
                "unknown primary",
                "unknown-primary-work",
                lambda p: [
                    row.update(work_id="foreign")
                    for row in (
                        p["supplemental_literature"][0],
                        p["sources"][-1],
                        p["evidence"][-1],
                    )
                ],
            ),
            (
                "duplicate pair",
                "duplicate literature work/version",
                lambda p: [
                    row.update(version_id="v1")
                    for row in (
                        p["supplemental_literature"][0],
                        p["sources"][-1],
                        p["evidence"][-1],
                    )
                ],
            ),
            (
                "foreign source",
                "literature-source-binding-mismatch",
                lambda p: p["supplemental_literature"][0].update(source_ids=["src1"]),
            ),
            (
                "foreign evidence",
                "literature-evidence-binding-mismatch",
                lambda p: p["supplemental_literature"][0].update(
                    claim_ids=["claim1"], roles=[]
                ),
            ),
            (
                "source level promotion",
                "evidence-level-promotion",
                lambda p: p["supplemental_literature"][0].update(
                    evidence_level="full-text"
                ),
            ),
        )
        for label, message, mutate in mutations:
            with self.subTest(label=label):
                changed = copy.deepcopy(valid)
                mutate(changed)
                with self.assertRaisesRegex(Stage2Error, message):
                    validate_packet(changed, self.source_root)

    def test_supplement_history_is_immutable_and_2_2_requires_new_run(self):
        previous = self.packet_with_supplement()
        changed = copy.deepcopy(previous)
        changed["supplemental_literature"][0]["title"] = "Rewritten title"
        with self.assertRaisesRegex(Stage2Error, "history-rewritten"):
            _validate_append_only(previous, changed)

        legacy = copy.deepcopy(self.packet)
        legacy["schema_version"] = "2.2.0"
        legacy.pop("supplemental_literature")
        with self.assertRaisesRegex(Stage2Error, "version-change-requires-new-run"):
            _validate_append_only(legacy, self.packet)

    def tables(self, packet):
        raw = "Compare the primary work with its supplemental source version."
        span = {"start": 0, "end": len(raw), "quote": raw}
        return {
            "kind": "Stage2ResearchTables",
            "schema_version": "1.0.0",
            "brief_sha256": canonical_hash(packet["brief"]),
            "input_packet_sha256": canonical_hash(packet),
            "input_snapshot_sha256": "a" * 64,
            "raw_proposal": raw,
            "raw_proposal_sha256": hashlib.sha256(raw.encode()).hexdigest(),
            "dimensions": [
                {
                    "dimension_id": "population",
                    "label": "Population description",
                    "research_need": "Compare the recorded population descriptions.",
                    "rationale": "Versions may contain different detail.",
                    "definition": "Use only the exact declared source version.",
                    "value_kind": "text",
                    "conditions": [],
                    "spans": [span],
                }
            ],
            "work_refs": [
                {"work_id": row["work_id"], "version_id": row["version_id"]}
                for row in [*packet["literature"], *packet["supplemental_literature"]]
            ],
            "cells": [
                {
                    "dimension_id": "population",
                    "work_id": "work1",
                    "version_id": version,
                    "status": "described",
                    "value": "Synthetic population",
                    "reason": "The bound source version describes the population.",
                    "inspection_scope": "Exact saved excerpt",
                    "negative_basis": None,
                    "evidence_ids": [evidence_id],
                    "spans": [span],
                }
                for version, evidence_id in (
                    (row["version_id"], row["claim_ids"][0])
                    for row in [
                        *packet["literature"],
                        *packet["supplemental_literature"],
                    ]
                )
            ],
            "direction_resources": [],
        }

    def test_table_grid_uses_exact_supplement_version_and_source(self):
        packet = self.packet_with_supplement()
        tables = self.tables(packet)
        self.assertEqual(validate_research_tables(tables, packet), tables)
        self.assertIn(
            "supplemental source version v2 of the same work",
            render_tables_markdown(tables, packet),
        )
        wrong = copy.deepcopy(tables)
        wrong["cells"][1]["evidence_ids"] = ["claim1"]
        with self.assertRaisesRegex(TopicTableError, "another work version"):
            validate_research_tables(wrong, packet)

        incomplete = copy.deepcopy(tables)
        incomplete["work_refs"].pop()
        incomplete["cells"].pop()
        self.assertEqual(validate_research_tables(incomplete, packet), incomplete)
        packet["research_tables"] = incomplete
        value = selection()
        value["evaluation_packet"] = packet
        gate = derive_content_gate(value)
        self.assertEqual(gate["status"], "draft")
        self.assertIn(
            "literature-coverage", [row["check_id"] for row in gate["blocking_items"]]
        )

    def test_source_update_after_matrix_keeps_history_and_requires_rebuild(self):
        packet = copy.deepcopy(self.packet)
        packet["research_tables"] = self.tables(packet)
        validate_packet(packet, self.source_root)
        original = copy.deepcopy(packet)
        raw_path, source, evidence, literature = self.supplement()
        result = prepare_source_update(
            packet,
            self.source_root,
            [
                {
                    "source": source,
                    "evidence": [evidence],
                    "literature": literature,
                    "raw_path": str(raw_path),
                    "acquisition": {
                        "status": "obtained",
                        "url": source["source_url"],
                        "retrieved_at": source["retrieved_at"],
                        "raw_sha256": source["sha256"],
                        "identity_status": "matched",
                        "evidence_level": "abstract",
                        "reason": "New abstract requires matrix rebuilding.",
                        "action_ref": "native-call-synthetic",
                    },
                }
            ],
            [],
            {
                row["candidate_id"]: {"status": "affected", "reason": "New source."}
                for row in packet["candidates"]
            },
            self.root / "update-after-matrix",
            expected_packet_sha256=canonical_hash(packet),
        )
        updated = json.loads(Path(result["packet_path"]).read_text(encoding="utf-8"))
        self.assertEqual(packet, original)
        self.assertEqual(updated["research_tables"], original["research_tables"])
        validate_packet(updated, Path(result["packet_path"]).parent)
        value = selection()
        value["evaluation_packet"] = updated
        gate = derive_content_gate(value)
        self.assertEqual(gate["status"], "draft")
        self.assertIn(
            "literature-coverage", [row["check_id"] for row in gate["blocking_items"]]
        )

    def test_report_bibliography_labels_supplement_without_extra_work(self):
        packet = self.packet_with_supplement()
        packet["supplemental_literature"][0]["title"] = (
            "<script>Versioned title</script>"
        )
        evidence = {row["evidence_id"]: row for row in packet["evidence"]}
        bibliography = build_bibliography(
            packet, {row["source_id"]: row for row in packet["sources"]}, evidence
        )
        lines = []
        bibliography_markdown(lines, bibliography, evidence)
        markdown = "\n".join(lines)
        html = bibliography_html(bibliography, evidence)
        self.assertEqual(len(bibliography["works"]), 1)
        self.assertEqual(markdown.count("### "), 1)
        self.assertEqual(html.count('class="card bibliography-work"'), 1)
        for rendered in (markdown, html):
            self.assertIn("Additional source version of the same study", rendered)
            self.assertIn("src1-v2", rendered)
            self.assertIn("sources/src1-v2.txt", rendered)
            self.assertIn("claim1-v2", rendered.replace("\\-", "-"))
            self.assertIn("Versioned title", rendered)
            self.assertNotIn("<script>", rendered)

    def test_v2_2_task_hash_remains_legacy_stable(self):
        legacy = copy.deepcopy(self.packet)
        legacy["schema_version"] = "2.2.0"
        legacy.pop("supplemental_literature")
        task = build_research_task(legacy, "a" * 64)
        self.assertEqual(
            task["input_hash"],
            "3b35e528a9aa1e1d82587d07a8b10120192ddc6acde2ee9dd965435b959bcb86",
        )

    def test_supplement_change_rejects_stale_evaluation_binding(self):
        packet = self.packet_with_supplement()
        view = prepare_content_view_v3(packet, "subject-old", "a" * 64, "b" * 64)
        action = prepare_action_view_v3(
            packet,
            view,
            content_assessment(view, evidence_ids=["claim1"]),
            action_record(packet),
        )
        stale = judge(view, action, packet)
        for row in stale["criteria"]:
            row["evidence_ids"] = ["claim1"]

        changed = copy.deepcopy(packet)
        changed["supplemental_literature"][0]["title"] = "New source-version title"
        current_view = prepare_content_view_v3(
            changed, "subject-old", "a" * 64, "b" * 64
        )
        current_action = prepare_action_view_v3(
            changed,
            current_view,
            content_assessment(current_view, evidence_ids=["claim1"]),
            action_record(changed),
        )
        with self.assertRaisesRegex(Stage2Error, "judge packet_sha256 mismatch"):
            validate_judge_output_v3(stale, current_view, current_action, changed)

    def test_content_gate_recognizes_v2_3_as_table_capable(self):
        value = selection()
        value["evaluation_packet"].update(
            schema_version="2.3.0", supplemental_literature=[]
        )
        refresh_actions(value)
        self.assertEqual(derive_content_gate(value)["status"], "content-complete")

    def test_enable_tables_requires_explicit_v2_3_opt_in(self):
        source = self.upstream.output / "packet.json"
        common = [
            "enable-tables",
            "--packet",
            str(source),
            "--source-root",
            str(self.source_root),
        ]
        default_output = self.root / "default-v2-2.json"
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(
                ideation_main([*common, "--output", str(default_output)]), 0
            )
        default = json.loads(default_output.read_text(encoding="utf-8"))
        self.assertEqual(default["schema_version"], "2.2.0")
        self.assertNotIn("supplemental_literature", default)

        opt_in_output = self.root / "opt-in-v2-3.json"
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(
                ideation_main(
                    [
                        *common,
                        "--output",
                        str(opt_in_output),
                        "--supplemental-versions",
                    ]
                ),
                0,
            )
        opt_in = json.loads(opt_in_output.read_text(encoding="utf-8"))
        self.assertEqual(opt_in["schema_version"], "2.3.0")
        self.assertEqual(opt_in["supplemental_literature"], [])

        default_bytes = default_output.read_bytes()
        upgraded = self.root / "upgrade-v2-2.json"
        upgrade_args = [
            "enable-tables",
            "--packet",
            str(default_output),
            "--source-root",
            str(self.source_root),
            "--output",
            str(upgraded),
        ]
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(ideation_main(upgrade_args), 2)
        self.assertFalse(upgraded.exists())
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(
                ideation_main([*upgrade_args, "--supplemental-versions"]), 0
            )
        self.assertEqual(default_output.read_bytes(), default_bytes)
        result = json.loads(upgraded.read_text(encoding="utf-8"))
        self.assertEqual(result["schema_version"], "2.3.0")
        self.assertEqual(result["research_tables"], None)
        self.assertEqual(result["literature"], default["literature"])


if __name__ == "__main__":
    unittest.main()
