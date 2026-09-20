"""Public entry point for explicit, saved-provenance retrieval attempts."""

import argparse
import json
from pathlib import Path

from stage1_ledger.journal import LedgerError, decode
from stage1_ledger.store import Ledger
from .runner import execute, resume
from .runtime_identity import capture_identity


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    freeze = sub.add_parser(
        "freeze-runtime", help="Bind reviewed runtime labels to actual code files"
    )
    freeze.add_argument("--runtime", type=Path, required=True)
    freeze.add_argument("--output", type=Path, required=True)
    init = sub.add_parser("init")
    init.add_argument("run", type=Path)
    init.add_argument("--runtime", type=Path, required=True)
    init.add_argument("--run-id", required=True)
    init.add_argument("--topic", required=True)
    run = sub.add_parser("execute")
    run.add_argument("run", type=Path)
    run.add_argument("query_id")
    run.add_argument("--backend", required=True)
    saved = sub.add_parser("resume")
    saved.add_argument("run", type=Path)
    saved.add_argument("attempt_id")
    args = parser.parse_args()
    try:
        if args.action == "freeze-runtime":
            from .receipt import check_pin

            pin = decode(args.runtime.read_bytes(), str(args.runtime))
            pin["code_identity"] = capture_identity(pin["argv_prefix"])
            check_pin(pin)
            with args.output.open("x", encoding="utf-8", newline="\n") as stream:
                json.dump(pin, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
            result = {
                "runtime": str(args.output),
                "files_sha256": pin["code_identity"]["files_sha256"],
            }
        elif args.action == "init":
            pin = decode(args.runtime.read_bytes(), str(args.runtime))
            Ledger.create(
                args.run, run_id=args.run_id, objective=args.topic, research_hub_pin=pin
            )
            result = dict(
                run=str(args.run),
                mode="research-hub-cli",
                dependency_status=pin["status"],
            )
        else:
            result = {
                "completion_id": execute(args.run, args.query_id, args.backend)
                if args.action == "execute"
                else resume(args.run, args.attempt_id)
            }
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (LedgerError, OSError, KeyError) as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
