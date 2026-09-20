"""Freeze a coverage plan. Planned queries have not been executed."""

import argparse
from pathlib import Path
import sys

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from stage1_coverage.plan import compile_plan, validate_bundle
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
    args = parser.parse_args(argv)
    try:
        if args.command == "compile":
            result = compile_plan(
                decode(args.input.read_bytes(), str(args.input)),
                args.output,
                as_of=args.as_of,
                actor=args.actor,
            )
        else:
            result = validate_bundle(args.directory)
        sys.stdout.buffer.write(canonical(result) + b"\n")
        return 1 if result.get("valid") is False else 0
    except (OSError, ValueError, TypeError) as error:
        sys.stdout.buffer.write(canonical({"error": str(error)}) + b"\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
