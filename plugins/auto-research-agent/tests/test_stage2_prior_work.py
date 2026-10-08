"""Candidate-bound prior-work review contract and integration regressions."""

import copy
from contextlib import redirect_stdout
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace


HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / "cli")]

from stage2_check import (  # noqa: E402
    apply_assessment,
    export_selection,
    initialize_run,
    inspect_run,
)
from stage2_common import (  # noqa: E402
    Stage2Error,
    canonical_hash,
    current_prior_work_reviews,
    source_set_hash,
    validate_packet,
)
from stage2_eval.evaluation_v3 import prepare_content_view_v3  # noqa: E402
from stage2_ideation.__main__ import _enable_tables  # noqa: E402
from stage2_live.controller import (  # noqa: E402
    _initial_review_view_version,
    _run_controller,
    materialize_snapshot_input_root,
    verify_controller,
)
from stage2_live.extraction import _prompt, generation_schema  # noqa: E402
from stage2_live.review_models import _review_view_version  # noqa: E402
from stage2_live.source_updates import prepare_source_update  # noqa: E402
from stage2_workflow.content_gate import derive_content_gate  # noqa: E402
from stage2_workflow.evaluation_delivery import (  # noqa: E402
    build_evaluated_delivery,
    inspect_evaluated_delivery,
)
from stage2_workflow.reviews import prepare_review  # noqa: E402
from stage2_workflow.store import (  # noqa: E402
    add_snapshot,
    initialize_workflow,
    inspect_workflow,
)
import test_stage1_stage2_handoff as upstream_fixtures  # noqa: E402
from test_stage2_controller import SyntheticAdapter  # noqa: E402
import test_stage2_content_delivery as delivery_fixtures  # noqa: E402
from test_stage2_content_gate import refresh_actions, selection  # noqa: E402


def _latest_candidates_for_test(packet):
    current = {}
    for candidate in packet["candidates"]:
        previous = current.get(candidate["candidate_id"])
        if previous is None or candidate["version"] > previous["version"]:
            current[candidate["candidate_id"]] = candidate
    return [current[candidate_id] for candidate_id in sorted(current)]


class Stage2PriorWorkTests(unittest.TestCase):
    def test_legacy_input_replay_does_not_require_new_combined_inventory(self):
        legacy = copy.deepcopy(self.packet)
        legacy["schema_version"] = "2.3.0"
        legacy.pop("prior_work_reviews")
        path = self.root / "legacy-input.json"
        path.write_text(json.dumps(legacy), encoding="utf-8")
        workflow = self.root / "legacy-input-workflow"
        initialize_workflow(
            path,
            self.source_root,
            workflow,
            {"model": "test", "reasoning": "medium"},
            {"path": "policy.json", "sha256": "f" * 64},
            canonical_hash(legacy),
        )
        snapshot = inspect_workflow(workflow)["latest_snapshot"]
        controller = self.root / "legacy-input-controller"
        self.assertEqual(
            materialize_snapshot_input_root(snapshot, controller, create=False),
            Path(snapshot["checker"]["root"]) / "sources",
        )
        self.assertFalse(controller.exists())

    def test_review_version_detection_keeps_legacy_and_prior_work_hashes(self):
        snapshot = "a" * 64
        role = "challenger"
        view = prepare_review(
            self.packet, "direction-1", snapshot, role, review_view_version="1.2.0"
        )
        self.assertEqual(
            _review_view_version(
                self.packet, "direction-1", snapshot, role, canonical_hash(view)
            ),
            "1.2.0",
        )
        legacy = copy.deepcopy(self.packet)
        legacy["schema_version"] = "2.3.0"
        legacy.pop("prior_work_reviews")
        for version in ("1.0.0", "1.1.0"):
            with self.subTest(version=version):
                old_view = prepare_review(
                    legacy, "direction-1", snapshot, role, review_view_version=version
                )
                self.assertEqual(
                    _review_view_version(
                        legacy, "direction-1", snapshot, role, canonical_hash(old_view)
                    ),
                    version,
                )
        with self.assertRaisesRegex(Stage2Error, "unrecognized"):
            _review_view_version(legacy, "direction-1", snapshot, role, "b" * 64)

    def setUp(self):
        if os.name == "nt":
            previous_tempdir = tempfile.tempdir
            external_temp = Path(
                os.environ.get("STAGE2_TEST_TEMP_ROOT", "C:/temp")
            ).resolve()
            external_temp.mkdir(parents=True, exist_ok=True)
            tempfile.tempdir = str(external_temp)
            self.addCleanup(setattr, tempfile, "tempdir", previous_tempdir)
        self.upstream = upstream_fixtures.Stage1Stage2HandoffTests()
        self.upstream.setUp()
        self.addCleanup(self.upstream.doCleanups)
        self.upstream.build()
        self.root = self.upstream.root
        self.source_root = self.upstream.output
        self.packet = self.upstream.packet()
        self.packet.update(
            schema_version="2.4.0",
            supplemental_literature=[],
            research_tables=None,
            prior_work_reviews=[],
        )
        self.packet["candidates"] = [
            {
                "candidate_id": "direction-1",
                "version": 1,
                "parent_version": None,
                "question": "Does the bounded design improve the stated outcome?",
                "research_mode": "method-development",
                "opportunity": "The saved work leaves a bounded method comparison unresolved.",
                "value": "The comparison could improve a concrete research decision.",
                "approach": "Compare the proposed design against the saved precedent.",
                "requirements": ["Use the source-bound comparison."],
                "limitations": ["The bounded search is not exhaustive."],
                "evidence_ids": [self.packet["evidence"][0]["evidence_id"]],
            }
        ]
        self.receipt_path = "receipts/search-1.json"
        self.write_receipt("results")
        self.packet["prior_work_reviews"] = [self.review()]
        validate_packet(self.packet, self.source_root)

    def write_receipt(self, outcome, *, work_refs=None):
        work_refs = work_refs or [self.work_ref(self.packet)]
        value = {
            "query": "bounded precedent query",
            "tool_ref": "native-search:search-1",
            "outcome": outcome,
            "work_refs": work_refs,
            "raw_output": {"items": ["captured observation"]},
        }
        path = self.source_root / self.receipt_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        return hashlib.sha256(path.read_bytes()).hexdigest()

    @staticmethod
    def work_ref(packet, index=0):
        row = packet["literature"][index]
        return {"work_id": row["work_id"], "version_id": row["version_id"]}

    def review(self, *, status="bounded-complete", positioning=None, outcome="results"):
        candidate = self.packet["candidates"][-1]
        work = self.packet["literature"][0]
        evidence_id = self.packet["evidence"][0]["evidence_id"]
        return {
            "kind": "Stage2PriorWorkReview",
            "schema_version": "1.0.0",
            "candidate_id": candidate["candidate_id"],
            "candidate_version": candidate["version"],
            "candidate_sha256": canonical_hash(candidate),
            "source_set_sha256": source_set_hash(self.packet),
            "positioning": positioning
            or "The candidate overlaps the saved precedent but tests a bounded difference.",
            "review_status": status,
            "stop_reason": "The declared search limit was reached.",
            "search_limits": ["One source family and one exact bounded query."],
            "unresolved": ["Broader citation chaining remains unresolved."],
            "searches": [
                {
                    "search_id": "search-1",
                    "need": "Find the closest saved precedent.",
                    "query": "bounded precedent query",
                    "status": "executed",
                    "tool_ref": "native-search:search-1",
                    "raw_path": self.receipt_path,
                    "raw_sha256": hashlib.sha256(
                        (self.source_root / self.receipt_path).read_bytes()
                    ).hexdigest(),
                    "outcome": outcome,
                    "work_refs": [self.work_ref(self.packet)],
                }
            ],
            "comparisons": [
                {
                    "work_id": work["work_id"],
                    "version_id": work["version_id"],
                    "role": "closest",
                    "established": "The saved work establishes the bounded baseline.",
                    "overlap": "Both address the same recorded research need.",
                    "difference": "The candidate tests a different method component.",
                    "evidence_ids": [evidence_id],
                    "limitations": ["The excerpt does not establish global novelty."],
                }
            ],
        }

    def add_stage2_work(self, *, level="full-text"):
        raw = b"A second saved work reports a distinct bounded method.\n"
        relative = "sources/work-2.txt"
        path = self.source_root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        source = copy.deepcopy(self.packet["sources"][0])
        source.update(
            origin="stage2",
            source_id="source-2",
            work_id="work-2",
            version_id="v1",
            path=relative,
            sha256=hashlib.sha256(raw).hexdigest(),
            evidence_level=level,
            access_status="stage2-added",
            source_url="https://example.org/work-2",
            final_url="https://example.org/work-2",
            access_note="Saved Stage 2 source.",
        )
        evidence = copy.deepcopy(self.packet["evidence"][0])
        evidence.update(
            origin="stage2",
            evidence_id="evidence-2",
            source_id="source-2",
            work_id="work-2",
            version_id="v1",
            claim_text="The second work reports a distinct bounded method.",
            relation="supports",
            evidence_level=level,
            locator="line 1",
            quote=raw.decode().strip(),
        )
        literature = copy.deepcopy(self.packet["literature"][0])
        literature.update(
            origin="stage2",
            work_id="work-2",
            version_id="v1",
            title="Second bounded work",
            evidence_level=level,
            source_ids=["source-2"],
            roles=[],
            claim_ids=["evidence-2"],
        )
        self.packet["sources"].append(source)
        self.packet["evidence"].append(evidence)
        self.packet["literature"].append(literature)
        return source, evidence, literature

    def test_partial_and_zero_novelty_positioning_are_valid_records(self):
        self.packet["prior_work_reviews"] = [
            self.review(
                status="partial",
                positioning="No distinct novelty is established; the defensible contribution is a replication under bounded conditions.",
            )
        ]
        validate_packet(self.packet, self.source_root)
        self.assertEqual(
            current_prior_work_reviews(self.packet)["direction-1"]["review_status"],
            "partial",
        )

    def test_rehashed_cross_work_evidence_and_metadata_promotion_fail(self):
        base = copy.deepcopy(self.packet)
        for level, expected in (
            ("full-text", "another work version"),
            ("metadata", "cannot promote metadata"),
        ):
            with self.subTest(level=level):
                packet = copy.deepcopy(base)
                self.packet = packet
                _, _, work = self.add_stage2_work(level=level)
                comparison = self.packet["prior_work_reviews"][0]["comparisons"][0]
                if level == "full-text":
                    comparison["evidence_ids"] = ["evidence-2"]
                else:
                    comparison.update(
                        work_id=work["work_id"],
                        version_id=work["version_id"],
                        evidence_ids=["evidence-2"],
                    )
                self.packet["prior_work_reviews"][0]["source_set_sha256"] = (
                    source_set_hash(self.packet)
                )
                with self.assertRaisesRegex(Stage2Error, expected):
                    validate_packet(self.packet, self.source_root)
        self.packet = base

    def test_stale_candidate_and_source_set_hashes_fail(self):
        revised = copy.deepcopy(self.packet)
        revised_candidate = copy.deepcopy(revised["candidates"][0])
        revised_candidate.update(
            version=2, parent_version=1, question="A revised question"
        )
        revised["candidates"].append(revised_candidate)
        with self.assertRaisesRegex(Stage2Error, "not for latest"):
            validate_packet(revised, self.source_root)
        changed = copy.deepcopy(self.packet)
        changed["evidence"][0]["claim_text"] += " changed"
        changed["upstream"]["stage1_evidence_sha256"] = canonical_hash(
            [changed["evidence"][0]]
        )
        unsigned = {
            k: v for k, v in changed["upstream"].items() if k != "binding_sha256"
        }
        changed["upstream"]["binding_sha256"] = canonical_hash(unsigned)
        with self.assertRaisesRegex(Stage2Error, "source-set hash mismatch"):
            validate_packet(changed, self.source_root)

    def test_receipt_mismatch_traversal_and_failure_empty_distinction(self):
        mismatch = copy.deepcopy(self.packet)
        mismatch["prior_work_reviews"][0]["searches"][0]["query"] = "different query"
        with self.assertRaisesRegex(Stage2Error, "receipt query mismatch"):
            validate_packet(mismatch, self.source_root)
        traversal = copy.deepcopy(self.packet)
        traversal["prior_work_reviews"][0]["searches"][0]["raw_path"] = (
            "../receipt.json"
        )
        with self.assertRaisesRegex(Stage2Error, "portable and relative"):
            validate_packet(traversal, self.source_root)
        failed = copy.deepcopy(self.packet)
        failed["prior_work_reviews"][0]["searches"][0]["outcome"] = "failure"
        with self.assertRaisesRegex(Stage2Error, "receipt outcome mismatch"):
            validate_packet(failed, self.source_root)
        self.write_receipt("failure")
        failed["prior_work_reviews"][0]["searches"][0]["raw_sha256"] = hashlib.sha256(
            (self.source_root / self.receipt_path).read_bytes()
        ).hexdigest()
        validate_packet(failed, self.source_root)

    def test_old_packet_versions_remain_isolated(self):
        legacy = self.upstream.packet()
        validate_packet(legacy, self.source_root)
        self.assertNotIn("prior_work_reviews", legacy)
        self.assertEqual(current_prior_work_reviews(legacy), {})

    def test_opt_in_upgrade_preserves_existing_supplemental_history(self):
        primary_work_id = self.packet["literature"][0]["work_id"]
        source, evidence, literature = self.add_stage2_work()
        source.update(work_id=primary_work_id, version_id="supplemental-v2")
        evidence.update(work_id=primary_work_id, version_id="supplemental-v2")
        literature.update(work_id=primary_work_id, version_id="supplemental-v2")
        packet = copy.deepcopy(self.packet)
        packet["schema_version"] = "2.3.0"
        packet.pop("prior_work_reviews")
        packet["supplemental_literature"] = [packet["literature"].pop()]
        validate_packet(packet, self.source_root)
        packet_path = self.root / "packet-2.3-supplemental.json"
        output = self.root / "packet-2.4-upgrade.json"
        packet_path.write_text(json.dumps(packet), encoding="utf-8")
        args = SimpleNamespace(
            packet=str(packet_path),
            source_root=str(self.source_root),
            output=str(output),
            supplemental_versions=False,
            prior_work_reviews=True,
        )
        with redirect_stdout(io.StringIO()):
            _enable_tables(args)
        upgraded = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(upgraded["schema_version"], "2.4.0")
        self.assertEqual(
            upgraded["supplemental_literature"], packet["supplemental_literature"]
        )
        self.assertEqual(upgraded["prior_work_reviews"], [])

    def test_checker_copies_receipts_and_restores_external_paths(self):
        packet_path = self.root / "packet-2.4.json"
        packet_path.write_text(json.dumps(self.packet), encoding="utf-8")
        run = self.root / "checker-2.4"
        initialize_run(
            packet_path,
            self.source_root,
            run,
            canonical_hash(self.packet),
        )
        state = inspect_run(run)
        stored_search = state["packet"]["prior_work_reviews"][0]["searches"][0]
        self.assertEqual(
            stored_search["raw_path"], "prior_work_receipts/receipts/search-1.json"
        )
        selection_value = export_selection(run)
        external_search = selection_value["evaluation_packet"]["prior_work_reviews"][0][
            "searches"
        ][0]
        self.assertEqual(external_search["raw_path"], self.receipt_path)
        self.assertIn(
            "prior_work_receipts/receipts/search-1.json",
            (run / "selection.md").read_text(encoding="utf-8"),
        )
        self.assertTrue((run / "prior_work_receipts" / self.receipt_path).is_file())

        workflow = self.root / "workflow-2.4"
        initialize_workflow(
            packet_path,
            self.source_root,
            workflow,
            {"model": "test", "reasoning": "medium"},
            {"path": "policy.json", "sha256": "f" * 64},
            canonical_hash(self.packet),
        )
        restored = inspect_workflow(workflow)["latest_snapshot"]["packet"]
        self.assertEqual(restored, self.packet)
        snapshot = inspect_workflow(workflow)["latest_snapshot"]
        view_root = materialize_snapshot_input_root(
            snapshot, self.root / "combined-input-view"
        )
        retained_receipt = view_root / self.receipt_path
        self.assertEqual(
            retained_receipt.read_bytes(),
            (self.source_root / self.receipt_path).read_bytes(),
        )
        retained_receipt.write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(Stage2Error, "input-view-artifact-mismatch"):
            materialize_snapshot_input_root(snapshot, self.root / "combined-input-view")

    def test_checker_revision_invalidates_only_current_dossier_projection(self):
        packet_path = self.root / "packet-revision.json"
        packet_path.write_text(json.dumps(self.packet), encoding="utf-8")
        run = self.root / "checker-revision"
        initialize_run(packet_path, self.source_root, run, canonical_hash(self.packet))
        candidate = copy.deepcopy(self.packet["candidates"][0])
        candidate.update(
            version=2,
            parent_version=1,
            question="Does the revised bounded design improve the stated outcome?",
        )
        check = {
            "kind": "Stage2Check",
            "schema_version": "1.0.0",
            "event_id": "revise-direction-1",
            "candidate_id": "direction-1",
            "candidate_version": 1,
            "packet_sha256": canonical_hash(self.packet),
            "checks": {
                axis: {
                    "status": "assessed",
                    "score": 1,
                    "rationale": "The saved evidence supports a bounded revision.",
                    "evidence_ids": [self.packet["evidence"][0]["evidence_id"]],
                    "blocking": False,
                    "next_check": None,
                }
                for axis in (
                    "opportunity",
                    "value",
                    "answerability",
                    "materials",
                    "execution",
                )
            },
            "disposition": "revise",
            "reason": "Revise the bounded question while retaining its evidence history.",
            "next_step": "Complete a fresh candidate-bound prior-work review.",
            "scope_change_requested": False,
            "revised_candidate": candidate,
        }
        check_path = self.root / "revision-assessment.json"
        check_path.write_text(json.dumps(check), encoding="utf-8")
        apply_assessment(run, check_path)
        state = inspect_run(run)
        self.assertEqual(
            [row["candidate_id"] for row in state["packet"]["prior_work_reviews"]],
            ["direction-1"],
        )
        self.assertEqual(
            json.loads((run / "input_packet.json").read_text(encoding="utf-8")),
            self.packet,
        )
        selection_value = export_selection(run)
        self.assertEqual(selection_value["evaluation_packet"]["prior_work_reviews"], [])
        self.assertEqual(
            [
                row["version"]
                for row in selection_value["evaluation_packet"]["candidates"]
            ],
            [1, 2],
        )
        validate_packet(selection_value["evaluation_packet"], self.source_root)

    def test_external_and_initial_review_views_are_candidate_scoped(self):
        content = prepare_content_view_v3(self.packet, "subject", "a" * 64, "b" * 64)[
            "scientific_content"
        ]
        self.assertEqual(
            content["prior_work_reviews"], self.packet["prior_work_reviews"]
        )
        initial = prepare_review(
            self.packet,
            "direction-1",
            "c" * 64,
            "challenger",
            review_view_version="1.2.0",
        )
        self.assertEqual(
            initial["prior_work_review"], self.packet["prior_work_reviews"][0]
        )
        self.assertEqual(_initial_review_view_version(self.packet), "1.2.0")
        old = copy.deepcopy(self.packet)
        old["schema_version"] = "2.3.0"
        old.pop("prior_work_reviews")
        self.assertEqual(_initial_review_view_version(old), "1.1.0")
        for forbidden in ("checks", "assessment", "judge", "current_options"):
            self.assertNotIn(forbidden, initial)
        missing = copy.deepcopy(self.packet)
        missing["prior_work_reviews"] = []
        with self.assertRaisesRegex(Stage2Error, "prior-work-review-missing"):
            prepare_review(
                missing,
                "direction-1",
                "c" * 64,
                "challenger",
                review_view_version="1.2.0",
            )
        stale = copy.deepcopy(self.packet)
        stale["prior_work_reviews"][0]["candidate_sha256"] = "0" * 64
        with self.assertRaisesRegex(Stage2Error, "candidate hash mismatch"):
            prepare_review(
                stale,
                "direction-1",
                "c" * 64,
                "challenger",
                review_view_version="1.2.0",
            )

    def test_native_extraction_retains_table_contract_for_packet_2_4(self):
        span_index = {"spans": []}
        schema = generation_schema(span_index, self.packet)
        self.assertEqual(
            schema["$id"], "stage2-live-ideation-extraction.span-ids.v1_1.schema.json"
        )
        task = {
            "kind": "Stage2IdeationTask",
            "schema_version": "1.1.0",
            "tools_policy": "research-tools-allowed",
            "snapshot_sha256": "a" * 64,
            "packet_sha256": canonical_hash(self.packet),
            "raw_proposal_sha256": "b" * 64,
            "input_hash": "c" * 64,
        }
        self.assertIn(
            "Research-table cell contract",
            _prompt(task, self.packet, span_index, schema),
        )

    def test_controller_persists_prior_work_gate_and_resumes_completed_snapshot(self):
        base_packet = copy.deepcopy(self.packet)
        base_packet["prior_work_reviews"] = []
        packet_path = self.root / "controller-base-2.4.json"
        packet_path.write_text(json.dumps(base_packet), encoding="utf-8")
        workflow = self.root / "controller-workflow"
        initialize_workflow(
            packet_path,
            self.source_root,
            workflow,
            {"model": "synthetic-model", "reasoning": "medium"},
            {"path": "policy.json", "sha256": "a" * 64},
            canonical_hash(base_packet),
        )
        initial = inspect_workflow(workflow)
        base_snapshot = initial["latest_snapshot"]["event"]["payload"][
            "snapshot_sha256"
        ]
        controller = self.root / "prior-work-controller"
        delivery = self.root / "prior-work-delivery"
        workspaces = {
            name: {
                "workspace": str(self.root / f"{name}-workspace"),
                "home": str(self.root / f"{name}-home"),
            }
            for name in ("research", "extractor")
        }
        spec = {
            "confirmed_brief_sha256": canonical_hash(base_packet["brief"]),
            "base_snapshot_sha256": base_snapshot,
            "seed": "prior-work-resume-seed",
            "native": {
                "codex": "synthetic-codex",
                "model": "synthetic-model",
                "reasoning": "medium",
                "extraction_policy": {
                    "schema_version": "3.1.0",
                    "evaluator_bundle_sha256": "b" * 64,
                    "timeout_seconds": 600,
                    "max_transient_transport_retries": 1,
                    "max_semantic_corrections_per_unit": 1,
                    "retry_timeouts": False,
                },
                "config_bindings": {},
                "policy_bindings": {
                    "sandbox": "workspace-write",
                    "network_access": True,
                },
            },
            "preflight": {"synthetic": True},
            "workspaces": workspaces,
        }

        class GeneratedCandidateAdapter(SyntheticAdapter):
            def extract(self, context):
                result = super().extract(context)
                candidate = copy.deepcopy(
                    result["next_packet"]["packet"]["candidates"][0]
                )
                candidate.update(
                    candidate_id="generated-after-prior-work",
                    question="Can the generated candidate answer the bounded question?",
                )
                result["next_packet"]["packet"]["candidates"].append(candidate)
                return result

        adapter = GeneratedCandidateAdapter()
        pending = _run_controller(
            workflow,
            controller,
            delivery,
            initial["head_sha256"],
            spec,
            adapter,
        )
        self.assertEqual(pending["status"], "needs-prior-work")
        self.assertEqual(adapter.calls, ["research", "extract"])
        self.assertEqual(
            pending["prior_work_completion"]["missing_candidate_ids"],
            ["direction-1", "generated-after-prior-work"],
        )
        saved = verify_controller(controller, pending["controller_manifest_sha256"])[
            "manifest"
        ]
        self.assertEqual(
            saved["prior_work_completion"], pending["prior_work_completion"]
        )

        state = inspect_workflow(workflow)
        completed_packet = copy.deepcopy(state["latest_snapshot"]["packet"])
        completed_packet["prior_work_reviews"] = []
        for candidate in _latest_candidates_for_test(completed_packet):
            review = self.review(status="partial")
            review.update(
                candidate_id=candidate["candidate_id"],
                candidate_version=candidate["version"],
                candidate_sha256=canonical_hash(candidate),
                source_set_sha256=source_set_hash(completed_packet),
            )
            review["searches"] = [
                {
                    "search_id": "planned-resume",
                    "need": "Complete another bounded search if needed.",
                    "query": "future bounded query",
                    "status": "planned",
                    "tool_ref": None,
                    "raw_path": None,
                    "raw_sha256": None,
                    "outcome": "unknown",
                    "work_refs": [],
                }
            ]
            completed_packet["prior_work_reviews"].append(review)
        completed_path = self.root / "completed-prior-work.json"
        completed_path.write_text(json.dumps(completed_packet), encoding="utf-8")
        latest = state["latest_snapshot"]
        event = add_snapshot(
            workflow,
            completed_path,
            latest["checker"]["root"] / "sources",
            "Completed candidate-bound prior-work dossiers.",
            {
                candidate["candidate_id"]: {
                    "status": "affected",
                    "reason": "A current prior-work dossier is now available.",
                }
                for candidate in _latest_candidates_for_test(completed_packet)
            },
            state["head_sha256"],
        )
        resumed = _run_controller(
            workflow,
            controller,
            delivery,
            event["event_sha256"],
            spec,
            GeneratedCandidateAdapter(),
        )
        self.assertEqual(resumed["status"], "needs-workspace")
        self.assertNotIn("prior_work_completion", resumed)
        resumed_state = inspect_workflow(workflow)
        completed_snapshot = resumed_state["latest_snapshot"]
        view_root = materialize_snapshot_input_root(completed_snapshot, controller)
        self.assertEqual(
            materialize_snapshot_input_root(completed_snapshot, controller), view_root
        )
        source_path = view_root / completed_packet["sources"][0]["path"]
        source_path.write_bytes(source_path.read_bytes() + b"tamper")
        with self.assertRaisesRegex(Stage2Error, "input-view-artifact-mismatch"):
            materialize_snapshot_input_root(completed_snapshot, controller)

    def test_evaluated_delivery_preserves_and_inspects_raw_receipts(self):
        fixture = delivery_fixtures.ContentDeliveryTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        value = copy.deepcopy(fixture.selection)
        packet = value["evaluation_packet"]
        packet.update(
            schema_version="2.4.0",
            supplemental_literature=[],
            prior_work_reviews=[],
        )
        self.packet = packet
        self.source_root = fixture.sources
        self.receipt_path = "receipts/evaluated-search.json"
        self.write_receipt("results")
        packet["prior_work_reviews"] = [self.review()]
        refresh_actions(value)
        bundle = fixture.make_bundle(value)
        snapshots = [
            {**row, "path": "sources/" + row["path"]} for row in packet["sources"]
        ]
        output = fixture.root / "evaluated-prior-work"
        manifest = build_evaluated_delivery(
            value,
            snapshots,
            fixture.sources,
            bundle,
            output,
            expected_bundle_sha256=canonical_hash(bundle),
            event_head="d" * 64,
            stored_packet_sha256="e" * 64,
        )
        retained = output / "sources" / self.receipt_path
        self.assertEqual(
            retained.read_bytes(),
            (fixture.sources / self.receipt_path).read_bytes(),
        )
        inspect_evaluated_delivery(
            output, expected_manifest_sha256=manifest["manifest_sha256"]
        )
        retained.write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(Stage2Error, "artifact-changed"):
            inspect_evaluated_delivery(
                output, expected_manifest_sha256=manifest["manifest_sha256"]
            )

    def test_content_gate_requires_review_only_for_packet_2_4(self):
        value = selection()
        value["evaluation_packet"].update(
            schema_version="2.4.0", supplemental_literature=[], prior_work_reviews=[]
        )
        refresh_actions(value)
        gate = derive_content_gate(value)
        self.assertEqual(gate["status"], "draft")
        self.assertIn(
            "candidate-table:v1:prior-work",
            {row["check_id"] for row in gate["blocking_items"]},
        )
        candidate = value["evaluation_packet"]["candidates"][0]
        work = value["evaluation_packet"]["literature"][0]
        evidence = value["evaluation_packet"]["evidence"][0]
        review = {
            **self.review(status="partial"),
            "candidate_id": candidate["candidate_id"],
            "candidate_version": candidate["version"],
            "candidate_sha256": canonical_hash(candidate),
            "source_set_sha256": source_set_hash(value["evaluation_packet"]),
            "searches": [
                {
                    "search_id": "planned-1",
                    "need": "Check another family.",
                    "query": "future bounded query",
                    "status": "planned",
                    "tool_ref": None,
                    "raw_path": None,
                    "raw_sha256": None,
                    "outcome": "unknown",
                    "work_refs": [],
                }
            ],
            "comparisons": [
                {
                    "work_id": work["work_id"],
                    "version_id": work["version_id"],
                    "role": "closest",
                    "established": "The saved work establishes a bounded baseline.",
                    "overlap": "Both address the recorded need.",
                    "difference": "The direction changes one method component.",
                    "evidence_ids": [evidence["evidence_id"]],
                    "limitations": ["This is not an exhaustive novelty claim."],
                }
            ],
        }
        value["evaluation_packet"]["prior_work_reviews"] = [review]
        refresh_actions(value)
        self.assertEqual(derive_content_gate(value)["status"], "content-complete")

    def test_source_update_clears_stale_reviews(self):
        source, evidence, literature = self.add_stage2_work()
        raw_path = self.source_root / source["path"]
        receipt = {
            "status": "obtained",
            "url": source["source_url"],
            "retrieved_at": source["retrieved_at"],
            "raw_sha256": source["sha256"],
            "identity_status": "matched",
            "evidence_level": source["evidence_level"],
            "reason": "Captured a bounded second work.",
            "action_ref": "native-call-synthetic",
        }
        parent = copy.deepcopy(self.packet)
        parent["sources"].pop()
        parent["evidence"].pop()
        parent["literature"].pop()
        parent["prior_work_reviews"][0]["source_set_sha256"] = source_set_hash(parent)
        result = prepare_source_update(
            parent,
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
            {
                "direction-1": {
                    "status": "affected",
                    "reason": "New prior work changes positioning.",
                }
            },
            self.root / "source-update-2.4",
            expected_packet_sha256=canonical_hash(parent),
        )
        updated = json.loads(Path(result["packet_path"]).read_text(encoding="utf-8"))
        self.assertEqual(updated["prior_work_reviews"], [])
        validate_packet(updated, Path(result["source_root"]))


if __name__ == "__main__":
    unittest.main()
