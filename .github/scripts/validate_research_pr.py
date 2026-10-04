"""Validate the research-harness pull-request explanation contract."""

import argparse
import ast
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path

REQUIRED_SECTIONS = (
    "Why",
    "What",
    "How",
    "Example",
    "Evaluation",
    "Research Deliverable",
    "Validation",
)
HEADING = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
METRIC = re.compile(r"\bP[1-9]\b")
CAPABILITY_DECISIONS = {"reuse", "wrap", "extend", "build-new"}
EXECUTION_STATUSES = {"complete", "partial", "blocked"}
EVALUATION_MODES = {"deterministic", "ai-judge", "hybrid"}
EVALUATION_READINESS = {
    "implementation-only",
    "stage-executable",
    "improvement-demonstrated",
}
AI_JUDGE_EVIDENCE = re.compile(
    r"^(artifact|deferred|not-applicable)\s*:\s*(.+)$", re.IGNORECASE
)
ARTIFACT_REF = re.compile(
    r"(?:https://|[A-Za-z0-9_.-]+/[A-Za-z0-9_./-]+|"
    r"[A-Za-z0-9_.-]+\.(?:jsonl?|md|txt|csv|ya?ml))"
)
EXTERNAL_PR = re.compile(r"https://github\.com/([^/\s]+)/([^/\s]+)/pull/\d+/?$")
DEPENDENCY_PIN = re.compile(
    r"^(https://github\.com/[^/\s]+/[^/\s]+/pull/\d+)/?\s*@\s*"
    r"([0-9a-fA-F]{40})\s*@\s*(open|merged)$"
)
OPERATIONAL_MAPPING = re.compile(
    r"^(P[1-9](?:V[0-9]+)?\.[A-Z0-9_]+)\s*->\s*"
    r"(S[1-3](?:V[0-9]+)?_[A-Z0-9_]+)\s*->\s*"
    r"([A-Za-z0-9_.:/-]+)$"
)
BOUND_MANIFEST = re.compile(r"^manifest=([^;\s]+)\s*;\s*sha256=([0-9a-fA-F]{64})$")
INVARIANT_ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
INVARIANT_EVIDENCE = re.compile(
    r"^([a-z0-9]+(?:-[a-z0-9]+)*)\s*->\s*"
    r"([^\s;]+\.py)::([A-Za-z_][A-Za-z0-9_.]*)\s*->\s*(passed|failed)$",
    re.IGNORECASE,
)
IMPROVEMENT_STATEMENT = re.compile(
    r"^(improved|not improved|not yet demonstrated)\s*(?:—|:|-)\s*"
    r"(.+?);\s*evidence:\s*(.+)$",
    re.IGNORECASE,
)
EVIDENCE_SIGNAL = re.compile(
    r"(?:\b\d+(?:/\d+|(?:\.\d+)?%)?\b|\btests?\s+(?:pass(?:ed)?|fail(?:ed)?)\b|"
    r"\b(?:artifact|schema|fixture|benchmark|paired|metric|measurement|milestone|a/b)\b|"
    r"https://|[A-Za-z0-9_.-]+/[A-Za-z0-9_./-]+)",
    re.IGNORECASE,
)
SKILL_TEST_LABELS = (
    "Skill test scenario",
    "Skill test command",
    "Skill test expected",
    "Skill test actual",
    "Skill test limitations",
)
RESEARCH_DELIVERABLE_APPLICABILITY = {"required", "not-applicable"}
RESEARCH_DELIVERABLE_EVIDENCE_LABELS = (
    "Public source acquisition evidence",
    "Editable report evidence",
    "Source binding evidence",
    "Access-state evidence",
    "Access and repository guardrail evidence",
    "Japan pilot evidence",
)
RESEARCH_DELIVERABLE_CAPABILITY = "cli:stage1-deliverable"
RESEARCH_PAPER_TEXT_ROOT = re.compile(
    r"(?:^|/)(?:papers?|full[-_]?texts?|sources?|downloads?|artifacts?|"
    r"evidence|outputs?|runs?|deliverables?|stage1[-_]?research[-_]?deliverable|"
    r"japan[-_]?pilot)(?:/|$)",
    re.IGNORECASE,
)
SYNTHETIC_FIXTURE_PATH = re.compile(
    r"(?:^|/)(?:\.github/scripts/fixtures|plugins/auto-research-agent/tests/fixtures)/",
    re.IGNORECASE,
)
PLACEHOLDER_VALUE = re.compile(
    r"^(?:tbd|todo|n/?a|none|pending|unknown|not[ -]tested|not[ -]run|"
    r"placeholder|fill[ -](?:this|me))(?:\s+(?:later|yet|here|please|soon))?$",
    re.IGNORECASE,
)
REQUIRED_LABELS = {
    "Why": ("Plain-language summary", "Target primary metric(s)"),
    "What": (
        "Affected capability ID(s)",
        "Capability decision",
        "Related external PR(s)",
        "Internal prerequisite PR(s)",
        "External dependency pin(s)",
    ),
    "Evaluation": (
        "Evaluation readiness",
        "Rubric version",
        "Rubric criterion ID(s)",
        "Operational-definition mapping",
        "Required invariant IDs",
        "Invariant test evidence",
        "Evaluation mode",
        "Hard measures",
        "AI-judge evidence",
        "Major-error guardrail",
        "Per-PR metric evidence",
        "Improvement statement",
        "Live smoke evidence",
        "Paired evaluation evidence",
        "Runtime integrity evidence",
        "Live paired A/B",
    ),
    "Research Deliverable": (
        "Applicability",
        "Applicability reason",
        *RESEARCH_DELIVERABLE_EVIDENCE_LABELS,
    ),
    "Validation": (
        "Execution status",
        "Remaining work or blocker",
        "Review and merge owner",
    ),
}

CRITERION_INVARIANTS = {
    "P4V3.FIDELITY": {"stage2-source-binding", "stage2-content-before-action"},
    "P4V3.COMPARABILITY": {"stage2-content-before-action"},
    "P4V3.SYNTHESIS": {"stage2-source-binding", "stage2-content-before-action"},
    "P5V3.PRECEDENT": {"stage2-source-binding", "rehash-tamper-rejected"},
    "P5V3.CONTRIBUTION": {"stage2-source-binding", "rehash-tamper-rejected"},
    "P5V3.REVISION": {"stage2-source-binding", "rehash-tamper-rejected"},
    "P6V3.VALUE": {"stage2-content-before-action"},
    "P6V3.FEASIBILITY": {"stage2-unknown-distinct"},
    "P6V3.CHOICE": {"stage2-disposition-independent"},
    "P4V2.COMPARISON": {"stage2-content-before-action"},
    "P5V2.OPPORTUNITY": {"stage2-source-binding", "rehash-tamper-rejected"},
    "P5V2.REVISION": {"stage2-source-binding", "rehash-tamper-rejected"},
    "P6V2.VALUE": {"stage2-content-before-action"},
    "P6V2.FEASIBILITY": {"stage2-unknown-distinct"},
    "P6V2.DISPOSITION": {"stage2-disposition-independent"},
    "P6V2.PORTFOLIO": {"stage2-disposition-independent"},
    "P1V3.IDENTITY": {"v3-rubric-hash-bound", "v3-source-bytes-bound"},
    "P1V3.CLAIM_SUPPORT": {"v3-source-bytes-bound", "v3-major-grounded"},
    "P1V3.EVIDENCE_LIMITS": {"v3-unknown-distinct"},
    "P2V3.SCOPE": {"v3-no-gold-dependency", "v3-omission-independent"},
    "P2V3.CORE_SELECTION": {"v3-no-gold-dependency", "v3-source-bytes-bound"},
    "P2V3.CLOSEST_FRONTIER": {"v3-omission-independent", "v3-source-bytes-bound"},
    "P2V3.BOUNDARIES": {"v3-major-grounded"},
    "P3V3.SEARCH_TRACE": {"v3-content-process-separated"},
    "P3V3.DECISION_TRACE": {"v3-content-process-separated"},
    "P3V3.STOP_JUSTIFICATION": {"v3-unknown-distinct", "v3-major-grounded"},
    "P1.IDENTITY": {
        "artifact-producer-bound",
        "evidence-work-version-bound",
        "missing-evidence-fails-closed",
    },
    "P1.CLAIM_SUPPORT": {
        "artifact-producer-bound",
        "evidence-work-version-bound",
        "missing-evidence-fails-closed",
    },
    "P1.LOCATOR": {
        "artifact-producer-bound",
        "evidence-work-version-bound",
        "missing-evidence-fails-closed",
    },
    "P2.CLOSEST_WORK": {"unverified-closest-blocks-stop"},
    "P3.FAILURE_STATE": {"failure-distinct-from-empty"},
    "P3.STOP_EVIDENCE": {"all-stop-inputs-required"},
}
RUNTIME_INVARIANTS = {
    "runtime-bytes-bound",
    "dependency-sha-bound",
    "resume-no-reexecution",
}
EVALUATOR_INVARIANTS = {"rehash-tamper-rejected"}
DEFAULT_REGISTRY = (
    Path(__file__).resolve().parents[2]
    / "plugins/auto-research-agent/evals/capability-metric-map.v1.json"
)
DEFAULT_V3_REGISTRY = DEFAULT_REGISTRY.with_name("capability-metric-map.v3.json")
DEFAULT_STAGE2_REGISTRY = DEFAULT_REGISTRY.with_name(
    "capability-metric-map.stage2-v2.json"
)
DEFAULT_STAGE2_V3_REGISTRY = DEFAULT_REGISTRY.with_name(
    "capability-metric-map.stage2-v3.json"
)
DEFAULT_RUBRIC_DIR = (
    Path(__file__).resolve().parents[2] / "plugins/auto-research-agent/evals/rubrics"
)
DEFAULT_OPERATIONAL_DEFINITIONS = (
    Path(__file__).resolve().parents[2]
    / "plugins/auto-research-agent/evals/OPERATIONAL_DEFINITIONS.zh-TW.md"
)
DEFAULT_INVARIANT_REGISTRY = Path(__file__).with_name("invariant-registry.v1.json")
DEFAULT_CRITERION_SUBMETRICS = Path(__file__).with_name(
    "criterion-submetric-map.v1.json"
)
DEFAULT_REPOSITORY = "WenyuChiou/AutoResearchAgent"
_SELECTOR_RESULTS = {}


def sections(body):
    matches = list(HEADING.finditer(body))
    return {
        match.group(1).strip(): body[
            match.end() : matches[index + 1].start()
            if index + 1 < len(matches)
            else len(body)
        ].strip()
        for index, match in enumerate(matches)
    }


def visible_text(value):
    return COMMENT.sub("", value).strip()


def label_value(value, label):
    """Return one bullet value, including indented Markdown continuation lines."""

    lines = visible_text(value).splitlines()
    pattern = re.compile(rf"^-\s*{re.escape(label)}:[ \t]*(.*)$")
    for index, line in enumerate(lines):
        match = pattern.match(line)
        if not match:
            continue
        parts = [match.group(1).strip()]
        for continuation in lines[index + 1 :]:
            if not continuation.strip():
                break
            if re.match(r"^-\s*[^:]+:", continuation):
                break
            if not continuation[:1].isspace():
                break
            parts.append(continuation.strip())
        return " ".join(part for part in parts if part).strip()
    return ""


def label_has_value(value, label):
    return bool(label_value(value, label))


def label_has_concrete_value(value, label):
    return text_is_concrete(label_value(value, label))


def text_is_concrete(value):
    candidate = value.strip().strip("`._- ")
    return bool(candidate and not PLACEHOLDER_VALUE.fullmatch(candidate))


def load_capability_metrics(path=DEFAULT_REGISTRY):
    registry = json.loads(path.read_text(encoding="utf-8"))
    entries = list(registry["capabilities"])
    extensions = []
    if path == DEFAULT_REGISTRY:
        for extension_path in (
            DEFAULT_V3_REGISTRY,
            DEFAULT_STAGE2_REGISTRY,
            DEFAULT_STAGE2_V3_REGISTRY,
        ):
            extension = json.loads(extension_path.read_text(encoding="utf-8"))
            if extension.get("extends") != "capability-metric-map-v1":
                raise ValueError("capability extension must extend v1")
            entries.extend(extension["capabilities"])
            extensions.extend(extension.get("capability_extensions", []))
    ids = [entry["capability_id"] for entry in entries]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate capability ID across registries")
    capabilities = {
        entry["capability_id"]: {
            "metrics": {effect["metric_id"] for effect in entry["metric_effects"]},
            "criteria": {
                criterion_id
                for effect in entry["metric_effects"]
                for criterion_id in effect["rubric_criteria"]
            },
            "owner_path": entry["owner_path"],
            "kind": entry.get("kind", ""),
            "runtime_integrity_required": entry.get(
                "runtime_integrity_required", entry.get("kind") == "cli"
            ),
        }
        for entry in entries
    }
    for patch in extensions:
        capability_id = patch["capability_id"]
        if capability_id not in capabilities:
            raise ValueError(f"v3 extension names unknown capability {capability_id}")
        for effect in patch["metric_effects"]:
            capabilities[capability_id]["metrics"].add(effect["metric_id"])
            capabilities[capability_id]["criteria"].update(effect["rubric_criteria"])
    return capabilities


def capability_ids(value):
    return [item.strip() for item in re.split(r"[,;]", value) if item.strip()]


def semicolon_entries(value):
    return [item.strip() for item in value.split(";") if item.strip()]


def evidence_value(value):
    match = AI_JUDGE_EVIDENCE.fullmatch(value)
    if not match:
        return "", ""
    return match.group(1).casefold(), match.group(2).strip()


def _selector_node(path, selector, repo_root):
    candidate = (repo_root / path).resolve()
    try:
        candidate.relative_to(repo_root.resolve())
    except ValueError:
        return None
    if not candidate.is_file():
        return None
    try:
        tree = ast.parse(candidate.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeDecodeError):
        return None
    parts = selector.split(".")
    if len(parts) == 1:
        return next(
            (
                node
                for node in tree.body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == parts[0]
            ),
            None,
        )
    if len(parts) == 2:
        class_name, method_name = parts
        klass = next(
            (
                node
                for node in tree.body
                if isinstance(node, ast.ClassDef) and node.name == class_name
            ),
            None,
        )
        if klass is not None:
            return next(
                (
                    member
                    for member in klass.body
                    if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and member.name == method_name
                ),
                None,
            )
    return None


def selector_exists(path, selector, repo_root):
    return _selector_node(path, selector, repo_root) is not None


def selector_is_skipped(path, selector, repo_root):
    node = _selector_node(path, selector, repo_root)
    if node is None:
        return False
    for decorator in node.decorator_list:
        name = ""
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        if isinstance(target, ast.Attribute):
            name = target.attr
        elif isinstance(target, ast.Name):
            name = target.id
        if name in {"skip", "skipIf", "skipUnless"}:
            return True
    return False


def execute_selector(path, selector, repo_root):
    """Execute the exact unittest selector once per file content and selector."""

    candidate = (repo_root / path).resolve()
    key = (str(candidate), hashlib.sha256(candidate.read_bytes()).hexdigest(), selector)
    if key in _SELECTOR_RESULTS:
        return _SELECTOR_RESULTS[key]
    environment = os.environ.copy()
    environment["RESEARCH_PR_INVARIANT_CHILD"] = "1"
    try:
        result = subprocess.run(
            [sys.executable, str(candidate), selector],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=60,
            env=environment,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        outcome = (False, str(error))
    else:
        output = "\n".join(
            part.strip() for part in (result.stdout, result.stderr) if part.strip()
        )
        runtime_skipped = bool(
            re.search(r"\bskipped(?:\s*=|\b)", output, re.IGNORECASE)
        )
        outcome = (result.returncode == 0 and not runtime_skipped, output[-1000:])
    _SELECTOR_RESULTS[key] = outcome
    return outcome


def required_invariants(declared_criteria, declared_capabilities, known_capabilities):
    required = set()
    for criterion_id in declared_criteria:
        required.update(CRITERION_INVARIANTS.get(criterion_id, set()))
    if known_capabilities is None:
        return required
    for capability_id in declared_capabilities:
        entry = known_capabilities.get(capability_id, {})
        owner = entry.get("owner_path", "").replace("\\", "/")
        kind = entry.get("kind", "")
        if entry.get("runtime_integrity_required", kind == "cli"):
            required.update(RUNTIME_INVARIANTS)
        if kind in {"validator", "gate"} or any(
            marker in f"/{owner}" for marker in ("/validators/", "/gates/")
        ):
            required.update(EVALUATOR_INVARIANTS)
    return required


def load_rubrics(directory=DEFAULT_RUBRIC_DIR):
    rubrics = {}
    for path in sorted(directory.glob("*.json")):
        rubric = json.loads(path.read_text(encoding="utf-8"))
        if (
            rubric.get("status") not in {"frozen", "experimental"}
            and rubric.get("rubric_id") != "stage1-general-v3"
        ):
            continue
        version = rubric.get("rubric_version", rubric.get("rubric_id"))
        if version in rubrics:
            raise ValueError(f"duplicate rubric version: {version}")
        criteria = {}
        entries = (
            (
                (criterion_id, metric["id"])
                for metric in rubric.get("metrics", [])
                for criterion_id in metric["criterion_ids"]
            )
            if "metrics" in rubric
            else (
                (criterion["id"], criterion["dimension"])
                for criterion in rubric["criteria"]
            )
        )
        for criterion_id, metric_id in entries:
            if criterion_id in criteria:
                raise ValueError(f"duplicate criterion ID in {version}: {criterion_id}")
            criteria[criterion_id] = metric_id
        rubrics[version] = criteria
    return rubrics


def load_operational_submetrics(path=DEFAULT_OPERATIONAL_DEFINITIONS):
    submetrics = {}
    row = re.compile(
        r"^\|\s*`(S[1-3](?:V[0-9]+)?_[A-Z0-9_]+)`\s*\|.*\|\s*([^|]+?)\s*\|\s*$"
    )
    for line in path.read_text(encoding="utf-8").splitlines():
        match = row.match(line)
        if match:
            submetrics[match.group(1)] = set(METRIC.findall(match.group(2)))
    return submetrics


def load_criterion_submetrics(path=DEFAULT_CRITERION_SUBMETRICS):
    value = json.loads(path.read_text(encoding="utf-8"))
    if path == DEFAULT_CRITERION_SUBMETRICS:
        for name in (
            "criterion-submetric-map.stage2-v2.json",
            "criterion-submetric-map.stage2-v3.json",
        ):
            extension = json.loads(path.with_name(name).read_text(encoding="utf-8"))[
                "criterion_submetrics"
            ]
            if set(value["criterion_submetrics"]) & set(extension):
                raise ValueError("duplicate criterion across submetric registries")
            value["criterion_submetrics"].update(extension)
    return {
        criterion_id: set(submetric_ids)
        for criterion_id, submetric_ids in value["criterion_submetrics"].items()
    }


def load_invariant_registry(path=DEFAULT_INVARIANT_REGISTRY):
    value = json.loads(path.read_text(encoding="utf-8"))
    return value["invariants"]


def _owner_files(owner_path, repo_root):
    owner = (repo_root / owner_path).resolve()
    try:
        owner.relative_to(repo_root.resolve())
    except ValueError:
        return []
    if owner.is_file():
        return [owner]
    if owner.is_dir():
        return [
            path
            for path in owner.rglob("*")
            if path.is_file()
            and path.suffix.casefold() in {".py", ".json", ".md", ".yaml", ".yml"}
            and "tests" not in {part.casefold() for part in path.parts}
        ]
    return []


def production_symbol_exists(
    target, declared_capabilities, known_capabilities, repo_root
):
    """Require the mapped field/function to exist under a declared production owner."""

    if not known_capabilities or "." not in target:
        return False
    namespace, symbol = target.split(".", 1)[0], target.rsplit(".", 1)[-1]
    namespace_key = re.sub(r"[^a-z0-9]", "", namespace.casefold())
    symbol_pattern = re.compile(
        r"(?<![A-Za-z0-9])"
        + re.escape(symbol).replace("_", r"[ _-]+")
        + r"(?![A-Za-z0-9])",
        re.IGNORECASE,
    )
    for capability_id in declared_capabilities:
        entry = known_capabilities.get(capability_id)
        if not entry:
            continue
        for path in _owner_files(entry["owner_path"], repo_root):
            stem_key = re.sub(r"[^a-z0-9]", "", path.stem.casefold())
            parent_key = re.sub(r"[^a-z0-9]", "", path.parent.name.casefold())
            if namespace_key not in {stem_key, parent_key}:
                continue
            try:
                content = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            if symbol_pattern.search(content):
                return True
    return False


def _safe_repo_file(path_text, repo_root):
    if not path_text or "\\" in path_text or Path(path_text).is_absolute():
        return None
    candidate = (repo_root / path_text).resolve()
    try:
        candidate.relative_to(repo_root.resolve())
    except ValueError:
        return None
    return candidate if candidate.is_file() else None


def _artifact_bindings(manifest, repo_root):
    errors = []
    bindings = manifest.get("artifacts")
    if not isinstance(bindings, list):
        return {}, ["readiness manifest artifacts must be a list"]
    by_role = {}
    for binding in bindings:
        if not isinstance(binding, dict):
            errors.append("readiness manifest artifact entries must be objects")
            continue
        role = binding.get("role")
        path_text = binding.get("path")
        digest = binding.get("sha256")
        if not isinstance(role, str) or role in by_role:
            errors.append("readiness manifest artifact roles must be unique strings")
            continue
        path = (
            _safe_repo_file(path_text, repo_root)
            if isinstance(path_text, str)
            else None
        )
        if path is None:
            errors.append(
                f"readiness artifact '{role}' does not exist inside the repository"
            )
            continue
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", digest):
            errors.append(f"readiness artifact '{role}' requires a 64-character sha256")
            continue
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual.casefold() != digest.casefold():
            errors.append(
                f"readiness artifact '{role}' sha256 does not match file bytes"
            )
            continue
        by_role[role] = {**binding, "_resolved_path": path}
    return by_role, errors


def load_bound_readiness_manifest(detail, repo_root, allow_contract_fixtures=False):
    """Open a hash-bound manifest and every artifact it names."""

    match = BOUND_MANIFEST.fullmatch(detail)
    if not match:
        return None, ["artifact evidence must use 'manifest=PATH; sha256=64HEX'"]
    path_text, expected = match.groups()
    path = _safe_repo_file(path_text, repo_root)
    if path is None:
        return None, ["readiness manifest does not exist inside the repository"]
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected.casefold():
        return None, ["readiness manifest sha256 does not match file bytes"]
    try:
        manifest = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        return None, [f"readiness manifest is not valid JSON: {error}"]
    errors = []
    if (
        manifest.get("kind") != "ReadinessEvidenceManifest"
        or manifest.get("schema_version") != "1.0.0"
    ):
        errors.append("readiness manifest kind/schema_version is unsupported")
    if (
        manifest.get("evidence_scope") == "contract-fixture"
        and not allow_contract_fixtures
    ):
        errors.append(
            "contract-fixture evidence cannot support a real PR readiness claim"
        )
    artifacts, artifact_errors = _artifact_bindings(manifest, repo_root)
    errors.extend(artifact_errors)
    manifest["_verified_roles"] = set(artifacts)
    manifest["_verified_artifacts"] = artifacts
    manifest["_binding"] = (path_text, expected.casefold())
    return manifest, errors


def _read_json_artifact(manifest, role):
    binding = manifest.get("_verified_artifacts", {}).get(role)
    if not binding:
        return None, [f"Japan pilot manifest missing verified artifact role '{role}'"]
    try:
        value = json.loads(binding["_resolved_path"].read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        return None, [f"Japan pilot artifact '{role}' is not valid JSON: {error}"]
    if not isinstance(value, dict):
        return None, [f"Japan pilot artifact '{role}' must be a JSON object"]
    return value, []


DELIVERABLE_STATES = {
    "available",
    "abstract-only",
    "metadata-only",
    "paywalled",
    "not-found",
    "rate-limited",
    "network-error",
    "parse-error",
    "login-page",
    "identity-mismatch",
}
DELIVERABLE_FAILURE_STATES = DELIVERABLE_STATES - {
    "available",
    "abstract-only",
    "metadata-only",
}


def validate_stage1_deliverable_pilot_manifest(manifest):
    """Validate public-safe evidence for the private, unscored Japan pilot."""

    errors = []
    if manifest.get("evidence_scope") not in {
        "stage1-research-deliverable-pilot",
        "contract-fixture",
    }:
        errors.append(
            "Japan pilot manifest evidence_scope must be "
            "'stage1-research-deliverable-pilot'"
        )
    if str(manifest.get("pilot_geography", "")).casefold() != "japan":
        errors.append("Japan pilot manifest pilot_geography must be Japan")
    if manifest.get("execution_status") != "complete":
        errors.append("Japan pilot manifest execution_status must be complete")
    if manifest.get("validator_status") != "passed":
        errors.append("Japan pilot manifest validator_status must be passed")

    required_roles = {
        "deliverable-inventory",
        "deliverable-validator-report",
        "exporter-runtime-bytes",
        "repository-guardrail-report",
    }
    missing_roles = required_roles.difference(manifest.get("_verified_roles", set()))
    if missing_roles:
        errors.append(
            "Japan pilot manifest missing verified artifact role(s): "
            + ", ".join(sorted(missing_roles))
        )

    inventory, inventory_errors = _read_json_artifact(manifest, "deliverable-inventory")
    validator_report, validator_errors = _read_json_artifact(
        manifest, "deliverable-validator-report"
    )
    guardrail_report, guardrail_errors = _read_json_artifact(
        manifest, "repository-guardrail-report"
    )
    errors.extend(inventory_errors + validator_errors + guardrail_errors)

    if inventory is not None:
        if inventory.get("status") != "complete":
            errors.append("Japan pilot deliverable inventory status must be complete")
        outputs = inventory.get("outputs")
        required_outputs = {
            "excel",
            "markdown",
            "bibtex",
            "metadata",
            "claims",
            "screening",
            "coverage",
        }
        if not isinstance(outputs, dict) or any(
            type(outputs.get(name)) is not int or outputs[name] < 1
            for name in required_outputs
        ):
            errors.append(
                "Japan pilot inventory must record at least one Excel, Markdown, "
                "BibTeX, metadata, claims, screening and coverage output"
            )
        bindings = inventory.get("source_bindings")
        if (
            not isinstance(bindings, dict)
            or type(bindings.get("total")) is not int
            or type(bindings.get("complete")) is not int
            or bindings.get("total", 0) < 1
            or bindings.get("complete") != bindings.get("total")
        ):
            errors.append(
                "Japan pilot inventory must bind every full source and report a "
                "positive complete/total count"
            )
        acquired = inventory.get("acquired_full_text")
        if not isinstance(acquired, dict) or any(
            type(acquired.get(name)) is not int or acquired[name] < 0
            for name in ("pdf", "html", "text")
        ):
            errors.append(
                "Japan pilot inventory must record non-negative PDF, HTML and text counts"
            )
        elif sum(acquired[name] for name in ("pdf", "html", "text")) < 1:
            errors.append(
                "Japan pilot must acquire at least one lawful public full text"
            )
        access_states = inventory.get("access_state_counts")
        if "not_exercised" in inventory:
            # New live runs preserve observed failures without manufacturing all
            # possible HTTP outcomes. Legacy fully exercised evidence stays valid.
            missing = inventory["not_exercised"]
            if (
                not isinstance(access_states, dict)
                or set(access_states) != DELIVERABLE_STATES
                or any(
                    type(count) is not int or count < 0
                    for count in access_states.values()
                )
                or not isinstance(missing, list)
                or any(not isinstance(state, str) for state in missing)
                or len(missing) != len(set(missing))
                or set(missing)
                != {state for state, count in access_states.items() if count == 0}
            ):
                errors.append(
                    "Japan pilot observed counts and not_exercised must partition all source states"
                )
            elif not any(
                access_states[state] > 0 for state in DELIVERABLE_FAILURE_STATES
            ):
                errors.append(
                    "Japan pilot requires at least one actual unavailable/access-error observation"
                )
            elif (
                not isinstance(acquired, dict)
                or any(
                    type(acquired.get(name)) is not int
                    for name in ("pdf", "html", "text")
                )
                or not isinstance(bindings, dict)
                or access_states["available"]
                != sum(acquired[name] for name in ("pdf", "html", "text"))
                or access_states["available"] != bindings.get("total")
            ):
                errors.append(
                    "Japan pilot available attempts, acquired full sources and bindings must reconcile"
                )
        elif not isinstance(access_states, dict) or any(
            type(access_states.get(name)) is not int or access_states[name] < 1
            for name in ("paywalled", "not-found", "parse-error", "login-page")
        ):
            errors.append(
                "Japan pilot inventory must exercise paywall, not-found, parse-error "
                "and login-page outcomes with positive distinct counts"
            )

    if validator_report is not None and (
        validator_report.get("status") != "passed"
        or validator_report.get("cross_format_reconciled") is not True
        or validator_report.get("tamper_test_rejected") is not True
    ):
        errors.append(
            "Japan pilot validator report must pass cross-format reconciliation "
            "and tamper rejection"
        )

    if guardrail_report is not None and (
        guardrail_report.get("status") != "passed"
        or guardrail_report.get("paywall_bypass") is not False
        or guardrail_report.get("abstract_as_full_text") is not False
        or guardrail_report.get("committed_paper_files") != 0
    ):
        errors.append(
            "Japan pilot repository guardrail must pass with no paywall bypass, "
            "abstract-as-full-text labels or committed paper files"
        )
    return errors


def validate_stage1_deliverable_claims(deliverable_evidence, manifest):
    """Reconcile human-readable PR counts with the bound pilot inventory."""

    inventory, errors = _read_json_artifact(manifest, "deliverable-inventory")
    if inventory is None:
        return errors
    outputs = inventory.get("outputs", {})
    bindings = inventory.get("source_bindings", {})
    acquired = inventory.get("acquired_full_text", {})
    access_states = inventory.get("access_state_counts", {})
    required_counts = (
        (
            outputs,
            (
                "excel",
                "markdown",
                "bibtex",
                "metadata",
                "claims",
                "screening",
                "coverage",
            ),
        ),
        (bindings, ("complete", "total")),
        (acquired, ("pdf", "html", "text")),
        (
            access_states,
            ("paywalled", "not-found", "parse-error", "login-page"),
        ),
    )
    if any(
        not isinstance(values, dict)
        or any(type(values.get(name)) is not int for name in names)
        for values, names in required_counts
    ):
        return errors

    expected_acquired = sum(acquired.get(name, 0) for name in ("pdf", "html", "text"))
    expected_total = expected_acquired + sum(
        access_states.get(name, 0)
        for name in ("paywalled", "not-found", "parse-error", "login-page")
    )
    if "not_exercised" in inventory and all(
        type(x) is int for x in access_states.values()
    ):
        expected_total = sum(access_states.values())
    acquisition_match = re.search(
        r"\b(\d+)\s*/\s*(\d+)\b",
        deliverable_evidence["Public source acquisition evidence"],
    )
    if not acquisition_match or tuple(map(int, acquisition_match.groups())) != (
        expected_acquired,
        expected_total,
    ):
        errors.append(
            "Public source acquisition claim does not match the Japan pilot inventory"
        )

    output_match = re.search(
        r"\b(\d+)\s+outputs?\s+passed\b",
        deliverable_evidence["Editable report evidence"],
        re.IGNORECASE,
    )
    expected_outputs = sum(
        outputs.get(name, 0)
        for name in (
            "excel",
            "markdown",
            "bibtex",
            "metadata",
            "claims",
            "screening",
            "coverage",
        )
    )
    if not output_match or int(output_match.group(1)) != expected_outputs:
        errors.append("Editable output claim does not match the Japan pilot inventory")

    binding_match = re.search(
        r"\b(\d+)\s*/\s*(\d+)\b",
        deliverable_evidence["Source binding evidence"],
    )
    if not binding_match or tuple(map(int, binding_match.groups())) != (
        bindings.get("complete"),
        bindings.get("total"),
    ):
        errors.append("Source binding claim does not match the Japan pilot inventory")

    states_match = re.search(
        r"\b(\d+)\s+(?:fixture\s+)?states?\s+(?:passed|observed)\b",
        deliverable_evidence["Access-state evidence"],
        re.IGNORECASE,
    )
    expected_state_types = sum(
        access_states.get(name, 0) > 0
        for name in ("paywalled", "not-found", "parse-error", "login-page")
    )
    if "not_exercised" in inventory:
        expected_state_types = sum(
            type(access_states.get(name)) is int and access_states[name] > 0
            for name in DELIVERABLE_FAILURE_STATES
        )
    if not states_match or int(states_match.group(1)) != expected_state_types:
        errors.append("Access-state claim does not match the Japan pilot inventory")
    return errors


def _evaluate_formal_paired_artifacts(manifest, repo_root, expected_decision):
    """Run the existing formal paired evaluator and compare its exact decision."""

    errors = []
    artifacts = manifest.get("_verified_artifacts", {})
    request_binding = artifacts.get("paired-request")
    decision_binding = artifacts.get("paired-decision")
    plan_binding = artifacts.get("frozen-plan")
    if not all((request_binding, decision_binding, plan_binding)):
        return ["formal paired evaluation artifacts are incomplete"]
    try:
        request = json.loads(
            request_binding["_resolved_path"].read_text(encoding="utf-8")
        )
        submitted_decision = json.loads(
            decision_binding["_resolved_path"].read_text(encoding="utf-8")
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        return [f"formal paired artifact is not readable JSON: {error}"]
    evaluator_path = (
        repo_root / "plugins/auto-research-agent/validators/paired_evaluation.py"
    ).resolve()
    if not evaluator_path.is_file():
        return ["formal paired evaluator is missing from the repository"]
    validator_root = str(evaluator_path.parent)
    sys.path.insert(0, validator_root)
    try:
        spec = importlib.util.spec_from_file_location(
            "_research_pr_paired_evaluation", evaluator_path
        )
        if spec is None or spec.loader is None:
            return ["formal paired evaluator could not be loaded"]
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        recomputed, evaluation_errors = module.evaluate_request(request)
    except (ImportError, OSError, ValueError, KeyError, TypeError) as error:
        return [f"formal paired evaluator failed closed: {error}"]
    finally:
        sys.path.remove(validator_root)
    if evaluation_errors:
        errors.extend(
            f"formal paired evaluator: {error}" for error in evaluation_errors
        )
        return errors
    if recomputed != submitted_decision:
        errors.append(
            "paired-decision artifact does not equal the evaluator's recomputed result"
        )
    if recomputed.get("decision") != expected_decision:
        errors.append(
            "recomputed paired decision does not match the Improvement statement"
        )
    repeats = {row.get("repeat") for row in recomputed.get("pair_results", [])}
    if repeats != {1, 2, 3} or len(request.get("bundles", [])) != 6:
        errors.append("formal evaluation must derive three pairs from six bundles")
    eval_root = (repo_root / "plugins/auto-research-agent/evals").resolve()
    requested_plan = request.get("plan", {}).get("path")
    if not isinstance(requested_plan, str):
        errors.append("paired request does not bind a frozen plan path")
    else:
        requested_path = (eval_root / requested_plan).resolve()
        if requested_path != plan_binding["_resolved_path"]:
            errors.append(
                "readiness manifest frozen-plan does not match the paired request"
            )
    return errors


def validate_readiness_manifest(
    manifest, readiness, improvement_status, repo_root=None
):
    errors = []
    if manifest.get("readiness") != readiness:
        errors.append("readiness manifest readiness does not match the PR claim")
    expected_scope = (
        "live-smoke" if readiness == "stage-executable" else "formal-paired"
    )
    if manifest.get("evidence_scope") not in {expected_scope, "contract-fixture"}:
        errors.append(f"{readiness} requires evidence_scope '{expected_scope}'")
    for field in ("execution_status", "validator_status", "resume_status"):
        if manifest.get(field) != "passed" and not (
            field == "execution_status" and manifest.get(field) == "complete"
        ):
            expected = "complete" if field == "execution_status" else "passed"
            errors.append(f"readiness manifest {field} must be '{expected}'")
    required_roles = {
        "live-run",
        "validator-report",
        "runtime-bytes",
        "dependency-bytes",
        "resume-report",
    }
    if readiness == "improvement-demonstrated":
        required_roles.update({"frozen-plan", "paired-request", "paired-decision"})
        if manifest.get("pair_count") != 3:
            errors.append("readiness manifest pair_count must be 3")
        if manifest.get("holdout_visibility") != "private" or not re.fullmatch(
            r"[0-9a-fA-F]{64}", str(manifest.get("holdout_manifest_sha256", ""))
        ):
            errors.append("readiness manifest must bind the private holdout SHA-256")
        expected_decision = (
            "improved" if improvement_status == "improved" else "not-improved"
        )
        if manifest.get("decision") != expected_decision:
            errors.append(
                "readiness manifest decision does not match the Improvement statement"
            )
    missing_roles = required_roles.difference(manifest.get("_verified_roles", set()))
    if missing_roles:
        errors.append(
            "readiness manifest missing verified artifact role(s): "
            + ", ".join(sorted(missing_roles))
        )
    if manifest.get("evidence_scope") != "contract-fixture":
        json_artifacts = {}
        for role in required_roles.difference({"runtime-bytes", "dependency-bytes"}):
            binding = manifest.get("_verified_artifacts", {}).get(role)
            if not binding:
                continue
            try:
                json_artifacts[role] = json.loads(
                    binding["_resolved_path"].read_text(encoding="utf-8")
                )
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                errors.append(f"readiness artifact '{role}' must be valid JSON")
        live_run = json_artifacts.get("live-run", {})
        validator_report = json_artifacts.get("validator-report", {})
        resume_report = json_artifacts.get("resume-report", {})
        if live_run.get("status") != "complete":
            errors.append("live-run artifact status must be complete")
        if validator_report.get("status") != "passed":
            errors.append("validator-report artifact status must be passed")
        if (
            resume_report.get("status") != "passed"
            or resume_report.get("reexecuted") is not False
        ):
            errors.append("resume-report artifact must be passed with reexecuted=false")
        if readiness == "improvement-demonstrated" and repo_root is not None:
            errors.extend(
                _evaluate_formal_paired_artifacts(
                    manifest, Path(repo_root), expected_decision
                )
            )
    return errors


def path_is_capability_entry(path):
    normalized = path.replace("\\", "/")
    if normalized in {
        ".github/scripts/validate_research_pr.py",
        ".github/scripts/check_research_pr_dependencies.py",
    }:
        return True
    roots = (
        "plugins/auto-research-agent/skills/",
        "plugins/auto-research-agent/tools/",
        "plugins/auto-research-agent/mcp/",
        "plugins/auto-research-agent/cli/",
        "plugins/auto-research-agent/validators/",
        "plugins/auto-research-agent/gates/",
    )
    matched_root = next((root for root in roots if normalized.startswith(root)), None)
    if matched_root is None:
        return False
    root_relative = normalized.removeprefix(matched_root)
    return (
        root_relative != "__init__.py"
        and Path(root_relative).name != "README.md"
        and not any(part == "__pycache__" for part in normalized.split("/"))
    )


def is_committed_paper_file(path):
    """Identify downloaded paper payloads while allowing declared synthetic fixtures."""

    normalized = path.replace("\\", "/")
    if SYNTHETIC_FIXTURE_PATH.search(normalized):
        return False
    suffix = Path(normalized).suffix.casefold()
    if suffix == ".pdf":
        return True
    return suffix in {".html", ".htm", ".txt"} and bool(
        RESEARCH_PAPER_TEXT_ROOT.search(normalized)
    )


def capabilities_for_changed_paths(changed_paths, known_capabilities):
    required = set()
    unowned = []
    for changed_path in changed_paths:
        normalized = changed_path.replace("\\", "/")
        if not path_is_capability_entry(normalized):
            continue
        owners = [
            capability_id
            for capability_id, entry in known_capabilities.items()
            if normalized == entry["owner_path"]
            or normalized.startswith(f"{entry['owner_path'].rstrip('/')}/")
        ]
        if owners:
            required.update(owners)
        else:
            unowned.append(normalized)
    return required, unowned


def changed_files(base_sha, head_sha, cwd=None):
    result = subprocess.run(
        [
            "git",
            "diff",
            "--name-only",
            "--diff-filter=ACMRT",
            f"{base_sha}...{head_sha}",
        ],
        check=True,
        capture_output=True,
        cwd=cwd,
        text=True,
    )
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def validate_pr_body(
    body,
    known_capabilities=None,
    changed_paths=None,
    known_rubrics=None,
    known_submetrics=None,
    known_criterion_submetrics=None,
    known_invariants=None,
    repo_root=None,
    current_repository=None,
    allow_contract_fixtures=False,
    execute_invariant_tests=True,
):
    repo_root = (
        Path(repo_root)
        if repo_root is not None
        else Path(__file__).resolve().parents[2]
    )
    current_repository = (
        current_repository or os.environ.get("GITHUB_REPOSITORY") or DEFAULT_REPOSITORY
    )
    current_owner, current_name = current_repository.split("/", 1)
    parsed = sections(body or "")
    errors = []
    for name in REQUIRED_SECTIONS:
        if name not in parsed:
            errors.append(f"missing section: ## {name}")
        elif not visible_text(parsed[name]):
            errors.append(f"empty section: ## {name}")
    for section, labels in REQUIRED_LABELS.items():
        for label in labels:
            if not label_has_value(parsed.get(section, ""), label):
                errors.append(f"{section} requires a non-empty '{label}:' value")
    target_metrics = label_value(parsed.get("Why", ""), "Target primary metric(s)")
    if not METRIC.search(target_metrics):
        errors.append("Target primary metric(s) must name at least one metric P1-P9")
    decision = label_value(parsed.get("What", ""), "Capability decision").lower()
    if decision not in CAPABILITY_DECISIONS:
        errors.append(
            "Capability decision must be exactly reuse, wrap, extend, or build-new"
        )
    deliverable_section = parsed.get("Research Deliverable", "")
    deliverable_applicability = label_value(
        deliverable_section, "Applicability"
    ).casefold()
    if deliverable_applicability not in RESEARCH_DELIVERABLE_APPLICABILITY:
        errors.append(
            "Research Deliverable Applicability must be exactly required or not-applicable"
        )
    deliverable_reason = label_value(deliverable_section, "Applicability reason")
    if deliverable_reason and (
        not text_is_concrete(deliverable_reason) or len(deliverable_reason) < 25
    ):
        errors.append(
            "Research Deliverable Applicability reason must concretely explain why it applies"
        )
    deliverable_evidence = {
        label: label_value(deliverable_section, label)
        for label in RESEARCH_DELIVERABLE_EVIDENCE_LABELS
    }
    if deliverable_applicability == "not-applicable":
        for label, value in deliverable_evidence.items():
            if value.casefold() != "not-applicable":
                errors.append(
                    f"Research Deliverable '{label}:' must be exactly not-applicable "
                    "when Applicability is not-applicable"
                )
    elif deliverable_applicability == "required":
        acquisition = deliverable_evidence[
            "Public source acquisition evidence"
        ].casefold()
        acquisition_requirements = {
            "PDF": ("pdf",),
            "HTML": ("html",),
            "text": ("text",),
            "lawfully public": ("lawful", "public"),
        }
        missing_acquisition = [
            name
            for name, aliases in acquisition_requirements.items()
            if not all(alias in acquisition for alias in aliases)
        ]
        if missing_acquisition:
            errors.append(
                "Public source acquisition evidence must cover: "
                + ", ".join(missing_acquisition)
            )
        acquisition_counts = [
            (int(found), int(total))
            for found, total in re.findall(r"\b(\d+)\s*/\s*(\d+)\b", acquisition)
        ]
        if not any(0 < found <= total for found, total in acquisition_counts):
            errors.append(
                "Public source acquisition evidence must report a positive acquired/total count"
            )
        editable = deliverable_evidence["Editable report evidence"].casefold()
        required_formats = {
            "Excel": ("excel", ".xlsx"),
            "Markdown": ("markdown", ".md"),
            "BibTeX": ("bibtex", ".bib"),
            "metadata": ("metadata",),
            "claims": ("claim",),
            "screening": ("screening",),
            "coverage": ("coverage",),
        }
        missing_formats = [
            name
            for name, aliases in required_formats.items()
            if not any(alias in editable for alias in aliases)
        ]
        if missing_formats:
            errors.append(
                "Editable report evidence must cover: " + ", ".join(missing_formats)
            )
        if not re.search(r"\b[1-9]\d*\s+outputs?\s+passed\b", editable):
            errors.append(
                "Editable report evidence must report a positive number of outputs passed"
            )
        binding = deliverable_evidence["Source binding evidence"].casefold()
        binding_requirements = {
            "work": ("work",),
            "version": ("version",),
            "URL/URI": ("url", "uri"),
            "access time": ("access time", "accessed at", "accessed_at"),
            "SHA-256": ("sha-256", "sha256"),
        }
        missing_bindings = [
            name
            for name, aliases in binding_requirements.items()
            if not any(alias in binding for alias in aliases)
        ]
        if missing_bindings:
            errors.append(
                "Source binding evidence must cover: " + ", ".join(missing_bindings)
            )
        binding_counts = [
            (int(complete), int(total))
            for complete, total in re.findall(r"\b(\d+)\s*/\s*(\d+)\b", binding)
        ]
        if not any(
            complete > 0 and complete == total for complete, total in binding_counts
        ):
            errors.append(
                "Source binding evidence must report a positive complete/total count"
            )
        access_states = deliverable_evidence["Access-state evidence"].casefold()
        state_requirements = {
            "paywall": ("paywall", "paywalled"),
            "not found": ("not found", "not-found", "not_found"),
            "parse error": ("parse error", "parse-error", "parse_error"),
            "login page": ("login page", "login-page", "login_page"),
        }
        missing_states = [
            name
            for name, aliases in state_requirements.items()
            if not any(alias in access_states for alias in aliases)
        ]
        if missing_states:
            errors.append(
                "Access-state evidence must distinguish: " + ", ".join(missing_states)
            )
        if not re.search(
            r"\b[1-9]\d*\s+(?:fixture\s+)?states?\s+(?:passed|observed)\b",
            access_states,
        ):
            errors.append(
                "Access-state evidence must report a positive number of states passed"
            )
        guardrail = deliverable_evidence[
            "Access and repository guardrail evidence"
        ].casefold()
        guardrail_requirements = {
            "lawfully public source": ("lawful", "public"),
            "no paywall bypass": ("no paywall bypass",),
            "abstract is not full text": ("abstract is not full text",),
            "paper files excluded from Git": ("paper files excluded from git",),
        }
        missing_guardrails = [
            name
            for name, aliases in guardrail_requirements.items()
            if not all(alias in guardrail for alias in aliases)
        ]
        if missing_guardrails:
            errors.append(
                "Access and repository guardrail evidence must cover: "
                + ", ".join(missing_guardrails)
            )
        pilot_evidence = deliverable_evidence["Japan pilot evidence"]
        pilot_match = AI_JUDGE_EVIDENCE.fullmatch(pilot_evidence)
        if (
            not pilot_match
            or pilot_match.group(1).casefold() != "artifact"
            or not BOUND_MANIFEST.fullmatch(pilot_match.group(2).strip())
        ):
            errors.append(
                "Japan pilot evidence must bind an artifact as "
                "'artifact: manifest=PATH; sha256=64HEX'"
            )
        else:
            pilot_manifest, pilot_errors = load_bound_readiness_manifest(
                pilot_match.group(2).strip(),
                repo_root,
                allow_contract_fixtures=allow_contract_fixtures,
            )
            errors.extend(f"Japan pilot: {error}" for error in pilot_errors)
            if pilot_manifest is not None:
                errors.extend(
                    f"Japan pilot: {error}"
                    for error in validate_stage1_deliverable_pilot_manifest(
                        pilot_manifest
                    )
                )
                errors.extend(
                    f"Japan pilot: {error}"
                    for error in validate_stage1_deliverable_claims(
                        deliverable_evidence, pilot_manifest
                    )
                )
    plain_summary = label_value(parsed.get("Why", ""), "Plain-language summary")
    if plain_summary and (
        not text_is_concrete(plain_summary) or len(plain_summary) < 25
    ):
        errors.append(
            "Plain-language summary must be one concrete sentence explaining the "
            "problem, change, and benefit"
        )
    external_prs = label_value(parsed.get("What", ""), "Related external PR(s)")
    if external_prs and external_prs.casefold() != "none":
        external_entries = [entry.strip() for entry in external_prs.split(";")]
        invalid_external = []
        for entry in external_entries:
            match = EXTERNAL_PR.fullmatch(entry)
            if not match or (
                match.group(1).casefold() == current_owner.casefold()
                and match.group(2).casefold() == current_name.casefold()
            ):
                invalid_external.append(entry)
        if invalid_external:
            errors.append(
                "Related external PR(s) must be 'None' or a semicolon-separated "
                "list of external GitHub pull-request URLs"
            )
    internal_prs = label_value(parsed.get("What", ""), "Internal prerequisite PR(s)")
    if internal_prs and internal_prs.casefold() != "none":
        invalid_internal = []
        for entry in semicolon_entries(internal_prs):
            match = EXTERNAL_PR.fullmatch(entry)
            if not match or (
                match.group(1).casefold() != current_owner.casefold()
                or match.group(2).casefold() != current_name.casefold()
            ):
                invalid_internal.append(entry)
        if invalid_internal:
            errors.append(
                "Internal prerequisite PR(s) must be 'None' or a semicolon-separated "
                f"list of {current_repository} pull-request URLs"
            )
    dependency_pins = label_value(parsed.get("What", ""), "External dependency pin(s)")
    dependency_entries = []
    if dependency_pins and dependency_pins.casefold() != "none":
        dependency_entries = semicolon_entries(dependency_pins)
        if any(not DEPENDENCY_PIN.fullmatch(entry) for entry in dependency_entries):
            errors.append(
                "External dependency pin(s) must be 'None' or entries formatted "
                "'PR_URL @ 40-character SHA @ open|merged'"
            )
    related_urls = {
        entry.rstrip("/")
        for entry in semicolon_entries(external_prs)
        if EXTERNAL_PR.fullmatch(entry)
    }
    pinned_urls = {
        match.group(1).rstrip("/")
        for entry in dependency_entries
        if (match := DEPENDENCY_PIN.fullmatch(entry))
    }
    if related_urls != pinned_urls:
        errors.append(
            "Related external PR(s) and External dependency pin(s) must name the same PR URLs"
        )
    improvement = label_value(parsed.get("Evaluation", ""), "Improvement statement")
    improvement_match = IMPROVEMENT_STATEMENT.fullmatch(improvement)
    if not improvement_match:
        errors.append(
            "Improvement statement must begin with improved, not improved, or "
            "not yet demonstrated and use '; evidence:' in the same sentence"
        )
    else:
        change = improvement_match.group(2)
        evidence = improvement_match.group(3)
        if (
            not text_is_concrete(change)
            or len(change.split()) < 4
            or not text_is_concrete(evidence)
            or not EVIDENCE_SIGNAL.search(evidence)
        ):
            errors.append(
                "Improvement statement must include a concrete change and a "
                "measurement, test result, artifact, or explicit milestone deferral"
            )
    readiness = label_value(
        parsed.get("Evaluation", ""), "Evaluation readiness"
    ).casefold()
    if readiness not in EVALUATION_READINESS:
        errors.append(
            "Evaluation readiness must be exactly implementation-only, "
            "stage-executable, or improvement-demonstrated"
        )
    improvement_status = (
        improvement_match.group(1).casefold() if improvement_match else ""
    )
    if (
        readiness in {"implementation-only", "stage-executable"}
        and improvement_status == "improved"
    ):
        errors.append(
            f"{readiness} readiness cannot claim 'improved' before the frozen paired evaluation"
        )
    if (
        readiness == "improvement-demonstrated"
        and improvement_status == "not yet demonstrated"
    ):
        errors.append(
            "improvement-demonstrated readiness cannot use 'not yet demonstrated'"
        )
    merge_owner = label_value(parsed.get("Validation", ""), "Review and merge owner")
    if merge_owner.casefold() != "core team":
        errors.append("Review and merge owner must be exactly 'core team'")
    execution_status = label_value(
        parsed.get("Validation", ""), "Execution status"
    ).casefold()
    if execution_status not in EXECUTION_STATUSES:
        errors.append("Execution status must be exactly complete, partial, or blocked")
    remaining = label_value(parsed.get("Validation", ""), "Remaining work or blocker")
    if remaining and remaining.casefold() != "none" and not text_is_concrete(remaining):
        errors.append("Remaining work or blocker must be 'None' or concrete")
    if execution_status in {"partial", "blocked"} and remaining.casefold() == "none":
        errors.append(
            "Partial or blocked execution must describe the remaining work or blocker"
        )
    declared_metrics = set(METRIC.findall(target_metrics))
    rubrics = known_rubrics if known_rubrics is not None else load_rubrics()
    rubric_version = label_value(parsed.get("Evaluation", ""), "Rubric version")
    rubric_criteria = rubrics.get(rubric_version, {})
    if rubric_version == "stage1-general-v3" and readiness != "implementation-only":
        errors.append(
            "experimental v3 rubric currently permits only implementation-only readiness"
        )
    if (
        rubric_version in {"stage2-general-v2", "stage2-general-v3"}
        and readiness != "implementation-only"
    ):
        errors.append(
            "experimental Stage2 rubric currently permits only implementation-only readiness"
        )
    if rubric_version and rubric_version not in rubrics:
        errors.append("Rubric version must name a registered rubric version")
    declared_criteria = capability_ids(
        label_value(parsed.get("Evaluation", ""), "Rubric criterion ID(s)")
    )
    unknown_criteria = [
        criterion_id
        for criterion_id in declared_criteria
        if criterion_id not in rubric_criteria
    ]
    if unknown_criteria:
        errors.append(
            "unknown rubric criterion ID(s): " + ", ".join(sorted(unknown_criteria))
        )
    criterion_metrics = {
        rubric_criteria[criterion_id]
        for criterion_id in declared_criteria
        if criterion_id in rubric_criteria
    }
    undeclared_criterion_metrics = criterion_metrics.difference(declared_metrics)
    if undeclared_criterion_metrics:
        errors.append(
            "rubric criteria require undeclared target metric(s): "
            + ", ".join(sorted(undeclared_criterion_metrics))
        )
    missing_criterion_metrics = declared_metrics.difference(criterion_metrics)
    if missing_criterion_metrics:
        errors.append(
            "target metrics missing a rubric criterion ID: "
            + ", ".join(sorted(missing_criterion_metrics))
        )
    mapping_entries = semicolon_entries(
        label_value(parsed.get("Evaluation", ""), "Operational-definition mapping")
    )
    submetrics = (
        known_submetrics
        if known_submetrics is not None
        else load_operational_submetrics()
    )
    criterion_submetrics = (
        known_criterion_submetrics
        if known_criterion_submetrics is not None
        else load_criterion_submetrics()
    )
    declared_capabilities = capability_ids(
        label_value(parsed.get("What", ""), "Affected capability ID(s)")
    )
    if (
        RESEARCH_DELIVERABLE_CAPABILITY in declared_capabilities
        and deliverable_applicability != "required"
    ):
        errors.append(
            "cli:stage1-deliverable changes require the Stage 1 research deliverable"
        )
    mapped_criteria = set()
    for entry in mapping_entries:
        match = OPERATIONAL_MAPPING.fullmatch(entry)
        if not match:
            errors.append(
                "Operational-definition mapping entries must use "
                "'CRITERION -> FROZEN_SUBMETRIC -> production.field_or_function'"
            )
            continue
        criterion_id, submetric_id, production_target = match.groups()
        mapped_criteria.add(criterion_id)
        if submetric_id not in submetrics:
            errors.append(f"unknown frozen operational submetric: {submetric_id}")
        elif (
            criterion_id in rubric_criteria
            and rubric_criteria[criterion_id] not in submetrics[submetric_id]
        ):
            errors.append(
                f"operational submetric {submetric_id} does not measure "
                f"{rubric_criteria[criterion_id]} for {criterion_id}"
            )
        allowed_submetrics = criterion_submetrics.get(criterion_id, set())
        if allowed_submetrics and submetric_id not in allowed_submetrics:
            errors.append(
                f"criterion {criterion_id} must map to frozen submetric(s): "
                + ", ".join(sorted(allowed_submetrics))
            )
        if not production_symbol_exists(
            production_target,
            declared_capabilities,
            known_capabilities,
            repo_root,
        ):
            errors.append(
                f"operational mapping target does not exist under a declared "
                f"production owner: {production_target}"
            )
    missing_mappings = set(declared_criteria).difference(mapped_criteria)
    extra_mappings = mapped_criteria.difference(declared_criteria)
    if missing_mappings:
        errors.append(
            "operational mapping missing declared criterion ID(s): "
            + ", ".join(sorted(missing_mappings))
        )
    if extra_mappings:
        errors.append(
            "operational mapping contains undeclared criterion ID(s): "
            + ", ".join(sorted(extra_mappings))
        )
    evaluation_mode = label_value(
        parsed.get("Evaluation", ""), "Evaluation mode"
    ).casefold()
    if evaluation_mode not in EVALUATION_MODES:
        errors.append(
            "Evaluation mode must be exactly deterministic, ai-judge, or hybrid"
        )
    per_pr_evidence = label_value(
        parsed.get("Evaluation", ""), "Per-PR metric evidence"
    )
    if not text_is_concrete(per_pr_evidence) or not EVIDENCE_SIGNAL.search(
        per_pr_evidence
    ):
        errors.append(
            "Per-PR metric evidence must name an actual passed/failed result, count, "
            "measurement, or artifact"
        )
    ai_judge_evidence = label_value(parsed.get("Evaluation", ""), "AI-judge evidence")
    evidence_match = AI_JUDGE_EVIDENCE.fullmatch(ai_judge_evidence)
    evidence_kind = evidence_match.group(1).casefold() if evidence_match else ""
    evidence_detail = evidence_match.group(2).strip() if evidence_match else ""
    invalid_evidence = not evidence_match or not text_is_concrete(evidence_detail)
    if evidence_kind == "artifact":
        invalid_evidence |= ARTIFACT_REF.search(evidence_detail) is None
    elif evidence_kind in {"deferred", "not-applicable"}:
        invalid_evidence |= len(evidence_detail.split()) < 5
    if ai_judge_evidence and invalid_evidence:
        errors.append(
            "AI-judge evidence must use 'artifact: PATH', 'deferred: REASON', "
            "or 'not-applicable: REASON' with concrete detail"
        )
    required_ids = set(
        capability_ids(
            label_value(parsed.get("Evaluation", ""), "Required invariant IDs")
        )
    )
    invalid_invariant_ids = sorted(
        invariant_id
        for invariant_id in required_ids
        if not INVARIANT_ID.fullmatch(invariant_id)
    )
    if invalid_invariant_ids:
        errors.append("invalid invariant ID(s): " + ", ".join(invalid_invariant_ids))
    invariant_registry = (
        known_invariants if known_invariants is not None else load_invariant_registry()
    )
    unknown_invariant_ids = required_ids.difference(invariant_registry)
    if unknown_invariant_ids:
        errors.append(
            "unknown invariant ID(s): " + ", ".join(sorted(unknown_invariant_ids))
        )
    derived_ids = required_invariants(
        declared_criteria, declared_capabilities, known_capabilities
    )
    missing_required_ids = derived_ids.difference(required_ids)
    if missing_required_ids:
        errors.append(
            "Required invariant IDs missing derived invariant(s): "
            + ", ".join(sorted(missing_required_ids))
        )
    evidence_entries = semicolon_entries(
        label_value(parsed.get("Evaluation", ""), "Invariant test evidence")
    )
    evidenced_ids = set()
    for entry in evidence_entries:
        match = INVARIANT_EVIDENCE.fullmatch(entry)
        if not match:
            errors.append(
                "Invariant test evidence entries must use "
                "'INVARIANT -> PATH.py::Class.test_method -> passed|failed'"
            )
            continue
        invariant_id, path, selector, result = match.groups()
        evidenced_ids.add(invariant_id)
        if result.casefold() != "passed":
            errors.append(f"invariant '{invariant_id}' test result must be passed")
        if not selector_exists(path, selector, repo_root):
            errors.append(
                f"invariant '{invariant_id}' test selector does not exist: "
                f"{path}::{selector}"
            )
            continue
        registration = invariant_registry.get(invariant_id)
        if registration and (
            not any(
                re.fullmatch(pattern, path) for pattern in registration["path_patterns"]
            )
            or not re.fullmatch(registration["selector_pattern"], selector)
        ):
            errors.append(
                f"invariant '{invariant_id}' evidence selector is not allowed by "
                "invariant-registry.v1.json"
            )
            continue
        if selector_is_skipped(path, selector, repo_root):
            errors.append(f"invariant '{invariant_id}' test selector is skipped")
            continue
        if execute_invariant_tests and not os.environ.get(
            "RESEARCH_PR_INVARIANT_CHILD"
        ):
            passed, output = execute_selector(path, selector, repo_root)
            if not passed:
                errors.append(
                    f"invariant '{invariant_id}' exact test selector failed: "
                    f"{path}::{selector}; output: {output or '<none>'}"
                )
    missing_evidence_ids = required_ids.difference(evidenced_ids)
    if missing_evidence_ids:
        errors.append(
            "Invariant test evidence missing required invariant(s): "
            + ", ".join(sorted(missing_evidence_ids))
        )
    undeclared_evidence_ids = evidenced_ids.difference(required_ids)
    if undeclared_evidence_ids:
        errors.append(
            "Invariant test evidence contains undeclared invariant(s): "
            + ", ".join(sorted(undeclared_evidence_ids))
        )
    readiness_evidence = {}
    for label in (
        "Live smoke evidence",
        "Paired evaluation evidence",
        "Runtime integrity evidence",
    ):
        raw_value = label_value(parsed.get("Evaluation", ""), label)
        kind, detail = evidence_value(raw_value)
        readiness_evidence[label] = (kind, detail)
        invalid = not kind or not text_is_concrete(detail)
        if kind == "artifact":
            invalid |= ARTIFACT_REF.search(detail) is None
        elif kind in {"deferred", "not-applicable"}:
            invalid |= len(detail.split()) < 5
        if raw_value and invalid:
            errors.append(
                f"{label} must use 'artifact: PATH', 'deferred: REASON', or "
                "'not-applicable: REASON' with concrete detail"
            )
    bound_manifests = {}
    if readiness in {"stage-executable", "improvement-demonstrated"}:
        if execution_status != "complete":
            errors.append(f"{readiness} readiness requires Execution status: complete")
        live_kind, live_detail = readiness_evidence.get("Live smoke evidence", ("", ""))
        if live_kind != "artifact":
            errors.append(
                f"{readiness} readiness requires hash-bound Live smoke evidence"
            )
        else:
            manifest, manifest_errors = load_bound_readiness_manifest(
                live_detail, repo_root, allow_contract_fixtures
            )
            errors.extend(f"Live smoke evidence: {error}" for error in manifest_errors)
            if manifest is not None:
                bound_manifests["Live smoke evidence"] = manifest
        runtime_kind, runtime_detail = readiness_evidence.get(
            "Runtime integrity evidence", ("", "")
        )
        if runtime_kind != "artifact":
            errors.append(
                f"{readiness} readiness requires hash-bound Runtime integrity evidence"
            )
        else:
            manifest, manifest_errors = load_bound_readiness_manifest(
                runtime_detail, repo_root, allow_contract_fixtures
            )
            errors.extend(
                f"Runtime integrity evidence: {error}" for error in manifest_errors
            )
            if manifest is not None:
                bound_manifests["Runtime integrity evidence"] = manifest
        for entry in dependency_entries:
            match = DEPENDENCY_PIN.fullmatch(entry)
            if match and match.group(3).casefold() != "merged":
                errors.append(
                    f"{readiness} readiness requires every external dependency pin "
                    "to declare merged"
                )
    if readiness == "improvement-demonstrated":
        paired_kind, paired_detail = readiness_evidence.get(
            "Paired evaluation evidence", ("", "")
        )
        if paired_kind != "artifact":
            errors.append(
                "improvement-demonstrated readiness requires hash-bound paired evidence"
            )
        else:
            manifest, manifest_errors = load_bound_readiness_manifest(
                paired_detail, repo_root, allow_contract_fixtures
            )
            errors.extend(
                f"Paired evaluation evidence: {error}" for error in manifest_errors
            )
            if manifest is not None:
                bound_manifests["Paired evaluation evidence"] = manifest
        if evidence_kind != "artifact":
            errors.append(
                "improvement-demonstrated readiness requires AI-judge evidence as an artifact"
            )
        live_ab = label_value(parsed.get("Evaluation", ""), "Live paired A/B")
        live_ab_kind, live_ab_detail = evidence_value(live_ab)
        if live_ab_kind != "artifact":
            errors.append(
                "improvement-demonstrated readiness requires Live paired A/B as an artifact"
            )
        else:
            manifest, manifest_errors = load_bound_readiness_manifest(
                live_ab_detail, repo_root, allow_contract_fixtures
            )
            errors.extend(f"Live paired A/B: {error}" for error in manifest_errors)
            if manifest is not None:
                bound_manifests["Live paired A/B"] = manifest
        if evidence_kind == "artifact":
            manifest, manifest_errors = load_bound_readiness_manifest(
                evidence_detail, repo_root, allow_contract_fixtures
            )
            errors.extend(f"AI-judge evidence: {error}" for error in manifest_errors)
            if manifest is not None:
                bound_manifests["AI-judge evidence"] = manifest
    if bound_manifests:
        bindings = {manifest["_binding"] for manifest in bound_manifests.values()}
        if len(bindings) != 1:
            errors.append(
                "all readiness artifact fields must bind the same manifest bytes"
            )
        for manifest in bound_manifests.values():
            errors.extend(
                validate_readiness_manifest(
                    manifest, readiness, improvement_status, repo_root
                )
            )
    if any(
        capability_id.startswith("skill:") for capability_id in declared_capabilities
    ):
        validation = parsed.get("Validation", "")
        for label in SKILL_TEST_LABELS:
            if not label_has_concrete_value(validation, label):
                errors.append(
                    f"Validation requires a concrete '{label}:' value for skill changes"
                )
    if known_capabilities is not None:
        for capability_id in declared_capabilities:
            if capability_id not in known_capabilities:
                errors.append(
                    f"unknown capability ID '{capability_id}'; register it in "
                    "capability-metric-map.v1.json"
                )
                continue
            capability_metrics = known_capabilities[capability_id]["metrics"]
            if declared_metrics.isdisjoint(capability_metrics):
                expected = ", ".join(sorted(capability_metrics))
                errors.append(
                    f"capability '{capability_id}' has no declared target metric in common "
                    f"with its registry entry ({expected})"
                )
            capability_criteria = known_capabilities[capability_id].get(
                "criteria", set()
            )
            if capability_criteria and set(declared_criteria).isdisjoint(
                capability_criteria
            ):
                expected = ", ".join(sorted(capability_criteria))
                errors.append(
                    f"capability '{capability_id}' has no declared rubric criterion "
                    f"in common with its registry entry ({expected})"
                )
        if changed_paths is not None:
            required, unowned = capabilities_for_changed_paths(
                changed_paths, known_capabilities
            )
            for path in unowned:
                errors.append(f"changed capability path '{path}' has no registry owner")
            missing = required.difference(declared_capabilities)
            if missing:
                errors.append(
                    "changed capabilities missing from 'Affected capability ID(s):': "
                    + ", ".join(sorted(missing))
                )
            required_capabilities, _ = capabilities_for_changed_paths(
                changed_paths, known_capabilities
            )
            if (
                RESEARCH_DELIVERABLE_CAPABILITY in required_capabilities
                and deliverable_applicability != "required"
            ):
                errors.append(
                    "Stage 1 deliverable implementation paths require Research "
                    "Deliverable Applicability: required"
                )
            committed_papers = [
                path.replace("\\", "/")
                for path in changed_paths
                if is_committed_paper_file(path)
            ]
            if committed_papers:
                errors.append(
                    "Downloaded paper files must stay out of Git: "
                    + ", ".join(sorted(committed_papers))
                )
    example = visible_text(parsed.get("Example", ""))
    for label in ("Before", "After"):
        if not re.search(rf"^{label}:[ \t]*[^\s\r\n].*$", example, re.MULTILINE):
            errors.append(f"Example requires a non-empty '{label}:' value")
    return errors


def context_from_event(path):
    event = json.loads(path.read_text(encoding="utf-8"))
    pull_request = event.get("pull_request")
    if not pull_request:
        return None
    return {
        "body": pull_request.get("body") or "",
        "base_sha": pull_request["base"]["sha"],
        "head_sha": pull_request["head"]["sha"],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--body-file", type=Path)
    args = parser.parse_args()
    if args.body_file:
        body = args.body_file.read_text(encoding="utf-8")
        paths = None
    else:
        event_path = os.environ.get("GITHUB_EVENT_PATH")
        if not event_path:
            print("No pull-request event; PR contract check skipped.")
            return 0
        context = context_from_event(Path(event_path))
        if context is None:
            print("No pull-request event; PR contract check skipped.")
            return 0
        body = context["body"]
        paths = changed_files(context["base_sha"], context["head_sha"])
    errors = validate_pr_body(body, load_capability_metrics(), paths, load_rubrics())
    if errors:
        print("Research PR contract failed:")
        for error in errors:
            print(f"- {error}")
        return 1
    print("Research PR contract passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
