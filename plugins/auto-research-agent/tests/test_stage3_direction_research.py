"""Authored offline evidence and independent design-review integration checks."""

# ruff: noqa: E402 -- repository fixture imports.

from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

PLUGIN = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(PLUGIN / "cli"), str(PLUGIN / "tests")]

from stage3_direction_fixtures import DirectionFixture
from stage3_plan.contracts import Stage3Error, canonical_bytes, digest
from stage3_plan.jobs import _ref
from stage3_plan.storage import read_json, write_new
from test_stage3_direction_jobs import authored_result


class _DirectionResearchFixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.direction = DirectionFixture(cls.addClassCleanup)

    def setUp(self):
        self.root = self.direction.fixture.root / self._testMethodName
        self.root.mkdir()
        self.context = self.direction.admit(self.direction.source())
        self.needs = [
            {
                "id": "access-basis",
                "question_ref": self.context["questions"][0]["question_ref"],
                "requirement": "Document lawful material access before interpretation.",
                "design_decision": "Decide whether independent interpretation is possible.",
            }
        ]
        self.planner_calls = []
        self.reviewer_calls = []
        self.plan = authored_result(self.context)
        self.plan["markdown"] = (
            "Only the delivered Markdown contains this staffing limitation."
        )

    def binding(self, *, lookup=None):
        from stage3_plan.direction_research import prepare_direction_evidence

        return prepare_direction_evidence(
            self.context, self.needs, self.root / "evidence.json", lookup=lookup
        )

    def callbacks(self, *, reviewer_error=None):
        def planner(**request):
            self.planner_calls.append(request)
            return {
                "raw_response": canonical_bytes(self.plan),
                "provenance": {"kind": "authored-planner-offline-stub"},
            }

        def reviewer(**request):
            self.reviewer_calls.append(request)
            if reviewer_error is not None:
                raise reviewer_error
            return {
                "raw_response": canonical_bytes(self.review()),
                "provenance": {"kind": "authored-reviewer-offline-stub"},
            }

        planner.request_context = {
            "kind": "authored-planner-offline-stub",
            "timeout_seconds": 1,
            "capture_dir": str(self.root / "planner-capture"),
        }
        reviewer.request_context = {
            "kind": "authored-reviewer-offline-stub",
            "timeout_seconds": 1,
            "capture_dir": str(self.root / "reviewer-capture"),
        }
        return planner, reviewer

    def adapter(self, *, binding=None, reviewer_error=None):
        from stage3_plan.direction_research import DirectionResearchAdapter

        planner, reviewer = self.callbacks(reviewer_error=reviewer_error)
        return DirectionResearchAdapter(
            planner, reviewer, evidence=self.binding() if binding is None else binding
        )

    def review(self):
        return {
            "kind": "Stage3DirectionDesignReview",
            "intent_sha256": self.context["intent_sha256"],
            "plan_sha256": digest(self.plan),
            "question_reviews": [
                {
                    "question_ref": question["question_ref"],
                    "answerability": "unknown",
                    "reason": "Authored assessment: lawful material access remains unknown.",
                    "supported_scope": "A proposed interpretation protocol only.",
                    "revision": "Verify lawful access before making an empirical claim.",
                }
                for question in self.context["questions"]
            ],
        }

    def review_data(self, prompt):
        from stage3_plan.context_projection import expand_context

        data = json.loads(prompt.split("UNTRUSTED_RESEARCH_DESIGN\n", 1)[1])
        if data.get("kind") == "Stage3SharedPlanningContext":
            return expand_context(data)
        return data


class Stage3DirectionResearchTests(_DirectionResearchFixture):
    def test_overbound_lookup_input_is_rejected_before_any_callback(self):
        from stage3_plan.direction_research import prepare_direction_evidence
        from stage3_plan.prompts import MAX_CONTEXT_BYTES
        from stage3_plan.storage import MAX_ARTIFACT_BYTES

        calls = []

        def lookup(need):
            calls.append(need["id"])
            return {
                "need_id": need["id"],
                "status": "unresolved",
                "finding": "Not acquired.",
                "limits": "Authored limitation.",
                "sources": [],
            }

        for i, size in enumerate((MAX_CONTEXT_BYTES + 1, MAX_ARTIFACT_BYTES + 1)):
            needs = deepcopy(self.needs)
            needs[0]["requirement"] = "x" * size
            output = self.root / f"oversized-{i}.json"
            with self.assertRaises(Stage3Error):
                prepare_direction_evidence(self.context, needs, output, lookup=lookup)
            self.assertEqual(calls, [])
            self.assertFalse(output.exists())

    def test_overbound_findings_stop_before_the_next_lookup(self):
        from stage3_plan.direction_research import prepare_direction_evidence
        from stage3_plan.storage import MAX_ARTIFACT_BYTES

        calls = []
        needs = deepcopy(self.needs)
        needs.append({**needs[0], "id": "second-gap"})

        def lookup(need):
            calls.append(need["id"])
            return {
                "need_id": need["id"],
                "status": "unresolved",
                "finding": "x" * (MAX_ARTIFACT_BYTES + 1),
                "limits": "Authored.",
                "sources": [],
            }

        output = self.root / "large-findings.json"
        with self.assertRaises(Stage3Error):
            prepare_direction_evidence(self.context, needs, output, lookup=lookup)
        self.assertEqual(calls, [needs[0]["id"]])
        self.assertFalse(output.exists())

    def test_capture_alias_cannot_share_the_planner_directory(self):
        from stage3_plan.direction_research import DirectionResearchAdapter

        planner, reviewer = self.callbacks()
        (self.root / "alias").mkdir()
        reviewer.request_context["capture_dir"] = str(
            self.root / "alias" / ".." / "planner-capture"
        )
        with self.assertRaises(Stage3Error):
            DirectionResearchAdapter(
                planner, reviewer, evidence=self.binding()
            ).request_context

    def test_review_prompt_includes_entire_delivery_and_source_conditions(self):
        from stage3_plan.direction_research import (
            build_design_review_prompt,
            research_context,
        )

        adapter = self.adapter()
        context = research_context(self.context, adapter.request_context)
        prompt = build_design_review_prompt(self.plan, context)
        self.assertEqual(self.review_data(prompt)["delivered_plan"], self.plan)
        self.assertIn(self.plan["markdown"], prompt)
        self.assertIn(self.context["source_unresolved"][0], prompt)
        self.assertIn(self.context["unresolved"][0], prompt)
        self.assertIn(self.needs[0]["requirement"], prompt)
        self.assertEqual(self.context, self.direction.admit(self.direction.source()))
        self.assertEqual((self.planner_calls, self.reviewer_calls), ([], []))

    def test_no_lookup_packet_preserves_unknowns_and_explicit_profile(self):
        from stage3_plan.direction_research import research_context

        adapter = self.adapter()
        binding = adapter.request_context["direction_research"]["evidence"]
        packet = read_json(binding["path"])
        self.assertIs(packet["lookup_enabled"], False)
        self.assertEqual(packet["findings"], [])
        context = research_context(self.context, adapter.request_context)
        self.assertEqual(context["direction_prompt_profile"], "source-design-v1")
        self.assertEqual(
            context["source_unresolved"], self.context["source_unresolved"]
        )
        self.assertEqual(context["unresolved"], self.context["unresolved"])
        self.assertEqual(context["evidence"], self.context["evidence"])
        self.assertNotIn("direction_core_route", context)
        with self.assertRaises(Stage3Error):
            changed = deepcopy(adapter.request_context)
            changed["direction_research"]["prompt_profile"] = "unknown-profile"
            research_context(self.context, changed)

    def test_lookup_projects_receipt_hash_and_preserves_supplemental_limits(self):
        from stage3_plan.direction_research import (
            build_design_review_prompt,
            research_context,
        )

        receipt = self.root / "source-receipt.json"
        url = "https://example.org/qualitative-access-documentation"
        write_new(receipt, {"kind": "Stage3PublicSourceLookupReceipt", "url": url})
        calls = []

        def lookup(need):
            calls.append(deepcopy(need))
            return {
                "need_id": need["id"],
                "status": "limited",
                "finding": "Authored documentation locator; access is not established.",
                "limits": "An index entry does not establish lawful access or material fit.",
                "sources": [
                    {
                        "title": "Authored access documentation",
                        "url": url,
                        "locator": "Access conditions",
                        "receipt": _ref(receipt),
                    }
                ],
            }

        adapter = self.adapter(binding=self.binding(lookup=lookup))
        context = research_context(self.context, adapter.request_context)
        finding = context["direction_research_evidence"]["findings"][0]
        self.assertEqual(calls, self.needs)
        self.assertEqual(finding["status"], "limited")
        self.assertIn("does not establish lawful access", finding["limits"])
        self.assertEqual(
            finding["sources"][0]["receipt_sha256"], _ref(receipt)["sha256"]
        )
        self.assertNotIn("receipt", finding["sources"][0])
        self.assertEqual(
            context["source_unresolved"], self.context["source_unresolved"]
        )
        data = self.review_data(build_design_review_prompt(self.plan, context))
        self.assertEqual(
            data["research_evidence"]["findings"][0]["limits"], finding["limits"]
        )

    def test_tampered_packet_receipt_or_frontier_is_rejected(self):
        from stage3_plan.direction_research import research_context

        receipt = self.root / "source-receipt.json"
        url = "https://example.org/access"
        write_new(receipt, {"kind": "Stage3PublicSourceLookupReceipt", "url": url})

        def lookup(need):
            return {
                "need_id": need["id"],
                "status": "limited",
                "finding": "Authored source locator only.",
                "limits": "Permission remains unknown.",
                "sources": [
                    {
                        "title": "Access",
                        "url": url,
                        "locator": "Index",
                        "receipt": _ref(receipt),
                    }
                ],
            }

        binding = self.binding(lookup=lookup)
        adapter = self.adapter(binding=binding)
        original_context = adapter.request_context
        bad_hash = deepcopy(original_context)
        bad_hash["direction_research"]["evidence"]["sha256"] = "0" * 64
        with self.assertRaises(Stage3Error):
            research_context(self.context, bad_hash)

        packet_path = Path(binding["path"])
        original_packet = read_json(packet_path)
        changed = deepcopy(original_packet)
        changed["intent_sha256"] = "0" * 64
        packet_path.write_bytes(canonical_bytes(changed))
        rehashed = deepcopy(original_context)
        rehashed["direction_research"]["evidence"] = _ref(packet_path)
        with self.assertRaises(Stage3Error):
            research_context(self.context, rehashed)

        packet_path.write_bytes(canonical_bytes(original_packet))
        receipt.write_bytes(
            canonical_bytes(
                {"kind": "Stage3PublicSourceLookupReceipt", "url": url + "/changed"}
            )
        )
        with self.assertRaises(Stage3Error):
            research_context(self.context, original_context)

    def test_review_rejects_wrong_plan_question_duplicates_and_missing_assessment(self):
        from stage3_plan.direction_research import validate_design_review

        review = self.review()
        self.assertEqual(
            validate_design_review(review, self.plan, self.context), review
        )
        variants = []
        wrong_plan = deepcopy(review)
        wrong_plan["plan_sha256"] = "0" * 64
        variants.append(wrong_plan)
        wrong_question = deepcopy(review)
        wrong_question["question_reviews"][0]["question_ref"] = "foreign@1/q0"
        variants.append(wrong_question)
        duplicate = deepcopy(review)
        duplicate["question_reviews"].append(deepcopy(duplicate["question_reviews"][0]))
        variants.append(duplicate)
        missing = deepcopy(review)
        missing["question_reviews"] = []
        variants.append(missing)
        for index, value in enumerate(variants):
            with self.subTest(index=index), self.assertRaises(Stage3Error):
                validate_design_review(value, self.plan, self.context)

    def test_planner_and_review_callbacks_and_capture_contexts_are_independent(self):
        from stage3_plan.direction_research import DirectionResearchAdapter

        binding = self.binding()
        planner, reviewer = self.callbacks()
        with self.assertRaises(Stage3Error):
            DirectionResearchAdapter(planner, planner, evidence=binding)
        reviewer.request_context = deepcopy(planner.request_context)
        with self.assertRaises(Stage3Error):
            DirectionResearchAdapter(
                planner, reviewer, evidence=binding
            ).request_context
        reviewer.request_context["kind"] = "authored-distinct-reviewer-stub"
        with self.assertRaises(Stage3Error):
            DirectionResearchAdapter(
                planner, reviewer, evidence=binding
            ).request_context
        self.assertEqual((self.planner_calls, self.reviewer_calls), ([], []))


if __name__ == "__main__":
    unittest.main()
