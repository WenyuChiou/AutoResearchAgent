import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace

from research_workspace_native.project_stage2_controller_config import (
    Stage2ControllerProfile,
)
from research_workspace_native.project_intake import ProjectIntakeService
from research_workspace_native.project_stage2_controller_connections import (
    Stage2ControllerConnections,
)
from research_workspace_native.project_stage_connections import (
    BindingTable,
    ConnectionStore,
)
from research_workspace_native.session_api import SessionApiError


class Stage2ControllerProfileTests(unittest.TestCase):
    def test_pinned_relative_profile_reopens_original_bytes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            path = root / "profile.json"
            data = {
                "kind": "ProjectStage2ControllerProfile",
                "schema_version": "1.0.0",
                "project_parent": str(root / "controllers"),
                "max_projects": 2,
                "policy_ref": {
                    "route": "stage2-general-v3/daily_v3",
                    "packet_profile": "scientific-v3",
                },
                "spec_path": "spec.json",
                "spec_sha256": "a" * 64,
                "controller_root": "controller",
                "delivery_root": "delivery",
                "preparation_path": "prep.json",
                "preparation_sha256": "b" * 64,
            }

            def load():
                raw = json.dumps(data).encode()
                path.write_bytes(raw)
                return Stage2ControllerProfile(path, hashlib.sha256(raw).hexdigest())

            profile = load()
            row, policy, limit = profile.resolve("project-abc")
            self.assertEqual(
                row["spec_path"], str(root / "controllers/project-abc/spec.json")
            )
            self.assertEqual(row["project_ref"], "project-abc")
            self.assertEqual(policy, data["policy_ref"])
            self.assertEqual(limit, 2)
            path.write_bytes(path.read_bytes() + b" ")
            with self.assertRaisesRegex(ValueError, "configuration-hash-differs"):
                profile.resolve("project-abc")
            with self.assertRaisesRegex(ValueError, "unsafe artifact path"):
                data["spec_path"] = "../spec.json"
                load()

    def test_discovery_isolates_malformed_project_from_healthy_selection(self):
        with tempfile.TemporaryDirectory() as temp:
            # Use the physical directory we just created as the trusted test root.
            root = Path(temp).resolve()
            intake = ProjectIntakeService(root, authenticate=lambda _: "local-viewer")
            try:
                good, bad = (
                    intake.create("own", {"key": key, "topic": topic})["project_ref"]
                    for key, topic in (
                        ("good", "Healthy fixture"),
                        ("bad", "Damaged fixture"),
                    )
                )
                intake.db.execute(
                    "UPDATE intake_projects SET state='{' WHERE ref=?", (bad,)
                )
                records = root / "controller"
                records.mkdir()
                (records / "result.json").touch()
                controllers = Stage2ControllerConnections(
                    SimpleNamespace(
                        projects=intake,
                        credential="own",
                        project_stage2_controllers={
                            good: SimpleNamespace(records=records)
                        },
                    ),
                    None,
                )
                selection = BindingTable({}, ConnectionStore(intake, "own"))
                selection.controllers = controllers
                self.assertEqual(list(selection), [good])
                with self.assertRaisesRegex(
                    SessionApiError, "stage-connection-source-invalid"
                ):
                    controllers[bad]
            finally:
                intake.close()
