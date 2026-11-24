"""Owner-bound admission of an operator-provided material, without execution."""

from stage1_deliverable.common import private_output, reject_links, safe_path
from stage1_ledger.journal import canonical, digest
from stage1_ledger.provided import check_identity, prepare

from .session_api import _check


FIELDS = {
    "source_project_ref",
    "source_relative",
    "material_sha256",
    "source_uri",
    "original_type",
    "record",
    "work_id",
    "version_id",
    "reason",
}


def execute(
    service, credential, project_ref, body, *, materials_root, check_deadline=None
):
    """The application owner selects the root; callers cannot supply a root."""
    root = private_output(materials_root)

    def request(ledger, actor):
        _check(body["source_project_ref"] == project_ref, "provided-project-differs")
        check_identity(body["record"], body["work_id"], body["version_id"])
        path = safe_path(root, body["source_relative"])
        reject_links(path)
        _check(path.is_file(), "provided-regular-file-required")
        with path.open("rb") as stream:
            material = stream.read(ledger.manifest["max_artifact_bytes"] + 1)
        _check(
            digest(material) == body["material_sha256"],
            "provided-material-hash-differs",
        )
        return dict(
            record=body["record"],
            material=material,
            material_sha256=body["material_sha256"],
            source_uri=body["source_uri"],
            original_type=body["original_type"],
            actor=actor,
            reason=body["reason"],
            expected_state_sha256=body["ledger_state_sha256"],
            expected_manifest_sha256=digest(canonical(ledger.manifest)),
            work_id=body["work_id"],
            version_id=body["version_id"],
        )

    def preflight(_state, _run, ledger, _report, actor):
        prepare(ledger, **request(ledger, actor))

    def producer(_state, _run, ledger, _request_hash, actor):
        return ledger.admit_saved_candidate(**request(ledger, actor))

    return service._mutate(
        credential,
        project_ref,
        body,
        "stage1-admit-saved-candidate",
        producer,
        fields=FIELDS,
        preflight=preflight,
        check_deadline=check_deadline,
    )
