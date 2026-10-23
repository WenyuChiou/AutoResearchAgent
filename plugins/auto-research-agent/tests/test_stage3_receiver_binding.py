"""Receiver provenance checks with authored fixtures, never real human identity."""

# ruff: noqa: E402 -- existing repository test import convention.
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent / "cli"), str(HERE)]

from stage2_common import Stage2Error, canonical_hash
from stage3_plan.intake import admit_intake, project_intake


class Stage3ReceiverBindingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Import inside the setup so unittest does not collect the upstream suite.
        from test_stage2_ui_submission import UISubmissionTests

        cls.fixture = UISubmissionTests()
        cls.fixture.setUp()
        cls.addClassCleanup(cls.fixture.doCleanups)
        prepared = cls.fixture.prepare()
        cls.pin = prepared["manifest"]["manifest_sha256"]
        cls.handoff = cls.fixture.inspect(cls.pin)["handoff"]

    def admit(self, package=None, pin=None):
        return admit_intake(
            package or self.fixture.package,
            self.fixture.delivery,
            expected_manifest_sha256=pin or self.pin,
        )

    def test_public_admission_preserves_ui_origin_without_promoting_authority(self):
        with patch(
            "stage3_plan.native.NativePlanner.__call__",
            side_effect=AssertionError("receiver must not generate a plan"),
        ) as native:
            admitted = self.admit()
        native.assert_not_called()
        self.assertTrue(
            "input_origin" in admitted, "verified UI origin is missing from intake"
        )
        self.assertEqual(admitted["input_origin"], self.handoff["input_origin"])
        self.assertIs(type(admitted["input_origin"]["input_version"]), int)
        self.assertEqual(admitted["input_origin"]["human_identity"], "not-established")
        self.assertEqual(admitted["input_origin"]["kind"], "projecthost-ui-submission")
        self.assertEqual(admitted["source_manifest_sha256"], self.pin)
        self.assertEqual(
            admitted["selected_candidates"], self.handoff["decision"]["selected"]
        )
        self.assertFalse(admitted["execution_authorized"])

    def test_projection_keeps_version_type_without_claiming_string_admission(self):
        # Only projection is tested here. Shared UI admission must separately
        # authorize the string-version contract; this helper cannot establish it.
        for version in ("1", 1):
            with self.subTest(version=version, type=type(version).__name__):
                source = deepcopy(self.handoff)
                source["input_origin"]["input_version"] = version
                projected = project_intake(source, self.pin)
                self.assertIs(
                    type(projected["input_origin"]["input_version"]), type(version)
                )
                self.assertEqual(projected["input_origin"]["input_version"], version)
                projected["input_origin"]["project_ref"] = "changed-in-caller"
                self.assertEqual(
                    source["input_origin"]["project_ref"],
                    self.handoff["input_origin"]["project_ref"],
                )

    def test_wrong_external_pin_is_rejected(self):
        with self.assertRaises(Stage2Error):
            self.admit(pin="0" * 64)

    def test_rehashed_handoff_changes_cannot_replace_verified_origin_or_choice(self):
        changes = (
            ("project_ref", "another-project"),
            ("input_version", "1"),
            ("input_version", True),
            ("kind", "native-codex"),
            ("candidate_version", None),
            ("duplicate_selection", None),
        )
        for field, value in changes:
            with self.subTest(field=field, value=value):
                temp = tempfile.TemporaryDirectory()
                self.addCleanup(temp.cleanup)
                package = Path(temp.name).resolve() / "private-planning-copy"
                shutil.copytree(self.fixture.package, package)
                source = deepcopy(self.handoff)
                if field == "candidate_version":
                    source["decision"]["selected"][0]["candidate_version"] += 1
                elif field == "duplicate_selection":
                    source["decision"]["selected"].append(
                        deepcopy(source["decision"]["selected"][0])
                    )
                else:
                    source["input_origin"][field] = value
                (package / "planning_handoff.json").write_text(
                    json.dumps(source), encoding="utf-8"
                )
                path = package / "planning_manifest.json"
                manifest = json.loads(path.read_bytes())
                for row in manifest["files"]:
                    raw = (package / row["path"]).read_bytes()
                    row.update(sha256=hashlib.sha256(raw).hexdigest(), size=len(raw))
                manifest["manifest_sha256"] = canonical_hash(
                    {k: v for k, v in manifest.items() if k != "manifest_sha256"}
                )
                path.write_text(json.dumps(manifest), encoding="utf-8")
                with self.assertRaises(Stage2Error):
                    self.admit(package, manifest["manifest_sha256"])


if __name__ == "__main__":
    unittest.main()
