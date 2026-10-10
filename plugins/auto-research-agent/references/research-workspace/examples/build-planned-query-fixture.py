"""Public, explicitly synthetic browser example of the installed query UI.

Default prepares a saved fixture and exits. --serve is an explicit opt-in to a
bounded loopback host (default 120 seconds, maximum 600 seconds). It never launches Codex, a model, Research Hub or a
network source request. It must run in a fresh isolated Python process.
"""

import argparse
from contextlib import ExitStack
from copy import deepcopy
import hashlib
import importlib.abc
import importlib.util
import json
import os
from pathlib import Path
import secrets
import stat
import shutil
import subprocess
import sys
import tempfile
import threading
import types


EXAMPLE = "plugins/auto-research-agent/references/research-workspace/examples/build-planned-query-fixture.py"
SCRIPT_REPO = Path(__file__).absolute().parents[5]
REQUIRED = (
    "cli/research_workspace_native/planned_queries.py",
    "cli/research_workspace_native/query_execution_source.py",
    "cli/research_workspace_native/query_http.py",
    "cli/research_workspace_native/web/stage-query-panel.js",
    "tests/planned_query_fixture.py",
    "tests/planned_query_safety_cases.py",
)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf8")


def save(path, value):
    with path.open("xb") as stream:
        stream.write(canonical(value))


def install_demo_bootstrap(server, credential):
    """Add an example-only memory bootstrap before the normal host consumes its own."""
    anchor = b'<script src="/host-panel.js"></script>'
    for view in server.views:
        route = view["url"]
        raw = server._assets[route]
        bootstrap_route = "/stage2-demo-bootstrap/" + view["ref"] + ".js"
        if raw.count(anchor) != 1 or bootstrap_route in server._assets:
            raise ValueError("Stage2 demo bootstrap placement differs")
        enabled = view["ref"] == "stage2"
        bootstrap = (
            b"window.WORKSPACE_STAGE2_DEMO="
            + canonical(
                dict(
                    enabled=enabled,
                    project_ref=view["ref"],
                    credential=credential if enabled else "",
                )
            )
            + b";"
        )
        tag = ('<script src="' + bootstrap_route + '"></script>').encode("utf8")
        changed = raw.replace(anchor, tag + anchor, 1)
        server._assets[route] = changed
        server._assets[bootstrap_route] = bootstrap
        server.host_binding["served_files"][route] = digest(changed)
        server.host_binding["served_files"][bootstrap_route] = digest(bootstrap)
    server.host_binding["stage2_demo_overlay"] = "independent synthetic example"
    server._assets["/host-binding.json"] = canonical(server.host_binding)


def git(repo, *args):
    result = subprocess.run(
        ["git", "-c", "core.longpaths=true", *args],
        cwd=repo,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=False,
        timeout=30,
    )
    if result.returncode:
        raise RuntimeError("read-only Git inspection failed")
    return result.stdout


def git_source_bytes(repo, prefix):
    rows = git(repo, "ls-tree", "-r", "HEAD", "--", prefix).splitlines()
    paths = []
    for row in rows:
        header, raw_path = row.split(b"\t", 1)
        mode, kind, oid = header.split()
        if mode not in (b"100644", b"100755") or kind != b"blob":
            raise ValueError("regular tracked source required")
        paths.append((oid, raw_path.decode("utf8")))
    result = subprocess.run(
        ["git", "cat-file", "--batch"],
        cwd=repo,
        input=b"\n".join(oid for oid, _ in paths) + b"\n",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=False,
        timeout=30,
    )
    if result.returncode:
        raise RuntimeError("Git raw blob inspection failed")
    raw, position, files = result.stdout, 0, {}
    for oid, path in paths:
        end = raw.index(b"\n", position)
        actual_oid, kind, size = raw[position:end].split()
        if actual_oid != oid or kind != b"blob":
            raise ValueError("Git blob response differs")
        start = end + 1
        finish = start + int(size)
        files[path] = digest(raw[start:finish])
        if raw[finish : finish + 1] != b"\n":
            raise ValueError("Git blob framing differs")
        position = finish + 1
    if position != len(raw):
        raise ValueError("unexpected Git blob response suffix")
    return files


class FixtureRawLoader(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    """Pin/compile public Python test fixtures, avoiding a cached test pyc."""

    def __init__(self, tests, files):
        self.tests, self.files = tests, files

    def find_spec(self, fullname, path=None, target=None):
        if "." in fullname or fullname + ".py" not in self.files:
            return None
        return importlib.util.spec_from_file_location(
            fullname, self.tests / (fullname + ".py"), loader=self
        )

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        path = self.tests / (module.__name__ + ".py")
        raw = path.read_bytes()
        if digest(raw) != self.files[path.name]:
            raise ValueError("test fixture bytes differ")
        exec(compile(raw, str(path), "exec"), module.__dict__)


def unlinked_path(path):
    path = path.absolute()
    for part in (path, *path.parents):
        info = part.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 1024:
            raise ValueError("source link/reparse refused")
        if part == path and stat.S_ISREG(info.st_mode) and info.st_nlink != 1:
            raise ValueError("source hardlink refused")
    return path


def close_fixture(server, stages, operations, query, boundary):
    errors, query_closed = [], query is None
    for resource in (server, stages, operations, query):
        if resource is None:
            continue
        try:
            resource.server_close() if resource is server else resource.close()
            if resource is query:
                query_closed = True
        except BaseException as error:
            errors.append(type(error).__name__ + ": " + str(error))
    # Never restore the child/probe boundary while a service worker may use it.
    if query_closed:
        try:
            boundary.close()
        except BaseException as error:
            errors.append(
                "injected boundary: " + type(error).__name__ + ": " + str(error)
            )
    return errors


def finish_receipt(output, receipt, verifier, proof, repo, head, errors):
    checks = {
        "source_manifest_unchanged": lambda: verifier(None) == proof,
        "head_unchanged": lambda: (
            git(repo, "rev-parse", "HEAD").decode().strip() == head
        ),
    }
    for name, observe in checks.items():
        try:
            receipt[name] = observe() is True
            if not receipt[name]:
                errors.append(name + ": changed or unobserved")
        except BaseException as error:
            receipt[name] = False
            errors.append(name + ": " + type(error).__name__ + ": " + str(error))
    receipt["cleanup_errors"] = errors
    if errors and receipt["status"] != "failed":
        receipt.update(
            status="failed",
            failure_type="FixtureCleanupUnobserved",
            failure="cleanup/source/head observation failed",
        )
    save(output / "completion-receipt.json", receipt)


def bootstrap(repo, expected_head):
    if not repo.is_absolute() or not repo.is_dir():
        raise ValueError("absolute complete repository required")
    repo = unlinked_path(repo).resolve()
    if unlinked_path(Path(__file__)) != repo / EXAMPLE:
        raise ValueError("example must come from this complete checkout")
    if digest(git(repo, "show", "HEAD:" + EXAMPLE)) != digest(
        Path(__file__).read_bytes()
    ):
        raise ValueError("example script/Git source differs")
    if git(repo, "rev-parse", "HEAD").decode().strip() != expected_head:
        raise ValueError("installed public HEAD differs; do not run an old demo")
    if git(repo, "status", "--porcelain", "--untracked-files=no").strip():
        raise ValueError("source must be frozen and clean before demo")
    plugin = repo / "plugins/auto-research-agent"
    for relative in REQUIRED:
        if not (plugin / relative).is_file():
            raise ValueError("final installed A-F query source required")
    helper_path = plugin / "cli/research_workspace_native/atlas_local_source.py"
    helper = types.ModuleType("research_workspace_native.atlas_local_source")
    helper.__file__ = str(helper_path)
    info = unlinked_path(helper_path).lstat()
    if not stat.S_ISREG(info.st_mode):
        raise ValueError("regular helper required")
    relative = helper_path.relative_to(repo).as_posix()
    expected = git_source_bytes(repo, relative).get(relative)
    helper_raw = helper_path.read_bytes()
    if digest(helper_raw) != expected:
        raise ValueError("helper physical/Git bytes differ before execution")
    exec(compile(helper_raw, str(helper_path), "exec"), helper.__dict__)
    files = {
        "cli/" + key: value for key, value in helper.inventory(plugin / "cli").items()
    }
    # Physical source must equal Git blobs, including assets and empty __init__.
    git_bytes = git_source_bytes(repo, "plugins/auto-research-agent/cli")
    for relative, expected in files.items():
        if git_bytes.get("plugins/auto-research-agent/" + relative) != expected:
            raise ValueError("physical/Git source bytes differ: " + relative)
    loader = helper.PinnedLoader(repo, files)
    sys.meta_path.insert(0, loader)
    sys.modules[helper.__name__] = helper
    tests = plugin / "tests"
    sys.path[:0] = [str(plugin / "cli"), str(tests)]
    test_hashes = {p.name: digest(p.read_bytes()) for p in tests.glob("*.py")}
    git_fixtures = git_source_bytes(repo, "plugins/auto-research-agent/tests")
    if any(
        git_fixtures.get("plugins/auto-research-agent/tests/" + name) != value
        for name, value in test_hashes.items()
    ):
        raise ValueError("fixture physical/Git bytes differ")
    fixture_loader = FixtureRawLoader(tests, test_hashes)
    sys.meta_path.insert(1, fixture_loader)
    proof = {"repo": str(repo), "files": files}

    def current_source(_claim):
        # Return a fresh raw manifest every time. Production verifies its hash,
        # every byte, module origins, loader identity and actual runner code.
        return {
            "repo": str(repo),
            "files": {
                "cli/" + key: value
                for key, value in helper.inventory(plugin / "cli").items()
            },
        }

    return plugin, helper, proof, current_source, test_hashes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=SCRIPT_REPO)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-head")
    parser.add_argument("--serve", action="store_true")
    parser.add_argument(
        "--demonstrate-stage2-run",
        action="store_true",
        help="Fixed legacy synthetic Stage2 controller; no live authority",
    )
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--lifetime", type=int, default=120)
    args = parser.parse_args()
    if not 1 <= args.lifetime <= 600 or not 0 <= args.port <= 65535:
        parser.error("loopback host limited to 600 seconds and a valid local port")
    if not sys.flags.isolated or not sys.dont_write_bytecode:
        parser.error("fresh Python -I -B -X utf8 required")
    args.repo = unlinked_path(args.repo).resolve()
    args.expected_head = (
        args.expected_head or git(args.repo, "rev-parse", "HEAD").decode().strip()
    )
    plugin, helper, proof, verifier, test_hashes = bootstrap(
        args.repo, args.expected_head
    )
    from stage1_deliverable.common import private_output

    if not args.output.is_absolute():
        parser.error("absolute new output directory outside Git required")
    output = private_output(helper.unlinked(args.output)).resolve()
    if output.is_relative_to(args.repo) or args.repo.is_relative_to(output):
        parser.error("source/output overlap refused")
    output.mkdir(parents=True, exist_ok=False)
    temporary_root = output / "temporary"
    temporary_root.mkdir()
    # All test fixture writes stay under the explicit private output directory.
    tempfile.tempdir = str(temporary_root)
    os.environ.update(
        TEMP=str(temporary_root), TMP=str(temporary_root), TMPDIR=str(temporary_root)
    )
    import planned_query_fixture

    planned_query_fixture.RAW_SOURCE_PROOF = deepcopy(proof)
    from research_workspace_native.planned_queries import PlannedQueryService
    from research_workspace_native.atlas_host import AtlasHost, load_views
    from research_workspace_native.stage_actions import StageActions
    from research_workspace_native.stage_inputs import snapshot_inputs, source_digest
    from research_workspace_native.harness_host import create_harness_operations
    from research_workspace_native.http import token_authenticator

    builder_path = (
        plugin / "references/research-workspace/examples/build-review-fixture.py"
    )
    builder = types.ModuleType("installed_saved_case_builder")
    builder.__file__ = str(builder_path)
    if digest(
        git(
            args.repo,
            "show",
            "HEAD:plugins/auto-research-agent/references/research-workspace/examples/build-review-fixture.py",
        )
    ) != digest(builder_path.read_bytes()):
        raise ValueError("saved case builder/Git bytes differ")
    exec(
        compile(builder_path.read_bytes(), str(builder_path), "exec"), builder.__dict__
    )
    notice_path = builder_path.with_name("planned-query-fixture-notice.js")
    notice_raw = notice_path.read_bytes()
    if digest(
        git(
            args.repo,
            "show",
            "HEAD:plugins/auto-research-agent/references/research-workspace/examples/planned-query-fixture-notice.js",
        )
    ) != digest(notice_raw):
        raise ValueError("fixture notice/Git bytes differ")
    original_index = builder.fixture_index

    def index():
        value = original_index()
        value["project_id"] = "project-a"
        value["topic"] = (
            "Synthetic planned-query UI / 模拟查询工程案例 / 模擬查詢工程案例"
        )
        return value

    builder.fixture_index = index
    query_case = planned_query_fixture.QueryCase("runTest")
    server = query = operations = stages = timer = demo = None
    setup_done = False
    boundary = ExitStack()
    receipt = dict(
        kind="SyntheticInstalledQueryUiDemo",
        expected_head=args.expected_head,
        expected_tree=git(args.repo, "rev-parse", "HEAD^{tree}").decode().strip(),
        repo=str(args.repo.resolve()),
        script_sha256=digest(Path(__file__).read_bytes()),
        source_manifest_sha256=digest(canonical(proof["files"])),
        test_source_hashes=test_hashes,
        builder_sha256=digest(builder_path.read_bytes()),
        classification="synthetic-repository-fixture",
        maximum_host_seconds=args.lifetime,
        native_script_role="fixture-notice-only",
        researcher_confirmed_intake=False,
        intake_mode="test-generated confirmation; not human research authority",
        permit_mode="synthetic fake-backend-only; not production search authority",
        raw_pinned_source=True,
        native_process_started=False,
        model_call_started=False,
        real_search_started=False,
        hub_child_mode="injected-Popen-object-no-process",
        probe_mode="pure-saved-byte-check-no-process",
        scientific_acceptance=False,
        stage2_lineage="independent saved synthetic completion example",
        stage1_query_scope="one explicitly confirmed synthetic existing planned backend query",
        original_view_updated_by_query=False,
        status="preparing",
    )
    save(output / "execution-source-manifest.json", proof)
    try:
        query_case.setUp()
        setup_done = True
        builder.build(output / "saved-views")
        saved = output / "saved-views"
        saved_receipt = json.loads((saved / "fixture-receipt.json").read_bytes())
        config = json.loads((saved / "host.json").read_bytes())
        config["views"][0].update(
            ref="case", label="Stage 1 synthetic query + saved repository case"
        )
        config["views"][1]["label"] = "Stage 2 independent synthetic saved completion"
        save(output / "host.json", config)
        files, views = load_views(output / "host.json", digest(canonical(config)))
        credential = secrets.token_urlsafe(
            32
        )  # Only in memory/bootstrap, never URL/file.
        authenticate = token_authenticator({credential: "local-viewer"})
        query_case.item["index_sha256"] = views[0]["index_sha256"]
        query_case.item["principals"] = ["local-viewer"]
        query_case.permit["binding"]["index_sha256"] = views[0]["index_sha256"]
        query_case.permit["principals"] = ["local-viewer"]
        query_case.write_permit()
        query = PlannedQueryService(
            query_case.root / "query.sqlite3",
            registrations={"case": deepcopy(query_case.item)},
            authenticate=authenticate,
            admit=lambda event: True,
            verify_source=verifier,
        )
        source_inputs = json.loads((saved / "stage-inputs.json").read_bytes())
        source_inputs["1"] = {"ledger_root": str(query_case.parent_ledger)}
        input_sha = source_digest(snapshot_inputs(source_inputs))
        stages = StageActions(
            output / "stages.sqlite3",
            authenticate=authenticate,
            registrations={
                view["ref"]: dict(
                    project_id=view["project_id"],
                    index_sha256=view["index_sha256"],
                    input_version=query_case.item["input_version"],
                    source_sha256=input_sha,
                    inputs=source_inputs,
                    output_root=str(output / "stage-results" / view["ref"]),
                    principals=["local-viewer"],
                )
                for view in views
            },
            planned_queries=query,
        )
        if args.demonstrate_stage2_run:
            demo_path = builder_path.with_name("stage2-demo.py")
            panel_path = builder_path.with_name("stage2-demo-panel.js")
            demo_raw, panel_raw = demo_path.read_bytes(), panel_path.read_bytes()
            for path, raw in ((demo_path, demo_raw), (panel_path, panel_raw)):
                relative = path.relative_to(args.repo).as_posix()
                if digest(git(args.repo, "show", "HEAD:" + relative)) != digest(raw):
                    raise ValueError("Stage2 demo source/Git bytes differ")
            demo_module = types.ModuleType("installed_fixed_stage2_demo")
            demo_module.__file__ = str(demo_path)
            exec(compile(demo_raw, str(demo_path), "exec"), demo_module.__dict__)
            fixed_pins = dict(proof["files"])
            fixed_pins.update({"tests/" + k: v for k, v in test_hashes.items()})
            demo = demo_module.RepositoryStage2Demo(
                output / "stage2-run-demo",
                repo=args.repo,
                sources=fixed_pins,
                project_ref="stage2",
                index_sha256=views[1]["index_sha256"],
                authenticate=authenticate,
            )
            notice_raw += b"\n" + panel_raw
            receipt.update(
                stage2_run_demo=True,
                stage2_demo_case_sha256=demo.case_sha256,
                stage2_demo_scope="legacy Stage2Packet 1.0.0 controller fixture; independent lineage; no scores",
                stage2_demo_script_sha256=digest(demo_raw),
                stage2_demo_panel_sha256=digest(panel_raw),
                native_script_role="fixture notice and fixed synthetic Stage2 action",
            )
        operations = create_harness_operations(
            files, views, output / "harness-operations", credential
        )
        receipt.update(
            status="prepared",
            stage1_papers=saved_receipt["stage1_papers"],
            stage2_literature=saved_receipt["stage2_literature"],
            stage1_parent_ledger_sha256=query_case.item["parent_ledger_sha256"],
            index_sha256=views[0]["index_sha256"],
            input_version=query_case.item["input_version"],
        )
        save(output / "prepared-receipt.json", receipt)
        if args.serve:
            # The real repository runner executes; only its probe and external
            # child boundary are injected. No fake executable can be launched.
            boundary.enter_context(query_case.no_probe())
            boundary.enter_context(query_case.fake_runner())
            server = AtlasHost(
                files=files,
                views=views,
                stage_actions=stages,
                harness_ops=operations,
                credential=credential,
                port=args.port,
                timeout=30,
                native_script=notice_raw,
            )
            if demo is not None:
                install_demo_bootstrap(server, credential)
                demo_module.install(server, demo)
            receipt.update(
                status="serving",
                origin=server.expected_origin,
                notice_sha256=digest(notice_raw),
                stage1_url=server.expected_origin + "/views/case/atlas.html",
                stage2_url=server.expected_origin + "/views/stage2/atlas.html",
            )
            save(output / "serving-receipt.json", receipt)
            print(
                json.dumps(
                    {
                        "output": str(output),
                        "stage1_url": receipt["stage1_url"],
                        "stage2_url": receipt["stage2_url"],
                        "classification": receipt["classification"],
                        "native": "disabled",
                        "model": "disabled",
                        "lifetime_seconds": args.lifetime,
                    }
                ),
                flush=True,
            )
            timer = threading.Timer(args.lifetime, server.shutdown)
            timer.daemon = True
            timer.start()
            try:
                server.serve_forever(poll_interval=0.1)
            except KeyboardInterrupt:
                pass
            finally:
                timer.cancel()
            receipt["query_history"] = query.view(credential, "case")
            if demo is not None:
                receipt["stage2_demo_history"] = demo.view(credential, "stage2")
            receipt["injected_children"] = deepcopy(query_case.children)
        else:
            print(
                json.dumps(
                    {
                        "output": str(output),
                        "classification": "synthetic-repository-fixture",
                        "status": "prepared-no-listener",
                    }
                ),
                flush=True,
            )
        receipt["status"] = "completed-fixture-lifecycle"
    except BaseException as error:
        receipt.update(
            status="failed", failure_type=type(error).__name__, failure=str(error)
        )
        raise
    finally:
        if timer is not None:
            timer.cancel()
        primary_failed = receipt["status"] == "failed"
        cleanup_errors = close_fixture(server, stages, operations, query, boundary)
        if demo is not None:
            try:
                demo.close()
            except Exception as error:
                cleanup_errors.append("Stage2 demo close: " + type(error).__name__)
        query_closed = query is None or query._closed
        receipt["retained_query_attempt_status"] = "not-created"
        if setup_done and query_case.root.exists():
            receipt["retained_query_attempt_status"] = "incomplete-worker-unobserved"
            if query_closed:
                try:
                    shutil.copytree(query_case.root, output / "retained-query-attempt")
                    receipt["retained_query_attempt_status"] = "closed-worker-copy"
                except BaseException as error:
                    cleanup_errors.append(
                        "retain: " + type(error).__name__ + ": " + str(error)
                    )
        if setup_done and query_closed:
            try:
                if query_case.doCleanups() is not True:
                    cleanup_errors.append("fixture root cleanup unobserved")
            except BaseException as error:
                cleanup_errors.append(
                    "fixture root: " + type(error).__name__ + ": " + str(error)
                )
        finish_receipt(
            output,
            receipt,
            verifier,
            proof,
            args.repo,
            args.expected_head,
            cleanup_errors,
        )
        if cleanup_errors and not primary_failed:
            raise RuntimeError(
                "fixture cleanup unobserved; retained completion receipt"
            )


if __name__ == "__main__":
    main()
