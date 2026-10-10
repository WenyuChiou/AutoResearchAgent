"""Register an explicit own-account, repository-content Codex pilot on loopback.

No model starts during preparation, server creation, a GET, or page refresh.
The user must confirm each offered task in the UI. This controlled corpus is
synthetic; its native execution does not establish canonical Stage1 completion,
daily_v3 evaluation, scientific improvement, or Stage3 execution authority.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import stat
import sys
from types import ModuleType, SimpleNamespace


REPO = Path(__file__).resolve().parents[5]
SCOPE = (
    "I allow real Codex model calls on this bound repository case only, at most "
    "8 turns and 900 seconds; no external search, trading, frozen inputs, "
    "command/file approval, private import or resume."
)
HASH = re.compile(r"[0-9a-f]{64}")


def _check(condition, message):
    if not condition:
        raise ValueError(message)


def _unlinked(value):
    path = Path(value)
    _check(path.is_absolute(), "absolute paths required")
    for item in (path, *path.parents):
        if item.exists():
            info = item.lstat()
            _check(
                not stat.S_ISLNK(info.st_mode)
                and not getattr(info, "st_file_attributes", 0) & 0x400,
                "linked path refused",
            )
    return path.resolve()


def _raw(path, maximum=1024 * 1024):
    path = _unlinked(path)
    _check(path.is_file(), "regular input file required")
    _check(path.stat().st_nlink == 1, "hardlinked input refused")
    with path.open("rb") as stream:
        raw = stream.read(maximum + 1)
    _check(0 < len(raw) <= maximum, "input size bound exceeded")
    return raw


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _canonical(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf8")


def _json(raw):
    def unique(pairs):
        value = {}
        for key, item in pairs:
            _check(key not in value, "duplicate JSON key")
            value[key] = item
        return value

    return json.loads(raw.decode("utf8"), object_pairs_hook=unique)


def case_inputs(args):
    """Validate the external case pin and every admitted corpus byte; no writes."""
    _check(args.accept_scope == SCOPE, "explicit repository-content scope required")
    _check(
        type(args.max_calls) is int and 1 <= args.max_calls <= 8,
        "max calls must be 1..8",
    )
    _check(
        type(args.max_seconds) is int and 1 <= args.max_seconds <= 900,
        "max seconds must be 1..900",
    )
    _check(
        isinstance(args.permission_id, str)
        and re.fullmatch(r"[A-Za-z0-9._:/-]{1,200}", args.permission_id),
        "explicit permission reference required",
    )
    _check(
        isinstance(args.model, str)
        and re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", args.model),
        "own-account model required",
    )
    _check(
        isinstance(args.case_sha256, str) and HASH.fullmatch(args.case_sha256),
        "external case SHA256 required",
    )
    _check(type(args.port) is int and 0 <= args.port <= 65535, "loopback port invalid")
    case_path = _unlinked(args.case)
    raw = _raw(case_path)
    _check(_sha(raw) == args.case_sha256, "case bytes differ")
    case = _json(raw)
    _check(
        isinstance(case, dict)
        and case.get("kind") == "RepositoryNativeStageRunCase"
        and case.get("schema_version") == "1.0.0"
        and case.get("canonical_stage1_to_stage2_lineage") is False
        and case.get("execution_authorized") is False
        and case.get("native_calls")
        == case.get("model_calls")
        == case.get("search_calls")
        == 0,
        "controlled, unexecuted repository case required",
    )
    provenance = case.get("content_provenance", {})
    _check(
        provenance.get("corpus") == "synthetic-repository-fixture"
        and provenance.get("fixture_helper") == "tests/stage2_fixture_helpers.py",
        "existing nonfrozen controlled corpus required",
    )
    repo = _unlinked(args.repo)
    plugin = repo / "plugins/auto-research-agent"
    _check(
        _sha(_raw(plugin / provenance["fixture_helper"]))
        == provenance.get("fixture_helper_sha256"),
        "repository fixture helper differs",
    )
    parent = case_path.parent
    paths = {}
    for name in (
        "packet_path",
        "source_root",
        "brief_path",
        "stage_inputs_path",
        "host_config_path",
        "stage1_ledger_root",
    ):
        path = _unlinked(case[name])
        _check(path.is_relative_to(parent), "case input outside the bound case root")
        paths[name] = path
    for name, pin in (
        ("packet_path", "packet_sha256"),
        ("brief_path", "brief_sha256"),
        ("stage_inputs_path", "stage_inputs_sha256"),
        ("host_config_path", "host_config_sha256"),
    ):
        _check(_sha(_raw(paths[name])) == case[pin], "bound " + name + " differs")
    sources = paths["source_root"]
    _check(
        sources.is_dir() and paths["stage1_ledger_root"].is_dir(),
        "case corpus and ledger required",
    )
    actual = {}
    for path in sources.rglob("*"):
        _unlinked(path)
        if path.is_file():
            actual[path.relative_to(sources).as_posix()] = _sha(_raw(path))
    _check(
        actual == case["source_bindings"] and len(actual) == 2,
        "exact two-source corpus required",
    )
    _check(
        _sha(_canonical(actual)) == case["source_binding_sha256"],
        "case source digest differs",
    )
    packet = _json(_raw(paths["packet_path"]))
    _check(
        packet.get("kind") == "Stage2Packet" and packet.get("candidates") == [],
        "empty, saved Stage2 seed required",
    )
    _check(
        {row["path"]: row["sha256"] for row in packet["sources"]} == actual,
        "packet and corpus source bindings differ",
    )
    _check(
        _json(_raw(paths["brief_path"])) == packet["brief"],
        "case and packet briefs differ",
    )
    config = _json(_raw(paths["host_config_path"]))
    _check(
        set(config) == {"views"} and len(config["views"]) == 2,
        "exact two saved case views required",
    )
    _check(
        {row["ref"] for row in config["views"]} == {"stage1", "stage2"},
        "saved stage references differ",
    )
    _check(
        {row["ref"]: row for row in config["views"]} == case["view_manifests"],
        "host and case view bindings differ",
    )
    for row in config["views"]:
        manifest = _unlinked(row["manifest"])
        _check(manifest.is_relative_to(parent), "view outside the bound case root")
        _check(_sha(_raw(manifest)) == row["sha256"], "saved view manifest differs")
    output = _unlinked(args.output)
    _check(
        not output.exists() and output.parent.is_dir(),
        "new private output and existing parent required",
    )
    _check(
        not output.is_relative_to(parent) and not parent.is_relative_to(output),
        "case/output overlap refused",
    )
    return case, paths, repo, output


def _inspect(args, case, paths, repo, output):
    """Use the existing raw-pinned source loader before importing owned modules."""
    plugin = repo / "plugins/auto-research-agent"
    prepare_path = plugin / "cli/research_workspace_native/atlas_local_prepare.py"
    raw = _raw(prepare_path)
    name = "_stage_pilot_preparation"
    _check(name not in sys.modules, "fresh preparation process required")
    prepare = ModuleType(name)
    prepare.__file__ = str(prepare_path)
    sys.modules[name] = prepare
    exec(compile(raw, str(prepare_path), "exec"), prepare.__dict__)
    helper = plugin / "cli/research_workspace_native/atlas_local_source.py"
    home = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")
    user_path = _unlinked(args.user_config or home / "config.toml")
    executable = _unlinked(args.codex_executable)
    checked = prepare.inspect_inputs(
        SimpleNamespace(
            repo=repo,
            source_helper_sha256=_sha(_raw(helper)),
            config=paths["host_config_path"],
            config_sha256=case["host_config_sha256"],
            project_ref="stage1",
            model=args.model,
            brief="brief.json",
            stage_inputs=paths["stage_inputs_path"],
            stage_inputs_sha256=case["stage_inputs_sha256"],
            user_config=user_path,
            user_config_sha256=_sha(_raw(user_path)),
            executable=executable,
            executable_sha256=_sha(_raw(executable, 512 * 1024 * 1024)),
            output=output,
        )
    )
    _check(
        checked["manifest"]["plugin_files"][
            "cli/research_workspace_native/atlas_local_prepare.py"
        ]
        == _sha(raw),
        "preparation helper changed during inventory",
    )
    _check(
        checked["project_id"] == case["project_id"]
        and checked["index_sha256"] == case["index_sha256"]
        and checked["input_version"] == case["brief_sha256"],
        "prepared project/index/brief differs",
    )
    return checked


def prepare(args):
    case, paths, repo, output = case_inputs(args)
    checked = _inspect(args, case, paths, repo, output)
    from stage1_deliverable.common import canonical, private_output
    from stage2_common import canonical_hash
    from research_workspace_native.atlas_host import load_views
    from research_workspace_native.http import token_authenticator
    from research_workspace_native.stage_model import StageModel
    from research_workspace_native.stage_pipeline import StagePipeline
    from research_workspace_native.stage_run_service import StageRunService

    private_output(output).mkdir(exist_ok=False)
    permit = dict(
        kind="NativeStagePilotPermit",
        schema_version="1.0.0",
        project_id=case["project_id"],
        source_sha256=case["source_binding_sha256"],
        case_sha256=args.case_sha256,
        output_root=output.as_posix(),
        model=args.model,
        max_calls=args.max_calls,
        max_seconds=args.max_seconds,
        execution_scope="repository-saved-content-only",
        external_search=False,
        frozen_subjects=False,
        permission_id=args.permission_id,
    )
    permit_path = output / "permit.json"
    with permit_path.open("xb") as stream:
        stream.write(canonical(permit))
    permit_sha = _sha(permit_path.read_bytes())
    credential = secrets.token_urlsafe(32)
    authenticate = token_authenticator({credential: "local-viewer"})
    holder = {}

    def verify(receipt, **bindings):
        _check("model" in holder, "native verifier not bound")
        return holder["model"].verify_receipt(receipt, **bindings)

    pipeline = StagePipeline(
        paths["packet_path"],
        paths["source_root"],
        output / "pipeline",
        expected_packet_sha256=canonical_hash(_json(_raw(paths["packet_path"]))),
        source_sha256=permit["source_sha256"],
        verify_receipt=verify,
        max_calls=args.max_calls,
    )
    service = StageRunService(
        permit_path, permit_sha, pipeline=pipeline, authenticate=authenticate
    )
    try:
        model = StageModel(
            checked,
            model=args.model,
            permit_sha256=permit_sha,
            source_sha256=permit["source_sha256"],
            executable_sha256=_sha(_raw(checked["executable"], 512 * 1024 * 1024)),
            user_config_sha256=_sha(_raw(checked["user_path"])),
            config_sha256=case["host_config_sha256"],
            authenticate=authenticate,
            credential=credential,
            admit=service.admit,
            output_root=output / "models",
        )
        holder["model"] = model
        service.attach_model(model)
        files, views = load_views(paths["host_config_path"], case["host_config_sha256"])
        _check(
            all(
                row["project_id"] == case["project_id"]
                and row["index_sha256"] == case["index_sha256"]
                for row in views
            ),
            "host view belongs to another case",
        )
        return checked, service, files, views, credential, output
    except BaseException:
        service.close()
        raise


def parser():
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--repo", type=Path, default=REPO)
    value.add_argument("--case", type=Path, required=True)
    value.add_argument("--case-sha256", required=True)
    value.add_argument("--model", required=True)
    value.add_argument("--max-calls", type=int, required=True)
    value.add_argument("--max-seconds", type=int, required=True)
    value.add_argument("--permission-id", required=True)
    value.add_argument("--accept-scope", required=True, help=SCOPE)
    value.add_argument("--codex-executable", type=Path, required=True)
    value.add_argument("--user-config", type=Path)
    value.add_argument("--output", type=Path, required=True)
    value.add_argument("--port", type=int, default=8770)
    value.add_argument("--prepare-only", action="store_true")
    return value


def main(argv=None):
    args = parser().parse_args(argv)
    checked, service, files, views, credential, output = prepare(args)
    server = None
    receipt = dict(
        kind="NativeStagePilotRegistration",
        schema_version="1.0.0",
        case_sha256=args.case_sha256,
        permission_id=args.permission_id,
        authority_evidence="Explicit operator CLI scope attestation; no account inference before a UI POST",
        max_calls=args.max_calls,
        max_seconds=args.max_seconds,
        model=args.model,
        own_account="not-observed-before-explicit-native-start",
        native_calls=0,
        execution="waiting-for-explicit-UI-task-confirmation",
        source_sha256=service.permit["source_sha256"],
        index_sha256=checked["index_sha256"],
        permit_sha256=service.permit_sha,
        corpus="synthetic-repository-fixture",
        canonical_stage1_handoff=False,
        daily_v3="not-started",
        stage3_execution_authorized=False,
    )
    try:
        if args.prepare_only:
            receipt["execution"] = "prepared-only; no HTTP server or model started"
        else:
            from research_workspace_native.stage_run_http import StageRunHost

            server = StageRunHost(
                files,
                views,
                service=service,
                credential=credential,
                host="127.0.0.1",
                port=args.port,
            )
            receipt["url"] = "http://127.0.0.1:" + str(server.server_address[1]) + "/"
        with (output / "launch-receipt.json").open(
            "x", encoding="utf8", newline="\n"
        ) as stream:
            json.dump(receipt, stream, ensure_ascii=False, sort_keys=True)
            stream.write("\n")
        print(json.dumps(receipt, ensure_ascii=False), flush=True)
        if server is not None:
            server.serve_forever(poll_interval=0.2)
        return 0
    except KeyboardInterrupt:
        return 0
    finally:
        if server is not None:
            server.server_close()
        else:
            service.close()


if __name__ == "__main__":
    raise SystemExit(main())
