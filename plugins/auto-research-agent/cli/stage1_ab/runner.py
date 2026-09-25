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
from datetime import datetime, timezone

PLUGIN_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = PLUGIN_ROOT.parents[1]
sys.path.insert(0, str(PLUGIN_ROOT))

from validators.evaluation_plan import validate_plan  # noqa: E402
from validators.holdout_manifest import canonical_sha256  # noqa: E402
from . import sequence  # noqa: E402

PROMPT_SHA256 = "9a73fa53b1e660d5a800aa433db617858f24c7c031fe52b302a404fddb769dfd"
RESEARCH_HUB_SHA = "9877f929587e7e44bc2533db118cbb89336bf94f"
FORMAL_CASE = "aging-sk-bidirectional-development-v2"


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


def freeze(plan_path, prompt_path, dependency_repo, output):
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
    lock = {
        "kind": "Stage1ABPublicLock",
        "schema_version": "1.0.0",
        "plan_sha256": canonical_sha256(plan),
        "holdout_sha256": canonical_sha256(holdout),
        "prompt_sha256": PROMPT_SHA256,
        "readiness_sha256": plan["bindings"]["stage1_readiness"]["sha256"],
        "research_hub_sha": RESEARCH_HUB_SHA,
        "plugin_tree_sha256": tree_sha(PLUGIN_ROOT),
        "case_id": FORMAL_CASE,
        "runtime": runtime,
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
                    },
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
        skill_sha = _functional_skill_smoke(codex, env, skill_path, probe_evidence_dir)
    else:
        skill_sha = None
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
    }


def _functional_skill_smoke(codex, env, skill_path, evidence_dir=None):
    """Ask the pinned subject model to read the installed skill in its real sandbox."""
    expected = sha(skill_path.read_bytes())
    with tempfile.TemporaryDirectory(prefix="stage1-ab-skill-probe-") as directory:
        try:
            result = subprocess.run(
                [
                    str(codex),
                    "exec",
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
):
    lock = read_json(lock_path)
    if lock.get("kind") != "Stage1ABPublicLock":
        raise ExecutionBlocked("host preflight needs a frozen public lock")
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
    b = probe_profile(codex, baseline_profile, baseline_workspace, False, private_root)
    t = probe_profile(
        codex,
        treatment_profile,
        treatment_workspace,
        True,
        private_root,
        probe_evidence_dir=Path(output).with_suffix(".probe"),
    )
    for key in (
        "codex_version",
        "model",
        "reasoning",
        "native_web_search",
        "native_capabilities",
    ):
        if b[key] != t[key]:
            raise ExecutionBlocked(f"B/T runtime differs: {key}")
    if (
        b["codex_version"] != lock["runtime"]["app_version"]
        or t["model"] != lock["runtime"]["model_id"]
        or t["reasoning"] != lock["runtime"]["reasoning"]
    ):
        raise ExecutionBlocked("clean profiles do not match frozen runtime")
    if b["native_capabilities_sha256"] != lock["runtime"]["tool_profile_sha256"]:
        raise ExecutionBlocked("native tool profile differs from frozen plan")
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
        "profiles": {
            "baseline": str(Path(baseline_profile).resolve()),
            "treatment": str(Path(treatment_profile).resolve()),
        },
        "workspaces": {
            "baseline": str(Path(baseline_workspace).resolve()),
            "treatment": str(Path(treatment_workspace).resolve()),
        },
        "probes": {"baseline": b, "treatment": t},
        "plugin_tree_sha256": tree_sha(PLUGIN_ROOT),
        "research_hub_sha": dependency.stdout.strip(),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
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
    ):
        raise ExecutionBlocked("missing or stale two-condition host preflight")
    if preflight["profiles"][condition] != str(Path(profile).resolve()) or preflight[
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
    if lock["prompt_sha256"] != sha(Path(prompt_path).read_bytes()):
        raise ExecutionBlocked("subject prompt changed")
    row = lock["paired_repeats"][repeat - 1]
    if row["repeat"] != repeat or condition not in row["order"]:
        raise ExecutionBlocked("run order differs from frozen plan")
    run = row[condition]
    output = Path(output)
    if any(
        output.resolve().is_relative_to(Path(root).resolve())
        for root in (*preflight["profiles"].values(), *preflight["workspaces"].values())
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
    if probe["codex_version"] != lock["runtime"]["app_version"]:
        raise ExecutionBlocked("Codex version differs from frozen runtime")
    if lock["runtime"]["search_enabled"] is not True:
        raise ExecutionBlocked("frozen runtime does not enable search")
    if condition == "treatment" and tree_sha(PLUGIN_ROOT) != lock["plugin_tree_sha256"]:
        raise ExecutionBlocked("treatment plugin bytes differ from frozen lock")
    env = dict(os.environ, CODEX_HOME=str(Path(profile).resolve()))
    command = [str(codex), "exec"]
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
    record_path.write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return record


def verify_capture(output):
    output = Path(output)
    record = read_json(output / "run.json")
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
    return record
