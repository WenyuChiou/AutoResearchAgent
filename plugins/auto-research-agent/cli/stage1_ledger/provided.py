"""Explicit saved candidate admission, without a search or identity attestation."""

from urllib.parse import urlsplit

from .contracts import check, check_record
from .identity import candidate_revision, work_key
from .journal import LedgerError, canonical, decode, digest
from .source_arguments import check_source_arguments


def discovery_order(discovery):
    event = (discovery.get("provided") or {}).get("event_id") or discovery[
        "completion_id"
    ]
    return int(event[1:]), discovery["record_index"]


def check_identity(record, work_id, version_id):
    check_record(record)
    if not record.get("version"):
        raise LedgerError("provided-version-required")
    key = work_key(record)
    expected_work = "work-" + digest(key.encode())
    expected_version = "version-" + digest(canonical([key, record["version"]]))
    if (work_id, version_id) != (expected_work, expected_version):
        raise LedgerError("provided-work-version-differs")


def provided_revision(previous, *, record, provenance, source_ref):
    """Reuse work/version and conservative identity aggregation; no fake backend."""
    event_id = provenance["event_id"]
    value = candidate_revision(
        previous,
        record=record,
        completion=dict(event_id=event_id, attempt_id=None, records=source_ref),
        query_id=None,
        index=0,
    )
    discovery = value["discoveries"][-1]
    discovery.update(
        discovery_id="provided:"
        + digest(
            canonical(
                [record, {k: v for k, v in provenance.items() if k != "event_id"}]
            )
        ),
        completion_id=None,
        provided=provenance,
    )
    return value


def check_provided(discovery, read_ref, manifest):
    provenance = discovery["provided"]
    check(provenance, "ProvidedCandidateProvenance")
    check_record(discovery["record"])
    work_key(discovery["record"])
    for ref in (discovery["source_ref"], provenance["material_ref"]):
        if (
            ref["artifact_type"] != "provided-material"
            or ref["producer"] != "stage1-provider"
        ):
            raise LedgerError("provided-artifact-producer-differs")
    if not discovery["record"].get("version"):
        raise LedgerError("provided-version-required")
    url = provenance["source_uri"]
    check_source_arguments(dict(kind="SourceImportStarted", source_uri=url))
    parts = urlsplit(url)
    if (
        parts.scheme not in {"http", "https"}
        or not parts.hostname
        or parts.username
        or parts.password
    ):
        raise LedgerError("provided-public-url-required")
    if provenance["manifest_sha256"] != digest(canonical(manifest)):
        raise LedgerError("provided-run-binding-differs")
    if decode(read_ref(discovery["source_ref"]), "provided record") != [
        discovery["record"]
    ]:
        raise LedgerError("provided-record-bytes-differ")
    read_ref(provenance["material_ref"])


def admit(
    ledger,
    *,
    record,
    material,
    material_sha256,
    source_uri,
    original_type,
    actor,
    reason,
    expected_state_sha256,
    expected_manifest_sha256,
    work_id,
    version_id,
):
    """Called under the ledger writer; all validation precedes saved bytes."""
    from .validation import validate_run

    if not validate_run(ledger.root)["valid"]:
        raise LedgerError("provided-invalid-ledger")
    if expected_state_sha256 != ledger.state_hash():
        raise LedgerError("provided-state-stale")
    if expected_manifest_sha256 != digest(canonical(ledger.manifest)):
        raise LedgerError("provided-run-binding-differs")
    if digest(material) != material_sha256:
        raise LedgerError("provided-material-hash-differs")
    if (
        max(len(material), len(canonical([record])))
        > ledger.manifest["max_artifact_bytes"]
    ):
        raise LedgerError("artifact-size-limit")
    check_identity(record, work_id, version_id)
    # Validate the entire future event before writing either artifact.
    ref = dict(
        kind="ArtifactRef",
        schema_version="1.0.0",
        artifact_id="placeholder",
        artifact_type="provided-material",
        path="raw/" + material_sha256 + ".bin",
        sha256=material_sha256,
        producer="stage1-provider",
        created_at=ledger.clock(),
    )
    provenance = dict(
        event_id="e000001",
        source_uri=source_uri,
        original_type=original_type,
        actor=actor,
        reason=reason,
        identity_status="unverified",
        scope="caller-attested-external-material-not-search",
        material_ref=ref,
        manifest_sha256=expected_manifest_sha256,
    )
    check(provenance, "ProvidedCandidateProvenance")
    parts = urlsplit(source_uri)
    check_source_arguments(dict(kind="SourceImportStarted", source_uri=source_uri))
    if (
        parts.scheme not in {"http", "https"}
        or not parts.hostname
        or parts.username
        or parts.password
    ):
        raise LedgerError("provided-public-url-required")
    previous = ledger.candidates().get(work_id)
    if previous:
        for discovery in previous["discoveries"]:
            p = discovery.get("provided")
            if (
                p
                and discovery["record"] == record
                and p["source_uri"] == source_uri
                and p["original_type"] == original_type
                and p["material_ref"]["sha256"] == material_sha256
            ):
                return dict(
                    work_id=work_id,
                    version_id=version_id,
                    event_id=p["event_id"],
                    reused=True,
                )
    # _save bounds bytes, fsyncs them, then journals the immutable references.
    material_ref = ledger._save(
        material, producer="stage1-provider", artifact_type="provided-material"
    )
    source_ref = ledger._save(
        canonical([record]),
        producer="stage1-provider",
        artifact_type="provided-material",
    )
    provenance.update(
        material_ref=material_ref, event_id=f"e{len(ledger.events()) + 1:06d}"
    )
    value = provided_revision(
        previous, record=record, provenance=provenance, source_ref=source_ref
    )
    check_provided(value["discoveries"][-1], ledger.read_ref, ledger.manifest)
    event = ledger.append(value)
    return dict(
        work_id=work_id, version_id=version_id, event_id=event["event_id"], reused=False
    )
