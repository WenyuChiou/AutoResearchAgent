"""Offline, explicitly bound source-audit reason-format migration.

Recovery receipts are not native calls and are not accepted by ordinary resume.
An independently reviewed future call plan must explicitly consume them.
"""

import argparse
import copy
import contextvars
from contextlib import contextmanager
import json
import os
from pathlib import Path
import sys
import stat

from .common import EvaluationError, canonical, read_json, sha, write_json
from .model_calls import _validate_local_schema, replay_native_model_call_archive
from .source_audit_units import (
    _prompt,
    _schema,
    build_audit_plan,
    normalize_audit_value,
)
from .spans import model_span_aliases

KIND = "Stage1ReasonRecovery.v1"
PLAN_KIND = "Stage1ReasonRecoveryPlan.v1"


_GUARD = contextvars.ContextVar("stage1_recovery_readonly", default=None)
_MUTATIONS = {
    "os.mkdir",
    "os.rmdir",
    "os.remove",
    "os.rename",
    "os.link",
    "os.symlink",
    "os.chown",
    "os.chmod",
    "os.utime",
    "os.truncate",
    "os.system",
    "os.posix_spawn",
    "os.exec",
    "os.fork",
    "os.forkpty",
}
_NETWORK = {"socket.connect", "socket.getaddrinfo", "socket.sendto", "socket.bind"}


def _audit_guard(event, args):
    state = _GUARD.get()
    if state is None:
        return
    if event == "open":
        mode, flags = args[1], args[2]
        if (isinstance(mode, str) and any(c in mode for c in "wax+")) or (
            isinstance(flags, int)
            and flags
            & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)
        ):
            raise EvaluationError("offline recovery forbids filesystem writes")
    if event in _MUTATIONS or event in _NETWORK:
        raise EvaluationError("offline recovery forbids " + event)
    if event == "subprocess.Popen":
        raise EvaluationError("offline recovery forbids subprocesses")


sys.addaudithook(_audit_guard)


@contextmanager
def readonly_guard():
    token = _GUARD.set({"child": None})
    previous = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        yield
    finally:
        sys.dont_write_bytecode = previous
        _GUARD.reset(token)


def verify_source_journal(path, result_path, prefix, journal_view=None):
    """Authenticate completed historical observations without registering a new one."""
    from .source_replay import EVENT_KIND

    raw = Path(path).read_bytes()
    physical_sha = sha(raw)
    if journal_view is not None:
        if physical_sha != journal_view["current_sha256"]:
            raise EvaluationError("incident-bound current journal changed")
        raw = journal_view["prefix"]
    previous = [json.loads(line) for line in raw.splitlines()]
    if not previous or len(previous) % 2:
        raise EvaluationError(
            "unfinished historical source journal requires reviewed disposition"
        )
    command = prefix + ["source", "validate", str(result_path), "--json"]
    expected_result = sha(Path(result_path).read_bytes())
    for request, outcome in zip(previous[::2], previous[1::2], strict=True):
        if (
            request.get("kind") != EVENT_KIND
            or outcome.get("kind") != EVENT_KIND
            or request.get("event") != "registered"
            or outcome.get("event") != "finished"
            or not request.get("attempt_id")
            or request.get("attempt_id") != outcome.get("attempt_id")
            or request.get("command") != command
            or request.get("result_sha256") != expected_result
            or outcome.get("validation_passed") is not True
            or outcome.get("status") != "completed"
            or outcome.get("returncode") != 0
            or any(
                outcome.get(k) != v
                for k, v in request.items()
                if k not in {"event", "observed_at"}
            )
        ):
            raise EvaluationError("historical source journal binding changed")
        for field in ("stdout", "stderr"):
            if (
                sha(bytes.fromhex(outcome[field + "_hex"]))
                != outcome[field + "_sha256"]
            ):
                raise EvaluationError("historical source journal bytes changed")
        report = json.loads(bytes.fromhex(outcome["stdout_hex"]))
        source = json.loads(Path(result_path).read_bytes())
        if (
            report.get("valid") is not True
            or report.get("errors") != []
            or report.get("schema_version") != "source-fetch-validation/v1"
            or report.get("result_path") != str(Path(result_path).resolve())
            or any(
                report.get(k) != source.get(k)
                for k in ("receipt_sha256", "source_version")
            )
        ):
            raise EvaluationError("historical source journal report changed")
    return {
        "view_sha256": sha(raw),
        "physical_sha256": physical_sha,
        "derived_prefix": journal_view is not None,
    }


def readonly_source_validator(source_plan, observations, journal_views=None):
    """Use the exact pinned CLI public validator; never append old journals."""
    from .runtime import executable_sha256, installed_package_sha256

    def validate(result_path, prefix, journal_path):
        journal_binding = verify_source_journal(
            journal_path,
            result_path,
            prefix,
            (journal_views or {}).get(str(Path(journal_path).resolve())),
        )
        if prefix != [sys.executable, "-m", "research_hub"]:
            raise EvaluationError("source parser command prefix changed")
        if executable_sha256(sys.executable) != source_plan["python_executable_sha256"]:
            raise EvaluationError("source parser Python pin changed")
        if (
            installed_package_sha256("research_hub")
            != source_plan["research_hub_package_sha256"]
        ):
            raise EvaluationError("source parser dependency pin changed")
        before = Path(result_path).read_bytes()
        from research_hub.source_fetch import validate_source_fetch

        # This public wrapper is exactly what the pinned CLI source validate calls.
        # Unlike the old evaluator wrapper, it never appends an evaluator journal.
        with readonly_guard():
            report = validate_source_fetch(Path(result_path))
        original = json.loads(before)
        if (
            Path(result_path).read_bytes() != before
            or report.get("valid") is not True
            or report.get("errors") != []
            or report.get("schema_version") != "source-fetch-validation/v1"
            or report.get("result_path") != str(Path(result_path).resolve())
            or any(
                report.get(k) != original.get(k)
                for k in ("receipt_sha256", "source_version")
            )
        ):
            raise EvaluationError("read-only source parser report binding changed")
        observations.append(
            {
                "kind": "Stage1ReadOnlySourceValidation.v1",
                "result_sha256": sha(before),
                "python_sha256": source_plan["python_executable_sha256"],
                "package_sha256": source_plan["research_hub_package_sha256"],
                "historical_journal": journal_binding,
                "validator": "research_hub.source_fetch.validate_source_fetch",
                "report": {k: v for k, v in report.items() if k != "checked_at"},
                "new_native_calls": 0,
                "original_journal_modified": False,
            }
        )
        return report

    return validate


def bound_bytes(ref):
    raw = Path(ref["path"]).read_bytes()
    if sha(raw) != ref["sha256"]:
        raise EvaluationError("external artifact binding changed")
    return raw


def bound_json(ref):
    return json.loads(bound_bytes(ref))


def require_reason_delta(old, new):
    expected = copy.deepcopy(old)
    if expected["properties"]["reason"]["maxLength"] != 400:
        raise EvaluationError("expected original reason limit 400")
    expected["properties"]["reason"]["maxLength"] = 1024
    if expected != new:
        raise EvaluationError("only source-audit reason 400 to 1024 is permitted")


def verify_inventory(binding, *, exact=False, exclude_profile=False):
    """Read only manifest-listed files; no credential/profile discovery or copying."""
    root = Path(binding["root"]).resolve()
    files = binding["files"]
    if not isinstance(files, dict) or not files:
        raise EvaluationError("empty evidence inventory")
    for relative, expected in files.items():
        path = root / relative
        if (
            not isinstance(relative, str)
            or Path(relative).is_absolute()
            or ".." in Path(relative).parts
            or path.is_symlink()
            or not path.resolve().is_relative_to(root)
        ):
            raise EvaluationError("unsafe evidence inventory path")
        if sha(path.read_bytes()) != (
            expected["sha256"] if isinstance(expected, dict) else expected
        ):
            raise EvaluationError("evidence inventory changed: " + relative)
    if exact:
        observed = set()
        for parent, directories, names in os.walk(root, followlinks=False):
            base = Path(parent)
            for name in list(directories):
                child = base / name
                if child.is_symlink():
                    raise EvaluationError("symlink directory in evidence inventory")
                if exclude_profile and child == root / "profile":
                    directories.remove(name)
                    if (child / "config.toml").is_file():
                        observed.add("profile/config.toml")
            observed.update(
                (base / name).relative_to(root).as_posix() for name in names
            )
        if observed != set(files):
            raise EvaluationError("evidence inventory omits or invents files")
    return root


def _assert_saved(path, value):
    if canonical(read_json(path)) != canonical(value):
        raise EvaluationError("reconstructed artifact differs: " + path.name)


def revalidate_unit(directory, label, target, group, config, policy):
    """Authenticate all historical generations, then select the earliest valid raw JSON."""
    directory = Path(directory)
    if label != "audit-" + sha(canonical({"target": target, "spans": group}))[:24]:
        raise EvaluationError("source-audit work/version/unit binding changed")
    aliases, _ = model_span_aliases(group)
    prompt = _prompt(target, aliases)
    new_schema = _schema(list(aliases))
    old_schema = copy.deepcopy(new_schema)
    old_schema["properties"]["reason"]["maxLength"] = 400
    schema_path = directory / (label + ".schema.json")
    initial_archive = directory / (label + ".model-call")
    correction_archive = directory / (label + "-correction.model-call")
    if not initial_archive.exists():
        if correction_archive.exists() or (directory / (label + ".unit.json")).exists():
            raise EvaluationError("orphan correction or accepted unit")
        return {
            "unit_id": label,
            "status": "missing",
            "coverage_eligible": False,
            "original_history": [],
            "new_native_calls": 0,
        }
    if read_json(schema_path) != old_schema:
        raise EvaluationError("original schema or aliases changed")
    require_reason_delta(old_schema, new_schema)
    original, initial = replay_native_model_call_archive(
        initial_archive,
        expected_prompt=prompt,
        expected_schema=schema_path,
        expected_config=config,
        expected_policy=policy,
        for_correction=True,
    )
    candidates = [("initial", original, initial)]
    old_error = None
    try:
        _validate_local_schema(original, old_schema)
        normalize_audit_value(original, group)
    except EvaluationError as error:
        old_error = str(error)
    if correction_archive.exists():
        if old_error is None:
            raise EvaluationError("correction after already valid original")
        correction_prompt = (
            prompt
            + "\nThe following output failed this unit's validation. Correct only this unit once; "
            "use the same evidence, preserve unknowns, and never invent sources.\n"
            + json.dumps(
                {
                    "unit": label,
                    "validation_error": old_error,
                    "rejected_output": original,
                },
                ensure_ascii=False,
            )
        )
        corrected, correction = replay_native_model_call_archive(
            correction_archive,
            expected_prompt=correction_prompt,
            expected_schema=schema_path,
            expected_config=config,
            expected_policy=policy,
            for_correction=True,
        )
        candidates.append(("correction", corrected, correction))
    # The old accepted receipt is verified independently of the newly selected attempt.
    old_receipt = directory / (label + ".unit.json")
    if old_receipt.exists():
        final = candidates[-1]
        _validate_local_schema(final[1], old_schema)
        old_value = normalize_audit_value(final[1], group)
        stored = read_json(old_receipt)
        if stored.get("label") != label or stored.get("value") != old_value:
            raise EvaluationError("historical accepted result changed")

        def stable(value):
            if isinstance(value, dict):
                return {
                    k: stable(v)
                    for k, v in value.items()
                    if k not in {"execution_status", "reused_completed_generation"}
                }
            return value

        expected = {"initial": initial, "correction": None}
        if len(candidates) == 2:
            expected.update(correction=candidates[1][2], correction_reason=old_error)
        if stable(stored.get("provenance")) != stable(expected):
            raise EvaluationError("historical accepted provenance changed")
    history, selected = [], None
    for name, raw, native in candidates:
        archive = Path(native["call_archive"])
        records = [read_json(p) for p in sorted(archive.glob("attempt-*.record.json"))]
        row = {
            "generation": name,
            "native": native,
            "attempt_records": records,
            "raw_output_sha256": native["output_sha256"],
        }
        try:
            _validate_local_schema(raw, new_schema)
            normalized = normalize_audit_value(raw, group)
            row["revalidation"] = "accepted"
            if selected is None:
                selected = {
                    "generation": name,
                    "value": normalized,
                    "native_output_sha256": native["output_sha256"],
                }
        except EvaluationError as error:
            row.update(revalidation="rejected", error=str(error))
        history.append(row)
    return {
        "unit_id": label,
        "status": "accepted" if selected else "rejected",
        "coverage_eligible": selected is not None,
        "selected": selected,
        "original_history": history,
        "historical_accepted_receipt": old_receipt.exists(),
        "old_schema_sha256": sha(schema_path.read_bytes()),
        "new_schema_sha256": sha(canonical(new_schema)),
        "new_native_calls": 0,
        "retry_budget_reset": False,
    }


def reconstruct_context(
    output, capture, background_ref, source_plan, observations, journal_views
):
    old_policy = source_plan["execution_policy"]
    """Reuse capture, extraction, original-field and source archive validators offline."""
    from .__main__ import _verify_background
    from .formal import observe_capture_v31
    from .extraction_v31 import extract_subject_v31
    from .original_fields import extract_original_fields
    from .sources_v31 import collect_sources_v31, attach_public_sources
    from .judging import make_packet_v31
    from .model_calls import _request_config
    from .source_runtime import source_runtime_preflight
    from .runtime import installed_package_sha256

    output = Path(output)
    inputs = read_json(output / "evaluation-input.json")
    if inputs["policy"] != old_policy:
        raise EvaluationError("original evaluator policy changed")
    config = inputs["model_config"]
    actual_config = _request_config(
        **{k: config[k] for k in ("codex", "evaluator_home", "model", "reasoning")}
    )
    if (
        actual_config != config
        or config["codex_executable_sha256"] != source_plan["codex_executable_sha256"]
        or config["codex"] != str(Path(source_plan["codex_executable"]).resolve())
        or inputs["source_runtime"] != source_plan["source_runtime"]
        or inputs["identity"]["evaluator_bundle_sha256"]
        != source_plan["evaluator_bundle_sha256"]
        or inputs["identity"]["research_hub_package_sha256"]
        != source_plan["research_hub_package_sha256"]
    ):
        raise EvaluationError("original model runtime changed")
    if source_runtime_preflight() != inputs["source_runtime"]:
        raise EvaluationError("source parser runtime changed")
    if (
        installed_package_sha256("research_hub")
        != inputs["identity"]["research_hub_package_sha256"]
    ):
        raise EvaluationError("source dependency runtime changed")
    subject, _ = observe_capture_v31(capture, portable=True)
    if sha((Path(capture) / "run.json").read_bytes()) != inputs["capture_run_sha256"]:
        raise EvaluationError("capture binding changed")
    _assert_saved(output / "subject-observation.json", subject)
    options = {k: config[k] for k in ("codex", "evaluator_home", "model", "reasoning")}
    options["execution_policy"] = old_policy
    extraction, provenance = extract_subject_v31(
        subject, output / "extraction", options, replay_only=True
    )
    provenance.pop("replay_only", None)
    _assert_saved(output / "subject-extraction.json", extraction)
    _assert_saved(output / "extraction-provenance.json", provenance)
    extraction, _ = extract_original_fields(
        subject,
        extraction,
        provenance,
        output / "original-fields",
        options,
        replay_only=True,
    )
    _assert_saved(output / "subject-original-extraction.json", extraction)
    spec = read_json(output / "spec.json")
    task = (output / "task.txt").read_bytes()
    if (
        sha(canonical(spec)) != inputs["spec_sha256"]
        or sha(task) != inputs["task_sha256"]
    ):
        raise EvaluationError("task/spec binding changed")
    background = bound_json(background_ref) if background_ref else None
    if inputs["mode"] == "evidence-audited":
        if not background:
            raise EvaluationError("missing audited background")
        _verify_background(background, background_ref["path"], spec)
    sources = collect_sources_v31(
        extraction,
        spec,
        output / "sources",
        ["@python", "-m", "research_hub"],
        replay_only=True,
        replay_validator=readonly_source_validator(
            source_plan, observations, journal_views
        ),
    )
    _assert_saved(output / "subject-sources.json", sources)
    packet = make_packet_v31(
        task.decode(),
        spec,
        subject,
        extraction,
        background,
        sources,
        mode=inputs["mode"],
    )
    attach_public_sources(packet, sources)
    catalogue = (background or {}).get("sources", []) + sources["sources"]
    return build_audit_plan(packet, catalogue, extraction), config


def historical_attempts(root, files):
    """Retain every original call record, including rejected and upstream calls."""
    rows = []
    for relative, bound in sorted(files.items()):
        if ".model-call/attempt-" not in relative or not relative.endswith(
            ".record.json"
        ):
            continue
        raw = (Path(root) / relative).read_bytes()
        expected = bound["sha256"] if isinstance(bound, dict) else bound
        if sha(raw) != expected:
            raise EvaluationError("historical attempt changed")
        try:
            record = json.loads(raw)
        except ValueError:
            record = None
        rows.append(
            {
                "path": relative,
                "sha256": expected,
                "record": record,
                "record_readable": record is not None,
            }
        )
    return rows


def rejected_history(directory, label):
    """Keep references on authentication failure; do not call these authenticated."""
    rows = []
    for name in (label, label + "-correction"):
        archive = directory / (name + ".model-call")
        for path in sorted(archive.glob("attempt-*.record.json")):
            raw = path.read_bytes()
            rows.append(
                {
                    "path": str(path),
                    "sha256": sha(raw),
                    "authentication": "not-established-unit-rejected",
                }
            )
    return rows


def _plan_contract(source, target, source_sha, old_bundle, new_bundle):
    if (
        target.get("kind") != PLAN_KIND
        or target.get("source_plan_sha256") != source_sha
        or target.get("source_bundle_sha256") != old_bundle
        or target.get("target_bundle_sha256") != new_bundle
        or target.get("targets") != source["targets"]
        or target.get("source_policy") != source["execution_policy"]
    ):
        raise EvaluationError("recovery plan binding changed")
    expected = copy.deepcopy(source["execution_policy"])
    expected["evaluator_bundle_sha256"] = new_bundle
    if target.get("target_policy") != expected:
        raise EvaluationError("recovery policy changes more than evaluator bundle")


def verify_code_contract(inventory, old_bundle):
    """Reconstruct the original bundle rather than trusting a self-labelled digest."""
    root = verify_inventory(inventory) / "plugins/auto-research-agent"
    files = sorted((root / "cli/stage1_eval").glob("*.py"))
    files += sorted((root / "evals/schemas").glob("*v3*.schema.json"))
    files += [
        root / "evals/rubrics/stage1-general.v3.json",
        root / "evals/stage1/execution-policy.v3_1.json",
    ]
    capture_files = [
        root / "cli/stage1_ab" / (name + ".py")
        for name in ("capture_history", "observer")
    ]
    for path in files + capture_files:
        if (
            "plugins/auto-research-agent/" + path.relative_to(root).as_posix()
            not in inventory["files"]
        ):
            raise EvaluationError("original bundle file omitted from inventory")
    rows = [
        {"path": p.relative_to(root).as_posix(), "sha256": sha(p.read_bytes())}
        for p in files
    ]
    rows.append(
        {
            "path": "capture-history-and-observer-v1",
            "sha256": sha(
                canonical(
                    [
                        {"module": "stage1_ab." + p.stem, "sha256": sha(p.read_bytes())}
                        for p in capture_files
                    ]
                )
            ),
        }
    )
    if sha(canonical(rows)) != old_bundle:
        raise EvaluationError("original evaluator bundle does not reconstruct")
    current = Path(__file__).resolve().parents[2]
    added = set(p.name for p in (current / "cli/stage1_eval").glob("*.py")) - set(
        p.name for p in (root / "cli/stage1_eval").glob("*.py")
    )
    if added != {"reason_recovery.py"}:
        raise EvaluationError("unexplained new evaluator modules")
    return root


def verify_incident(ref, generation_inventory):
    """An exact externally bound incident permits a labelled derived prefix, never repair."""
    incident = bound_json(ref)
    if (
        incident.get("kind") != "Stage1ReasonRecoveryIncident.v1"
        or not isinstance(incident.get("decision_url"), str)
        or not incident["decision_url"].startswith(
            "https://github.com/WenyuChiou/AutoResearchAgent/pull/62#issuecomment-"
        )
    ):
        raise EvaluationError("unsupported incident disposition")
    before = bound_json(incident["pre_inventory"])
    after = bound_json(incident["post_inventory"])
    if (
        after != generation_inventory
        or Path(before["root"]).resolve() != Path(after["root"]).resolve()
        or set(before["files"]) != set(after["files"])
    ):
        raise EvaluationError("incident inventory population or root changed")
    if before.get("excluded_scope") != after.get("excluded_scope"):
        raise EvaluationError("incident exclusions changed")
    changes = incident["changes"]
    if len(changes) != 1:
        raise EvaluationError("only one explicitly bound journal incident is supported")
    change = changes[0]
    relative = change["path"]
    differing = {
        key for key in before["files"] if before["files"][key] != after["files"][key]
    }
    if differing != {relative} or not relative.endswith(
        "/validation/replay-events.jsonl"
    ):
        raise EvaluationError("incident delta differs from declared journal")
    if before["files"][relative] != {
        "bytes": change["original_bytes"],
        "sha256": change["original_sha256"],
    } or after["files"][relative] != {
        "bytes": change["current_bytes"],
        "sha256": change["current_sha256"],
    }:
        raise EvaluationError("incident original/current inventory binding changed")
    root = Path(after["root"]).resolve()
    path = (root / relative).resolve()
    if not path.is_relative_to(root):
        raise EvaluationError("incident journal escapes original generation")
    raw = path.read_bytes()
    if sha(raw) != change["current_sha256"] or len(raw) != change["current_bytes"]:
        raise EvaluationError("incident current journal changed")
    prefix, tail = raw[: change["original_bytes"]], raw[change["original_bytes"] :]
    if (
        sha(prefix) != change["original_sha256"]
        or sha(tail) != change["append_sha256"]
        or len(tail) != change["append_bytes"]
        or prefix != bound_bytes(change["derived_prefix"])
    ):
        raise EvaluationError("incident prefix or append mismatch")
    event = json.loads(tail)
    if (
        event.get("event") != "registered"
        or event.get("counts_as_source_acquisition") is not False
    ):
        raise EvaluationError(
            "incident tail is not a bound registration-only observation"
        )
    diagnostics = incident["diagnostics"]
    if set(diagnostics) != {"traceback", "diff"}:
        raise EvaluationError(
            "incident requires bound traceback and complete inventory diff"
        )
    for item in diagnostics.values():
        bound_bytes(item)
    provenance = {
        "kind": incident["kind"],
        "manifest_sha256": ref["sha256"],
        "decision_url": incident["decision_url"],
        "changes": changes,
        "pre_inventory": incident["pre_inventory"],
        "post_inventory": incident["post_inventory"],
        "interpretation": "Authenticated derived original-prefix view; original journal includes preserved incident append.",
    }
    return {
        str(path.resolve()): {"prefix": prefix, "current_sha256": sha(raw)}
    }, provenance


def verify_operator_runtime(source, generation):
    from .runtime import executable_sha256

    if executable_sha256(sys.executable) != source["python_executable_sha256"]:
        raise EvaluationError("original Python runtime pin changed")
    if (
        sha((Path(generation) / "research-hub.json").read_bytes())
        != source["research_hub_config_sha256"]
    ):
        raise EvaluationError("original source configuration pin changed")


def _dry_run(manifest_path, expected_sha256):
    """Return fully revalidated private migration state without writing or calling models."""
    from .pipeline_v31 import bundle_sha_v31, execution_policy

    manifest = bound_json({"path": manifest_path, "sha256": expected_sha256})
    if manifest.get("kind") != KIND or manifest.get("reason_delta") != [400, 1024]:
        raise EvaluationError("unsupported recovery manifest")
    source = bound_json(manifest["source_plan"])
    target = bound_json(manifest["target_plan"])
    old_bundle = source["evaluator_bundle_sha256"]
    new_bundle = bundle_sha_v31()
    _plan_contract(
        source, target, manifest["source_plan"]["sha256"], old_bundle, new_bundle
    )
    if target["target_policy"] != execution_policy():
        raise EvaluationError("target policy differs from current evaluator")
    generation_inventory = bound_json(manifest["generation"])
    code_inventory = bound_json(manifest["old_code"])
    capture_inventory = bound_json(manifest["captures"])["captures"]
    generation = verify_inventory(
        generation_inventory, exact=True, exclude_profile=True
    )
    if Path(manifest["source_plan"]["path"]).resolve() != generation / "plan.json":
        raise EvaluationError("source plan is outside original generation")
    frozen_captures = bound_json(
        {
            "path": str(generation / "capture-inventory.json"),
            "sha256": source["capture_inventory_sha256"],
        }
    )
    if set(frozen_captures) != set(source["targets"]) or set(capture_inventory) != set(
        source["targets"]
    ):
        raise EvaluationError("capture population differs from source plan")
    for name, capture_binding in capture_inventory.items():
        actual = {
            key: value["sha256"] for key, value in capture_binding["files"].items()
        }
        if actual != frozen_captures[name]:
            raise EvaluationError(
                "capture inventory differs from original frozen target"
            )
    journal_views, incident_provenance = ({}, None)
    if manifest.get("incident") is not None:
        journal_views, incident_provenance = verify_incident(
            manifest["incident"], generation_inventory
        )
    verify_operator_runtime(source, generation)
    old_code = verify_code_contract(code_inventory, old_bundle)
    current = Path(__file__).resolve().parents[2]
    # Request validation remains byte-identical; unrelated evaluator changes cannot pass.
    allowed = {
        "cli/stage1_eval/source_audit_units.py",
        "cli/stage1_eval/reason_recovery.py",
        "cli/stage1_eval/sources_v31.py",
    }
    for relative, item in code_inventory["files"].items():
        relative = relative.removeprefix("plugins/auto-research-agent/")
        digest = item["sha256"] if isinstance(item, dict) else item
        if (
            relative.startswith("cli/stage1_eval/")
            or (relative.startswith("evals/schemas/") and "v3" in Path(relative).name)
            or relative
            in {
                "evals/rubrics/stage1-general.v3.json",
                "evals/stage1/execution-policy.v3_1.json",
                "cli/stage1_ab/capture_history.py",
                "cli/stage1_ab/observer.py",
            }
        ):
            if (
                relative not in allowed
                and sha((current / relative).read_bytes()) != digest
            ):
                raise EvaluationError(
                    "unexplained evaluator contract change: " + relative
                )
    if not all(
        "plugins/auto-research-agent/cli/stage1_eval/" + name in code_inventory["files"]
        for name in ("model.py", "model_calls.py", "source_audit_units.py")
    ):
        raise EvaluationError("incomplete evaluator code inventory")
    del old_code
    rows, output_rows, observations = [], [], []
    bindings = {row["id"]: row for row in manifest["outputs"]}
    if list(bindings) != source["targets"] or len(bindings) != len(manifest["outputs"]):
        raise EvaluationError("recovery output population changed")
    for target_id in source["targets"]:
        entry = bindings[target_id]
        capture = verify_inventory(capture_inventory[target_id], exact=True)
        if entry["output"] != "evaluations/" + target_id:
            raise EvaluationError("output mapping differs from original target")
        output = generation / entry["output"]
        if not output.resolve().is_relative_to(generation):
            raise EvaluationError("output escapes original generation")
        if not (output / "evaluation-input.json").exists():
            output_rows.append(
                {"id": target_id, "status": "unstarted", "unit_population": None}
            )
            continue
        plan, config = reconstruct_context(
            output,
            capture,
            entry.get("background"),
            source,
            observations,
            journal_views,
        )
        if (
            config["model"] != source["model"]
            or config["reasoning"] != source["reasoning"]
        ):
            raise EvaluationError("frozen model or reasoning changed")
        output_rows.append(
            {
                "id": target_id,
                "status": "revalidated",
                "unit_population": sum(
                    len(r["expected_unit_ids"]) for r in plan["plan"]
                )
                * 2,
            }
        )
        for role in ("r1", "r2"):
            directory = output / "source-audits" / role
            if (directory / "plan.json").exists():
                _assert_saved(directory / "plan.json", plan)
            elif directory.exists() and any(directory.iterdir()):
                raise EvaluationError("source-audit artifacts without plan")
            for planned in plan["plan"]:
                for label, group in zip(
                    planned["expected_unit_ids"], planned["windows"]
                ):
                    try:
                        value = revalidate_unit(
                            directory,
                            label,
                            planned["target"],
                            group,
                            config,
                            source["execution_policy"],
                        )
                    except (
                        EvaluationError,
                        OSError,
                        KeyError,
                        TypeError,
                        ValueError,
                    ) as error:
                        value = {
                            "unit_id": label,
                            "status": "rejected",
                            "coverage_eligible": False,
                            "error": str(error),
                            "new_native_calls": 0,
                            "original_history": rejected_history(directory, label),
                            "retry_budget_reset": False,
                        }
                    rows.append(
                        {
                            "output_id": target_id,
                            "role": role,
                            "plan_sha256": sha(canonical(plan)),
                            **value,
                        }
                    )
    # Existing validators may reread files; recheck every externally bound byte before acceptance.
    verify_inventory(generation_inventory, exact=True, exclude_profile=True)
    verify_inventory(code_inventory)
    for row in capture_inventory.values():
        verify_inventory(row, exact=True)
    return {
        "kind": KIND,
        "manifest_sha256": expected_sha256,
        "source_plan_sha256": manifest["source_plan"]["sha256"],
        "target_plan_sha256": manifest["target_plan"]["sha256"],
        "source_bundle_sha256": old_bundle,
        "target_bundle_sha256": new_bundle,
        "outputs": output_rows,
        "units": rows,
        "original_attempt_inventory": historical_attempts(
            generation, generation_inventory["files"]
        ),
        "recovery_attempt_inventory": [],
        "source_validation_observations": observations,
        "incident": incident_provenance,
        "counts": {
            status: sum(r["status"] == status for r in rows)
            for status in ("accepted", "rejected", "missing")
        },
        "new_native_calls": 0,
        "retry_budget_reset": False,
        "formal_eligible": False,
        "gate_accepted": False,
        "future_execution_authorized": False,
    }


def dry_run(manifest_path, expected_sha256):
    """Read-only API guard is active before any upstream validation helper."""
    with readonly_guard():
        return _dry_run(manifest_path, expected_sha256)


def _recovery_destination(destination, protected=(), *, exists_ok=False):
    """Check lexical indirection before canonical overlap and every output write."""
    lexical = Path(destination).absolute()
    for ancestor in (lexical, *lexical.parents):
        if (ancestor / ".git").exists():
            raise EvaluationError("private recovery output must be outside Git")
        try:
            info = ancestor.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise EvaluationError("private recovery output cannot traverse links")
    if ".." in lexical.parts:
        raise EvaluationError(
            "private recovery output cannot contain traversal segments"
        )
    resolved = lexical.resolve()
    for root in protected:
        root = Path(root).resolve()
        if resolved.is_relative_to(root) or root.is_relative_to(resolved):
            raise EvaluationError("recovery destination overlaps original evidence")
    if resolved.exists() and not exists_ok:
        raise EvaluationError("recovery destination already exists")
    return resolved


def import_recovery(manifest_path, expected_sha256, destination):
    original_destination = destination
    destination = _recovery_destination(original_destination)
    manifest = bound_json({"path": manifest_path, "sha256": expected_sha256})
    protected = [
        bound_json(manifest[key])["root"] for key in ("generation", "old_code")
    ]
    protected += [
        r["root"] for r in bound_json(manifest["captures"])["captures"].values()
    ]
    protected = [Path(root).resolve() for root in protected]
    destination = _recovery_destination(original_destination, protected)
    try:
        result = dry_run(manifest_path, expected_sha256)
    except Exception as error:
        destination = _recovery_destination(original_destination, protected)
        destination.mkdir(parents=True, exist_ok=False)
        destination = _recovery_destination(
            original_destination, protected, exists_ok=True
        )
        write_json(
            destination / "recovery-failure.json",
            {
                "kind": KIND,
                "manifest_sha256": expected_sha256,
                "status": "binding-failed",
                "error": str(error),
                "coverage_eligible": False,
                "new_native_calls": 0,
                "unit_population": None,
                "future_execution_authorized": False,
            },
        )
        raise
    destination = _recovery_destination(original_destination, protected)
    destination.mkdir(parents=True, exist_ok=False)
    manifest_raw = Path(manifest_path).read_bytes()
    if sha(manifest_raw) != expected_sha256:
        raise EvaluationError("manifest changed during import")
    destination = _recovery_destination(original_destination, protected, exists_ok=True)
    (destination / "manifest.json").write_bytes(manifest_raw)
    destination = _recovery_destination(original_destination, protected, exists_ok=True)
    write_json(destination / "recovery.json", result)
    return result


def replay_recovery(destination, expected_manifest_sha256):
    destination = Path(destination)
    actual = dry_run(destination / "manifest.json", expected_manifest_sha256)
    _assert_saved(destination / "recovery.json", actual)
    return actual


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("dry-run", "import", "replay"))
    parser.add_argument("path")
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--destination")
    args = parser.parse_args(argv)

    if args.action == "replay":
        result = replay_recovery(args.path, args.sha256)
    elif args.action == "import":
        if not args.destination:
            parser.error("import requires --destination")
        result = import_recovery(args.path, args.sha256, args.destination)
    else:
        result = dry_run(args.path, args.sha256)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
