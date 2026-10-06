"""Export a source-bound draft without changing workflow or selection state."""

import argparse
import copy
import hashlib
import json
from pathlib import Path
import sys

from stage2_check.contracts import decode_json
from stage2_common import Stage2Error, canonical_hash, validate_packet
from stage1_deliverable.common import private_output

from .extraction import validate_extraction

from .report import (
    build_proposal_view,
    render_proposal_html,
    render_proposal_markdown,
)


def _read(path):
    return decode_json(Path(path).read_bytes(), str(path))


def _enable_tables(args):
    """Prepare a new opt-in run seed without rewriting or promoting its parent."""
    original = _read(args.packet)
    validate_packet(original, args.source_root)
    if original["schema_version"] not in {"2.0.0", "2.1.0"}:
        raise Stage2Error("topic tables require a v2 or exploratory v2.1 input seed")
    packet = copy.deepcopy(original)
    packet["schema_version"] = "2.2.0"
    packet["research_tables"] = None
    validate_packet(packet, args.source_root)
    output = Path(args.output).absolute()
    private_output(output.parent)
    raw = (json.dumps(packet, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    with output.open("xb") as stream:
        stream.write(raw)
    print(
        json.dumps(
            {
                "packet": str(output),
                "parent_packet_sha256": canonical_hash(original),
                "packet_sha256": canonical_hash(packet),
                "requires_new_run": True,
                "research_tables_prepared": False,
                "scientific_quality_verified": False,
                "stage3_authorized": False,
            }
        )
    )


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m stage2_ideation")
    commands = parser.add_subparsers(dest="command", required=True)
    enable = commands.add_parser(
        "enable-tables", help="prepare a new topic-table workflow seed"
    )
    for name in ("packet", "source-root", "output"):
        enable.add_argument("--" + name, required=True)
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
    report.add_argument("--completeness-record")
    report.add_argument("--expected-completeness-sha256")
    args = parser.parse_args(argv)
    try:
        if args.command == "enable-tables":
            _enable_tables(args)
            return 0
        if bool(args.completeness_record) != bool(args.expected_completeness_sha256):
            raise Stage2Error(
                "completeness record and external hash must be supplied together"
            )
        packet = _read(args.packet)
        raw_proposal = Path(args.raw_proposal).read_bytes().decode("utf-8")
        extraction = _read(args.extraction)
        completeness = (
            _read(args.completeness_record) if args.completeness_record else None
        )
        if completeness is not None:
            validate_packet(packet, args.source_root)
            validate_extraction(
                raw_proposal,
                extraction,
                packet,
                args.snapshot_sha256,
                completeness_record=completeness,
                expected_completeness_sha256=args.expected_completeness_sha256,
            )
        view = build_proposal_view(
            packet,
            args.source_root,
            raw_proposal,
            extraction,
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
        if completeness is not None:
            files["idea_completeness.json"] = (
                json.dumps(completeness, ensure_ascii=False, indent=2) + "\n"
            ).encode("utf-8")
            manifest.update(
                schema_version="1.1.0",
                completeness_sha256=canonical_hash(completeness),
                completeness_scope="caller-supplied-spans-only",
            )
            manifest["files"]["idea_completeness.json"] = {
                "sha256": hashlib.sha256(files["idea_completeness.json"]).hexdigest(),
                "bytes": len(files["idea_completeness.json"]),
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
