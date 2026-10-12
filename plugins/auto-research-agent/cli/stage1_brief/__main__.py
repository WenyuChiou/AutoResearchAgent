"""Record scope decisions, then compile a confirmed research search plan."""

import argparse
import json
from pathlib import Path

from stage1_ledger.journal import decode

from .brief import compile_confirmed, create_brief, validate_bound_plan, validate_brief
from .formal_target import formal_question, prepare_formal_intake, submit_formal_target


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("record")
    create.add_argument("request", type=Path)
    create.add_argument("output", type=Path)
    create.add_argument("--previous", type=Path)
    intake = sub.add_parser("intake")
    intake.add_argument("request", type=Path)
    intake.add_argument("output", type=Path)
    intake.add_argument("--project-id", required=True)
    intake.add_argument("--input-version", required=True)
    intake.add_argument("--request-id", required=True)
    intake.add_argument("--proposed-target", type=int, default=30)
    question = sub.add_parser("formal-question")
    question.add_argument("brief", type=Path)
    answer = sub.add_parser("submit-formal-target")
    answer.add_argument("brief", type=Path)
    answer.add_argument("answer", type=Path)
    answer.add_argument("output", type=Path)
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

        def load(path):
            return decode(path.read_bytes(), str(path))

        if args.command == "record":
            result = create_brief(load(args.request), args.output, args.previous)
        elif args.command == "intake":
            result = create_brief(
                prepare_formal_intake(
                    load(args.request),
                    project_id=args.project_id,
                    input_version=args.input_version,
                    request_id=args.request_id,
                    proposed_target=args.proposed_target,
                ),
                args.output,
            )
        elif args.command == "formal-question":
            result = formal_question(load(args.brief))
        elif args.command == "submit-formal-target":
            result = create_brief(
                submit_formal_target(load(args.brief), load(args.answer)),
                args.output,
                previous=args.brief,
            )
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
