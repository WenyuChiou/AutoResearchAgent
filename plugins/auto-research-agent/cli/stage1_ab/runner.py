"""Freeze, inspect, capture, and verify blinded Stage 1 subject runs.

The evaluator owns the private plan and answer bytes. Only the public lock may
be moved to a subject host. This module never supplies an answer to Codex.
"""

import hashlib
import json
import os
from pathlib import Path
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import tomllib
from contextlib import nullcontext
from datetime import datetime, timezone

PLUGIN_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = PLUGIN_ROOT.parents[1]
sys.path.insert(0, str(PLUGIN_ROOT))

from validators.evaluation_plan import validate_plan  # noqa: E402
from validators.holdout_manifest import canonical_sha256  # noqa: E402
from stage1_retrieval.receipt import check_pin  # noqa: E402
from stage1_retrieval.runtime_identity import verify_identity  # noqa: E402
from stage1_export.bundle import source_state  # noqa: E402
from . import sequence  # noqa: E402

PROMPT_SHA256 = "9a73fa53b1e660d5a800aa433db617858f24c7c031fe52b302a404fddb769dfd"
RESEARCH_HUB_SHA = "9877f929587e7e44bc2533db118cbb89336bf94f"
FORMAL_CASE = "aging-sk-bidirectional-development-v2"
SUBJECT_EXECUTION_POLICY = {"sandbox": "workspace-write", "network_access": True}
SUBJECT_SANDBOX_ARGS = [
    "--sandbox",
    "workspace-write",
    "-c",
    "sandbox_workspace_write.network_access=true",
]


class ExecutionBlocked(ValueError):
    pass


def sha(data):
    return hashlib.sha256(data).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise ExecutionBlocked(f"output already exists: {path}")
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def verify_bound_file(root, binding):
    root = Path(root).resolve()
    target = (root / binding["path"]).resolve()
    if not target.is_relative_to(root) or not target.is_file():
        raise ExecutionBlocked(
            f"bound file is missing or escapes root: {binding['path']}"
        )
    if sha(target.read_bytes()) != binding["sha256"]:
        raise ExecutionBlocked(f"bound file byte hash differs: {binding['path']}")
    return target


def verify_private_bytes(plan, holdout, eval_root):
    for key in ("answer_key", "candidate_screening_log"):
        verify_bound_file(eval_root, holdout[key])
    for approval in holdout["curation"]["human_approvals"]:
        verify_bound_file(eval_root, approval["approval_artifact"])
    for approval in plan["human_approvals"]:
        verify_bound_file(eval_root, approval["artifact"])
    verify_bound_file(eval_root, plan["bindings"]["condition_map"])


def tree_sha(root):
    root = Path(root).resolve()
    if not root.is_dir():
        raise ExecutionBlocked(f"plugin tree missing: {root}")
    rows = []
    # Path ordering follows the host filesystem (case-insensitive on Windows).
    # Freeze a byte-identical plugin tree to the same digest on every host.
    for p in sorted(
        root.rglob("*"), key=lambda path: path.relative_to(root).as_posix()
    ):
        if p.is_file() and not any(
            x in {"__pycache__", ".pytest_cache", "private"}
            for x in p.relative_to(root).parts
        ):
            rows.append(
                p.relative_to(root).as_posix().encode()
                + b"\0"
                + hashlib.sha256(p.read_bytes()).digest()
            )
    return sha(b"\n".join(rows))


def _runtime_pin(path, expected_sha=None, *, verify_host=False, workspace=None):
    """Read the reviewed public CLI pin; host checks bind executable bytes."""
    if path is None:
        raise ExecutionBlocked("treatment runtime pin is required")
    path = Path(path).resolve()
    raw = path.read_bytes()
    if expected_sha is not None and sha(raw) != expected_sha:
        raise ExecutionBlocked("treatment runtime pin bytes differ from frozen lock")
    pin = json.loads(raw)
    check_pin(pin)
    if pin.get("revision") != RESEARCH_HUB_SHA or pin.get("status") != "merged":
        raise ExecutionBlocked("treatment runtime pin differs from merged research-hub")
    if verify_host:
        config_path = Path(pin["config"]["path"]).resolve()
        if sha(config_path.read_bytes()) != pin["config"]["sha256"]:
            raise ExecutionBlocked("treatment runtime config bytes changed")
        if workspace is not None:
            data_paths = json.loads(config_path.read_text(encoding="utf-8"))[
                "knowledge_base"
            ]
            if not all(
                Path(value).resolve().is_relative_to(Path(workspace).resolve())
                for value in data_paths.values()
            ):
                raise ExecutionBlocked(
                    "treatment runtime data escapes subject workspace"
                )
        verify_identity(pin, probe=True)
    return pin, sha(raw)


def _pin_paths(value, repeats):
    paths = value if isinstance(value, (list, tuple)) else [value]
    if len(paths) != repeats or any(path is None for path in paths):
        raise ExecutionBlocked(
            f"one treatment runtime pin per repeat required ({repeats})"
        )
    resolved = [Path(path).resolve() for path in paths]
    if len(set(resolved)) != repeats:
        raise ExecutionBlocked("each repeat needs a distinct treatment runtime pin")
    return resolved


def _repeat_pin_sha(lock, repeat):
    by_repeat = lock.get("treatment_runtime_pin_sha256_by_repeat")
    if by_repeat is not None:
        return by_repeat.get(str(repeat))
    if len(lock.get("paired_repeats", [])) == 1 and repeat == 1:
        return lock.get("treatment_runtime_pin_sha256")
    return None


def _repeat_subject_path(root, repeat, repeats):
    root = Path(root).resolve()
    return root if repeats == 1 else root / f"repeat-{repeat:02d}"


def _preflight_binding(preflight, repeat):
    bindings = preflight.get("repeat_bindings")
    if bindings is not None:
        return bindings[str(repeat)]
    if repeat == 1:
        return preflight
    raise ExecutionBlocked("host preflight lacks per-repeat isolation")


def _native_config_sha(config_text, probe_workspace=None):
    try:
        settings = tomllib.loads(config_text)
    except tomllib.TOMLDecodeError as exc:
        raise ExecutionBlocked("subject profile config is invalid TOML") from exc
    settings.pop("marketplaces", None)
    settings.pop("plugins", None)
    if probe_workspace is not None:
        projects = settings.get("projects", {})
        projects.pop(str(Path(probe_workspace).resolve()), None)
        if not projects:
            settings.pop("projects", None)
    return sha(json.dumps(settings, sort_keys=True).encode())


def _skill_probe_directory(profile):
    profile = Path(profile).resolve()
    return profile.parent / f"{profile.name}-stage1-skill-probe"


def freeze(plan_path, prompt_path, dependency_repo, output, treatment_runtime_pin=None):
    """Run on the evaluator, with its private evals tree. Emits no answer data."""
    plan = read_json(plan_path)
    errors = validate_plan(plan)
    if errors:
        raise ExecutionBlocked("invalid frozen plan: " + "; ".join(errors))
    if plan["execution_class"] != "formal" or plan["status"] != "frozen":
        raise ExecutionBlocked("formal execution requires a frozen formal plan")
    if plan["case_id"] != FORMAL_CASE or plan["metric_ids"] != ["P1", "P2", "P3"]:
        raise ExecutionBlocked("wrong Stage 1 case or metrics")
    if set(plan["target_metric_ids"]) != {"P2", "P3"}:
        raise ExecutionBlocked("formal Stage 1 targets must be P2 and P3")
    runtime = plan["subject_runtime"]
    if (
        runtime["model_id"],
        runtime["reasoning"],
        runtime["mode"],
        runtime["search_enabled"],
    ) != ("gpt-5.6-sol", "high", "default", True):
        raise ExecutionBlocked("model, reasoning, mode, or search differs")
    prompt = Path(prompt_path).read_bytes()
    if len(prompt) != 1247 or sha(prompt) != PROMPT_SHA256:
        raise ExecutionBlocked("exact subject prompt bytes differ")
    if plan["bindings"]["prompt"]["artifact"]["sha256"] != PROMPT_SHA256:
        raise ExecutionBlocked("frozen plan prompt differs")
    eval_root = PLUGIN_ROOT / "evals"
    holdout_name = plan["bindings"]["holdout"]["path"]
    holdout_path = (eval_root / holdout_name).resolve()
    if (
        not holdout_path.is_relative_to(eval_root.resolve())
        or not holdout_path.is_file()
    ):
        raise ExecutionBlocked("private holdout path is missing or escapes evals")
    holdout = read_json(holdout_path)
    if canonical_sha256(holdout) != plan["bindings"]["holdout"]["canonical_sha256"]:
        raise ExecutionBlocked("holdout canonical hash differs")
    verify_private_bytes(plan, holdout, eval_root)
    approval_ids = [approval["actor_id"] for approval in plan["human_approvals"]]
    single_human = holdout["schema_version"] == "2.1.0"
    curator_attestations = {
        actor["actor_id"]: actor["attestation_ref"]
        for actor in holdout["curation"]["actors"]
    }
    if (
        len(approval_ids) != len(set(approval_ids))
        or (single_human and len(approval_ids) != 1)
        or (not single_human and len(approval_ids) < 2)
        or (
            single_human
            and (
                set(approval_ids) != set(curator_attestations)
                or any(
                    approval["attestation_ref"]
                    != curator_attestations.get(approval["actor_id"])
                    for approval in plan["human_approvals"]
                )
            )
        )
    ):
        raise ExecutionBlocked(
            "final human approvals must match the frozen holdout curators"
        )
    dep = subprocess.run(
        ["git", "-C", str(dependency_repo), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    )
    if dep.stdout.strip() != RESEARCH_HUB_SHA:
        raise ExecutionBlocked("research-hub checkout does not match merged SHA")
    if (
        plan["bindings"].get("stage1_readiness", {}).get("research_hub_sha")
        != RESEARCH_HUB_SHA
    ):
        raise ExecutionBlocked("frozen plan lacks research-hub pin")
    repeats = (
        len(sequence.expected_runs({"paired_repeats": plan["paired_repeats"]})) // 2
    )
    pin_paths = _pin_paths(treatment_runtime_pin, repeats)
    pin_shas = {
        str(index): _runtime_pin(path)[1] for index, path in enumerate(pin_paths, 1)
    }
    lock = {
        "kind": "Stage1ABPublicLock",
        "schema_version": "1.0.0",
        "plan_sha256": canonical_sha256(plan),
        "holdout_sha256": canonical_sha256(holdout),
        "prompt_sha256": PROMPT_SHA256,
        "readiness_sha256": plan["bindings"]["stage1_readiness"]["sha256"],
        "research_hub_sha": RESEARCH_HUB_SHA,
        "treatment_runtime_pin_sha256_by_repeat": pin_shas,
        "plugin_tree_sha256": tree_sha(PLUGIN_ROOT),
        "case_id": FORMAL_CASE,
        "runtime": runtime,
        "execution_policy": SUBJECT_EXECUTION_POLICY,
        "builds": {
            condition: plan["bindings"][condition + "_build"]
            for condition in ("baseline", "treatment")
        },
        "paired_repeats": plan["paired_repeats"],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    write_json(output, lock)
    return lock


def _assert_host_isolation(
    profile, workspace, private_root, prohibited_ids, allow_existing_workspace=False
):
    profile, workspace = Path(profile).resolve(), Path(workspace).resolve()
    if (
        profile == workspace
        or profile.is_relative_to(workspace)
        or workspace.is_relative_to(profile)
    ):
        raise ExecutionBlocked("profile and workspace must be separate")
    if (
        not profile.is_dir()
        or not workspace.is_dir()
        or (not allow_existing_workspace and any(workspace.iterdir()))
    ):
        raise ExecutionBlocked("profile missing or subject workspace is not empty")
    rules_dir = profile / "rules"
    if rules_dir.exists() or rules_dir.is_symlink():
        raise ExecutionBlocked(
            "clean subject profile must not contain Codex exec rules"
        )
    if Path(private_root).exists():
        raise ExecutionBlocked("private answer tree is present on subject host")
    for root in (profile, workspace):
        for path in root.rglob("*"):
            if path.is_symlink():
                raise ExecutionBlocked("subject profile/workspace contains a symlink")
            if path.is_file():
                rel = path.relative_to(root)
                if "private" in {part.casefold() for part in rel.parts}:
                    raise ExecutionBlocked(
                        "readable private file in subject environment"
                    )
                if not (
                    root == profile and rel.parts[:2] == ("plugins", "cache")
                ) and re.search(
                    r"answer.?key|holdout|human.?ratings|source.?packet",
                    path.name,
                    re.IGNORECASE,
                ):
                    raise ExecutionBlocked("answer-like file in subject environment")
            if path.is_file() and path.stat().st_size <= 2_000_000:
                data = path.read_bytes()
                if any(token.encode() in data for token in prohibited_ids):
                    raise ExecutionBlocked(
                        "private answer identifier in subject environment"
                    )


def probe_profile(
    codex,
    profile,
    workspace,
    expected_plugin,
    private_root,
    prohibited_ids=(),
    allow_existing_workspace=False,
    probe_evidence_dir=None,
):
    """Read-only probe; a missing login or uncertain plugin discovery blocks launch."""
    _assert_host_isolation(
        profile, workspace, private_root, prohibited_ids, allow_existing_workspace
    )
    env = dict(os.environ, CODEX_HOME=str(Path(profile).resolve()))
    version = subprocess.run(
        [str(codex), "--version"], env=env, capture_output=True, text=True, timeout=20
    )
    login = subprocess.run(
        [str(codex), "login", "status"],
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
    )
    if (
        version.returncode
        or login.returncode
        or "Logged in" not in (login.stdout + login.stderr)
    ):
        raise ExecutionBlocked(
            "clean condition profile lacks verified Codex authentication"
        )
    config = Path(profile) / "config.toml"
    config_text = config.read_text(encoding="utf-8") if config.exists() else ""
    if re.search(r"\[mcp_servers\.|model_provider", config_text) or (
        not expected_plugin and re.search(r"\[plugins\.|marketplace", config_text)
    ):
        raise ExecutionBlocked(
            "condition profile has unreviewed extension or provider config"
        )
    # The public plugin API observes effective workspace discovery. Handshake
    # must complete before later requests; sending them all at once is invalid.
    with tempfile.TemporaryFile() as stderr:
        process = subprocess.Popen(
            [str(codex), "app-server", "--stdio"],
            env=env,
            cwd=workspace,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=stderr,
            text=True,
            encoding="utf-8",
        )
        replies = queue.Queue()

        def read_replies():
            for line in process.stdout:
                try:
                    replies.put(json.loads(line))
                except json.JSONDecodeError:
                    replies.put({"invalid": line[:80]})

        reader = threading.Thread(target=read_replies, daemon=True)
        reader.start()

        def request(number, method, params):
            process.stdin.write(
                json.dumps({"id": number, "method": method, "params": params}) + "\n"
            )
            process.stdin.flush()
            while True:
                try:
                    response = replies.get(timeout=30)
                except queue.Empty as exc:
                    raise ExecutionBlocked(f"{method} timed out") from exc
                if response.get("id") == number:
                    if "error" in response:
                        raise ExecutionBlocked(f"{method} failed: {response['error']}")
                    return response.get("result")

        try:
            request(
                1,
                "initialize",
                {
                    "clientInfo": {"name": "stage1-ab-preflight", "version": "1"},
                    "capabilities": {"experimentalApi": True},
                },
            )
            process.stdin.write('{"method":"initialized"}\n')
            process.stdin.flush()
            listing = request(
                2,
                "plugin/list",
                {
                    "cwds": [str(Path(workspace).resolve())],
                    "marketplaceKinds": ["local"],
                },
            )
            models = request(3, "model/list", {"includeHidden": True, "limit": 100})
            capabilities = request(4, "modelProvider/capabilities/read", {})
            if expected_plugin:
                market = next(
                    (
                        m
                        for m in listing.get("marketplaces", [])
                        if any(
                            p.get("name") == "auto-research-agent"
                            for p in m.get("plugins", [])
                        )
                    ),
                    None,
                )
                if market is None:
                    raise ExecutionBlocked("treatment marketplace missing")
                detail = request(
                    5,
                    "plugin/read",
                    {
                        "marketplacePath": market["path"],
                        "pluginName": "auto-research-agent",
                    },
                )
            else:
                detail = None
        finally:
            process.stdin.close()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.terminate()
                process.wait(timeout=5)
            reader.join(timeout=5)
            process.stdout.close()
    if listing is None:
        raise ExecutionBlocked("plugin/list could not verify effective extensions")
    names = [
        p["name"]
        for market in listing.get("marketplaces", [])
        for p in market.get("plugins", [])
    ]
    if names != (["auto-research-agent"] if expected_plugin else []):
        raise ExecutionBlocked(f"condition plugin discovery differs: {names}")
    installed_sha = None
    if expected_plugin:
        market = listing["marketplaces"][0]
        plugin = market["plugins"][0]
        if plugin.get("installed") is not True or plugin.get("enabled") is not True:
            raise ExecutionBlocked("treatment plugin is discovered but not enabled")
        skills = detail.get("plugin", {}).get("skills", []) if detail else []
        if [skill.get("name") for skill in skills] != [
            "auto-research-agent:stage1-literature"
        ]:
            raise ExecutionBlocked("treatment Stage 1 skill did not load")
        cache = (
            Path(profile)
            / "plugins"
            / "cache"
            / market["name"]
            / plugin["name"]
            / plugin["localVersion"]
        )
        installed_sha = tree_sha(cache)
        if installed_sha != tree_sha(PLUGIN_ROOT):
            raise ExecutionBlocked(
                "installed treatment plugin bytes differ from source"
            )
        skill_path = cache / "skills" / "stage1-literature" / "SKILL.md"
    if models is None or capabilities is None:
        raise ExecutionBlocked(
            "model or native tool capabilities could not be verified"
        )
    model = next(
        (
            m
            for m in models.get("data", [])
            if m.get("model") == "gpt-5.6-sol" or m.get("id") == "gpt-5.6-sol"
        ),
        None,
    )
    if model is None or "high" not in {
        x.get("reasoningEffort") for x in model.get("supportedReasoningEfforts", [])
    }:
        raise ExecutionBlocked("gpt-5.6-sol High is unavailable in clean profile")
    if capabilities.get("webSearch") is not True or re.search(
        r"web_search\s*=\s*(?:false|\"disabled\")", config_text
    ):
        raise ExecutionBlocked("native web search is unavailable or disabled")
    if expected_plugin:
        if probe_evidence_dir is not None:
            Path(probe_evidence_dir).mkdir(parents=True, exist_ok=False)
        skill_sha = _functional_skill_smoke(codex, env, skill_path, probe_evidence_dir)
    else:
        skill_sha = None
    config_text = config.read_text(encoding="utf-8") if config.exists() else ""
    if re.search(r"\[mcp_servers\.|model_provider", config_text) or (
        not expected_plugin and re.search(r"\[plugins\.|marketplace", config_text)
    ):
        raise ExecutionBlocked(
            "condition profile config changed to unreviewed extension"
        )
    if capabilities.get("webSearch") is not True or re.search(
        r"web_search\s*=\s*(?:false|\"disabled\")", config_text
    ):
        raise ExecutionBlocked("native web search changed during profile probe")
    if expected_plugin and probe_evidence_dir is not None:
        (Path(probe_evidence_dir) / "capability-probe.json").write_text(
            json.dumps(
                {
                    "codex_version": version.stdout.strip(),
                    "model": model.get("model"),
                    "reasoning": "high",
                    "native_capabilities": capabilities,
                    "plugin_names": names,
                    "installed_plugin_sha256": installed_sha,
                    "config_sha256": sha(config_text.encode()),
                    "native_config_sha256": _native_config_sha(
                        config_text, _skill_probe_directory(profile)
                    ),
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
    return {
        "codex_version": version.stdout.strip(),
        "login_status": "authenticated",
        "plugin_names": names,
        "installed_plugin_sha256": installed_sha,
        "functional_skill_sha256": skill_sha,
        "model": model.get("model"),
        "reasoning": "high",
        "native_web_search": True,
        "native_capabilities": capabilities,
        "native_capabilities_sha256": sha(
            json.dumps(capabilities, sort_keys=True).encode()
        ),
        "config_sha256": sha(config_text.encode()),
        "native_config_sha256": _native_config_sha(
            config_text, _skill_probe_directory(profile)
        ),
    }


def _functional_skill_smoke(codex, env, skill_path, evidence_dir=None):
    """Ask the pinned subject model to read the installed skill in its real sandbox."""
    expected = sha(skill_path.read_bytes())
    if "CODEX_HOME" in env:
        directory = _skill_probe_directory(env["CODEX_HOME"])
        if directory.is_symlink() or (directory.exists() and not directory.is_dir()):
            raise ExecutionBlocked("skill probe workspace is not a normal directory")
        directory.mkdir(exist_ok=True)
        if any(directory.iterdir()):
            raise ExecutionBlocked("skill probe workspace is not empty")
        context = nullcontext(str(directory))
    else:
        context = tempfile.TemporaryDirectory(prefix="stage1-ab-skill-probe-")
    with context as directory:
        try:
            result = subprocess.run(
                [
                    str(codex),
                    "exec",
                    *SUBJECT_SANDBOX_ARGS,
                    "--json",
                    "--ephemeral",
                    "-m",
                    "gpt-5.6-sol",
                    "-c",
                    'model_reasoning_effort="high"',
                    "-C",
                    directory,
                    "--skip-git-repo-check",
                    "-",
                ],
                input=(
                    "Read this installed Stage 1 skill file using an actual file tool, "
                    "compute its SHA-256 from the file bytes, and reply with only the "
                    f"64-character digest or BLOCKED: {skill_path}"
                ).encode(),
                env=env,
                cwd=directory,
                capture_output=True,
                timeout=120,
            )
        except subprocess.TimeoutExpired as exc:
            raise ExecutionBlocked("treatment skill functional read timed out") from exc
    if evidence_dir is not None:
        evidence_dir = Path(evidence_dir)
        evidence_dir.mkdir(parents=True, exist_ok=True)
        (evidence_dir / "skill-read.jsonl").write_bytes(result.stdout)
        (evidence_dir / "skill-read.stderr").write_bytes(result.stderr)
        (evidence_dir / "expected-skill-sha256.txt").write_text(
            expected + "\n", encoding="utf-8"
        )
    if result.returncode:
        raise ExecutionBlocked("treatment skill functional read failed")
    try:
        events = [json.loads(line) for line in result.stdout.splitlines()]
        messages = [
            event["item"]["text"].strip()
            for event in events
            if event.get("type") == "item.completed"
            and event.get("item", {}).get("type") == "agent_message"
        ]
        tool_outputs = [
            json.dumps(event.get("item", {}), sort_keys=True).lower()
            for event in events
            if event.get("type") == "item.completed"
            and event.get("item", {}).get("type") == "command_execution"
        ]
    except (ValueError, KeyError, UnicodeDecodeError) as exc:
        raise ExecutionBlocked(
            "treatment skill read probe produced invalid events"
        ) from exc
    if (
        not messages
        or messages[-1] != expected
        or not any(expected in output for output in tool_outputs)
    ):
        raise ExecutionBlocked(
            "treatment skill is discovered but unreadable in the subject sandbox"
        )
    return expected


def host_preflight(
    codex,
    lock_path,
    baseline_profile,
    treatment_profile,
    baseline_workspace,
    treatment_workspace,
    private_root,
    dependency_repo,
    output,
    treatment_runtime_pin=None,
):
    lock = read_json(lock_path)
    if lock.get("kind") != "Stage1ABPublicLock":
        raise ExecutionBlocked("host preflight needs a frozen public lock")
    if lock.get("execution_policy") != SUBJECT_EXECUTION_POLICY:
        raise ExecutionBlocked(
            "subject sandbox/network policy differs from reviewed policy"
        )
    repeats = len(lock.get("paired_repeats", []))
    sequence.expected_runs(lock)
    if any(not _repeat_pin_sha(lock, repeat) for repeat in range(1, repeats + 1)):
        raise ExecutionBlocked("frozen lock lacks treatment runtime pin")
    if sequence.registry_path(lock_path).exists():
        raise ExecutionBlocked("this public lock already has a host execution series")
    if Path(baseline_profile).resolve() == Path(treatment_profile).resolve():
        raise ExecutionBlocked("B and T profiles must be separate")
    if Path(baseline_workspace).resolve() == Path(treatment_workspace).resolve():
        raise ExecutionBlocked("B and T workspaces must be separate")
    if any(
        Path(output).resolve().is_relative_to(Path(root).resolve())
        for root in (
            baseline_profile,
            treatment_profile,
            baseline_workspace,
            treatment_workspace,
        )
    ):
        raise ExecutionBlocked(
            "preflight and sequence registry must be outside subject environments"
        )
    pin_paths = _pin_paths(treatment_runtime_pin, repeats)
    repeat_bindings = {}
    all_paths = []
    reference_probe = None
    for repeat, pin_path in enumerate(pin_paths, 1):
        profiles = {
            condition: str(_repeat_subject_path(root, repeat, repeats))
            for condition, root in (
                ("baseline", baseline_profile),
                ("treatment", treatment_profile),
            )
        }
        workspaces = {
            condition: str(_repeat_subject_path(root, repeat, repeats))
            for condition, root in (
                ("baseline", baseline_workspace),
                ("treatment", treatment_workspace),
            )
        }
        paths = [
            Path(value).resolve()
            for value in (*profiles.values(), *workspaces.values())
        ]
        if any(
            left == right or left.is_relative_to(right) or right.is_relative_to(left)
            for left in paths
            for right in all_paths
        ) or any(
            left == right or left.is_relative_to(right) or right.is_relative_to(left)
            for index, left in enumerate(paths)
            for right in paths[index + 1 :]
        ):
            raise ExecutionBlocked(
                "all six subject profiles/workspaces must be separate"
            )
        all_paths.extend(paths)
        b = probe_profile(
            codex, profiles["baseline"], workspaces["baseline"], False, private_root
        )
        t = probe_profile(
            codex,
            profiles["treatment"],
            workspaces["treatment"],
            True,
            private_root,
            probe_evidence_dir=Path(output).with_suffix(f".repeat-{repeat:02d}.probe"),
        )
        for key in (
            "codex_version",
            "model",
            "reasoning",
            "native_web_search",
            "native_capabilities",
            "native_config_sha256",
        ):
            if b[key] != t[key] or (
                reference_probe is not None and b[key] != reference_probe[key]
            ):
                raise ExecutionBlocked(f"B/T or repeat runtime differs: {key}")
        if (
            b["codex_version"] != lock["runtime"]["app_version"]
            or t["model"] != lock["runtime"]["model_id"]
            or t["reasoning"] != lock["runtime"]["reasoning"]
            or b["native_capabilities_sha256"] != lock["runtime"]["tool_profile_sha256"]
        ):
            raise ExecutionBlocked("clean profiles do not match frozen runtime")
        reference_probe = b
        _, pin_sha = _runtime_pin(
            pin_path,
            _repeat_pin_sha(lock, repeat),
            verify_host=True,
            workspace=workspaces["treatment"],
        )
        repeat_bindings[str(repeat)] = {
            "profiles": profiles,
            "workspaces": workspaces,
            "probes": {"baseline": b, "treatment": t},
            "treatment_runtime_pin": {"path": str(pin_path), "sha256": pin_sha},
        }
    if tree_sha(PLUGIN_ROOT) != lock["plugin_tree_sha256"]:
        raise ExecutionBlocked("treatment plugin bytes differ from frozen lock")
    dependency = subprocess.run(
        ["git", "-C", str(dependency_repo), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        timeout=20,
    )
    if (
        dependency.returncode
        or dependency.stdout.strip() != lock["research_hub_sha"]
        or dependency.stdout.strip() != RESEARCH_HUB_SHA
    ):
        raise ExecutionBlocked(
            "subject host research-hub checkout differs from merged SHA"
        )
    report = {
        "kind": "Stage1ABHostPreflight",
        "valid": True,
        "lock_sha256": sha(Path(lock_path).read_bytes()),
        "repeat_bindings": repeat_bindings,
        "plugin_tree_sha256": tree_sha(PLUGIN_ROOT),
        "research_hub_sha": dependency.stdout.strip(),
        "execution_policy": SUBJECT_EXECUTION_POLICY,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    if repeats == 1:
        report.update(repeat_bindings["1"])
    sequence.expected_runs(lock)
    write_json(output, report)
    try:
        sequence.create(lock, lock_path, output, sha)
    except FileExistsError as exc:
        raise ExecutionBlocked(
            "this public lock already has a host execution series"
        ) from exc
    return report


def _event_summary(raw):
    try:
        events = [json.loads(line) for line in raw.splitlines()]
    except (ValueError, UnicodeDecodeError):
        return {"status": "failed", "thread_id": None, "usage": None}
    started = [e for e in events if e.get("type") == "thread.started"]
    completed = [e for e in events if e.get("type") == "turn.completed"]
    failed = [e for e in events if e.get("type") in {"turn.failed", "error"}]
    if len(started) != 1 or len(completed) + len(failed) != 1:
        return {
            "status": "incomplete",
            "thread_id": started[0].get("thread_id") if started else None,
            "usage": None,
        }
    rerouted = any(
        e.get("type") in {"model.rerouted", "model_rerouted", "modelRerouted"}
        for e in events
    )
    return {
        "status": "failed" if failed else "incomplete" if rerouted else "complete",
        "thread_id": started[0].get("thread_id"),
        "usage": completed[0].get("usage") if completed else None,
    }


def _completed_searches(raw):
    searches = []
    for line in raw.splitlines():
        event = json.loads(line)
        item = event.get("item", {})
        if event.get("type") == "item.completed" and item.get("type") in {
            "web_search",
            "mcp_tool_call",
        }:
            signature = {
                k: item.get(k)
                for k in ("type", "query", "queries", "server", "tool", "arguments")
            }
            searches.append(sha(json.dumps(signature, sort_keys=True).encode()))
    return searches


def capture(
    codex,
    lock_path,
    condition,
    repeat,
    profile,
    workspace,
    prompt_path,
    output,
    private_root,
    host_preflight_path,
    prohibited_ids=(),
    resume=False,
):
    """Advance exactly one frozen subject, with a durable reservation."""
    lock = read_json(lock_path)
    path = sequence.registry_path(lock_path)
    if not path.is_file():
        raise ExecutionBlocked(
            "sequence verification failed: frozen lock has no registry"
        )
    with sequence.exclusive(path):
        try:
            registry = sequence.verify(
                path, lock, lock_path, host_preflight_path, sha, verify_capture
            )
        except (OSError, KeyError, ValueError) as exc:
            raise ExecutionBlocked(f"sequence verification failed: {exc}") from exc
        index = registry["next_index"]
        if index == len(registry["runs"]):
            raise ExecutionBlocked("all frozen subjects already completed")
        wanted = registry["runs"][index]
        if (repeat, condition) != (wanted["repeat"], wanted["condition"]):
            raise ExecutionBlocked("subject is not next in frozen B/T sequence")
        active = registry["active"]
        if resume:
            if active != {
                "run_id": wanted["run_id"],
                "output": str(Path(output).resolve()),
            }:
                raise ExecutionBlocked(
                    "resume must target the active subject and original output"
                )
        elif active is not None:
            raise ExecutionBlocked("active subject requires inspected resume")
        if not resume and Path(output).exists():
            raise ExecutionBlocked("run output already exists")
        result = _capture_subject(
            codex,
            lock_path,
            condition,
            repeat,
            profile,
            workspace,
            prompt_path,
            output,
            private_root,
            host_preflight_path,
            prohibited_ids,
            resume,
            registry=registry,
            registry_path=path,
        )
        if result["status"] == "complete":
            verify_capture(output)
            registry["completed"].append(
                {
                    "run_id": wanted["run_id"],
                    "output": str(Path(output).resolve()),
                    "run_sha256": sha((Path(output) / "run.json").read_bytes()),
                }
            )
            registry["active"] = None
            registry["next_index"] += 1
            sequence.save(path, registry)
        return result


def _capture_subject(
    codex,
    lock_path,
    condition,
    repeat,
    profile,
    workspace,
    prompt_path,
    output,
    private_root,
    host_preflight_path,
    prohibited_ids=(),
    resume=False,
    registry=None,
    registry_path=None,
):
    """One attempt only. Recovery appends to the same run and never repeats a completed turn."""
    lock = read_json(lock_path)
    if lock.get("kind") != "Stage1ABPublicLock":
        raise ExecutionBlocked("missing public lock")
    preflight = read_json(host_preflight_path)
    if (
        preflight.get("kind") != "Stage1ABHostPreflight"
        or preflight.get("valid") is not True
        or preflight.get("lock_sha256") != sha(Path(lock_path).read_bytes())
        or preflight.get("execution_policy") != SUBJECT_EXECUTION_POLICY
        or lock.get("execution_policy") != SUBJECT_EXECUTION_POLICY
    ):
        raise ExecutionBlocked("missing or stale two-condition host preflight")
    binding = _preflight_binding(preflight, repeat)
    if binding["profiles"][condition] != str(Path(profile).resolve()) or binding[
        "workspaces"
    ][condition] != str(Path(workspace).resolve()):
        raise ExecutionBlocked(
            "subject profile or workspace differs from host preflight"
        )
    if (
        preflight.get("research_hub_sha") != lock.get("research_hub_sha")
        or lock.get("research_hub_sha") != RESEARCH_HUB_SHA
    ):
        raise ExecutionBlocked("host preflight dependency SHA differs from frozen lock")
    pin_binding = binding.get("treatment_runtime_pin", {})
    if pin_binding.get("sha256") != _repeat_pin_sha(lock, repeat):
        raise ExecutionBlocked("host preflight runtime pin differs from frozen lock")
    if lock["prompt_sha256"] != sha(Path(prompt_path).read_bytes()):
        raise ExecutionBlocked("subject prompt changed")
    row = lock["paired_repeats"][repeat - 1]
    if row["repeat"] != repeat or condition not in row["order"]:
        raise ExecutionBlocked("run order differs from frozen plan")
    run = row[condition]
    output = Path(output)
    all_bindings = preflight.get("repeat_bindings", {"1": preflight}).values()
    if any(
        output.resolve().is_relative_to(Path(root).resolve())
        for item in all_bindings
        for root in (*item["profiles"].values(), *item["workspaces"].values())
    ):
        raise ExecutionBlocked(
            "capture output must be outside both subject environments"
        )
    record_path = output / "run.json"
    if resume:
        record = read_json(record_path)
        if (
            record["run_id"] != run["run_id"]
            or record["condition"] != condition
            or record.get("series_id") != registry["series_id"]
            or record["status"] == "complete"
        ):
            raise ExecutionBlocked("untrusted recovery or completed run")
        verify_capture(output)
        thread_id = record["thread_id"]
        if not thread_id:
            raise ExecutionBlocked("recovery lacks trusted thread ID")
        previous_files = {
            "workspace/" + name.split("/", 2)[2]: digest
            for name, digest in record["attempts"][-1]["files"].items()
            if name.startswith("workspace/") and len(name.split("/", 2)) == 3
        }
        current_files = {
            "workspace/" + p.relative_to(workspace).as_posix(): sha(p.read_bytes())
            for p in Path(workspace).rglob("*")
            if p.is_file()
        }
        if current_files != previous_files:
            raise ExecutionBlocked("workspace changed before recovery")
    else:
        if output.exists():
            raise ExecutionBlocked("run output already exists")
        record = {
            "run_id": run["run_id"],
            "subject_id": run["subject_id"],
            "condition": condition,
            "repeat": repeat,
            "series_id": registry["series_id"],
            "execution_policy": SUBJECT_EXECUTION_POLICY,
            "status": "incomplete",
            "attempts": [],
        }
        thread_id = None
    _assert_host_isolation(profile, workspace, private_root, prohibited_ids, resume)
    probe = probe_profile(
        codex,
        profile,
        workspace,
        condition == "treatment",
        private_root,
        prohibited_ids,
        resume,
        probe_evidence_dir=(
            (
                Path(host_preflight_path).parent
                / f"capture-probe-{repeat}-{condition}-{len(record['attempts']) + 1}"
            )
            if condition == "treatment"
            else None
        ),
    )
    frozen_probe = binding["probes"][condition]
    for key in (
        "codex_version",
        "config_sha256",
        "native_config_sha256",
        "native_capabilities_sha256",
        "model",
        "reasoning",
        "native_web_search",
        "plugin_names",
        "installed_plugin_sha256",
        "functional_skill_sha256",
    ):
        if probe.get(key) != frozen_probe.get(key):
            raise ExecutionBlocked(f"subject profile changed after preflight: {key}")
    if probe["codex_version"] != lock["runtime"]["app_version"]:
        raise ExecutionBlocked("Codex version differs from frozen runtime")
    if lock["runtime"]["search_enabled"] is not True:
        raise ExecutionBlocked("frozen runtime does not enable search")
    if condition == "treatment" and tree_sha(PLUGIN_ROOT) != lock["plugin_tree_sha256"]:
        raise ExecutionBlocked("treatment plugin bytes differ from frozen lock")
    env = dict(os.environ, CODEX_HOME=str(Path(profile).resolve()))
    env.pop("STAGE1_RUNTIME_PIN", None)
    if condition == "treatment":
        _runtime_pin(
            pin_binding.get("path"),
            pin_binding["sha256"],
            verify_host=True,
            workspace=workspace,
        )
        env["STAGE1_RUNTIME_PIN"] = pin_binding["path"]
        record["treatment_runtime_pin_path"] = pin_binding["path"]
        env.update(_research_hub_workspace_env(Path(workspace), resume))
    # The same writable, isolated workspace is required in both conditions so
    # the treatment can persist its append-only Stage 1 ledger.
    command = [str(codex), "exec", *SUBJECT_SANDBOX_ARGS]
    if resume:
        command += [
            "resume",
            "--json",
            "-m",
            "gpt-5.6-sol",
            "-c",
            'model_reasoning_effort="high"',
            "--skip-git-repo-check",
            thread_id,
            "-",
        ]
    else:
        command += [
            "--json",
            "-m",
            "gpt-5.6-sol",
            "-c",
            'model_reasoning_effort="high"',
            "-C",
            str(workspace),
            "--skip-git-repo-check",
            "-",
        ]
    attempt_no = len(record["attempts"]) + 1
    if not resume:
        registry["active"] = {"run_id": run["run_id"], "output": str(output.resolve())}
        sequence.save(registry_path, registry)
    output.mkdir(parents=True, exist_ok=resume)
    final_path = output / f"attempt-{attempt_no:02d}.final.txt"
    command[-1:-1] = ["-o", str(final_path)]
    started = datetime.now(timezone.utc)
    result = subprocess.run(
        command,
        input=Path(prompt_path).read_bytes(),
        env=env,
        cwd=workspace,
        capture_output=True,
    )
    ended = datetime.now(timezone.utc)
    prefix = f"attempt-{attempt_no:02d}"
    files = {}
    for name, data in (
        (prefix + ".jsonl", result.stdout),
        (prefix + ".stderr", result.stderr),
    ):
        path = output / name
        path.write_bytes(data)
        files[name] = sha(data)
    if final_path.is_file():
        files[final_path.name] = sha(final_path.read_bytes())
    if condition == "treatment":
        pin_name = prefix + ".runtime-pin.json"
        pin_bytes = Path(pin_binding["path"]).read_bytes()
        if sha(pin_bytes) != pin_binding["sha256"]:
            raise ExecutionBlocked("treatment runtime pin changed during capture")
        (output / pin_name).write_bytes(pin_bytes)
        files[pin_name] = sha(pin_bytes)
    summary = _event_summary(result.stdout)
    if thread_id and summary["thread_id"] != thread_id:
        summary["status"] = "incomplete"
    record["thread_id"] = summary["thread_id"]
    record["status"] = summary["status"] if result.returncode == 0 else "failed"
    if not final_path.is_file() and record["status"] == "complete":
        record["status"] = "incomplete"
    record["profile_probe"] = probe
    record["attempts"].append(
        {
            "started_at": started.isoformat(),
            "ended_at": ended.isoformat(),
            "exit_code": result.returncode,
            "files": files,
            "summary": summary,
        }
    )
    if resume:
        earlier = {
            item
            for old in record["attempts"][:-1]
            for name in old["files"]
            if name.endswith(".jsonl")
            for item in _completed_searches((output / name).read_bytes())
        }
        if earlier.intersection(_completed_searches(result.stdout)):
            record["status"] = "incomplete"
    for p in Path(workspace).rglob("*"):
        if p.is_file():
            rel = p.relative_to(workspace).as_posix()
            snapshot = output / "workspace" / f"{attempt_no:02d}" / rel
            snapshot.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(p, snapshot)
            files["workspace/" + f"{attempt_no:02d}/" + rel] = sha(
                snapshot.read_bytes()
            )
    if any(
        token.encode() in result.stdout or token.encode() in result.stderr
        for token in prohibited_ids
    ):
        record["status"] = "incomplete"
    if condition == "treatment" and record["status"] == "complete":
        try:
            record["stage1_receipt"] = _treatment_receipt(
                output / "workspace" / f"{attempt_no:02d}",
                pin_binding,
                pin_bytes=(output / pin_name).read_bytes(),
            )
        except (ExecutionBlocked, OSError, ValueError) as error:
            record["status"] = "incomplete"
            record["stage1_receipt_error"] = str(error)
    record_path.write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return record


def _treatment_receipt(snapshot, pin_binding, *, pin_bytes, verify_runtime=True):
    """Require a current, strictly validated CLI ledger after the Codex turn."""
    manifests = list(Path(snapshot).rglob("run_manifest.json"))
    if len(manifests) != 1:
        raise ExecutionBlocked("treatment needs exactly one Stage 1 ledger")
    ledger_root = manifests[0].parent
    ledger, report, _events, checkpoint = source_state(
        ledger_root, verify_runtime=verify_runtime
    )
    if sha(pin_bytes) != pin_binding["sha256"]:
        raise ExecutionBlocked("saved runtime pin bytes differ from capture")
    pin = json.loads(pin_bytes)
    check_pin(pin)
    if pin.get("revision") != RESEARCH_HUB_SHA or pin.get("status") != "merged":
        raise ExecutionBlocked("saved runtime pin differs from merged research-hub")
    if verify_runtime:
        host_pin, _ = _runtime_pin(pin_binding["path"], pin_binding["sha256"])
        if host_pin != pin:
            raise ExecutionBlocked("saved runtime pin differs from host runtime")
    if (
        ledger.manifest.get("mode") != "research-hub-cli"
        or ledger.manifest.get("research_hub_pin") != pin
    ):
        raise ExecutionBlocked("Stage 1 ledger used a different CLI runtime pin")
    if report["counts"]["queries"] < 1 or report["counts"]["backend_attempts"] < 1:
        raise ExecutionBlocked("Stage 1 ledger has no completed backend retrieval")
    return {
        "workspace_path": ledger_root.relative_to(snapshot).as_posix(),
        "state_sha256": report["state_sha256"],
        "checkpoint_event_id": checkpoint["event_id"],
        "counts": report["counts"],
        "runtime_pin_sha256": pin_binding["sha256"],
    }


def _research_hub_workspace_env(workspace, resume):
    """Keep the pinned public CLI's data and config inside the subject workspace."""
    workspace = Path(workspace).resolve()
    local = workspace / ".research-hub-runtime"
    data = local / "data"
    config = local / "config.json"
    paths = {
        "root": str(data),
        "raw": str(data / "raw"),
        "hub": str(data / "hub"),
        "projects": str(data / "projects"),
        "logs": str(data / "logs"),
        "obsidian_graph": str(data / ".obsidian" / "graph.json"),
    }
    config_bytes = (
        json.dumps({"knowledge_base": paths, "no_zotero": True}, sort_keys=True) + "\n"
    ).encode()
    if resume:
        if (
            not config.is_file()
            or config.read_bytes() != config_bytes
            or not data.is_dir()
        ):
            raise ExecutionBlocked(
                "research-hub workspace config changed before recovery"
            )
    else:
        if local.exists():
            raise ExecutionBlocked("research-hub workspace config already exists")
        data.mkdir(parents=True)
        config.write_bytes(config_bytes)
    return {
        "RESEARCH_HUB_CONFIG": str(config),
        "RESEARCH_HUB_ROOT": str(data),
        "RESEARCH_HUB_ALLOW_EXTERNAL_ROOT": "1",
        "RESEARCH_HUB_NO_ZOTERO": "1",
    }


def verify_capture(output, *, verify_runtime=True):
    output = Path(output)
    record = read_json(output / "run.json")
    if record.get("execution_policy") != SUBJECT_EXECUTION_POLICY:
        raise ExecutionBlocked("captured subject sandbox/network policy differs")
    for attempt in record["attempts"]:
        for name, digest in attempt["files"].items():
            path = output / name
            if not path.is_file() or sha(path.read_bytes()) != digest:
                raise ExecutionBlocked(f"capture byte hash differs: {name}")
        raw = (
            output / next(name for name in attempt["files"] if name.endswith(".jsonl"))
        ).read_bytes()
        if _event_summary(raw) != attempt["summary"]:
            raise ExecutionBlocked("captured events differ from recorded summary")
    if record["condition"] == "treatment" and record["status"] == "complete":
        receipt = record.get("stage1_receipt")
        if not receipt:
            raise ExecutionBlocked("completed treatment lacks Stage 1 ledger receipt")
        pin_binding = {
            "path": record["treatment_runtime_pin_path"],
            "sha256": receipt["runtime_pin_sha256"],
        }
        pin_name = f"attempt-{len(record['attempts']):02d}.runtime-pin.json"
        if pin_name not in record["attempts"][-1]["files"]:
            raise ExecutionBlocked("completed treatment lacks saved runtime pin")
        snapshot = output / "workspace" / f"{len(record['attempts']):02d}"
        if (
            _treatment_receipt(
                snapshot,
                pin_binding,
                pin_bytes=(output / pin_name).read_bytes(),
                verify_runtime=verify_runtime,
            )
            != receipt
        ):
            raise ExecutionBlocked("captured Stage 1 receipt differs from replay")
    return record
