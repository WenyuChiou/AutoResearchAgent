"""Export reproducible Stage 1 inputs without reading frozen evaluation answers."""

import argparse
from pathlib import Path
import sys

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from stage1_export.bundle import export_run, replay_export_artifacts, validate_export
from stage1_ledger.journal import canonical


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create")
    create.add_argument("--run", type=Path, required=True)
    create.add_argument("--output", type=Path, required=True)
    create.add_argument("--native-capture", type=Path)
    validate = commands.add_parser("validate")
    validate.add_argument("directory", type=Path)
    replay = commands.add_parser("replay-artifacts")
    replay.add_argument("directory", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "create":
            result = export_run(
                args.run, args.output, native_capture=args.native_capture
            )
        elif args.command == "validate":
            result = validate_export(args.directory)
        else:
            result = replay_export_artifacts(args.directory)
    except (OSError, ValueError, TypeError, KeyError) as error:
        result = dict(
            errors=[str(error)],
            evaluation_status="not-scored",
            **(
                dict(
                    kind="Stage1ExportArtifactReplay",
                    schema_version="1.0.0",
                    scope="saved-artifacts-only",
                    artifact_valid=False,
                    source_state_sha256=None,
                    runtime_attestation="not-rechecked",
                )
                if args.command == "replay-artifacts"
                else dict(valid=False)
            ),
        )
    sys.stdout.buffer.write(canonical(result) + b"\n")
    return 0 if result.get("artifact_valid", result.get("valid", False)) else 1


if __name__ == "__main__":
    raise SystemExit(main())
