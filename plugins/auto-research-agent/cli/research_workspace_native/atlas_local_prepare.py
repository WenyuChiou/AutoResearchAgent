"""Check local saved Atlas inputs; explicitly prepare, never launch, a text session."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import time
import tomllib
from types import ModuleType

ACCEPT_TEXT_SCOPE = (
    "I allow a fresh local read-only Codex session with at most two text turns "
    "and a 600-second lease; no research, search, trading, or command/file approval."
)
if __name__ == "__main__":
    sys.path[:] = [
        p
        for p in sys.path
        if Path(p or os.getcwd()).resolve() != Path(__file__).parent.resolve()
    ]


def _raw(path, expected):
    path = Path(path)
    if not path.is_absolute() or not re.fullmatch(r"[0-9a-f]{64}", expected or ""):
        raise ValueError("absolute bootstrap path and SHA256 required")
    for item in (path, *path.parents):
        if item.exists():
            info = item.lstat()
            if (
                stat.S_ISLNK(info.st_mode)
                or getattr(info, "st_file_attributes", 0) & 0x400
            ):
                raise ValueError("linked bootstrap path refused")
    if not stat.S_ISREG(path.stat().st_mode):
        raise ValueError("regular bootstrap file required")
    with path.open("rb") as stream:
        raw = stream.read(32 * 1024 * 1024 + 1)
    if (
        not 0 < len(raw) <= 32 * 1024 * 1024
        or hashlib.sha256(raw).hexdigest() != expected
    ):
        raise ValueError("source helper binding differs")
    return raw


def inspect_inputs(args):
    repo = Path(args.repo)
    helper = (
        repo
        / "plugins/auto-research-agent/cli/research_workspace_native/atlas_local_source.py"
    )
    raw = _raw(helper, args.source_helper_sha256)  # Check ancestors before resolve.
    alias = "_atlas_prepare_source"
    if alias in sys.modules:
        raise ValueError("preloaded preparation helper; fresh process required")
    source = ModuleType(alias)
    source.__file__ = str(helper)
    sys.modules[alias] = source
    exec(compile(raw, str(helper), "exec"), source.__dict__)
    repo = source.unlinked(repo).resolve()
    plugin = repo / "plugins/auto-research-agent"
    files = source.inventory(plugin)
    source.require(
        files["cli/research_workspace_native/atlas_local_source.py"]
        == args.source_helper_sha256,
        "helper changed during inventory",
    )
    loader = source.PinnedLoader(repo, files)
    sys.dont_write_bytecode = True
    sys.meta_path.insert(0, loader)
    from stage1_deliverable.common import private_output, safe_path
    from research_workspace_native.host_config import load_config
    from research_workspace_native.runtime_spec import (
        DENIED_THREAD_CONFIG,
        _thread_config,
    )
    from research_workspace_native.stage_inputs import snapshot_inputs, source_digest
    from research_workspace_native.scope_api import MAX_BRIEF, _brief

    require = source.require
    require(
        re.fullmatch(r"[A-Za-z0-9_-]{1,64}", args.project_ref or "") is not None,
        "bounded project reference required",
    )
    require(
        re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", args.model or "") is not None,
        "explicit bounded model required",
    )
    config_path = source.unlinked(args.config).resolve()
    config_raw = source.pinned(config_path, args.config_sha256)
    config_value = source.decode(config_raw)
    require(
        set(config_value) == {"views"}, "prepared view-only host configuration required"
    )
    config = load_config(config_path, args.config_sha256)
    selected = [row for row in config["views"] if row["ref"] == args.project_ref]
    require(len(selected) == 1, "exact project view required")
    row = selected[0]
    entry = next(v for v in config_value["views"] if v["ref"] == args.project_ref)
    manifest_path = source.unlinked(entry["manifest"]).resolve()
    source_root = source.unlinked(manifest_path.parent).resolve()
    private_output(source_root)
    brief = safe_path(source_root, args.brief)
    input_raw = source.read(brief, MAX_BRIEF)
    _brief(input_raw, source.digest(input_raw))
    index_path = source_root / "workspace-index.json"
    index_raw = source.pinned(index_path, row["index_sha256"], 32 * 1024 * 1024)
    require(
        source.decode(index_raw)["project_id"] == row["project_id"],
        "project/index differs",
    )
    stage_path = source.unlinked(args.stage_inputs).resolve()
    stage_inputs = source.decode(source.pinned(stage_path, args.stage_inputs_sha256))
    snapshot = snapshot_inputs(stage_inputs)
    user_path = source.unlinked(args.user_config).resolve()
    if not user_path.is_file() or user_path.stat().st_size == 0:
        raise ValueError(
            "inherited user config is missing or empty; create a nonempty config.toml explicitly"
        )
    home = source.unlinked(os.environ.get("CODEX_HOME") or Path.home() / ".codex")
    require(
        user_path == source.unlinked(home / "config.toml").resolve(),
        "pin inherited CODEX_HOME/config.toml",
    )
    for ancestor in (source_root, *source_root.parents):
        layer = ancestor / ".codex/config.toml"
        require(
            not layer.exists() or source.unlinked(layer).resolve() == user_path,
            "additional project configuration layer unsupported",
        )
    names = tomllib.loads(
        source.pinned(user_path, args.user_config_sha256).decode("utf8")
    ).get("mcp_servers", {})
    require(
        isinstance(names, dict) and len(names) <= 64, "bounded user MCP names required"
    )
    thread_config = _thread_config(
        {**DENIED_THREAD_CONFIG, **{f"mcp_servers.{n}.enabled": False for n in names}}
    )
    executable = source.unlinked(args.executable).resolve()
    require(
        executable.name.casefold() in {"codex", "codex.exe"},
        "pinned installed Codex executable required",
    )
    source.pinned(executable, args.executable_sha256, 512 * 1024 * 1024)
    output = source.unlinked(args.output).resolve()
    require(
        not output.exists() and output.parent.is_dir(),
        "fresh output and existing parent required",
    )
    private_output(output)
    roots = [repo] + [
        source.unlinked(Path(v["manifest"]).parent).resolve()
        for v in config_value["views"]
    ]
    for stage in stage_inputs.values():
        for name, value in (stage or {}).items():
            if name.endswith("_root") and value is not None:
                roots.append(source.unlinked(value).resolve())
    require(
        all(
            not output.is_relative_to(r) and not r.is_relative_to(output) for r in roots
        ),
        "input/output overlap refused",
    )
    manifest = dict(
        kind="LocalAtlasByteInventory",
        repo_root=repo.as_posix(),
        source_root=source_root.as_posix(),
        plugin_files=files,
        source_files=source.inventory(source_root),
    )
    pins = [
        (config_path, args.config_sha256),
        (manifest_path, entry["sha256"]),
        (index_path, row["index_sha256"]),
        (brief, source.digest(input_raw)),
        (stage_path, args.stage_inputs_sha256),
        (user_path, args.user_config_sha256),
        (executable, args.executable_sha256),
    ]
    # Refuse bytes changing during the preparation read, before creating files.
    for path, expected in pins:
        source.pinned(
            path,
            expected,
            512 * 1024 * 1024 if path == executable else 32 * 1024 * 1024,
        )
    require(
        source.inventory(plugin) == files
        and source.inventory(source_root) == manifest["source_files"],
        "inventory changed during preparation",
    )
    require(
        source_digest(snapshot_inputs(stage_inputs)) == source_digest(snapshot),
        "saved stage inputs changed during preparation",
    )
    return dict(
        source=source,
        repo=repo,
        output=output,
        manifest=manifest,
        source_root=source_root,
        project_id=row["project_id"],
        index_path=index_path,
        index_sha256=row["index_sha256"],
        input_path=brief,
        input_version=source.digest(input_raw),
        thread_config=thread_config,
        stage_inputs=stage_inputs,
        stage_source_sha256=source_digest(snapshot),
        config_path=config_path,
        user_path=user_path,
        executable=executable,
    )


def bundle_documents(args, checked, now):
    source, output = checked["source"], checked["output"]
    manifest_path, permit_path, spec_path = (
        output / n for n in ("byte-inventory.json", "permit.json", "runtime-spec.json")
    )
    raw_manifest = source.canonical(checked["manifest"]) + b"\n"
    identity = dict(
        kind="NativeAtlasRuntimeSpec",
        schema_version="1.0.0",
        project_ref=args.project_ref,
        project_id=checked["project_id"],
        principals=["local-viewer"],
        source_root=checked["source_root"].as_posix(),
        index_path=checked["index_path"].as_posix(),
        index_sha256=checked["index_sha256"],
        input_path=checked["input_path"].as_posix(),
        input_version=checked["input_version"],
        store_path=(output / "attempt/native/session.sqlite3").as_posix(),
        executable=checked["executable"].as_posix(),
        executable_sha256=args.executable_sha256,
        model=args.model,
        approval_policy="on-request",
        limits=dict(
            lifetime_seconds=600,
            max_stream_bytes=1048576,
            max_text_bytes=4096,
            max_starts=2,
            timeout_seconds=30,
        ),
        thread_config=checked["thread_config"],
        handshake_timeout_seconds=120,
    )
    permit = dict(
        kind="LocalCodexAtlasPermit",
        schema_version="1.0.0",
        spec_identity_sha256=source.digest(source.canonical(identity)),
        host_config=dict(
            path=checked["config_path"].as_posix(), sha256=args.config_sha256
        ),
        user_config=dict(
            path=checked["user_path"].as_posix(), sha256=args.user_config_sha256
        ),
        source_manifest=dict(
            path=manifest_path.as_posix(), sha256=source.digest(raw_manifest)
        ),
        attempt_root=(output / "attempt").as_posix(),
        brief_path=args.brief,
        stage_inputs=checked["stage_inputs"],
        stage_source_sha256=checked["stage_source_sha256"],
        max_turns=2,
        lease_seconds=600,
        sandbox="read-only",
        network_access=False,
        allow_fresh_session=True,
        allow_user_messages=True,
        expires_at_unix=now + 600,
    )
    permit_raw = source.canonical(permit) + b"\n"
    permit_sha = source.digest(permit_raw)
    spec_raw = source.canonical(dict(identity, permit_sha256=permit_sha)) + b"\n"
    source.require(
        len(raw_manifest) <= 1024 * 1024
        and len(permit_raw) <= 256 * 1024
        and len(spec_raw) <= 256 * 1024,
        "prepared document exceeds launcher bounds",
    )
    launcher = (
        checked["repo"]
        / "plugins/auto-research-agent/cli/research_workspace_native/atlas_local_launcher.py"
    )
    argv = [
        sys.executable,
        "-B",
        "-X",
        "utf8",
        str(launcher),
        "--enable-native",
        "--repo",
        str(checked["repo"]),
        "--config",
        str(checked["config_path"]),
        "--config-sha256",
        args.config_sha256,
        "--spec",
        str(spec_path),
        "--spec-sha256",
        source.digest(spec_raw),
        "--permit",
        str(permit_path),
        "--permit-sha256",
        permit_sha,
        "--open",
    ]
    return {
        "byte-inventory.json": raw_manifest,
        "permit.json": permit_raw,
        "runtime-spec.json": spec_raw,
        "launcher-argv.json": source.canonical(argv) + b"\n",
    }


def prepare(args):
    if args.allow_text_session:
        if args.accept_text_scope != ACCEPT_TEXT_SCOPE:
            raise ValueError("exact limited text-session acceptance required")
    elif args.accept_text_scope is not None:
        raise ValueError("acceptance requires explicit allow-text-session flag")
    checked = inspect_inputs(args)
    result = dict(
        kind="AtlasLocalPreparation",
        status="checked-only",
        project_ref=args.project_ref,
        index_sha256=checked["index_sha256"],
        input_version=checked["input_version"],
        native_process_started=False,
        model_calls=0,
        research_authority=False,
        files_written=0,
        argv=None,
    )
    if not args.allow_text_session:
        return result
    documents = bundle_documents(args, checked, int(time.time()))
    checked["output"].mkdir()
    for name, raw in documents.items():
        with (checked["output"] / name).open("xb") as stream:
            stream.write(raw)
    return dict(
        result,
        status="prepared-not-started",
        files_written=len(documents),
        output=str(checked["output"]),
        argv=json.loads(documents["launcher-argv.json"]),
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in "repo config stage-inputs executable user-config output".split():
        parser.add_argument("--" + name, type=Path, required=True)
    for name in "source-helper config stage-inputs executable user-config".split():
        parser.add_argument("--" + name + "-sha256", required=True)
    for name in ("project-ref", "brief", "model"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--allow-text-session", action="store_true")
    parser.add_argument("--accept-text-scope")
    args = parser.parse_args(argv)
    try:
        result = prepare(args)
    except Exception as error:
        known = "inherited user config is missing or empty; create a nonempty config.toml explicitly"
        print(
            json.dumps(
                dict(
                    kind="AtlasLocalPreparation",
                    status="refused",
                    error_type=type(error).__name__,
                    reason=known
                    if str(error) == known
                    else "Pinned saved-input validation failed; check local paths, hashes and acceptance.",
                    files_written=None,
                    native_process_started=False,
                    model_calls=0,
                    research_authority=False,
                    argv=None,
                )
            ),
            flush=True,
        )
        raise SystemExit(2) from None
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
