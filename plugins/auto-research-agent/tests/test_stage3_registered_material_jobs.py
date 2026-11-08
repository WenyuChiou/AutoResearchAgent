"""Authored material-to-planner and independent-review integration; zero models."""

# ruff: noqa: E402
from copy import deepcopy
import hashlib
from pathlib import Path
import sys
import unittest

PLUGIN = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(PLUGIN / "cli"), str(PLUGIN / "tests")]
from stage3_plan.contracts import Stage3Error, canonical_bytes
from stage3_plan.context_projection import expand_context
from stage3_plan.direction_materials import (
    MAX_MATERIAL_FRAGMENT_BYTES,
    prepare_registered_materials,
    inspect_registered_materials,
)
from stage3_plan.direction_intent import build_direction_prompt
from stage3_plan.direction_research import build_design_review_prompt, research_context
from stage3_plan.storage import decode_json
from test_stage3_direction_research import _DirectionResearchFixture
from test_stage3_study_jobs import _StudySetup
import test_stage3_direction_research_jobs as fixture


class RegisteredMaterialJobsTests(_DirectionResearchFixture, _StudySetup):
    prepare_job = fixture.Stage3DirectionResearchJobsTests.prepare_job
    run_job = fixture.Stage3DirectionResearchJobsTests.run_job
    saved_root = fixture.Stage3DirectionResearchJobsTests.saved_root

    def configure_materials(self, context, root, *, document=None, catalog_name=None):
        material = {
            "unit": "authored units",
            "availability": "unknown",
            "source_limit": "Unverified survey weights.",
            "observations": [2, 5],
        }
        if document is not None:
            material.update(document)
        self.material_raw = canonical_bytes(material)
        self.material_id = "file-" + "1" * 32
        self.material_sha = hashlib.sha256(self.material_raw).hexdigest()
        entry = dict(
            id=self.material_id,
            kind="manual-file",
            project_ref=context["project_ref"],
            stage=3,
            name="authored-original.json" if catalog_name is None else catalog_name,
            bytes=len(self.material_raw),
            sha256=self.material_sha,
            status="registered",
            content_status="unreviewed-material-not-screened-or-read",
            registered_at="2026-01-01T00:00:00Z",
            execution_authorized=False,
        )
        selection = dict(
            file_id=self.material_id,
            sha256=self.material_sha,
            bytes=len(self.material_raw),
            pointers=["/unit", "/availability", "/source_limit", "/observations"],
            question_refs=[context["questions"][0]["question_ref"]],
            purpose="Inspect existing values for a proposed comparison.",
            limits="These observed development data are not new holdout evidence.",
        )
        self.material_reads = []

        def read_file(identity):
            self.material_reads.append(identity)
            return self.material_raw

        binding = prepare_registered_materials(
            context,
            [selection],
            root / "registered-materials",
            catalog=lambda ref: [entry],
            read_file=read_file,
        )
        self.study_adapter.materials = binding
        self.expected_materials = inspect_registered_materials(binding, context)

    def prepare_material_job(self):
        self.setup_study(self.context, self.root)
        self.configure_materials(self.context, self.root)
        return self.prepare_job(self.study_adapter)

    @staticmethod
    def prompt_context(prompt, marker):
        value = decode_json(prompt.split(marker, 1)[1])
        return (
            expand_context(value)
            if value.get("kind") == "Stage3SharedPlanningContext"
            else value
        )

    def test_actual_planner_and_independent_review_share_exact_material_values(self):
        prepared = self.prepare_material_job()
        saved = self.run_job(prepared, self.study_adapter)
        self.assertEqual(saved["result"]["outcome"], "saved")
        planner = self.prompt_context(
            self.study_calls[0]["prompt"], "UNTRUSTED_STAGE2_CONTEXT\n"
        )
        review = self.prompt_context(
            self.study_reviews[0]["prompt"], "UNTRUSTED_RESEARCH_DESIGN\n"
        )
        self.assertEqual(planner["registered_materials"], self.expected_materials)
        self.assertEqual(review["registered_materials"], self.expected_materials)
        self.assertFalse(planner["registered_materials"]["rights_verified"])
        self.assertFalse(review["registered_materials"]["scientific_quality_verified"])
        self.assertEqual(self.run_job(prepared, self.study_adapter), saved)
        self.assertEqual(
            (len(self.study_calls), len(self.study_reviews), len(self.material_reads)),
            (1, 1, 1),
        )

    def test_changed_saved_material_rejects_before_any_model_callback(self):
        prepared = self.prepare_material_job()
        path = self.root / "registered-materials" / (self.material_id + ".json")
        path.write_bytes(b'{"observations":[99]}')
        with self.assertRaises(Stage3Error):
            self.run_job(prepared, self.study_adapter)
        self.assertEqual((self.study_calls, self.study_reviews), ([], []))

    def test_another_material_binding_cannot_reuse_a_prepared_request(self):
        prepared = self.prepare_material_job()
        changed = deepcopy(self.study_adapter.request_context)
        changed["direction_research"]["materials"]["sha256"] = "a" * 64
        self.study_adapter.materials = changed["direction_research"]["materials"]
        with self.assertRaises(Stage3Error):
            self.run_job(prepared, self.study_adapter)
        self.assertEqual((self.study_calls, self.study_reviews), ([], []))

    def test_large_scalar_rejects_before_either_model_callback(self):
        self.setup_study(self.context, self.root)
        self.configure_materials(
            self.context,
            self.root,
            document={"observations": " ".join(str(i % 10) for i in range(12000))},
        )
        with self.assertRaisesRegex(Stage3Error, "material fragment exceeds"):
            prepared = self.prepare_job(self.study_adapter)
            self.run_job(prepared, self.study_adapter)
        self.assertEqual((self.study_calls, self.study_reviews), ([], []))

    def test_both_public_prompts_bound_values_and_catalog_metadata_before_sharing(self):
        cases = (
            ({"observations": [1] * 600}, None),
            ({"unit": "界" * 300}, None),
            ({"unit": "\n" * 400}, None),
            (None, "n" * 900),
        )
        for index, (document, name) in enumerate(cases):
            with self.subTest(index=index):
                root = self.root / str(index)
                root.mkdir()
                self.setup_study(self.context, root)
                self.configure_materials(
                    self.context, root, document=document, catalog_name=name
                )
                context = dict(
                    self.context, registered_materials=self.expected_materials
                )
                for build in (
                    lambda: build_direction_prompt(context),
                    lambda: build_design_review_prompt(self.study_plan, context),
                ):
                    with self.assertRaisesRegex(
                        Stage3Error, "material fragment exceeds"
                    ):
                        build()
                self.assertEqual((self.study_calls, self.study_reviews), ([], []))

    def test_exact_fragment_boundary_preserves_original_in_both_model_inputs(self):
        # JSON pointer/value envelope is included in the byte bound, not just text.
        prefix = len(canonical_bytes({"pointer": "/unit", "value": ""}))
        scalar = "a" * (MAX_MATERIAL_FRAGMENT_BYTES - prefix)
        self.setup_study(self.context, self.root)
        self.configure_materials(self.context, self.root, document={"unit": scalar})
        prepared = self.prepare_job(self.study_adapter)
        saved = self.run_job(prepared, self.study_adapter)
        self.assertEqual(saved["result"]["outcome"], "saved")
        for request, marker in (
            (self.study_calls[0], "UNTRUSTED_STAGE2_CONTEXT\n"),
            (self.study_reviews[0], "UNTRUSTED_RESEARCH_DESIGN\n"),
        ):
            material = self.prompt_context(request["prompt"], marker)[
                "registered_materials"
            ]
            self.assertEqual(material, self.expected_materials)
            self.assertEqual(material["materials"][0]["values"][0]["value"], scalar)
        self.assertEqual((len(self.study_calls), len(self.study_reviews)), (1, 1))
        too_large = dict(
            self.context, registered_materials=deepcopy(self.expected_materials)
        )
        too_large["registered_materials"]["materials"][0]["values"][0]["value"] += "a"
        for build in (
            lambda: build_direction_prompt(too_large),
            lambda: build_design_review_prompt(self.study_plan, too_large),
        ):
            with self.assertRaisesRegex(Stage3Error, "material fragment exceeds"):
                build()

    def test_direct_builders_reject_non_json_metadata_before_serialization(self):
        self.setup_study(self.context, self.root)
        self.configure_materials(self.context, self.root)
        verified = research_context(self.context, self.study_adapter.request_context)
        cyclic = []
        cyclic.append(cyclic)
        for name in (
            ("x" * 23999,),
            {"nested": ("x" * 23999,)},
            cyclic,
            {int("1" * 1000): 0},
        ):
            context = deepcopy(verified)
            context["registered_materials"]["materials"][0]["catalog"]["name"] = name
            for build in (
                lambda: build_direction_prompt(context),
                lambda: build_design_review_prompt(self.study_plan, context),
            ):
                with self.subTest(name_type=type(name).__name__, build=build):
                    with self.assertRaisesRegex(
                        Stage3Error, "invalid registered material JSON type"
                    ):
                        build()
        self.assertEqual((self.study_calls, self.study_reviews), ([], []))

    def test_direct_builders_bound_numeric_material_metadata(self):
        self.setup_study(self.context, self.root)
        self.configure_materials(self.context, self.root)
        context = research_context(self.context, self.study_adapter.request_context)
        context["registered_materials"]["materials"][0]["catalog"]["bytes"] = int(
            "1" * 1000
        )
        for build in (
            lambda: build_direction_prompt(context),
            lambda: build_design_review_prompt(self.study_plan, context),
        ):
            with self.subTest(build=build):
                with self.assertRaisesRegex(Stage3Error, "material fragment exceeds"):
                    build()
        self.assertEqual((self.study_calls, self.study_reviews), ([], []))


class ProjectRegisteredMaterialTests(unittest.TestCase, _StudySetup):
    @classmethod
    def setUpClass(cls):
        from stage3_direction_fixtures import DirectionFixture

        cls.direction = DirectionFixture(cls.addClassCleanup)

    def setUp(self):
        import test_stage3_study_jobs as studies

        studies.ProjectStudyForwardingTests.setUp(self)
        self.context = self.direction.admit(self.source)
        self.root = self.fixture.fixture.root / self._testMethodName
        RegisteredMaterialJobsTests.configure_materials(self, self.context, self.root)
        self.service.bindings[self.project["project_ref"]]["adapter_context"] = (
            deepcopy(self.study_adapter.request_context)
        )

    def test_original_host_forwards_materials_to_both_configured_callbacks(self):
        ref = self.project["project_ref"]
        prepared = self.service.prepare("own", ref, self.body)
        body = dict(
            self.body, request_sha256=prepared["request_sha256"], confirmed=True
        )
        saved = self.service.run("own", ref, body)
        self.assertEqual(saved["outcome"], "saved")
        for request, marker in (
            (self.study_calls[0], "UNTRUSTED_STAGE2_CONTEXT\n"),
            (self.study_reviews[0], "UNTRUSTED_RESEARCH_DESIGN\n"),
        ):
            context = RegisteredMaterialJobsTests.prompt_context(
                request["prompt"], marker
            )
            self.assertEqual(context["registered_materials"], self.expected_materials)
        self.assertEqual(self.service.run("own", ref, body), saved)
        self.assertEqual(
            (len(self.study_calls), len(self.study_reviews), len(self.material_reads)),
            (1, 1, 1),
        )
        self.assertFalse(saved["execution_authorized"])


if __name__ == "__main__":
    unittest.main()
