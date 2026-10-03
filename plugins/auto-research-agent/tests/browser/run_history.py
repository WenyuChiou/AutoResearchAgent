"""Serve the real UI/API against synthetic data; open the printed URL to test.

The browser page runs assertions automatically and posts its result. Exit 0 means
pass; failure or no browser result within 180 seconds exits nonzero. No Codex,
external model, research provider, or production data is used.
"""

import json
import mimetypes
from pathlib import Path
import sys
import threading
from unittest.mock import patch
from urllib.parse import urlsplit

TESTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TESTS))
from test_research_studio import StudioTests, TOKEN  # noqa: E402
from research_studio.server import make_server  # noqa: E402


def main():
    case = StudioTests("test_resume_no_reexecution")
    case.setUp()
    server = None
    worker = None
    completed = threading.Event()
    results = []
    try:
        run = case.run_fixture()
        detail = case.store.detail(run["id"], 0)
        origins = set()
        server = make_server(case.engine, TOKEN, origins, ("127.0.0.1", 0))
        origin = f"http://127.0.0.1:{server.server_port}"
        origins.add(origin)
        static = TESTS.parent / "cli/research_studio/static"
        files = {
            f"/ui/{name}": static / name
            for name in ("index.html", "studio.js", "studio.css", "config.js")
        }
        files["/test.html"] = Path(__file__).with_name("history.html")
        base = server.RequestHandlerClass

        class Handler(base):
            def do_GET(self):
                path = urlsplit(self.path).path
                if path == "/fixture.json":
                    return self.send(200, {"token": TOKEN, "detail": detail})
                if path in files:
                    data = files[path].read_bytes()
                    self.send_response(200)
                    self.send_header(
                        "Content-Type", mimetypes.guess_type(path)[0] or "text/plain"
                    )
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                    return
                return super().do_GET()

            def do_POST(self):
                if self.path == "/test-result":
                    if self.headers.get("Origin") != origin:
                        return self.send(403, {"error": "test origin required"})
                    size = int(self.headers.get("Content-Length", "0"))
                    if not 0 < size <= 16384:
                        return self.send(400, {"error": "bounded test result required"})
                    result = json.loads(self.rfile.read(size))
                    results.append(result)
                    self.send(200, {"received": True})
                    completed.set()
                    return
                return super().do_POST()

        server.RequestHandlerClass = Handler
        answer = json.dumps(
            {
                "message": "Synthetic attachment received.",
                "question": "",
                "suggested_scope": "",
            }
        )
        code = (
            "import pathlib,sys; sys.stdin.read(); pathlib.Path('final.md').write_text("
            + repr(answer)
            + ",encoding='utf-8')"
        )
        with (
            patch.object(
                case.engine, "command", return_value=[sys.executable, "-c", code]
            ),
            patch.object(
                case.engine,
                "dialogue_command",
                return_value=[sys.executable, "-c", code],
            ),
        ):
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            print(
                f"Open {origin}/test.html (synthetic browser/API regression)",
                flush=True,
            )
            if not completed.wait(180):
                raise AssertionError("No browser result within 180 seconds")
            print(json.dumps(results[-1], ensure_ascii=True), flush=True)
            if results[-1].get("status") != "passed":
                raise AssertionError("Browser regression failed")
            # Independently confirm two persisted review decisions on the fixture version.
            decisions = case.store.decisions(run["stage"], run["topic"])
            assert len(decisions) == 2, decisions
            for decision in decisions:
                assert decision["request"]["run_id"] == run["id"]
                assert (
                    decision["request"]["manifest_sha256"] == detail["manifest_sha256"]
                )
            assert len(case.store.list()) == 1, "unexpected extra research run"
            print(
                "PASS: persisted decisions match the inspected run and manifest",
                flush=True,
            )
    finally:
        if server is not None:
            if worker is not None:
                server.shutdown()
            server.server_close()
        case.tearDown()
        case.doCleanups()


if __name__ == "__main__":
    main()
