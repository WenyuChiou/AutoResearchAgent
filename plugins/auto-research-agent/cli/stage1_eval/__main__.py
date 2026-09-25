"""Run the independent Stage 1 rubric-evidence evaluation path."""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from .adapter import (
    adapt_subject,
    extract_subject,
    reuse_saved_extraction,
    validate_extraction,
)
from .collector import (
    collect_background,
    collect_subject_sources,
    rebuild_background_sources,
    rebuild_subject_sources,
)
from .formal import attach_workspace, bind_capture, verify_hub_receipts
from .common import (
    EVAL_ROOT,
    EvaluationError,
    canonical,
    check_spec,
    read_json,
    sha,
    validate_schema,
    write_json,
)
from .judging import judge_packet, make_packet
from .requirements import finalize_saved_spec, prepare_spec
from .runtime import (
    executable_sha256,
    installed_package_sha256,
)
from .score import aggregate

ROOT = Path(__file__).resolve().parent


def _model_options(args):
    return {
        "codex": args.codex,
        "evaluator_home": args.evaluator_home,
        "model": args.model,
        "reasoning": args.reasoning,
    }


def _hub_command(args):
    if args.hub_command_json:
        command = json.loads(args.hub_command_json)
        if (
            not isinstance(command, list)
            or not command
            or not all(isinstance(part, str) and part for part in command)
        ):
            raise EvaluationError("hub command must be a nonempty JSON string array")
        return command
    if not args.hub:
        raise EvaluationError("provide --hub or --hub-command-json")
    return [args.hub]


def _code_sha():
    raw = b"".join(
        path.name.encode() + b"\0" + path.read_bytes()
        for path in sorted(ROOT.glob("*.py"))
    )
    return sha(raw)


def _evaluator_bundle_sha():
    files = sorted(ROOT.glob("*.py")) + sorted(
        (EVAL_ROOT / "schemas").glob("*v3.schema.json")
    )
    files.append(EVAL_ROOT / "rubrics/stage1-general.v3.json")
    raw = b"".join(
        path.relative_to(EVAL_ROOT.parent).as_posix().encode("utf-8")
        + b"\0"
        + sha(path.read_bytes()).encode("ascii")
        + b"\n"
        for path in files
    )
    return sha(raw)


def _costs(output, background, source_result, started):
    usage = []
    for path in output.rglob("*.jsonl"):
        for raw in path.read_bytes().splitlines():
            try:
                event = json.loads(raw)
            except ValueError:
                continue
            if event.get("type") == "turn.completed" and isinstance(
                event.get("usage"), dict
            ):
                usage.append(event["usage"])
    fields = (
        "input_tokens",
        "cached_input_tokens",
        "output_tokens",
        "reasoning_output_tokens",
    )
    receipts = [*(background or {}).get("receipts", []), *source_result["receipts"]]
    return {
        "evaluator_model_completed_turns": len(usage),
        "evaluator_tokens": {
            key: sum(row.get(key, 0) for row in usage) if usage else None
            for key in fields
        },
        "source_acquisition_calls": len(receipts),
        "source_acquisition_failures": sum(
            row["status"] not in {"results", "zero-results"} for row in receipts
        ),
        "evaluator_elapsed_seconds_this_attempt": round(
            (datetime.now(started.tzinfo) - started).total_seconds(), 3
        ),
        "subject_tokens": None,
        "currency_cost": None,
    }


def _verify_background(background, path, spec):
    if background.get("kind") != "Stage1BackgroundEvidence" or background.get(
        "spec_sha256"
    ) != sha(canonical(spec)):
        raise EvaluationError("background does not match frozen topic spec")
    root = Path(path).resolve().parent / "raw"
    for row in background["receipts"]:
        for kind in ("stdout", "stderr"):
            filename = row[kind + "_path"]
            target = (root / filename).resolve()
            if (
                not target.is_relative_to(root.resolve())
                or not target.is_file()
                or sha(target.read_bytes()) != row[kind + "_sha256"]
            ):
                raise EvaluationError("background raw search receipt changed")
    if canonical(
        rebuild_background_sources(spec, background["receipts"], root)
    ) != canonical(background["sources"]):
        raise EvaluationError("background sources differ from raw search receipts")


def _verify_source_receipts(source_result, output, extraction, spec):
    root = (output / "source-acquisition" / "raw").resolve()
    for row in source_result["receipts"]:
        for kind in ("stdout", "stderr"):
            target = (root / row[kind + "_path"]).resolve()
            if (
                not target.is_relative_to(root)
                or not target.is_file()
                or sha(target.read_bytes()) != row[kind + "_sha256"]
            ):
                raise EvaluationError("subject source raw receipt changed")
    if canonical(
        rebuild_subject_sources(extraction, spec, source_result["receipts"], root)
    ) != canonical(source_result["sources"]):
        raise EvaluationError("subject sources differ from raw enrich receipts")


def evaluate(args):
    started = datetime.now().astimezone()
    output = Path(args.output).resolve()
    if args.execution_class == "formal" and (
        not getattr(args, "lock", None) or not getattr(args, "capture", None)
    ):
        raise EvaluationError("formal v3 requires pre-subject lock and native capture")
    if args.resume_pilot and args.execution_class != "exploratory-pilot":
        raise EvaluationError(
            "saved-call resume is permitted only for exploratory pilots"
        )
    if output.exists() and not args.resume_pilot:
        raise EvaluationError("evaluation output already exists")
    if args.resume_pilot and not output.is_dir():
        raise EvaluationError("pilot resume directory does not exist")
    formal_binding = None
    if args.execution_class == "formal":
        spec_for_binding = read_json(args.spec)
        check_spec(spec_for_binding)
        formal_binding = bind_capture(args, spec_for_binding, _evaluator_bundle_sha())
    output.mkdir(parents=True, exist_ok=True)
    try:
        spec = read_json(args.spec)
        check_spec(spec)
        codex_hash = executable_sha256(args.codex)
        hub_hash = installed_package_sha256("research_hub")
        task_path = Path(args.task)
        if sha(task_path.read_bytes()) != spec["task_sha256"]:
            raise EvaluationError("task differs from frozen topic spec")
        if Path(args.answer).resolve().is_relative_to(output):
            raise EvaluationError("subject answer cannot be an evaluator-produced file")
        subject = adapt_subject(
            args.answer,
            args.transcript,
            args.artifact,
            status=args.subject_status,
            max_trace_bytes=2_000_000 if formal_binding else 200_000,
        )
        if formal_binding:
            attach_workspace(subject, formal_binding)
        if args.resume_pilot:
            if canonical(read_json(output / "subject-observation.json")) != canonical(
                subject
            ):
                raise EvaluationError("resumed subject observation changed")
            extraction = validate_extraction(
                read_json(output / "subject-extraction.json"), subject
            )
            extraction_meta = read_json(output / "extraction-provenance.json")
        elif args.saved_extraction:
            write_json(output / "subject-observation.json", subject)
            extraction, extraction_meta = reuse_saved_extraction(
                subject, args.saved_extraction
            )
        else:
            write_json(output / "subject-observation.json", subject)
            extraction, extraction_meta = extract_subject(
                subject, output / "model-logs", _model_options(args)
            )
        if not args.resume_pilot:
            write_json(output / "subject-extraction.json", extraction)
            write_json(output / "extraction-provenance.json", extraction_meta)
        background = None
        if args.mode == "evidence-audited":
            if not args.background or not args.background_sha256:
                raise EvaluationError(
                    "evidence-audited mode needs immutable background path and SHA"
                )
            if sha(Path(args.background).read_bytes()) != args.background_sha256:
                raise EvaluationError("background bytes changed")
            background = read_json(args.background)
            _verify_background(background, args.background, spec)
            if formal_binding:
                verify_hub_receipts(background["receipts"], formal_binding)
        if args.resume_pilot:
            source_result = read_json(output / "subject-sources.json")
        else:
            source_result = collect_subject_sources(
                extraction, spec, output / "source-acquisition", _hub_command(args)
            )
            write_json(output / "subject-sources.json", source_result)
        _verify_source_receipts(source_result, output, extraction, spec)
        if formal_binding:
            verify_hub_receipts(source_result["receipts"], formal_binding)
        packet = make_packet(
            task_path.read_text(encoding="utf-8"),
            spec,
            subject,
            extraction,
            background,
            source_result,
            mode=args.mode,
        )
        if args.resume_pilot:
            if canonical(read_json(output / "evidence-packet.json")) != canonical(
                packet
            ):
                raise EvaluationError("resumed evidence packet changed")
        else:
            write_json(output / "evidence-packet.json", packet)
        judgment = judge_packet(
            packet,
            output / "judging",
            _model_options(args),
            reuse_completed=args.resume_pilot,
        )
        write_json(output / "judgments.json", judgment)
        result = aggregate(
            packet,
            judgment,
            evaluator_identity={
                "model": args.model,
                "reasoning": args.reasoning,
                "evaluator_code_sha256": _code_sha(),
                "evaluator_bundle_sha256": _evaluator_bundle_sha(),
                "codex_executable_sha256": codex_hash,
                "research_hub_package_sha256": hub_hash,
                "research_hub_commit": None,
            },
            costs=_costs(output, background, source_result, started),
        )
        if formal_binding:
            result["formal_capture"] = {
                key: value
                for key, value in formal_binding.items()
                if key
                not in {
                    "snapshot_path",
                    "research_hub_commit",
                    "codex_runtime_sha256",
                    "hub_command_prefix",
                    "hub_executable_sha256",
                    "research_hub_package_sha256",
                }
            }
            result["evaluator_identity"]["research_hub_commit"] = formal_binding[
                "research_hub_commit"
            ]
            result["evaluator_identity"]["codex_runtime_sha256"] = formal_binding[
                "codex_runtime_sha256"
            ]
        validate_schema(result, "stage-evaluation-result.v3.schema.json")
        write_json(output / "result.json", result)
        lines = [
            "# Stage 1 general rubric evaluation",
            f"Topic: {spec['draft']['question']}",
            f"Mode: {args.mode}; status: {result['scientific_readiness_status']}",
            "This is bounded source-grounded adequacy, not gold-paper recall or a formal A/B result.",
            "",
        ]
        for metric in ("P1", "P2", "P3"):
            item = result["dimensions"][metric]
            lines.append(
                f"- {metric} {item['name']}: observed {item['observed_score_100']}; "
                f"assessed {item['scored_count']}/{item['applicable_count']}; "
                f"bounds {item['lower_bound_100']}–{item['upper_bound_100']}; "
                f"confirmed major issues {len(item['confirmed_major_issue_ids'])}"
            )
        (output / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
        return result
    except Exception as exc:
        failure_path = output / "evaluation-failure.json"
        if args.resume_pilot:
            index = 1
            while (output / f"evaluation-failure-resume-{index}.json").exists():
                index += 1
            failure_path = output / f"evaluation-failure-resume-{index}.json"
        write_json(
            failure_path,
            {
                "kind": "EvaluationFailure",
                "schema_version": "3.0.0",
                "failure_type": "evaluator-error",
                "error": type(exc).__name__,
                "message": str(exc),
                "note": "This is not a zero score for the subject. Preserve partial artifacts for diagnosis.",
            },
        )
        raise


def parser():
    root = argparse.ArgumentParser(description=__doc__)
    sub = root.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare-spec")
    prep.add_argument("task")
    prep.add_argument("as_of")
    prep.add_argument("output")
    prep.add_argument("--backend", choices=["openalex", "crossref"], default="openalex")
    recover = sub.add_parser("finalize-saved-spec")
    recover.add_argument("task")
    recover.add_argument("as_of")
    recover.add_argument("saved_draft")
    recover.add_argument("output")
    recover.add_argument("--model", required=True)
    recover.add_argument("--reasoning", required=True)
    background = sub.add_parser("collect-background")
    background.add_argument("spec")
    background.add_argument("output")
    run = sub.add_parser("evaluate")
    for flag in ("task", "spec", "answer", "output"):
        run.add_argument(flag)
    run.add_argument("--transcript")
    run.add_argument("--lock")
    run.add_argument("--capture")
    run.add_argument("--saved-extraction")
    run.add_argument("--resume-pilot", action="store_true")
    run.add_argument("--artifact", action="append", default=[])
    run.add_argument(
        "--subject-status",
        choices=["complete", "partial", "failed"],
        default="complete",
    )
    run.add_argument(
        "--execution-class",
        choices=["exploratory-pilot", "formal"],
        default="exploratory-pilot",
    )
    run.add_argument(
        "--mode", choices=["packet-only", "evidence-audited"], required=True
    )
    run.add_argument("--background")
    run.add_argument("--background-sha256")
    for command in (prep, run):
        command.add_argument("--codex", required=True)
        command.add_argument("--evaluator-home", required=True)
        command.add_argument("--model", required=True)
        command.add_argument(
            "--reasoning",
            choices=["low", "medium", "high", "xhigh", "max", "ultra"],
            required=True,
        )
    for command in (background, run):
        command.add_argument("--hub")
        command.add_argument("--hub-command-json")
    return root


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if args.command == "prepare-spec":
            result = prepare_spec(
                args.task,
                args.as_of,
                args.output,
                _model_options(args),
                backend=args.backend,
            )
        elif args.command == "finalize-saved-spec":
            result = finalize_saved_spec(
                args.task,
                args.as_of,
                args.saved_draft,
                args.output,
                model=args.model,
                reasoning=args.reasoning,
            )
        elif args.command == "collect-background":
            spec = read_json(args.spec)
            check_spec(spec)
            result = collect_background(spec, args.output, _hub_command(args))
        else:
            result = evaluate(args)
    except (EvaluationError, OSError, ValueError) as exc:
        print(f"stage1-eval: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
