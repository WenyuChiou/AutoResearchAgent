"""Explicit native calls and extraction, without a second workflow scheduler."""

import argparse
import json
from pathlib import Path
import sys

from stage1_eval.common import EvaluationError
from stage2_check.contracts import decode_json
from stage2_common import Stage2Error, validate_packet
from stage2_ideation import build_research_task

from .extraction import run_live_extraction
from .judges import run_stage2_judges
from .native import CaptureError, capture_native, verify_capture
from .preflight import inspect_preflight
from .profile import prepare_profile
from .review_models import (
    extract_resolution,
    extract_review,
    reconciliation_task,
    review_task,
)


def _read(path):
    return decode_json(Path(path).read_bytes(), str(path))


def _save(path, value):
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m stage2_live")
    commands = parser.add_subparsers(dest="command", required=True)
    control = commands.add_parser(
        "controller", help="run the foreground Stage 2 sequence"
    )
    for option in (
        "workflow",
        "controller-root",
        "delivery",
        "spec",
        "expected-head",
        "output",
    ):
        control.add_argument("--" + option, required=True)
    control_check = commands.add_parser(
        "verify-controller", help="read-only controller verification"
    )
    for option in ("controller-root", "receipt", "output"):
        control_check.add_argument("--" + option, required=True)
    action_extract = commands.add_parser(
        "extract-actions", help="shared prose action extraction for either arm"
    )
    for option in (
        "raw-proposal",
        "packet",
        "source-root",
        "codex",
        "evaluator-home",
        "model",
        "reasoning",
        "policy",
        "output",
        "replay-receipt-output",
    ):
        action_extract.add_argument("--" + option, required=True)
    action_extract.add_argument("--resume", action="store_true")
    action_extract.add_argument("--replay-receipt")
    calibration = commands.add_parser(
        "calibrate", help="run one frozen supplied-fact calibration unit"
    )
    for option in (
        "unit",
        "codex",
        "evaluator-home",
        "model",
        "reasoning",
        "policy",
        "output",
    ):
        calibration.add_argument("--" + option, required=True)
    calibration.add_argument("--resume", action="store_true")
    calibration.add_argument("--replay-receipt")
    calibration.add_argument("--replay-receipt-output", required=True)
    profile = commands.add_parser(
        "prepare-profile", help="prepare a new profile from native skill discovery"
    )
    profile.add_argument("--destination", required=True)
    profile.add_argument("--skills-response", required=True)
    profile.add_argument("--skills-sha256", required=True)
    profile.add_argument("--output", required=True)
    preflight = commands.add_parser(
        "preflight", help="verify effective policy, native actions and isolation"
    )
    preflight.add_argument("--capture", required=True)
    preflight.add_argument("--receipt", required=True)
    preflight.add_argument("--probe", required=True)
    preflight.add_argument("--inventory-receipt")
    preflight.add_argument("--output", required=True)
    capture = commands.add_parser("capture", help="capture one native research call")
    capture.add_argument("--request", required=True)
    capture.add_argument("--receipt-output", required=True)
    verify = commands.add_parser("verify-capture", help="verify saved capture bytes")
    verify.add_argument("--capture", required=True)
    verify.add_argument("--receipt", required=True)
    tasks = []
    for name in ("research-task", "review-task", "reconciliation-task"):
        task = commands.add_parser(name)
        task.add_argument("--snapshot-sha256", required=True)
        task.add_argument("--output", required=True)
        if name != "research-task":
            task.add_argument("--candidate", required=True)
        if name == "review-task":
            task.add_argument(
                "--role", required=True, choices=["challenger", "feasibility"]
            )
        if name == "reconciliation-task":
            task.add_argument("--reviews", required=True)
        tasks.append(task)
    calls = []
    for name in ("extract", "extract-review", "extract-resolution", "judge"):
        call = commands.add_parser(name)
        call.add_argument("--codex", required=True)
        call.add_argument("--model", required=True)
        call.add_argument("--reasoning", required=True)
        call.add_argument("--policy", required=True)
        call.add_argument("--output", required=True)
        call.add_argument("--resume", action="store_true")
        call.add_argument(
            "--replay-receipt", help="externally retained receipt JSON for resume"
        )
        call.add_argument(
            "--replay-receipt-output", help="new external file for the returned receipt"
        )
        if name != "judge":
            call.add_argument("--evaluator-home", required=True)
            call.add_argument("--snapshot-sha256", required=True)
        if name == "extract":
            call.add_argument("--raw-proposal", required=True)
        elif name != "judge":
            call.add_argument("--candidate", required=True)
            call.add_argument("--capture", required=True)
            call.add_argument("--receipt", required=True)
            if name == "extract-review":
                call.add_argument(
                    "--role", choices=["challenger", "feasibility"], required=True
                )
            else:
                call.add_argument("--reviews", required=True)
        else:
            for option in (
                "subject-id",
                "input-sha256",
                "config-sha256",
                "actions",
                "r1-home",
                "r2-home",
                "adj-home",
            ):
                call.add_argument("--" + option, required=True)
        calls.append(call)
    for command in tasks + calls:
        command.add_argument("--packet", required=True)
        command.add_argument("--source-root", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command in {"controller", "verify-controller"}:
            from .controller import run_controller, verify_controller

            if Path(args.output).exists():
                raise CaptureError("output already exists")
            if args.command == "controller":
                result = run_controller(
                    args.workflow,
                    args.controller_root,
                    args.delivery,
                    args.expected_head,
                    _read(args.spec),
                )
            else:
                result = verify_controller(args.controller_root, args.receipt)
            _save(args.output, result)
        elif args.command == "extract-actions":
            from .action_extraction import run_action_extraction

            if Path(args.replay_receipt_output).exists():
                raise CaptureError("replay receipt output already exists")
            result = run_action_extraction(
                Path(args.raw_proposal).read_bytes().decode("utf-8"),
                _read(args.packet),
                args.source_root,
                codex=args.codex,
                evaluator_home=args.evaluator_home,
                model=args.model,
                reasoning=args.reasoning,
                execution_policy=_read(args.policy),
                output_dir=args.output,
                resume=args.resume,
                resume_receipt=_read(args.replay_receipt)
                if args.replay_receipt
                else None,
            )
            _save(args.replay_receipt_output, result["replay_receipt"])
        elif args.command == "calibrate":
            from .calibration import run_calibration_unit

            if Path(args.replay_receipt_output).exists():
                raise CaptureError("replay receipt output already exists")
            result = run_calibration_unit(
                _read(args.unit),
                codex=args.codex,
                evaluator_home=args.evaluator_home,
                model=args.model,
                reasoning=args.reasoning,
                execution_policy=_read(args.policy),
                output_dir=args.output,
                resume=args.resume,
                resume_receipt=_read(args.replay_receipt)
                if args.replay_receipt
                else None,
            )
            _save(args.replay_receipt_output, result["replay_receipt"])
        elif args.command in {"prepare-profile", "preflight"}:
            if Path(args.output).exists():
                raise CaptureError("output already exists")
            if args.command == "prepare-profile":
                result = prepare_profile(
                    args.destination, args.skills_response, args.skills_sha256
                )
            else:
                result = inspect_preflight(
                    args.capture,
                    args.receipt,
                    _read(args.probe),
                    inventory_receipt=_read(args.inventory_receipt)
                    if args.inventory_receipt
                    else None,
                )
            _save(args.output, result)
        elif args.command == "capture":
            if Path(args.receipt_output).exists():
                raise CaptureError("receipt output already exists")
            request = _read(args.request)
            # No caller-supplied executable Python/test seams can enter via JSON.
            allowed = {
                "codex",
                "codex_home",
                "workspace",
                "prompt",
                "model",
                "reasoning",
                "input_bindings",
                "config_bindings",
                "policy_bindings",
                "output_dir",
                "resume",
                "record_sha256_receipt",
            }
            if not isinstance(request, dict) or set(request) - allowed:
                raise CaptureError("capture request contains unsupported fields")
            result = capture_native(**request)
            _save(
                args.receipt_output,
                {
                    "receipt": result["record_sha256_receipt"],
                    "status": result["status"],
                },
            )
        elif args.command == "verify-capture":
            record, _ = verify_capture(args.capture, args.receipt)
            result = {
                "status": "complete",
                "capture_verified": True,
                "native_session_records": record.get(
                    "native_session_records", "unknown"
                ),
            }
        else:
            packet = _read(args.packet)
            validate_packet(packet, args.source_root)
            if args.command in {"research-task", "review-task", "reconciliation-task"}:
                if args.command == "research-task":
                    result = build_research_task(packet, args.snapshot_sha256)
                elif args.command == "review-task":
                    result = review_task(
                        packet, args.candidate, args.snapshot_sha256, args.role
                    )
                else:
                    result = reconciliation_task(
                        packet,
                        args.candidate,
                        args.snapshot_sha256,
                        _read(args.reviews),
                    )
                _save(args.output, result)
            else:
                if (
                    args.replay_receipt_output
                    and Path(args.replay_receipt_output).exists()
                ):
                    raise EvaluationError("replay receipt output already exists")
                options = {
                    "codex": args.codex,
                    "model": args.model,
                    "reasoning": args.reasoning,
                    "execution_policy": _read(args.policy),
                    "output_dir": args.output,
                    "resume": args.resume,
                    "resume_receipt": _read(args.replay_receipt)
                    if args.replay_receipt
                    else None,
                }
                if args.command == "judge":
                    result = run_stage2_judges(
                        packet,
                        args.source_root,
                        args.subject_id,
                        args.input_sha256,
                        args.config_sha256,
                        _read(args.actions),
                        r1_home=args.r1_home,
                        r2_home=args.r2_home,
                        adj_home=args.adj_home,
                        **options,
                    )
                else:
                    options["evaluator_home"] = args.evaluator_home
                    if args.command == "extract":
                        raw = Path(args.raw_proposal).read_bytes().decode("utf-8")
                        result = run_live_extraction(
                            raw,
                            packet,
                            args.source_root,
                            args.snapshot_sha256,
                            **options,
                        )
                    elif args.command == "extract-review":
                        result = extract_review(
                            packet,
                            args.source_root,
                            args.candidate,
                            args.snapshot_sha256,
                            args.role,
                            args.capture,
                            args.receipt,
                            **options,
                        )
                    else:
                        result = extract_resolution(
                            packet,
                            args.source_root,
                            args.candidate,
                            args.snapshot_sha256,
                            _read(args.reviews),
                            args.capture,
                            args.receipt,
                            **options,
                        )
                if args.replay_receipt_output and "replay_receipt" in result:
                    _save(args.replay_receipt_output, result["replay_receipt"])
        print(json.dumps(result, ensure_ascii=False))
        return (
            2
            if result.get("status")
            in {
                "failed",
                "incomplete",
                "evaluator-failure",
                "blocked",
                "unresolved",
                "needs-workspace",
                "needs-recovery",
                "follow-up-needed",
            }
            else 0
        )
    except (
        OSError,
        UnicodeError,
        ValueError,
        KeyError,
        TypeError,
        Stage2Error,
        EvaluationError,
    ) as error:
        print(
            json.dumps({"status": "failed", "error": str(error)}, ensure_ascii=False),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
