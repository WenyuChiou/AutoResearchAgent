"""Explicit fresh bounded local Codex Atlas; no automatic model turn."""

import argparse
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import stat
import sys
import threading
import time
from types import ModuleType
import webbrowser

# Direct script invocation removes its sibling http.py from stdlib lookup.
if __name__ == "__main__":
    sys.path[:] = [
        p
        for p in sys.path
        if Path(p or os.getcwd()).resolve() != Path(__file__).parent.resolve()
    ]
SOURCE = PERMIT = None


def _raw(path, expected, maximum):
    path = Path(path)
    if not path.is_absolute():
        raise ValueError("absolute bootstrap path required")
    for ancestor in (path, *path.parents):
        if ancestor.exists():
            info = ancestor.lstat()
            if (
                stat.S_ISLNK(info.st_mode)
                or getattr(info, "st_file_attributes", 0) & 0x400
            ):
                raise ValueError("linked bootstrap path refused")
    if not stat.S_ISREG(path.stat().st_mode):
        raise ValueError("regular bootstrap file required")
    with path.open("rb") as stream:
        raw = stream.read(maximum + 1)
    if not 0 < len(raw) <= maximum or hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError("bootstrap byte binding differs")
    return raw


def bootstrap(args):
    permit = json.loads(_raw(args.permit, args.permit_sha256, 256 * 1024))
    pin = permit["source_manifest"]
    manifest = json.loads(_raw(pin["path"], pin["sha256"], 1024 * 1024))
    repo = Path(args.repo)
    for ancestor in (repo, *repo.parents):
        if ancestor.exists():
            info = ancestor.lstat()
            if (
                stat.S_ISLNK(info.st_mode)
                or getattr(info, "st_file_attributes", 0) & 0x400
            ):
                raise ValueError("linked repository path refused")
    if not repo.is_absolute() or repo.resolve().as_posix() != manifest["repo_root"]:
        raise ValueError("complete pinned repository required")
    paths = []
    for name in ("source", "permit"):
        alias = "_atlas_local_" + name
        if alias in sys.modules:
            raise ValueError("preloaded launcher helper; fresh process required")
        path = repo / (
            "plugins/auto-research-agent/cli/research_workspace_native/atlas_local_"
            + name
            + ".py"
        )
        relative = (
            "cli/"
            + path.relative_to(repo / "plugins/auto-research-agent/cli").as_posix()
        )
        raw = _raw(path, manifest["plugin_files"][relative], 32 * 1024 * 1024)
        module = ModuleType(alias)
        module.__file__ = str(path)
        sys.modules[alias] = module
        exec(compile(raw, str(path), "exec"), module.__dict__)
        paths.append(path)
    global SOURCE, PERMIT
    SOURCE, PERMIT = (
        sys.modules["_atlas_local_source"],
        sys.modules["_atlas_local_permit"],
    )
    return paths


def validate_user_config(spec, permit):
    from research_workspace_native.runtime_spec import (
        _thread_config,
        DENIED_THREAD_CONFIG,
    )
    import tomllib

    user = permit["user_config"]
    effective_home = SOURCE.unlinked(
        os.environ.get("CODEX_HOME") or Path.home() / ".codex"
    )
    effective_config = SOURCE.unlinked(effective_home / "config.toml").resolve()
    SOURCE.require(
        SOURCE.unlinked(user["path"]).resolve() == effective_config,
        "permit must pin inherited CODEX_HOME/config.toml",
    )
    for ancestor in (Path(spec["source_root"]), *Path(spec["source_root"]).parents):
        layer = ancestor / ".codex/config.toml"
        SOURCE.require(
            not layer.exists() or SOURCE.unlinked(layer).resolve() == effective_config,
            "additional project configuration layer is unsupported",
        )
    names = tomllib.loads(
        SOURCE.pinned(user["path"], user["sha256"]).decode("utf8")
    ).get("mcp_servers", {})
    SOURCE.require(
        isinstance(names, dict) and len(names) <= 64,
        "bounded user MCP configuration required",
    )
    SOURCE.require(
        spec["thread_config"]
        == {
            **DENIED_THREAD_CONFIG,
            **{f"mcp_servers.{name}.enabled": False for name in names},
        },
        "observed user MCP names differ from thread denials",
    )

    _thread_config(spec["thread_config"])


def validate_session_policy(spec, permit):
    """An explicit model stays inside the canonical spec/permit identity."""
    model = spec.get("model")
    SOURCE.require(
        isinstance(model, str)
        and re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", model)
        and spec["approval_policy"] == "on-request"
        and isinstance(spec.get("thread_config"), dict)
        and spec["principals"] == ["local-viewer"]
        and spec["limits"]["max_starts"] == permit["max_turns"]
        and spec["limits"]["lifetime_seconds"] == permit["lease_seconds"],
        "runtime limits/policy differ",
    )


def validate_scope_input(spec, permit):
    """Refuse an unusable scope overlay before creating the native process."""
    from stage1_deliverable.common import safe_path
    from research_workspace_native.scope_api import MAX_BRIEF, _brief

    path = safe_path(spec["source_root"], permit["brief_path"])
    SOURCE.require(path.as_posix() == spec["input_path"], "brief/input differs")
    _brief(SOURCE.pinned(path, spec["input_version"], MAX_BRIEF), spec["input_version"])


def preflight(args):
    helper_paths = bootstrap(args)
    permit = SOURCE.decode(SOURCE.pinned(args.permit, args.permit_sha256))
    spec = SOURCE.decode(SOURCE.pinned(args.spec, args.spec_sha256))
    fields = {
        "user_config",
        "kind",
        "schema_version",
        "spec_identity_sha256",
        "host_config",
        "source_manifest",
        "attempt_root",
        "brief_path",
        "stage_inputs",
        "stage_source_sha256",
        "max_turns",
        "lease_seconds",
        "sandbox",
        "network_access",
        "allow_fresh_session",
        "allow_user_messages",
        "expires_at_unix",
    }
    SOURCE.require(
        set(permit) == fields
        and permit["kind"] == "LocalCodexAtlasPermit"
        and permit["schema_version"] == "1.0.0",
        "unsupported permit schema",
    )
    SOURCE.require(
        permit["allow_fresh_session"] is True
        and permit["allow_user_messages"] is True
        and permit["sandbox"] == "read-only"
        and permit["network_access"] is False
        and type(permit["max_turns"]) is int
        and 1 <= permit["max_turns"] <= 2
        and type(permit["lease_seconds"]) is int
        and 1 <= permit["lease_seconds"] <= 600
        and type(permit["expires_at_unix"]) is int
        and time.time() < permit["expires_at_unix"] <= time.time() + 600,
        "explicit bounded fresh/message permit required",
    )
    identity = {k: v for k, v in spec.items() if k != "permit_sha256"}
    SOURCE.require(
        SOURCE.digest(SOURCE.canonical(identity)) == permit["spec_identity_sha256"]
        and spec["permit_sha256"] == args.permit_sha256,
        "runtime spec/permit identity differs",
    )
    validate_session_policy(spec, permit)
    SOURCE.require(
        Path(spec["executable"]).name.casefold() in {"codex", "codex.exe"},
        "real pinned Codex executable required",
    )
    repo = SOURCE.unlinked(args.repo).resolve()
    SOURCE.require(repo.is_absolute(), "complete repository required")
    for name in ("host_config", "source_manifest", "user_config"):
        SOURCE.require(
            set(permit[name]) == {"path", "sha256"},
            "pinned registration fields differ",
        )
    SOURCE.require(
        Path(permit["host_config"]["path"]).resolve() == args.config.resolve()
        and permit["host_config"]["sha256"] == args.config_sha256,
        "host configuration differs",
    )
    manifest = SOURCE.decode(
        SOURCE.pinned(
            permit["source_manifest"]["path"],
            permit["source_manifest"]["sha256"],
            1024 * 1024,
        )
    )
    SOURCE.require(
        set(manifest)
        == {"kind", "repo_root", "source_root", "plugin_files", "source_files"}
        and manifest["kind"] == "LocalAtlasByteInventory"
        and manifest["repo_root"] == repo.as_posix()
        and manifest["source_root"] == spec["source_root"],
        "byte inventory roots differ",
    )
    attempt = SOURCE.unlinked(permit["attempt_root"])
    SOURCE.require(
        attempt.is_absolute()
        and not attempt.exists()
        and attempt.parent.is_dir()
        and Path(spec["store_path"]) == attempt / "native" / "session.sqlite3",
        "new private attempt required",
    )
    authority = PERMIT.PermitAuthority(
        spec=spec,
        spec_path=args.spec,
        spec_sha256=args.spec_sha256,
        permit_path=args.permit,
        permit_sha256=args.permit_sha256,
        permit=permit,
        manifest=manifest,
        repo=repo,
    )
    authority.helper_paths = helper_paths + [Path(__file__).resolve()]
    authority.verify(dict(spec_sha256=args.spec_sha256, spec=spec), full=True)
    loader = SOURCE.PinnedLoader(repo, manifest["plugin_files"])
    authority.loader = loader
    sys.dont_write_bytecode = True
    sys.meta_path.insert(0, loader)
    from stage1_deliverable.common import private_output
    from research_workspace_native.host_config import load_config
    from research_workspace_native.stage_inputs import snapshot_inputs, source_digest

    validate_user_config(spec, permit)
    private_output(attempt)
    config = load_config(args.config, args.config_sha256)
    matching = [
        v
        for v in config["views"]
        if v["ref"] == spec["project_ref"]
        and v["project_id"] == spec["project_id"]
        and v["index_sha256"] == spec["index_sha256"]
    ]
    SOURCE.require(len(matching) == 1, "native project/view differs")
    validate_scope_input(spec, permit)
    SOURCE.require(
        source_digest(snapshot_inputs(permit["stage_inputs"]))
        == permit["stage_source_sha256"],
        "saved stage inputs differ",
    )
    return authority, config, attempt


def launch(args):
    if not args.enable_native:
        return {
            "status": "disabled",
            "actual_codex_process_observed": False,
            "inference_attempted": False,
        }
    authority, config, attempt = preflight(args)
    from research_workspace_native.runtime_factory import compose_runtime
    from research_workspace_native.runtime_spec import _load
    from research_workspace_native.host_config import create_host, HostRegistry
    from research_workspace_native.http import token_authenticator
    from research_workspace_native.scope_api import ScopeApi
    from research_workspace_native.harness_host import create_harness_operations
    from research_workspace_native.stage_actions import StageActions

    attempt.mkdir()
    (attempt / "native").mkdir()
    runtime = operations = stages = server = None
    original_error = None
    receipt = dict(
        kind="LocalCodexAtlasAttempt",
        spec_sha256=args.spec_sha256,
        permit_sha256=args.permit_sha256,
        authenticated_process=False,
        process_tree_containment_verified=False,
        actual_codex_process_observed=False,
        inference_attempted=False,
        completed_research=False,
        status="preflight",
    )
    try:
        _load(args.spec, args.spec_sha256)
        credential = secrets.token_urlsafe(32)
        authenticate = token_authenticator({credential: "local-viewer"})
        receipt.update(status="composing", actual_codex_process_observed=None)
        runtime = compose_runtime(
            [(args.spec, args.spec_sha256)],
            enabled=True,
            authenticate=authenticate,
            gates={authority.spec["project_ref"]: authority.callbacks()},
        )
        authority.runtime = runtime
        receipt.update(
            actual_codex_process_observed=True,
            status="ready",
            observation="pinned executable spawned; bootstrap/account/thread response schemas accepted",
        )
        scope = ScopeApi(runtime.api)
        scope.register(
            authority.spec["project_ref"],
            brief_path=authority.permit["brief_path"],
            expected_sha256=authority.spec["input_version"],
        )
        operations = create_harness_operations(
            config["files"], config["views"], attempt / "harness", credential
        )
        stages = StageActions(
            attempt / "stages.sqlite3",
            authenticate=authenticate,
            registrations={
                authority.spec["project_ref"]: dict(
                    project_id=authority.spec["project_id"],
                    index_sha256=authority.spec["index_sha256"],
                    input_version=authority.spec["input_version"],
                    source_sha256=authority.permit["stage_source_sha256"],
                    inputs=authority.permit["stage_inputs"],
                    output_root=attempt / "stage-results",
                    principals=["local-viewer"],
                )
            },
        )
        config = deepcopy(config)
        config["server_object_requests"]["native"] = dict(
            mode="registered", runtime_ref="local-codex"
        )
        server = create_host(
            config,
            registry=HostRegistry(runtimes={"local-codex": runtime}),
            credential=credential,
            scope_api=scope,
            harness_ops=operations,
            stage_actions=stages,
            port=args.port,
            timeout=authority.spec["limits"]["timeout_seconds"],
            connection={
                "status": "native-ready",
                "actual_codex_process_observed": True,
                "inference_attempted": False,
                "completed_research": False,
            },
        )
        runtime.start()  # Passive pump only; no seed message or model turn.
        url = server.expected_origin + matching_url(
            config, authority.spec["project_ref"]
        )
        print(
            json.dumps(
                dict(
                    receipt,
                    url=url,
                    cleanup_receipt=str(attempt / "cleanup-receipt.json"),
                )
            ),
            flush=True,
        )
        if args.open:
            webbrowser.open(url)
        timer = threading.Timer(
            max(0, authority.deadline - time.monotonic()), server.shutdown
        )
        timer.daemon = True
        timer.start()
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            timer.cancel()
    except BaseException as error:
        original_error = error
        receipt.update(status="failed", error_type=type(error).__name__)
        raise
    finally:
        receipt["user_message_admissions"] = authority.starts
        receipt["inference_attempted"] = None if authority.starts else False
        receipt["inference_status"] = (
            "not-attested" if authority.starts else "no-user-turn-admitted"
        )
        cleanup_errors = []
        try:
            if server is not None:
                try:
                    server.server_close()
                    receipt["cleanup"] = server.native_shutdown
                except BaseException as error:
                    cleanup_errors.append(error)
            else:
                for resource in (runtime, operations, stages):
                    if resource is not None:
                        try:
                            if resource is runtime:
                                receipt["cleanup"] = resource.shutdown(timeout=10)
                            else:
                                resource.close()
                        except BaseException as error:
                            cleanup_errors.append(error)
            receipt["cleanup_status"] = (
                "unknown"
                if cleanup_errors
                else "observed"
                if runtime is not None
                else "runtime-composition-outcome-unobserved"
            )
            if cleanup_errors:
                receipt["cleanup_errors"] = [
                    type(error).__name__ for error in cleanup_errors
                ]
        finally:
            with (attempt / "cleanup-receipt.json").open("xb") as stream:
                stream.write(SOURCE.canonical(receipt) + b"\n")
        if cleanup_errors and original_error is None:
            raise cleanup_errors[0]
    return receipt


def matching_url(config, project_ref):
    return next(row["url"] for row in config["views"] if row["ref"] == project_ref)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--enable-native", action="store_true")
    for name in ("repo", "config", "spec", "permit"):
        parser.add_argument("--" + name, type=Path)
    for name in ("config", "spec", "permit"):
        parser.add_argument("--" + name + "-sha256")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--open", action="store_true")
    args = parser.parse_args(argv)
    if args.enable_native:
        if not all(
            getattr(args, name) is not None
            for name in (
                "repo",
                "config",
                "spec",
                "permit",
                "config_sha256",
                "spec_sha256",
                "permit_sha256",
            )
        ):
            raise ValueError("enabled launcher requires all file/hash pins")
    result = launch(args)
    if not args.enable_native:
        print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
