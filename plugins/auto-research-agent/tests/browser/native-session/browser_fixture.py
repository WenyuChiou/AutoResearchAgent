"""Explicit local browser fixture: real journals/API, synthetic injected channel only."""

import argparse
import hashlib
import importlib
import json
from pathlib import Path
import sys
import tempfile
import threading
import time


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--reference-root", type=Path, required=True)
    parser.add_argument("--overlay", type=Path, required=True)
    parser.add_argument("--temp-root", type=Path, required=True)
    parser.add_argument("--control-file", type=Path, required=True)
    parser.add_argument("--scope", action="store_true")
    args = parser.parse_args()
    plugin = args.repo / "plugins/auto-research-agent"
    sys.path[:0] = [str(plugin / "tests"), str(plugin / "cli")]
    import research_workspace_native

    research_workspace_native.__path__.insert(0, str(args.overlay))
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
        assets = {
            name: (args.reference_root / name).read_bytes() for name in REFERENCE_HASHES
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
            public_readme=(args.reference_root.parents[1] / "README.md").read_bytes(),
            **scope_options,
        )
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        projects = {}

        def command(row):
            operation, name = row["op"], row.get("name", "a")
            if operation in {"create", "create-scope"}:
                create = (
                    fixture.project
                    if operation == "create"
                    else lambda n, principal: ScopeApiTests.brief(fixture, n, principal)
                )
                p = create(name, row.get("principal", "principal-a"))
                projects[name] = p
                return dict(ref=p.ref, token=token, other=other, index_sha256=p.hash)
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

        modules = [
            importlib.import_module("research_workspace_native." + name)
            for name in (
                "controller",
                "recording",
                "frame_journal",
                "session_api",
                "http",
                "wiki_http",
            )
        ]
        if args.scope:
            modules.extend(
                importlib.import_module("research_workspace_native." + name)
                for name in ("scope_api", "scope_http")
            )
        emit(
            dict(
                origin=server.expected_origin,
                served_sha256={
                    name: hashlib.sha256(raw).hexdigest()
                    for name, raw in server._wiki_assets.items()
                },
                source_sha256={
                    str(Path(module.__file__)): hashlib.sha256(
                        Path(module.__file__).read_bytes()
                    ).hexdigest()
                    for module in modules
                },
            )
        )
        try:

            def commands():
                deadline = time.monotonic() + 120
                with args.control_file.open(encoding="utf-8") as control:
                    while time.monotonic() < deadline:
                        line = control.readline()
                        if line:
                            deadline = time.monotonic() + 120
                            yield line
                        else:
                            time.sleep(0.02)
                    raise TimeoutError("synthetic fixture control lease expired")

            for line in commands():
                row = json.loads(line)
                if row["op"] == "stop":
                    emit({"stopped": True})
                    break
                try:
                    emit({"ok": command(row)})
                except Exception as error:
                    emit({"error": type(error).__name__, "message": str(error)})
        finally:
            server.shutdown()
            server.server_close()
            worker.join(2)
            fixture.doCleanups()


if __name__ == "__main__":
    main()
