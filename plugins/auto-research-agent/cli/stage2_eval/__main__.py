"""Offline JSON CLI for Stage 2 view, judge, merge, and comparison checks."""

import argparse
import json
from pathlib import Path

from stage2_common import Stage2Error, validate_packet

from .evaluation import (
    compare_pairs,
    merge_judgments,
    prepare_content_view,
    validate_judge_output,
)


def _read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write(value, path):
    raw = (
        json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        + "\n"
    )
    if path:
        target = Path(path)
        if target.exists():
            raise Stage2Error(f"refusing to overwrite {target}")
        target.write_text(raw, encoding="utf-8")
    else:
        print(raw, end="")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    content = sub.add_parser("prepare-content")
    content.add_argument("--packet", required=True)
    content.add_argument("--source-root", required=True)
    content.add_argument("--subject-id", required=True)
    content.add_argument("--input-sha256", required=True)
    content.add_argument("--config-sha256", required=True)
    content.add_argument("--rubric")
    content.add_argument("--output")
    action = sub.add_parser("prepare-action")
    for flag in (
        "packet",
        "source-root",
        "content-view",
        "content-assessment",
        "action-record",
    ):
        action.add_argument("--" + flag, required=True)
    action.add_argument("--output")
    judge = sub.add_parser("validate-judge")
    for flag in ("packet", "source-root", "content-view", "action-view", "judge"):
        judge.add_argument("--" + flag, required=True)
    judge.add_argument("--rubric")
    merge = sub.add_parser("merge")
    for flag in ("packet", "source-root", "content-view", "r1", "r2"):
        merge.add_argument("--" + flag, required=True)
    merge.add_argument(
        "--action-view",
        required=True,
        help="R1 action view (also used for R2 only when --action-view-r2 is omitted)",
    )
    merge.add_argument(
        "--action-view-r2",
        help="R2 action view when its independently written content assessment differs",
    )
    merge.add_argument(
        "--action-view-adj",
        help="ADJ action view when adjudication uses its own content assessment",
    )
    merge.add_argument("--adj")
    merge.add_argument("--audit")
    merge.add_argument("--rubric")
    merge.add_argument("--output")
    compare = sub.add_parser("compare")
    compare.add_argument("--pairs", required=True)
    compare.add_argument("--output")
    args = parser.parse_args(argv)
    if args.command == "compare":
        _write(compare_pairs(_read(args.pairs)), args.output)
        return 0
    packet = _read(args.packet)
    validate_packet(packet, args.source_root)
    if args.command == "prepare-content":
        value = prepare_content_view(
            packet,
            args.subject_id,
            args.input_sha256,
            args.config_sha256,
            rubric_path=args.rubric,
        )
        _write(value, args.output)
    elif args.command == "prepare-action":
        from .evaluation import prepare_action_view

        _write(
            prepare_action_view(
                packet,
                _read(args.content_view),
                _read(args.content_assessment),
                _read(args.action_record),
            ),
            args.output,
        )
    elif args.command == "validate-judge":
        validate_judge_output(
            _read(args.judge),
            _read(args.content_view),
            _read(args.action_view),
            packet,
            rubric_path=args.rubric,
        )
        print('{"valid":true,"diagnostic_only":true,"external_claim_ready":false}')
    else:
        value = merge_judgments(
            _read(args.r1),
            _read(args.r2),
            _read(args.content_view),
            _read(args.action_view),
            packet,
            action_view_r2=(
                _read(args.action_view_r2) if args.action_view_r2 else None
            ),
            adj=_read(args.adj) if args.adj else None,
            action_view_adj=(
                _read(args.action_view_adj) if args.action_view_adj else None
            ),
            audit=_read(args.audit) if args.audit else None,
            rubric_path=args.rubric,
        )
        _write(value, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
