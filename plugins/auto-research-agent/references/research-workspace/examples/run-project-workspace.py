"""Own-account project portal with explicit UI or pinned saved-run consent.

Bootstrap uses the externally pinned raw source helper before any owned import.
No startup, GET, topic entry or budget declaration probes/starts Codex. Only an
explicit --stage1-run-request can start a bounded run after original plan and
consent checks; registration alone grants nothing. Saved views remain optional
snapshots, independent from the new versioned projects.
"""

import argparse
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import stat
import sys
import time
from types import ModuleType
import webbrowser

REPO = Path(__file__).resolve().parents[5]
HELPER = "cli/research_workspace_native/atlas_local_source.py"
SCRIPT = "references/research-workspace/examples/run-project-workspace.py"
HASH = re.compile(r"[0-9a-f]{64}")
QUERY_BACKENDS = {"openalex", "crossref", "semantic-scholar", "arxiv", "pubmed"}
QUERY_CAPS = {
    "max_attempts": 128,
    "max_reserved_seconds": 86400,
    "max_results": 100,
    "validity_seconds": 86400,
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def unlinked(path):
    path = Path(path)
    require(path.is_absolute(), "absolute path required")
    for item in (path, *path.parents):
        try:
            info = item.lstat()
        except FileNotFoundError:
            continue
        require(
            not stat.S_ISLNK(info.st_mode)
            and not getattr(info, "st_file_attributes", 0) & 0x400,
            "links/reparse points refused",
        )
    return path.resolve()


def raw_file(path, maximum=256 * 1024):
    path = unlinked(path)
    require(stat.S_ISREG(path.stat().st_mode), "regular file required")
    with path.open("rb") as stream:
        raw = stream.read(maximum + 1)
    require(0 < len(raw) <= maximum, "file bound exceeded")
    return raw


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def query_runtime_config(path, expected):
    """Read an external byte pin without importing or probing its runtime."""
    require(
        isinstance(expected, str) and HASH.fullmatch(expected),
        "external Stage1 query runtime SHA256 required",
    )
    # A complete interpreter/dependency byte inventory exceeds 64 KiB on a
    # normal installation. Keep the external hash and strict schema binding,
    # with a finite bound large enough for the SDK's actual inventory.
    raw = raw_file(path, 4 * 1024 * 1024)
    require(digest(raw) == expected, "Stage1 query runtime bytes differ")

    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, "duplicate Stage1 query runtime field")
            result[key] = value
        return result

    def constant(_):
        raise ValueError("nonfinite Stage1 query runtime value")

    try:
        value = json.loads(
            raw.decode("utf8"), object_pairs_hook=pairs, parse_constant=constant
        )
    except (UnicodeError, RecursionError, json.JSONDecodeError) as error:
        raise ValueError("invalid Stage1 query runtime JSON") from error
    require(
        isinstance(value, dict)
        and set(value) == {"kind", "schema_version", "pin", "caps", "backends"}
        and value["kind"] == "ProjectStage1QueryRuntime"
        and value["schema_version"] == "1.0.0",
        "unsupported Stage1 query runtime schema",
    )
    require(
        isinstance(value["pin"], dict) and value["pin"],
        "saved Stage1 query runtime pin required",
    )
    caps = value["caps"]
    require(
        isinstance(caps, dict)
        and set(caps) == set(QUERY_CAPS)
        and all(
            type(caps[key]) is int and 1 <= caps[key] <= maximum
            for key, maximum in QUERY_CAPS.items()
        ),
        "bounded Stage1 query runtime caps required",
    )
    backends = value["backends"]
    require(
        isinstance(backends, list)
        and 1 <= len(backends) <= len(QUERY_BACKENDS)
        and all(
            type(backend) is str and backend in QUERY_BACKENDS for backend in backends
        )
        and len(set(backends)) == len(backends),
        "Stage1 query runtime backends invalid",
    )
    return value


def windows_root_preflight(root, *, platform=None, model=False, existing_stage23=False):
    """Reserve physical SQLite/native archive space, without changing core names."""
    if existing_stage23:
        require(not model, "existing Stage2/3 store cannot enable native content")
        database = unlinked(root / "project-intake.sqlite")
        require(database.is_file(), "existing Stage2/3 intake database required")
        with database.open("rb") as stream:
            require(
                stream.read(16) == b"SQLite format 3\x00",
                "existing Stage2/3 intake database header differs",
            )
        if (sys.platform if platform is None else platform) == "win32":
            require(
                len(
                    str(database.with_name(database.name + "-journal")).encode(
                        "utf-16-le"
                    )
                )
                // 2
                < 240,
                "existing intake SQLite layout is too long",
            )
        return
    if (sys.platform if platform is None else platform) == "win32":
        # Core Stage1 archives impose their own <=170 character producer path.
        # Native owner/sidecars can add another 170 characters to this prefix.
        require(
            len(str(root).encode("utf-16-le")) // 2 <= 60,
            "Windows projects root is too long; choose a short private path such "
            "as D:/rp/projects (do not put it inside the download)",
        )
        if model:
            longest = (
                root
                / "m"
                / ("0" * 24)
                / "n"
                / ("0" * 64)
                / ("native.sqlite3.owner-" + "0" * 64 + ".sqlite3-journal")
            )
            require(
                len(str(longest).encode("utf-16-le")) // 2 < 240,
                "Windows content model runtime SQLite layout is too long; "
                "choose a shorter private projects root (native owner/sidecar "
                "path must stay under 240 UTF-16 characters)",
            )


def resolve_codex(value):
    selected = Path(value)
    if not selected.is_absolute():
        require(selected.name == value, "Codex must be an absolute path or command")
        found = shutil.which(value)
        require(found is not None, "installed Codex command not found")
        selected = Path(found)
    selected = unlinked(selected)
    require(
        selected.name.casefold() in {"codex", "codex.exe"},
        "use the actual installed codex/codex.exe; shell wrappers are refused",
    )
    raw_file(selected, 512 * 1024 * 1024)
    return selected


def parser():
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--repo", type=Path, default=REPO)
    value.add_argument("--source-helper-sha256", required=True)
    value.add_argument("--projects-root", type=Path, required=True)
    value.add_argument(
        "--existing-stage23-store",
        action="store_true",
        help="Serve an existing Stage2/3 store without native Stage1 registration",
    )
    value.add_argument("--views-config", type=Path)
    value.add_argument("--views-sha256")
    value.add_argument("--stage1-query-runtime", type=Path)
    value.add_argument("--stage1-query-runtime-sha256")
    value.add_argument("--stage1-materials-root", type=Path)
    value.add_argument(
        "--source-cap-seconds",
        type=int,
        default=60,
        help="Source-job ceiling including parsing/registration, within Harness 1..300 seconds",
    )
    value.add_argument(
        "--enable-public-sources",
        action="store_true",
        help="Register the contained Windows source worker; each source still needs UI authorization",
    )
    value.add_argument("--port", type=int, default=0)
    value.add_argument("--open", action="store_true")
    value.add_argument("--enable-content-model", action="store_true")
    value.add_argument("--model")
    value.add_argument(
        "--model-cap-seconds",
        type=int,
        default=120,
        help="Server per-call upper bound; shared project reservations are never refunded",
    )
    value.add_argument("--codex")
    value.add_argument("--codex-home", type=Path)
    value.add_argument(
        "--enable-stage1-run",
        action="store_true",
        help="Register one shared typed run issuer; grants still require explicit consent",
    )
    value.add_argument("--stage1-run-request", type=Path)
    value.add_argument("--stage1-run-request-sha256")
    value.add_argument(
        "--enable-stage1-full-source",
        action="store_true",
        help="Use full-source analysis for the explicit saved Stage1 run",
    )
    value.add_argument("--stage1-full-notes-root", type=Path)
    value.add_argument("--check-only", action="store_true")
    value.add_argument("--prepare-only", action="store_true")
    return value


def inspect_inputs(args):
    """Filesystem-only checks; do not create an output or import owned modules."""
    existing_stage23 = getattr(args, "existing_stage23_store", False)
    if existing_stage23:
        require(
            not any(
                getattr(args, name, None)
                for name in (
                    "enable_content_model",
                    "enable_public_sources",
                    "enable_stage1_run",
                    "stage1_query_runtime",
                    "stage1_materials_root",
                    "native_stage1_config",
                )
            ),
            "existing Stage2/3 store cannot register native Stage1 services",
        )
    require(
        type(args.source_cap_seconds) is int and 1 <= args.source_cap_seconds <= 300,
        "source cap must remain within Harness 1..300 seconds",
    )
    require(
        HASH.fullmatch(args.source_helper_sha256), "external helper SHA256 required"
    )
    require(0 <= args.port <= 65535, "loopback port invalid")
    require(
        0 < args.model_cap_seconds <= 600, "model per-call cap must be 1..600 seconds"
    )
    require(
        bool(args.views_config) == bool(args.views_sha256),
        "saved views require their external configuration SHA256",
    )
    run_request = getattr(args, "stage1_run_request", None)
    run_pin = getattr(args, "stage1_run_request_sha256", None)
    full_source = getattr(args, "enable_stage1_full_source", False)
    notes_root = getattr(args, "stage1_full_notes_root", None)
    require(
        type(full_source) is bool and full_source == (notes_root is not None),
        "full-source analysis and notes root must be selected together",
    )
    if full_source:
        require(
            args.enable_stage1_run and run_request is not None,
            "full-source analysis requires an enabled pinned Stage1 run request",
        )
        notes_root = unlinked(notes_root)
        require(notes_root.is_dir(), "existing full-source notes directory required")
        projects_root = unlinked(args.projects_root)
        require(
            not notes_root.is_relative_to(projects_root)
            and not projects_root.is_relative_to(notes_root),
            "full-source notes must be separate from the project store",
        )
    require(
        (run_request is None) == (run_pin is None),
        "Stage1 run request requires its external SHA256",
    )
    require(
        not run_request or args.enable_stage1_run,
        "Stage1 run request requires --enable-stage1-run",
    )
    require(
        not args.enable_stage1_run
        or (args.enable_content_model and args.enable_public_sources),
        "whole Stage1 run requires model and public source registration",
    )
    require(
        not run_request or not args.prepare_only,
        "prepare-only never executes a Stage1 run",
    )
    if run_request is not None:
        require(
            type(run_pin) is str and HASH.fullmatch(run_pin),
            "Stage1 run request SHA256 invalid",
        )
        require(
            digest(raw_file(run_request, 16384)) == run_pin,
            "Stage1 run request bytes differ",
        )
    runtime_path = getattr(args, "stage1_query_runtime", None)
    runtime_sha = getattr(args, "stage1_query_runtime_sha256", None)
    require(
        (runtime_path is None) == (runtime_sha is None),
        "Stage1 query runtime path and SHA256 required together",
    )
    query_runtime = None
    if runtime_path is not None:
        runtime_path = unlinked(runtime_path)
        query_runtime = dict(
            path=runtime_path,
            sha256=runtime_sha,
            value=query_runtime_config(runtime_path, runtime_sha),
        )
    repo, root = unlinked(args.repo), unlinked(args.projects_root)
    plugin = repo / "plugins/auto-research-agent"
    require((plugin / "cli").is_dir(), "complete plugin checkout required")
    require(
        not root.is_relative_to(repo) and not repo.is_relative_to(root),
        "project store and repository must not overlap",
    )
    require(root.is_dir() or not root.exists(), "project root must be a directory")
    require(root.parent.is_dir(), "project root parent must already exist")
    require(
        not any((parent / ".git").exists() for parent in (root, *root.parents)),
        "project root must stay outside every Git checkout",
    )
    materials = getattr(args, "stage1_materials_root", None)
    require(
        not args.enable_public_sources
        or runtime_path is not None
        and materials is not None,
        "public source controls require the query runtime and private materials root",
    )
    if materials is not None:
        require(
            query_runtime is not None, "saved Stage1 materials require query runtime"
        )
        materials = unlinked(materials)
        require(materials.is_dir(), "saved Stage1 materials root must already exist")
        require(
            not materials.is_relative_to(repo) and not repo.is_relative_to(materials),
            "saved Stage1 materials and repository must not overlap",
        )
        require(
            not materials.is_relative_to(root) and not root.is_relative_to(materials),
            "saved Stage1 materials and project storage must not overlap",
        )
        require(
            not any(
                (parent / ".git").exists() for parent in (materials, *materials.parents)
            ),
            "saved Stage1 materials must stay outside every Git checkout",
        )
    windows_root_preflight(
        root, model=args.enable_content_model, existing_stage23=existing_stage23
    )
    helper = plugin / HELPER
    helper_raw = raw_file(helper)
    require(digest(helper_raw) == args.source_helper_sha256, "helper bytes differ")
    script_raw = raw_file(plugin / SCRIPT)
    require(
        digest(script_raw) == digest(raw_file(Path(__file__).absolute())),
        "launcher must match the selected repository bytes",
    )
    model_options = (args.model, args.codex, args.codex_home)
    if args.enable_content_model:
        require(all(model_options), "model, Codex executable and own home are explicit")
        require(
            re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", args.model),
            "own-account model selection invalid",
        )
        home = unlinked(args.codex_home)
        require(home.is_dir(), "own Codex home required")
        config = home / "config.toml"
        raw_file(config)
        executable = resolve_codex(args.codex)
    else:
        require(not any(model_options), "model options require --enable-content-model")
        home = config = executable = None
    if args.views_config:
        require(HASH.fullmatch(args.views_sha256), "external views SHA256 required")
        config_raw = raw_file(args.views_config)
        require(digest(config_raw) == args.views_sha256, "views config bytes differ")
    return dict(
        repo=repo,
        root=root,
        plugin=plugin,
        helper=helper,
        helper_raw=helper_raw,
        home=home,
        user_config=config,
        executable=executable,
        query_runtime=query_runtime,
        stage1_materials_root=materials,
    )


def install_source(checked):
    """Reject preloads, then install the existing raw compile source loader."""
    name = "_project_workspace_source_bootstrap"
    require(name not in sys.modules, "fresh bootstrap process required")
    source = ModuleType(name)
    source.__file__ = str(checked["helper"])
    sys.modules[name] = source
    exec(compile(checked["helper_raw"], source.__file__, "exec"), source.__dict__)
    files = source.inventory(checked["plugin"])
    source.require(files[HELPER] == digest(checked["helper_raw"]), "helper changed")
    loader = source.PinnedLoader(checked["repo"], files)
    sys.meta_path.insert(0, loader)
    spec = loader.find_spec("research_workspace_native.atlas_local_source")
    require(
        spec is not None
        and spec.origin == str(checked["helper"])
        and spec.loader is loader,
        "raw bootstrap helper origin differs",
    )
    # Reuse the already verified raw module/class identity for the query alias.
    # Supply its real loader metadata; never reload or loosen origin checks.
    source.__spec__, source.__loader__, source.__package__ = spec, loader, spec.parent
    return source, files


def prepare(args, checked, *, source=None, inventory=None):
    """Real services and strict factory only; no HTTP or native/model start."""
    runtime = checked.get("query_runtime")
    source = checked.get("source") if source is None else source
    inventory = checked.get("inventory") if inventory is None else inventory
    if runtime is not None:
        require(
            source is not None and isinstance(inventory, dict) and inventory,
            "raw Stage1 query source loader required",
        )
        # PinnedLoader has already rejected preloads. Reuse its exact helper
        # class so the query service can independently verify module origins.
        alias = "research_workspace_native.atlas_local_source"
        require(alias not in sys.modules, "preloaded query source helper refused")
        require(
            query_runtime_config(runtime["path"], runtime["sha256"])
            == runtime["value"],
            "Stage1 query runtime configuration differs",
        )
        sys.modules[alias] = source
    from research_workspace_native.atlas_host import load_views
    from research_workspace_native.http import token_authenticator
    from research_workspace_native.project_host import ProjectHost
    from research_workspace_native.project_intake import ProjectIntakeService
    from research_workspace_native.project_model import ProjectModelService
    from research_workspace_native.project_stage1 import ProjectStage1Service
    from research_workspace_native.project_stage2 import ProjectStage2Service

    files, views = (
        load_views(args.views_config, args.views_sha256)
        if args.views_config
        else ({}, [])
    )
    credential = secrets.token_urlsafe(32)
    authenticate = token_authenticator({credential: "local-viewer"})
    projects = ProjectIntakeService(checked["root"], authenticate=authenticate)
    models = queries = sources = source_dispatcher = None
    try:
        run_grants = None
        if args.enable_stage1_run:
            from research_workspace_native.project_stage1_run_grant import (
                ProjectStage1RunGrantService,
            )

            run_grants = ProjectStage1RunGrantService(
                projects, runtime_sha256=digest(source.canonical(inventory))
            )
        factory = None
        if args.enable_content_model:
            from research_workspace_native.project_model_factory import (
                OwnAccountProjectModelFactory,
            )

            # An explicit home selects this user's account config for this process.
            os.environ["CODEX_HOME"] = str(checked["home"])
            factory = OwnAccountProjectModelFactory(
                checked["repo"],
                checked["executable"],
                checked["user_config"],
                checked["home"],
                authenticate,
                credential,
            )
        models = ProjectModelService(
            projects,
            provider_factory=factory,
            model=args.model,
            local_cap_seconds=args.model_cap_seconds,
            run_grants=run_grants,
            analysis_coverage=args.enable_stage1_run,
        )
        stage1, stage2 = ProjectStage1Service(projects), ProjectStage2Service(projects)
        if runtime is not None:
            from research_workspace_native.project_stage1_queries import (
                ProjectStage1QueryService,
            )

            source_files = deepcopy(inventory)
            runtime_path, runtime_sha = runtime["path"], runtime["sha256"]

            def source_proof(_):
                query_runtime_config(runtime_path, runtime_sha)
                return dict(
                    repo=checked["repo"].as_posix(), files=deepcopy(source_files)
                )

            def admit(_):
                query_runtime_config(runtime_path, runtime_sha)
                return True  # The service still requires a separate saved UI permit.

            config = deepcopy(runtime["value"])
            queries = ProjectStage1QueryService(
                stage1,
                runtime_pin=config["pin"],
                execution_source_root=checked["repo"].as_posix(),
                execution_source_sha256=digest(source.canonical(source_files)),
                verify_source=source_proof,
                admit=admit,
                caps=config["caps"],
                backends=config["backends"],
                run_grants=run_grants,
            )
        sources, source_dispatcher = None, None
        if args.enable_public_sources:
            from research_workspace_native.portable_source_worker_profile import (
                prepare_source_worker_profile,
                register_source_worker,
            )
            from research_workspace_native.project_source_dispatcher import (
                ProjectSourceDispatcher,
            )
            from research_workspace_native.project_source_saved_pipeline import (
                SourceSavedPipeline,
            )
            from research_workspace_native.project_stage1_delivery import (
                ProjectStage1DeliveryService,
            )
            from research_workspace_native.saved_source_parser_factory import (
                ContainedSavedSourceParserFactory,
                prepare_saved_parser_runtime,
            )

            profile = prepare_source_worker_profile(
                repo=checked["repo"],
                materials_root=checked["stage1_materials_root"],
                runtime_sha256=digest(source.canonical(runtime["value"]["pin"])),
                timeout_seconds=args.source_cap_seconds,
            )
            runner, source_config = register_source_worker(profile)
            records = queries.create_records_service(
                ProjectStage1DeliveryService(stage1),
                materials_root=checked["stage1_materials_root"],
            )
            parser_runtime = prepare_saved_parser_runtime(
                sdk_root=Path(runtime["value"]["pin"]["code_identity"]["entry"]).parent
            )
            parser_factory = ContainedSavedSourceParserFactory(
                worker=runner, runtime=parser_runtime
            )
            pipeline = SourceSavedPipeline(
                stage1, records, parser_factory, phase_admission=True
            )
            source_config["pipeline_sha256"] = pipeline.binding_sha256
            sources = runner.create_service(
                projects,
                stage1,
                config=source_config,
                pipeline=pipeline,
                run_grants=run_grants,
            )
            source_dispatcher = ProjectSourceDispatcher(sources)
        return dict(
            projects=projects,
            stage1_run_grants=run_grants,
            models=models,
            stage1=stage1,
            stage2=stage2,
            queries=queries,
            stage1_sources=sources,
            stage1_source_dispatcher=source_dispatcher,
            stage1_materials_root=checked.get("stage1_materials_root"),
            credential=credential,
            files=files,
            views=views,
            host_type=ProjectHost,
        )
    except BaseException:
        try:
            if source_dispatcher is not None:
                source_dispatcher.close()
            elif sources is not None:
                sources.close()
        finally:
            try:
                if queries is not None:
                    queries.close()
            finally:
                try:
                    if models is not None:
                        models.close()
                finally:
                    projects.close()
        raise


def run_requested_stage1(args, host, services):
    """Explicit CLI request only; JSON grants no typed action authority itself."""
    raw = raw_file(args.stage1_run_request, 16384)
    require(digest(raw) == args.stage1_run_request_sha256, "Stage1 run request changed")
    from stage1_ledger.journal import decode
    from research_workspace_native.project_stage1_run_grant import (
        ProjectStage1RunGrantService,
    )

    request = decode(raw, "Stage1 run request")
    require(
        type(request) is dict
        and request.get("kind") == "ProjectStage1RunRequest"
        and request.get("schema_version") == "1.0.0",
        "Stage1 run request schema invalid",
    )
    common = {"kind", "schema_version", "project_ref", "run_id"}
    if "slice_max_actions" in request:
        common.add("slice_max_actions")
    require(
        set(request) in (common | {"authorization"}, common | {"resume"}),
        "Stage1 run request fields invalid",
    )
    issuer = services["stage1_run_grants"]
    require(
        type(issuer) is ProjectStage1RunGrantService
        and issuer.intake is services["projects"],
        "Stage1 run issuer unconnected",
    )
    ref, credential = request["project_ref"], services["credential"]
    require(
        type(ref) is str
        and type(request["run_id"]) is str
        and 0 < len(request["run_id"]) <= 256,
        "Stage1 run reference invalid",
    )
    if "slice_max_actions" in request:
        cap = request["slice_max_actions"]
        require(
            type(cap) is int and 0 < cap <= 512,
            "Stage1 slice cannot expand original action limit",
        )
        if "authorization" in request:
            authorization = request["authorization"]
            require(
                type(authorization) is dict
                and type(authorization.get("max_actions")) is int
                and cap <= authorization["max_actions"],
                "Stage1 slice cannot expand original action limit",
            )
    if "authorization" in request:
        grant = issuer.authorize(credential, ref, request["authorization"])
        require(grant["status"] == "saved", "Stage1 run authorization not saved")
    else:
        grant = request["resume"]
        require(
            type(grant) is dict and set(grant) == {"grant_ref", "grant_sha256"},
            "Stage1 run resume fields invalid",
        )
    doc = issuer.inspect(credential, ref, grant["grant_ref"], grant["grant_sha256"])
    cap = request.get("slice_max_actions", doc["max_actions"])
    require(
        type(cap) is int and 0 < cap <= doc["max_actions"],
        "Stage1 slice cannot expand original action limit",
    )
    remaining = doc["expires_at"] - issuer._now()
    require(remaining > 0, "Stage1 run original deadline exhausted")
    if getattr(args, "enable_stage1_full_source", False):
        host.register_stage1_full_source(
            credential,
            ref,
            run_grants=issuer,
            grant_ref=grant["grant_ref"],
            grant_sha256=grant["grant_sha256"],
            output_root=args.stage1_full_notes_root,
        )
    result = host.continue_stage1(
        credential,
        ref,
        run_id=request["run_id"],
        deadline=time.monotonic() + remaining,
        max_actions=cap,
        run_grants=issuer,
        grant_ref=grant["grant_ref"],
        grant_sha256=grant["grant_sha256"],
    )
    return dict(
        kind="ProjectStage1RunReceipt",
        schema_version="1.0.0",
        project_ref=ref,
        grant_ref=grant["grant_ref"],
        grant_sha256=grant["grant_sha256"],
        result=result,
    )


def main(argv=None):
    args = parser().parse_args(argv)
    checked = inspect_inputs(args)
    source, inventory = install_source(checked)
    checked.update(source=source, inventory=inventory)
    receipt = dict(
        kind="OwnAccountProjectWorkspaceRegistration",
        schema_version="1.0.0",
        plugin_inventory_sha256=digest(
            json.dumps(inventory, sort_keys=True, separators=(",", ":")).encode("utf8")
        ),
        content_model="explicit-UI-authorization-required"
        if args.enable_content_model
        else "disabled",
        actual_account_authentication="not-observed",
        native_calls=0,
        model_calls=0,
        stage1="query runtime configured; separate UI authorization required"
        if checked["query_runtime"] is not None
        else "offline-ledger; external execution unconnected",
        stage2="registered-canonical-import-only; native execution unconnected",
        stages3_to6="planned/unconnected",
        execution_authorized=False,
        stage1_saved_records_configuration=checked["stage1_materials_root"] is not None,
        stage1_source_acquisition_configuration=args.enable_public_sources,
        stage1_saved_parser_core_configuration=args.enable_public_sources,
        stage1_source_acquisition=False,
        stage1_automatic_reading=False,
        stage1_run_grant_configuration=args.enable_stage1_run,
    )
    if args.check_only:
        receipt["status"] = "filesystem-and-raw-loader-preflight-only"
        print(json.dumps(receipt, ensure_ascii=False), flush=True)
        return 0
    services, host = prepare(args, checked), None
    try:
        if not args.prepare_only:
            host = services["host_type"](
                **{
                    k: services[k]
                    for k in (
                        "projects",
                        "models",
                        "stage1",
                        "stage2",
                        "credential",
                        "files",
                        "views",
                        "stage1_materials_root",
                        "stage1_sources",
                        "stage1_source_dispatcher",
                    )
                },
                host="127.0.0.1",
                port=args.port,
            )
            receipt["url"] = host.expected_origin + "/"
        receipt["status"] = "prepared-only" if args.prepare_only else "local-UI-ready"
        print(json.dumps(receipt, ensure_ascii=False), flush=True)
        if args.stage1_run_request is not None:
            result = run_requested_stage1(args, host, services)
            print(json.dumps(result, ensure_ascii=False), flush=True)
            return (
                0
                if result["result"]["status"] == "barrier"
                and result["result"]["reason"] == "saved-delivery"
                else 2
            )
        if host is not None:
            if args.open:
                webbrowser.open(receipt["url"])
            host.serve_forever(poll_interval=0.2)
        return 0
    except KeyboardInterrupt:
        return 2 if args.stage1_run_request is not None else 0
    finally:
        try:
            if host is not None:
                host.server_close()
        finally:
            try:
                if services.get("stage1_source_dispatcher") is not None:
                    services["stage1_source_dispatcher"].close()
                elif services.get("stage1_sources") is not None:
                    services["stage1_sources"].close()
            finally:
                try:
                    if services.get("queries") is not None:
                        services["queries"].close()
                finally:
                    try:
                        services["models"].close()
                    finally:
                        services["projects"].close()


if __name__ == "__main__":
    raise SystemExit(main())
