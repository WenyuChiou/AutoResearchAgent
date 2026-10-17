"""Select V7 on the repository's real ProjectHost; startup performs no research."""

import argparse
import json
from pathlib import Path
import runpy
import subprocess
import sys
import webbrowser

from build_v7 import canonical, sha, snapshot
from saved_views import snapshot_saved_views
from native_routes import handle_native

LAUNCHER = "plugins/auto-research-agent/references/research-workspace/examples/run-project-workspace.py"
LIMIT_KEYS = {"model_calls", "seconds", "search_calls", "source_reads", "rounds"}
HOST_KEYS = ("projects", "models", "stage1", "stage2", "credential", "files", "views",
             "stage1_materials_root", "stage1_sources", "stage1_source_dispatcher")
CSP = ("default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
       "connect-src 'self'; img-src 'self' data:; font-src 'self'; object-src 'none'; "
       "base-uri 'none'; form-action 'none'; frame-ancestors 'none'")


def limits_file(path):
    raw = path.read_bytes()
    if len(raw) > 4096:
        raise ValueError("run limits must be a small JSON object")
    value = json.loads(raw)
    if not isinstance(value, dict) or set(value) != LIMIT_KEYS:
        raise ValueError("run limits require exactly: " + ", ".join(sorted(LIMIT_KEYS)))
    if any(type(item) is not int or item < 0 for item in value.values()):
        raise ValueError("run limits must be explicit nonnegative integers")
    return value


def revision(repo):
    # The actual source inventory below is authoritative, also for an exported checkout.
    try:
        result = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                                capture_output=True, text=True, check=False)
    except OSError:
        return "Unknown"
    value = result.stdout.strip()
    return value if result.returncode == 0 and len(value) == 40 else "Unknown"


def metadata(args, inventory, renderer, limits):
    return {
        "kind": "V7RuntimeConfiguration", "schema_version": "1.0.0",
        "harness_head": revision(args.repo), "harness_inventory_sha256": sha(canonical(inventory)),
        "renderer_manifest_sha256": sha(canonical(renderer)),
        "model": args.model if args.enable_content_model else "unconnected",
        "run_limits": limits,
        "evidence": "operator-configured; registration is not research acceptance",
        "execution_authorized": False,
        "content_model_registered": bool(args.enable_content_model),
        "query_runtime_registered": args.stage1_query_runtime is not None,
        "source_worker_requested": bool(args.enable_public_sources),
        "stage2": "canonical-import-only; native execution unconnected",
        "stages3_to6": "planned/unconnected",
    }


def install_renderer(host, assets, meta, project_handler, atlas_handler):
    class V7Handler(project_handler):
        def do_GET(self):
            if handle_native(self, 'GET'):
                return
            # ProjectHost's saved-view redirect must not replace this V7 root.
            # The normal Atlas handler still enforces Host, Origin and fetch-site.
            if self.path in ("/", "/index.html"):
                return atlas_handler.do_GET(self)
            return super().do_GET()

        def do_POST(self):
            if handle_native(self, 'POST'):
                return
            return super().do_POST()

        def send_header(self, name, value):
            if name.lower() == "content-security-policy" and self.path in ("/", "/index.html"):
                return atlas_handler.send_header(self, name, CSP)
            return super().send_header(name, value)

    host.RequestHandlerClass = V7Handler
    host._assets.update(assets)
    host._assets.update(snapshot_saved_views(host._assets, host.views))
    host._assets["/v7-case.json"] = canonical(meta)
    host.host_binding.update(project_home_route="/", project_operations_presentation="v7-stage-separated",
                             v7_renderer_manifest_sha256=meta["renderer_manifest_sha256"])
    host.host_binding["served_files"] = {
        route: sha(raw) for route, raw in host._assets.items() if route != "/host-binding.json"
    }
    host._assets["/host-binding.json"] = canonical(host.host_binding)


def close_services(services, host):
    try:
        if host is not None and getattr(host, 'v7_native_stage1', None) is not None:
            host.v7_native_stage1.close()
        if host is not None:
            host.server_close()
        else:
            owner = services.get("stage1_source_dispatcher") or services.get("stage1_sources")
            if owner is not None:
                owner.close()
    finally:
        try:
            if services.get("queries") is not None:
                services["queries"].close()
        finally:
            try:
                if services.get("models") is not None:
                    services["models"].close()
            finally:
                services["projects"].close()


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    selection = argparse.ArgumentParser(add_help=False)
    selection.add_argument("--repo", type=Path, required=True)
    selected, _ = selection.parse_known_args(argv)
    repo = selected.repo.resolve()
    launcher = repo / LAUNCHER
    if not launcher.is_file():
        raise ValueError("selected checkout lacks the production workspace launcher")
    boot = runpy.run_path(str(launcher))
    parser = boot["parser"]()
    parser.description = __doc__
    parser.add_argument("--run-limits", type=Path, required=True,
                        help="Explicit project resource envelope JSON, not research authorization or acceptance")
    parser.add_argument('--native-stage1-config', type=Path)
    parser.add_argument('--native-stage1-config-sha256')
    args = parser.parse_args(argv)
    args.repo = repo
    limits = limits_file(args.run_limits)
    native_config = None
    if (args.native_stage1_config is None) != (args.native_stage1_config_sha256 is None):
        raise ValueError('native config and external SHA are required together')
    if args.native_stage1_config is not None:
        raw = args.native_stage1_config.read_bytes()
        if len(raw) > 1024*1024 or sha(raw) != args.native_stage1_config_sha256:
            raise ValueError('native startup configuration differs')
        native_config = json.loads(raw)
        if (set(native_config) != {'kind', 'private_root', 'cases', 'presentations'}
                or native_config['kind'] != 'V7NativeStage1Configuration'):
            raise ValueError('native startup configuration shape differs')
    assets, renderer = snapshot(repo)
    checked = boot["inspect_inputs"](args)
    source, inventory = boot["install_source"](checked)
    checked.update(source=source, inventory=inventory)
    meta = metadata(args, inventory, renderer, limits)
    receipt = {"kind": "V7ProjectWorkspaceStartup", "renderer_manifest_sha256": meta["renderer_manifest_sha256"],
               "harness_inventory_sha256": meta["harness_inventory_sha256"],
               "model_calls": 0, "search_calls": 0, "execution_authorized": False,
               "resource_envelope_is_research_acceptance": False,
               "model": meta["model"], "stage2": meta["stage2"], "stages3_to6": meta["stages3_to6"]}
    if args.check_only:
        print(json.dumps(dict(receipt, status="filesystem-and-raw-loader-preflight-only")), flush=True)
        return 0
    services, host = boot["prepare"](args, checked), None
    try:
        if not args.prepare_only:
            from research_workspace_native.atlas_host import AtlasHandler
            from research_workspace_native.project_host import ProjectHandler

            host = services["host_type"](**{key: services[key] for key in HOST_KEYS},
                                         host="127.0.0.1", port=args.port)
            host.v7_native_stage1 = None
            if native_config is not None:
                from native_stage1 import NativeStage1Service
                from native_outputs import NativeOutputs
                private = Path(native_config['private_root'])
                host.v7_native_presentations = native_config['presentations']
                for case in native_config['cases']:
                    if host.v7_native_presentations[case['ref']]['project_id'] != case['project_id']:
                        raise ValueError('native case presentation association differs')
                host.v7_native_results = NativeOutputs(private / 'verified-results', native_config['presentations'])
                host.v7_native_stage1 = NativeStage1Service(private, native_config['cases'],
                    on_completed=host.v7_native_results.collect)
            install_renderer(host, assets, meta, ProjectHandler, AtlasHandler)
            receipt["url"] = host.expected_origin + "/"
        receipt["status"] = "prepared-only" if args.prepare_only else "local-V7-Wiki-ready"
        print(json.dumps(receipt, sort_keys=True), flush=True)
        if host is not None:
            if args.open:
                webbrowser.open(receipt["url"])
            host.serve_forever(poll_interval=0.2)
        return 0
    except KeyboardInterrupt:
        return 0
    finally:
        close_services(services, host)


if __name__ == "__main__":
    raise SystemExit(main())
