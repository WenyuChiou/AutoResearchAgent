"""Command-line entry point for the offline Stage 2 checker."""

import argparse
import json
import sys

from stage2_common import Stage2Error

from .run import apply_assessment, export_selection, initialize_run


def _parser():
    parser = argparse.ArgumentParser(prog="python -m stage2_check")
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init", help="initialize an immutable checker run")
    init.add_argument("--packet", required=True)
    init.add_argument("--source-root", required=True)
    init.add_argument("--output", required=True)
    init.add_argument("--expected-packet-sha256")
    apply = commands.add_parser("apply", help="append an external assessment")
    apply.add_argument("--run", required=True)
    apply.add_argument("--assessment", required=True)
    export = commands.add_parser("export", help="rebuild prehuman selection views")
    export.add_argument("--run", required=True)
    export.add_argument("--expected-event-head")
    return parser


def main(argv=None):
    args = _parser().parse_args(argv)
    try:
        if args.command == "init":
            result = initialize_run(
                args.packet,
                args.source_root,
                args.output,
                args.expected_packet_sha256,
            )
        elif args.command == "apply":
            result = apply_assessment(args.run, args.assessment)
        else:
            result = export_selection(
                args.run, expected_event_head=args.expected_event_head
            )
    except (Stage2Error, OSError) as error:
        print(f"stage2-check: {error}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
