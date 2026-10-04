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
    formal_plan = sub.add_parser("freeze-formal-plan")
    formal_plan.add_argument("--config", required=True)
    formal_plan.add_argument("--evidence-root", required=True)
    formal_plan.add_argument("--output", required=True)
    formal_plan_v3 = sub.add_parser("freeze-formal-plan-v3")
    formal_plan_v3.add_argument("--config", required=True)
    formal_plan_v3.add_argument("--evidence-root", required=True)
    formal_plan_v3.add_argument("--output", required=True)
    for name in ("validate-readiness", "validate-formal-result"):
        entry = sub.add_parser(name)
        for option in ("manifest", "evidence-root", "receipt", "output"):
            entry.add_argument("--" + option, required=True)
        if name == "validate-formal-result":
            entry.add_argument("--plan", required=True)
    diagnostics = sub.add_parser("prepare-diagnostics")
    diagnostics.add_argument("--cases", required=True)
    diagnostics.add_argument("--recipes", required=True)
    diagnostics.add_argument("--output", required=True)
    diagnostics.add_argument(
        "--output-version", choices=("2.0.0", "2.1.0"), default="2.0.0"
    )
    diagnostic_check = sub.add_parser("validate-diagnostic")
    diagnostic_check.add_argument("--cases", required=True)
    diagnostic_check.add_argument("--result", required=True)
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
    content_v3 = sub.add_parser("prepare-content-v3")
    for flag in (
        "packet",
        "source-root",
        "subject-id",
        "input-sha256",
        "config-sha256",
        "output",
    ):
        content_v3.add_argument("--" + flag, required=True)
    action_v3 = sub.add_parser("prepare-action-v3")
    for flag in (
        "packet",
        "source-root",
        "content-view",
        "content-assessment",
        "action-record",
        "output",
    ):
        action_v3.add_argument("--" + flag, required=True)
    judge_v3 = sub.add_parser("validate-judge-v3")
    for flag in (
        "packet",
        "source-root",
        "content-view",
        "action-view",
        "judge",
        "output",
    ):
        judge_v3.add_argument("--" + flag, required=True)
    merge_v3 = sub.add_parser("merge-v3")
    for flag in (
        "packet",
        "source-root",
        "content-view",
        "action-view",
        "r1",
        "r2",
        "output",
    ):
        merge_v3.add_argument("--" + flag, required=True)
    merge_v3.add_argument("--action-view-r2")
    merge_v3.add_argument("--action-view-adj")
    merge_v3.add_argument("--adj")
    merge_v3.add_argument("--audit")
    compare_v3 = sub.add_parser("compare-v3")
    compare_v3.add_argument("--pairs", required=True)
    compare_v3.add_argument("--output", required=True)
    bundle_v3 = sub.add_parser("validate-bundle-v3")
    bundle_v3.add_argument("--bundle", required=True)
    bundle_v3.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    if args.command in {
        "freeze-formal-plan",
        "freeze-formal-plan-v3",
        "validate-readiness",
        "validate-formal-result",
    }:
        from .formal import (
            freeze_formal_plan_v1,
            validate_readiness_v1,
            validate_formal_result_v1,
        )

        try:
            if args.command == "freeze-formal-plan-v3":
                from .formal_v3 import freeze_formal_plan_v2

                value = freeze_formal_plan_v2(_read(args.config), args.evidence_root)
            elif args.command == "freeze-formal-plan":
                value = freeze_formal_plan_v1(_read(args.config), args.evidence_root)
            elif args.command == "validate-readiness":
                value = validate_readiness_v1(
                    args.manifest, args.evidence_root, args.receipt
                )
            else:
                value = validate_formal_result_v1(
                    args.manifest, args.evidence_root, args.receipt, _read(args.plan)
                )
        except (OSError, ValueError, KeyError, TypeError) as error:
            # An invalid/missing archive is a measurement failure, not a zero
            # scientific score or permission to launch another subject.
            value = {
                "status": "blocked",
                "error_type": "evaluator_failure",
                "operation": args.command,
                "reason": str(error),
                "formal_ready": False,
                "improvement_established": False,
            }
        _write(value, args.output)
        return 2 if value.get("status") in {"blocked", "inconclusive"} else 0
    if args.command == "prepare-diagnostics":
        from stage2_live.calibration import prepare_calibration

        _write(
            prepare_calibration(
                _read(args.cases),
                _read(args.recipes),
                output_version=args.output_version,
            ),
            args.output,
        )
        return 0
    if args.command == "validate-diagnostic":
        from .diagnostics import validate_diagnostic_output

        validate_diagnostic_output(_read(args.result), _read(args.cases))
        print('{"valid":true,"diagnostic_only":true,"scientific_approval":false}')
        return 0
    if args.command == "compare":
        _write(compare_pairs(_read(args.pairs)), args.output)
        return 0
    if args.command in {"compare-v3", "validate-bundle-v3"}:
        from .evaluation_v3 import compare_pairs_v3, validate_bundle_v3

        if args.command == "compare-v3":
            value = compare_pairs_v3(_read(args.pairs))
        else:
            validate_bundle_v3(_read(args.bundle))
            value = {
                "valid": True,
                "diagnostic_only": True,
                "external_claim_ready": False,
            }
        _write(value, args.output)
        return 0
    packet = _read(args.packet)
    validate_packet(packet, args.source_root)
    if args.command.endswith("-v3"):
        from .evaluation_v3 import (
            merge_judgments_v3,
            prepare_action_view_v3,
            prepare_content_view_v3,
            validate_judge_output_v3,
        )

        if args.command == "prepare-content-v3":
            value = prepare_content_view_v3(
                packet,
                args.subject_id,
                args.input_sha256,
                args.config_sha256,
            )
        elif args.command == "prepare-action-v3":
            value = prepare_action_view_v3(
                packet,
                _read(args.content_view),
                _read(args.content_assessment),
                _read(args.action_record),
            )
        elif args.command == "validate-judge-v3":
            validate_judge_output_v3(
                _read(args.judge),
                _read(args.content_view),
                _read(args.action_view),
                packet,
            )
            value = {
                "valid": True,
                "diagnostic_only": True,
                "external_claim_ready": False,
            }
        else:
            value = merge_judgments_v3(
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
            )
        _write(value, args.output)
        return 0
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
