"""Freeze a coverage plan. Planned queries have not been executed."""

import argparse
from pathlib import Path
import sys

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from stage1_coverage.plan import compile_plan, validate_bundle
from stage1_coverage.run import CoverageLedger
from stage1_ledger.journal import canonical, decode


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    compile_command = commands.add_parser("compile")
    compile_command.add_argument("--input", type=Path, required=True)
    compile_command.add_argument("--output", type=Path, required=True)
    compile_command.add_argument(
        "--as-of",
        required=True,
        help="Frozen YYYY-MM-DD date; recent means this year and the preceding two",
    )
    compile_command.add_argument("--actor", required=True)
    validate = commands.add_parser("validate")
    validate.add_argument("directory", type=Path)
    for name in (
        "bind",
        "open-round",
        "start-query",
        "receipt",
        "close-round",
        "expand",
        "review-work",
        "human-action",
    ):
        command = commands.add_parser(name)
        command.add_argument("--run", type=Path, required=True)
        if name in {"bind", "receipt", "expand", "review-work", "human-action"}:
            command.add_argument("--request", type=Path, required=True)
        if name == "bind":
            command.add_argument("--plan", type=Path, required=True)
        if name == "start-query":
            command.add_argument("--planned-id", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "compile":
            result = compile_plan(
                decode(args.input.read_bytes(), str(args.input)),
                args.output,
                as_of=args.as_of,
                actor=args.actor,
            )
        elif args.command == "validate":
            result = validate_bundle(args.directory)
        else:
            ledger = CoverageLedger(args.run)
            request = (
                decode(args.request.read_bytes(), str(args.request))
                if hasattr(args, "request")
                else {}
            )
            if args.command == "bind":
                result = ledger.bind_plan(args.plan, **request)
            elif args.command == "open-round":
                result = ledger.open_round()
            elif args.command == "start-query":
                result = {"query_id": ledger.start_planned(args.planned_id)}
            elif args.command == "receipt":
                result = ledger.receipt(**request)
            elif args.command == "expand":
                result = {"query_id": ledger.start_expansion(**request)}
            elif args.command == "review-work":
                result = ledger.review_work(**request)
            elif args.command == "human-action":
                result = ledger.human_action(**request)
            else:
                result = ledger.close_round()
        sys.stdout.buffer.write(canonical(result) + b"\n")
        return 1 if result.get("valid") is False else 0
    except (OSError, ValueError, TypeError) as error:
        sys.stdout.buffer.write(canonical({"error": str(error)}) + b"\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
