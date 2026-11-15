"""Real V9 Wiki renderer over the isolated Stage2/Stage3 Host fixture."""

import json
from pathlib import Path
import sys
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[3]
HARNESS_UI = ROOT / "harness-ui"
PLUGIN_CLI = ROOT / "plugins" / "auto-research-agent" / "cli"
for import_root in (HARNESS_UI, PLUGIN_CLI):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from build_v7 import canonical, sha, snapshot  # noqa: E402
import run_v7  # noqa: E402
import run_v9  # noqa: E402
from research_workspace_native.atlas_host import AtlasHandler  # noqa: E402
from research_workspace_native.project_host import ProjectHandler  # noqa: E402
from project_stage3_host_e2e_fixture import Stage3HostE2ESeed  # noqa: E402
from test_project_stage3_host_e2e import HostConnection  # noqa: E402


class ProjectWikiCompletionFixture:
    """Install the production V9 renderer without replacing Host services."""

    def __init__(self, case, evidence_root):
        self.case = case
        self.evidence_root = Path(evidence_root).resolve()
        self.evidence_root.mkdir(parents=True, exist_ok=False)
        self.seed = Stage3HostE2ESeed(
            case, evidence_root=self.evidence_root / "host-artifacts"
        )
        self.connection = HostConnection(case, self.seed)
        assets, renderer = snapshot(ROOT)
        self.renderer_manifest = renderer
        self.renderer_manifest_sha256 = sha(canonical(renderer))
        state = self.evidence_root / "ui-state"
        incoming = self.evidence_root / "incoming"
        state.mkdir()
        incoming.mkdir()
        invoked = []

        def install_only(arguments):
            invoked.append(list(arguments))
            run_v7.install_renderer(
                self.connection.host,
                assets,
                {"renderer_manifest_sha256": self.renderer_manifest_sha256},
                ProjectHandler,
                AtlasHandler,
            )
            return 0

        arguments = [
            "--ui-state-root",
            str(state),
            "--incoming-root",
            str(incoming),
            "--repo",
            str(ROOT),
        ]
        with patch.object(run_v7, "main", side_effect=install_only):
            case.assertEqual(run_v9.main(arguments), 0)
        case.assertEqual(len(invoked), 1)
        case.assertEqual(self.connection.host.host_binding["ui_version"], "V9")
        case.assertEqual(
            self.connection.host.host_binding["v7_renderer_manifest_sha256"],
            self.renderer_manifest_sha256,
        )
        case.assertTrue(
            self.connection.host.host_binding["v9"]["stage3_planning_configured"]
        )

    @property
    def origin(self):
        return self.connection.host.expected_origin

    def write_renderer_receipt(self):
        target = self.evidence_root / "renderer-receipt.json"
        with target.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(
                {
                    "kind": "ProjectWikiV9RendererReceipt",
                    "renderer_manifest_sha256": self.renderer_manifest_sha256,
                    "three_core": self.renderer_manifest["three_core"],
                    "ui_version": self.connection.host.host_binding["ui_version"],
                    "served_files": self.connection.host.host_binding["served_files"],
                },
                stream,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            stream.write("\n")
        return target
