"""Observed zero execution is distinct from unavailable native tools."""

import json
from hashlib import sha256

from stage2_common import Stage2Error, canonical_hash

from .no_tool_trace_evidence import _verify_trace_evidence
from .trace_parsing import _tools, _tool_counts


def _fail(reason):
    raise Stage2Error("no-execution-trace-evidence-" + reason)


def _offered_inventory(observation, raw):
    inventories = []
    for call in observation["inferences"]:
        reference = call.get("request_ref")
        if not isinstance(reference, str) or reference not in raw:
            _fail("offered-tools-unresolved")
        request = json.loads(raw[reference])
        definitions = _tools(request)
        inherited = definitions is None
        if inherited:
            offered = observation["threads"][0].get("offered_tools")
            if call.get("tools_inherited") is not True or not isinstance(offered, dict):
                _fail("offered-tools-unresolved")
            definitions = offered.get("definitions")
        if not isinstance(definitions, list):
            _fail("offered-tools-unresolved")
        inventories.append(
            {
                "request_ref": reference,
                "request_sha256": sha256(raw[reference]).hexdigest(),
                "definitions_sha256": canonical_hash(definitions),
                "counts": _tool_counts(definitions),
                "tools_inherited": inherited,
                "tool_choice": request.get("tool_choice"),
            }
        )
    return inventories


def verify_no_execution_trace_evidence(
    archive_provenance,
    trace_root,
    seal_file,
    externally_retained_seal_sha256,
    *,
    expected_config,
):
    """Require observed zero actions, retain available tools, never grant isolation.

    Authenticate the canonical archive first. This explicit policy cannot be
    substituted for strict unavailable-tools proof or a formal readiness gate.
    """
    return _verify_trace_evidence(
        archive_provenance,
        trace_root,
        seal_file,
        externally_retained_seal_sha256,
        expected_config=expected_config,
        offered_tool_mode="record",
    )
