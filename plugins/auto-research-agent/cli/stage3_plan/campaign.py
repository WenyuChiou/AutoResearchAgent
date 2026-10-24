"""Bounded, offline campaign preparation and deterministic read-only replay."""

import hashlib
from pathlib import Path

from .campaign_views import assessor_view
from .contracts import Stage3Error, canonical_bytes, digest
from .evaluation import inspect_evaluation_request
from .preparation import closed, file_binding, sha256, text
from .storage import MAX_ARTIFACT_BYTES, private_output, read_bytes, write_new

POLICY = dict.fromkeys(
    (
        "execution_authorized",
        "evaluation_calls_authorized",
        "formal_execution_enabled",
        "external_claim_ready",
    ),
    False,
)
SELECTION_FIELDS = {
    "intake_sha256",
    "source_manifest_sha256",
    "selected_candidates",
    "question_refs",
}


def binding(path):
    return {"path": str(path), "sha256": hashlib.sha256(read_bytes(path)).hexdigest()}


def pinned(ref):
    closed(ref, {"path", "sha256"}, "artifact binding")
    if not isinstance(ref["path"], str) or not Path(ref["path"]).is_absolute():
        raise Stage3Error("absolute artifact path required")
    try:
        return file_binding(ref["path"], ref["sha256"])
    except (RecursionError, UnicodeError) as error:
        raise Stage3Error("invalid bounded pinned JSON") from error


def positive(value, maximum, label):
    if type(value) is not int or not 0 < value <= maximum:
        raise Stage3Error(f"{label} exceeds the positive bounded limit")


def build_campaign(definition, *, definition_sha256):
    sha256(definition_sha256)
    closed(
        definition,
        {
            "kind",
            "schema_version",
            "campaign_id",
            "seed",
            "repetitions",
            "cases",
            "arms",
            "runtime",
            "roles",
            "subject_order",
            "display_order",
            "limits",
            "analysis",
        },
        "campaign definition",
    )
    if (
        definition["kind"] != "Stage3CampaignDefinition"
        or definition["schema_version"] != "1.0.0"
    ):
        raise Stage3Error("unsupported campaign version")
    text(definition["campaign_id"], "campaign id")
    if type(definition["seed"]) is not int:
        raise Stage3Error("integer schedule seed required")
    closed(definition["limits"], {"max_units", "max_view_bytes"}, "campaign limits")
    positive(definition["limits"]["max_units"], 4096, "work units")
    positive(
        definition["limits"]["max_view_bytes"],
        16 * MAX_ARTIFACT_BYTES,
        "total view bytes",
    )
    positive(definition["repetitions"], 4096, "repetitions")
    closed(definition["arms"], {"A", "B"}, "arms")
    for arm in definition["arms"].values():
        closed(arm, {"build_sha256", "protocol"}, "arm protocol")
        sha256(arm["build_sha256"])
        text(arm["protocol"], "arm protocol")
    closed(
        definition["runtime"],
        {"model", "reasoning", "tool_policy", "timeout_seconds"},
        "runtime",
    )
    for name in ("model", "reasoning"):
        text(definition["runtime"][name], name)
    if definition["runtime"]["tool_policy"] != "none":
        raise Stage3Error("explicit no-tool runtime required")
    positive(definition["runtime"]["timeout_seconds"], 2**31 - 1, "deadline")
    closed(definition["roles"], {"R1", "R2", "ADJ"}, "configured roles")
    for role in definition["roles"].values():
        closed(role, {"model", "reasoning"}, "role configuration")
        for value in role.values():
            text(value, "role setting")
    closed(
        definition["analysis"],
        {"version", "case_rule", "audit_triggers"},
        "analysis spec",
    )
    if (
        definition["analysis"]["version"] != "1.0.0"
        or definition["analysis"]["case_rule"] != "pareto-over-planned-pairs"
    ):
        raise Stage3Error("explicit supported case-level ordinal analysis required")
    triggers = definition["analysis"]["audit_triggers"]
    if (
        not isinstance(triggers, list)
        or not triggers
        or any(
            not isinstance(t, str)
            or t not in {"disagreement", "unverifiable", "grader_error", "score-zero"}
            for t in triggers
        )
        or len(set(triggers)) != len(triggers)
    ):
        raise Stage3Error("explicit supported unique audit triggers required")
    for key in ("subject_order", "display_order"):
        if definition[key] not in ("AB", "BA", "seeded"):
            raise Stage3Error("subject/display order must be explicit AB, BA or seeded")
    cases = definition["cases"]
    if not isinstance(cases, list) or not cases:
        raise Stage3Error("nonempty cases required")
    planned = len(cases) * definition["repetitions"] * 2 * len(definition["roles"])
    if planned > definition["limits"]["max_units"]:
        raise Stage3Error("planned work exceeds configured work-unit bound")
    seen, splits, units, schedule, views = set(), {}, [], [], {}
    for case in cases:
        closed(
            case,
            {
                "case_id",
                "base_case_id",
                "variant",
                "research_type",
                "split",
                "selection",
                "subjects",
            },
            "case",
        )
        for key in ("case_id", "base_case_id", "variant", "research_type", "split"):
            text(case[key], key)
        if case["case_id"] in seen:
            raise Stage3Error("duplicate case")
        seen.add(case["case_id"])
        base = case["base_case_id"]
        if splits.setdefault(base, case["split"]) != case["split"]:
            raise Stage3Error("base case leaks across calibration/held-out splits")
        closed(case["selection"], SELECTION_FIELDS, "declared selection")
        for key in ("intake_sha256", "source_manifest_sha256"):
            sha256(case["selection"][key])
        if (
            not isinstance(case["selection"]["question_refs"], list)
            or not case["selection"]["question_refs"]
            or not isinstance(case["selection"]["selected_candidates"], list)
            or not case["selection"]["selected_candidates"]
        ):
            raise Stage3Error("declared candidate/version and all SQ refs required")
        for candidate in case["selection"]["selected_candidates"]:
            closed(
                candidate, {"candidate_id", "candidate_version"}, "selected candidate"
            )
            text(candidate["candidate_id"], "candidate id")
            positive(candidate["candidate_version"], 2**31 - 1, "candidate version")
        if any(
            not isinstance(q, str) or not q for q in case["selection"]["question_refs"]
        ) or len(set(case["selection"]["question_refs"])) != len(
            case["selection"]["question_refs"]
        ):
            raise Stage3Error("unique question refs required")
        subjects = {}
        if not isinstance(case["subjects"], list):
            raise Stage3Error("subject bindings must be a list")
        for row in case["subjects"]:
            closed(row, {"repeat", "arm", "request", "failure"}, "subject")
            positive(row["repeat"], definition["repetitions"], "subject repeat")
            if (
                row["arm"] not in ("A", "B")
                or (row["repeat"], row["arm"]) in subjects
                or (row["request"] is not None and row["failure"] is not None)
            ):
                raise Stage3Error("duplicate/invalid subject identity or state")
            subjects[row["repeat"], row["arm"]] = row
        for repeat in range(1, definition["repetitions"] + 1):
            orders = {}
            for key in ("subject_order", "display_order"):
                mode = definition[key]
                orders[key] = (
                    list(mode)
                    if mode != "seeded"
                    else sorted(
                        ("A", "B"),
                        key=lambda arm: digest(
                            [definition["seed"], key, case["case_id"], repeat, arm]
                        ),
                    )
                )
            schedule.append({"case_id": case["case_id"], "repeat": repeat, **orders})
            for arm in orders["subject_order"]:
                row = subjects.get((repeat, arm), {"request": None, "failure": None})
                subject_id = (
                    "subject-"
                    + digest([definition["campaign_id"], case["case_id"], repeat, arm])[
                        :32
                    ]
                )
                request, aliases = None, {}
                if row["request"] is not None:
                    pinned(row["request"])
                    request = inspect_evaluation_request(
                        row["request"]["path"], expected_sha256=row["request"]["sha256"]
                    )
                    if {k: request["bindings"][k] for k in SELECTION_FIELDS} != case[
                        "selection"
                    ]:
                        raise Stage3Error(
                            "subject does not match declared source/selection/SQ"
                        )
                    view, aliases = assessor_view(request, subject_id)
                    view["request_sha256"] = row["request"]["sha256"]
                    views[subject_id] = view
                if row["failure"] is not None:
                    closed(row["failure"], {"path", "sha256"}, "subject failure")
                    if not Path(row["failure"]["path"]).is_absolute():
                        raise Stage3Error("absolute subject failure path required")
                    sha256(row["failure"]["sha256"])
                    if (
                        hashlib.sha256(read_bytes(row["failure"]["path"])).hexdigest()
                        != row["failure"]["sha256"]
                    ):
                        raise Stage3Error("subject failure hash mismatch")
                for role in sorted(definition["roles"]):
                    units.append(
                        {
                            "unit_id": digest([subject_id, role]),
                            "subject_id": subject_id,
                            "case_id": case["case_id"],
                            "base_case_id": base,
                            "repeat": repeat,
                            "arm": arm,
                            "role": role,
                            "request": row["request"],
                            "failure": row["failure"],
                            "aliases": aliases,
                            "source_scope": request["bindings"]["admission_scope"]
                            if request
                            else "declared-unverified",
                            "plan_binding": request["bindings"] if request else None,
                            "guidance_binding": request["guidance"]
                            if request
                            else None,
                            "catalog_binding": request["catalog"] if request else None,
                        }
                    )
    if (
        sum(len(canonical_bytes(v)) for v in views.values())
        > definition["limits"]["max_view_bytes"]
    ):
        raise Stage3Error("assessor views exceed configured aggregate byte bound")
    producer = {
        path.name: hashlib.sha256(read_bytes(path)).hexdigest()
        for path in sorted(Path(__file__).parent.glob("*.py"))
    }
    return {
        "kind": "Stage3CampaignManifest",
        "schema_version": "1.0.0",
        "definition": definition,
        "definition_raw_sha256": definition_sha256,
        "producer": producer,
        "schedule": schedule,
        "units": units,
        "views": {k: digest(v) for k, v in views.items()},
        "policy": POLICY,
        "independence": "unverified",
        "calibration": "not-run",
    }, views


def prepare_campaign(definition, *, expected_sha256, output):
    raw = read_bytes(definition)
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise Stage3Error("external campaign definition hash mismatch")
    value = pinned({"path": str(definition), "sha256": expected_sha256})
    manifest, views = build_campaign(value, definition_sha256=expected_sha256)
    if len(canonical_bytes(manifest)) > MAX_ARTIFACT_BYTES or any(
        len(canonical_bytes(v)) > MAX_ARTIFACT_BYTES for v in views.values()
    ):
        raise Stage3Error("campaign artifact exceeds existing byte bound")
    target = private_output(output)
    if target.exists():
        return inspect_campaign(target, expected_sha256=digest(manifest))
    target.mkdir(parents=True)
    write_new(target / "definition.json", raw, raw=True)
    for name, view in views.items():
        write_new(target / (name + ".json"), view)
    write_new(target / "manifest.json", manifest)
    return {"manifest": manifest, "campaign_sha256": digest(manifest)}


def inspect_campaign(root, *, expected_sha256):
    root = private_output(root)
    actual = pinned({"path": str(root / "manifest.json"), "sha256": expected_sha256})
    closed(
        actual,
        {
            "kind",
            "schema_version",
            "definition",
            "definition_raw_sha256",
            "producer",
            "schedule",
            "units",
            "views",
            "policy",
            "independence",
            "calibration",
        },
        "campaign manifest",
    )
    expected, views = build_campaign(
        actual["definition"], definition_sha256=actual["definition_raw_sha256"]
    )
    if (
        digest(actual) != digest(expected)
        or pinned(
            {
                "path": str(root / "definition.json"),
                "sha256": actual["definition_raw_sha256"],
            }
        )
        != actual["definition"]
    ):
        raise Stage3Error("campaign differs from deterministic source-aware replay")
    expected_names = {"definition.json", "manifest.json"} | {
        name + ".json" for name in views
    }
    if {p.name for p in root.iterdir()} != expected_names:
        raise Stage3Error("campaign inventory is incomplete or changed")
    for name, view in views.items():
        if file_binding(root / (name + ".json"), digest(view)) != view:
            raise Stage3Error("assessor view changed")
    return {"manifest": actual, "campaign_sha256": expected_sha256}
