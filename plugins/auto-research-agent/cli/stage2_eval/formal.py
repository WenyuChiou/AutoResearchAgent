"""Read-only Stage 2 formal-admission contracts, version 1.0.0.

Schemas are represented by strict dictionaries rather than permissive status flags:

``Stage2FormalPlan`` freezes common scientific inputs, runtime identities, six
subjects, and the AB/BA/AB order. ``Stage2FormalReadinessManifest`` binds two
runtime preflights, two authentic pilot controller receipts, thirteen diagnostic
cases in five presentation variants, five actual unit results, an independent
semantic audit, and the frozen plan. ``Stage2FormalResultManifest`` binds six
native captures, shared source-located extraction evidence, isolated content-first
judge inputs/bundles, required named audits, and the unchanged paired comparison.

All public validators are read-only. Missing authenticated replay support returns
an explicit blocker; it never becomes success, a subject defect, or a zero score.
"""

import hashlib
import json
from datetime import datetime
from copy import deepcopy
from pathlib import Path, PurePosixPath, PureWindowsPath

from stage2_common import canonical_hash
from stage2_common import Stage2Error
from stage2_live.calibration import prepare_calibration
from stage2_live.replay import verify_calibration_unit, verify_extraction
from stage2_common import validate_packet
from stage2_live.controller import verify_controller
from stage2_live.native import verify_capture
from stage2_live.preflight import inspect_preflight, verify_preflight

from .diagnostics import _validate_cases
from .evaluation import RUBRIC_PATH, compare_pairs

VERSION = "1.0.0"
ORDERS = ("AB", "BA", "AB")
ARMS = ("A", "B", "B", "A", "A", "B")
VARIANTS = ("base", "order", "verbosity", "prestige", "preference")
PILOT_TOPICS = ("US-aging", "flaky-tests")


class FormalError(ValueError):
    """A formal plan, retained artifact, or admission binding is invalid."""


def _require(condition, message):
    if not condition:
        raise FormalError(message)


def _text(value, label):
    _require(isinstance(value, str) and value.strip(), f"missing {label}")


def _sha(value, label):
    _require(
        isinstance(value, str)
        and len(value) == 64
        and all(char in "0123456789abcdef" for char in value),
        f"invalid {label}",
    )


def _fields(value, expected, label):
    _require(isinstance(value, dict), f"{label} must be an object")
    _require(set(value) == set(expected), f"invalid {label} fields")


def _relative(value, label):
    _text(value, label)
    posix = PurePosixPath(value)
    windows = PureWindowsPath(value)
    _require(
        not posix.is_absolute()
        and not windows.is_absolute()
        and windows.drive == ""
        and not windows.root
        and ":" not in value
        and "\\" not in value
        and value == posix.as_posix()
        and all(part not in ("", ".", "..") for part in posix.parts),
        f"unsafe {label}",
    )
    return posix


def _contained(root, relative, label, *, directory=False):
    posix = _relative(relative, label)
    # The host chooses the evidence root; canonicalize platform aliases such as
    # macOS /var. Manifest-controlled components must be checked before resolve.
    root = Path(root).resolve()
    path = root.joinpath(*posix.parts)
    components = list(
        root.joinpath(*posix.parts[:index]) for index in range(1, len(posix.parts) + 1)
    )
    for current in components:
        try:
            attributes = getattr(current.lstat(), "st_file_attributes", 0)
        except FileNotFoundError:
            attributes = 0
        except OSError as error:
            raise FormalError(f"cannot inspect {label} path component") from error
        junction = hasattr(current, "is_junction") and current.is_junction()
        _require(
            not current.is_symlink() and not junction and not attributes & 0x400,
            f"linked path component in {label}",
        )
    resolved = path.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as error:
        raise FormalError(f"{label} escapes evidence root") from error
    _require(
        resolved.is_dir() if directory else resolved.is_file(),
        f"missing {label}: {relative}",
    )
    return resolved


def _verify_ref(root, ref, label):
    _fields(ref, ("path", "sha256"), f"{label} artifact reference")
    _sha(ref["sha256"], f"{label} sha256")
    path = _contained(root, ref["path"], label)
    raw = path.read_bytes()
    _require(hashlib.sha256(raw).hexdigest() == ref["sha256"], f"{label} hash mismatch")
    return raw, path


def _read_ref(root, ref, label):
    raw, path = _verify_ref(root, ref, label)
    try:
        return json.loads(raw.decode("utf-8")), path
    except (UnicodeDecodeError, ValueError) as error:
        raise FormalError(f"{label} is not UTF-8 JSON") from error


def _read_manifest(path, root, receipt, kind, *, versions=(VERSION,)):
    path = _contained(root, path, "manifest")
    raw = path.read_bytes()
    _sha(receipt, "externally retained manifest receipt")
    _require(
        hashlib.sha256(raw).hexdigest() == receipt,
        "manifest differs from externally retained receipt",
    )
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as error:
        raise FormalError("manifest is not UTF-8 JSON") from error
    _require(value.get("kind") == kind, f"wrong {kind} kind")
    _require(value.get("schema_version") in versions, f"wrong {kind} version")
    return value


def _validate_investment_policy(value):
    """Money is optional; a supplied limit must cite a recorded authorization."""
    for key in ("api_money_limit", "api_budget", "money_limit"):
        if key in value:
            limit = value[key]
            _require(
                isinstance(limit, dict)
                and set(limit) == {"amount", "currency", "authorization_ref"},
                "API money limit needs amount, currency and authorization_ref",
            )
            _require(
                type(limit["amount"]) in (int, float) and limit["amount"] >= 0,
                "invalid API money limit",
            )
            _text(limit["currency"], "money currency")
            _text(limit["authorization_ref"], "money authorization")


def freeze_formal_plan_v1(config, evidence_root):
    """Freeze a six-subject Stage 2 plan after validating all common byte refs."""

    return _freeze_formal_plan(config, evidence_root, RUBRIC_PATH, VERSION)


def _freeze_formal_plan(config, evidence_root, rubric_path, version):
    """Share byte, policy and chronology admission without changing old plans."""

    _fields(
        config,
        (
            "brief",
            "rubric",
            "stage1_source_manifest",
            "prompt",
            "model",
            "reasoning",
            "task",
            "native_capability_policy",
            "cutoff",
            "investment_policy",
            "runtime_sha256",
            "plugin_sha256",
            "dependency_sha256",
            "evaluator_contracts",
            "runtime_contracts",
            "runs",
        ),
        "formal plan config",
    )
    for name in ("brief", "stage1_source_manifest"):
        _read_ref(evidence_root, config[name], name)
    rubric, _ = _verify_ref(evidence_root, config["rubric"], "rubric")
    rubric_label = "v2" if version == VERSION else "v3"
    _require(
        rubric == rubric_path.read_bytes(), f"rubric differs from Stage2 {rubric_label}"
    )
    _verify_ref(evidence_root, config["prompt"], "prompt")
    _require(config["model"] == "gpt-5.6-sol", "formal model must be gpt-5.6-sol")
    _require(config["reasoning"] == "high", "formal reasoning must be high")
    _text(config["task"], "formal task")
    _require(
        isinstance(config["native_capability_policy"], dict)
        and config["native_capability_policy"],
        "native capability policy must be explicit",
    )
    _text(config["cutoff"], "source cutoff")
    _require(
        isinstance(config["investment_policy"], dict) and config["investment_policy"],
        "investment policy must be explicit",
    )
    _validate_investment_policy(config["investment_policy"])
    for field in ("runtime_sha256", "plugin_sha256", "dependency_sha256"):
        _sha(config[field], field)
    _fields(
        config["evaluator_contracts"],
        ("extraction", "actions", "judge"),
        "evaluator contracts",
    )
    for role, contract in config["evaluator_contracts"].items():
        _fields(
            contract,
            ("model", "reasoning", "runtime_sha256", "policy_sha256"),
            f"{role} evaluator contract",
        )
        _text(contract["model"], f"{role} model")
        _text(contract["reasoning"], f"{role} reasoning")
        _sha(contract["runtime_sha256"], f"{role} runtime")
        _sha(contract["policy_sha256"], f"{role} policy")
    _fields(config["runtime_contracts"], ("A", "B"), "runtime contracts")
    for arm, contract in config["runtime_contracts"].items():
        _fields(
            contract,
            ("inventory_sha256", "policy_bindings", "config_bindings"),
            f"{arm} runtime contract",
        )
        _sha(contract["inventory_sha256"], f"{arm} inventory")
        _require(
            isinstance(contract["config_bindings"], dict),
            "config bindings must be objects",
        )
        for digest in contract["config_bindings"].values():
            _sha(digest, "config binding")
    _require(
        config["runtime_contracts"]["A"]["policy_bindings"]
        == config["runtime_contracts"]["B"]["policy_bindings"],
        "A/B native policies differ",
    )
    _require(
        not config["runtime_contracts"]["A"]["config_bindings"],
        "A cannot load research extensions",
    )
    _require(
        config["runtime_contracts"]["B"]["config_bindings"].get("stage2_plugin")
        == config["plugin_sha256"]
        and config["runtime_contracts"]["B"]["config_bindings"].get(
            "research_dependency"
        )
        == config["dependency_sha256"],
        "B plugin and dependency are not pinned",
    )
    _validate_runs(config["runs"])
    for run in config["runs"]:
        _require(
            (run["harness_bindings"] or {})
            == config["runtime_contracts"][run["arm"]]["config_bindings"],
            "run harness differs from arm contract",
        )
    plan = {
        "kind": "Stage2FormalPlan",
        "schema_version": version,
        "status": "frozen",
        **deepcopy(config),
    }
    plan["plan_sha256"] = canonical_hash(plan)
    return plan


def _validate_runs(runs):
    _require(isinstance(runs, list) and len(runs) == 6, "formal plan needs six runs")
    expected = []
    for pair_index, order in enumerate(ORDERS, 1):
        for arm in order:
            expected.append((f"pair-{pair_index}", order, arm))
    actual = []
    subjects = []
    b_bindings = []
    for row in runs:
        _fields(
            row,
            ("pair_id", "order", "arm", "subject_id", "harness_bindings"),
            "formal run",
        )
        actual.append((row["pair_id"], row["order"], row["arm"]))
        _text(row["subject_id"], "subject ID")
        subjects.append(row["subject_id"])
        if row["arm"] == "A":
            _require(row["harness_bindings"] is None, "A cannot require the B ledger")
        else:
            _require(
                isinstance(row["harness_bindings"], dict) and row["harness_bindings"],
                "B needs explicit harness bindings",
            )
            b_bindings.append(row["harness_bindings"])
    _require(actual == expected, "formal run order must be AB, BA, AB")
    _require(len(subjects) == len(set(subjects)), "formal subject IDs must be unique")
    _require(
        all(value == b_bindings[0] for value in b_bindings),
        "B harness bindings changed across runs",
    )


def validate_formal_plan_v1(plan, evidence_root):
    """Replay a frozen plan's structure, artifacts, identities, and canonical hash."""

    _fields(
        plan,
        (
            "kind",
            "schema_version",
            "status",
            "brief",
            "rubric",
            "stage1_source_manifest",
            "prompt",
            "model",
            "reasoning",
            "task",
            "native_capability_policy",
            "cutoff",
            "investment_policy",
            "runtime_sha256",
            "plugin_sha256",
            "dependency_sha256",
            "evaluator_contracts",
            "runtime_contracts",
            "runs",
            "plan_sha256",
        ),
        "formal plan",
    )
    supplied = deepcopy(plan)
    digest = supplied.pop("plan_sha256")
    expected = freeze_formal_plan_v1(
        {
            key: supplied[key]
            for key in supplied
            if key not in ("kind", "schema_version", "status")
        },
        evidence_root,
    )
    _require(plan == expected, "formal plan changed after freeze")
    _require(digest == expected["plan_sha256"], "formal plan hash mismatch")
    return None


def _calibration_blockers(calibration, root, verifier=verify_calibration_unit):
    _fields(
        calibration,
        ("cases", "recipes", "units", "semantic_audit"),
        "calibration admission",
    )
    cases, _ = _read_ref(root, calibration["cases"], "calibration cases")
    _validate_cases(cases)
    _require(len(cases) == 13, "calibration requires thirteen frozen cases")
    recipes, _ = _read_ref(root, calibration["recipes"], "calibration recipes")
    expected = prepare_calibration(cases, recipes)
    units = calibration["units"]
    _require(
        isinstance(units, list) and len(units) == 5,
        "calibration needs five unit results",
    )
    _require(
        [row.get("variant") for row in units] == list(VARIANTS),
        "calibration variants changed",
    )
    result_hashes = {}
    for row, frozen in zip(units, expected, strict=True):
        _fields(
            row,
            ("variant", "frozen_unit", "result", "replay_receipt", "config", "policy"),
            "calibration unit binding",
        )
        saved_unit, _ = _read_ref(root, row["frozen_unit"], "calibration frozen unit")
        legacy = "recipe" not in saved_unit
        compared = deepcopy(frozen)
        if legacy:
            compared.pop("recipe")
        _require(
            saved_unit == compared, f"calibration frozen unit changed: {row['variant']}"
        )
        result, result_path = _read_ref(root, row["result"], "calibration result")
        receipt, _ = _read_ref(
            root, row["replay_receipt"], "calibration replay receipt"
        )
        _require(
            receipt.get("result_sha256") == row["result"]["sha256"],
            "calibration result receipt mismatch",
        )
        replay = verifier(
            result_path.parent,
            receipt,
            frozen_unit=saved_unit,
            expected_config=row["config"],
            expected_policy=row["policy"],
            legacy_recipe=frozen["recipe"] if legacy else None,
        )
        _require(
            replay["result"] == result and result["case_outputs"] == 13,
            "calibration replay differs",
        )
        result_hashes[row["variant"]] = row["result"]["sha256"]
    audit, _ = _read_ref(
        root, calibration["semantic_audit"], "calibration semantic audit"
    )
    _fields(
        audit,
        (
            "kind",
            "schema_version",
            "reviewer",
            "reviewer_role",
            "result_sha256s",
            "decision",
            "rationale",
            "preassessment",
            "review_record",
            "case_reviews",
        ),
        "calibration semantic audit",
    )
    _require(
        audit["kind"] == "Stage2CalibrationSemanticAudit"
        and audit["schema_version"] == VERSION
        and audit["reviewer_role"] in {"independent-human", "independent-ai"}
        and audit["result_sha256s"] == result_hashes,
        "calibration audit identity or result binding mismatch",
    )
    _text(audit["reviewer"], "calibration audit reviewer")
    _text(audit["rationale"], "calibration audit rationale")
    _verify_ref(root, audit["preassessment"], "independent preassessment")
    _verify_ref(root, audit["review_record"], "independent review record")
    rows = audit["case_reviews"]
    required = {(variant, case["case_id"]) for variant in VARIANTS for case in cases}
    _require(
        isinstance(rows, list)
        and len(rows) == 65
        and {(r.get("variant"), r.get("case_id")) for r in rows} == required,
        "semantic audit must cover all65outputs",
    )
    for row in rows:
        _fields(
            row,
            ("variant", "case_id", "status", "reason", "evidence_ids"),
            "case review",
        )
        _require(
            row["status"]
            in {
                "accepted",
                "minor-unresolved",
                "major-unresolved",
                "evaluator-failure",
            },
            "unknown semantic audit status",
        )
        _text(row["reason"], "case review reason")
        ids = {
            f["evidence_id"]
            for c in cases
            if c["case_id"] == row["case_id"]
            for f in c["source_facts"]
        }
        _require(
            isinstance(row["evidence_ids"], list)
            and set(row["evidence_ids"]).issubset(ids),
            "semantic audit evidence mismatch",
        )
    blockers = [
        f"calibration:{r['variant']}:{r['case_id']}:{r['status']}"
        for r in rows
        if r["status"] != "accepted"
    ]
    if audit["decision"] != "accepted":
        blockers.append("calibration-audit-not-accepted")
    return blockers


def _rubric_quality_blockers(binding, root, verifier=None, *, judge_contract=None):
    """Require replayed native QA, not a hand-filled aggregate acceptance flag."""
    from .rubric_admission import verify_rubric_quality_admission

    expected = (
        "verification_code_sha256",
        "model",
        "reasoning",
        "runtime_sha256",
        "rubric_sha256",
        "guidance_sha256",
        "execution_policy_sha256",
    )
    _fields(
        binding,
        (
            "dataset",
            "reference",
            "run_dir",
            "run_result_sha256_receipt",
            "codex_executable",
            *expected,
        ),
        "rubric quality binding",
    )
    dataset, _ = _read_ref(root, binding["dataset"], "rubric quality dataset")
    reference, _ = _read_ref(root, binding["reference"], "rubric quality reference")
    run_dir = _contained(root, binding["run_dir"], "rubric quality run", directory=True)
    _sha(binding["run_result_sha256_receipt"], "rubric quality run receipt")
    _text(binding["codex_executable"], "rubric quality executable")
    executable = Path(binding["codex_executable"])
    _require(executable.is_absolute(), "rubric quality executable must be absolute")
    for field in expected:
        if field.endswith("sha256"):
            _sha(binding[field], f"rubric quality {field}")
        else:
            _text(binding[field], f"rubric quality {field}")
    try:
        result = (verifier or verify_rubric_quality_admission)(
            dataset,
            reference,
            dataset_sha256=canonical_hash(dataset),
            reference_sha256=canonical_hash(reference),
            run_dir=run_dir,
            run_result_sha256=binding["run_result_sha256_receipt"],
            codex=executable,
        )
    except (Stage2Error, OSError) as error:
        raise FormalError(f"rubric quality replay failed: {error}") from error
    _require(isinstance(result, dict), "rubric quality replay is not an object")
    actual = result.get("bindings")
    _require(
        isinstance(actual, dict)
        and all(actual.get(field) == binding[field] for field in expected),
        "rubric quality verification differs from manifest binding",
    )
    if judge_contract is not None:
        _require(
            all(
                actual[field] == judge_contract.get(field)
                for field in ("model", "reasoning", "runtime_sha256")
            ),
            "rubric quality judge differs from frozen evaluation plan",
        )
    _require(
        result.get("formal_ready") is False, "QA cannot itself assert formal readiness"
    )
    if result.get("accepted") is not True:
        return ["rubric-quality-not-accepted"]
    return []


def validate_readiness_v1(
    manifest_path,
    evidence_root,
    externally_retained_manifest_receipt,
    *,
    _synthetic_test_verifiers=None,
):
    """Replay readiness evidence without dispatch; return blockers instead of promotion.

    ``_synthetic_test_verifiers`` is a private unit-test seam. Its use permanently
    tags the result ``synthetic-test-only`` and can never set ``formal_ready``.
    """

    manifest = _read_manifest(
        manifest_path,
        evidence_root,
        externally_retained_manifest_receipt,
        "Stage2FormalReadinessManifest",
        versions=(VERSION, "1.1.0"),
    )
    _fields(
        manifest,
        (
            "kind",
            "schema_version",
            "preflights",
            "pilots",
            "calibration",
            "formal_plan",
            *(("rubric_quality",) if manifest["schema_version"] == "1.1.0" else ()),
        ),
        "readiness manifest",
    )
    synthetic = _synthetic_test_verifiers is not None
    verifiers = _synthetic_test_verifiers or {}
    inspect_fn = verifiers.get("inspect_preflight", inspect_preflight)
    preflight_fn = verifiers.get("verify_preflight", verify_preflight)
    controller_fn = verifiers.get("verify_controller", verify_controller)
    blockers = []
    if not synthetic:
        # These collectors are not implemented by the current CLI capture.
        # Keep admission closed, even if a caller supplies optimistic JSON.
        blockers.extend(
            [
                "per-execution-inventory-collector-unavailable",
                "complete-subagent-budget-accounting-unavailable",
            ]
        )
        if manifest["schema_version"] == VERSION:
            blockers.append("legacy-rubric-quality-evidence-unbound")
    plan, _ = _read_ref(evidence_root, manifest["formal_plan"], "formal plan")
    validate_formal_plan_v1(plan, evidence_root)
    preflights = manifest["preflights"]
    reports = []
    _require(
        isinstance(preflights, list) and len(preflights) == 2,
        "readiness needs A/B preflights",
    )
    _require(
        [row.get("arm") for row in preflights] == ["A", "B"],
        "preflight arms must be A and B",
    )
    for row in preflights:
        _fields(
            row,
            (
                "arm",
                "report",
                "capture_dir",
                "capture_record_sha256_receipt",
                "probe_spec",
                "inventory_receipt",
            ),
            "preflight binding",
        )
        report, _ = _read_ref(evidence_root, row["report"], "preflight report")
        probe, _ = _read_ref(evidence_root, row["probe_spec"], "preflight probe")
        inventory, _ = _read_ref(
            evidence_root, row["inventory_receipt"], "preflight inventory"
        )
        _require(
            probe.get("kind") != "Stage2ProductionRuntimeProbeSpec"
            and report.get("kind") != "Stage2ProductionRuntimePreflight"
            and report.get("validation_scope") != "production-single",
            "production-only preflight cannot establish formal A/B isolation",
        )
        capture = _contained(
            evidence_root, row["capture_dir"], "preflight capture", directory=True
        )
        _sha(row["capture_record_sha256_receipt"], "preflight capture receipt")
        inspected = inspect_fn(
            capture,
            row["capture_record_sha256_receipt"],
            probe,
            inventory_receipt=inventory,
        )
        verified = preflight_fn(
            report,
            capture,
            row["capture_record_sha256_receipt"],
            probe,
            inventory_receipt=inventory,
        )
        _require(
            inspected == verified == report, "preflight inspect/verify replay mismatch"
        )
        reports.append(report)
        if not synthetic:
            contract = plan["runtime_contracts"][row["arm"]]
            values = {name: item["value"] for name, item in report["inventory"].items()}
            _require(
                canonical_hash(values) == contract["inventory_sha256"],
                "preflight inventory differs from frozen arm contract",
            )
            record, _ = verify_capture(capture, row["capture_record_sha256_receipt"])
            stable = record["stable_request_binding"]
            _require(
                stable["codex_runtime_sha256"] == plan["runtime_sha256"]
                and stable["policy_bindings"] == contract["policy_bindings"],
                "preflight runtime differs from plan",
            )
            for field in ("model", "reasoning"):
                _require(
                    report["actual_runtime"].get(field) == plan[field],
                    f"preflight effective {field} differs",
                )
        if report.get("runtime_gate") is not True or report.get("status") != "passed":
            blockers.append(f"preflight-not-passed:{row['arm']}")
    if not synthetic:
        # Full inventories are frozen separately. The actual native tool set must
        # remain identical; extensions may add instructions but not weaken A.
        _require(
            reports[0]["inventory"]["tools"]["value"]
            == reports[1]["inventory"]["tools"]["value"],
            "A/B native tool inventories differ",
        )
    pilots = manifest["pilots"]
    _require(
        isinstance(pilots, list) and len(pilots) == 2, "readiness needs two pilots"
    )
    _require(
        [row.get("topic_id") for row in pilots] == list(PILOT_TOPICS),
        "pilot topics must be US-aging and flaky-tests",
    )
    _require(
        len({r.get("controller_manifest_sha256_receipt") for r in pilots}) == 2,
        "pilot archives must be distinct",
    )
    pilot_briefs = set()
    for row in pilots:
        _fields(
            row,
            (
                "topic_id",
                "controller_dir",
                "controller_manifest_sha256_receipt",
                "brief",
            ),
            "pilot binding",
        )
        controller = _contained(
            evidence_root, row["controller_dir"], "pilot controller", directory=True
        )
        _sha(row["controller_manifest_sha256_receipt"], "controller manifest receipt")
        verification = controller_fn(
            controller, row["controller_manifest_sha256_receipt"]
        )
        brief, _ = _read_ref(evidence_root, row["brief"], "pilot brief")
        _require(
            canonical_hash(brief) not in pilot_briefs, "pilot briefs must be distinct"
        )
        pilot_briefs.add(canonical_hash(brief))
        if not synthetic:
            _require(
                verification["workflow"]["snapshots"][0]["packet"]["brief"] == brief,
                "pilot topic brief differs from actual workflow",
            )
        if (
            verification.get("pilot_executable") is not True
            or verification.get("authentic_native_execution") is not True
            or verification.get("synthetic_test_only") is not False
        ):
            blockers.append(f"pilot-not-authentic-and-executable:{row['topic_id']}")
    blockers.extend(
        _calibration_blockers(
            manifest["calibration"],
            evidence_root,
            verifiers.get("verify_calibration_unit", verify_calibration_unit),
        )
    )
    if manifest["schema_version"] == "1.1.0":
        blockers.extend(
            _rubric_quality_blockers(
                manifest["rubric_quality"],
                evidence_root,
                verifiers.get("verify_rubric_quality"),
                judge_contract=plan["evaluator_contracts"]["judge"],
            )
        )
    plan, _ = _read_ref(evidence_root, manifest["formal_plan"], "formal plan")
    validate_formal_plan_v1(plan, evidence_root)
    if synthetic:
        blockers.append("synthetic-test-only")
    blockers = sorted(set(blockers))
    return {
        "kind": "Stage2FormalReadinessValidation",
        "schema_version": VERSION,
        "status": "ready" if not blockers else "blocked",
        "formal_ready": not blockers and not synthetic,
        "evidence_class": "synthetic-test-only" if synthetic else "authentic-replay",
        "blockers": blockers,
        "plan_sha256": plan["plan_sha256"],
    }


def _verify_evaluator_contract(plan, role, config, policy):
    contract = plan["evaluator_contracts"][role]
    _require(
        config.get("model") == contract["model"]
        and config.get("reasoning") == contract["reasoning"]
        and config.get("codex_executable_sha256") == contract["runtime_sha256"]
        and canonical_hash(policy) == contract["policy_sha256"],
        f"{role} evaluator differs from frozen contract",
    )


def _arm_contamination(value):
    forbidden = {"arm", "arm_map", "condition_map", "experimental_assignment"}
    if isinstance(value, dict):
        return any(
            str(key).casefold() in forbidden or _arm_contamination(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_arm_contamination(item) for item in value)
    return False


def _verify_run_chronology(records):
    """One archived subject cannot stand in for three independent repetitions."""
    _require(len(records) == 6, "six observed runs required")
    ids = [record["event_summary"].get("thread_id") for record in records]
    _require(
        all(isinstance(i, str) and i for i in ids) and len(set(ids)) == 6,
        "six distinct native session IDs required",
    )
    for left, right in zip(records, records[1:]):
        _require(
            datetime.fromisoformat(left["ended_at"])
            <= datetime.fromisoformat(right["started_at"]),
            "observed execution order differs from frozen AB BA AB",
        )


def validate_formal_result_v1(
    manifest_path,
    evidence_root,
    externally_retained_manifest_receipt,
    plan,
    *,
    _synthetic_test_verifier=None,
):
    """Validate six saved runs and replay ``compare_pairs`` without model execution."""

    validate_formal_plan_v1(plan, evidence_root)
    manifest = _read_manifest(
        manifest_path,
        evidence_root,
        externally_retained_manifest_receipt,
        "Stage2FormalResultManifest",
    )
    _fields(
        manifest,
        (
            "kind",
            "schema_version",
            "plan_sha256",
            "evidence_class",
            "runs",
            "pairs",
            "readiness",
            "readiness_receipt",
            "claim_audit",
        ),
        "formal result manifest",
    )
    _require(
        manifest["plan_sha256"] == plan["plan_sha256"], "formal result plan mismatch"
    )
    synthetic = _synthetic_test_verifier is not None
    expected_class = "synthetic-test-only" if synthetic else "authentic-native"
    _require(
        manifest["evidence_class"] == expected_class,
        "formal result evidence class mismatch",
    )
    runs = manifest["runs"]
    _require(isinstance(runs, list) and len(runs) == 6, "formal result needs six runs")
    expected_subjects = [row["subject_id"] for row in plan["runs"]]
    _require(
        len({r.get("native_capture", {}).get("record_sha256_receipt") for r in runs})
        == 6,
        "six distinct capture receipts required",
    )
    _require(
        [row.get("subject_id") for row in runs] == expected_subjects,
        "formal result subject coverage mismatch",
    )
    blockers = []
    readiness, _ = _read_ref(evidence_root, manifest["readiness"], "readiness manifest")
    _require(
        manifest["readiness_receipt"] == manifest["readiness"]["sha256"],
        "readiness receipt mismatch",
    )
    if not synthetic:
        admitted = validate_readiness_v1(
            manifest["readiness"]["path"], evidence_root, manifest["readiness_receipt"]
        )
        _require(
            admitted["plan_sha256"] == plan["plan_sha256"], "readiness plan mismatch"
        )
        blockers.extend(admitted["blockers"])
    bundle_by_subject = {}
    observed_runs = []
    verifier = _synthetic_test_verifier
    for row, planned in zip(runs, plan["runs"], strict=True):
        _fields(
            row,
            (
                "subject_id",
                "native_capture",
                "extraction",
                "judge_input",
                "judge_archive",
                "judge_bundle",
                "named_audit",
                "action_extraction",
                "execution_environment",
            ),
            "formal run result",
        )
        _fields(
            row["native_capture"],
            ("directory", "record_sha256_receipt"),
            "native capture binding",
        )
        capture_dir = _contained(
            evidence_root,
            row["native_capture"]["directory"],
            "native capture",
            directory=True,
        )
        _sha(row["native_capture"]["record_sha256_receipt"], "native capture receipt")
        if verifier is None:
            try:
                captured, raw_proposal = verify_capture(
                    capture_dir, row["native_capture"]["record_sha256_receipt"]
                )
                observed_runs.append(captured)
                from stage2_live.environment import verify_environment_capture

                environment, _ = _read_ref(
                    evidence_root, row["execution_environment"], "execution environment"
                )
                _fields(
                    environment,
                    ("preflight", "inventory_receipt"),
                    "execution environment",
                )
                verify_environment_capture(
                    capture_dir,
                    row["native_capture"]["record_sha256_receipt"],
                    environment["preflight"],
                    environment["inventory_receipt"],
                )
                stable = captured["stable_request_binding"]
                for key, expected in (
                    ("prompt_sha256", plan["prompt"]["sha256"]),
                    ("model", plan["model"]),
                    ("reasoning", plan["reasoning"]),
                    ("codex_runtime_sha256", plan["runtime_sha256"]),
                ):
                    _require(
                        stable.get(key) == expected,
                        f"native run differs from frozen {key}",
                    )
                for name in ("brief", "stage1_source_manifest"):
                    _require(
                        stable.get("input_bindings", {}).get(name, {}).get("sha256")
                        == plan[name]["sha256"],
                        f"native input {name} differs",
                    )
                expected_harness = planned["harness_bindings"] or {}
                _require(
                    stable.get("policy_bindings")
                    == plan["runtime_contracts"][planned["arm"]]["policy_bindings"],
                    "native policy differs from frozen contract",
                )
                actual_harness = stable.get("config_bindings", {})
                _require(
                    set(actual_harness) == set(expected_harness)
                    and all(
                        actual_harness[k].get("sha256") == v
                        for k, v in expected_harness.items()
                    ),
                    "native harness binding differs",
                )
            except (OSError, ValueError) as error:
                raise FormalError(
                    f"native capture replay failed: {row['subject_id']}: {error}"
                ) from error
        else:
            verifier("capture", row, capture_dir)
        _fields(
            row["extraction"],
            (
                "artifact",
                "external_replay_receipt",
                "source_locations",
                "packet",
                "source_root",
                "snapshot_sha256",
                "config",
                "policy",
            ),
            "extraction binding",
        )
        extraction, extraction_path = _read_ref(
            evidence_root, row["extraction"]["artifact"], "shared extraction"
        )
        receipt, _ = _read_ref(
            evidence_root,
            row["extraction"]["external_replay_receipt"],
            "extraction replay receipt",
        )
        _fields(
            receipt, ("result_sha256", "unit_receipts"), "extraction replay receipt"
        )
        _require(
            receipt["result_sha256"] == row["extraction"]["artifact"]["sha256"],
            "extraction external receipt does not bind result bytes",
        )
        _require(
            isinstance(receipt["unit_receipts"], dict) and receipt["unit_receipts"],
            "extraction replay receipt lacks native model calls",
        )
        for digest in receipt["unit_receipts"].values():
            _sha(digest, "extraction model-unit receipt")
        locations = row["extraction"]["source_locations"]
        _require(
            isinstance(locations, list) and locations,
            "extraction needs source locations",
        )
        _require(
            all(isinstance(value, str) and value.strip() for value in locations),
            "invalid extraction source location",
        )
        if verifier is None:
            packet, _ = _read_ref(
                evidence_root, row["extraction"]["packet"], "extraction input packet"
            )
            source_root = _contained(
                evidence_root,
                row["extraction"]["source_root"],
                "source root",
                directory=True,
            )
            validate_packet(packet, source_root)
            initial_packet, _ = _read_ref(
                evidence_root, plan["stage1_source_manifest"], "common source packet"
            )
            brief, _ = _read_ref(evidence_root, plan["brief"], "common brief")
            _require(
                packet == initial_packet and packet["brief"] == brief,
                "supplemental-evidence-not-supported: extraction must retain the common starting packet",
            )
            _verify_evaluator_contract(
                plan,
                "extraction",
                row["extraction"]["config"],
                row["extraction"]["policy"],
            )
            replayed = verify_extraction(
                extraction_path.parent,
                receipt,
                raw_proposal=raw_proposal,
                packet=packet,
                source_root=source_root,
                snapshot_sha256=row["extraction"]["snapshot_sha256"],
                expected_config=row["extraction"]["config"],
                expected_policy=row["extraction"]["policy"],
            )
            _require(replayed["result"] == extraction, "extraction replay differs")
            span_path = extraction_path.parent / "span-index.json"
            span_index = json.loads(span_path.read_text(encoding="utf-8"))
            _require(
                locations == [span["span_id"] for span in span_index["spans"]],
                "extraction source locations differ",
            )
        else:
            verifier(
                "extraction", {"value": extraction, "receipt": receipt}, extraction_path
            )
        judge_input, _ = _read_ref(evidence_root, row["judge_input"], "judge input")
        _require(not _arm_contamination(judge_input), "arm map appears in judge input")
        _fields(
            row["judge_archive"],
            (
                "directory",
                "external_replay_receipt",
                "config",
                "policy",
                "action_record",
            ),
            "judge archive binding",
        )
        judge_dir = _contained(
            evidence_root,
            row["judge_archive"]["directory"],
            "judge archive",
            directory=True,
        )
        judge_receipt, _ = _read_ref(
            evidence_root,
            row["judge_archive"]["external_replay_receipt"],
            "judge replay receipt",
        )
        _fields(
            judge_receipt, ("result_sha256", "unit_receipts"), "judge replay receipt"
        )
        judge_units = judge_receipt["unit_receipts"]
        _require(
            isinstance(judge_units, dict)
            and {"r1-content", "r1-judge", "r2-content", "r2-judge"}.issubset(
                judge_units
            ),
            "isolated content-first R1/R2 model-call receipts are missing",
        )
        for label, digest in judge_units.items():
            _sha(digest, "judge model-unit receipt")
            unit = judge_dir / f"{label}.unit.json"
            archive = judge_dir / f"{label}.model-call" / "request.json"
            _require(
                unit.is_file()
                and archive.is_file()
                and hashlib.sha256(unit.read_bytes()).hexdigest() == digest,
                f"judge model-call archive is incomplete: {label}",
            )
        bundle, _ = _read_ref(evidence_root, row["judge_bundle"], "judge bundle")
        _require(
            bundle.get("subject_id") == row["subject_id"],
            "judge bundle subject mismatch",
        )
        _require(
            bundle.get("raw", {}).get("r1") is not None
            and bundle.get("raw", {}).get("r2") is not None,
            "isolated content-first R1/R2 archives are missing",
        )
        if bundle.get("adjudicated"):
            _require(
                bundle.get("raw", {}).get("adj") is not None,
                "required ADJ archive is missing",
            )
            _require(
                {"adj-content", "adj-judge"}.issubset(judge_units),
                "required ADJ model-call receipts are missing",
            )
        if bundle.get("audit_required"):
            _require(row["named_audit"] is not None, "required named audit is missing")
            audit, _ = _read_ref(evidence_root, row["named_audit"], "named audit")
            _require(
                audit == bundle.get("raw", {}).get("audit"),
                "named audit binding mismatch",
            )
        else:
            _require(row["named_audit"] is None, "unexpected named audit binding")
        if not synthetic:
            from stage2_live.judge_replay import verify_judges

            _verify_evaluator_contract(
                plan,
                "judge",
                row["judge_archive"]["config"],
                row["judge_archive"]["policy"],
            )

            action_record, _ = _read_ref(
                evidence_root,
                row["judge_archive"]["action_record"],
                "subject action record",
            )
            judged_packet = extraction["next_packet"]["packet"]
            from stage2_live.action_extraction import verify_action_extraction

            _fields(
                row["action_extraction"],
                ("directory", "replay_receipt", "config", "policy"),
                "action extraction",
            )
            actions = row["action_extraction"]
            _verify_evaluator_contract(
                plan, "actions", actions["config"], actions["policy"]
            )
            action_receipt, _ = _read_ref(
                evidence_root, actions["replay_receipt"], "action extraction receipt"
            )
            action_root = _contained(
                evidence_root, actions["directory"], "action extraction", directory=True
            )
            verified_actions = verify_action_extraction(
                action_root,
                action_receipt,
                raw_proposal=raw_proposal,
                packet=judged_packet,
                source_root=source_root,
                expected_config=actions["config"],
                expected_policy=actions["policy"],
            )
            _require(
                verified_actions["result"].get("status") == "passed"
                and verified_actions["result"].get("action_record") == action_record,
                "subject actions not authenticated by common extraction",
            )
            _require(
                bundle.get("raw", {}).get("packet") == judged_packet,
                "judge packet differs from shared extraction",
            )
            verified_judges = verify_judges(
                judge_dir,
                judge_receipt,
                packet=judged_packet,
                source_root=source_root,
                subject_id=row["subject_id"],
                input_sha256=plan["plan_sha256"],
                config_sha256=canonical_hash(plan["evaluator_contracts"]),
                action_record=action_record,
                expected_config=row["judge_archive"]["config"],
                expected_policy=row["judge_archive"]["policy"],
                named_audit=audit if bundle.get("audit_required") else None,
            )
            _require(
                verified_judges.get("bundle") == bundle,
                "saved bundle differs from native judge replay",
            )
            _require(
                judge_input
                == json.loads(
                    (judge_dir / "content-view.json").read_text(encoding="utf-8")
                ),
                "judge input differs from actual content prompt",
            )
        bundle_by_subject[row["subject_id"]] = bundle
        _require(planned["arm"] in ("A", "B"), "invalid planned arm")
    if not synthetic:
        _verify_run_chronology(observed_runs)
    pairs, _ = _read_ref(evidence_root, manifest["pairs"], "formal pairs")
    _require(
        isinstance(pairs, list) and len(pairs) == 3,
        "formal result needs three complete pairs",
    )
    expected_pairs = []
    for index, order in enumerate(ORDERS):
        first = plan["runs"][index * 2]
        second = plan["runs"][index * 2 + 1]
        by_arm = {first["arm"]: first, second["arm"]: second}
        a = bundle_by_subject[by_arm["A"]["subject_id"]]
        b = bundle_by_subject[by_arm["B"]["subject_id"]]
        expected_pairs.append(
            {
                "pair_id": f"pair-{index + 1}",
                "order": order,
                "A": a,
                "B": b,
                "A_content_view_sha256": a["content_view_sha256"],
                "B_content_view_sha256": b["content_view_sha256"],
            }
        )
    _require(pairs == expected_pairs, "formal pairs differ from six bound runs")
    comparison = compare_pairs(pairs)
    if comparison["decision"] == "inconclusive":
        blockers.append("paired-evidence-inconclusive")
    audit_triggers = []
    if comparison["decision"] == "diagnostic-improvement":
        audit_triggers.append("improvement-claim")
    if any(
        abs(a["score"] - b["score"]) == 1
        for pair in pairs
        for a, b in zip(pair["A"]["criteria"], pair["B"]["criteria"], strict=True)
        if a["status"] == b["status"] == "assessed"
    ):
        audit_triggers.append("one-point-criterion-difference")
    if audit_triggers:
        if manifest["claim_audit"] is None:
            blockers.append("required-paired-claim-audit-missing")
        else:
            audit, _ = _read_ref(
                evidence_root, manifest["claim_audit"], "paired claim audit"
            )
            _fields(
                audit,
                (
                    "reviewer",
                    "reviewed_at",
                    "plan_sha256",
                    "pairs_sha256",
                    "triggers",
                    "decision",
                    "rationale",
                    "human_record",
                ),
                "paired claim audit",
            )
            _require(
                audit["reviewer"] == "Eric"
                and audit["plan_sha256"] == plan["plan_sha256"]
                and audit["pairs_sha256"] == manifest["pairs"]["sha256"]
                and audit["triggers"] == audit_triggers,
                "paired audit binding mismatch",
            )
            _text(audit["reviewed_at"], "audit time")
            _text(audit["rationale"], "audit rationale")
            _verify_ref(
                evidence_root, audit["human_record"], "genuine human audit record"
            )
            if audit["decision"] != "accepted":
                blockers.append("paired-claim-audit-not-accepted")
    elif manifest["claim_audit"] is not None:
        raise FormalError("unexpected paired audit")
    if synthetic:
        blockers.append("synthetic-test-only")
    blockers = sorted(set(blockers))
    return {
        "kind": "Stage2FormalResultValidation",
        "schema_version": VERSION,
        "status": "validated" if not blockers else "inconclusive",
        "formal_ready": not blockers and not synthetic,
        "evidence_class": expected_class,
        "blockers": blockers,
        "comparison": comparison,
        "audit_triggers": audit_triggers,
        "formal_decision": "inconclusive"
        if blockers
        else {
            "diagnostic-improvement": "improved",
            "not-improved": "not-improved",
            "inconclusive": "inconclusive",
        }[comparison["decision"]],
        "improvement_established": not blockers
        and comparison["decision"] == "diagnostic-improvement",
        "null_criteria_preserved": comparison["decision"] == "inconclusive"
        if any(row.get("status") == "inconclusive" for row in comparison["pairs"])
        else True,
    }
