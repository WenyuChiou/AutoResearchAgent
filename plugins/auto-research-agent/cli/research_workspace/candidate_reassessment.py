"""New screening of saved observations, never reconstruction of missing history."""

from copy import deepcopy
from datetime import datetime
import re
from urllib.parse import parse_qsl, unquote, urlencode, urlsplit

from stage1_deliverable.common import DeliverableError, canonical, sha


def _url_key(url):
    parsed = urlsplit(url or "")
    host, path = (
        parsed.netloc.lower().removeprefix("www."),
        unquote(parsed.path).rstrip("/"),
    )
    if host == "arxiv.org" and re.match(r"^/(abs|pdf|html)/", path):
        return "arxiv:" + re.sub(
            r"v\d+$", "", path.split("/", 2)[2].removesuffix(".pdf")
        )
    query = [
        (k, v)
        for k, v in parse_qsl(parsed.query)
        if not k.startswith("utm_") and k not in {"trk", "fbclid"}
    ]
    return host + path + ("?" + urlencode(sorted(query)) if query else "")


def validate_candidates(reference, resolve, index, input_sha256):
    def require(value, message):
        if not value:
            raise DeliverableError("candidate-reassessment: " + message)

    value = reference["value"]
    require(
        value.get("kind") == "NewSavedCandidateScreening"
        and value.get("scope") == "saved-observations-only"
        and value.get("not_historical") is True
        and value.get("input_canonical_sha256") == input_sha256,
        "scope differs",
    )
    reviewer = value.get("reviewer", {})
    require(
        reviewer.get("type") in {"ai", "human"}
        and isinstance(reviewer.get("identity"), str)
        and reviewer["identity"].strip()
        and reviewer.get("authenticated") is False,
        "declared reviewer required",
    )
    try:
        moment = datetime.fromisoformat(value["reviewed_at"].replace("Z", "+00:00"))
        require(moment.tzinfo is not None, "timezone required")
    except (KeyError, ValueError, TypeError, AttributeError) as error:
        raise DeliverableError("candidate-reassessment: invalid review time") from error
    observations = resolve(value["observations_ref"])["value"]
    require(
        type(observations) is list and 0 < len(observations) <= 5000,
        "observation bound",
    )
    by_id = {o["observation_ref"]: o for o in observations}
    captures = {key: resolve(ref) for key, ref in value.get("captures", {}).items()}
    require(0 < len(captures) <= 512, "saved capture proof required")
    require(len(by_id) == len(observations), "duplicate original observation")
    rows = value.get("rows")
    require(
        type(rows) is list and len(rows) == len(observations),
        "complete saved cohort required",
    )
    seen, works = set(), {p["work_id"] for p in index["papers"]}
    urls = {}
    for record in [*index["papers"], *index["sources"]]:
        receipt = record.get("receipt", {})
        candidates = [record.get("url"), receipt.get("url"), receipt.get("final_url")]
        candidates += [
            a.get(k) for a in receipt.get("attempts", []) for k in ("url", "final_url")
        ]
        urls.setdefault(record["work_id"], set()).update(
            _url_key(u) for u in candidates if u
        )
    for row in rows:
        key = row.get("observation_ref")
        original = by_id.get(key)
        require(
            original is not None and key not in seen, "observation identity differs"
        )
        require(
            row.get("original_observation_sha256") == sha(canonical(original)),
            "observation bytes differ",
        )
        require(
            row.get("title_observed") == original.get("title_observed")
            and row.get("url_observed") == original.get("url_observed"),
            "observation display differs",
        )
        evidence = row.get("saved_evidence", {})
        capture = captures.get(evidence.get("batch_ref"), {})
        text, start, end = (
            capture.get("value"),
            evidence.get("start"),
            evidence.get("end"),
        )
        require(
            capture.get("source_sha256")
            == evidence.get("source_sha256")
            == original.get("saved_receipt_ref", {}).get("sha256")
            and evidence.get("batch_ref") == original.get("batch_ref")
            and isinstance(text, str)
            and type(start) is int
            and type(end) is int
            and 0 <= start < end <= len(text)
            and text[start:end] == evidence.get("quote"),
            "saved screening evidence differs",
        )
        lines = text.splitlines(keepends=True)
        line = original.get("raw_header_line")
        require(type(line) is int and 1 <= line <= len(lines), "header line differs")
        later = [
            o["raw_header_line"] - 1
            for o in observations
            if o["batch_ref"] == original["batch_ref"] and o["raw_header_line"] > line
        ]
        block_start, block_end = (
            sum(map(len, lines[: line - 1])),
            sum(map(len, lines[: min(later)])) if later else len(text),
        )
        require(
            block_start <= start < end <= block_end
            and original["title_observed"] in lines[line - 1]
            and original["url_observed"] in lines[line - 1],
            "evidence is outside its original result block",
        )
        require(
            row.get("decision") in {"include", "exclude", "pending", "duplicate"}
            and isinstance(row.get("rationale"), str)
            and 24 <= len(row["rationale"].strip().encode("utf-8")) <= 8192
            and isinstance(row.get("reason_code"), str)
            and row["reason_code"].strip(),
            "specific decision required",
        )
        if row["decision"] == "include":
            require(
                row.get("linked_work_id") in works,
                "included work not in saved source inventory",
            )
            require(
                _url_key(original["url_observed"]) in urls[row["linked_work_id"]],
                "included URL does not identify the saved work",
            )
        if row["decision"] == "duplicate":
            prior = row.get("repeat_of")
            require(
                prior in seen
                and original.get("url_observed") is not None
                and original["url_observed"] == by_id[prior].get("url_observed"),
                "repeat requires an earlier identical saved URL; not scholarly deduplication",
            )
        seen.add(key)
    result = deepcopy(reference)
    result["observations"] = deepcopy(observations)
    result["counts"] = {
        d: sum(r["decision"] == d for r in rows)
        for d in ("include", "exclude", "pending", "duplicate")
    }
    result["counts"]["saved_observations"] = len(rows)
    result["historical_candidate_total"] = "Unknown"
    return result
