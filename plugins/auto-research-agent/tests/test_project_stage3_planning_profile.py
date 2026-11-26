"""Closed Stage 3 profile paths and journal selection."""

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from research_workspace_native.project_stage3_planning_config import (
    Stage3PlanningProfile,
    validate_profile_journal,
)
from stage3_plan.contracts import Stage3Error


class Stage3PlanningProfileTests(unittest.TestCase):
    def test_pinned_profile_resolves_only_server_owned_paths(self):
        with tempfile.TemporaryDirectory(prefix="s3p-") as temp:
            # Pass the physical path of the directory owned by this fixture.
            root = Path(temp).resolve()
            codex, home = root / "unused-codex", root / "home"
            codex.touch()
            home.mkdir()
            settings = {
                "kind": "ProjectStage3PlanningProfile",
                "schema_version": "1.0.0",
                "journal_path": str(root / "planning.sqlite"),
                "project_parent": str(root / "runtime"),
                "max_projects": 2,
                "jobs_root": "jobs",
                "configuration": {"model": "authored-fixture", "reasoning": "medium"},
                "native": {
                    "codex": str(codex),
                    "codex_home": str(home),
                    "capture_dir": "capture",
                    "timeout_seconds": 5,
                },
                "recovery_pins": [],
            }
            path = root / "profile.json"
            raw = json.dumps(settings).encode()
            path.write_bytes(raw)
            profile = Stage3PlanningProfile(path, hashlib.sha256(raw).hexdigest())
            validate_profile_journal(
                profile, {"journal_path": str(profile.journal_path)}
            )
            with self.assertRaisesRegex(Stage3Error, "profile-journal-differs"):
                validate_profile_journal(
                    profile, {"journal_path": str(root / "other.sqlite")}
                )
            row = profile.resolve("project-native", "project-native")
            self.assertEqual(row["project_id"], "project-native")
            self.assertEqual(
                Path(row["jobs_root"]), root / "runtime/project-native/jobs"
            )
            self.assertEqual(
                Path(row["native"]["capture_dir"]),
                root / "runtime/project-native/capture",
            )
            self.assertFalse((root / "planning.sqlite").exists())
            self.assertFalse((root / "runtime").exists())
            path.write_bytes(raw + b" ")
            with self.assertRaisesRegex(Stage3Error, "hash-differs"):
                profile.resolve("project-native", "project-native")

    def test_profile_has_no_browser_owned_identity(self):
        with tempfile.TemporaryDirectory(prefix="s3p-") as temp:
            path = Path(temp) / "profile.json"
            raw = b'{"project_ref":"fake-project"}'
            path.write_bytes(raw)
            with self.assertRaises(Stage3Error):
                Stage3PlanningProfile(path, hashlib.sha256(raw).hexdigest())
