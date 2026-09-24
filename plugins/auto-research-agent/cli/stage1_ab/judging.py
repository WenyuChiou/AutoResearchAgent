"""Run independent blinded rubric judges and defer required human audits."""

import json
import os
from pathlib import Path
import re
import subprocess
from datetime import datetime, timezone

from .packet import verify_packet
from .runner import ExecutionBlocked, PLUGIN_ROOT, read_json, sha, write_json
from validators.holdout_manifest import canonical_sha256


def _bound_json(eval_root, path):
    target = Path(path).resolve()
    root = Path(eval_root).resolve()
    if not target.is_relative_to(root) or not target.relative_to(
        root
    ).as_posix().startswith("private/"):
        raise ExecutionBlocked("judge artifacts must remain under evals/private")
    return {
        "path": target.relative_to(root).as_posix(),
        "canonical_sha256": canonical_sha256(read_json(target)),
    }


def run_judges(
    codex, plan_path, packet_path, rubric_path, prompt_r12, prompt_adj, profiles, output
):
    from validators.evaluation_plan import validate_plan
    from validators.rubric_judge_result import validate_result
    from validators.judge_bundle import validate_bundle, _result_signature

    plan = read_json(plan_path)
    if validate_plan(plan) or plan["status"] != "frozen":
        raise ExecutionBlocked("judge requires a valid frozen plan")
    packet = read_json(packet_path)
    model_input = verify_packet(packet, plan)
    packet_bytes = json.dumps(model_input, sort_keys=True).encode()
    known = {
        run["run_id"]: run["subject_id"]
        for pair in plan["paired_repeats"]
        for run in (pair["baseline"], pair["treatment"])
    }
    if (
        model_input.get("run_id") not in known
        or model_input.get("subject_id") != known[model_input["run_id"]]
    ):
        raise ExecutionBlocked("blinded packet does not bind a frozen subject")
    configs = {x["role"]: x for x in plan["judge_configs"]}
    if (
        sha(Path(prompt_r12).read_bytes()) != configs["auto-r1"]["prompt_sha256"]
        or sha(Path(prompt_adj).read_bytes()) != configs["auto-adj"]["prompt_sha256"]
    ):
        raise ExecutionBlocked("judge prompt hash differs from frozen plan")
    if len({str(Path(p).resolve()) for p in profiles.values()}) != 3:
        raise ExecutionBlocked("R1, R2, and ADJ require separate profiles")
    eval_root = PLUGIN_ROOT / "evals"
    rubric = read_json(rubric_path)
    if canonical_sha256(rubric) != plan["bindings"]["rubric"]["canonical_sha256"]:
        raise ExecutionBlocked("judge rubric differs from frozen plan")
    output = Path(output).resolve()
    if not output.is_relative_to(eval_root.resolve()) or not output.relative_to(
        eval_root.resolve()
    ).as_posix().startswith("private/"):
        raise ExecutionBlocked("judge output must stay under evals/private")
    if output.exists():
        raise ExecutionBlocked("judge output already exists")
    output.mkdir(parents=True)
    subject_path = output / "blinded-subject.json"
    subject_path.write_bytes(packet_bytes)
    subject_binding = {
        "path": subject_path.relative_to(eval_root.resolve()).as_posix(),
        "sha256": sha(packet_bytes),
    }
    results = {}
    for role in ("auto-r1", "auto-r2"):
        results[role] = _invoke(
            codex,
            role,
            configs[role],
            profiles[role],
            prompt_r12,
            rubric_path,
            packet_bytes,
            output,
            subject_binding,
        )
    if any(
        re.search(r"\b(baseline|treatment)\b", json.dumps(value), re.IGNORECASE)
        for value in results.values()
    ):
        raise ExecutionBlocked("judge result leaked a condition label")
    disagreement = _result_signature(results["auto-r1"]) != _result_signature(
        results["auto-r2"]
    )
    if disagreement:
        adjudication_input = (
            packet_bytes
            + b"\nR1 and R2 independent decisions:\n"
            + json.dumps(
                [results["auto-r1"], results["auto-r2"]], sort_keys=True
            ).encode()
        )
        results["auto-adj"] = _invoke(
            codex,
            "auto-adj",
            configs["auto-adj"],
            profiles["auto-adj"],
            prompt_adj,
            rubric_path,
            adjudication_input,
            output,
            subject_binding,
        )
    for role, result in results.items():
        errors = validate_result(result)
        if errors:
            raise ExecutionBlocked(f"{role} output invalid: {'; '.join(errors)}")
    requires_audit = any(x["requires_human_audit"] for x in results.values())
    selected = results.get("auto-adj", results["auto-r1"])
    bundle = {
        "kind": "JudgeBundle",
        "schema_version": "1.0.0",
        "bundle_id": "bundle-" + model_input["run_id"],
        "plan": {
            "plan_id": plan["plan_id"],
            "artifact": _bound_json(eval_root, plan_path),
        },
        "run_id": model_input["run_id"],
        "subject_id": model_input["subject_id"],
        "subject_artifact": subject_binding,
        "artifacts": {
            "auto_r1": _bound_json(eval_root, output / "auto-r1.json"),
            "auto_r2": _bound_json(eval_root, output / "auto-r2.json"),
            "auto_adj": _bound_json(eval_root, output / "auto-adj.json")
            if disagreement
            else None,
            "human_audit": None,
        },
        "status": "audit-required" if requires_audit else "agreed",
        "selected_evaluation_id": None if requires_audit else selected["evaluation_id"],
        "usable_for_pairing": not requires_audit,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    errors = validate_bundle(bundle)
    if errors:
        raise ExecutionBlocked("judge bundle invalid: " + "; ".join(errors))
    write_json(output / "bundle.json", bundle)
    return bundle


def _invoke(
    codex,
    role,
    config,
    profile,
    prompt_path,
    rubric_path,
    packet,
    output,
    subject_binding,
):
    profile = Path(profile).resolve()
    if not profile.is_dir():
        raise ExecutionBlocked(f"{role} profile missing")
    env = dict(os.environ, CODEX_HOME=str(profile))
    login = subprocess.run(
        [str(codex), "login", "status"],
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
    )
    if login.returncode or "Logged in" not in (login.stdout + login.stderr):
        raise ExecutionBlocked(f"{role} profile not authenticated")
    result_path = output / f"{role}.json"
    schema = PLUGIN_ROOT / "evals" / "schemas" / "rubric-judge-result.v1.schema.json"
    command = [
        str(codex),
        "exec",
        "--json",
        "--sandbox",
        "read-only",
        "--skip-git-repo-check",
        "-m",
        config["model_id"],
        "-c",
        f'model_reasoning_effort="{config["reasoning"]}"',
        "--output-schema",
        str(schema),
        "-o",
        str(result_path),
        "-",
    ]
    prompt = (
        Path(prompt_path).read_bytes()
        + b"\nFrozen rubric:\n"
        + Path(rubric_path).read_bytes()
        + b"\nBlinded subject binding:\n"
        + json.dumps(subject_binding, sort_keys=True).encode()
        + b"\nBlinded evidence packet:\n"
        + packet
    )
    result = subprocess.run(
        command, input=prompt, env=env, cwd=output, capture_output=True
    )
    (output / f"{role}.jsonl").write_bytes(result.stdout)
    (output / f"{role}.stderr").write_bytes(result.stderr)
    if result.returncode or not result_path.is_file():
        raise ExecutionBlocked(f"{role} failed; raw logs retained")
    return read_json(result_path)
