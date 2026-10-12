"""Explicit native calls and extraction, without a second workflow scheduler."""

import argparse
import json
from pathlib import Path
import sys

from stage1_eval.common import EvaluationError
from stage2_check.contracts import decode_json
from stage2_common import Stage2Error, validate_packet
from stage2_ideation import build_research_task
from stage2_workflow.reviews import REVIEW_VIEW_VERSIONS

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


def _assessment_target_options(path):
    if path is None:
        return {}
    binding = _read(path)
    if not isinstance(binding, dict):
        raise EvaluationError("assessment target policy must be a JSON object")
    return {"assessment_target_policy": binding}


def _save(path, value):
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m stage2_live")
    commands = parser.add_subparsers(dest="command", required=True)
    observe = commands.add_parser(
        "observe-runtime", help="private app-server snapshot; no model turn or A/B"
    )
    for option in ("codex", "codex-home", "workspace", "output", "receipt-output"):
        observe.add_argument("--" + option, required=True)
    observe.add_argument("--thread-id")
    observation_check = commands.add_parser(
        "verify-observation", help="read-only verification of a runtime snapshot"
    )
    observation_check.add_argument("--directory", required=True)
    observation_check.add_argument("--receipt", required=True)
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
    control_check.add_argument("--evaluation")
    control_check.add_argument("--expected-evaluation-manifest-sha256")
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
    daily_v3 = commands.add_parser(
        "daily-v3", help="run ordinary B-only Stage 2 v3 independent scoring"
    )
    for option in (
        "selection",
        "source-root",
        "codex",
        "r1-home",
        "r2-home",
        "adj-home",
        "model",
        "reasoning",
        "policy",
        "output",
        "replay-receipt-output",
    ):
        daily_v3.add_argument("--" + option, required=True)
    daily_v3.add_argument("--audit")
    daily_v3.add_argument("--source-context-policy")
    daily_v3.add_argument(
        "--assessment-target-policy",
        help="JSON file containing the host-frozen binding; no score or default change",
    )
    daily_v3.add_argument("--resume", action="store_true")
    daily_v3.add_argument("--replay-receipt")
    finalize_daily_v3 = commands.add_parser(
        "finalize-daily-v3", help="append a named audit to an audit-required v3 run"
    )
    for option in (
        "bundle",
        "selection",
        "source-root",
        "audit",
        "expected-bundle-sha256",
        "output",
    ):
        finalize_daily_v3.add_argument("--" + option, required=True)
    finalize_daily_v3.add_argument("--parent-replay-receipt")
    quality_v3 = commands.add_parser(
        "calibrate-v3", help="run the fixed 72-presentation Stage 2 v3 calibration"
    )
    for option in (
        "dataset",
        "reference",
        "codex",
        "r1-home",
        "r2-home",
        "model",
        "reasoning",
        "policy",
        "output",
    ):
        quality_v3.add_argument("--" + option, required=True)
    source_update = commands.add_parser(
        "source-update", help="prepare an immutable review-required source update"
    )
    for option in (
        "packet",
        "source-root",
        "additions",
        "revisions",
        "impact",
        "output",
        "expected-packet-sha256",
    ):
        source_update.add_argument("--" + option, required=True)
    source_update.add_argument("--unresolved")
    revision_input = commands.add_parser(
        "prepare-content-revision-input",
        help="bind exact new excerpts from existing source bytes",
    )
    for option in ("packet", "source-root", "additions", "output"):
        revision_input.add_argument("--" + option, required=True)
    content_revision = commands.add_parser(
        "content-revision",
        help="authenticate a source-free content revision snapshot",
    )
    for option in (
        "run",
        "expected-head",
        "extraction-root",
        "extraction-receipt",
        "source-root",
        "impact",
        "output",
    ):
        content_revision.add_argument("--" + option, required=True)
    profile = commands.add_parser(
        "prepare-profile", help="prepare a new profile from native skill discovery"
    )
    profile.add_argument("--destination", required=True)
    profile.add_argument("--skills-response", required=True)
    profile.add_argument("--skills-sha256", required=True)
    profile.add_argument("--output", required=True)
    profile.add_argument("--workspace")
    quality_check_v3 = commands.add_parser(
        "verify-quality-v3", help="read-only replay of a native v3 calibration"
    )
    context_quality_v3 = commands.add_parser(
        "calibrate-context-v3", help="native blinded supplemental 12-case calibration"
    )
    for option in (
        "dataset",
        "reference",
        "codex",
        "r1-home",
        "r2-home",
        "model",
        "reasoning",
        "policy",
        "output",
        "replay-receipt-output",
    ):
        context_quality_v3.add_argument("--" + option, required=True)
    context_quality_v3.add_argument("--resume", action="store_true")
    context_quality_v3.add_argument("--resume-receipt")
    for option in ("root", "receipt", "dataset", "reference", "config", "output"):
        quality_check_v3.add_argument("--" + option, required=True)
    daily_check_v3 = commands.add_parser(
        "verify-daily-v3", help="read-only replay of a native v3 daily run"
    )
    for option in (
        "run-dir",
        "receipt",
        "selection",
        "source-root",
        "config",
        "output",
    ):
        daily_check_v3.add_argument("--" + option, required=True)
    daily_check_v3.add_argument("--source-context-policy")
    daily_check_v3.add_argument(
        "--assessment-target-policy",
        help="JSON file containing the host-frozen binding; no score or default change",
    )
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
        if name in {"review-task", "reconciliation-task"}:
            task.add_argument(
                "--review-view-version",
                choices=REVIEW_VIEW_VERSIONS,
                default="1.0.0",
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
            call.add_argument(
                "--update-mode",
                choices=["append", "replace-comparison-unresolved"],
                default="append",
            )
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
            call.add_argument(
                "--review-view-version",
                choices=REVIEW_VIEW_VERSIONS,
                default="1.0.0",
            )
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
        if args.command == "observe-runtime":
            from .observation import collect_runtime_observation

            if Path(args.receipt_output).exists():
                raise CaptureError("observation receipt output already exists")
            for protected in (args.output, args.codex_home, args.workspace):
                if (
                    Path(args.receipt_output)
                    .resolve()
                    .is_relative_to(Path(protected).resolve())
                ):
                    raise CaptureError(
                        "observation receipt must be outside archive/profile/workspace"
                    )
            result = collect_runtime_observation(
                codex=args.codex,
                codex_home=args.codex_home,
                workspace=args.workspace,
                output_dir=args.output,
                thread_id=args.thread_id,
            )
            _save(
                args.receipt_output,
                {"record_sha256_receipt": result["record_sha256_receipt"]},
            )
            result = {
                k: result[k]
                for k in (
                    "kind",
                    "status",
                    "record_sha256_receipt",
                    "model_turns_dispatched",
                    "offered_tool_inventory",
                    "formal_ready",
                )
            }
        elif args.command == "verify-observation":
            from .observation import verify_runtime_observation

            verified = verify_runtime_observation(args.directory, args.receipt)
            result = {k: verified[k] for k in ("kind", "status", "formal_ready")}
        elif args.command in {"controller", "verify-controller"}:
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
                verified = verify_controller(
                    args.controller_root,
                    args.receipt,
                    evaluation_dir=args.evaluation,
                    expected_evaluation_manifest_sha256=args.expected_evaluation_manifest_sha256,
                )
                # Internal inspection state contains Path objects and full source
                # packets. Emit the explicit public receipt/status projection.
                result = {
                    key: verified[key]
                    for key in (
                        "kind",
                        "schema_version",
                        "manifest",
                        "completion",
                        "authentic_native_execution",
                        "synthetic_test_only",
                        "selection_ready",
                        "stage2_complete",
                        "model_call_verification",
                        "model_call_blockers",
                        "pilot_executable",
                        "formal_ready",
                        "formal_readiness_blocker",
                    )
                }
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
        elif args.command == "daily-v3":
            from .daily_v3 import run_daily_evaluation_v3

            if args.resume != bool(args.replay_receipt):
                raise EvaluationError(
                    "daily-v3 resume and replay receipt must be supplied together"
                )
            receipt_output = Path(args.replay_receipt_output).resolve()
            if receipt_output.exists():
                raise EvaluationError("replay receipt output already exists")
            if receipt_output.is_relative_to(Path(args.output).resolve()):
                raise EvaluationError("replay receipt must remain outside daily output")
            result = run_daily_evaluation_v3(
                _read(args.selection),
                args.source_root,
                codex=args.codex,
                r1_home=args.r1_home,
                r2_home=args.r2_home,
                adj_home=args.adj_home,
                model=args.model,
                reasoning=args.reasoning,
                execution_policy=_read(args.policy),
                output_dir=args.output,
                resume=args.resume,
                resume_receipt=(
                    _read(args.replay_receipt) if args.replay_receipt else None
                ),
                audit=_read(args.audit) if args.audit else None,
                source_context_policy=(
                    _read(args.source_context_policy)
                    if args.source_context_policy
                    else None
                ),
                **_assessment_target_options(args.assessment_target_policy),
            )
            _save(args.replay_receipt_output, result["replay_receipt"])
        elif args.command == "finalize-daily-v3":
            from .daily_v3 import finalize_daily_evaluation_v3

            result = finalize_daily_evaluation_v3(
                _read(args.bundle),
                _read(args.selection),
                args.source_root,
                _read(args.audit),
                args.output,
                expected_bundle_sha256=args.expected_bundle_sha256,
                parent_replay_receipt=(
                    _read(args.parent_replay_receipt)
                    if args.parent_replay_receipt
                    else None
                ),
            )
        elif args.command == "calibrate-v3":
            from .rubric_quality_v3 import run_quality_v3

            result = run_quality_v3(
                _read(args.dataset),
                _read(args.reference),
                codex=args.codex,
                r1_home=args.r1_home,
                r2_home=args.r2_home,
                model=args.model,
                reasoning=args.reasoning,
                execution_policy=_read(args.policy),
                output_dir=args.output,
            )
        elif args.command == "calibrate-context-v3":
            from .context_quality_v3 import run_context_quality_v3

            receipt = Path(args.replay_receipt_output).resolve()
            roots = [
                Path(p).resolve() for p in (args.output, args.r1_home, args.r2_home)
            ]
            if receipt.exists() or any(
                receipt == root or root in receipt.parents or receipt in root.parents
                for root in roots
            ):
                raise EvaluationError("new external replay receipt path required")
            if args.resume != bool(args.resume_receipt):
                raise EvaluationError("resume requires its external replay receipt")
            result = run_context_quality_v3(
                _read(args.dataset),
                _read(args.reference),
                codex=args.codex,
                r1_home=args.r1_home,
                r2_home=args.r2_home,
                model=args.model,
                reasoning=args.reasoning,
                execution_policy=_read(args.policy),
                output_dir=args.output,
                resume=args.resume,
                resume_receipt=_read(args.resume_receipt)
                if args.resume_receipt
                else None,
            )
            _save(receipt, result["replay_receipt"])
        elif args.command == "source-update":
            from .source_updates import prepare_source_update

            result = prepare_source_update(
                _read(args.packet),
                args.source_root,
                _read(args.additions),
                _read(args.revisions),
                _read(args.impact),
                args.output,
                expected_packet_sha256=args.expected_packet_sha256,
                unresolved=_read(args.unresolved) if args.unresolved else None,
            )
        elif args.command == "prepare-content-revision-input":
            from .content_revision import prepare_content_revision_input

            result = prepare_content_revision_input(
                _read(args.packet),
                args.source_root,
                _read(args.additions),
                args.output,
            )
        elif args.command == "content-revision":
            from .content_revision import prepare_content_revision

            result = prepare_content_revision(
                args.run,
                args.expected_head,
                args.extraction_root,
                args.extraction_receipt,
                args.source_root,
                _read(args.impact),
                args.output,
            )
        elif args.command == "verify-quality-v3":
            from .v3_replay import verify_quality_v3

            result = verify_quality_v3(
                args.root,
                _read(args.receipt),
                dataset=_read(args.dataset),
                reference=_read(args.reference),
                expected_config=_read(args.config),
            )
            _save(args.output, result)
        elif args.command == "verify-daily-v3":
            from .daily_replay_v3 import verify_daily_v3

            result = verify_daily_v3(
                args.run_dir,
                _read(args.receipt),
                selection=_read(args.selection),
                source_root=args.source_root,
                expected_config=_read(args.config),
                source_context_policy=(
                    _read(args.source_context_policy)
                    if args.source_context_policy
                    else None
                ),
                **_assessment_target_options(args.assessment_target_policy),
            )
            _save(args.output, result)
        elif args.command in {"prepare-profile", "preflight"}:
            if Path(args.output).exists():
                raise CaptureError("output already exists")
            if args.command == "prepare-profile":
                if args.workspace:
                    result = prepare_profile(
                        args.destination,
                        args.skills_response,
                        args.skills_sha256,
                        workspace=args.workspace,
                    )
                else:
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
                "timeout_seconds",
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
                        packet,
                        args.candidate,
                        args.snapshot_sha256,
                        args.role,
                        review_view_version=args.review_view_version,
                    )
                else:
                    result = reconciliation_task(
                        packet,
                        args.candidate,
                        args.snapshot_sha256,
                        _read(args.reviews),
                        review_view_version=args.review_view_version,
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
                        if args.update_mode != "append":
                            options["update_mode"] = args.update_mode
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
                            review_view_version=args.review_view_version,
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
                            review_view_version=args.review_view_version,
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
