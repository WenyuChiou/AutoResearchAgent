"""Scope intake behavior is separate from scientific literature scores."""

import json
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cli"))
from stage1_brief.brief import (
    compile_confirmed,
    create_brief,
    validate_bound_plan,
    validate_brief,
    validate_search_request,
)
from test_stage1_coverage import proposal


def brief(status="pending", value=None):
    return {
        "kind": "ResearchBrief",
        "schema_version": "1.0.0",
        "original_description": "Study aging and household consumption with agent feedback.",
        "needs": [
            {
                "need_id": "consumption",
                "question": "How do household states and consumption interact?",
            }
        ],
        "scope_fields": [
            {
                "field": "geography",
                "material": True,
                "reason": "Data and household institutions depend on place.",
            }
        ],
        "suggestions": [],
        "decisions": []
        if status == "pending"
        else [
            {
                "event_id": "decision-1",
                "field": "geography",
                "status": status,
                "value": value,
                "actor": "test-user",
                "authority": "user",
                "user_input": "Keep the search broad" if value is None else value,
                "source_ref": "test-conversation:turn-1",
                "recorded_at": "2026-09-26T12:00:00Z",
            }
        ],
    }


def search_request():
    return {
        "proposal": proposal(),
        "query_bindings": [
            {
                "family_id": f"family-{i}",
                "need_ids": ["consumption"],
                "purpose": "study-evidence",
                "scope_filters": {},
            }
            for i in range(1, 5)
        ],
    }


class ResearchBriefTests(unittest.TestCase):
    def test_declared_filter_reaches_all_compiled_query_variants(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            create_brief(brief("specified", "chosen-place"), root / "brief.json")
            request = search_request()
            request["query_bindings"][0]["scope_filters"] = {
                "geography": "chosen-place"
            }
            request["query_bindings"][1].update(
                purpose="transferable-method",
                scope_filters={"geography": "comparator-place"},
                transfer_rationale="Independent methods evidence",
            )
            compile_confirmed(
                root / "brief.json",
                request,
                root / "plan",
                as_of="2026-09-26",
                actor="test",
            )
            rows = [
                json.loads(line)
                for line in (root / "plan/query_plan.jsonl").read_text().splitlines()
            ]
            for row in rows:
                expected = {
                    "family-1": "chosen-place",
                    "family-2": "comparator-place",
                }.get(row["family_id"])
                if expected:
                    self.assertIn('"' + expected + '"', row["query"])
            self.assertTrue(
                validate_bound_plan(root / "plan", root / "brief.json")["valid"]
            )

    def test_unspecified_never_compiles_implicit_country(self):
        value = brief()
        self.assertEqual(validate_brief(value)["pending_fields"], ["geography"])
        for country in ("South Korea", "Canada", "United States"):
            request = search_request()
            request["query_bindings"][0]["scope_filters"] = {"geography": country}
            with (
                self.subTest(country=country),
                self.assertRaisesRegex(ValueError, "clarification incomplete"),
            ):
                validate_search_request(value, request)

    def test_specified_region_preserved(self):
        request = search_request()
        request["query_bindings"][0]["scope_filters"] = {"geography": "chosen-place"}
        result = validate_search_request(brief("specified", "chosen-place"), request)
        self.assertTrue(result["necessary_clarification_complete"])
        request["query_bindings"][0]["scope_filters"]["geography"] = "another-place"
        with self.assertRaisesRegex(ValueError, "unauthorized scope narrowing"):
            validate_search_request(brief("specified", "chosen-place"), request)

    def test_explicit_unrestricted_persists(self):
        value = brief("unrestricted")
        request = search_request()
        self.assertEqual(
            validate_search_request(value, request)[
                "unauthorized_scope_narrowing_count"
            ],
            0,
        )
        request["query_bindings"][0]["scope_filters"] = {"geography": "any-place"}
        with self.assertRaisesRegex(ValueError, "unauthorized scope narrowing"):
            validate_search_request(value, request)

    def test_suggestions_are_not_decisions(self):
        value = brief("recommendations-requested")
        value["suggestions"] = [
            {
                "suggestion_id": "s1",
                "field": "geography",
                "value": "candidate-place",
                "literature_basis": "published studies",
                "data_basis": "public survey",
                "validation_basis": "held-out years",
                "source_refs": ["source-1"],
            }
        ]
        self.assertFalse(validate_brief(value)["necessary_clarification_complete"])
        value["suggestions"][0]["source_refs"] = []
        with self.assertRaisesRegex(ValueError, "feasibility evidence"):
            validate_brief(value)

    def test_method_comparator_does_not_change_case(self):
        request = search_request()
        request["query_bindings"][0].update(
            purpose="transferable-method",
            scope_filters={"geography": "comparison-place"},
            transfer_rationale="Population weighting method transfers; study remains chosen-place.",
        )
        report = validate_search_request(brief("specified", "chosen-place"), request)
        self.assertEqual(report["scope"]["geography"]["value"], "chosen-place")

    def test_region_irrelevant_does_not_force_choice(self):
        value = brief()
        value["scope_fields"][0].update(
            material=False, reason="Pure mathematical method"
        )
        self.assertTrue(
            validate_brief(value, require_confirmed=True)[
                "necessary_clarification_complete"
            ]
        )

    def test_revision_keeps_history_and_invalidates_old_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first, second = root / "brief1.json", root / "brief2.json"
            create_brief(brief("unrestricted"), first)
            compile_confirmed(
                first, search_request(), root / "plan", as_of="2026-09-26", actor="test"
            )
            self.assertTrue(validate_bound_plan(root / "plan", first)["valid"])
            updated = json.loads(first.read_text(encoding="utf-8"))
            event = deepcopy(updated["decisions"][0])
            event.update(
                event_id="decision-2",
                status="specified",
                value="new-place",
                user_input="Use new-place",
            )
            updated["decisions"].append(event)
            create_brief(updated, second, first)
            with self.assertRaisesRegex(ValueError, "different brief revision"):
                validate_bound_plan(root / "plan", second)
            updated["decisions"][0]["user_input"] = "rewritten"
            with self.assertRaisesRegex(ValueError, "append-only"):
                create_brief(updated, root / "bad.json", first)

    def test_missing_provenance_and_need_mapping_rejected(self):
        value = brief("unrestricted")
        value["decisions"][0]["source_ref"] = ""
        with self.assertRaisesRegex(ValueError, "provenance"):
            validate_brief(value)
        request = search_request()
        request["query_bindings"][0]["need_ids"] = []
        with self.assertRaisesRegex(ValueError, "research need"):
            validate_search_request(brief("unrestricted"), request)

    def test_blank_provenance_and_invalid_timestamp_rejected(self):
        for key, bad in (
            ("actor", "  "),
            ("source_ref", " "),
            ("recorded_at", "not-a-time"),
            ("recorded_at", "2026-09-26T00:00:00"),
        ):
            value = brief("unrestricted")
            value["decisions"][0][key] = bad
            with self.subTest(key=key, bad=bad), self.assertRaises(ValueError):
                validate_brief(value)

    def test_rebinding_known_needs_without_regenerating_plan_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            value = brief("unrestricted")
            value["needs"].append(
                {"need_id": "methods", "question": "Which methods transfer?"}
            )
            create_brief(value, root / "brief.json")
            compile_confirmed(
                root / "brief.json",
                search_request(),
                root / "plan",
                as_of="2026-09-26",
                actor="test",
            )
            path = root / "plan/research_brief_binding.json"
            binding = json.loads(path.read_text())
            binding["request"]["query_bindings"][0]["need_ids"] = ["methods"]
            path.write_text(json.dumps(binding), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "different proposal"):
                validate_bound_plan(root / "plan", root / "brief.json")
