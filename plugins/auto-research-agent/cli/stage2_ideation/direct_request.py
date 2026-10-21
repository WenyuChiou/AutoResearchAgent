"""Create an empty rich Stage 2 seed from externally pinned request bytes."""

import hashlib
import json
from pathlib import Path

from stage1_deliverable.common import private_output
from stage2_common import Stage2Error, canonical_hash, validate_packet
from stage2_common.direct_request import RESOURCES, VERSION, request_brief


def prepare_direct_request(request_path, output_dir, *, expected_request_sha256):
    """No sources, candidates, scope decisions, models or execution authority."""
    try:
        raw = Path(request_path).read_bytes()
        text = raw.decode("utf-8")
    except (OSError, UnicodeError) as error:
        raise Stage2Error(f"direct-request-read-failed: {error}") from error
    digest = hashlib.sha256(raw).hexdigest()
    if digest != expected_request_sha256:
        raise Stage2Error("direct-request-external-hash-mismatch")
    origin = {
        "kind": "Stage2DirectRequestOrigin",
        "schema_version": "1.0.0",
        "request_text": text,
        "request_sha256": digest,
        "stage1_lineage": False,
    }
    origin["binding_sha256"] = canonical_hash(origin)
    packet = {
        "kind": "Stage2Packet",
        "schema_version": VERSION,
        "packet_id": "direct-request-" + digest[:24],
        "brief": request_brief(text),
        "resources": RESOURCES,
        "comparison": "Not researched; no upstream literature is supplied.",
        "literature": [],
        "supplemental_literature": [],
        "evidence": [],
        "sources": [],
        "candidates": [],
        "unresolved": [
            "Research, source verification and independent review are pending."
        ],
        "entry": origin,
        "research_tables": None,
        "prior_work_reviews": [],
    }
    root = private_output(Path(output_dir).absolute())
    validate_packet(packet, root)
    # Exclusive creation prevents silently replacing a previous seed.
    root.mkdir(parents=False)
    path = root / "packet.json"
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(packet, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    return {
        "packet": str(path),
        "packet_sha256": canonical_hash(packet),
        "request_sha256": digest,
        "stage1_lineage": False,
        "scientific_quality_verified": False,
        "user_selection_recorded": False,
        "stage3_authorized": False,
    }
