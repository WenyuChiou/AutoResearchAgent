"""Actual automatic producer to own-account factory; no native process or model."""

from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cli"))

import test_project_model_factory as factory_fixture
import test_project_stage1_execution as execution_fixture
from research_workspace_native import atlas_local_source as source
from research_workspace_native.project_stage1_review_units import prompt
from research_workspace_native.project_stage1_auto import ProjectStage1AutoDriver
from research_workspace_native.session_api import SessionApiError
from stage1_review_test_support import continue_with_diagnostics


class AutomaticFactoryAdapterTests(unittest.TestCase):
    factory = factory_fixture.ProjectModelFactoryTests.factory

    def setUp(self):
        factory_fixture.ProjectModelFactoryTests.setUp(self)
        self.case, saved, _, execution, calls = (
            execution_fixture.AutomaticStage1ProductionTests.fixture(self)
        )
        ref = saved["ref"]
        work = next(row for row in execution.work_items(ref) if row.get("next_task"))
        offer = execution.register_task(ref, work["next_task"])
        state = self.case.intake._load("alice", ref)
        self.context = deepcopy(
            state["model_operations"]["offers"][offer["offer_ref"]]["context"]
        )
        self.assertEqual(self.context["saved_reading"]["schema_version"], "1.1.0")
        self.assertEqual(calls, [])

    def rebound(self, value, *, snapshot=False):
        value = deepcopy(value)
        if snapshot:
            reading = value["saved_reading"]
            value["snapshot_sha256"] = source.digest(source.canonical(reading))
            value["prompt_sha256"] = source.digest(prompt(reading).encode("utf8"))
        value["source_sha256"] = source.digest(
            source.canonical({k: v for k, v in value.items() if k != "source_sha256"})
        )
        return value

    def test_emitted_11_reaches_actual_factory_without_native_start(self):
        with (
            patch.object(subprocess, "Popen", side_effect=AssertionError("no native")),
            patch.object(subprocess, "run", side_effect=AssertionError("no probe")),
        ):
            provider = self.factory()(
                context=self.context,
                admit=lambda event: True,
                output_root=self.root / "native-units",
            )
            saved = json.loads(self.created[0].checked["config_path"].read_bytes())
            self.assertEqual(saved, self.context)
            self.assertEqual(saved["saved_reading"]["schema_version"], "1.1.0")
            self.assertIn("semantic_context", saved["saved_reading"])
            self.assertTrue(
                provider.run("authored", prompt(saved["saved_reading"]), 1)["synthetic"]
            )
            provider.close()

    def test_unsupported_or_rehashed_snapshot_tampering_still_refuses(self):
        own = self.factory()
        variants = []
        for version in ("1.2.0", "2.0.0", "", None):
            value = deepcopy(self.context)
            value["saved_reading"]["schema_version"] = version
            variants.append(self.rebound(value, snapshot=True))
        for key, replacement in (
            ("kind", "Stage1SavedTextReadingInput"),
            ("input_version", "1"),
            ("human_acceptance", True),
            ("scientific_acceptance", True),
        ):
            value = deepcopy(self.context)
            value["saved_reading"][key] = replacement
            variants.append(self.rebound(value, snapshot=True))
        for value in variants:
            with self.subTest(snapshot=value["saved_reading"]):
                with self.assertRaises(ValueError):
                    own(
                        context=value,
                        admit=lambda event: True,
                        output_root=self.root / "native-units",
                    )
        self.assertEqual(self.created, [])
        self.assertFalse((self.root / "project-model-input").exists())

    def test_identity_hash_and_deny_only_guards_still_refuse(self):
        own = self.factory()
        for key, replacement in (
            ("task_ref", "foreign-task"),
            ("work_ref", "foreign-work"),
            ("project_ref", "foreign-project"),
            ("project_id", "foreign-project"),
            ("input_version", True),
            ("brief_sha256", "0" * 64),
            ("snapshot_sha256", "0" * 64),
            ("prompt_sha256", "0" * 64),
            ("deny_only", False),
            ("trusted_stage_unit", False),
        ):
            value = deepcopy(self.context)
            value[key] = replacement
            with self.subTest(field=key):
                with self.assertRaises(ValueError):
                    own(
                        context=self.rebound(value),
                        admit=lambda event: True,
                        output_root=self.root / "native-units",
                    )
        value = deepcopy(self.context)
        value["source_sha256"] = "0" * 64
        with self.assertRaises(ValueError):
            own(
                context=value,
                admit=lambda event: True,
                output_root=self.root / "native-units",
            )
        self.assertEqual(self.created, [])
        self.assertFalse((self.root / "project-model-input").exists())


class ReviewFailureDiagnosticsTests(unittest.TestCase):
    def test_original_exception_chain_is_visible_without_retry(self):
        try:
            try:
                raise ValueError("authored inner failure")
            except ValueError as cause:
                raise SessionApiError("intake-operation-failed", 409) from cause
        except SessionApiError as error:
            original_error = error

        driver = SimpleNamespace()
        action = SimpleNamespace(kind="delivery")
        deadline = time.monotonic() + 300

        def continued(credential, ref, **kwargs):
            with self.assertRaises(SessionApiError) as caught:
                ProjectStage1AutoDriver.dispatch(driver, action, "same-key", deadline)
            self.assertIs(caught.exception, original_error)
            return dict(reason="handler-failed")

        with patch.object(
            ProjectStage1AutoDriver, "dispatch", side_effect=original_error
        ) as original:
            result, failures = continue_with_diagnostics(
                SimpleNamespace(continue_stage1=continued), "authored", "project"
            )
            self.assertIs(ProjectStage1AutoDriver.dispatch, original)
            original.assert_called_once_with(driver, action, "same-key", deadline)
        self.assertEqual(result, dict(reason="handler-failed"))
        self.assertEqual(len(failures), 1)
        self.assertIn(
            "ValueError: authored inner failure", failures[0]["exception_chain"]
        )
        self.assertEqual(failures[0]["exception_code"], "intake-operation-failed")

    def test_success_keeps_the_original_result_and_deadline(self):
        marker = object()
        seen = []
        deadline = time.monotonic() + 300

        def continued(credential, ref, **kwargs):
            seen.append((credential, ref, kwargs))
            return marker

        result, failures = continue_with_diagnostics(
            SimpleNamespace(continue_stage1=continued),
            "authored",
            "project",
            deadline=deadline,
        )
        self.assertIs(result, marker)
        self.assertEqual(failures, [])
        self.assertEqual(seen, [("authored", "project", dict(deadline=deadline))])


if __name__ == "__main__":
    unittest.main()
