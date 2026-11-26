"""Real V9 Wiki renderer over the isolated Stage2/Stage3 Host fixture."""

import json
import os
from pathlib import Path
import sys
import tempfile
import threading
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
import project_stage3_host_e2e_fixture as host_seed  # noqa: E402
from research_workspace_native.atlas_host import AtlasHandler  # noqa: E402
from research_workspace_native.project_host import ProjectHandler  # noqa: E402
from stage3_plan.storage import private_output  # noqa: E402
from test_project_stage3_host_e2e import HostConnection  # noqa: E402


_renderer_install_lock = threading.Lock()


class _WikiHostDirectory(host_seed.EvidenceDirectory):
    def __init__(self, *args, evidence_root, **kwargs):
        if not args and kwargs == {"prefix": "rich-controller-choice-"}:
            # The Windows Wiki fixture already reserved a private directory
            # for this project. Avoid adding another long prefix inside it.
            self.name = str(evidence_root)
        else:
            super().__init__(*args, evidence_root=evidence_root, **kwargs)


def wiki_host_artifacts(evidence_root, *, short_paths):
    if not short_paths:
        return evidence_root / "host-artifacts", host_seed.EvidenceDirectory

    parent = private_output(evidence_root.parent)
    workspace = Path(tempfile.mkdtemp(prefix="", dir=parent))
    # Record the pairing before any Stage 2 setup so failed cases are traceable.
    with (evidence_root / "host-workspace.json").open("x", encoding="utf-8") as stream:
        json.dump({"workspace": str(workspace)}, stream)
    return workspace, _WikiHostDirectory


class ProjectWikiCompletionFixture:
    """Install the production V9 renderer without replacing Host services."""

    def __init__(self, case, evidence_root):
        self.case = case
        self.evidence_root = Path(evidence_root).resolve()
        self.evidence_root.mkdir(parents=True, exist_ok=False)
        workspace, directory_factory = wiki_host_artifacts(
            self.evidence_root, short_paths=os.name == "nt"
        )
        self.seed = host_seed.Stage3HostE2ESeed(
            case, evidence_root=workspace, evidence_directory=directory_factory
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
        with (
            _renderer_install_lock,
            patch.object(run_v7, "main", side_effect=install_only),
        ):
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
