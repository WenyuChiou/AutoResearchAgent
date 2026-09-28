"""Export a source-bound draft without changing workflow or selection state."""

import argparse
import hashlib
import json
from pathlib import Path
import sys

from stage2_check.contracts import decode_json
from stage2_common import Stage2Error

from .report import (
    build_proposal_view,
    render_proposal_html,
    render_proposal_markdown,
)


def _read(path):
    return decode_json(Path(path).read_bytes(), str(path))


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m stage2_ideation")
    commands = parser.add_subparsers(dest="command", required=True)
    report = commands.add_parser("report", help="export an unassessed ideation draft")
    for name in (
        "packet",
        "source-root",
        "raw-proposal",
        "extraction",
        "snapshot-sha256",
        "output",
    ):
        report.add_argument("--" + name, required=True)
    args = parser.parse_args(argv)
    try:
        view = build_proposal_view(
            _read(args.packet),
            args.source_root,
            Path(args.raw_proposal).read_bytes().decode("utf-8"),
            _read(args.extraction),
            args.snapshot_sha256,
        )
        files = {
            "proposal-view.json": (
                json.dumps(view, ensure_ascii=False, indent=2) + "\n"
            ).encode("utf-8"),
            "proposal.md": render_proposal_markdown(view),
            "proposal.html": render_proposal_html(view),
        }
        manifest = {
            "kind": "Stage2IdeationDraftExport",
            "schema_version": "1.0.0",
            "status": view["status"],
            "snapshot_sha256": view["snapshot_sha256"],
            "files": {
                name: {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
                for name, data in files.items()
            },
            "scientific_quality_verified": False,
            "user_selection_recorded": False,
        }
        output = Path(args.output)
        # Validate and render before creating a fresh export. Never replace edits.
        output.mkdir(parents=True, exist_ok=False)
        for name, data in files.items():
            with (output / name).open("xb") as stream:
                stream.write(data)
        # A missing manifest marks an interrupted/partial export, never completion.
        with (output / "manifest.json").open(
            "x", encoding="utf-8", newline="\n"
        ) as stream:
            stream.write(json.dumps(manifest, indent=2) + "\n")
        print(json.dumps(manifest, sort_keys=True))
        return 0
    except (Stage2Error, OSError, ValueError) as error:
        print(f"stage2-ideation: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
