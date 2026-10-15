"""Five-minute synthetic browser fixture; no Codex, model or search process."""

import argparse
import hashlib
from pathlib import Path
import secrets
import sys
import threading
import time
from types import ModuleType
import json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    if not args.report.is_absolute() or args.report.exists():
        raise ValueError("new absolute report path required")
    tests = Path(__file__).resolve().parents[1]
    repo = tests.parents[2]
    helper = tests / "browser/project-intake-fixture.py"
    raw_loader = ModuleType("_recovery_raw_loader")
    exec(compile(helper.read_bytes(), str(helper), "exec"), raw_loader.__dict__)
    roots = [tests.parent / "cli", tests]
    sys.meta_path.insert(0, raw_loader.RawSources(roots))
    sys.path[:0] = [str(root) for root in roots]
    from test_project_model_recovery import ModelRecoveryTests
    from research_workspace_native.project_host import ProjectHost

    case = ModelRecoveryTests()
    case.setUp()
    host = None
    try:
        ref, _, _ = case.unknown(principal="local-viewer")
        credential = secrets.token_urlsafe(32)
        case.case.intake.authenticate = lambda token: (
            "local-viewer" if token in {credential, "alice-token"} else None
        )
        ui_sources = {
            str(path.relative_to(repo)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in (roots[0] / "research_workspace_native/web").iterdir()
            if path.is_file()
        }
        host = ProjectHost(
            projects=case.case.intake,
            models=case.case.model,
            credential=credential,
            files={},
            views=[],
            port=0,
        )
        thread = threading.Thread(target=host.serve_forever, daemon=True)
        thread.start()
        print(
            json.dumps(
                {
                    "url": "http://127.0.0.1:" + str(host.server_address[1]) + "/",
                    "project_ref": ref,
                    "synthetic": True,
                    "lease_seconds": 300,
                }
            ),
            flush=True,
        )
        stop = args.report.with_suffix(".stop")
        expires = time.monotonic() + 300
        while not stop.exists() and time.monotonic() < expires:
            time.sleep(0.1)
        host.shutdown()
        host.server_close()
        thread.join(3)
        report = {
            "kind": "SyntheticModelRetirementBrowserObservation",
            "project_ref": ref,
            "view": case.case.model.read("alice-token", ref),
            "history": case.case.model.history("alice-token", ref),
            "provider_factories": case.case.factories,
            "provider_io": case.case.io,
            "native_or_model_processes_started": 0,
            "source_repo": str(repo),
            "executed_sources": {
                str(Path(path).relative_to(repo)): digest
                for path, digest in raw_loader.EXECUTED_SOURCES.items()
            },
            "ui_sources": ui_sources,
        }
        args.report.parent.mkdir(parents=True, exist_ok=True)
        with args.report.open("x", encoding="utf8", newline="\n") as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
    finally:
        if host is not None:
            host.shutdown()
            host.server_close()
        case.tearDown()


if __name__ == "__main__":
    main()
