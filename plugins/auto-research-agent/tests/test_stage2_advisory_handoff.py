"""Synthetic advice-context checks; no fixture establishes a human research choice."""

import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import unittest

PLUGIN = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(PLUGIN / "cli"), str(PLUGIN / "tests")]
from stage2_common import Stage2Error, canonical_hash  # noqa: E402
from stage2_workflow.advisory_handoff import (  # noqa: E402
    inspect_advisory_handoff,
    prepare_advisory_handoff,
)
from stage2_workflow.planning_handoff import inspect_planning_handoff  # noqa: E402
import test_stage2_delivery as delivery_tests  # noqa: E402
from test_stage2_checker import assessment  # noqa: E402


class Stage2AdvisoryHandoffTests(unittest.TestCase):
    def setUp(self):
        fixture = delivery_tests.Stage2DeliveryTests(
            "test_full_cycle_binds_package_and_preserves_embedded_checker"
        )
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.fixture = fixture
        value = assessment(fixture.packet, disposition="park")
        value["checks"]["materials"].update(
            status="unknown",
            score=None,
            evidence_ids=[],
            blocking=True,
            rationale="Material access has not been established in this fixture.",
            next_check="Confirm the exact analytic product and access conditions.",
        )
        reviews, resolutions = fixture._complete_inputs(value)
        self.delivery = fixture.root / "advisory-delivery"
        self.manifest = fixture._build(self.delivery, reviews, resolutions)
        self.output = fixture.root / "advisory-package"
        self.selection = json.loads((self.delivery / "selection.json").read_bytes())
        self.assertEqual(self.selection["recommendations"], [])

    def prepare(self):
        return prepare_advisory_handoff(
            self.delivery,
            expected_delivery_manifest_sha256=self.manifest["manifest_sha256"],
            output_dir=self.output,
        )

    def refresh_manifest(self):
        path = self.output / "advisory_manifest.json"
        manifest = json.loads(path.read_bytes())
        for row in manifest["files"]:
            raw = (self.output / row["path"]).read_bytes()
            row.update(sha256=hashlib.sha256(raw).hexdigest(), size=len(raw))
        manifest["manifest_sha256"] = canonical_hash(
            {k: v for k, v in manifest.items() if k != "manifest_sha256"}
        )
        path.write_text(json.dumps(manifest), encoding="utf-8")
        return manifest["manifest_sha256"]

    def test_unselected_zero_recommendations_and_unknowns_survive_roundtrip(self):
        before = {p: p.read_bytes() for p in self.delivery.rglob("*") if p.is_file()}
        result = self.prepare()
        context = result["context"]
        self.assertEqual(context["selection"], self.selection)
        self.assertEqual(context["selected_options"], [])
        self.assertEqual(context["human_selection"], "pending")
        self.assertIs(context["execution_authorized"], False)
        self.assertIsNone(
            context["selection"]["current_options"][0]["assessment"]["checks"][
                "materials"
            ]["score"]
        )
        self.assertEqual(before, {p: p.read_bytes() for p in before})
        replay = inspect_advisory_handoff(
            self.output,
            self.delivery,
            expected_manifest_sha256=result["manifest"]["manifest_sha256"],
        )
        self.assertEqual(replay, result)

    def test_wrong_external_delivery_hash_creates_no_package(self):
        with self.assertRaises(Stage2Error):
            prepare_advisory_handoff(
                self.delivery,
                expected_delivery_manifest_sha256="0" * 64,
                output_dir=self.output,
            )
        self.assertFalse(self.output.exists())

    def test_output_inside_delivery_is_rejected_without_mutating_input(self):
        before = {p: p.read_bytes() for p in self.delivery.rglob("*") if p.is_file()}
        target = self.delivery / "nested-advisory"
        with self.assertRaisesRegex(Stage2Error, "advisory-output-overlaps-delivery"):
            prepare_advisory_handoff(
                self.delivery,
                expected_delivery_manifest_sha256=self.manifest["manifest_sha256"],
                output_dir=target,
            )
        self.assertFalse(target.exists())
        self.assertEqual(before, {p: p.read_bytes() for p in before})

    def test_rehashed_selection_or_execution_claim_is_rejected(self):
        original = self.prepare()["context"]
        for change in (
            {"execution_authorized": True},
            {"execution_authorized": 0},
            {"human_selection": "recorded"},
            {"selected_options": [self.selection["current_options"][0]]},
            {"selection": {**self.selection, "recommendations": ["invented"]}},
        ):
            value = copy.deepcopy(original)
            value.update(change)
            (self.output / "advisory_context.json").write_text(
                json.dumps(value), encoding="utf-8"
            )
            expected = self.refresh_manifest()
            with self.subTest(change=list(change)):
                with self.assertRaisesRegex(Stage2Error, "advisory-context-projection"):
                    inspect_advisory_handoff(
                        self.output, self.delivery, expected_manifest_sha256=expected
                    )

    def test_wrong_package_hash_and_missing_context_are_rejected(self):
        result = self.prepare()
        with self.assertRaisesRegex(Stage2Error, "advisory-manifest-binding"):
            inspect_advisory_handoff(
                self.output, self.delivery, expected_manifest_sha256="0" * 64
            )
        (self.output / "advisory_context.json").unlink()
        with self.assertRaisesRegex(Stage2Error, "advisory-package-inventory"):
            inspect_advisory_handoff(
                self.output,
                self.delivery,
                expected_manifest_sha256=result["manifest"]["manifest_sha256"],
            )

    def test_modified_delivery_is_not_accepted_by_package_replay(self):
        result = self.prepare()
        source = self.delivery / "selection.json"
        source.write_text("{}", encoding="utf-8")
        with self.assertRaises(Stage2Error):
            inspect_advisory_handoff(
                self.output,
                self.delivery,
                expected_manifest_sha256=result["manifest"]["manifest_sha256"],
            )

    def test_extra_package_file_and_existing_output_are_rejected(self):
        result = self.prepare()
        with self.assertRaisesRegex(Stage2Error, "advisory-output-exists"):
            self.prepare()
        (self.output / "extra.json").write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(Stage2Error, "advisory-package-inventory"):
            inspect_advisory_handoff(
                self.output,
                self.delivery,
                expected_manifest_sha256=result["manifest"]["manifest_sha256"],
            )

    def test_advisory_package_cannot_pass_as_selected_planning_input(self):
        result = self.prepare()
        with self.assertRaisesRegex(Stage2Error, "planning-manifest-invalid"):
            inspect_planning_handoff(
                self.output,
                self.delivery,
                expected_manifest_sha256=result["manifest"]["manifest_sha256"],
            )

    def test_cli_prepares_and_inspects_without_interaction_or_models(self):
        args = [
            sys.executable,
            "-m",
            "stage2_workflow",
            "prepare-stage3-advice",
            "--delivery",
            str(self.delivery),
            "--expected-delivery-manifest-sha256",
            self.manifest["manifest_sha256"],
            "--output",
            str(self.output),
        ]
        created = subprocess.run(
            args, cwd=PLUGIN / "cli", capture_output=True, text=True, timeout=30
        )
        self.assertEqual(created.returncode, 0, created.stderr)
        manifest = json.loads((self.output / "advisory_manifest.json").read_bytes())
        target = self.fixture.root / "advisory-inspection.json"
        checked = subprocess.run(
            [
                sys.executable,
                "-m",
                "stage2_workflow",
                "inspect-stage3-advice",
                "--package",
                str(self.output),
                "--delivery",
                str(self.delivery),
                "--expected-manifest-sha256",
                manifest["manifest_sha256"],
                "--output",
                str(target),
            ],
            cwd=PLUGIN / "cli",
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(checked.returncode, 0, checked.stderr)
        self.assertEqual(
            json.loads(target.read_bytes())["context"]["selection"], self.selection
        )

    def test_cli_inspection_output_cannot_mutate_either_input(self):
        result = self.prepare()
        before = {
            root: {
                path.relative_to(root): path.read_bytes()
                for path in root.rglob("*")
                if path.is_file()
            }
            for root in (self.delivery, self.output)
        }
        for root in before:
            target = root / "new-inspection.json"
            with self.subTest(root=root.name):
                checked = subprocess.run(
                    [
                        sys.executable,
                        "-m",
                        "stage2_workflow",
                        "inspect-stage3-advice",
                        "--package",
                        str(self.output),
                        "--delivery",
                        str(self.delivery),
                        "--expected-manifest-sha256",
                        result["manifest"]["manifest_sha256"],
                        "--output",
                        str(target),
                    ],
                    cwd=PLUGIN / "cli",
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                self.assertNotEqual(checked.returncode, 0)
                self.assertIn(
                    "advisory-inspection-output-overlaps-input", checked.stderr
                )
                self.assertFalse(target.exists())
        for root, inventory in before.items():
            self.assertEqual(
                inventory,
                {
                    path.relative_to(root): path.read_bytes()
                    for path in root.rglob("*")
                    if path.is_file()
                },
            )
        self.assertEqual(
            inspect_advisory_handoff(
                self.output,
                self.delivery,
                expected_manifest_sha256=result["manifest"]["manifest_sha256"],
            ),
            result,
        )
