"""Trusted adoption of an accepted Stage1 input, without inventing user actions.

A ProjectHost reference is local and opaque. Scientific project/version identity
and the confirmed brief bytes remain those of the independently verified source.
This is not a browser route or a research/model execution permit.
"""

from copy import deepcopy
from pathlib import Path
import os

from stage1_brief.brief import validate_brief
from stage1_deliverable.common import identifier, sha
from stage1_ledger.journal import canonical, decode
from .session_api import _check, _hash
from .project_intake_contract import MAX_PROJECTS, MAX_REQUEST


RECEIVING_ROUTE = "stage1-saved-source-receiving-only"


def registration_mode(policy, *, settings=None):
    """Receiving an authenticated input is separate from offering research."""
    if type(policy) is dict and policy.get("route") == RECEIVING_ROUTE:
        _check(
            policy.get("schema_version") == "1.0.0"
            and policy.get("execution_authorized") is False,
            "stage2-receiving-only-policy-required",
            400,
        )
        if settings is not None:
            _check(
                type(settings) is dict
                and settings.get("mode") == RECEIVING_ROUTE
                and settings.get("execution_authorized") is False
                and all(
                    type(settings.get(key)) is int and settings[key] == 0
                    for key in (
                        "model_calls_authorized",
                        "external_queries_authorized",
                        "source_acquisitions_authorized",
                    )
                ),
                "stage2-receiving-only-zero-budget-required",
                400,
            )
        return "receiving-only"
    _check(
        type(policy) is dict
        and policy.get("route") == "stage2-general-v3/daily_v3"
        and policy.get("packet_profile", "legacy-v2") in ("legacy-v2", "scientific-v3"),
        "stage2-daily-v3-policy-reference-required",
        400,
    )
    return "research"


def saved_view_reference(value):
    """An optional trusted declaration pins an existing saved view, not a path."""
    if value is None:
        return None
    _check(
        type(value) is dict
        and set(value) == {"ref", "index_sha256", "manifest_sha256"}
        and type(value["ref"]) is str
        and 0 < len(value["ref"]) <= 64
        and _hash(value["index_sha256"])
        and _hash(value["manifest_sha256"]),
        "stage1-saved-view-reference-invalid",
        400,
    )
    identifier(value["ref"])
    return deepcopy(value)


def import_stage1_project(
    service,
    credential,
    *,
    brief_path,
    expected_brief_sha256,
    settings,
    saved_view=None,
    **registration,
):
    from .project_stage2 import _raw, _verified_inputs

    intake = service.intake
    principal = intake._principal(credential)
    _check(
        type(settings) is dict
        and type(settings.get("resource_envelope")) is str
        and len(canonical(settings)) <= MAX_REQUEST,
        "stage2-import-settings-required",
        400,
    )
    policy = registration.get("policy_ref")
    registration_mode(policy, settings=settings)
    view_ref = saved_view_reference(saved_view)
    raw = _raw(brief_path, expected_brief_sha256, maximum=MAX_REQUEST)
    brief = decode(raw, "confirmed Stage1 brief")
    validate_brief(brief, require_confirmed=True)
    identifier(brief["project_id"])
    inputs = {}
    for source, target in (
        ("deliverable_dir", "deliverable_dir"),
        ("expected_manifest_sha256", "manifest_sha256"),
        ("handoff_path", "handoff_path"),
        ("expected_handoff_sha256", "handoff_sha256"),
        ("resources_path", "resources_path"),
        ("expected_resources_sha256", "resources_sha256"),
        ("saved_source_root", "saved_source_root"),
        ("saved_source_acceptance_sha256", "saved_source_acceptance_sha256"),
        ("host_replay_receipt", "host_replay_receipt"),
        ("trusted_host_replay_sha256", "trusted_host_replay_sha256"),
        ("historical_exporter_root", "historical_exporter_root"),
        ("replayer_exporter_root", "replayer_exporter_root"),
    ):
        value = registration.get(source)
        if value is not None:
            inputs[target] = (
                value if target.endswith("sha256") else str(Path(value).absolute())
            )
    _check(
        "saved_source_root" in inputs and "saved_source_acceptance_sha256" in inputs,
        "stage2-import-saved-admission-required",
        400,
    )
    binding = dict(
        project_id=brief["project_id"],
        input_version=brief["input_version"],
        brief_path=Path(brief_path),
        brief_sha256=expected_brief_sha256,
        settings=deepcopy(settings),
        plan_manifest_sha256=None,
    )
    # Reopen actual external admission and HostReplay receipts before any write.
    _verified_inputs(binding, inputs)
    origin = dict(
        kind="ImportedStage1ProjectContext",
        schema_version="1.0.0",
        project_id=brief["project_id"],
        input_version=brief["input_version"],
        brief_sha256=expected_brief_sha256,
        settings=deepcopy(settings),
        inputs=inputs,
        policy_ref=deepcopy(policy),
        execution_authorized=False,
    )
    if view_ref is not None:
        origin["saved_view"] = view_ref
    origin_raw = canonical(origin)
    _check(len(origin_raw) <= MAX_REQUEST, "stage2-import-context-too-large", 400)
    origin_hash = sha(origin_raw)
    ref = (
        "project-" + sha(canonical(dict(principal=principal, origin=origin_hash)))[:32]
    )
    with intake._lock:
        intake.db.execute("BEGIN IMMEDIATE")
        try:
            existing = intake.db.execute(
                "SELECT principal FROM intake_projects WHERE ref=?", (ref,)
            ).fetchone()
            if existing is not None:
                _check(existing[0] == principal, "project-unavailable", 404)
                state = intake._load(principal, ref)
                _check(
                    state.get("stage1_import", {}).get("sha256") == origin_hash,
                    "stage2-import-origin-differs",
                )
                imported_binding(intake, state)
                intake.db.commit()
            else:
                count = intake.db.execute(
                    "SELECT COUNT(*) FROM intake_projects WHERE principal=?",
                    (principal,),
                ).fetchone()[0]
                _check(count < MAX_PROJECTS, "intake-project-bound-exceeded")
                folder = intake._path(ref, "import")
                folder.mkdir(parents=True, exist_ok=True)
                for name, content in (("brief.json", raw), ("origin.json", origin_raw)):
                    path = intake._path(ref, "import/" + name)
                    if path.exists():
                        with path.open("rb") as existing:
                            retained = existing.read(len(content) + 1)
                        _check(
                            retained == content,
                            "stage2-import-partial-bytes-differ",
                        )
                    else:
                        with path.open("xb") as stream:
                            stream.write(content)
                            stream.flush()
                            os.fsync(stream.fileno())
                state = dict(
                    project_ref=ref,
                    project_id=brief["project_id"],
                    input_version=brief["input_version"],
                    revision=0,
                    briefs=[
                        dict(
                            input_version=brief["input_version"],
                            path="import/brief.json",
                            sha256=sha(raw),
                            raw_utf8=raw.decode("utf-8"),
                        )
                    ],
                    settings=deepcopy(settings),
                    plan=None,
                    stage1_import=dict(path="import/origin.json", sha256=origin_hash),
                )
                intake.db.execute(
                    "INSERT INTO intake_projects VALUES(?,?,?)",
                    (ref, principal, canonical(state).decode()),
                )
                intake._save(
                    state, "stage1-input-imported", dict(origin_sha256=origin_hash)
                )
                intake.db.commit()
        except BaseException:
            intake.db.rollback()
            raise
    offer = service.register(ref, **registration)
    return dict(project_ref=ref, offer=offer, execution_authorized=False)


def imported_binding(intake, state):
    """Recheck immutable import evidence; never substitute a compiled Stage1 plan."""
    saved = state["stage1_import"]
    with intake._path(state["project_ref"], saved["path"]).open("rb") as stream:
        raw = stream.read(MAX_REQUEST + 1)
    _check(len(raw) <= MAX_REQUEST, "stage2-import-context-too-large")
    _check(sha(raw) == saved["sha256"], "stage2-import-origin-bytes-differ")
    events = [
        decode(row[0].encode("utf-8"), "import event")
        for row in intake.db.execute(
            "SELECT payload FROM intake_events WHERE project=? AND kind='stage1-input-imported'",
            (state["project_ref"],),
        )
    ]
    _check(
        events == [dict(origin_sha256=saved["sha256"])],
        "stage2-import-origin-journal-differs",
    )
    origin = decode(raw, "import origin")
    row, path, brief = intake._brief(state)
    validate_brief(brief, require_confirmed=True)
    _check(
        origin["kind"] == "ImportedStage1ProjectContext"
        and origin["schema_version"] == "1.0.0"
        and origin["execution_authorized"] is False
        and origin["project_id"] == state["project_id"] == brief["project_id"]
        and type(origin["input_version"])
        is type(state["input_version"])
        is type(brief["input_version"])
        and origin["input_version"] == state["input_version"] == brief["input_version"]
        and origin["brief_sha256"] == row["sha256"]
        and origin["settings"] == state["settings"]
        and state["plan"] is None,
        "stage2-import-context-differs",
    )
    mode = registration_mode(origin["policy_ref"], settings=state["settings"])
    binding = dict(
        project_id=state["project_id"],
        input_version=state["input_version"],
        brief_path=path,
        brief_sha256=row["sha256"],
        settings=deepcopy(state["settings"]),
        plan_root=None,
        plan_manifest_sha256=None,
        imported_input_sha256=saved["sha256"],
        execution_authorized=False,
    )
    if mode == "receiving-only":
        binding["receiving_only"] = True
    if origin.get("saved_view") is not None:
        binding["saved_view"] = saved_view_reference(origin["saved_view"])
        binding["imported_stage1_inputs"] = deepcopy(origin["inputs"])
    return binding


def load_stage1_imports(service, credential, config_path, expected_sha256):
    """Hash-pinned host bootstrap only; all paths remain on the server."""
    from .project_stage2 import _raw

    config = decode(
        _raw(config_path, expected_sha256, maximum=MAX_REQUEST),
        "Stage1 import configuration",
    )
    _check(
        type(config) is dict
        and set(config) == {"kind", "schema_version", "entries"}
        and config["kind"] == "ProjectStage1ImportConfiguration"
        and config["schema_version"] == "1.0.0"
        and type(config["entries"]) is list
        and 0 < len(config["entries"]) <= MAX_PROJECTS,
        "stage2-import-configuration-invalid",
        400,
    )
    required = {
        "brief_path",
        "expected_brief_sha256",
        "settings",
        "deliverable_dir",
        "expected_manifest_sha256",
        "handoff_path",
        "expected_handoff_sha256",
        "resources_path",
        "expected_resources_sha256",
        "policy_ref",
        "saved_source_root",
        "saved_source_acceptance_sha256",
    }
    optional = {
        "host_replay_receipt",
        "trusted_host_replay_sha256",
        "historical_exporter_root",
        "replayer_exporter_root",
        "saved_view",
    }
    _check(
        all(
            type(row) is dict and required <= set(row) <= required | optional
            for row in config["entries"]
        ),
        "stage2-import-configuration-fields-invalid",
        400,
    )
    return [
        service.import_stage1_project(credential, **row) for row in config["entries"]
    ]
