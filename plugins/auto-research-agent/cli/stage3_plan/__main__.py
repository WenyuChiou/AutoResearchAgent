"""Explicit planning commands; no scientific-execution command is provided."""

import argparse
import json
import sys

from .contracts import Stage3Error
from .decision import record_plan_decision
from .planner import draft_plan
from .report import render_plan
from .review import plan_status, validate_review
from .storage import inspect_package, read_json
from .validation import check_plan


def _intake_args(parser):
    parser.add_argument("--planning-package", required=True)
    parser.add_argument("--delivery", required=True)
    parser.add_argument("--expected-source-manifest-sha256", required=True)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Generic Stage3 scientific planning (no research execution)"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    legacy = commands.add_parser("prepare-legacy-mapping")
    for name in ("packet", "source-root", "expected-packet-sha256", "output"):
        legacy.add_argument("--" + name, required=True)
    legacy_inspect = commands.add_parser("inspect-legacy-mapping")
    legacy_inspect.add_argument("--package", required=True)
    legacy_inspect.add_argument("--expected-manifest-sha256", required=True)
    evaluation_prepare = commands.add_parser("evaluation-prepare")
    evaluation_prepare.add_argument("--package", required=True)
    evaluation_prepare.add_argument("--expected-manifest-sha256", required=True)
    evaluation_prepare.add_argument("--output", required=True)
    evaluation_record = commands.add_parser("evaluation-record")
    for name in (
        "request",
        "expected-request-sha256",
        "judgment",
        "expected-judgment-sha256",
        "output",
    ):
        evaluation_record.add_argument("--" + name, required=True)
    from .workflow_cli import add_commands

    add_commands(commands)
    draft = commands.add_parser("draft")
    _intake_args(draft)
    for name in (
        "output",
        "plan-id",
        "model",
        "reasoning",
        "codex",
        "codex-home",
        "capture-dir",
    ):
        draft.add_argument("--" + name, required=True)
    draft.add_argument("--version", type=int, default=1)
    draft.add_argument(
        "--plan-schema-version", choices=("1.0.0", "1.1.0"), default="1.0.0"
    )
    draft.add_argument("--timeout-seconds", type=float, required=True)
    draft.add_argument("--resume-manifest-sha256")
    for command in ("inspect", "check", "render", "record-plan-decision"):
        sub = commands.add_parser(command)
        sub.add_argument("--package", required=True)
        sub.add_argument("--expected-manifest-sha256", required=True)
        if command in {"render", "check"}:
            sub.add_argument("--review")
        if command == "record-plan-decision":
            _intake_args(sub)
            for name in (
                "review",
                "expected-review-sha256",
                "native-message",
                "user-text",
                "output",
            ):
                sub.add_argument("--" + name, required=True)
            sub.add_argument("--message-index", type=int, required=True)
            sub.add_argument(
                "--decision", choices=("confirm", "revise", "defer"), required=True
            )
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare-legacy-mapping":
            from .legacy_mapping import prepare_legacy_mapping

            result = prepare_legacy_mapping(
                args.packet,
                args.source_root,
                expected_packet_sha256=args.expected_packet_sha256,
                output_dir=args.output,
            )
        elif args.command == "inspect-legacy-mapping":
            from .legacy_mapping import inspect_legacy_mapping

            result = inspect_legacy_mapping(
                args.package,
                expected_manifest_sha256=args.expected_manifest_sha256,
            )
        elif args.command == "evaluation-prepare":
            from .evaluation import prepare_evaluation

            result = prepare_evaluation(
                args.package,
                expected_manifest_sha256=args.expected_manifest_sha256,
                output=args.output,
            )
        elif args.command == "evaluation-record":
            from .evaluation import record_evaluation

            result = record_evaluation(
                args.request,
                expected_request_sha256=args.expected_request_sha256,
                judgment=args.judgment,
                expected_judgment_sha256=args.expected_judgment_sha256,
                output=args.output,
            )
        elif args.command.startswith("workflow-"):
            from .workflow_cli import run

            result = run(args)
        elif args.command == "draft":
            from .native import NativePlanner

            result = draft_plan(
                args.planning_package,
                args.delivery,
                expected_manifest_sha256=args.expected_source_manifest_sha256,
                output_dir=args.output,
                callback=NativePlanner(
                    codex=args.codex,
                    codex_home=args.codex_home,
                    capture_dir=args.capture_dir,
                    timeout_seconds=args.timeout_seconds,
                ),
                configuration={"model": args.model, "reasoning": args.reasoning},
                plan_id=args.plan_id,
                version=args.version,
                schema_version=args.plan_schema_version,
                resume_manifest_sha256=args.resume_manifest_sha256,
            )
            result = result["manifest"]
        elif args.command == "record-plan-decision":
            result = record_plan_decision(
                args.package,
                expected_manifest_sha256=args.expected_manifest_sha256,
                review_path=args.review,
                expected_review_sha256=args.expected_review_sha256,
                native_message=args.native_message,
                message_index=args.message_index,
                user_text=args.user_text,
                decision=args.decision,
                output_dir=args.output,
                planning_package=args.planning_package,
                delivery_dir=args.delivery,
                expected_source_manifest_sha256=args.expected_source_manifest_sha256,
            )
        elif args.command == "render":
            print(
                render_plan(
                    args.package,
                    expected_manifest_sha256=args.expected_manifest_sha256,
                    review=read_json(args.review) if args.review else None,
                )
            )
            return 0
        else:
            saved = inspect_package(args.package, args.expected_manifest_sha256)
            result = saved["manifest"]
            if args.command == "check":
                plan = saved["artifacts"].get("plan.json")
                if plan is None:
                    raise Stage3Error("no valid saved plan; inspect retained failure")
                intake = saved["artifacts"]["request.json"]["intake"]
                review = read_json(args.review) if args.review else None
                if review:
                    validate_review(plan, intake, review)
                result = {
                    **check_plan(plan, intake=intake),
                    "plan_status": plan_status(
                        plan,
                        intake,
                        review,
                        admission_scope=saved["artifacts"]["request.json"][
                            "admission_scope"
                        ],
                    ),
                }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (Stage3Error, OSError, ValueError) as error:
        failure = {
            "status": "failed",
            "error": str(error),
            "execution_authorized": False,
        }
        if args.command.startswith("evaluation-"):
            failure["evaluation_calls_authorized"] = False
            failure["formal_execution_enabled"] = False
            failure["external_claim_ready"] = False
        print(
            json.dumps(failure, ensure_ascii=False),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
