"""Complete source representations for auditing, separate from historical views.

Callers must replay-validate source acquisition before supplying the full records.
This transformation binds representations; it does not verify scientific claims.
"""

from copy import deepcopy

from .common import EvaluationError, canonical, sha

KIND = "Stage1AuditSourceMaterialization.v1"


def materialize_audit_sources(packet, source_records):
    """Keep full abstracts and identity metadata at their distinct evidence levels."""
    if not isinstance(source_records, list):
        raise EvaluationError("complete source catalogue must be a list")
    catalog, occurrences = {}, {}
    for number, record in enumerate(source_records):
        if not isinstance(record, dict) or not isinstance(record.get("source_id"), str):
            raise EvaluationError("invalid complete source record")
        key = record["source_id"]
        if not key or (key in catalog and canonical(catalog[key]) != canonical(record)):
            raise EvaluationError("conflicting complete source records")
        catalog[key] = record
        occurrences.setdefault(key, []).append(number)
    result, derivations, exclusions = deepcopy(packet), [], []
    for key, record in catalog.items():
        if key not in packet["sources"]:
            if record.get("date_status") != "after-cutoff":
                raise EvaluationError("complete source is absent from the input packet")
            exclusions.append(
                {
                    "source_id": key,
                    "record_sha256": sha(canonical(record)),
                    "reason": "after-cutoff",
                }
            )
    for key, source in packet["sources"].items():
        old = packet["content_evidence"].get(key)
        if not isinstance(old, dict) or source.get("source_id") != key:
            raise EvaluationError("source evidence binding is missing")
        if key not in catalog:
            if (
                not old.get("artifact_path")
                or not old.get("source_version")
                or old["source_version"] != source.get("version_id")
                or old.get("subject_work_id") != source.get("subject_work_id")
            ):
                raise EvaluationError("complete source record is missing")
            continue  # Already materialized public text; retain its original binding.
        record = catalog[key]
        if canonical(
            {field: value for field, value in record.items() if field != "abstract"}
        ) != canonical(source):
            raise EvaluationError(
                "complete source metadata or version differs from packet"
            )
        if not isinstance(record.get("abstract"), str):
            raise EvaluationError("complete abstract must be a string")
        if source.get("source_level") not in {"abstract", "metadata"}:
            raise EvaluationError("unsupported catalogue evidence level")
        if not isinstance(source.get("version_id"), str) or not source["version_id"]:
            raise EvaluationError("complete source version is missing")
        record_sha = sha(canonical(record))
        identity_text = canonical(
            record if source["source_level"] == "metadata" else source
        ).decode("utf-8")
        abstract = record["abstract"]

        def evidence(text, field, level):
            return {
                "text": text,
                "sha256": sha(text.encode("utf-8")),
                "origin": old["origin"],
                "subject_work_id": source.get("subject_work_id"),
                "source_version": source.get("version_id"),
                "source_level": level,
                "source_record_sha256": record_sha,
                "raw_source_sha256": record.get("raw_sha256"),
                "locator": [
                    {
                        "type": "json-field"
                        if field == "abstract"
                        else "derived-identity-projection",
                        "value": field,
                        "record_sha256": record_sha,
                        "start": 0,
                        "end": len(text),
                    }
                ],
            }

        ids = [key]
        if source["source_level"] == "abstract":
            if not abstract:
                raise EvaluationError("abstract-level source has no abstract")
            identity_id = key + ":identity"
            if (
                identity_id in packet["sources"]
                or identity_id in packet["content_evidence"]
            ):
                raise EvaluationError("derived identity evidence ID collision")
            result["content_evidence"][key] = evidence(abstract, "abstract", "abstract")
            result["content_evidence"][identity_id] = evidence(
                identity_text, "metadata", "metadata"
            )
            result["sources"][identity_id] = {
                **source,
                "source_id": identity_id,
                "source_level": "metadata",
                "related_source_id": key,
            }
            result["source_origins"][identity_id] = deepcopy(
                packet["source_origins"][key]
            )
            ids.append(identity_id)
        else:
            result["content_evidence"][key] = evidence(
                identity_text, "metadata", "metadata"
            )
        derivations.append(
            {
                "source_id": key,
                "source_record_sha256": record_sha,
                "catalogue_occurrence_indices": occurrences[key],
                "original_projection_sha256": sha(canonical(old)),
                "derived_evidence_ids": ids,
                "reason": "replace clipped combined view with complete abstract and distinct identity metadata",
            }
        )
    receipt = {
        "kind": KIND,
        "input_packet_sha256": sha(canonical(packet)),
        "source_catalogue_sha256": sha(canonical(source_records)),
        "materialized_packet_sha256": sha(canonical(result)),
        "derivations": derivations,
        "exclusions": exclusions,
        "semantic_audit_completed": False,
    }
    return result, receipt


def verify_audit_materialization(packet, source_records, result, receipt):
    expected = materialize_audit_sources(packet, source_records)
    if canonical((result, receipt)) != canonical(expected):
        raise EvaluationError("source audit materialization failed reconstruction")
    return True
