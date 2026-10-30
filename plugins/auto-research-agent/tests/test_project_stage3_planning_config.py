"""Trusted CLI configuration and original Journal ownership; zero model calls."""

# ruff: noqa: E402 -- match the existing standalone CLI test imports.
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cli"))
from research_workspace_native.http import token_authenticator
from research_workspace_native.journal import Journal
from research_workspace_native.project_intake import ProjectIntakeService
from research_workspace_native.project_stage2_selection import (
    ProjectStage2SelectionService,
)
from research_workspace_native import project_stage3_planning_config as configuration
from stage3_plan.contracts import Stage3Error, digest


TOKEN = "authored-local-cli-configuration-token-00000000"


def write_json(path, value):
    raw = json.dumps(value, ensure_ascii=False).encode("utf-8")
    path.write_bytes(raw)
    return path, hashlib.sha256(raw).hexdigest()


def project(intake, token, key):
    saved = intake.create(
        token, {"key": key, "topic": "Reproducible observation study " + key}
    )
    return intake.read(token, saved["project_ref"])


def settings(root, projects):
    codex = root / "authored-codex-unused"
    codex.write_text("Never executed by these engineering tests.", encoding="utf-8")
    home = root / "authored-home"
    home.mkdir(exist_ok=True)
    return {
        "kind": "ProjectStage3PlanningConfiguration",
        "schema_version": "1.0.0",
        "journal_path": str(root / "planning.sqlite"),
        "bindings": [
            dict(
                project_ref=p["project_ref"],
                project_id=p["project_id"],
                jobs_root=str(root / ("jobs-" + str(i))),
                configuration={
                    "model": "authored-offline-fixture",
                    "reasoning": "medium",
                },
                native=dict(
                    codex=str(codex),
                    codex_home=str(home),
                    capture_dir=str(root / ("capture-" + str(i))),
                    timeout_seconds=5,
                ),
                recovery_pins=[],
            )
            for i, p in enumerate(projects)
        ],
    }


class Stage3PlanningConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = self.enterContext(
            tempfile.TemporaryDirectory(prefix="stage3-cli-config-")
        )
        self.root = Path(self.tmp).resolve()
        self.intake = ProjectIntakeService(
            self.root / "projects",
            authenticate=token_authenticator({TOKEN: "local-viewer"}),
        )
        self.addCleanup(self.intake.close)
        self.project = project(self.intake, TOKEN, "first")
        self.value = settings(self.root, [self.project])
        self.selection = ProjectStage2SelectionService(self.intake, {})
        self.native = self.enterContext(
            patch.object(
                configuration.NativePlanner,
                "__call__",
                side_effect=AssertionError("Model forbidden"),
            )
        )
        self.addCleanup(self.native.assert_not_called)

    def load(self, value):
        path, pin = write_json(self.root / "configuration.json", value)
        return configuration.load_stage3_planning_configuration(
            self.intake, TOKEN, path, pin
        )

    def test_load_is_read_only_and_returns_independent_settings(self):
        loaded = self.load(self.value)
        self.assertEqual(loaded, self.value)
        loaded["bindings"][0]["configuration"]["model"] = "changed"
        self.assertNotEqual(loaded, self.value)
        self.assertFalse((self.root / "planning.sqlite").exists())
        self.assertFalse((self.root / "jobs-0").exists())
        self.assertFalse((self.root / "capture-0").exists())

    def test_direction_capture_collision_rejects_before_opening_journal(self):
        value = deepcopy(self.value)
        capture = Path(value["bindings"][0]["native"]["capture_dir"])
        value["bindings"][0]["jobs_root"] = str(
            capture.with_name(capture.name + "-direction")
        )
        with self.assertRaisesRegex(Stage3Error, "output-overlap"):
            self.load(value)
        self.assertFalse((self.root / "planning.sqlite").exists())

    def test_closed_shapes_identity_deadline_and_output_collisions_fail_before_io(self):
        cases = []
        for name, mutate in (
            ("root-extra", lambda v: v.update(execution_authorized=True)),
            ("binding-extra", lambda v: v["bindings"][0].update(callback="arbitrary")),
            (
                "wrong-project-id",
                lambda v: v["bindings"][0].update(project_id="wrong-id"),
            ),
            (
                "duplicate-project",
                lambda v: v["bindings"].append(deepcopy(v["bindings"][0])),
            ),
            ("relative-journal", lambda v: v.update(journal_path="relative.sqlite")),
            (
                "nested-output",
                lambda v: v["bindings"][0]["native"].update(
                    capture_dir=v["bindings"][0]["jobs_root"] + "/nested"
                ),
            ),
            (
                "missing-executable",
                lambda v: v["bindings"][0]["native"].update(
                    codex=str(self.root / "absent")
                ),
            ),
            (
                "boolean-deadline",
                lambda v: v["bindings"][0]["native"].update(timeout_seconds=True),
            ),
            (
                "nonfinite-deadline",
                lambda v: v["bindings"][0]["native"].update(
                    timeout_seconds=float("nan")
                ),
            ),
            (
                "zero-deadline",
                lambda v: v["bindings"][0]["native"].update(timeout_seconds=0),
            ),
            (
                "untrusted-key",
                lambda v: v["bindings"][0]["configuration"].update(approval="yes"),
            ),
        ):
            value = deepcopy(self.value)
            mutate(value)
            cases.append((name, value))
        for name, value in cases:
            with self.subTest(case=name), self.assertRaises((Stage3Error, ValueError)):
                self.load(value)
        self.assertFalse((self.root / "planning.sqlite").exists())
        self.assertFalse((self.root / "jobs-0").exists())
        self.assertFalse((self.root / "capture-0").exists())

    def test_raw_hash_duplicate_json_and_duplicate_recovery_pins_fail(self):
        path, pin = write_json(self.root / "configuration.json", self.value)
        with self.assertRaisesRegex(Stage3Error, "hash-differs"):
            configuration.load_stage3_planning_configuration(
                self.intake, TOKEN, path, "0" * 64
            )
        raw = path.read_bytes().replace(
            b'"schema_version": "1.0.0"',
            b'"schema_version": "1.0.0", "schema_version": "1.0.0"',
            1,
        )
        path.write_bytes(raw)
        with self.assertRaises((Stage3Error, ValueError)):
            configuration.load_stage3_planning_configuration(
                self.intake, TOKEN, path, hashlib.sha256(raw).hexdigest()
            )
        value = deepcopy(self.value)
        pin = dict(key="same", request_sha256="1" * 64, plan_manifest_sha256="2" * 64)
        value["bindings"][0]["recovery_pins"] = [pin, deepcopy(pin)]
        with self.assertRaisesRegex(Stage3Error, "duplicate-recovery"):
            self.load(value)
        self.assertFalse((self.root / "planning.sqlite").exists())

    def test_real_factory_reopens_stable_identity_and_maps_trusted_pins(self):
        pin = dict(key="saved", request_sha256="1" * 64, plan_manifest_sha256="2" * 64)
        self.value["bindings"][0]["recovery_pins"] = [pin]
        first = configuration.Stage3PlanningHostResources(
            self.intake, TOKEN, self.selection, self.load(self.value)
        )
        identity = deepcopy(first.identities)
        self.assertEqual(
            first.recovery_pins,
            {(self.project["project_ref"], "saved", "1" * 64): "2" * 64},
        )
        self.assertEqual(
            identity[self.project["project_ref"]]["project_id"],
            self.project["project_id"],
        )
        self.assertEqual(
            identity[self.project["project_ref"]]["projects_root"],
            str(self.intake.root),
        )
        first.close()
        first.close()
        second = configuration.Stage3PlanningHostResources(
            self.intake, TOKEN, self.selection, self.load(self.value)
        )
        self.addCleanup(second.close)
        self.assertEqual(second.identities, identity)

    def test_wrong_existing_journal_binding_is_not_relabelled(self):
        journal = Journal(self.value["journal_path"])
        journal.bind_project(self.project["project_id"], digest({"incompatible": True}))
        journal.close()
        with self.assertRaises(Exception):
            configuration.Stage3PlanningHostResources(
                self.intake, TOKEN, self.selection, self.value
            )
        self.assertFalse((self.root / "capture-0").exists())

    def test_two_real_projects_have_distinct_owners_and_cannot_share_capture(self):
        other = project(self.intake, TOKEN, "second")
        value = settings(self.root, [self.project, other])
        owner = configuration.Stage3PlanningHostResources(
            self.intake, TOKEN, self.selection, value
        )
        self.addCleanup(owner.close)
        self.assertEqual(
            set(owner.identities), {self.project["project_ref"], other["project_ref"]}
        )
        self.assertEqual(len(set(owner._owners.values())), 2)
        jobs = [
            owner.service.bindings[p["project_ref"]]["jobs"]
            for p in (self.project, other)
        ]
        same_key = "same-browser-key"
        self.assertEqual(jobs[0]._key(same_key), jobs[1]._key(same_key))
        self.assertNotEqual(
            (jobs[0].project_id, jobs[0].root), (jobs[1].project_id, jobs[1].root)
        )
        self.assertIs(jobs[0].journal, jobs[1].journal)
        value["bindings"][1]["native"]["capture_dir"] = value["bindings"][0]["native"][
            "capture_dir"
        ]
        with self.assertRaisesRegex(Stage3Error, "output-overlap"):
            self.load(value)

    def test_constructor_failure_releases_first_owner_and_keeps_cleanup_notes(self):
        primary = RuntimeError("authored callback construction failure")
        with patch.object(configuration, "NativePlanner", side_effect=primary):
            with self.assertRaises(RuntimeError) as raised:
                configuration.Stage3PlanningHostResources(
                    self.intake, TOKEN, self.selection, self.value
                )
        self.assertIs(raised.exception, primary)
        journal = Journal(self.value["journal_path"])
        self.addCleanup(journal.close)
        token = journal.acquire_owner(
            self.project["project_id"], "after-failed-construction"
        )
        journal.release_owner(self.project["project_id"], token)
        with (
            patch.object(configuration, "NativePlanner", side_effect=primary),
            patch.object(
                Journal,
                "release_owner",
                side_effect=RuntimeError("authored lease cleanup failure"),
            ),
        ):
            with self.assertRaises(RuntimeError) as raised:
                configuration.Stage3PlanningHostResources(
                    self.intake, TOKEN, self.selection, self.value
                )
        self.assertIs(raised.exception, primary)
        self.assertTrue(
            any("lease cleanup failure" in note for note in primary.__notes__)
        )


if __name__ == "__main__":
    unittest.main()
