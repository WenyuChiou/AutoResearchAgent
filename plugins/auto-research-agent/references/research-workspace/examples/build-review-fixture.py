"""Build public synthetic Stage 1/2 review views; optionally serve on loopback.

This example reuses repository fixtures with injected source/judge behavior.
It never checks Codex, creates a native runtime, calls a model or searches.
"""

import argparse
import json
from pathlib import Path
import shutil
import sys
import webbrowser

PLUGIN = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(PLUGIN / "cli"), str(PLUGIN / "tests")]

from research_workspace.stage2_import import prepare_stage2_bridge  # noqa: E402
from research_workspace.view import write_workspace  # noqa: E402
from research_workspace_native.atlas_host import AtlasHost, load_views  # noqa: E402
from stage1_deliverable.common import canonical, private_output, sha  # noqa: E402
from test_research_workspace_view import fixture_index  # noqa: E402
from test_stage2_content_delivery import ContentDeliveryTests  # noqa: E402


def save(path, value):
    with path.open("xb") as stream:
        stream.write(canonical(value))


def build(output):
    root = private_output(output)
    root.mkdir(parents=True, exist_ok=False)
    reference = PLUGIN / "references/research-workspace"
    index = fixture_index()
    write_workspace(index, reference, root / "stage1", atlas=True)
    fixture = ContentDeliveryTests()
    fixture.setUp()
    try:
        manifest = fixture.deliver()
        delivery = root / "stage2-delivery"
        shutil.copytree(fixture.root / "evaluated", delivery)
        bridge = prepare_stage2_bridge(
            index, delivery, expected_manifest_sha256=manifest["manifest_sha256"]
        )
        save(root / "stage2-bridge.json", bridge)
        write_workspace(
            index,
            reference,
            root / "stage2",
            atlas=True,
            stage2_delivery=delivery,
            stage2_bridge=bridge,
            expected_stage2_bridge_sha256=sha(canonical(bridge)),
        )
        selection = json.loads((delivery / "core_selection.json").read_bytes())
    finally:
        fixture.doCleanups()
    config = {
        "views": [
            {
                "ref": stage,
                "label": stage.upper() + " synthetic repository case",
                "manifest": str(root / stage / "view-manifest.json"),
                "sha256": sha((root / stage / "view-manifest.json").read_bytes()),
                "fixture": True,
            }
            for stage in ("stage1", "stage2")
        ]
    }
    path = root / "host.json"
    save(path, config)
    pin = sha(path.read_bytes())
    files, views = load_views(path, pin)
    receipt = {
        "kind": "SyntheticAtlasReviewFixture",
        "config": str(path),
        "config_sha256": pin,
        "index_sha256": sha(canonical(index)),
        "builder_sha256": sha(Path(__file__).read_bytes()),
        "project_id": index["project_id"],
        "views": views,
        "retained_status": index["status"],
        "stage1_papers": len(index["papers"]),
        "stage2_literature": len(selection["evaluation_packet"].get("literature", [])),
        "classification": "synthetic-repository-fixture",
        "original_stage1_lineage_attested": False,
        "execution_authority": False,
        "scientific_quality_verified": False,
        "native_process_started": False,
        "model_call_started": False,
    }
    save(root / "fixture-receipt.json", receipt)
    print(json.dumps(receipt, ensure_ascii=True), flush=True)
    return files, views


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--open", action="store_true")
    parser.add_argument("--port", type=int, default=0)
    args = parser.parse_args()
    if args.open and not args.serve:
        parser.error("--open requires --serve")
    files, views = build(args.output)
    if args.serve:
        server = AtlasHost(files=files, views=views, port=args.port)
        print(server.expected_origin + "/", flush=True)
        if args.open:
            webbrowser.open(server.expected_origin + "/")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()


if __name__ == "__main__":
    main()
