"""Offline Stage 2 checker behavior and source/history binding tests."""

import copy
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
import sys

from jsonschema import Draft202012Validator

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cli"))
from stage2_check import apply_assessment, export_selection, initialize_run, inspect_run
from stage2_check.__main__ import main
from stage2_common import Stage2Error, canonical_hash, validate_packet
from stage2_fixture_helpers import write_stage2_fixture


SCHEMA = Path(__file__).resolve().parents[1] / "schemas/stage2-check.v1.schema.json"
SHARED_SCHEMA = (
    Path(__file__).resolve().parents[1] / "schemas/stage-contracts.v1.schema.json"
)


def finding(status="assessed", score=2, *, evidence_ids=None, blocking=False):
    return {
        "status": status,
        "score": score,
        "rationale": (
            "The bound synthetic source supports this limited design judgment."
            if status == "assessed"
            else "The supplied source does not establish this axis."
        ),
        "evidence_ids": ["ev-1"] if evidence_ids is None else evidence_ids,
        "blocking": blocking,
        "next_check": "Obtain the missing bounded measurement."
        if status == "unknown"
        else None,
    }


def assessment(packet, *, event_id="check-1", disposition="recommend", version=1):
    return {
        "kind": "Stage2Check",
        "schema_version": "1.0.0",
        "event_id": event_id,
        "candidate_id": "candidate-1",
        "candidate_version": version,
        "packet_sha256": canonical_hash(packet),
        "checks": {
            axis: finding()
            for axis in (
                "opportunity",
                "value",
                "answerability",
                "materials",
                "execution",
            )
        },
        "disposition": disposition,
        "reason": "A source-bound semantic assessor recorded this bounded judgment.",
        "next_step": "Collect the specified evidence."
        if disposition in {"revise", "park"}
        else None,
        "scope_change_requested": False,
    }


class Stage2CheckerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.sources = self.root / "sources"
        self.packet = write_stage2_fixture(self.sources, candidate_count=1)
        self.packet["unresolved"] = []
        self.packet_path = self.root / "packet.json"
        self.write(self.packet_path, self.packet)
        self.run = self.root / "run"

    @staticmethod
    def write(path, value):
        path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")

    def apply(self, value, name="assessment.json"):
        path = self.root / name
        self.write(path, value)
        return apply_assessment(self.run, path)

    def test_whitespace_text_is_rejected_before_event_write(self):
        initialize_run(self.packet_path, self.sources, self.run)
        for field in ("event_id", "reason"):
            bad = assessment(self.packet)
            bad[field] = " \t "
            with self.assertRaisesRegex(Stage2Error, "schema:"):
                self.apply(bad)
        bad = assessment(self.packet, disposition="park")
        bad["checks"]["materials"] = finding("unknown", None, evidence_ids=[])
        bad["checks"]["materials"]["next_check"] = " "
        with self.assertRaisesRegex(Stage2Error, "schema:"):
            self.apply(bad)
        self.assertEqual(list((self.run / "events").glob("*.json")), [])

    def test_incomplete_revision_provenance_exports_unavailable_handoff(self):
        for imported in (True, False):
            with self.subTest(imported=imported):
                sources = self.root / f"sources-{imported}"
                packet = write_stage2_fixture(
                    sources, candidate_count=1, revise_first=imported
                )
                path = self.root / f"packet-{imported}.json"
                run = self.root / f"run-{imported}"
                self.write(path, packet)
                initialize_run(path, sources, run)
                if not imported:
                    revised = assessment(packet, disposition="revise")
                    revised["checks"] = {
                        axis: finding("unknown", None, evidence_ids=[])
                        for axis in revised["checks"]
                    }
                    candidate = copy.deepcopy(packet["candidates"][0])
                    candidate.update(version=2, parent_version=1, evidence_ids=[])
                    revised["revised_candidate"] = candidate
                    revise_path = self.root / "no-evidence-revision.json"
                    self.write(revise_path, revised)
                    apply_assessment(run, revise_path)
                recheck = assessment(packet, event_id="new-check", version=2)
                recheck_path = self.root / f"recheck-{imported}.json"
                self.write(recheck_path, recheck)
                apply_assessment(run, recheck_path)
                selection = export_selection(run)
                self.assertIsNone(selection["action_record"])
                self.assertEqual(selection["action_record_status"], "unavailable")
                self.assertTrue(selection["action_record_blocking_items"])
                self.assertEqual(
                    len(selection["candidate_histories"]["candidate-1"]), 2
                )
                self.assertEqual(len(selection["recommendations"]), 1)

    def test_schema_separates_unknown_not_applicable_and_assessed_scores(self):
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        validator = Draft202012Validator(schema)
        value = assessment(self.packet)
        value["checks"]["materials"] = finding("not-applicable", None, evidence_ids=[])
        validator.validate(value)
        value["checks"]["materials"]["score"] = 2
        self.assertFalse(validator.is_valid(value))
        value["checks"]["materials"] = finding("unknown", None, evidence_ids=[])
        validator.validate(value)

    def test_cli_init_apply_export_is_source_bound_and_prehuman(self):
        original_packet = self.packet_path.read_bytes()
        original_sources = {
            path.name: path.read_bytes() for path in self.sources.glob("*.txt")
        }
        output = io.StringIO()
        with redirect_stdout(output):
            init_code = main(
                [
                    "init",
                    "--packet",
                    str(self.packet_path),
                    "--source-root",
                    str(self.sources),
                    "--output",
                    str(self.run),
                ]
            )
        self.assertEqual(init_code, 0)
        check_path = self.root / "check.json"
        self.write(check_path, assessment(self.packet))
        with redirect_stdout(output):
            apply_code = main(
                ["apply", "--run", str(self.run), "--assessment", str(check_path)]
            )
            export_code = main(["export", "--run", str(self.run)])
        self.assertEqual((apply_code, export_code), (0, 0))
        selection = json.loads(
            (self.run / "selection.json").read_text(encoding="utf-8")
        )
        manifest = json.loads(
            (self.run / "run_manifest.json").read_text(encoding="utf-8")
        )
        stored_packet = json.loads(
            (self.run / "packet.json").read_text(encoding="utf-8")
        )
        stage_result = json.loads(
            (self.run / "stage_result.json").read_text(encoding="utf-8")
        )
        decisions = [
            json.loads(line)
            for line in (self.run / "decision_events.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
        ]
        self.assertEqual(len(decisions), 1)
        self.assertEqual(decisions[0]["new_decision"], "recommend")
        shared = Draft202012Validator(
            json.loads(SHARED_SCHEMA.read_text(encoding="utf-8"))
        )
        shared.validate(decisions[0])
        self.assertTrue((self.run / decisions[0]["evidence_refs"][0]["path"]).is_file())
        Draft202012Validator(
            json.loads(SHARED_SCHEMA.read_text(encoding="utf-8"))
        ).validate(stage_result)
        self.assertEqual(
            [row["candidate_id"] for row in selection["recommendations"]],
            ["candidate-1"],
        )
        self.assertEqual(selection["evaluation_packet"], self.packet)
        self.assertEqual(
            selection["action_record"]["selected_candidate_ids"], ["candidate-1"]
        )
        self.assertEqual(
            selection["action_record"]["latest_dispositions"][0]["disposition"],
            "recommend",
        )
        self.assertEqual(manifest["packet_sha256"], canonical_hash(self.packet))
        self.assertEqual(stored_packet["sources"][0]["path"], "sources/source-1.txt")
        self.assertEqual(
            selection["stage3"],
            {"status": "not-started", "execution_authorized": False},
        )
        self.assertFalse(selection["scientific_truth_validated"])
        markdown = (self.run / "selection.md").read_text(encoding="utf-8")
        for label in (
            "Value:",
            "Approach:",
            "Requirements:",
            "Limitations:",
            "Next step:",
        ):
            self.assertIn(label, markdown)
        self.assertEqual(self.packet_path.read_bytes(), original_packet)
        self.assertEqual(
            {path.name: path.read_bytes() for path in self.sources.glob("*.txt")},
            original_sources,
        )

    def test_identical_event_id_is_idempotent_and_changed_content_fails(self):
        initialize_run(self.packet_path, self.sources, self.run)
        value = assessment(self.packet)
        first = self.apply(value)
        second = self.apply(value)
        self.assertEqual(first, second)
        self.assertEqual(len(list((self.run / "events").glob("*.json"))), 1)
        parked = assessment(
            self.packet, event_id="park-after-review", disposition="park"
        )
        self.apply(parked)
        export_selection(self.run)
        decisions = [
            json.loads(line)
            for line in (self.run / "decision_events.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
        ]
        self.assertEqual(
            [row["new_decision"] for row in decisions], ["recommend", "park"]
        )
        self.assertEqual(decisions[1]["prior_decision"], "recommend")
        self.assertEqual(decisions[1]["reverses_event_id"], first["event_id"])
        self.assertEqual(len(list((self.run / "events").glob("*.json"))), 2)
        changed = copy.deepcopy(value)
        changed["reason"] = "Changed content under a reused ID."
        with self.assertRaisesRegex(Stage2Error, "event-id-content-conflict"):
            self.apply(changed)

    def test_revision_is_retained_and_requires_fresh_current_version_check(self):
        initialize_run(self.packet_path, self.sources, self.run)
        revised = assessment(self.packet, disposition="revise")
        candidate = copy.deepcopy(self.packet["candidates"][0])
        candidate.update(
            version=2,
            parent_version=1,
            question="Can the revised bounded question be answered?",
        )
        revised["revised_candidate"] = candidate
        self.apply(revised)
        selection = export_selection(self.run)
        self.assertEqual(
            [row["version"] for row in selection["candidate_histories"]["candidate-1"]],
            [1, 2],
        )
        self.assertEqual(selection["recommendations"], [])
        self.assertIn("pending assessment", " ".join(selection["blocking_items"]))
        self.assertIsNone(selection["action_record"])
        stale = assessment(self.packet, event_id="stale")
        with self.assertRaisesRegex(Stage2Error, "stale-candidate-version"):
            self.apply(stale, "stale.json")
        current = assessment(self.packet, event_id="current", version=2)
        self.apply(current, "current.json")
        refreshed = export_selection(self.run)
        self.assertEqual(refreshed["recommendations"][0]["version"], 2)
        validate_packet(refreshed["evaluation_packet"], self.sources)
        self.assertEqual(
            [row["version"] for row in refreshed["evaluation_packet"]["candidates"]],
            [1, 2],
        )
        self.assertEqual(
            refreshed["action_record"]["packet_sha256"],
            canonical_hash(refreshed["evaluation_packet"]),
        )
        # The independent evaluator consumes this neutral record, while the
        # production checker remains isolated from evaluator implementation.
        from stage2_eval.evaluation import validate_action_record

        validate_action_record(
            refreshed["action_record"], refreshed["evaluation_packet"]
        )
        self.assertEqual(
            refreshed["action_record"]["revision_history"],
            [
                {
                    "candidate_id": "candidate-1",
                    "from_version": 1,
                    "to_version": 2,
                    "reason": revised["reason"],
                    "evidence_ids": ["ev-1"],
                }
            ],
        )

    def test_unknown_and_pending_scope_block_recommendations_without_becoming_zero(
        self,
    ):
        initialize_run(self.packet_path, self.sources, self.run)
        unknown = assessment(self.packet)
        unknown["checks"]["answerability"] = finding(
            "unknown", None, evidence_ids=[], blocking=False
        )
        with self.assertRaisesRegex(Stage2Error, "recommendation-blocked: unknown"):
            self.apply(unknown)
        pending = assessment(self.packet)
        pending.update(
            scope_change_requested=True,
            next_step="Ask whether the expanded population is in scope.",
        )
        with self.assertRaisesRegex(Stage2Error, "scope-change-requested"):
            self.apply(pending, "pending.json")

    def test_informational_unresolved_and_bad_alternative_do_not_poison_good_choice(
        self,
    ):
        sources = self.root / "portfolio-sources"
        packet = write_stage2_fixture(sources, candidate_count=2)
        packet_path = self.root / "portfolio.json"
        run = self.root / "portfolio-run"
        self.write(packet_path, packet)
        initialize_run(packet_path, sources, run)
        good = assessment(packet, event_id="good")
        good_path = self.root / "good.json"
        self.write(good_path, good)
        apply_assessment(run, good_path)
        bad = assessment(packet, event_id="bad", disposition="park")
        bad["candidate_id"] = "candidate-2"
        bad["checks"]["execution"] = finding(
            "unknown", None, evidence_ids=[], blocking=True
        )
        bad["next_step"] = "Measure the unresolved execution requirement."
        bad_path = self.root / "bad.json"
        self.write(bad_path, bad)
        apply_assessment(run, bad_path)
        selection = export_selection(run)
        self.assertEqual(
            [row["candidate_id"] for row in selection["recommendations"]],
            ["candidate-1"],
        )
        self.assertEqual(selection["unresolved"], ["External validity remains unknown"])
        self.assertEqual(
            selection["action_record"]["selected_candidate_ids"], ["candidate-1"]
        )

        bad.update(
            event_id="scope-pending",
            scope_change_requested=True,
            next_step="Ask about changing the alternative's study population.",
        )
        self.write(bad_path, bad)
        apply_assessment(run, bad_path)
        pending = export_selection(run)
        self.assertEqual(
            [row["candidate_id"] for row in pending["recommendations"]], ["candidate-1"]
        )
        self.assertTrue(pending["pending_scope_questions"])

    def test_not_applicable_is_null_and_does_not_automatically_score_two(self):
        initialize_run(self.packet_path, self.sources, self.run)
        value = assessment(self.packet)
        value["checks"]["materials"] = finding("not-applicable", None, evidence_ids=[])
        self.apply(value)
        stored = export_selection(self.run)["assessment_history"][0]["assessment"]
        self.assertEqual(
            (
                stored["checks"]["materials"]["status"],
                stored["checks"]["materials"]["score"],
            ),
            ("not-applicable", None),
        )

    def test_reject_all_and_zero_candidates_are_valid_without_recommendation(self):
        reject_sources = self.root / "reject-sources"
        reject_packet = write_stage2_fixture(reject_sources, candidate_count=2)
        reject_packet["unresolved"] = []
        reject_path = self.root / "reject-packet.json"
        reject_run = self.root / "reject-run"
        self.write(reject_path, reject_packet)
        initialize_run(reject_path, reject_sources, reject_run)
        for index, candidate in enumerate(reject_packet["candidates"], 1):
            value = assessment(
                reject_packet, event_id=f"reject-{index}", disposition="reject"
            )
            value["candidate_id"] = candidate["candidate_id"]
            value["checks"]["opportunity"] = finding(score=0)
            value_path = self.root / f"reject-{index}.json"
            self.write(value_path, value)
            apply_assessment(reject_run, value_path)
        selection = export_selection(reject_run)
        self.assertEqual(selection["recommendations"], [])
        self.assertEqual(len(selection["rejected_options"]), 2)
        self.assertEqual(selection["action_record"]["selected_candidate_ids"], [])
        self.assertTrue(selection["action_record"]["choice_rationale"])

        empty_sources = self.root / "empty-sources"
        empty_packet = write_stage2_fixture(empty_sources, candidate_count=0)
        empty_packet["unresolved"] = []
        empty_path = self.root / "empty-packet.json"
        self.write(empty_path, empty_packet)
        empty_run = self.root / "empty-run"
        initialize_run(empty_path, empty_sources, empty_run)
        self.assertEqual(export_selection(empty_run)["recommendations"], [])

    def test_controlled_scientific_scenarios_gate_supplied_assessments_only(self):
        scenarios = {
            "prior-work-achieved-increment": "revise",
            "downloadable-data-misses-variable": "park-unknown",
            "valuable-but-resource-blocked": "park-resource",
            "simple-feasible-method": "recommend",
        }
        for name, case in scenarios.items():
            with self.subTest(name=name):
                sources = self.root / name / "sources"
                packet = write_stage2_fixture(sources, candidate_count=1)
                packet["unresolved"] = []
                packet_path = self.root / name / "packet.json"
                run = self.root / name / "run"
                self.write(packet_path, packet)
                initialize_run(packet_path, sources, run)
                disposition = (
                    "revise"
                    if case == "revise"
                    else "park"
                    if case.startswith("park")
                    else "recommend"
                )
                value = assessment(packet, disposition=disposition)
                value["reason"] = f"Controlled assessor scenario: {name}."
                if case == "revise":
                    revised = copy.deepcopy(packet["candidates"][0])
                    revised.update(
                        version=2,
                        parent_version=1,
                        opportunity="The claimed increment is narrowed beyond the supplied prior work.",
                    )
                    value["revised_candidate"] = revised
                elif case == "park-unknown":
                    value["checks"]["answerability"] = finding(
                        "unknown", None, evidence_ids=[]
                    )
                    value["next_step"] = (
                        "Obtain a source that measures the missing variable."
                    )
                elif case == "park-resource":
                    value["checks"]["execution"] = finding(score=0)
                    value["next_step"] = "Revise to a smaller source-supported study."
                value_path = self.root / name / "assessment.json"
                self.write(value_path, value)
                apply_assessment(run, value_path)
                selected = export_selection(run)["recommendations"]
                self.assertEqual(
                    [row["candidate_id"] for row in selected],
                    ["candidate-1"] if case == "recommend" else [],
                )

    def test_source_tamper_packet_rehash_and_stale_history_fail_closed(self):
        initialize_run(self.packet_path, self.sources, self.run)
        (self.run / "sources" / "source-1.txt").write_text(
            "replaced source\n", encoding="utf-8"
        )
        with self.assertRaisesRegex(
            Stage2Error, "source hash mismatch|source-snapshot-hash"
        ):
            inspect_run(self.run)

        second_run = self.root / "second-run"
        initialize_run(self.packet_path, self.sources, second_run)
        copied_packet_path = second_run / "packet.json"
        copied = json.loads(copied_packet_path.read_text(encoding="utf-8"))
        copied["comparison"] = "Rehashed replacement packet."
        self.write(copied_packet_path, copied)
        self.assertNotEqual(canonical_hash(copied), canonical_hash(self.packet))
        with self.assertRaisesRegex(Stage2Error, "stored-packet-hash-mismatch"):
            inspect_run(second_run)

        third_run = self.root / "third-run"
        initialize_run(self.packet_path, self.sources, third_run)
        check = self.root / "third-check.json"
        self.write(check, assessment(self.packet))
        apply_assessment(third_run, check)
        event_path = third_run / "events" / "000001.json"
        event = json.loads(event_path.read_text(encoding="utf-8"))
        event["sequence"] = 2
        self.write(event_path, event)
        with self.assertRaisesRegex(Stage2Error, "event-chain-invalid"):
            inspect_run(third_run)

    def test_original_packet_binding_and_external_event_head_detect_rewrites(self):
        initialize_run(self.packet_path, self.sources, self.run)
        manifest_path = self.run / "run_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["source_snapshots"][0]["original_path"] = "renamed-source.txt"
        manifest["manifest_sha256"] = canonical_hash(
            {key: value for key, value in manifest.items() if key != "manifest_sha256"}
        )
        self.write(manifest_path, manifest)
        with self.assertRaisesRegex(Stage2Error, "original-packet-hash-mismatch"):
            inspect_run(self.run)

        receipt_run = self.root / "receipt-run"
        initialize_run(self.packet_path, self.sources, receipt_run)
        for number in (1, 2):
            value = assessment(self.packet, event_id=f"receipt-{number}")
            path = self.root / f"receipt-{number}.json"
            self.write(path, value)
            latest = apply_assessment(receipt_run, path)
        receipt = latest["event_sha256"]
        (receipt_run / "events" / "000002.json").unlink()
        self.assertEqual(len(inspect_run(receipt_run)["events"]), 1)
        with self.assertRaisesRegex(Stage2Error, "event-head-receipt-mismatch"):
            export_selection(receipt_run, expected_event_head=receipt)

    def test_rejected_revision_or_clock_regression_appends_no_bytes(self):
        initialize_run(self.packet_path, self.sources, self.run)
        invalid = assessment(self.packet, disposition="revise")
        candidate = copy.deepcopy(self.packet["candidates"][0])
        candidate.update(version=3, parent_version=1)
        invalid["revised_candidate"] = candidate
        invalid_path = self.root / "invalid-revision.json"
        self.write(invalid_path, invalid)
        with self.assertRaisesRegex(Stage2Error, "revision-version-not-contiguous"):
            apply_assessment(self.run, invalid_path)
        self.assertEqual(list((self.run / "events").glob("*.json")), [])

        valid_path = self.root / "valid-clock.json"
        self.write(valid_path, assessment(self.packet, event_id="old-clock"))
        with self.assertRaisesRegex(Stage2Error, "event-time-regression"):
            apply_assessment(
                self.run,
                valid_path,
                clock=lambda: "2000-01-01T00:00:00Z",
            )
        self.assertEqual(list((self.run / "events").glob("*.json")), [])

    def test_wrong_packet_hash_and_negative_reject_without_evidence_are_rejected(self):
        initialize_run(self.packet_path, self.sources, self.run)
        wrong = assessment(self.packet)
        wrong["packet_sha256"] = "f" * 64
        with self.assertRaisesRegex(Stage2Error, "assessment-packet-hash-mismatch"):
            self.apply(wrong)
        reject = assessment(self.packet, disposition="reject")
        with self.assertRaisesRegex(Stage2Error, "reject-assessed-negative"):
            self.apply(reject, "reject.json")


if __name__ == "__main__":
    unittest.main()
