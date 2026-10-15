"""Saved canonical 1.2 presenter and exact native renderer byte binding."""

import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from test_project_stage1_discovery_records import discovery_candidates
from test_project_stage1_records import saved_stage1_case
from research_workspace_native import project_atlas_shell as shell
from research_workspace_native import project_stage1_atlas as atlas
from research_workspace_native.session_api import SessionApiError
from stage1_deliverable.common import sha

PLUGIN = Path(__file__).resolve().parents[1]


class ProjectAtlasScreeningTests(unittest.TestCase):
    def test_missing_duplicate_or_already_derived_ledger_entry_is_refused(self):
        for ui in (
            b"no ledger entry",
            shell.LEDGER_ENTRY * 2,
            shell.LEDGER_ENTRY + b" ProjectAtlasScreening",
        ):
            with self.subTest(ui=ui), self.assertRaisesRegex(ValueError, "binding"):
                shell.renderer_assets({"atlas-ui.js": ui})

    def test_saved_mixed_library_real_renderer_selection_and_trilingual_history(self):
        with saved_stage1_case() as (case, fixture):
            discovery_candidates(case, fixture)
            offer = case.produce(fixture)
            case.delivery.deliver(
                "alice-token", fixture["ref"], case.body(fixture, offer)
            )
            case.reopen()
            service = atlas.ProjectStage1AtlasService(case.delivery)
            state = case.intake._load("alice", fixture["ref"])
            artifact = state["stage1_canonical_package"]
            args = dict(
                input_version=state["input_version"],
                revision=state["revision"],
                artifact_ref=artifact["artifact_ref"],
                manifest_sha256=artifact["manifest_sha256"],
            )
            changes = case.intake.db.total_changes
            with (
                patch.object(
                    case.intake, "_perform", side_effect=AssertionError("I/O")
                ),
                patch.object(case.intake, "_save", side_effect=AssertionError("write")),
            ):
                view = service.read("alice-token", fixture["ref"], **args)
                assets = shell.shell_assets(shell.WEB_ROOT)
                self.assertEqual(
                    {
                        name.removeprefix("/project-atlas-static/"): sha(raw)
                        for name, raw in assets.items()
                        if name.startswith("/project-atlas-static/")
                    },
                    service.renderer_sha256,
                )
                self.assertNotEqual(
                    service._base_renderer_sha256["atlas-ui.js"],
                    service.renderer_sha256["atlas-ui.js"],
                )
                real = atlas.renderer_assets

                def changed(*values):
                    result = real(*values)
                    result["project-atlas-screening.js"] += b" /* changed */"
                    return result

                with (
                    patch.object(atlas, "renderer_assets", side_effect=changed),
                    self.assertRaisesRegex(SessionApiError, "renderer-bytes-differ"),
                ):
                    service.read("alice-token", fixture["ref"], **args)
                self.assertEqual(case.intake.db.total_changes, changes)
                self.assertEqual(
                    service.read("alice-token", fixture["ref"], **args), view
                )
            case.runner.assert_not_called()
            node = shutil.which("node")
            self.assertIsNotNone(node, "Node required for actual renderer DOM checks")
            with tempfile.TemporaryDirectory(prefix="atlas-ledger-") as temp:
                temp = Path(temp)
                (temp / "payload.json").write_text(
                    json.dumps(view["payload"], ensure_ascii=True), encoding="utf8"
                )
                (temp / "ui.js").write_bytes(
                    assets["/project-atlas-static/atlas-ui.js"]
                )
                result = subprocess.run(
                    [
                        node,
                        str(PLUGIN / "tests/browser/project-atlas-screening-test.cjs"),
                        str(temp),
                    ],
                    capture_output=True,
                    text=True,
                    encoding="utf8",
                    timeout=30,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                print(result.stdout.strip())


if __name__ == "__main__":
    unittest.main()
