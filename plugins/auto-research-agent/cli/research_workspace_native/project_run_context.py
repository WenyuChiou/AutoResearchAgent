"""Portable saved context beside a canonical package; never execution authority.

The journal prefix ends at the durable delivery intent, before its saved event.
Historical absolute paths are data. All current reads use contained local refs.
"""

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import stat
import sys

from research_workspace.canonical_delivery import _delivery
from stage1_brief.brief import validate_bound_plan
from stage1_deliverable.common import (
    DeliverableError,
    canonical,
    private_output,
    reject_links,
    safe_path,
    sha,
)
from stage1_deliverable.sources import reject_secrets
from stage1_ledger.journal import Journal, decode
from stage1_ledger.validation import validate_run

from .project_resource_budget import KINDS, resource_view

CONTRACT = "Stage1RunContext"
MANIFEST = "run-context.json"
MAX_FILES = 4096
MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_TOTAL_BYTES = 512 * 1024 * 1024
BINDING_FIELDS = (
    "artifact_ref",
    "manifest_sha256",
    "records_sha256",
    "binding",
    "run_ref",
    "ledger_state_sha256",
    "handoff_sha256",
    "checkpoint_event_id",
    "eligible_for_stage2",
)
FLAGS = dict(
    execution_authorized=False,
    research_execution_authorized=False,
    Core_acceptance=False,
    formal_Stage2_import=False,
    scientific_complete=False,
)


def _check(condition, message):
    if not condition:
        raise DeliverableError("run-context: " + message)


def _raw(path):
    reject_links(path)
    info = path.stat()
    _check(
        stat.S_ISREG(info.st_mode) and info.st_nlink == 1,
        "regular unlinked file required",
    )
    with path.open("rb") as stream:
        raw = stream.read(MAX_FILE_BYTES + 1)
    _check(len(raw) <= MAX_FILE_BYTES, "file bound exceeded")
    return raw


def _tree(root):
    from .project_stage1_delivery import _io_root

    root = _io_root(private_output(root))
    _check(root.is_dir(), "source directory missing")
    result, total = {}, 0
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        path = safe_path(root, relative)
        _check(path.is_dir() or path.is_file(), "special source entry")
        if path.is_dir():
            continue
        _check(relative != ".writer-lock", "ledger writer active")
        raw = _raw(path)
        total += len(raw)
        _check(
            len(result) < MAX_FILES and total <= MAX_TOTAL_BYTES,
            "inventory bound exceeded",
        )
        result[relative] = raw
    return result


def _inventory(files):
    return {
        name: dict(bytes=len(raw), sha256=sha(raw))
        for name, raw in sorted(files.items())
    }


def _resource_archive(intake, state, principal):
    """Capture real project history, not a synthesized authorization or reset."""
    project = state["project_ref"]
    events = [
        dict(row)
        for row in intake.db.execute(
            "SELECT id,kind,payload FROM intake_events WHERE project=? ORDER BY id",
            (project,),
        )
    ]
    actions = [
        dict(row)
        for row in intake.db.execute(
            "SELECT principal,key,request_hash,receipt FROM intake_actions "
            "WHERE project=? ORDER BY principal,key",
            (project,),
        )
    ]
    value = dict(
        kind="ProjectResourceHistoryCapture",
        schema_version="1.0.0",
        project_ref=project,
        state=deepcopy(state),
        events=events,
        actions=actions,
        view=resource_view(intake, state, principal),
    )
    reject_secrets(canonical(value))
    return value


def _check_archive(value, binding):
    _check(
        type(value) is dict
        and set(value)
        == {
            "kind",
            "schema_version",
            "project_ref",
            "state",
            "events",
            "actions",
            "view",
        },
        "resource archive fields differ",
    )
    _check(
        value["kind"] == "ProjectResourceHistoryCapture"
        and value["schema_version"] == "1.0.0",
        "resource archive contract differs",
    )
    state, view = value["state"], value["view"]
    basis = binding["binding"]
    _check(
        state["project_ref"] == value["project_ref"] == view["binding"]["project_ref"]
        and all(
            state[k] == basis[k] == view["binding"][k]
            for k in ("project_id", "input_version")
        )
        and view["binding"]["brief_sha256"] == basis["brief_sha256"]
        and state["settings"]["brief_sha256"] == basis["brief_sha256"]
        and view["automatic_refund"] is False
        and view["actual_seconds"] is None,
        "resource project/input binding differs",
    )
    actions = {}
    for row in value["actions"]:
        receipt = json.loads(row["receipt"])
        key = (row["principal"], row["key"])
        _check(
            key not in actions and receipt["project_ref"] == value["project_ref"],
            "resource action duplicate or foreign",
        )
        _check(
            receipt["key"] == row["key"]
            and receipt["request_sha256"]
            == row["request_hash"]
            == sha(canonical(dict(kind=receipt["kind"], body=receipt["request"]))),
            "resource action hash differs",
        )
        actions[key] = receipt
    last, intents, reservations = 0, {}, {}
    for row in value["events"]:
        _check(
            type(row["id"]) is int and row["id"] > last, "resource event order differs"
        )
        last = row["id"]
        payload = json.loads(row["payload"])
        if row["kind"] == "project-resource-reservation":
            digest = payload["request_sha256"]
            _check(digest not in reservations, "duplicate reservation event")
            reservations[digest] = row["id"]
        elif row["kind"] in {kind + "-intent" for kind in KINDS}:
            digest = payload["request_sha256"]
            _check(
                digest not in intents
                and digest
                == sha(canonical(dict(kind=payload["kind"], body=payload["request"])))
                and payload["project_ref"] == value["project_ref"],
                "resource intent differs",
            )
            saved = [
                r
                for (_, key), r in actions.items()
                if key == payload["key"] and r["request_sha256"] == digest
            ]
            _check(len(saved) == 1, "resource intent action missing")
            intents[digest] = row["id"]
    _check(
        all(
            digest in intents and intents[digest] == number + 1
            for digest, number in reservations.items()
        ),
        "reservation/intent prefix differs",
    )
    return last


def _capture(delivery, project_ref, artifact, context, canonical_root):
    intake = delivery.intake
    current = delivery._context(project_ref)
    principal, state, _, run, ledger, report, *_ = current
    _check(
        current[2] == context[2]
        and run == context[3]
        and report["state_sha256"] == artifact["ledger_state_sha256"]
        and state["stage1_active"] == run["run_ref"]
        and run["run_ref"] == artifact["run_ref"],
        "producer context drifted",
    )
    binding = intake.binding(project_ref)
    brief = intake.brief_binding(project_ref, require_confirmed=True)
    archive = _resource_archive(intake, state, principal)
    files = {}
    roots = {
        "canonical": Path(canonical_root),
        "plan": Path(binding["plan_root"]),
        "ledger": ledger.root,
    }
    for prefix, path in roots.items():
        files.update({prefix + "/" + name: raw for name, raw in _tree(path).items()})
    files["brief.json"] = _raw(Path(brief["brief_path"]))
    files["resource-history.json"] = canonical(archive) + b"\n"
    _check(
        len(files) <= MAX_FILES and sum(map(len, files.values())) <= MAX_TOTAL_BYTES,
        "combined inventory bound exceeded",
    )
    return files, archive, roots


def build_run_context(delivery, project_ref, artifact, canonical_root, context):
    """Called only inside the existing delivery transaction, before final save."""
    intake = delivery.intake
    _check(intake.db.in_transaction, "delivery transaction required")
    output = private_output(
        Path(canonical_root).with_name(Path(canonical_root).name + "-context")
    )
    _check(not output.exists(), "output exists; preserve for reconciliation")
    files, archive, roots = _capture(
        delivery, project_ref, artifact, context, canonical_root
    )
    for source in roots.values():
        source = source.absolute()
        _check(
            source != output
            and source not in output.parents
            and output not in source.parents,
            "source/output overlap",
        )
    binding = {key: deepcopy(artifact[key]) for key in BINDING_FIELDS}
    last = _check_archive(archive, binding)
    manifest = dict(
        kind=CONTRACT,
        schema_version="1.0.0",
        binding=binding,
        core_run=dict(
            run_id=context[4].manifest["research_run"]["run_id"],
            manifest_sha256=context[3]["manifest_sha256"],
            query_owned=context[3].get("query_owned", False),
        ),
        capture_boundary=dict(
            scope="durable-intent-prefix-before-delivery-saved-event",
            project_ref=project_ref,
            revision=archive["state"]["revision"],
            last_event_id=last,
            state_sha256=sha(canonical(archive["state"])),
        ),
        captured_at=datetime.now(timezone.utc).isoformat(),
        timestamp_scope="capture-time-not-historical-discovery-time",
        producer=dict(
            module_sha256=sha(Path(__file__).read_bytes()), python_version=sys.version
        ),
        files=_inventory(files),
        **FLAGS,
    )
    output.mkdir(parents=True, exist_ok=False)
    for name, raw in files.items():
        target = safe_path(output, name)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as stream:
            stream.write(raw)
    manifest_raw = canonical(manifest) + b"\n"
    with (output / MANIFEST).open("xb") as stream:
        stream.write(manifest_raw)
    digest = sha(manifest_raw)
    validate_run_context(output, digest)
    after, after_archive, _ = _capture(
        delivery, project_ref, artifact, context, canonical_root
    )
    _check(
        files == after and archive == after_archive, "sources changed during capture"
    )
    return dict(
        kind=CONTRACT,
        schema_version="1.0.0",
        context_ref="stage1-context-" + digest[:32],
        manifest_sha256=digest,
        status="captured-validated",
        execution_authorized=False,
    )


def validate_run_context(root, expected_manifest_sha256):
    """Replay saved bytes only; do not open historical runtime absolute paths."""
    from .project_stage1_delivery import _io_root

    root = _io_root(private_output(root))
    files = _tree(root)
    _check(
        MANIFEST in files and sha(files[MANIFEST]) == expected_manifest_sha256,
        "external context manifest hash differs",
    )
    manifest = decode(files[MANIFEST], MANIFEST)
    _check(
        set(manifest)
        == {
            "kind",
            "schema_version",
            "binding",
            "core_run",
            "capture_boundary",
            "captured_at",
            "timestamp_scope",
            "producer",
            "files",
            *FLAGS,
        },
        "manifest fields differ",
    )
    _check(
        manifest["kind"] == CONTRACT
        and manifest["schema_version"] == "1.0.0"
        and all(manifest[k] is v for k, v in FLAGS.items()),
        "context contract or authority differs",
    )
    _check(
        manifest["files"]
        == _inventory({name: raw for name, raw in files.items() if name != MANIFEST}),
        "context inventory differs",
    )
    binding = manifest["binding"]
    _check(set(binding) == set(BINDING_FIELDS), "binding fields differ")
    brief = decode(files["brief.json"], "brief.json")
    basis = binding["binding"]
    _check(
        sha(files["brief.json"]) == basis["brief_sha256"]
        and brief["project_id"] == basis["project_id"]
        and brief["input_version"] == basis["input_version"],
        "brief project/input differs",
    )
    validate_bound_plan(root / "plan", root / "brief.json")
    canonical_bytes = {
        name.removeprefix("canonical/"): raw
        for name, raw in files.items()
        if name.startswith("canonical/")
    }
    canonical_manifest, _, _ = _delivery(
        root / "canonical", binding["manifest_sha256"], canonical_bytes
    )
    _check(
        canonical_manifest["original_input_sha256"] == binding["records_sha256"],
        "canonical records pin differs",
    )
    report = validate_run(root / "ledger", verify_runtime=False)
    _check(
        report["valid"] and report["state_sha256"] == binding["ledger_state_sha256"],
        "saved ledger replay differs",
    )
    journal = Journal(root / "ledger")
    core_run = manifest["core_run"]
    _check(
        core_run
        == dict(
            run_id=journal.manifest["research_run"]["run_id"],
            manifest_sha256=sha(files["ledger/run_manifest.json"]),
            query_owned=core_run.get("query_owned"),
        )
        and type(core_run["query_owned"]) is bool,
        "ledger run manifest differs",
    )
    checkpoints = [
        row["payload"]
        for row in journal.events()
        if row["payload"]["kind"] == "Checkpoint"
    ]
    _check(
        checkpoints and checkpoints[-1]["event_id"] == binding["checkpoint_event_id"],
        "checkpoint differs",
    )
    handoff = journal.read_ref(checkpoints[-1]["stage_result"]["outputs"][-1])
    _check(
        sha(handoff) == binding["handoff_sha256"]
        and json.loads(handoff)["eligible_for_stage2"]
        is binding["eligible_for_stage2"],
        "handoff differs",
    )
    archive = decode(files["resource-history.json"], "resource-history.json")
    saved_run = archive["state"]["stage1_runs"][binding["run_ref"]]
    _check(
        archive["state"]["stage1_active"] == saved_run["run_ref"] == binding["run_ref"]
        and saved_run["manifest_sha256"] == core_run["manifest_sha256"]
        and saved_run["binding"] == binding["binding"]
        and saved_run.get("query_owned", False) is core_run["query_owned"],
        "captured project run differs",
    )
    last = _check_archive(archive, binding)
    boundary = manifest["capture_boundary"]
    _check(
        boundary
        == dict(
            scope="durable-intent-prefix-before-delivery-saved-event",
            project_ref=archive["project_ref"],
            revision=archive["state"]["revision"],
            last_event_id=last,
            state_sha256=sha(canonical(archive["state"])),
        ),
        "capture prefix differs",
    )
    _check(_tree(root) == files, "context changed during replay")
    return dict(
        kind=CONTRACT,
        schema_version="1.0.0",
        status="saved-context-validated",
        manifest_sha256=expected_manifest_sha256,
        binding=binding,
        capture_boundary=boundary,
        counts=report["counts"],
        runtime_attested=False,
        **FLAGS,
    )


def check_saved_context(canonical_root, artifact):
    if "run_context" not in artifact:
        return "legacy-no-run-context"
    descriptor = artifact["run_context"]
    _check(
        type(descriptor) is dict
        and set(descriptor)
        == {
            "kind",
            "schema_version",
            "context_ref",
            "manifest_sha256",
            "status",
            "execution_authorized",
        },
        "saved descriptor differs",
    )
    digest = descriptor["manifest_sha256"]
    _check(
        descriptor
        == dict(
            kind=CONTRACT,
            schema_version="1.0.0",
            context_ref="stage1-context-" + digest[:32],
            manifest_sha256=digest,
            status="captured-validated",
            execution_authorized=False,
        ),
        "saved descriptor invalid",
    )
    root = Path(canonical_root).with_name(Path(canonical_root).name + "-context")
    report = validate_run_context(root, digest)
    _check(
        report["binding"] == {key: artifact[key] for key in BINDING_FIELDS},
        "saved artifact/context differs",
    )
    return "saved-context-validated"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root")
    parser.add_argument("--expected-manifest-sha256", required=True)
    args = parser.parse_args(argv)
    try:
        print(
            json.dumps(
                validate_run_context(Path(args.root), args.expected_manifest_sha256),
                ensure_ascii=False,
            )
        )
        return 0
    except (ValueError, OSError, KeyError, TypeError) as error:
        print(
            json.dumps(dict(status="rejected", error=str(error), **FLAGS)),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
