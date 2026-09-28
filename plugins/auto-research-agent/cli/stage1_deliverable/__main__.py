"""Export and verify a private Stage 1 researcher package."""

import argparse
import json
import subprocess
import sys
from pathlib import Path

from .common import DeliverableError, preflight
from .package import build, validate


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    probe = commands.add_parser("preflight")
    probe.add_argument("private_root", type=Path)
    export = commands.add_parser("build")
    export.add_argument("records", type=Path)
    export.add_argument("output", type=Path)
    export.add_argument("--records-sha256", required=True)
    check = commands.add_parser("validate")
    check.add_argument("package", type=Path)
    check.add_argument("--expected-sha256", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "preflight":
            result = preflight(args.private_root)
        elif args.command == "build":
            result = build(args.records, args.output, args.records_sha256)
        else:
            result = validate(args.package, args.expected_sha256)
    except (
        DeliverableError,
        ValueError,
        OSError,
        KeyError,
        TypeError,
        subprocess.SubprocessError,
    ) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
