"""Offline direction admission; no job layer, model or research execution."""

# ruff: noqa: E402 -- repository fixture imports.

from copy import deepcopy
from pathlib import Path
import sys
import unittest

PLUGIN = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(PLUGIN / "cli"), str(PLUGIN / "tests")]

from stage3_direction_fixtures import DirectionFixture
from stage3_plan.contracts import Stage3Error, canonical_bytes
from stage3_plan.context_projection import pack_context, expand_context, REF, LITERAL
from stage3_plan.direction_intent import build_direction_prompt
from stage3_plan.prompts import MAX_CONTEXT_BYTES
from stage3_plan.storage import read_json


class Stage3DirectionIntentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.direction = DirectionFixture(cls.addClassCleanup)

    def test_zero_recommendations_keeps_real_questions_and_unknowns(self):
        before = {
            p: p.read_bytes() for p in self.direction.delivery.rglob("*") if p.is_file()
        }
        context = self.direction.admit(self.direction.source())
        self.assertEqual(context["recommendations"], [])
        self.assertEqual(context["selected_options"], [])
        self.assertEqual(context["human_selection"], "pending")
        self.assertIs(context["formal_selected_receiver"], False)
        self.assertIs(context["execution_authorized"], False)
        self.assertEqual(
            context["questions"][0]["text"],
            "How do participants explain the recorded process?",
        )
        self.assertIsNone(
            context["preferred_options"][0]["assessment"]["checks"]["materials"][
                "score"
            ]
        )
        self.assertEqual(context["unresolved"], self.direction.intent["unresolved"])
        self.assertTrue(context["evidence"])
        prompt = build_direction_prompt(context)
        self.assertIn(self.direction.intent["user_input"], prompt)
        self.assertEqual(before, {p: p.read_bytes() for p in before})

    def test_stale_direction_and_changed_user_text_are_rejected(self):
        changed = deepcopy(self.direction.intent)
        changed["preferred_directions"][0]["candidate_version"] = 99
        with self.assertRaisesRegex(Stage3Error, "absent"):
            self.direction.admit(self.direction.source(changed))
        source = self.direction.source()
        source["intent"]["user_input"] += " changed after receipt"
        with self.assertRaisesRegex(Stage3Error, "external hash"):
            self.direction.admit(source)

    def test_rehashed_authority_and_wrong_delivery_are_rejected(self):
        changed = deepcopy(self.direction.intent)
        changed["execution_authorized"] = True
        with self.assertRaisesRegex(Stage3Error, "non-authorizing"):
            self.direction.admit(self.direction.source(changed))
        source = self.direction.source()
        source["delivery_manifest_sha256"] = "0" * 64
        with self.assertRaisesRegex(Stage3Error, "source pins"):
            self.direction.admit(source)

    def test_missing_mapping_prepares_no_prompt(self):
        context = self.direction.admit(self.direction.source())
        context["missing_mapping"] = [{"reason": "No source scientific question."}]
        with self.assertRaisesRegex(Stage3Error, "needs-information"):
            build_direction_prompt(context)

    def test_source_unknowns_remain_distinct_from_user_conditions(self):
        context = self.direction.admit(self.direction.source())
        selection = read_json(self.direction.delivery / "selection.json")
        self.assertEqual(
            context["source_unresolved"], selection["evaluation_packet"]["unresolved"]
        )
        self.assertEqual(
            context["pending_scope_questions"], selection["pending_scope_questions"]
        )
        self.assertNotEqual(context["source_unresolved"], context["unresolved"])
        self.assertIn(
            "Packet-only access condition, distinct from user text.",
            build_direction_prompt(context),
        )

    def test_workflow_manifest_binding_rejects_an_altered_intent(self):
        changed = deepcopy(self.direction.intent)
        changed["workflow_manifest_sha256"] = "0" * 64
        with self.assertRaisesRegex(Stage3Error, "workflow manifest"):
            self.direction.admit(self.direction.source(changed))

    def test_oversize_context_cannot_prepare_a_prompt(self):
        context = self.direction.admit(self.direction.source())
        context["user_input"] = "x" * MAX_CONTEXT_BYTES
        with self.assertRaisesRegex(Stage3Error, "context bound"):
            build_direction_prompt(context)


class ContextProjectionTests(unittest.TestCase):
    def test_repeated_source_values_and_reserved_keys_round_trip(self):
        text = "Source wording and access unknown. " * 20
        source = {
            "questions": [text, text],
            "repeated_records": [{"wording": text, "unknown": None}] * 2,
            "literal": {REF: text},
            "nested": {LITERAL: [[REF, {"false": False, "null": None, "zero": 0}]]},
        }
        packed = pack_context(source)
        self.assertEqual(expand_context(packed), source)
        self.assertLess(len(canonical_bytes(packed)), len(canonical_bytes(source)))

    def test_changed_shared_values_missing_refs_and_cycles_are_rejected(self):
        packed = pack_context(["Original source. " * 20] * 2)
        for value in ({REF: "absent"}, {REF: 0}, {REF: False}, {REF: -1}):
            changed = deepcopy(packed)
            changed["data"] = value
            if value[REF] == 0:
                changed["shared"][0] = value
            with self.subTest(value=value), self.assertRaises(Stage3Error):
                expand_context(changed)
        changed = deepcopy(packed)
        changed["shared"][0] = "Changed wording."
        with self.assertRaisesRegex(Stage3Error, "hash differs"):
            expand_context(changed)


if __name__ == "__main__":
    unittest.main()
