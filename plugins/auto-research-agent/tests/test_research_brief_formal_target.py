"""Formal-count intake is explicit and separate from scientific adequacy."""

from contextlib import redirect_stdout
from copy import deepcopy
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cli"))
from stage1_brief.__main__ import main
from stage1_brief.brief import (
    create_brief,
    compile_confirmed,
    validate_bound_plan,
    validate_brief,
)
from stage1_brief.formal_target import (
    formal_question,
    formal_selection_progress,
    prepare_formal_intake,
    submit_formal_target,
)
from test_research_brief import brief, search_request


def intake():
    return prepare_formal_intake(
        brief("unrestricted"),
        project_id="project-a",
        input_version="input-1",
        request_id="request-1",
    )


def answer(target=30):
    return {
        "event_id": "formal-1",
        "project_id": "project-a",
        "input_version": "input-1",
        "request_id": "request-1",
        "status": "submitted",
        "target": target,
        "actor": "test-user",
        "authority": "user",
        "provenance": "user-attested",
        "user_input": "Use 30 formally usable distinct works.",
        "source_ref": "test-turn:2",
        "recorded_at": "2026-10-08T12:00:00Z",
    }


class FormalTargetTests(unittest.TestCase):
    def cli(self, *arguments):
        stream = io.StringIO()
        with redirect_stdout(stream):
            status = main(list(map(str, arguments)))
        return status, json.loads(stream.getvalue())

    def test_duplicate_answer_json_keys_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pending, submitted, output = [
                root / name
                for name in ("pending.json", "answer.json", "confirmed.json")
            ]
            create_brief(intake(), pending)
            submitted.write_text(
                json.dumps(answer()).replace(
                    '"target": 30,', '"target": 30, "target": 30,'
                ),
                encoding="utf-8",
            )
            code, report = self.cli("submit-formal-target", pending, submitted, output)
            self.assertEqual(code, 1)
            self.assertIn("duplicate-json-key", report["error"])
            self.assertFalse(output.exists())

    def test_invalid_formal_revision_returns_structured_cli_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            previous = root / "previous.json"
            create_brief(intake(), previous)
            for ordinal, invalid in enumerate((None, [], "bad-record", 30)):
                with self.subTest(value=invalid):
                    revised = intake()
                    revised["formal_final_count"] = invalid
                    request, output = (
                        root / f"request-{ordinal}.json",
                        root / f"out-{ordinal}.json",
                    )
                    request.write_text(json.dumps(revised), encoding="utf-8")
                    code, report = self.cli(
                        "record", request, output, "--previous", previous
                    )
                    self.assertEqual(code, 1)
                    self.assertFalse(report["valid"])
                    self.assertIn("formal count must be an object", report["error"])
                    self.assertFalse(output.exists())

    def test_new_pending_submitted_then_compiled_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            request, pending, confirmed, submission = [
                root / name
                for name in (
                    "request.json",
                    "pending.json",
                    "confirmed.json",
                    "answer.json",
                )
            ]
            request.write_text(json.dumps(brief("unrestricted")), encoding="utf-8")
            code, report = self.cli(
                "intake",
                request,
                pending,
                "--project-id",
                "project-a",
                "--input-version",
                "input-1",
                "--request-id",
                "request-1",
            )
            self.assertEqual(code, 0)
            self.assertFalse(report["necessary_clarification_complete"])
            self.assertEqual(report["formal_final_count"]["target"], None)
            question = self.cli("formal-question", pending)[1]
            self.assertEqual(question["proposed_target"], 30)
            self.assertEqual(question["request_id"], "request-1")
            self.assertIn("formally usable distinct works", question["question"])
            with self.assertRaisesRegex(ValueError, "formal_final_count"):
                compile_confirmed(
                    pending,
                    search_request(),
                    root / "blocked",
                    as_of="2026-09-26",
                    actor="test",
                )
            self.assertFalse((root / "blocked").exists())
            original = pending.read_bytes()
            submission.write_text(json.dumps(answer()), encoding="utf-8")
            self.assertEqual(
                self.cli("submit-formal-target", pending, submission, confirmed)[0], 0
            )
            self.assertEqual(pending.read_bytes(), original)
            result = compile_confirmed(
                confirmed,
                search_request(),
                root / "plan",
                as_of="2026-09-26",
                actor="test",
            )
            self.assertEqual(
                result["intake_metrics"]["formal_final_count"]["target"], 30
            )
            self.assertTrue(validate_bound_plan(root / "plan", confirmed)["valid"])
            binding_path = root / "plan/research_brief_binding.json"
            bound = json.loads(binding_path.read_text(encoding="utf-8"))
            self.assertEqual(bound["schema_version"], "1.1.0")
            self.assertEqual(len(bound["formal_final_count_sha256"]), 64)
            self.assertTrue(
                all(
                    not row["scope_filters"]
                    for row in bound["request"]["query_bindings"]
                )
            )
            bound["formal_final_count_sha256"] = "0" * 64
            binding_path.write_text(json.dumps(bound), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "formal count binding changed"):
                validate_bound_plan(root / "plan", confirmed)

    def test_wrong_project_stale_version_request_or_silent_answer_rejected(self):
        for key, value in (
            ("project_id", "project-b"),
            ("input_version", "input-2"),
            ("request_id", "request-2"),
            ("status", "default"),
            ("authority", "system"),
            ("source_ref", ""),
            ("user_input", " "),
            ("recorded_at", "2026-10-08"),
            ("provenance", "authenticated"),
        ):
            submitted = answer()
            submitted[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                submit_formal_target(intake(), submitted)
        with self.assertRaises(ValueError):
            submit_formal_target(intake(), {})

    def test_quantity_requires_positive_integer_in_proposal_and_answer(self):
        for value in (True, False, 0, -1, 30.0, "30", None):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    prepare_formal_intake(
                        brief(),
                        project_id="project-a",
                        input_version="input-1",
                        request_id="request-1",
                        proposed_target=value,
                    )
                with self.assertRaises(ValueError):
                    submit_formal_target(intake(), answer(value))

    def test_answer_revision_is_append_only_and_original_description_is_immutable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first, second = root / "first.json", root / "second.json"
            confirmed = submit_formal_target(intake(), answer())
            create_brief(confirmed, first)
            revised_answer = answer(35)
            revised_answer.update(
                event_id="formal-2", user_input="Use 35 formally usable works."
            )
            revised = submit_formal_target(confirmed, revised_answer)
            create_brief(revised, second, first)
            self.assertEqual(
                [row["target"] for row in revised["formal_final_count"]["decisions"]],
                [30, 35],
            )
            for mutate in ("history", "description"):
                bad = deepcopy(revised)
                if mutate == "history":
                    bad["formal_final_count"]["decisions"][0]["user_input"] = (
                        "rewritten"
                    )
                else:
                    bad["original_description"] = "rewritten"
                with self.subTest(mutate=mutate), self.assertRaises(ValueError):
                    create_brief(bad, root / (mutate + ".json"), first)

    def test_legacy_brief_and_plan_replay_are_not_stamped(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            old = brief("unrestricted")
            path = root / "old.json"
            create_brief(old, path)
            before = path.read_bytes()
            compile_confirmed(
                path, search_request(), root / "plan", as_of="2026-09-26", actor="test"
            )
            self.assertTrue(validate_bound_plan(root / "plan", path)["valid"])
            self.assertEqual(before, path.read_bytes())
            self.assertNotIn("formal_final_count", validate_brief(old))
            self.assertEqual(json.loads(before)["schema_version"], "1.0.0")
            with self.assertRaises(ValueError):
                formal_question(old)

    def test_progress_deduplicates_works_and_preserves_versions(self):
        confirmed = submit_formal_target(intake(), answer())
        selection = {
            "project_id": "project-a",
            "input_version": "input-1",
            "rows": [
                {"work_id": "work-a", "version_id": "v1", "status": "included"},
                {"work_id": "work-a", "version_id": "v2", "status": "included"},
                {"work_id": "work-b", "version_id": "v1", "status": "pending"},
                {"work_id": "work-c", "version_id": "v1", "status": "excluded"},
            ],
        }
        original = deepcopy(selection)
        report = formal_selection_progress(confirmed, selection)
        self.assertEqual(selection, original)
        self.assertEqual(report["formally_usable_distinct_works"], 1)
        self.assertEqual(report["included_version_row_count"], 2)
        self.assertEqual(report["target_shortfall"], 29)
        self.assertEqual(report["action"], "continue-target")
        selection["rows"] = [
            {"work_id": f"work-{i}", "status": "included"} for i in range(30)
        ]
        report = formal_selection_progress(confirmed, selection)
        self.assertTrue(report["formal_target_met"])
        for field in (
            "scientific_sufficiency",
            "coverage",
            "stop_decision",
            "stage2_eligibility",
        ):
            self.assertEqual(report[field], "not-assessed")

    def test_progress_binding_and_invalid_rows_rejected(self):
        confirmed = submit_formal_target(intake(), answer())
        for key, value in (
            ("project_id", "project-b"),
            ("input_version", True),
            ("rows", None),
            ("rows", [{"work_id": "", "status": "included"}]),
            ("rows", [{"work_id": "a", "status": "INCLUDED"}]),
        ):
            selection = {
                "project_id": "project-a",
                "input_version": "input-1",
                "rows": [],
            }
            selection[key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                formal_selection_progress(confirmed, selection)
