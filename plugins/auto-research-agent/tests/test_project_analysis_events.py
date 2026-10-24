"""Pure agent event-plan preparation; no ledger, source, model, or SDK I/O."""

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cli"))

from research_workspace_native.project_analysis_events import prepare_agent_events
from research_workspace_native.session_api import SessionApiError
from stage1_deliverable.common import canonical, sha
from stage1_ledger.contracts import check
from stage1_ledger.journal import LedgerError
from test_project_full_analysis import fixture
from test_project_semantic_analysis import proposal


def inputs():
    snapshot = fixture()
    full = snapshot["reading_input"]["full_source"]
    source = full["sources"][0]
    source["text"] = "尾端證據 Ω decoy " + source["text"]
    encoded = source["text"].encode("utf8")
    source["text_sha256"] = sha(encoded)
    source["text_bytes"] = len(encoded)
    saved_source = snapshot["reading_input"]["saved_reading"]["sources"][0]
    saved_source["text_sha256"] = source["text_sha256"]
    saved_source["text_bytes"] = source["text_bytes"]
    snapshot["reading_input"]["saved_reading"]["source_failures"] = [
        {
            "source_id": "source-failed",
            "outcome": "failed",
            "identity_status": "unverified",
            "reason": "Unknown",
        },
        {
            "source_id": "source-failed",
            "outcome": "failed",
            "identity_status": "unverified",
            "reason": "Unknown",
        },
    ]
    value = proposal(full)
    quote = "尾端證據 Ω".encode("utf8")
    start = encoded.rindex(quote)
    value["reading"]["evidence"][0].update(
        start_byte=start,
        end_byte=start + len(quote),
    )
    value["screening"].update(
        decision="pending",
        reason_code="evidence-unknown",
        rationale="Unknown remains unresolved.",
        missing_information=["Independent confirmation remains Unknown."],
    )
    value["claims"][0]["relation"] = "contradicts"
    ref = {
        "kind": "ArtifactRef",
        "schema_version": "1.0.0",
        "artifact_id": "artifact-" + source["text_sha256"] + "-source-1",
        "artifact_type": "raw-output",
        "path": "raw/" + source["text_sha256"] + ".bin",
        "sha256": source["text_sha256"],
        "producer": "source-1",
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    facts = [
        {
            "source_id": "source-1",
            "work_id": "work-1",
            "version_id": "version-1",
            "text_ref": ref,
            "evidence_level": "abstract",
            "receipt_sha256": "b" * 64,
        }
    ]
    raw = canonical(value)
    proposal_ref = {
        "kind": "ArtifactRef",
        "schema_version": "1.0.0",
        "artifact_id": "artifact-" + sha(raw) + "-analysis-agent",
        "artifact_type": "raw-output",
        "path": "raw/" + sha(raw) + ".bin",
        "sha256": sha(raw),
        "producer": "analysis-agent",
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    return snapshot, value, raw, facts, proposal_ref


def prepare(snapshot, raw, facts, ref):
    return prepare_agent_events(
        raw,
        snapshot,
        facts,
        proposal_ref=ref,
        actor="analysis-agent",
        method="full-source-analysis-v1",
    )


def prepare_from_sources(snapshot, raw, facts, ref=None, source_evidence=True):
    return prepare_agent_events(
        raw,
        snapshot,
        facts,
        proposal_ref=ref,
        actor="analysis-agent",
        method="full-source-analysis-v1",
        source_evidence=source_evidence,
    )


class AnalysisEventPlanTests(unittest.TestCase):
    def test_source_evidence_plan_uses_only_validated_source_refs(self):
        snapshot, _, raw, facts, _ = inputs()
        plan = prepare_from_sources(snapshot, raw, facts)
        self.assertEqual(plan["schema_version"], "1.1.0")
        self.assertIsNone(plan["proposal_ref"])
        self.assertEqual(plan["proposal_sha256"], sha(raw))
        self.assertEqual(plan["proposal_storage"], "original-model-job")
        self.assertEqual(
            plan["decision_arguments"]["evidence_refs"],
            [facts[0]["text_ref"]],
        )
        self.assertIsNot(
            plan["decision_arguments"]["evidence_refs"][0], facts[0]["text_ref"]
        )

    def test_source_evidence_mode_is_explicit_and_rejects_arbitrary_refs(self):
        snapshot, _, raw, facts, ref = inputs()
        for kwargs in (
            {"ref": ref},
            {"source_evidence": 1},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(SessionApiError):
                prepare_from_sources(snapshot, raw, facts, **kwargs)
        with self.assertRaises(SessionApiError):
            prepare_from_sources(snapshot, raw, [])
        legacy = prepare(snapshot, raw, facts, ref)
        self.assertEqual(legacy["schema_version"], "1.0.0")
        self.assertNotIn("proposal_sha256", legacy)
        self.assertNotIn("proposal_storage", legacy)
        self.assertEqual(legacy["decision_arguments"]["evidence_refs"], [ref])

    def test_unicode_bytes_become_exact_character_spans_and_preserve_proposal(self):
        snapshot, value, raw, facts, ref = inputs()
        plan = prepare(snapshot, raw, facts, ref)
        source_text = snapshot["reading_input"]["full_source"]["sources"][0]["text"]
        first = plan["claims"][0]
        self.assertEqual(
            source_text[first["span"]["start"] : first["span"]["end"]],
            first["span"]["quote"],
        )
        self.assertEqual(first["span"]["quote"], "尾端證據 Ω")
        self.assertNotEqual(
            source_text.find(first["span"]["quote"]), first["span"]["start"]
        )
        self.assertEqual(plan["proposal"]["screening"], value["screening"])
        self.assertEqual(
            [row["arguments"]["assessment"] for row in plan["claims"]],
            [row["assessment"] for row in value["claims"]],
        )
        self.assertEqual(plan["source_ids"], ["source-1", "source-failed"])

    def test_core_bare_assessment_labels_refuse_before_event_plan(self):
        for label in (
            "Unknown",
            "unverified",
            "unverifiable",
            "pending",
            "unclear",
            "supports",
            "partial",
            "contradicts",
            "context",
        ):
            snapshot, value, _, facts, ref = inputs()
            value["claims"][0]["assessment"]["rationale"] = label
            raw = canonical(value)
            ref["sha256"] = sha(raw)
            ref["artifact_id"] = "artifact-" + sha(raw) + "-analysis-agent"
            ref["path"] = "raw/" + sha(raw) + ".bin"
            with (
                self.subTest(label=label),
                self.assertRaisesRegex(LedgerError, "claim-assessment-reason"),
            ):
                prepare(snapshot, raw, facts, ref)

    def test_metadata_cannot_supply_text_support_relations(self):
        for relation in ("supports", "partial", "contradicts", "context"):
            snapshot, value, _, facts, ref = inputs()
            facts[0]["evidence_level"] = "metadata"
            value["claims"][0]["relation"] = relation
            raw = canonical(value)
            ref["sha256"] = sha(raw)
            ref["artifact_id"] = "artifact-" + sha(raw) + "-analysis-agent"
            ref["path"] = "raw/" + sha(raw) + ".bin"
            with (
                self.subTest(relation=relation),
                self.assertRaisesRegex(LedgerError, "claim-needs-text-evidence"),
            ):
                prepare(snapshot, raw, facts, ref)

    def test_evidence_level_comes_only_from_source_fact(self):
        snapshot, value, _, facts, ref = inputs()
        for level in ("metadata", "abstract"):
            changed = deepcopy(facts)
            changed[0]["evidence_level"] = level
            preserved = deepcopy(value)
            if level == "metadata":
                for row in preserved["claims"]:
                    row["relation"] = "unclear"
            raw = canonical(preserved)
            changed_ref = dict(
                ref,
                sha256=sha(raw),
                artifact_id="artifact-" + sha(raw) + "-analysis-agent",
                path="raw/" + sha(raw) + ".bin",
            )
            plan = prepare(snapshot, raw, changed, changed_ref)
            self.assertEqual(
                [row["arguments"]["relation"] for row in plan["claims"]],
                [row["relation"] for row in preserved["claims"]],
            )
            self.assertTrue(
                all(
                    row["arguments"]["evidence_level"] == level
                    for row in plan["claims"]
                )
            )
        self.assertEqual(
            snapshot["reading_input"]["full_source"]["sources"][0]["scope"],
            "full-text",
        )

    def test_decision_and_claim_arguments_are_agent_only_and_unadopted(self):
        snapshot, _, raw, facts, ref = inputs()
        plan = prepare(snapshot, raw, facts, ref)
        self.assertEqual(
            plan["decision_arguments"],
            {
                "work_id": "work-1",
                "decision": "pending",
                "reason": "evidence-unknown",
                "rationale": "Unknown remains unresolved.",
                "evidence_refs": [ref],
                "actor": "agent",
                "authorization": None,
            },
        )
        self.assertEqual(plan["actor"], "analysis-agent")
        self.assertEqual(plan["claims"][0]["arguments"]["relation"], "contradicts")
        for field in (
            "core_events_created",
            "human_authorization",
            "researcher_acceptance",
            "scientific_acceptance",
        ):
            self.assertIs(plan[field], False)

    def test_decision_evidence_ref_passes_core_consumer_schema(self):
        snapshot, _, raw, facts, ref = inputs()
        plan = prepare(snapshot, raw, facts, ref)
        arguments = plan["decision_arguments"]
        check(
            {
                "kind": "DecisionEvent",
                "schema_version": "1.0.0",
                "event_id": "e000001",
                "run_id": "run-1",
                "stage_run_id": "stage1",
                "sequence": 1,
                "created_at": ref["created_at"],
                "actor": arguments["actor"],
                "actor_type": "agent",
                "subject_id": arguments["work_id"],
                "prior_decision": None,
                "new_decision": arguments["decision"],
                "reason_code": arguments["reason"],
                "rationale": arguments["rationale"],
                "evidence_refs": arguments["evidence_refs"],
                "reverses_event_id": None,
                "authorization": arguments["authorization"],
            },
            "DecisionEvent",
        )
        self.assertEqual(arguments["evidence_refs"], [ref])

    def test_model_cannot_inject_level_actor_or_canonical_id(self):
        snapshot, value, _, facts, ref = inputs()
        for field, injected in (
            ("evidence_level", "full-text"),
            ("actor", "human"),
            ("claim_id", "canonical-1"),
        ):
            bad = deepcopy(value)
            bad["claims"][0][field] = injected
            with self.subTest(field=field), self.assertRaises(SessionApiError):
                changed_ref = deepcopy(ref)
                changed_ref["sha256"] = sha(canonical(bad))
                changed_ref["path"] = "raw/" + changed_ref["sha256"] + ".bin"
                changed_ref["artifact_id"] = (
                    "artifact-" + changed_ref["sha256"] + "-analysis-agent"
                )
                prepare(snapshot, canonical(bad), facts, changed_ref)

    def test_source_fact_set_and_exact_fields_are_required(self):
        snapshot, _, raw, facts, ref = inputs()
        variants = ([], facts + deepcopy(facts), [{**facts[0], "extra": True}])
        for changed in variants:
            with self.subTest(changed=changed), self.assertRaises(SessionApiError):
                prepare(snapshot, raw, changed, ref)
        duplicate = deepcopy(facts) + deepcopy(facts)
        duplicate[1]["source_id"] = "source-other"
        with self.assertRaises(SessionApiError):
            prepare(snapshot, raw, duplicate, ref)

    def test_source_bindings_levels_receipts_and_core_ref_are_strict(self):
        snapshot, _, raw, facts, ref = inputs()
        changes = (
            ("work_id", "other"),
            ("version_id", "other"),
            ("evidence_level", "full-scope"),
            ("receipt_sha256", "B" * 64),
        )
        for field, value in changes:
            bad = deepcopy(facts)
            bad[0][field] = value
            with self.subTest(field=field), self.assertRaises(SessionApiError):
                prepare(snapshot, raw, bad, ref)
        for field, value in (("sha256", "c" * 64), ("path", "../text.bin")):
            bad = deepcopy(facts)
            bad[0]["text_ref"][field] = value
            with (
                self.subTest(ref_field=field),
                self.assertRaises((SessionApiError, LedgerError)),
            ):
                prepare(snapshot, raw, bad, ref)

    def test_proposal_ref_is_exact_full_core_ref(self):
        snapshot, _, raw, facts, ref = inputs()
        for field, value in (
            ("sha256", "c" * 64),
            ("path", "../analysis.json"),
            ("kind", "OtherRef"),
            ("created_at", "not-a-time"),
        ):
            bad = deepcopy(ref)
            bad[field] = value
            with (
                self.subTest(field=field, value=value),
                self.assertRaises((SessionApiError, LedgerError)),
            ):
                prepare(snapshot, raw, facts, bad)
        with self.assertRaises((SessionApiError, LedgerError)):
            prepare(snapshot, raw, facts, {**ref, "extra": True})
        normalized = {
            "path": "model/analysis.json",
            "sha256": sha(raw),
            "bytes": len(raw),
        }
        with self.assertRaises((SessionApiError, LedgerError)):
            prepare(snapshot, raw, facts, normalized)

    def test_raw_is_revalidated_and_inputs_and_outputs_are_independent(self):
        snapshot, value, raw, facts, ref = inputs()
        before = deepcopy((snapshot, facts, ref))
        plan = prepare(snapshot, raw, facts, ref)
        self.assertEqual((snapshot, facts, ref), before)
        facts[0]["text_ref"]["path"] = "changed"
        ref["path"] = "changed"
        value["claims"][0]["claim_text"] = "changed"
        self.assertNotEqual(plan["proposal_ref"]["path"], "changed")
        self.assertNotEqual(
            plan["claims"][0]["arguments"]["source_ref"]["path"], "changed"
        )
        self.assertNotEqual(plan["proposal"]["claims"][0]["claim_text"], "changed")


if __name__ == "__main__":
    unittest.main()
