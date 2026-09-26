"""Versioned extraction, public sources and independently replayable judging."""

import json
from datetime import datetime, timezone
from pathlib import Path

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
from .extraction_v31 import extract_subject_v31
from .judging import make_packet
from .judging_v31 import judge_packet_v31
from .runtime import executable_sha256, installed_package_sha256
from .score import aggregate
from .sources_v31 import attach_public_sources, collect_sources_v31


def bundle_sha_v31():
    from .formal import capture_module_binding

    root = EVAL_ROOT.parent
    files = sorted((root / "cli/stage1_eval").glob("*.py"))
    files += sorted((EVAL_ROOT / "schemas").glob("*v3*.schema.json"))
    files += [
        EVAL_ROOT / "rubrics/stage1-general.v3.json",
        EVAL_ROOT / "stage1/execution-policy.v3_1.json",
    ]
    return sha(
        canonical(
            [
                {"path": p.relative_to(root).as_posix(), "sha256": sha(p.read_bytes())}
                for p in files
            ]
            + [capture_module_binding()]
        )
    )


def execution_policy():
    value = read_json(EVAL_ROOT / "stage1/execution-policy.v3_1.json")
    value["evaluator_bundle_sha256"] = bundle_sha_v31()
    return value


def persist(path, value, *, replay_only=False):
    if path.exists():
        if canonical(read_json(path)) != canonical(value):
            raise EvaluationError("saved evaluator artifact changed: " + path.name)
    elif replay_only:
        raise EvaluationError("missing evaluator artifact: " + path.name)
    else:
        write_json(path, value)


def persist_bytes(path, raw, *, replay_only=False):
    if path.exists():
        if path.read_bytes() != raw:
            raise EvaluationError("saved evaluator input changed: " + path.name)
    elif replay_only:
        raise EvaluationError("missing evaluator input: " + path.name)
    else:
        path.write_bytes(raw)


def model_costs(root):
    """Count each native attempt once; compatibility exports are not extra calls."""
    usage, attempts, missing = [], 0, 0
    for archive in root.rglob("*.model-call"):
        for path in sorted(archive.glob("attempt-*.record.json")):
            attempts += 1
            record = read_json(path)
            events = []
            for line in (
                (archive / record["files"]["stdout"]["path"]).read_bytes().splitlines()
            ):
                try:
                    events.append(json.loads(line))
                except ValueError:
                    continue
            completed = [
                e["usage"]
                for e in events
                if e.get("type") == "turn.completed"
                and isinstance(e.get("usage"), dict)
            ]
            missing += not bool(completed)
            usage.extend(completed)
    return {
        "attempts": attempts,
        "attempts_without_usage": missing,
        "completed_turns_with_usage": len(usage),
        "tokens": {
            k: sum(u[k] for u in usage)
            if usage and not missing and all(k in u for u in usage)
            else None
            for k in (
                "input_tokens",
                "cached_input_tokens",
                "output_tokens",
                "reasoning_output_tokens",
            )
        },
        "observed_token_subtotals": {
            k: sum(u[k] for u in usage if k in u)
            if any(k in u for u in usage)
            else None
            for k in (
                "input_tokens",
                "cached_input_tokens",
                "output_tokens",
                "reasoning_output_tokens",
            )
        },
        "currency_cost": None,
    }


def evaluate_v31(args, *, replay_only=False):
    from .__main__ import _verify_background
    from .formal import observe_capture_v31, verify_binding_v31, verify_hub_receipts
    from .model_calls import _request_config

    output = Path(args.output).resolve()
    if output.exists() and not (args.resume_verified or replay_only):
        raise EvaluationError("v3.1 output exists; verified resume must be explicit")
    if replay_only and not output.is_dir():
        raise EvaluationError("missing evaluation archive")
    output.mkdir(parents=True, exist_ok=True)
    started = datetime.now(timezone.utc)
    spec = read_json(args.spec)
    check_spec(spec)
    task = Path(args.task).read_bytes()
    if sha(task) != spec["task_sha256"]:
        raise EvaluationError("task does not match frozen spec")
    if args.hub or json.loads(args.hub_command_json or "null") != [
        "@python",
        "-m",
        "research_hub",
    ]:
        raise EvaluationError(
            "v3.1 source acquisition needs its separately pinned Python package"
        )
    if args.artifact or args.saved_extraction or args.resume_pilot:
        raise EvaluationError(
            "v3.1 derives inputs from complete captures and verified units"
        )
    policy = execution_policy()
    if (
        getattr(args, "portable_diagnostic", False)
        and args.execution_class != "repair-diagnostic"
    ):
        raise EvaluationError("portable replay is diagnostic only")
    subject, record = observe_capture_v31(
        args.capture, portable=getattr(args, "portable_diagnostic", False)
    )
    binding = verify_binding_v31(args, spec, record, policy)
    identity = {
        "model": args.model,
        "reasoning": args.reasoning,
        "evaluator_code_sha256": bundle_sha_v31(),
        "evaluator_bundle_sha256": bundle_sha_v31(),
        "codex_executable_sha256": executable_sha256(args.codex),
        "research_hub_package_sha256": installed_package_sha256("research_hub"),
        "research_hub_commit": binding.get("evaluator_research_hub_sha"),
    }
    if "codex_runtime_sha256" in binding:
        identity["codex_runtime_sha256"] = binding["codex_runtime_sha256"]
    run_input = {
        "schema_version": "3.1.0",
        "execution_class": args.execution_class,
        "task_sha256": sha(task),
        "spec_sha256": sha(canonical(spec)),
        "capture_run_sha256": sha((Path(args.capture) / "run.json").read_bytes()),
        "policy": policy,
        "identity": identity,
        "binding": binding,
        "model_config": _request_config(
            args.codex, args.evaluator_home, args.model, args.reasoning
        ),
        "mode": args.mode,
    }
    persist(output / "evaluation-input.json", run_input, replay_only=replay_only)
    persist_bytes(output / "task.txt", task, replay_only=replay_only)
    persist(output / "spec.json", spec, replay_only=replay_only)
    attempt_number = len(list(output.glob("evaluation-attempt-*.json"))) + 1
    status = {
        "status": "evaluator-error",
        "message": "Evaluation did not reach completion.",
    }
    try:
        persist(output / "subject-observation.json", subject, replay_only=replay_only)
        options = {
            "codex": args.codex,
            "evaluator_home": args.evaluator_home,
            "model": args.model,
            "reasoning": args.reasoning,
            "execution_policy": policy,
        }
        extraction, provenance = extract_subject_v31(
            subject, output / "extraction", options, replay_only=replay_only
        )
        provenance.pop("replay_only", None)
        persist(output / "subject-extraction.json", extraction, replay_only=replay_only)
        persist(
            output / "extraction-provenance.json", provenance, replay_only=replay_only
        )
        background = None
        if args.mode == "evidence-audited":
            if (
                not args.background
                or sha(Path(args.background).read_bytes()) != args.background_sha256
            ):
                raise EvaluationError("background is missing or changed")
            background = read_json(args.background)
            _verify_background(background, args.background, spec)
        sources = collect_sources_v31(
            extraction,
            spec,
            output / "sources",
            ["@python", "-m", "research_hub"],
            replay_only=replay_only,
        )
        if args.execution_class != "repair-diagnostic":
            verify_hub_receipts(sources["receipts"], binding)
            verify_hub_receipts(
                [r["receipt"] for r in sources["public_fetches"] if "receipt" in r],
                binding,
            )
        persist(output / "subject-sources.json", sources, replay_only=replay_only)
        packet = make_packet(
            task.decode("utf-8"),
            spec,
            subject,
            extraction,
            background,
            sources,
            mode=args.mode,
        )
        # v3.1 keeps every attempt; IDs are no longer the legacy trace-N form.
        evidence = subject["evidence"].values()
        packet["process_evidence"]["capture-integrity"] = {
            "text": (
                f"Subject status: {subject['status']}; native trace events: "
                f"{sum(v['origin'] == 'subject-native-trace' for v in evidence)}; "
                "delivered artifacts: "
                f"{sum(v['origin'] == 'subject-delivered-artifact' for v in evidence)}"
            ),
            "origin": "evaluator-mechanical-inventory",
            "sha256": sha(canonical(subject)),
        }
        attach_public_sources(packet, sources)
        persist(output / "evidence-packet.json", packet, replay_only=replay_only)
        judgments = judge_packet_v31(
            packet, output / "judging", options, replay_only=replay_only
        )
        persist(output / "judgments.json", judgments, replay_only=replay_only)
        costs = model_costs(output)
        result = aggregate(packet, judgments, evaluator_identity=identity)
        result.update(
            schema_version="3.1.0",
            evaluator_version="3.1.0",
            execution_class=args.execution_class,
            evaluation_input_sha256=sha(canonical(run_input)),
        )
        if args.execution_class == "formal":
            result["formal_capture"] = binding
        result["costs"]["evaluator_tokens"] = costs["tokens"]
        result["costs"]["evaluator_model_completed_turns"] = costs[
            "completed_turns_with_usage"
        ]
        result["costs"]["source_acquisition_calls"] = len(sources["receipts"]) + sum(
            "receipt" in r for r in sources["public_fetches"]
        )
        result["costs"]["source_acquisition_failures"] = sum(
            r.get("status") not in {"results", "zero-results"}
            for r in sources["receipts"]
        ) + sum(
            not r.get("result") or r["result"].get("status") != "available"
            for r in sources["public_fetches"]
        )
        # A completed result is immutable across replay; timestamps are not scores.
        target = output / "result.json"
        if target.exists():
            previous = read_json(target)
            result["created_at"] = previous["created_at"]
        validate_schema(result, "stage-evaluation-result.v3_1.schema.json")
        persist(target, result, replay_only=replay_only)
        persist(output / "model-costs.json", costs, replay_only=replay_only)
        status = {"status": "complete", "result_sha256": sha(target.read_bytes())}
        return result
    except Exception as exc:
        status = {
            "status": "evaluator-error",
            "error": type(exc).__name__,
            "message": str(exc),
            "note": "No subject zero is assigned; all previous attempts remain.",
        }
        raise
    finally:
        if not replay_only:
            persist(
                output / f"evaluation-attempt-{attempt_number:03d}.json",
                {
                    **status,
                    "started_at": started.isoformat(),
                    "ended_at": datetime.now(timezone.utc).isoformat(),
                },
            )
