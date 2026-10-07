"""Opt-in browser/service acceptance with injected channels, never native research."""

import argparse
import hashlib
import importlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading
import time


PLUGIN = Path("plugins/auto-research-agent")
FIXTURE = PLUGIN / "tests/research_workspace_native_browser/core_panel_fixture.py"
DRIVER = PLUGIN / "tests/research_workspace_native_browser/core_panel_path.js"
REQUIRED = (
    [
        PLUGIN / "cli/research_workspace_native" / name
        for name in (
            "wiki_http.py",
            "http.py",
            "session_api.py",
            "controller.py",
            "construction.py",
            "frame_journal.py",
            "web/session-panel.js",
            "web/session-panel.css",
        )
    ]
    + [
        PLUGIN / "tests" / name
        for name in (
            "test_research_workspace_native_session_api.py",
            "native_session_fixtures.py",
        )
    ]
    + [DRIVER, FIXTURE, PLUGIN / "README.md"]
    + [
        PLUGIN / "references/research-workspace" / name
        for name in (
            "prototype.html",
            "literature-reference.js",
            "workspace-i18n.js",
            "workspace.css",
        )
    ]
)


def git(repo, *args):
    env = dict(os.environ, GIT_NO_LAZY_FETCH="1", GIT_NO_REPLACE_OBJECTS="1")
    return subprocess.check_output(["git", "-C", str(repo), *args], env=env)


def reference_assets(repo, commit, pins):
    if len(commit) != 40 or any(c not in "0123456789abcdef" for c in commit):
        raise ValueError("exact retained reference commit required")
    assets, receipts = {}, {}
    for name, expected in pins.items():
        path = (PLUGIN / "references/research-workspace" / name).as_posix()
        raw = git(repo, "show", commit + ":" + path)
        if hashlib.sha256(raw).hexdigest() != expected:
            raise ValueError("retained reference hash differs: " + name)
        assets[name] = raw
        receipts[name] = dict(commit=commit, path=path, sha256=expected)
    return assets, receipts


def file_receipt(repo, path):
    path = path.resolve(strict=True)
    if not path.is_file() or not path.is_relative_to(repo):
        raise ValueError("candidate origin is outside the declared checkout")
    relative = path.relative_to(repo).as_posix()
    raw = path.read_bytes()
    if raw != git(repo, "show", ":" + relative):
        raise ValueError(
            "candidate physical bytes differ from the Git index: " + relative
        )
    return dict(path=str(path), sha256=hashlib.sha256(raw).hexdigest())


def candidate(repo_arg, head, staged_sha=None):
    if not Path(repo_arg).is_absolute():
        raise ValueError("absolute candidate root required")
    repo = Path(repo_arg).resolve(strict=True)
    root = Path(git(repo, "rev-parse", "--show-toplevel").decode().strip()).resolve()
    if root != repo or git(repo, "rev-parse", "HEAD").decode().strip() != head:
        raise ValueError("candidate root or HEAD differs")
    if staged_sha is None:
        if git(repo, "status", "--porcelain").strip():
            raise ValueError("clean candidate checkout required")
    else:
        diff = git(repo, "diff", "--cached", "--binary", "--full-index")
        if (
            not diff
            or hashlib.sha256(diff).hexdigest() != staged_sha
            or git(repo, "diff", "--name-only").strip()
            or git(repo, "ls-files", "--others", "--exclude-standard").strip()
        ):
            raise ValueError("staged candidate fingerprint or working bytes differ")
    for folder in (repo / PLUGIN / "cli", repo / PLUGIN / "tests"):
        if any(folder.rglob("*.pyc")):
            raise ValueError("candidate bytecode cache must be absent before import")
    return repo, {p.as_posix(): file_receipt(repo, repo / p) for p in REQUIRED}


def origins(repo, modules):
    result = {}
    for name, module in tuple(modules.items()):
        if name.startswith(
            (
                "research_workspace_native",
                "test_research_workspace_native",
                "native_session_fixtures",
            )
        ) and getattr(module, "__file__", None):
            result[name] = file_receipt(repo, Path(module.__file__))
    return result


def output_root(path_arg, repo):
    if not Path(path_arg).is_absolute():
        raise ValueError("absolute output directory required")
    path = Path(path_arg).resolve()
    if path.exists() or path.is_relative_to(repo) or not path.parent.is_dir():
        raise ValueError("new output directory outside the candidate required")
    probe = subprocess.run(
        ["git", "-C", str(path.parent), "rev-parse", "--is-inside-work-tree"],
        capture_output=True,
        check=False,
    )
    if probe.returncode == 0:
        raise ValueError("output must be outside every Git worktree")
    path.mkdir()
    return path


def stop_child(process):
    if process is None or process.poll() is not None:
        return
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                check=True,
                capture_output=True,
            )
        else:
            os.killpg(process.pid, signal.SIGKILL)
    finally:
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=10)


def record_cleanups(fixture):
    errors, register = [], fixture.addCleanup

    def remember(action, *args, **kwargs):
        def observed():
            try:
                action(*args, **kwargs)
            except BaseException as error:
                errors.append(
                    "fixture callback: "
                    + type(error).__name__
                    + ": "
                    + str(error)[:1000]
                )
                raise

        register(observed)

    fixture.addCleanup = remember
    return errors


def cleanup(fixture, process, server, worker, diagnostics=()):
    failures = []
    steps = [("owned browser child", lambda: stop_child(process))]
    if server is not None:
        if worker is not None and worker.is_alive():
            steps.append(("service shutdown", server.shutdown))
        steps.append(("service close", server.server_close))
    if worker is not None:
        steps.append(("service join", lambda: worker.join(2)))
    for name, action in steps:
        try:
            action()
        except BaseException as error:
            failures.append(name + ": " + repr(error))
    if worker is not None and worker.is_alive():
        failures.append("service worker did not stop")
    try:
        if not fixture.doCleanups():
            failures.append("fixture doCleanups reported failure")
    except BaseException as error:
        failures.append("fixture cleanup: " + repr(error))
    return failures + list(diagnostics)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("repo", "head", "node", "executor", "node-modules", "output"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument(
        "--staged-sha256", help="exact precommit fingerprint; never implicit"
    )
    args = parser.parse_args()
    repo, sources = candidate(args.repo, args.head, args.staged_sha256)
    if Path(__file__).resolve() != repo / FIXTURE:
        raise ValueError(
            "run the fixture from the declared candidate, no overlay fallback"
        )
    node, executor = (
        Path(args.node).resolve(strict=True),
        Path(args.executor).resolve(strict=True),
    )
    env = os.environ.copy()
    env["NODE_PATH"] = str(Path(args.node_modules).resolve(strict=True))
    # Prove the existing runtime can resolve Playwright and its browser. No installer.
    runtime = json.loads(
        subprocess.check_output(
            [
                str(node),
                "-e",
                'const p=require("playwright"); console.log(JSON.stringify({node:process.version,playwright:require("playwright/package.json").version,browser:p.chromium.executablePath()}))',
            ],
            env=env,
            text=True,
            timeout=10,
        )
    )
    browser = Path(runtime["browser"]).resolve(strict=True)
    if not browser.is_file():
        raise ValueError("existing Chromium executable required")
    output = output_root(args.output, repo)
    driver = output / "playwright-test-core-panel.js"
    driver.write_bytes((repo / DRIVER).read_bytes())
    tempfile.tempdir = str(output)
    sys.dont_write_bytecode = True
    sys.path[:0] = [str(repo / PLUGIN / "tests"), str(repo / PLUGIN / "cli")]
    fixtures = importlib.import_module("test_research_workspace_native_session_api")
    wiki = importlib.import_module("research_workspace_native.wiki_http")
    http = importlib.import_module("research_workspace_native.http")
    api = importlib.import_module("research_workspace_native.session_api")
    imported = origins(repo, sys.modules)
    fixture = fixtures.SessionApiTests()
    cleanup_diagnostics = record_cleanups(fixture)
    started = time.monotonic()
    server, worker, failure, process, result = None, None, None, None, {}
    references = {}
    try:
        fixture.setUp()
        fixture.api = api.SessionApi(
            authenticate=http.token_authenticator({"a" * 40: "principal-a"})
        )
        projects = [fixture.project("a"), fixture.project("b")]
        for p in projects:
            fixture.push(
                p,
                {
                    "id": 83,
                    "method": "item/tool/requestUserInput",
                    "params": {
                        "threadId": p.thread,
                        "turnId": "synthetic-turn-" + p.ref,
                        "itemId": "synthetic-item",
                        "questions": [
                            {
                                "id": "q",
                                "question": "Synthetic question "
                                + p.ref
                                + " <source-value>",
                            }
                        ],
                    },
                },
            )
        assets, references = reference_assets(
            repo, wiki.REFERENCE_COMMIT, wiki.REFERENCE_HASHES
        )
        server = wiki.WikiSessionServer(
            fixture.api,
            reference_assets=assets,
            public_readme=(repo / PLUGIN / "README.md").read_bytes(),
        )
        errors = []
        server.handle_error = lambda request, address: errors.append(address)
        worker = threading.Thread(
            target=server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True
        )
        worker.start()
        env.update(
            TARGET_URL="http://" + server.expected_host, WIKI_BROWSER_OUTPUT=str(output)
        )
        process = subprocess.Popen(
            [str(node), str(executor), str(driver)],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            start_new_session=os.name != "nt",
        )
        try:
            stdout, _ = process.communicate(timeout=120)
        except subprocess.TimeoutExpired:
            raise RuntimeError("bounded browser driver timeout")
        (output / "browser.log").write_text(stdout, encoding="utf-8")
        first = fixture.api.view("a" * 40, "project-a")
        result = dict(
            injected_write_counts=[p.channel.calls.count("write") for p in projects],
            action_statuses=[item["status"] for item in first["actions"]],
            request_statuses=[item["status"] for item in first["requests"]],
            projects=[
                dict(
                    project=p.ref,
                    root=str(p.root),
                    thread=p.thread,
                    epoch=p.epoch,
                    index_sha256=p.hash,
                    input_version=p.version,
                )
                for p in projects
            ],
            server_errors=errors,
        )
        if (
            process.returncode
            or result["injected_write_counts"] != [1, 0]
            or result["action_statuses"] != ["dispatched"]
            or result["request_statuses"] != ["answer-sent"]
            or errors
        ):
            raise RuntimeError(
                "browser or service acceptance failed; inspect saved receipts"
            )
        candidate(args.repo, args.head, args.staged_sha256)
    except BaseException as error:
        failure = repr(error)
        raise
    finally:
        cleanup_failures = cleanup(
            fixture, process, server, worker, cleanup_diagnostics
        )
        failure = failure or ("; ".join(cleanup_failures) if cleanup_failures else None)
        receipt = dict(
            status="FAIL" if failure else "PASS",
            head=args.head,
            staged_sha256=args.staged_sha256,
            repo=str(repo),
            seconds=time.monotonic() - started,
            sources=sources,
            origins=imported,
            reference_assets=references,
            runtime=dict(
                runtime,
                python=sys.version,
                node_sha256=hashlib.sha256(node.read_bytes()).hexdigest(),
                executor_sha256=hashlib.sha256(executor.read_bytes()).hexdigest(),
            ),
            browser_driver_sha256=hashlib.sha256(driver.read_bytes()).hexdigest(),
            failure=failure,
            cleanup_failures=cleanup_failures,
            native_research_calls=0,
            model_calls=0,
            synthetic_fixture_only=True,
            result=result,
        )
        (output / "service-result.json").write_text(
            json.dumps(receipt, indent=2) + "\n", encoding="utf-8"
        )
        print(
            json.dumps(
                {
                    key: receipt[key]
                    for key in (
                        "status",
                        "head",
                        "staged_sha256",
                        "seconds",
                        "failure",
                        "result",
                    )
                }
            )
        )
        if failure:
            raise RuntimeError(failure)


if __name__ == "__main__":
    main()
