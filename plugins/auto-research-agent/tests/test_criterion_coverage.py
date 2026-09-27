"""Complete routing, bounded context and fail-closed reconstruction tests."""

import json
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cli"))

from stage1_eval.common import EvaluationError, canonical, read_json, sha  # noqa: E402
from stage1_eval.coverage_plan import (  # noqa: E402
    MAX_UNIT_BYTES,
    build_coverage_plan,
    main,
    pending_manifest,
    verify_coverage_plan,
)


def packet(text, *, name="workspace-2", origin="subject-delivered-artifact"):
    evidence = {name: {"text": text, "sha256": sha(text.encode()), "origin": origin}}
    return {"content_evidence": deepcopy(evidence), "process_evidence": evidence}


def assignments(plan):
    return [key for unit in plan["units"] for key in unit["assigned_span_ids"]]


class CriterionCoverageTests(unittest.TestCase):
    def test_sized_plan_is_versioned_while_default_v1_shape_stays_unchanged(self):
        subject = packet("研究🚀" * 900)
        _, original = build_coverage_plan(subject, "process")
        self.assertEqual(original["kind"], "Stage1CriterionCoveragePlan.v1")
        self.assertNotIn("span_characters", original)
        index, sized = build_coverage_plan(
            subject, "process", max_unit_bytes=4500, span_characters=300
        )
        self.assertEqual(verify_coverage_plan(subject, sized), index)
        self.assertEqual(len(assignments(sized)), len(index))
        altered = deepcopy(sized)
        altered["span_characters"] = 900
        with self.assertRaises(EvaluationError):
            verify_coverage_plan(subject, altered)
        for invalid in (True, None, 99, 901):
            with self.assertRaises(EvaluationError):
                build_coverage_plan(subject, "process", span_characters=invalid)

    def test_all_83_spans_including_middle_and_end_are_assigned(self):
        text = "".join(f"{number:02d}:" + "x" * 895 + "\n" for number in range(83))
        subject = packet(text)
        index, plan = build_coverage_plan(subject, "process")
        self.assertEqual(len(index), 83)
        self.assertEqual(set(assignments(plan)), set(index))
        self.assertEqual(len(assignments(plan)), 83)
        self.assertGreater(len(plan["units"]), 1)
        for unit in plan["units"]:
            selected = {
                key: index[key]
                for key in [*unit["context_span_ids"], *unit["assigned_span_ids"]]
            }
            self.assertLessEqual(len(canonical(selected)), MAX_UNIT_BYTES)
        self.assertEqual(verify_coverage_plan(subject, plan), index)

    def test_three_of_83_rehash_tamper_rejected(self):
        subject = packet("z" * (900 * 83))
        _, plan = build_coverage_plan(subject, "process")
        changed = deepcopy(plan)
        changed["units"] = changed["units"][:1]
        changed["units"][0]["assigned_span_ids"] = changed["units"][0][
            "assigned_span_ids"
        ][:3]
        changed["span_count"] = 3
        # Even consistent-looking author-edited totals and a new wrapper hash
        # cannot replace obligations reconstructed from the original packet.
        for row in changed["criteria"].values():
            row["expected_unit_ids"] = [changed["units"][0]["unit_id"]]
        sha(canonical(changed))
        with self.assertRaisesRegex(EvaluationError, "full reconstructed"):
            verify_coverage_plan(subject, changed)

    def test_missing_duplicate_changed_version_or_locator_fail(self):
        subject = packet("x" * 70_000)
        subject["process_evidence"]["workspace-2"].update(
            source_version="v1", locator="paragraphs"
        )
        _, plan = build_coverage_plan(subject, "process")
        for mutation in ("missing", "duplicate", "version", "locator", "schema"):
            with self.subTest(mutation=mutation):
                changed = deepcopy(plan)
                if mutation == "missing":
                    changed["units"].pop()
                elif mutation == "duplicate":
                    changed["units"].append(deepcopy(changed["units"][0]))
                elif mutation == "schema":
                    changed["schema_version"] = "999"
                else:
                    altered = deepcopy(subject)
                    altered["process_evidence"]["workspace-2"][
                        "source_version" if mutation == "version" else "locator"
                    ] = "changed"
                    with self.assertRaises(EvaluationError):
                        verify_coverage_plan(altered, changed)
                    continue
                with self.assertRaises(EvaluationError):
                    verify_coverage_plan(subject, changed)

    def test_contrary_tail_survives_padding_format_filename_and_order(self):
        contrary = "CONTRARY: the source does not support the asserted effect."
        for padding in (0, 80_000, 160_000):
            for formatted in (False, True):
                text = "positive\n" + "irrelevant\n" * (padding // 11) + contrary
                if formatted:
                    text = json.dumps({"notes": text})
                subject = packet(
                    text, name="arbitrary.json" if formatted else "notes.md"
                )
                index, plan = build_coverage_plan(subject, "process")
                restored = "".join(index[key]["text"] for key in assignments(plan))
                self.assertEqual(restored, text)
                self.assertIn(contrary, restored)
                subject["process_evidence"]["second-file"] = {
                    "text": "another saved input",
                    "sha256": sha(b"another saved input"),
                    "origin": "subject-delivered-artifact",
                }
                _, multi_file_plan = build_coverage_plan(subject, "process")
                reversed_packet = deepcopy(subject)
                reversed_packet["process_evidence"] = dict(
                    reversed(list(subject["process_evidence"].items()))
                )
                self.assertEqual(
                    build_coverage_plan(reversed_packet, "process")[1], multi_file_plan
                )

    def test_raw_command_failure_and_decoded_output_both_have_routes(self):
        raw = json.dumps(
            {
                "item": {
                    "command": "exact args",
                    "exit_code": 1,
                    "aggregated_output": "HTTP 429",
                }
            }
        )
        subject = packet(raw, origin="subject-native-trace")
        index, plan = build_coverage_plan(subject, "process")
        self.assertEqual(
            {row["view"] for row in index.values()}, {"text", "item.aggregated_output"}
        )
        self.assertEqual(set(assignments(plan)), set(index))
        self.assertIn(
            "exit_code", "".join(index[key]["text"] for key in assignments(plan))
        )

    def test_neighbour_context_is_bound_and_never_counts_as_new_coverage(self):
        subject = packet("x" * 80_000)
        index, plan = build_coverage_plan(subject, "process", max_unit_bytes=4_000)
        self.assertTrue(any(unit["context_span_ids"] for unit in plan["units"][1:]))
        self.assertEqual(len(assignments(plan)), len(index))
        for unit in plan["units"][1:]:
            for key in unit["context_span_ids"]:
                self.assertLess(
                    index[key]["start"], index[unit["assigned_span_ids"][0]]["start"]
                )

    def test_unicode_budget_and_pending_plan_never_claim_completed_reading(self):
        subject = packet("研究记录与反证\n" * 12_000)
        _, plan = build_coverage_plan(subject, "process")
        manifest = pending_manifest(subject, plan)
        self.assertEqual(manifest["status"], "pending")
        for row in manifest["criteria"].values():
            self.assertEqual(row["completed_unit_ids"], [])
            self.assertEqual(row["pending_unit_ids"], row["expected_unit_ids"])
        for value in (True, 3_999, 60_001, None):
            with self.assertRaises(EvaluationError):
                build_coverage_plan(subject, "process", max_unit_bytes=value)

    def test_cli_preserves_existing_output_and_reports_empty_evidence_pending(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, output = root / "packet.json", root / "output"
            source.write_bytes(canonical(packet("")))
            self.assertEqual(main([str(source), str(output), "--phase", "process"]), 0)
            saved = (output / "coverage-plan.json").read_bytes()
            self.assertEqual(
                read_json(output / "coverage-manifest.json")["status"], "pending"
            )
            self.assertEqual(main([str(source), str(output), "--phase", "process"]), 1)
            self.assertEqual((output / "coverage-plan.json").read_bytes(), saved)

    def test_cli_bad_or_missing_input_is_evaluator_error_without_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, output = root / "packet.json", root / "output"
            for text in (None, "{broken", "{}"):
                if text is not None:
                    source.write_text(text, encoding="utf-8")
                self.assertEqual(
                    main([str(source), str(output), "--phase", "content"]), 1
                )
                self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
