"""One explicit planning call, retained failures, and verified replay."""

import hashlib
import importlib.metadata
from pathlib import Path
import sys

from .contracts import Stage3Error, digest
from .prompts import build_prompt
from .storage import (
    inspect_package,
    private_output,
    publish_manifest,
    read_bytes,
    write_new,
)
from .validation import check_plan

SCHEMA = (
    Path(__file__).resolve().parents[2] / "schemas/stage3-research-plan.v1.schema.json"
)


def _draft_from_intake(
    intake,
    output_dir,
    callback,
    *,
    configuration,
    plan_id,
    version=1,
    resume_manifest_sha256=None,
    admission_scope,
):
    """The callback is a trusted host seam, not proof of a native or human call."""
    if not callable(callback):
        raise Stage3Error("planning callback required")
    if set(configuration) != {"model", "reasoning"} or any(
        not isinstance(value, str) or not value.strip()
        for value in configuration.values()
    ):
        raise Stage3Error("exact host-selected model and reasoning required")
    if (
        not isinstance(plan_id, str)
        or not plan_id.strip()
        or type(version) is not int
        or version < 1
    ):
        raise Stage3Error("plan identity/version invalid")
    prompt = build_prompt(intake, plan_id=plan_id, version=version)
    schema = read_bytes(SCHEMA)
    cli_root = Path(__file__).resolve().parents[1]
    source_hashes = {
        p.relative_to(cli_root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(cli_root.rglob("*.py"))
    }
    request = {
        "operation": "stage3.scientific-plan.v1",
        "admission_scope": admission_scope,
        "intake": intake,
        "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
        "schema_sha256": hashlib.sha256(schema).hexdigest(),
        "producer_sha256": digest(source_hashes),
        "configuration": configuration,
        "runtime": {
            "python": sys.version,
            "jsonschema": importlib.metadata.version("jsonschema"),
        },
        "callback_context": getattr(
            callback, "request_context", {"kind": "host-callback-unverified"}
        ),
        "plan_id": plan_id,
        "version": version,
        "policy": {
            "tools": "none",
            "scientific_execution": False,
            "retries": 0,
            "execution_authorized": False,
        },
    }
    request_sha = digest(request)
    output = private_output(output_dir)
    if output.exists():
        if resume_manifest_sha256 is None:
            raise Stage3Error(
                "planning attempt exists; inspect it, do not silently retry"
            )
        saved = inspect_package(output, resume_manifest_sha256)
        if saved["manifest"]["request_sha256"] != request_sha:
            raise Stage3Error("resume inputs/configuration/schema/producer changed")
        if saved["artifacts"].get("request.json") != request:
            raise Stage3Error("resume request differs")
        return {**saved, "resume_action": "verified-replay-no-generation"}
    if resume_manifest_sha256 is not None:
        raise Stage3Error("resume requires a saved completed or failed attempt")
    output.mkdir(parents=True)
    write_new(output / "request.json", request)
    write_new(output / "prompt.txt", prompt.encode(), raw=True)
    write_new(output / "schema.json", schema, raw=True)
    names = ["request.json", "prompt.txt", "schema.json"]
    try:
        response = callback(
            prompt=prompt,
            schema_path=SCHEMA,
            output_dir=output,
            configuration=dict(configuration),
        )
        # Native callback returns raw JSON plus its unchanged primitive provenance.
        if not isinstance(response, dict) or set(response) != {
            "raw_response",
            "provenance",
        }:
            raise Stage3Error("callback must return raw_response and provenance")
        raw = response["raw_response"]
        if isinstance(raw, str):
            raw = raw.encode("utf-8")
        if not isinstance(raw, bytes):
            raise Stage3Error("callback raw response must be bytes/text")
        write_new(output / "raw-response.json", raw, raw=True)
        names.append("raw-response.json")
        write_new(output / "generation.json", response["provenance"])
        names.append("generation.json")
        from .storage import read_json

        plan = read_json(output / "raw-response.json")
        report = check_plan(plan, intake=intake)
        if (
            not report["structural_valid"]
            or plan["plan_id"] != plan_id
            or plan["version"] != version
        ):
            write_new(output / "validation.json", report)
            names.append("validation.json")
            raise Stage3Error("generated plan failed source/graph/identity checks")
        write_new(output / "plan.json", plan)
        names.append("plan.json")
        write_new(output / "validation.json", report)
        names.append("validation.json")
        state = "needs-information" if report["blocked_questions"] else "draft"
    except BaseException as error:
        write_new(
            output / "failure.json",
            {
                "error_class": type(error).__name__,
                "message": str(error),
                "execution_authorized": False,
            },
        )
        names.append("failure.json")
        manifest = publish_manifest(
            output, names, request_sha256=request_sha, state="failed"
        )
        raise Stage3Error(
            f"planning failed; original evidence retained; manifest={manifest['manifest_sha256']}: {error}"
        ) from error
    manifest = publish_manifest(output, names, request_sha256=request_sha, state=state)
    return inspect_package(output, manifest["manifest_sha256"])


def draft_plan(
    package_dir,
    delivery_dir,
    *,
    expected_manifest_sha256,
    output_dir,
    callback,
    configuration,
    plan_id,
    version=1,
    resume_manifest_sha256=None,
):
    """Public selected planning always replays strict external-hash admission."""
    from .intake import admit_intake

    intake = admit_intake(
        package_dir, delivery_dir, expected_manifest_sha256=expected_manifest_sha256
    )
    return _draft_from_intake(
        intake,
        output_dir,
        callback,
        configuration=configuration,
        plan_id=plan_id,
        version=version,
        resume_manifest_sha256=resume_manifest_sha256,
        admission_scope="strict-selected",
    )


def draft_synthetic_plan(
    intake,
    output_dir,
    callback,
    *,
    configuration,
    plan_id,
    version=1,
    resume_manifest_sha256=None,
):
    """Explicit test seam: projected dictionaries cannot become confirmed plans."""
    return _draft_from_intake(
        intake,
        output_dir,
        callback,
        configuration=configuration,
        plan_id=plan_id,
        version=version,
        resume_manifest_sha256=resume_manifest_sha256,
        admission_scope="synthetic-test",
    )
