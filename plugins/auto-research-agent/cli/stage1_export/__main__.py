"""Export reproducible Stage 1 inputs without reading frozen evaluation answers."""

import argparse
from pathlib import Path
import sys

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from stage1_export.bundle import export_run, validate_export
from stage1_ledger.journal import canonical


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create")
    create.add_argument("--run", type=Path, required=True)
    create.add_argument("--output", type=Path, required=True)
    validate = commands.add_parser("validate")
    validate.add_argument("directory", type=Path)
    args = parser.parse_args(argv)
    try:
        result = (
            export_run(args.run, args.output)
            if args.command == "create"
            else validate_export(args.directory)
        )
    except (OSError, ValueError, TypeError, KeyError) as error:
        result = dict(valid=False, errors=[str(error)], evaluation_status="not-scored")
    sys.stdout.buffer.write(canonical(result) + b"\n")
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
