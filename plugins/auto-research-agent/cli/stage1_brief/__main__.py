"""Record scope decisions, then compile a confirmed research search plan."""

import argparse
import json
from pathlib import Path

from .brief import compile_confirmed, create_brief, validate_bound_plan, validate_brief


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("record")
    create.add_argument("request", type=Path)
    create.add_argument("output", type=Path)
    create.add_argument("--previous", type=Path)
    check = sub.add_parser("validate")
    check.add_argument("brief", type=Path)
    check.add_argument("--confirmed", action="store_true")
    compile_cmd = sub.add_parser("compile")
    compile_cmd.add_argument("brief", type=Path)
    compile_cmd.add_argument("request", type=Path)
    compile_cmd.add_argument("output", type=Path)
    compile_cmd.add_argument("--as-of", required=True)
    compile_cmd.add_argument("--actor", required=True)
    verify = sub.add_parser("validate-plan")
    verify.add_argument("directory", type=Path)
    verify.add_argument("brief", type=Path)
    args = parser.parse_args(argv)
    try:
        load = lambda p: json.loads(p.read_text(encoding="utf-8"))
        if args.command == "record":
            result = create_brief(load(args.request), args.output, args.previous)
        elif args.command == "validate":
            result = validate_brief(load(args.brief), require_confirmed=args.confirmed)
        elif args.command == "compile":
            result = compile_confirmed(
                args.brief,
                load(args.request),
                args.output,
                as_of=args.as_of,
                actor=args.actor,
            )
        else:
            result = validate_bound_plan(args.directory, args.brief)
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(json.dumps({"valid": False, "error": str(exc)}))
        return 1
    print(json.dumps(result, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
