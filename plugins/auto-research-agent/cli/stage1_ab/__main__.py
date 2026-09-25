"""Controlled Stage 1 A/B freeze, subject capture, judging, and export."""

import argparse
import json
from pathlib import Path
import statistics
import subprocess
import sys

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from stage1_ab import facts, judging, packet, runner
else:
    from . import facts, judging, packet, runner

from validators.judge_bundle import validate_bundle
from validators.paired_evaluation import evaluate_request
from validators.stage1_evaluation_result_v2 import validate_result_v2
from stage1_export.bundle import export_run, validate_export


def parser_for_commands():
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest="command", required=True)
    p = subs.add_parser("freeze")
    for name in ("plan", "prompt", "dependency_repo", "output"):
        p.add_argument(name, type=Path)
    p.add_argument("--treatment-runtime-pin", type=Path, action="append", required=True)
    p = subs.add_parser("probe")
    for name in ("codex", "profile", "workspace", "private_root"):
        p.add_argument(name, type=Path)
    p.add_argument("--treatment", action="store_true")
    p = subs.add_parser("host-preflight")
    for name in (
        "codex",
        "lock",
        "baseline_profile",
        "treatment_profile",
        "baseline_workspace",
        "treatment_workspace",
        "private_root",
        "dependency_repo",
        "output",
    ):
        p.add_argument(name, type=Path)
    p.add_argument("--treatment-runtime-pin", type=Path, action="append", required=True)
    p = subs.add_parser("capture")
    for name in (
        "codex",
        "lock",
        "condition",
        "repeat",
        "profile",
        "workspace",
        "prompt",
        "output",
        "private_root",
        "host_preflight",
    ):
        p.add_argument(
            name,
            type=int
            if name == "repeat"
            else Path
            if name not in {"condition"}
            else str,
        )
    p.add_argument("--resume", action="store_true")
    p = subs.add_parser("verify")
    p.add_argument("output", type=Path)
    p.add_argument("--portable", action="store_true")
    p = subs.add_parser("export-ledger")
    p.add_argument("run", type=Path)
    p.add_argument("output", type=Path)
    p.add_argument("--native-capture", type=Path)
    p = subs.add_parser("validate-ledger-export")
    p.add_argument("directory", type=Path)
    p = subs.add_parser("facts")
    for name in (
        "annotations",
        "holdout",
        "plan",
        "capture_dir",
        "eval_root",
        "output",
    ):
        p.add_argument(name, type=Path)
    p = subs.add_parser("judge")
    for name in (
        "codex",
        "plan",
        "packet",
        "rubric",
        "prompt_r12",
        "prompt_adj",
        "profile_r1",
        "profile_r2",
        "profile_adj",
        "output",
    ):
        p.add_argument(name, type=Path)
    p = subs.add_parser("blind-packet")
    for name in ("result", "plan", "evidence", "output"):
        p.add_argument(name, type=Path)
    p = subs.add_parser("judge-check")
    p.add_argument("bundle", type=Path)
    p = subs.add_parser("paired")
    p.add_argument("request", type=Path)
    p.add_argument("output", type=Path)
    p.add_argument("--results", nargs=6, type=Path, required=True)
    p.add_argument("--capture-dirs", nargs=6, type=Path, required=True)
    p = subs.add_parser("report")
    p.add_argument("request", type=Path)
    p.add_argument("decision", type=Path)
    p.add_argument("plan", type=Path)
    p.add_argument("holdout", type=Path)
    p.add_argument("results", nargs=6, type=Path)
    p.add_argument("capture_dirs", nargs=6, type=Path)
    p.add_argument("--output", required=True, type=Path)
    return parser


def _bind_one_series(results, capture_dirs, expected):
    if len(capture_dirs) != 6:
        raise runner.ExecutionBlocked("six subject capture directories required")
    captures = [
        runner.verify_capture(path, verify_runtime=False) for path in capture_dirs
    ]
    capture_by_run = {
        capture["run_id"]: (capture, path)
        for capture, path in zip(captures, capture_dirs)
    }
    if len(capture_by_run) != 6 or set(capture_by_run) != expected:
        raise runner.ExecutionBlocked("six distinct frozen subject captures required")
    series_ids = {capture.get("series_id") for capture in captures}
    if len(series_ids) != 1 or not next(iter(series_ids)):
        raise runner.ExecutionBlocked("subject captures span multiple execution series")
    for value in results:
        capture, capture_dir = capture_by_run[value["run_id"]]
        if (
            capture.get("status") != "complete"
            or capture.get("condition") != value["condition"]
            or value.get("capture_provenance")
            != {
                "series_id": capture["series_id"],
                "run_sha256": runner.sha((Path(capture_dir) / "run.json").read_bytes()),
            }
        ):
            raise runner.ExecutionBlocked(
                "factual result does not bind its subject capture"
            )
    return next(iter(series_ids))


def report(request, decision, plan, holdout, result_paths, capture_dirs):
    from validators.holdout_manifest import canonical_sha256

    recomputed, errors = evaluate_request(request)
    if errors:
        raise runner.ExecutionBlocked("paired request invalid: " + "; ".join(errors))
    if decision != recomputed:
        raise runner.ExecutionBlocked("paired decision differs from recomputed request")
    if request["plan"]["canonical_sha256"] != canonical_sha256(plan):
        raise runner.ExecutionBlocked("paired request binds a different plan")
    if decision["plan_id"] != plan["plan_id"]:
        raise runner.ExecutionBlocked("paired decision binds a different plan")
    if decision["decision"] == "improved" and not all(
        row["audit_state"] in {"not-required", "accept-comparison"}
        for row in decision["pair_results"]
    ):
        raise runner.ExecutionBlocked("improvement requires every triggered audit")
    results = [runner.read_json(path) for path in result_paths]
    by_run = {result["run_id"]: result for result in results}
    expected = {
        run["run_id"]
        for pair in plan["paired_repeats"]
        for run in (pair["baseline"], pair["treatment"])
    }
    if len(by_run) != 6 or set(by_run) != expected:
        raise runner.ExecutionBlocked("six distinct frozen run results required")
    series_id = _bind_one_series(results, capture_dirs, expected)
    for value in results:
        errors = validate_result_v2(value, holdout, plan)
        if errors:
            raise runner.ExecutionBlocked("v2 result invalid: " + "; ".join(errors))
        for artifact in value["artifacts"]:
            runner.verify_bound_file(runner.PLUGIN_ROOT / "evals", artifact)
    eval_root = runner.PLUGIN_ROOT / "evals"
    for binding in request["bundles"]:
        bundle_path = eval_root / binding["path"]
        bundle = runner.read_json(bundle_path)
        subject_path = runner.verify_bound_file(eval_root, bundle["subject_artifact"])
        subject = json.loads(subject_path.read_text(encoding="utf-8"))
        run_id = bundle["run_id"]
        if run_id not in by_run or subject.get(
            "factual_result_sha256"
        ) != canonical_sha256(by_run[run_id]):
            raise runner.ExecutionBlocked(
                "paired judge packet does not bind its factual result"
            )
    summaries = []
    for metric in ("P1", "P2", "P3"):
        rows = [row for row in decision["pair_results"] if row["metric_id"] == metric]
        if len(rows) != 3:
            raise runner.ExecutionBlocked("paired decision lacks three metric rows")
        deltas = [row["treatment"]["score"] - row["baseline"]["score"] for row in rows]
        summaries.append(
            {
                "metric_id": metric,
                "pair_deltas": deltas,
                "median": statistics.median(deltas),
                "range": [min(deltas), max(deltas)],
            }
        )
    hard_counts = {run_id: result["fact_metrics"] for run_id, result in by_run.items()}
    return {
        "kind": "Stage1ABReport",
        "decision": decision["decision"],
        "metric_summaries": summaries,
        "hard_counts": hard_counts,
        "run_costs": decision["run_costs"],
        "added_major_errors": decision["added_major_errors"],
        "execution_series_id": series_id,
        "no_composite_total": True,
        "external_claim_ready": False,
    }


def main(argv=None):
    args = parser_for_commands().parse_args(argv)
    try:
        if args.command == "freeze":
            value = runner.freeze(
                args.plan,
                args.prompt,
                args.dependency_repo,
                args.output,
                treatment_runtime_pin=args.treatment_runtime_pin,
            )
        elif args.command == "probe":
            value = runner.probe_profile(
                args.codex,
                args.profile,
                args.workspace,
                args.treatment,
                args.private_root,
            )
        elif args.command == "host-preflight":
            value = runner.host_preflight(
                args.codex,
                args.lock,
                args.baseline_profile,
                args.treatment_profile,
                args.baseline_workspace,
                args.treatment_workspace,
                args.private_root,
                args.dependency_repo,
                args.output,
                treatment_runtime_pin=args.treatment_runtime_pin,
            )
        elif args.command == "capture":
            value = runner.capture(
                args.codex,
                args.lock,
                args.condition,
                args.repeat,
                args.profile,
                args.workspace,
                args.prompt,
                args.output,
                args.private_root,
                args.host_preflight,
                resume=args.resume,
            )
        elif args.command == "verify":
            value = runner.verify_capture(args.output, verify_runtime=not args.portable)
        elif args.command == "export-ledger":
            value = export_run(
                args.run, args.output, native_capture=args.native_capture
            )
            if not value["valid"]:
                raise runner.ExecutionBlocked("Stage 1 ledger export failed")
        elif args.command == "validate-ledger-export":
            value = validate_export(args.directory)
            if not value["valid"]:
                raise runner.ExecutionBlocked("Stage 1 ledger export invalid")
        elif args.command == "facts":
            value = facts.make_result(
                args.annotations,
                args.holdout,
                args.plan,
                args.capture_dir,
                args.eval_root,
            )
            runner.write_json(args.output, value)
        elif args.command == "judge":
            value = judging.run_judges(
                args.codex,
                args.plan,
                args.packet,
                args.rubric,
                args.prompt_r12,
                args.prompt_adj,
                {
                    "auto-r1": args.profile_r1,
                    "auto-r2": args.profile_r2,
                    "auto-adj": args.profile_adj,
                },
                args.output,
            )
        elif args.command == "blind-packet":
            value = packet.make_packet(
                args.result, args.plan, args.evidence, args.output
            )
        elif args.command == "judge-check":
            errors = validate_bundle(runner.read_json(args.bundle))
            if errors:
                raise runner.ExecutionBlocked(
                    "judge bundle invalid: " + "; ".join(errors)
                )
            value = {
                "valid": True,
                "usable_for_pairing": runner.read_json(args.bundle)[
                    "usable_for_pairing"
                ],
            }
        elif args.command == "paired":
            request = runner.read_json(args.request)
            value, errors = evaluate_request(request)
            if errors:
                raise runner.ExecutionBlocked(
                    "paired request invalid: " + "; ".join(errors)
                )
            eval_root = runner.PLUGIN_ROOT / "evals"
            plan = runner.read_json(eval_root / request["plan"]["path"])
            holdout = runner.read_json(eval_root / plan["bindings"]["holdout"]["path"])
            report(request, value, plan, holdout, args.results, args.capture_dirs)
            runner.write_json(args.output, value)
        else:
            value = report(
                runner.read_json(args.request),
                runner.read_json(args.decision),
                runner.read_json(args.plan),
                runner.read_json(args.holdout),
                args.results,
                args.capture_dirs,
            )
            runner.write_json(args.output, value)
    except (
        runner.ExecutionBlocked,
        OSError,
        KeyError,
        ValueError,
        subprocess.CalledProcessError,
    ) as error:
        print(json.dumps({"valid": False, "error": str(error)}), file=sys.stderr)
        return 1
    print(json.dumps(value, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
