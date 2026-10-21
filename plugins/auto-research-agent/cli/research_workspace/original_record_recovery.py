"""Recover saved records and exact span locations, without new scientific verdicts."""

from copy import deepcopy
from functools import lru_cache
import csv
import io
import json
import re

from stage1_deliverable.common import (
    DeliverableError,
    canonical,
    inventory,
    private_output,
    safe_path,
    sha,
)

FIELD = "original_record_recovery"
CONTRACT = "S1-ORIGINAL-RECORD-RECOVERY-1.0.0"


def _require(value, message):
    if not value:
        raise DeliverableError("original-record-recovery: " + message)


def _pointer(value, pointer):
    _require(
        isinstance(pointer, str) and (not pointer or pointer.startswith("/")),
        "invalid pointer",
    )
    for part in pointer.split("/")[1:]:
        part = part.replace("~1", "/").replace("~0", "~")
        try:
            value = value[int(part)] if isinstance(value, list) else value[part]
        except (KeyError, IndexError, ValueError, TypeError) as error:
            raise DeliverableError(
                "original-record-recovery: unresolved pointer"
            ) from error
    return value


def _spans(value, text, source_sha256, pointer=""):
    result = []
    if isinstance(value, dict):
        if {"start", "end", "quote"} <= set(value):
            start, end, quote = (value[k] for k in ("start", "end", "quote"))
            _require(
                type(start) is int
                and type(end) is int
                and isinstance(quote, str)
                and bool(quote),
                "invalid saved span",
            )
            exact = 0 <= start <= end <= len(text) and text[start:end] == quote
            first = -1 if exact else text.find(quote)
            second = -1 if first < 0 else text.find(quote, first + 1)
            unique = first >= 0 and second < 0
            result.append(
                dict(
                    pointer=pointer,
                    original=deepcopy(value),
                    source_sha256=source_sha256,
                    state="exact"
                    if exact
                    else "relocated-exact"
                    if unique
                    else "ambiguous"
                    if first >= 0
                    else "quote-not-found",
                    current=dict(start=start, end=end, quote=quote)
                    if exact
                    else dict(start=first, end=first + len(quote), quote=quote)
                    if unique
                    else None,
                    exact_match_count=1
                    if exact or unique
                    else "at-least-2"
                    if second >= 0
                    else 0,
                    scientific_verification=False,
                )
            )
        else:
            for key, item in value.items():
                result.extend(
                    _spans(
                        item,
                        text,
                        source_sha256,
                        pointer + "/" + key.replace("~", "~0").replace("/", "~1"),
                    )
                )
    elif isinstance(value, list):
        for n, item in enumerate(value):
            result.extend(_spans(item, text, source_sha256, pointer + "/" + str(n)))
    return result


def validate_attachment(index, attachment):
    """Check an immutable recovered snapshot against its original Index identity."""
    _require(
        type(attachment) is dict
        and {"manifest_sha256", "payload", "payload_sha256"} <= set(attachment),
        "recovery snapshot fields required",
    )
    _require(attachment.get("contract_version") == CONTRACT, "unknown contract")
    _require(
        attachment.get("scientific_assessment") is False
        and attachment.get("official_stage2_import_eligible") is False,
        "recovery grants no scientific authority",
    )
    payload = attachment["payload"]
    _require(
        sha(canonical(payload)) == attachment["payload_sha256"], "snapshot bytes differ"
    )
    _require(
        "manifest_utf8" in attachment and "artifacts_utf8" in attachment,
        "original evidence snapshot required",
    )
    raw = attachment["manifest_utf8"].encode("utf-8")
    _require(sha(raw) == attachment.get("manifest_sha256"), "manifest bytes differ")
    _require(
        _replay_snapshot(canonical(index), raw, canonical(attachment["artifacts_utf8"]))
        == canonical(payload),
        "recovered evidence or span projection differs",
    )
    _require(
        payload["project_id"] == index["project_id"]
        and payload["input_canonical_sha256"] == sha(canonical(index))
        and payload["records_sha256"] == index["provenance"]["records_sha256"],
        "input identity differs",
    )
    claims = {c["claim_id"]: c for c in index["claims"]}
    seen = set()
    for row in payload["claims"]:
        key = row["claim_id"]
        _require(
            key in claims
            and key not in seen
            and row["original_claim_sha256"] == sha(canonical(claims[key])),
            "claim identity differs",
        )
        seen.add(key)
    works = {(p["work_id"], p["version_id"]) for p in index["papers"]}
    keys = [(r["work_id"], r["version_id"]) for r in payload["works"]]
    _require(len(keys) == len(set(keys)) and set(keys) <= works, "work/version differs")
    return attachment


@lru_cache(maxsize=2)
def _replay_snapshot(index_raw, manifest_raw, artifacts_raw):
    """Cache only exact immutable bytes; any changed input/proof misses the cache."""
    data = {
        name: value.encode("utf-8") for name, value in json.loads(artifacts_raw).items()
    }
    return canonical(_project_recovery(json.loads(index_raw), manifest_raw, data))


def _project_recovery(index, raw, data):
    manifest = json.loads(raw)
    _require(
        manifest.get("kind") == "Stage1OriginalRecordRecovery"
        and manifest.get("schema_version") == "1.0.0",
        "unsupported manifest",
    )
    declared = manifest["files"]
    _require(
        type(declared) is dict
        and 0 < len(declared) <= 512
        and "manifest.json" not in declared,
        "bounded file inventory required",
    )
    _require(set(data) == set(declared), "source inventory differs")
    total = 0
    for name, digest in declared.items():
        _require(
            re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]*", name)
            and not {"", ".", ".."}.intersection(name.split("/")),
            "unsafe evidence path",
        )
        content = data[name]
        _require(len(content) <= 16 * 1024 * 1024, "file bound")
        total += len(content)
        _require(
            total <= 64 * 1024 * 1024 and sha(content) == digest, "source bytes differ"
        )
    spec = json.loads(data["recovery.json"])
    _require(
        len(spec["claims"]) <= 10000
        and len(spec["works"]) <= 10000
        and len(spec["historical_documents"]) <= 512,
        "record bound",
    )
    _require(
        spec["project_id"] == index["project_id"]
        and spec["input_canonical_sha256"] == sha(canonical(index))
        and spec["records_sha256"] == index["provenance"]["records_sha256"],
        "input binding differs",
    )

    resolved_bytes, reference_count = 0, 0

    def reference(ref):
        nonlocal resolved_bytes, reference_count
        _require(
            set(ref) == {"path", "pointer"} and ref["path"] in data,
            "unlisted reference",
        )
        content = data[ref["path"]]
        document = content.decode("utf-8")
        if ref["path"].endswith(".csv"):
            document = list(csv.DictReader(io.StringIO(document.lstrip("\ufeff"))))
        elif ref["pointer"] or ref["path"].endswith(".json"):
            document = json.loads(document)
        value = deepcopy(_pointer(document, ref["pointer"]))
        resolved_bytes += len(canonical(value))
        reference_count += 1
        _require(
            resolved_bytes <= 16 * 1024 * 1024 and reference_count <= 10000,
            "expanded reference bound",
        )
        return dict(
            **ref,
            source_sha256=sha(content),
            value=value,
        )

    claims = {c["claim_id"]: c for c in index["claims"]}
    rows, bound_sources = [], {}
    for row in spec["claims"]:
        claim = claims.get(row["claim_id"])
        _require(
            claim is not None and row["original_claim_sha256"] == sha(canonical(claim)),
            "original claim differs",
        )
        source = data[row["source_path"]]
        source_row = next(
            (
                s
                for s in index["sources"]
                if s["source_id"] == claim["source_id"]
                and (s["work_id"], s["version_id"])
                == (claim["work_id"], claim["version_id"])
            ),
            None,
        )
        _require(
            source_row is not None
            and source_row.get("receipt", {}).get("extracted_text_sha256")
            == sha(source),
            "source text binding differs",
        )
        text = source.decode("utf-8")
        bound_sources[source_row["source_id"]] = (source_row, text)
        _require(
            text[claim["start"] : claim["end"]] == claim["quote"],
            "original quote differs",
        )
        notes = [reference(r) for r in row["notes"]]
        for note in notes:
            original_note = json.loads(data[note["path"]])
            value = note["value"]
            for binding in (
                original_note.get("binding", original_note),
                value,
                value.get("binding", {}) if isinstance(value, dict) else {},
            ):
                if isinstance(binding, dict):
                    for key in ("work_id", "version_id", "source_id"):
                        _require(
                            key not in binding or binding[key] == claim[key],
                            "note identity differs",
                        )
            _require(
                isinstance(value, dict)
                and (
                    value.get("statement") == claim["text"]
                    or any(
                        s.get("text") == claim["text"]
                        for s in value.get("statements", [])
                    )
                ),
                "note assertion differs",
            )
        reason = reference(row["reason"]) if row.get("reason") else None
        if reason:
            reason_claim = reference(row["reason_claim"])
            _require(
                reason_claim["value"] == claim
                and reason_claim["path"] == reason["path"]
                and reason_claim["pointer"].rsplit("/", 1)[0]
                == reason["pointer"].rsplit("/", 1)[0],
                "reason claim binding differs",
            )
        _require(
            reason is None
            or isinstance(reason["value"], str)
            and bool(reason["value"].strip()),
            "reason must be recorded text",
        )
        rows.append(
            dict(
                claim_id=row["claim_id"],
                original_claim_sha256=row["original_claim_sha256"],
                historical_reason=reason,
                notes=notes,
                additional_bindings=[
                    reference(r) for r in row.get("additional_bindings", [])
                ],
                span_checks=[
                    dict(note_path=n["path"], note_pointer=n["pointer"], **s)
                    for n in notes
                    for s in _spans(n["value"], text, sha(source))
                ],
                missing=deepcopy(row["missing"]),
                relation_changed=False,
            )
        )
        if row.get("literal_revisions"):
            from .literal_revisions import apply_literal_revisions

            rows[-1]["span_checks"] = apply_literal_revisions(
                claim,
                rows[-1]["span_checks"],
                [reference(r) for r in row["literal_revisions"]],
                {n["path"]: n["source_sha256"] for n in notes},
                text,
                source_row["receipt"].get("raw_sha256"),
            )
        if row.get("new_assessment"):
            from .source_reassessment import validate_review

            rows[-1]["new_assessment"] = validate_review(
                reference(row["new_assessment"]),
                claim,
                source_row,
                text,
                spec["input_canonical_sha256"],
                claim=True,
            )
    payload = {
        k: spec[k] for k in ("project_id", "input_canonical_sha256", "records_sha256")
    }
    payload.update(
        claims=rows,
        works=[
            dict(
                work_id=r["work_id"],
                version_id=r["version_id"],
                context=[reference(v) for v in r["context"]],
                missing=deepcopy(r["missing"]),
            )
            for r in spec["works"]
        ],
        historical_documents=[
            dict(scope=r["scope"], meaning=r["meaning"], source=reference(r["source"]))
            for r in spec["historical_documents"]
        ],
        missing_originals=deepcopy(spec["missing_originals"]),
        mapping_scope="Declared original references; existing identity fields checked; no independent scientific assessment.",
    )
    for original, projected in zip(spec["works"], payload["works"]):
        if original.get("new_screening_review"):
            from .source_reassessment import validate_review

            review = reference(original["new_screening_review"])
            source_id = review["value"].get("source_id")
            _require(source_id in bound_sources, "review source not bound")
            source_row, text = bound_sources[source_id]
            projected["new_screening_review"] = validate_review(
                review,
                original,
                source_row,
                text,
                spec["input_canonical_sha256"],
                claim=False,
            )
    if spec.get("new_candidate_screening"):
        from .candidate_reassessment import validate_candidates

        payload["new_candidate_screening"] = validate_candidates(
            reference(spec["new_candidate_screening"]),
            reference,
            index,
            spec["input_canonical_sha256"],
        )
    return payload


def attach_original_records(index, recovery_root, expected_manifest_sha256):
    """Read a pinned private bundle; every frozen projection can replay its proof.

    Existing host/API boundaries also require the complete Index's external pin.
    This is source preservation, not reviewer authentication or formal admission.
    """
    from .projection import validate_index

    validate_index(index)
    _require(FIELD not in index, "a recovery is already attached")
    root = private_output(recovery_root)
    raw = safe_path(root, "manifest.json").read_bytes()
    _require(sha(raw) == expected_manifest_sha256, "external manifest hash differs")
    declared = json.loads(raw)["files"]
    _require(type(declared) is dict and len(declared) <= 512, "file inventory bound")
    data = {}
    for name in declared:
        path = safe_path(root, name)
        _require(path.stat().st_size <= 16 * 1024 * 1024, "file bound")
        data[name] = path.read_bytes()
        _require(sum(map(len, data.values())) <= 64 * 1024 * 1024, "package bound")
    _require(
        inventory(root) == {**declared, "manifest.json": sha(raw)}, "inventory differs"
    )
    payload = _project_recovery(index, raw, data)
    result = deepcopy(index)
    result[FIELD] = dict(
        contract_version=CONTRACT,
        manifest_sha256=sha(raw),
        manifest_utf8=raw.decode("utf-8"),
        artifacts_utf8={name: value.decode("utf-8") for name, value in data.items()},
        payload_sha256=sha(canonical(payload)),
        payload=payload,
        scientific_assessment=False,
        official_stage2_import_eligible=False,
    )
    validate_attachment(index, result[FIELD])
    return result
