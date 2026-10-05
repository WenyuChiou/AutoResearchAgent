"""Parsing helpers for native trace inference requests and responses."""

from stage2_common import canonical_hash

from .trace_files import _fail, _require

MAX_TOOL_DEFINITIONS = 256
MAX_TOOL_DEPTH = 8


def _tools(request):
    _require(isinstance(request, dict), "inference-request-invalid")
    top_level = None
    if "tools" in request:
        _require(isinstance(request["tools"], list), "top-level-tools-invalid")
        top_level = request["tools"]
    additional = []
    additional_supplied = False
    inputs = request.get("input")
    _require(isinstance(inputs, list), "inference-request-input-invalid")
    for item in inputs:
        _require(isinstance(item, dict), "inference-request-input-invalid")
        if item.get("type") == "additional_tools":
            if item.get("role") != "developer" or not isinstance(
                item.get("tools"), list
            ):
                _fail("additional-tools-invalid")
            additional.extend(item["tools"])
            additional_supplied = True
    if top_level is not None and additional_supplied:
        _require(top_level == additional, "offered-tools-alias-mismatch")
        return top_level
    if top_level is not None:
        return top_level
    return additional if additional_supplied else None


def _tool_counts(definitions):
    counts = {"namespace": 0, "custom": 0, "function": 0, "other": 0}
    seen = 0

    def visit(row, depth):
        nonlocal seen
        _require(
            isinstance(row, dict) and isinstance(row.get("type"), str),
            "tool-definition-invalid",
        )
        seen += 1
        _require(
            seen <= MAX_TOOL_DEFINITIONS and depth <= MAX_TOOL_DEPTH,
            "tool-definition-limit",
        )
        kind = row["type"]
        counts[kind if kind in counts else "other"] += 1
        nested = row.get("tools", [])
        _require(isinstance(nested, list), "tool-definition-invalid")
        for item in nested:
            visit(item, depth + 1)

    for definition in definitions:
        visit(definition, 1)
    return counts


def _usage(response):
    _require(isinstance(response, dict), "inference-response-invalid")
    usage = response.get("token_usage")
    fields = (
        "input_tokens",
        "cached_input_tokens",
        "cache_write_input_tokens",
        "output_tokens",
        "reasoning_output_tokens",
        "total_tokens",
    )
    if usage is None:
        return None
    if not isinstance(usage, dict) or any(
        isinstance(usage.get(key), bool)
        or not isinstance(usage.get(key), int)
        or usage[key] < 0
        for key in fields
    ):
        _fail("token-usage-invalid")
    if (
        usage["cached_input_tokens"] > usage["input_tokens"]
        or usage["cache_write_input_tokens"] > usage["input_tokens"]
        or usage["reasoning_output_tokens"] > usage["output_tokens"]
    ):
        _fail("token-usage-subset-mismatch")
    if usage["total_tokens"] != usage["input_tokens"] + usage["output_tokens"]:
        _fail("token-usage-total-mismatch")
    return {key: usage[key] for key in fields}


def summarize_inferences(
    inferences,
    responses,
    blockers,
    compaction_attempts,
    compaction_accounting_unverified,
):
    """Resolve offered tools and token usage for parsed inference events."""
    thread_tools = {}
    inference_rows, usage_rows = [], []
    for call_id, item in sorted(inferences.items(), key=lambda value: value[1]["seq"]):
        request = item["request"]
        definitions = _tools(request)
        inherited = False
        if definitions is None:
            previous = request.get("previous_response_id")
            if "previous_response_id" in request and not isinstance(previous, str):
                _fail("previous-response-id-invalid")
            prior = responses.get(previous)
            if (
                isinstance(prior, dict)
                and prior.get("terminal") == "inference_completed"
                and type(prior.get("completion_seq")) is int
                and 0 < prior["completion_seq"] < item["seq"]
                and prior.get("thread_id") == item["thread_id"]
            ):
                definitions = prior.get("resolved_tools")
                inherited = definitions is not None
        item["resolved_tools"] = definitions
        if definitions is None:
            blockers.append(f"offered-tools-unknown:{call_id}")
        else:
            digest = canonical_hash(definitions)
            existing = thread_tools.get(item["thread_id"])
            if existing is not None and existing["sha256"] != digest:
                blockers.append(f"offered-tools-ambiguous:{item['thread_id']}")
            thread_tools[item["thread_id"]] = {
                "definitions": definitions,
                "sha256": digest,
                "counts": _tool_counts(definitions),
            }
        usage = (
            _usage(item["response"])
            if item["terminal"] == "inference_completed"
            else None
        )
        if item["terminal"] is None:
            blockers.append(f"inference-terminal-missing:{call_id}")
        if usage is None:
            blockers.append(f"token-usage-unknown:{call_id}")
        else:
            usage_rows.append(usage)
        inference_rows.append(
            {
                "inference_call_id": call_id,
                "thread_id": item["thread_id"],
                "codex_turn_id": item["codex_turn_id"],
                "status": item["terminal"] or "incomplete",
                "request_ref": item["request_ref"],
                "request_sha256": item["request_sha256"],
                "response_ref": item.get("response_ref"),
                "response_sha256": item.get("response_sha256"),
                "tools_inherited": inherited,
                "token_usage": usage,
            }
        )
    compaction_usage = [
        _usage({"token_usage": value}) if value is not None else None
        for value in compaction_attempts.values()
    ]
    if compaction_accounting_unverified:
        blockers.append("compaction-accounting-unverified")
    if any(value is None for value in compaction_usage):
        blockers.append("compaction-usage-missing")
    totals = None
    if (
        len(usage_rows) == len(inference_rows)
        and not compaction_accounting_unverified
        and all(value is not None for value in compaction_usage)
    ):
        all_usage = usage_rows + compaction_usage
        totals = {
            key: sum(row[key] for row in all_usage)
            for key in ("input_tokens", "output_tokens", "total_tokens")
        }
    return inference_rows, thread_tools, totals
