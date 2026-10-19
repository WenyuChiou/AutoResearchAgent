"""Legacy projection is readable provenance, not strict workflow acceptance."""

import copy
import contextlib
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from stage2_common.scientific_argument import validate_scientific_argument
from stage3_plan.contracts import Stage3Error, canonical_bytes, digest
from stage3_plan.legacy_mapping import inspect_legacy_mapping, prepare_legacy_mapping
from stage2_fixture_helpers import write_stage2_fixture


class Stage3LegacyMappingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.sources = self.root / "input"
        self.packet = write_stage2_fixture(self.sources, revise_first=True)
        self.packet_path = self.root / "packet.json"
        self.packet_path.write_bytes(canonical_bytes(self.packet))
        self.packet_sha = hashlib.sha256(self.packet_path.read_bytes()).hexdigest()
        self.output = self.root / "mapping"

    def prepare(self):
        return prepare_legacy_mapping(
            self.packet_path,
            self.sources,
            expected_packet_sha256=self.packet_sha,
            output_dir=self.output,
        )

    def inspect(self, manifest_sha):
        return inspect_legacy_mapping(
            self.output, expected_manifest_sha256=manifest_sha
        )

    def rehash_manifest(self):
        path = self.output / "manifest.json"
        value = json.loads(path.read_bytes())
        for row in value["files"]:
            row["sha256"] = hashlib.sha256(
                (self.output / row["path"]).read_bytes()
            ).hexdigest()
        unsigned = {k: v for k, v in value.items() if k != "manifest_sha256"}
        value["manifest_sha256"] = digest(unsigned)
        path.write_bytes(canonical_bytes(value))
        return value["manifest_sha256"]

    def test_exact_original_bytes_and_current_versions_are_preserved(self):
        saved = self.prepare()
        self.assertEqual(
            (self.output / "original-packet.json").read_bytes(),
            self.packet_path.read_bytes(),
        )
        self.assertEqual(saved["packet"], self.packet)
        versions = {
            c["candidate_id"]: c["candidate_version"]
            for c in saved["mapping"]["candidates"]
        }
        self.assertEqual(versions, {"candidate-1": 2, "candidate-2": 1})
        self.assertFalse(saved["strict_delivery"])
        self.assertFalse(saved["can_prepare_selected_handoff"])
        self.assertFalse(saved["execution_authorized"])
        self.assertIsNone(saved["mapping"]["human_selection"])
        self.assertEqual(len(saved["packet"]["candidates"]), 3)

    def test_arguments_resolve_without_promoting_resource_or_assessment(self):
        saved = self.prepare()
        packet = copy.deepcopy(self.packet)
        packet["research_tables"] = {"direction_resources": []}
        for row in saved["mapping"]["candidates"]:
            packet["research_tables"]["direction_resources"].extend(row["resources"])
            candidate = {
                "candidate_id": row["candidate_id"],
                "version": row["candidate_version"],
                "scientific_argument": row["scientific_argument"],
            }
            validate_scientific_argument(candidate, packet)
            self.assertIsNone(row["recommendation_eligible"])
            self.assertEqual({r["status"] for r in row["resources"]}, {"unknown"})
            original = next(
                c
                for c in self.packet["candidates"]
                if c["candidate_id"] == row["candidate_id"]
                and c["version"] == row["candidate_version"]
            )
            self.assertEqual(
                row["scientific_argument"]["questions"][0]["text"], original["question"]
            )
            self.assertEqual(row["limitations"], original["limitations"])

    def test_wrong_external_packet_hash_creates_no_output(self):
        with self.assertRaisesRegex(Stage3Error, "external hash mismatch"):
            prepare_legacy_mapping(
                self.packet_path,
                self.sources,
                expected_packet_sha256="0" * 64,
                output_dir=self.output,
            )
        self.assertFalse(self.output.exists())

    def test_source_bytes_mismatch_creates_no_output(self):
        (self.sources / "source-1.txt").write_text("changed", encoding="utf8")
        with self.assertRaises(ValueError):
            self.prepare()
        self.assertFalse(self.output.exists())

    def test_missing_source_creates_no_output(self):
        (self.sources / "source-1.txt").unlink()
        with self.assertRaises(ValueError):
            self.prepare()
        self.assertFalse(self.output.exists())

    def test_wrong_manifest_hash_rejected(self):
        self.prepare()
        with self.assertRaisesRegex(Stage3Error, "external binding mismatch"):
            self.inspect("0" * 64)

    def test_source_tamper_rejected_even_with_rehashed_transport(self):
        self.prepare()
        (self.output / "sources/source-1.txt").write_text("changed", encoding="utf8")
        new_sha = self.rehash_manifest()
        with self.assertRaises(ValueError):
            self.inspect(new_sha)

    def test_question_tamper_rejected_even_with_rehashed_transport(self):
        self.prepare()
        path = self.output / "mapping.json"
        value = json.loads(path.read_bytes())
        value["candidates"][0]["scientific_argument"]["questions"][0]["text"] = (
            "A different scientific question"
        )
        path.write_bytes(canonical_bytes(value))
        new_sha = self.rehash_manifest()
        with self.assertRaisesRegex(Stage3Error, "meaning/projection differs"):
            self.inspect(new_sha)

    def test_added_selection_cannot_promote_mapping(self):
        self.prepare()
        path = self.output / "mapping.json"
        value = json.loads(path.read_bytes())
        value["human_selection"] = [
            dict(candidate_id="candidate-1", candidate_version=2)
        ]
        path.write_bytes(canonical_bytes(value))
        with self.assertRaisesRegex(Stage3Error, "meaning/projection differs"):
            self.inspect(self.rehash_manifest())

    def test_extra_and_missing_files_are_rejected(self):
        sha = self.prepare()["manifest"]["manifest_sha256"]
        extra = self.output / "unexpected.txt"
        extra.write_text("extra", encoding="utf8")
        with self.assertRaisesRegex(Stage3Error, "inventory incomplete or unexpected"):
            self.inspect(sha)
        extra.unlink()
        (self.output / "mapping.json").unlink()
        with self.assertRaises(Stage3Error):
            self.inspect(sha)

    def test_traversal_and_duplicate_inventory_rejected(self):
        self.prepare()
        path = self.output / "manifest.json"
        original = json.loads(path.read_bytes())
        for bad in ("../escape", "/absolute", "C:/absolute", "sources\\source-1.txt"):
            value = copy.deepcopy(original)
            value["files"][0]["path"] = bad
            value["manifest_sha256"] = digest(
                {k: v for k, v in value.items() if k != "manifest_sha256"}
            )
            path.write_bytes(canonical_bytes(value))
            with self.assertRaisesRegex(Stage3Error, "inventory path invalid"):
                self.inspect(value["manifest_sha256"])
        value = copy.deepcopy(original)
        value["files"].append(value["files"][0])
        value["manifest_sha256"] = digest(
            {k: v for k, v in value.items() if k != "manifest_sha256"}
        )
        path.write_bytes(canonical_bytes(value))
        with self.assertRaisesRegex(Stage3Error, "duplicate legacy inventory"):
            self.inspect(value["manifest_sha256"])

    def test_existing_package_is_never_overwritten(self):
        sha = self.prepare()["manifest"]["manifest_sha256"]
        original = (self.output / "manifest.json").read_bytes()
        with self.assertRaisesRegex(Stage3Error, "output exists"):
            self.prepare()
        self.assertEqual((self.output / "manifest.json").read_bytes(), original)
        self.assertEqual(self.inspect(sha)["manifest"]["manifest_sha256"], sha)

    def test_cli_preparation_and_inspection_are_model_free(self):
        from stage3_plan.__main__ import main
        from unittest.mock import patch

        stdout = io.StringIO()
        with patch(
            "stage3_plan.planner._draft_from_intake",
            side_effect=AssertionError("no generation"),
        ):
            with contextlib.redirect_stdout(stdout):
                code = main(
                    [
                        "prepare-legacy-mapping",
                        "--packet",
                        str(self.packet_path),
                        "--source-root",
                        str(self.sources),
                        "--expected-packet-sha256",
                        self.packet_sha,
                        "--output",
                        str(self.output),
                    ]
                )
            self.assertEqual(code, 0)
            result = json.loads(stdout.getvalue())
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = main(
                    [
                        "inspect-legacy-mapping",
                        "--package",
                        str(self.output),
                        "--expected-manifest-sha256",
                        result["manifest"]["manifest_sha256"],
                    ]
                )
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(stdout.getvalue()), result)

    def test_untrusted_source_paths_are_rejected_before_validation_reads(self):
        from unittest.mock import patch

        for name in ("/absolute", "C:/absolute", "../escape", "sources\\file"):
            packet = copy.deepcopy(self.packet)
            packet["sources"][0]["path"] = name
            self.packet_path.write_bytes(canonical_bytes(packet))
            self.packet_sha = hashlib.sha256(self.packet_path.read_bytes()).hexdigest()
            with patch(
                "stage3_plan.legacy_mapping.validate_packet",
                side_effect=AssertionError("no outside reads"),
            ):
                with self.assertRaisesRegex(Stage3Error, "source path escapes root"):
                    self.prepare()
            self.assertFalse(self.output.exists())

    def test_mapping_cannot_replace_a_strict_selected_delivery(self):
        from stage3_plan.planner import draft_plan
        from unittest.mock import Mock

        result = self.prepare()
        callback = Mock(side_effect=AssertionError("mapping must not generate"))
        with self.assertRaises((ValueError, OSError)):
            draft_plan(
                self.output,
                self.output,
                expected_manifest_sha256=result["manifest"]["manifest_sha256"],
                output_dir=self.root / "plan",
                callback=callback,
                configuration={"model": "synthetic", "reasoning": "synthetic"},
                plan_id="not-admitted",
            )
        callback.assert_not_called()
        self.assertFalse((self.root / "plan").exists())

    def strict_fixture(self):
        candidate = next(
            c
            for c in self.packet["candidates"]
            if c["candidate_id"] == "candidate-1" and c["version"] == 2
        )
        return dict(
            handoff=dict(
                execution_authorized=False,
                decision=dict(
                    kind="select",
                    selected=[dict(candidate_id="candidate-1", candidate_version=2)],
                ),
                selected_options=[dict(candidate=copy.deepcopy(candidate))],
                selected_direction_resources=dict(rows=[]),
                selected_prior_work_reviews=[],
                evaluation_packet=copy.deepcopy(self.packet),
            )
        )

    def admit_mapped_fixture(self, verifier):
        from stage3_plan.intake import admit_intake
        from unittest.mock import patch

        fixture = self.strict_fixture()
        with patch(
            "stage3_plan.intake.inspect_planning_handoff", return_value=fixture
        ) as inspector:
            result = admit_intake(
                "strict-fixture",
                "delivery-fixture",
                expected_manifest_sha256="1" * 64,
                scientific_mapping=self.output,
                expected_mapping_manifest_sha256=self.prepare_result["manifest"][
                    "manifest_sha256"
                ],
                verify_mapping_choice=verifier,
            )
            inspector.assert_called_once_with(
                "strict-fixture", "delivery-fixture", expected_manifest_sha256="1" * 64
            )
            return result

    def test_mapped_intake_still_requires_trusted_human_mapping_verification(self):
        self.prepare_result = self.prepare()
        with self.assertRaisesRegex(Stage3Error, "trusted host must verify"):
            self.admit_mapped_fixture(None)
        with self.assertRaisesRegex(Stage3Error, "host verification rejected"):
            self.admit_mapped_fixture(
                lambda binding: dict(
                    kind="Stage2MappedSelectionVerification",
                    binding_sha256=digest(binding),
                    verified=False,
                    evidence_ref="synthetic rejection",
                )
            )

    def test_mapped_strict_intake_copies_only_selected_question_and_unknowns(self):
        self.prepare_result = self.prepare()
        bindings = []

        def verifier(binding):
            bindings.append(binding)
            return dict(
                kind="Stage2MappedSelectionVerification",
                binding_sha256=digest(binding),
                verified=True,
                evidence_ref="synthetic host seam; no real person authenticated",
            )

        intake = self.admit_mapped_fixture(verifier)
        self.assertEqual(intake["legacy_candidates"], [])
        self.assertEqual(len(intake["scientific_arguments"]), 1)
        self.assertEqual(intake["questions"][0]["question_ref"], "candidate-1@2/Q1")
        self.assertEqual({r["status"] for r in intake["resources"]}, {"unknown"})
        self.assertEqual(
            bindings[0]["mapping_manifest_sha256"],
            self.prepare_result["manifest"]["manifest_sha256"],
        )
        self.assertEqual(intake["legacy_mapping"]["origin"], "legacy-manual-v1")
        self.assertFalse(intake["execution_authorized"])

    def test_mapping_for_a_different_strict_packet_rejects_before_host_verifier(self):
        from stage3_plan.intake import admit_intake
        from unittest.mock import Mock, patch

        saved = self.prepare()
        fixture = self.strict_fixture()
        fixture["handoff"]["evaluation_packet"]["comparison"] = (
            "Different research comparison"
        )
        verify = Mock()
        with patch("stage3_plan.intake.inspect_planning_handoff", return_value=fixture):
            with self.assertRaisesRegex(
                Stage3Error, "not the current strict delivery packet"
            ):
                admit_intake(
                    "strict-fixture",
                    "delivery-fixture",
                    expected_manifest_sha256="1" * 64,
                    scientific_mapping=self.output,
                    expected_mapping_manifest_sha256=saved["manifest"][
                        "manifest_sha256"
                    ],
                    verify_mapping_choice=verify,
                )
        verify.assert_not_called()

    def test_oversized_source_rejects_before_any_unbounded_original_read(self):
        from unittest.mock import patch
        from stage3_plan.storage import MAX_ARTIFACT_BYTES

        source = self.sources / self.packet["sources"][0]["path"]
        source.write_bytes(b"x" * (MAX_ARTIFACT_BYTES + 1))
        original_read = Path.read_bytes

        def guarded_read(path):
            if path == source:
                raise AssertionError("unbounded original source read")
            return original_read(path)

        with patch.object(Path, "read_bytes", guarded_read):
            with self.assertRaisesRegex(Stage3Error, "bounded size"):
                self.prepare()
        self.assertFalse(self.output.exists())

    def test_mapped_restrictions_reach_prompt_and_confirmation_replay(self):
        from unittest.mock import patch
        from stage3_plan.decision import record_plan_decision
        from stage3_plan.prompts import build_prompt

        candidate = next(
            c
            for c in self.packet["candidates"]
            if c["candidate_id"] == "candidate-1" and c["version"] == 2
        )
        candidate["approach"] = "ORIGINAL_APPROACH_ONLY"
        candidate["limitations"] = ["ORIGINAL_NO_CAUSAL_INFERENCE"]
        self.packet["unresolved"] = ["ORIGINAL_LICENSE_UNKNOWN"]
        self.packet_path.write_bytes(canonical_bytes(self.packet))
        self.packet_sha = hashlib.sha256(self.packet_path.read_bytes()).hexdigest()
        self.prepare_result = self.prepare()
        fixture = self.strict_fixture()
        fixture["handoff"]["decision"]["unresolved"] = ["DECISION_SCOPE_UNKNOWN"]
        self.strict_fixture = lambda: fixture
        intake = self.admit_mapped_fixture(
            lambda binding: dict(
                kind="Stage2MappedSelectionVerification",
                binding_sha256=digest(binding),
                verified=True,
                evidence_ref="synthetic host seam; no person authenticated",
            )
        )
        prompt = build_prompt(intake, plan_id="synthetic-restriction-replay", version=1)
        for text in (
            "ORIGINAL_APPROACH_ONLY",
            "ORIGINAL_NO_CAUSAL_INFERENCE",
            "ORIGINAL_LICENSE_UNKNOWN",
            "DECISION_SCOPE_UNKNOWN",
        ):
            self.assertIn(text, prompt)
        self.assertEqual(intake["unresolved"], ["DECISION_SCOPE_UNKNOWN"])
        self.assertEqual(
            intake["legacy_mapping"]["packet_unresolved"], ["ORIGINAL_LICENSE_UNKNOWN"]
        )
        changed = copy.deepcopy(intake)
        changed["scientific_arguments"][0]["limitations"].append("NEW_RESTRICTION")
        saved = dict(artifacts={"plan.json": {}, "request.json": {"intake": intake}})
        with (
            patch("stage3_plan.decision.inspect_package", return_value=saved),
            patch("stage3_plan.intake.admit_intake", return_value=changed),
        ):
            with self.assertRaisesRegex(Stage3Error, "conditions changed"):
                record_plan_decision(
                    "synthetic-plan",
                    expected_manifest_sha256="2" * 64,
                    review_path="unused",
                    expected_review_sha256="3" * 64,
                    native_message="unused",
                    message_index=0,
                    user_text="synthetic",
                    decision="confirm",
                    output_dir=self.root / "confirmation",
                    planning_package="strict-fixture",
                    delivery_dir="delivery-fixture",
                    expected_source_manifest_sha256="1" * 64,
                )
        self.assertFalse((self.root / "confirmation").exists())


if __name__ == "__main__":
    unittest.main()
