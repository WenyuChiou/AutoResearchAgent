"""Bind an uploaded Stage 1 file to the existing provided-candidate operation.

No query runtime, model, review, source acquisition or execution permit is made.
Browser input selects an owned material ID, never a filesystem path or actor.
"""

from manual_materials import require


FIELDS = {
    "key",
    "revision",
    "input_version",
    "brief_sha256",
    "confirmed",
    "ledger_state_sha256",
    "project_ref",
    "material_id",
    "material_sha256",
    "record",
    "source_uri",
    "original_type",
    "reason",
}


def admit_material(host, store, credential, body, *, check_deadline):
    from research_workspace_native.session_api import SessionApiError
    from stage1_ledger.contracts import check_record
    from stage1_ledger.identity import work_key
    from stage1_ledger.journal import canonical, digest

    service = getattr(host, "project_stage1", None)
    if not callable(getattr(service, "admit_saved_candidate", None)):
        raise SessionApiError("stage1-provided-admission-unconnected", 409)
    require(set(body) == FIELDS, "provided-material-fields-differ")
    ref = body["project_ref"]
    require(type(ref) is str, "provided-project-required")
    # Authenticate before looking up any material or its original bytes.
    service.intake.read(credential, ref)
    require(type(body["material_id"]) is str, "provided-material-id-required")
    with store.lock:
        item = store._get("materials", body["material_id"])
        require(
            item.get("project_ref") == ref and item.get("stage") == 1,
            "provided-material-project-or-stage-differs",
        )
        require(
            item.get("kind") == "manual-file" and item.get("status") == "registered",
            "provided-complete-upload-required",
        )
        require(
            item["sha256"] == body["material_sha256"], "provided-material-hash-differs"
        )
        store.file_bytes(item["id"])  # Original upload's length and SHA are rechecked.
        record = body["record"]
        require(
            type(record) is dict and type(record.get("version")) is str,
            "provided-record-version-required",
        )
        check_record(record)
        identity = work_key(record)
        request = {
            key: body[key]
            for key in (
                "key",
                "revision",
                "input_version",
                "brief_sha256",
                "confirmed",
                "ledger_state_sha256",
                "material_sha256",
                "record",
                "source_uri",
                "original_type",
                "reason",
            )
        }
        request.update(
            source_project_ref=ref,
            source_relative="files/" + item["id"] + ".bin",
            work_id="work-" + digest(identity.encode()),
            version_id="version-" + digest(canonical([identity, record["version"]])),
        )
        # Core revalidates private paths/bytes, typed version, revision, current
        # ledger, explicit confirmation and idempotency under its original lock.
        return service.admit_saved_candidate(
            credential,
            ref,
            request,
            materials_root=store.root,
            check_deadline=check_deadline,
        )
