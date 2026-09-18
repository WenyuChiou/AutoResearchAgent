"""Saved-observation CLI. No command in this release executes network searches."""

import argparse
from pathlib import Path
import sys

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from stage1_ledger.journal import LedgerError, canonical, decode
from stage1_ledger.readiness import readiness
from stage1_ledger.store import Ledger
from stage1_ledger.validation import validate_run


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser(
        "init", help="Create an explicitly offline observation run"
    )
    init.add_argument("--run-id", required=True)
    init.add_argument("--objective", required=True)
    start = commands.add_parser("start", help="Register intent before the observation")
    start.add_argument("--request", type=Path, required=True)
    save = commands.add_parser(
        "save", help="Save immutable source bytes and emit ArtifactRef"
    )
    save.add_argument("--source", type=Path, required=True)
    save.add_argument("--producer", required=True)
    for name in ("finish", "decide", "claim"):
        command = commands.add_parser(name)
        command.add_argument("--request", type=Path, required=True)
    query = commands.add_parser("complete-query")
    query.add_argument("--query-id", required=True)
    for name in ("extract", "validate", "gate", "checkpoint", "recover"):
        commands.add_parser(name)
    args = parser.parse_args(argv)
    try:
        ledger = Ledger(args.run)
        if args.command == "init":
            ledger = Ledger.create(
                args.run, run_id=args.run_id, objective=args.objective
            )
            result = ledger.manifest
        elif args.command in {"start", "finish", "decide", "claim"}:
            request = decode(args.request.read_bytes(), str(args.request))
            if not isinstance(request, dict):
                raise LedgerError("request-must-be-object")
            result = {"event_id": getattr(ledger, args.command)(**request)}
        elif args.command == "save":
            if args.source.stat().st_size > ledger.manifest["max_artifact_bytes"]:
                raise LedgerError("artifact-size-limit")
            result = ledger.save_bytes(args.source.read_bytes(), producer=args.producer)
        elif args.command == "complete-query":
            result = {"event_id": ledger.complete_query(args.query_id)}
        elif args.command == "validate":
            result = validate_run(args.run)
        elif args.command == "gate":
            gate, action = readiness(validate_run(args.run))
            result = {"gate": gate, "next_allowed_action": action}
        else:
            result = getattr(ledger, args.command)()
        sys.stdout.buffer.write(canonical(result) + b"\n")
        failed = (args.command == "validate" and not result["valid"]) or (
            args.command == "extract" and result["extraction_failures"]
        )
        return 1 if failed else 0
    except (LedgerError, OSError, TypeError, KeyError, ValueError) as error:
        sys.stdout.buffer.write(
            canonical({"error": str(error), "operation": args.command}) + b"\n"
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
