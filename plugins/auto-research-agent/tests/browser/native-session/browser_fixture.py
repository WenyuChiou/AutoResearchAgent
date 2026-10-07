"""Explicit local browser fixture: real journals/API, synthetic injected channel only."""

import argparse
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import time
from types import ModuleType


def cleanup(fixture, server, worker, diagnostics):
    failures = []
    steps = []
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
    if failures or diagnostics:
        raise RuntimeError("; ".join(failures + diagnostics))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--reference-root", type=Path, required=True)
    parser.add_argument("--temp-root", type=Path, required=True)
    parser.add_argument("--control-file", type=Path, required=True)
    parser.add_argument("--scope", action="store_true")
    args = parser.parse_args()
    if not args.repo.is_absolute():
        raise ValueError("absolute candidate repo required")
    repo = args.repo.resolve(strict=True)
    scripts = repo / "plugins/auto-research-agent/tests/browser/native-session"
    if Path(__file__).resolve(strict=True) != scripts / "browser_fixture.py":
        raise ValueError("fixture must belong to the sole candidate repo")
    script_bytes = {}
    for name in ("browser_fixture.py", "candidate_source.py", "browser_driver.cjs"):
        source = scripts / name
        if source.resolve(strict=True) != source:
            raise ValueError("linked fixture scripts are not allowed")
        script_bytes[name] = source.read_bytes()
    script_sources = {
        name: dict(path=str(scripts / name), sha256=hashlib.sha256(raw).hexdigest())
        for name, raw in script_bytes.items()
    }
    candidate_source = ModuleType("candidate_source")
    exec(
        compile(
            script_bytes["candidate_source.py"],
            str(scripts / "candidate_source.py"),
            "exec",
        ),
        candidate_source.__dict__,
    )
    candidate = candidate_source.load_candidate(repo, args.scope)
    from research_workspace_native.http import token_authenticator
    from research_workspace_native.session_api import SessionApi
    from research_workspace_native.wiki_http import REFERENCE_HASHES, WikiSessionServer
    from test_research_workspace_native_session_api import SessionApiTests

    if args.scope:
        from research_workspace_native.scope_api import ScopeApi
        from research_workspace_native.scope_http import ScopeWikiSessionServer
        from test_research_workspace_native_scope_api import ScopeApiTests

    args.temp_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=args.temp_root) as folder:
        fixture = SessionApiTests()
        fixture.root, fixture.auth = Path(folder), []
        token, other = "a" * 40, "b" * 40
        fixture.api = SessionApi(
            authenticate=token_authenticator(
                {token: "principal-a", other: "principal-b"}
            )
        )
        server = worker = None
        server_errors = []
        try:
            assets = {
                name: (args.reference_root / name).read_bytes()
                for name in REFERENCE_HASHES
            }
            scope_options = {}
            server_class = WikiSessionServer
            if args.scope:
                fixture.scope = ScopeApi(fixture.api)
                server_class = ScopeWikiSessionServer
                scope_options["scope_api"] = fixture.scope
            server = server_class(
                fixture.api,
                reference_assets=assets,
                public_readme=(
                    args.reference_root.parents[1] / "README.md"
                ).read_bytes(),
                max_connections=16,
                timeout=5,
                **scope_options,
            )
            server.handle_error = lambda request, address: server_errors.append(
                "service handler failure"
            )
            worker = threading.Thread(
                target=server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True
            )
            worker.start()
            projects = {}

            def command(row):
                operation, name = row["op"], row.get("name", "a")
                if operation in {"create", "create-scope"}:
                    create = (
                        fixture.project
                        if operation == "create"
                        else lambda n, principal: ScopeApiTests.brief(
                            fixture, n, principal
                        )
                    )
                    p = create(name, row.get("principal", "principal-a"))
                    projects[name] = p
                    return dict(
                        ref=p.ref, token=token, other=other, index_sha256=p.hash
                    )
                p = projects[name]
                if operation == "question":
                    method = row.get("method", "item/tool/requestUserInput")
                    fixture.push(
                        p,
                        dict(
                            id=83,
                            method=method,
                            params=dict(
                                threadId=p.thread,
                                turnId="private-turn",
                                itemId="private-item",
                                approvalId="private-approval",
                                command="neutral command",
                                questions=[
                                    dict(id="q", question="Evidence <literal> 作者原文")
                                ]
                                + (
                                    [dict(id="q2", question="Methods 原文")]
                                    if row.get("two_questions")
                                    else []
                                ),
                            ),
                        ),
                    )
                elif operation == "resolved":
                    fixture.push(
                        p,
                        dict(
                            method="serverRequest/resolved",
                            params=dict(
                                threadId=p.thread,
                                requestId=83,
                            ),
                        ),
                    )
                elif operation == "start":
                    p.controller.client_action(
                        "fixture-start",
                        "turn/start",
                        {
                            "threadId": p.thread,
                        },
                        p.controller.view()["revision"],
                    )
                    sent = p.channel.messages()[-1]
                    fixture.push(
                        p, dict(id=sent["id"], result={"turn": {"id": "saved-turn"}})
                    )
                elif operation == "partial":
                    p.channel.writes.extend([5, OSError("synthetic write failure")])
                elif operation == "drift":
                    p.source_ok = False
                elif operation == "owner-loss":
                    p.store.release_owner(p.pid, p.owner)
                    p.store.acquire_owner(p.pid, "replacement")
                elif operation == "malformed":
                    p.channel.reads.append(b"\xff\n")
                    try:
                        p.controller.pump()
                    except Exception as error:
                        return {"error": type(error).__name__}
                    raise AssertionError("malformed bytes were accepted")
                elif operation != "state":
                    raise ValueError("unknown fixture command")
                try:
                    messages = p.channel.messages()
                except json.JSONDecodeError:
                    messages = []
                state = p.store.snapshot(p.pid)
                return dict(
                    calls=list(p.channel.calls),
                    index_sha256=state["index_sha256"],
                    protocol=state["protocol"],
                    scope=fixture.scope.history(token, p.ref)
                    if hasattr(p, "brief_raw")
                    else None,
                    brief_sha256=hashlib.sha256(p.brief_path.read_bytes()).hexdigest()
                    if hasattr(p, "brief_raw")
                    else None,
                    base_brief_sha256=p.brief_hash if hasattr(p, "brief_raw") else None,
                    writes=p.channel.calls.count("write"),
                    messages=messages,
                    raw_hex=b"".join(p.channel.sent).hex(),
                    intents=state["intents"],
                    requests=state["requests"],
                    turns=state["turns"],
                )

            def emit(value):
                print(json.dumps(value, ensure_ascii=True), flush=True)

            bound_sources = candidate.receipt()
            emit(
                dict(
                    candidate=bound_sources,
                    scripts=script_sources,
                    origin=server.expected_origin,
                    served_sha256={
                        name: hashlib.sha256(raw).hexdigest()
                        for name, raw in server._wiki_assets.items()
                    },
                    source_sha256={
                        row["path"]: row["sha256"]
                        for row in bound_sources["modules"].values()
                    },
                    service_limits={"max_connections": 16, "request_seconds": 5},
                )
            )

            def commands():
                deadline = time.monotonic() + 120
                with args.control_file.open(encoding="utf-8") as control:
                    while time.monotonic() < deadline:
                        line = control.readline()
                        if line:
                            yield line
                        else:
                            time.sleep(0.02)
                    raise TimeoutError("synthetic fixture absolute deadline expired")

            for line in commands():
                row = json.loads(line)
                candidate.verify()
                for name, raw in script_bytes.items():
                    if (scripts / name).read_bytes() != raw:
                        raise ValueError("fixture script bytes changed")
                if row["op"] == "stop":
                    emit({"stopped": True})
                    break
                try:
                    emit({"ok": command(row)})
                except Exception as error:
                    emit({"error": type(error).__name__, "message": str(error)})
        finally:
            cleanup(fixture, server, worker, server_errors)


if __name__ == "__main__":
    main()
