"""Hash-approved, single-owner output scheduling with preserved failure history."""

import hashlib
import json
import os
import re
import subprocess
import sys
import threading
import tomllib
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime, timezone
from pathlib import Path


class SchedulerError(ValueError):
    """Admission or evidence did not meet the approved execution amendment."""


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_bytes())


def require(condition, message):
    if not condition:
        raise SchedulerError(message)


def save(path, value):
    with Path(path).open("xb") as stream:
        stream.write(canonical(value))
        stream.flush()
        os.fsync(stream.fileno())


def utc():
    return datetime.now(timezone.utc).isoformat()


def inventory(root):
    root = Path(root)
    result = {}
    for p in sorted(root.rglob("*")):
        require(
            not p.is_symlink() and p.resolve().is_relative_to(root.resolve()),
            "unsafe artifact path",
        )
        if p.is_file():
            result[p.relative_to(root).as_posix()] = digest(p)
    return result


def safe_absolute(value):
    path = Path(value)
    require(path.is_absolute(), "path must be absolute")
    require(not any(p.is_symlink() for p in (path, *path.parents)), "symlink in path")
    return path.resolve()


def live_commands(plan, job):
    """Construct the only accepted real worker commands from bound inputs."""
    runtime = plan["runtime"]
    args = [
        "evaluate",
        job["inputs"]["task"],
        job["inputs"]["spec"],
        job["inputs"]["subject"],
        job["output"],
        "--evaluator-version",
        "3.1",
        "--execution-class",
        "repair-diagnostic",
        "--portable-diagnostic",
        "--lock",
        job["inputs"]["lock"],
        "--capture",
        job["capture_root"],
        "--mode",
        "evidence-audited",
        "--background",
        job["inputs"]["background"],
        "--background-sha256",
        digest(job["inputs"]["background"]),
        "--hub-command-json",
        '["@python","-m","research_hub"]',
        "--codex",
        runtime["codex_executable"],
        "--evaluator-home",
        job["profile"],
        "--model",
        "gpt-5.6-sol",
        "--reasoning",
        "high",
    ]
    evaluate = [
        runtime["python_executable"],
        "-P",
        "-X",
        "utf8",
        "-m",
        "stage1_eval",
        *args,
    ]
    if job["id"] == plan["legacy"]["fenced_target"]:
        evaluate.append("--resume-verified")
    replay = [
        runtime["python_executable"],
        "-P",
        "-X",
        "utf8",
        runtime["replay_guard"],
        *args,
        "--resume-verified",
        "--replay-only",
    ]
    return evaluate, replay


def validate_live(plan):
    runtime = plan["runtime"]
    require(
        safe_absolute(runtime["python_executable"]) == Path(sys.executable).resolve(),
        "child interpreter differs",
    )
    require(
        safe_absolute(runtime["cli_root"]) == Path(__file__).resolve().parents[1],
        "child import root differs",
    )
    require(
        safe_absolute(runtime["replay_guard"])
        == Path(__file__).with_name("offline_replay.py").resolve(),
        "replay guard implementation differs",
    )
    bound = {safe_absolute(b["path"]) for b in plan["bindings"]}
    require(
        {safe_absolute(p) for p in Path(__file__).parent.glob("*.py")}.issubset(bound),
        "operator module binding incomplete",
    )
    for p in (
        runtime["python_executable"],
        runtime["codex_executable"],
        runtime["replay_guard"],
    ):
        require(safe_absolute(p) in bound, "missing runtime binding")
    for job in plan["jobs"]:
        require(
            (job["evaluate"], job["replay"]) == live_commands(plan, job),
            "real worker argv differs from fixed contract",
        )
        require(
            job["env"]
            == {
                "PYTHONPATH": runtime["cli_root"],
                "RESEARCH_HUB_CONFIG": job["hub_config"],
                "RESEARCH_HUB_ALLOW_EXTERNAL_ROOT": "1",
            },
            "child environment differs",
        )
        for p in [
            *job["inputs"].values(),
            job["hub_config"],
            str(Path(job["profile"]) / "config.toml"),
        ]:
            require(safe_absolute(p) in bound, "unbound job input/config")
        cfg = read(job["hub_config"])
        require(
            safe_absolute(cfg["knowledge_base"]["root"]) == safe_absolute(job["cache"])
            and cfg["no_zotero"] is True
            and cfg["disable_pdf_fallback"] is True,
            "source configuration differs",
        )
        profile = tomllib.loads(
            (Path(job["profile"]) / "config.toml").read_text(encoding="utf-8")
        )
        require(
            profile
            == {
                "model": "gpt-5.6-sol",
                "model_reasoning_effort": "high",
                "approval_policy": "never",
                "cli_auth_credentials_store": "file",
            },
            "profile config differs",
        )
        require(
            safe_absolute(job["output"])
            == (
                safe_absolute(plan["legacy"]["generation"]) / "evaluations" / job["id"]
            ),
            "successor moved original output",
        )
        require(
            safe_absolute(job["inputs"]["subject"]).is_relative_to(
                safe_absolute(job["capture_root"])
            ),
            "subject outside capture",
        )


def validate_amendment(plan, expected_sha256):
    require(
        re.fullmatch(r"[0-9a-f]{64}", expected_sha256 or ""), "invalid amendment digest"
    )
    require(plan["kind"] == "Stage1OutputSchedule.v1", "unsupported scheduler version")
    require(
        plan["evidence_scope"] in {"synthetic-test", "repair-diagnostic"},
        "invalid scope",
    )
    require(
        type(plan["max_jobs"]) is int and 1 <= plan["max_jobs"] <= 2,
        "output ceiling must be 1 or 2",
    )
    require(plan["executor_sha256"] == digest(__file__), "executor bytes changed")
    require(
        plan["jobs"] and isinstance(plan["bindings"], list), "missing jobs/bindings"
    )
    seen, paths = set(), [safe_absolute(plan["control_root"])]
    for job in plan["jobs"]:
        require(
            re.fullmatch(r"[a-zA-Z0-9_-]+", job["id"]) and job["id"] not in seen,
            "duplicate/unsafe job id",
        )
        seen.add(job["id"])
        for key in ("output", "profile", "cache", "temp"):
            resolved = safe_absolute(job[key])
            require(
                all(
                    not (
                        resolved == q
                        or resolved.is_relative_to(q)
                        or q.is_relative_to(resolved)
                    )
                    for q in paths
                ),
                "writable paths overlap",
            )
            paths.append(resolved)
        require(Path(job["cwd"]).is_absolute(), "cwd must be absolute")
        require(
            Path(job["capture_root"]).is_dir() and job["capture_manifest"],
            "missing capture inventory",
        )
        require(
            not any(
                Path(job["capture_root"]).resolve().is_relative_to(q)
                or q.is_relative_to(Path(job["capture_root"]).resolve())
                for q in paths
            ),
            "capture overlaps writable paths",
        )
        require(
            not Path(job["result"]).is_absolute()
            and ".." not in Path(job["result"]).parts,
            "unsafe result path",
        )
        for phase in ("evaluate", "replay"):
            cmd = job[phase]
            require(
                isinstance(cmd, list)
                and cmd
                and all(isinstance(x, str) and x for x in cmd),
                "invalid command",
            )
            require(Path(cmd[0]).is_absolute(), "executable must be absolute")
            require(
                any(
                    Path(b["path"]).resolve() == Path(cmd[0]).resolve()
                    for b in plan["bindings"]
                ),
                "unbound executable",
            )
        if plan["evidence_scope"] != "synthetic-test":
            require(
                "stage1_eval" in job["evaluate"] and "evaluate" in job["evaluate"],
                "not an evaluator command",
            )
            require(
                "--replay-only" in job["replay"]
                and "--resume-verified" in job["replay"],
                "unguarded replay",
            )
    require(
        plan["legacy"] is not None or plan["evidence_scope"] == "synthetic-test",
        "live schedule needs legacy handoff",
    )
    for path in paths:
        require(
            not any((p / ".git").exists() for p in (path, *path.parents)),
            "writable path is in Git checkout",
        )
    for job in plan["jobs"]:
        capture = safe_absolute(job["capture_root"])
        require(
            not any(
                capture.is_relative_to(p) or p.is_relative_to(capture) for p in paths
            ),
            "capture overlaps writable paths",
        )
    if plan["evidence_scope"] != "synthetic-test":
        validate_live(plan)


def verify_bindings(plan):
    for binding in plan["bindings"]:
        require(
            digest(binding["path"]) == binding["sha256"],
            "runtime/dependency binding changed",
        )
    if plan["evidence_scope"] != "synthetic-test":
        from stage1_eval.pipeline_v31 import bundle_sha_v31, execution_policy
        from stage1_eval.runtime import installed_package_sha256

        runtime = plan["runtime"]
        require(
            bundle_sha_v31() == runtime["evaluator_bundle_sha256"],
            "evaluator bundle changed",
        )
        require(
            execution_policy() == runtime["execution_policy"],
            "evaluator policy changed",
        )
        require(
            installed_package_sha256("research_hub")
            == runtime["research_hub_package_sha256"],
            "dependency changed",
        )
        legacy_root = Path(plan["legacy"]["generation"])
        require(
            digest(legacy_root / "plan.json") == plan["legacy"]["plan_sha256"],
            "old plan changed",
        )
        original = read(legacy_root / "plan.json")
        for key in (
            "evaluator_bundle_sha256",
            "execution_policy",
            "research_hub_package_sha256",
        ):
            require(
                runtime[key] == original[key],
                "successor changed frozen evaluator contract",
            )
        require(
            digest(runtime["codex_executable"]) == original["codex_executable_sha256"]
            and digest(runtime["python_executable"])
            == original["python_executable_sha256"],
            "original executable pin changed",
        )
        require(
            digest(legacy_root / "capture-inventory.json")
            == original["capture_inventory_sha256"],
            "original capture inventory changed",
        )
        captures = read(legacy_root / "capture-inventory.json")
        for job in plan["jobs"]:
            require(
                job["capture_manifest"] == captures[job["id"]],
                "saved target/capture identity changed",
            )


def load_approved(path, expected, approval):
    require(approval == expected, "external approval must name exact amendment digest")
    raw = Path(path).read_bytes()
    require(hashlib.sha256(raw).hexdigest() == expected, "amendment bytes changed")
    plan = json.loads(raw)
    validate_amendment(plan, expected)
    verify_bindings(plan)
    return plan


def process_snapshot():
    """Read actual Windows process identities; unknown platforms fail closed."""
    require(os.name == "nt", "live handoff requires Windows process inspection")
    script = "Get-CimInstance Win32_Process | ForEach-Object { [pscustomobject]@{pid=$_.ProcessId;parent_pid=$_.ParentProcessId;created_utc=$_.CreationDate.ToUniversalTime().ToString('o');executable=$_.ExecutablePath;command_line=$_.CommandLine} } | ConvertTo-Json -Compress"
    raw = subprocess.check_output(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script]
    )
    value = json.loads(raw)
    require(isinstance(value, list) and value, "missing process snapshot")
    return value


def fence_value(plan, amendment_sha):
    return {
        "kind": "Stage1OwnershipFence.v1",
        "amendment_sha256": amendment_sha,
        "legacy": plan["legacy"],
    }


def fence_path(plan):
    return (
        Path(plan["legacy"]["generation"])
        / "evaluations"
        / plan["legacy"]["fenced_target"]
    )


def reservation_path(plan):
    legacy = plan["legacy"]
    return Path(legacy["generation"]) / (
        "fence-reservation-" + legacy["fenced_target"] + ".json"
    )


def legacy_identities(plan):
    legacy = plan["legacy"]
    identities = legacy["processes"]
    require(
        identities and len({p["pid"] for p in identities}) == len(identities),
        "missing/duplicate legacy identities",
    )
    require(
        legacy["runner_pid"] in {p["pid"] for p in identities},
        "runner identity missing",
    )
    for p in identities:
        require(
            type(p["pid"]) is int
            and p["pid"] > 0
            and type(p["parent_pid"]) is int
            and p.get("created_utc")
            and Path(p["executable"]).is_absolute(),
            "incomplete process identity",
        )
        datetime.fromisoformat(p["created_utc"].replace("Z", "+00:00"))
    if plan["evidence_scope"] != "synthetic-test":
        by_pid = {p["pid"]: p for p in identities}
        runner = by_pid[legacy["runner_pid"]]
        require(runner["parent_pid"] in by_pid, "runner parent identity missing")
        require(
            any(p["parent_pid"] == runner["pid"] for p in identities),
            "active evaluator identity missing",
        )
        require(
            legacy["runner_script"].replace("\\", "/").lower()
            in runner["command_line"].replace("\\", "/").lower(),
            "runner command identity differs",
        )
        require(
            legacy["expected_stderr"]
            in (
                "stage1-eval: EvaluationError: v3.1 output exists; verified resume must be explicit\n",
                "stage1-eval: EvaluationError: v3.1 output exists; verified resume must be explicit\r\n",
            ),
            "invalid expected guard stderr",
        )
    return identities


def descendants(snapshot, roots):
    found = set(roots)
    while True:
        expanded = found | {p["pid"] for p in snapshot if p["parent_pid"] in found}
        if expanded == found:
            return [p for p in snapshot if p["pid"] in found]
        found = expanded


def reserve_fence(
    amendment_path, expected_sha256, *, approval_sha256, process_inspector=None
):
    plan = load_approved(amendment_path, expected_sha256, approval_sha256)
    legacy = plan["legacy"]
    require(legacy is not None, "reservation requires legacy identity")
    identities = legacy_identities(plan)
    current = (process_inspector or process_snapshot)()
    require(all(p in current for p in identities), "legacy process identity changed")
    root = Path(legacy["generation"])
    require(
        not (root / "batch-stop.json").exists()
        and not (root / "batch-complete.json").exists(),
        "legacy already terminal",
    )
    start = read(root / "batch-start.json")
    require(
        start["pid"] == legacy["runner_pid"]
        and start["plan_sha256"] == legacy["plan_sha256"],
        "legacy batch identity mismatch",
    )
    old = read(root / "plan.json")
    require(digest(root / "plan.json") == legacy["plan_sha256"], "legacy plan changed")
    i = old["targets"].index(legacy["active_target"])
    require(
        old["targets"][i + 1] == legacy["fenced_target"], "fence is not next target"
    )
    require(
        (root / "logs" / (legacy["active_target"] + "-evaluate-start.json")).is_file(),
        "active evaluation missing",
    )
    require(
        not (root / "logs" / (legacy["active_target"] + "-evaluate.json")).exists(),
        "active evaluation advanced; refresh amendment",
    )
    require(
        not (
            root / "logs" / (legacy["fenced_target"] + "-evaluate-start.json")
        ).exists(),
        "pending target already admitted",
    )
    require(
        digest(legacy["runner_script"])
        == legacy["runner_sha256"]
        == old["operator_script_sha256"],
        "original runner binding differs",
    )
    observed = descendants(current, {p["pid"] for p in identities})
    if plan["evidence_scope"] != "synthetic-test":
        active = legacy["active_target"] + "-evaluate"
        require(
            read(root / "logs" / (active + "-start.json"))["command"]
            == legacy["expected_commands"][active],
            "active command changed before reservation",
        )
    destination = fence_path(plan)
    destination.mkdir(exist_ok=False)
    marker = destination / "ownership-fence.json"
    save(marker, fence_value(plan, expected_sha256))
    save(
        reservation_path(plan),
        {
            "kind": "Stage1FenceObservation.v1",
            "amendment_sha256": expected_sha256,
            "at": utc(),
            "processes": observed,
            "batch_start_sha256": digest(root / "batch-start.json"),
            "active_start_sha256": digest(
                root / "logs" / (legacy["active_target"] + "-evaluate-start.json")
            ),
            "marker_sha256": digest(marker),
        },
    )
    # A racing original admission must never be silently accepted as a fence.
    require(
        not (
            root / "logs" / (legacy["fenced_target"] + "-evaluate-start.json")
        ).exists(),
        "reservation raced old admission; preserve and review",
    )
    return {
        "fence": str(marker),
        "sha256": digest(marker),
        "execution_authorized": False,
    }


def verify_handoff(plan, amendment_sha, process_inspector=None):
    legacy = plan["legacy"]
    if legacy is None:
        require(plan["evidence_scope"] == "synthetic-test", "missing live handoff")
        return {}
    root, target = Path(legacy["generation"]), legacy["fenced_target"]
    legacy_identities(plan)
    require(digest(root / "plan.json") == legacy["plan_sha256"], "legacy plan changed")
    require(
        digest(legacy["runner_script"]) == legacy["runner_sha256"],
        "legacy runner changed",
    )
    require(
        read(root / "plan.json")["operator_script_sha256"] == legacy["runner_sha256"],
        "runner not bound to legacy plan",
    )
    marker = fence_path(plan) / "ownership-fence.json"
    require(
        marker.read_bytes() == canonical(fence_value(plan, amendment_sha)),
        "reservation bytes changed",
    )
    require(
        set(p.name for p in fence_path(plan).iterdir()) == {marker.name},
        "reservation is not marker-only",
    )
    observation = read(reservation_path(plan))
    require(
        observation["amendment_sha256"] == amendment_sha
        and observation["marker_sha256"] == digest(marker)
        and observation["batch_start_sha256"] == digest(root / "batch-start.json")
        and observation["active_start_sha256"]
        == digest(root / "logs" / (legacy["active_target"] + "-evaluate-start.json"))
        and all(p in observation["processes"] for p in legacy["processes"]),
        "reservation observation differs",
    )
    expected_pids = {p["pid"] for p in observation["processes"]}
    processes = (process_inspector or process_snapshot)()
    require(
        not any(
            p["pid"] in expected_pids or p["parent_pid"] in expected_pids
            for p in processes
        ),
        "legacy coordinator/descendants still alive",
    )
    if plan["evidence_scope"] != "synthetic-test":
        for p in processes:
            command = (p.get("command_line") or "").replace("\\", "/").lower()
            require(
                str(root).replace("\\", "/").lower() not in command,
                "generation still has live process",
            )
        for key, command in legacy["expected_commands"].items():
            require(
                read(root / "logs" / (key + "-start.json"))["command"] == command,
                "legacy command provenance differs",
            )
        require(
            set(legacy["expected_commands"])
            == {
                legacy["active_target"] + "-evaluate",
                legacy["active_target"] + "-replay",
                target + "-evaluate",
            },
            "missing command provenance",
        )
    start = read(root / "batch-start.json")
    require(
        start["pid"] == legacy["runner_pid"]
        and start["plan_sha256"] == legacy["plan_sha256"],
        "legacy batch identity mismatch",
    )
    for phase in ("evaluate", "replay"):
        rec = read(root / "logs" / f"{legacy['active_target']}-{phase}.json")
        require(
            rec["target"] == legacy["active_target"]
            and rec["phase"] == phase
            and rec["exit_code"] == 0
            and rec["capture_all_files_unchanged"] is True,
            "prior output failed or unverified",
        )
        if phase == "replay":
            require(
                rec["replay_archive_unchanged"] is True, "prior replay changed archive"
            )
            if plan["evidence_scope"] != "synthetic-test":
                guard = json.loads(
                    (root / "logs" / f"{legacy['active_target']}-replay.stdout.txt")
                    .read_bytes()
                    .splitlines()[-1]
                )
                require(
                    guard
                    == {
                        "offline_guard": True,
                        "blocked_actions": [],
                        "new_model_calls": 0,
                        "exit_code": 0,
                    },
                    "prior replay lacks zero-call guard receipt",
                )
    rec = read(root / "logs" / f"{target}-evaluate.json")
    require(
        rec["target"] == target
        and rec["phase"] == "evaluate"
        and rec["exit_code"] == 2
        and rec["capture_all_files_unchanged"] is True,
        "not the expected fence rejection",
    )
    stderr = root / "logs" / f"{target}-evaluate.stderr.txt"
    expected_stderr = legacy.get(
        "expected_stderr",
        "stage1-eval: EvaluationError: v3.1 output exists; verified resume must be explicit\n",
    ).encode()
    require(stderr.read_bytes() == expected_stderr, "unexpected fence stderr")
    stop = read(root / "batch-stop.json")
    old = read(root / "plan.json")
    index = old["targets"].index(target)
    require(
        stop["status"] == "failed-preserved"
        and stop["target"] == target
        and stop["phase"] == "evaluate"
        and stop["completed"] == old["targets"][:index],
        "legacy stop does not prove handoff",
    )
    require(
        [j["id"] for j in plan["jobs"]] == old["targets"][index:],
        "successor jobs differ from remaining legacy order",
    )
    return {
        "legacy_stop_sha256": digest(root / "batch-stop.json"),
        "prior_completed": stop["completed"],
        "intentional_orchestration_failure": True,
    }


def check_capture(job):
    require(
        inventory(job["capture_root"]) == job["capture_manifest"],
        "capture bytes changed",
    )


def run(amendment_path, expected_sha256, *, approval_sha256, process_inspector=None):
    plan = load_approved(amendment_path, expected_sha256, approval_sha256)
    handoff = verify_handoff(plan, expected_sha256, process_inspector)
    control = Path(plan["control_root"])
    control.mkdir(exist_ok=False)  # permanent exclusive ownership; never auto-reclaimed
    save(
        control / "owner.json",
        {
            "pid": os.getpid(),
            "started_at": utc(),
            "amendment_sha256": expected_sha256,
            "handoff": handoff,
        },
    )
    lock, admission_closed, results = threading.Lock(), threading.Event(), {}

    def close_admission():
        with lock:
            admission_closed.set()

    def execute(job):
        directory = control / job["id"]
        outcome = {"id": job["id"], "status": "failed", "phases": []}
        try:
            verify_bindings(plan)
            check_capture(job)
            out = Path(job["output"])
            is_fenced = plan["legacy"] and job["id"] == plan["legacy"]["fenced_target"]
            if is_fenced:
                require(
                    out.resolve() == fence_path(plan).resolve(),
                    "fenced output path mismatch",
                )
                require(
                    inventory(out)
                    == {
                        "ownership-fence.json": hashlib.sha256(
                            canonical(fence_value(plan, expected_sha256))
                        ).hexdigest()
                    },
                    "fence changed before admission",
                )
                require(
                    "--resume-verified" in job["evaluate"],
                    "reserved output needs explicit verified admission",
                )
            else:
                require(
                    not out.exists(), "output already exists; no automatic recovery"
                )
            for key in ("profile", "cache", "temp"):
                require(
                    Path(job[key]).is_dir(),
                    "prepare isolated job environment before launch",
                )
            if plan["evidence_scope"] != "synthetic-test":
                require(
                    not any(Path(job["cache"]).iterdir())
                    and not any(Path(job["temp"]).iterdir()),
                    "never-started cache/temp is not empty",
                )
            env = {
                k: v
                for k, v in os.environ.items()
                if not k.startswith(("RESEARCH_HUB_", "ZOTERO_", "CODEX_", "PYTHON"))
            }
            if (
                plan["evidence_scope"] == "synthetic-test"
                and "PYTHONPATH" in os.environ
            ):
                env["PYTHONPATH"] = os.environ["PYTHONPATH"]
            env.update(job["env"])
            env.update(
                TEMP=job["temp"],
                TMP=job["temp"],
                TMPDIR=job["temp"],
                CODEX_HOME=job["profile"],
                RESEARCH_HUB_ROOT=job["cache"],
            )
            for phase in ("evaluate", "replay"):
                verify_bindings(plan)
                before = inventory(out) if phase == "replay" else None
                started = utc()
                save(
                    directory / f"{phase}-start.json",
                    {
                        "at": started,
                        "argv": job[phase],
                        "amendment_sha256": expected_sha256,
                    },
                )
                with (
                    (directory / f"{phase}.stdout").open("xb") as stdout,
                    (directory / f"{phase}.stderr").open("xb") as stderr,
                ):
                    proc = subprocess.Popen(
                        job[phase],
                        cwd=job["cwd"],
                        env=env,
                        stdout=stdout,
                        stderr=stderr,
                    )
                    try:
                        save(
                            directory / f"{phase}-process.json",
                            {"pid": proc.pid, "started_at": started},
                        )
                    except Exception:
                        # A known bookkeeping failure must stop new work before drain.
                        close_admission()
                        raise
                    finally:
                        try:
                            # Retain ownership even when process-receipt persistence fails.
                            code = proc.wait()
                        except Exception:
                            close_admission()
                            raise
                        if code != 0:
                            # Publish failure before closing streams or saving receipts.
                            close_admission()
                receipt = {
                    "phase": phase,
                    "exit_code": code,
                    "started_at": started,
                    "ended_at": utc(),
                }
                outcome["phases"].append(receipt)
                save(directory / f"{phase}-exit.json", receipt)
                require(code == 0, f"{phase} process failed")
                check_capture(job)
                if phase == "replay":
                    require(
                        before == inventory(out), "replay changed evaluator archive"
                    )
                    if plan["evidence_scope"] != "synthetic-test":
                        guard = json.loads(
                            (directory / "replay.stdout").read_bytes().splitlines()[-1]
                        )
                        require(
                            guard
                            == {
                                "offline_guard": True,
                                "blocked_actions": [],
                                "new_model_calls": 0,
                                "exit_code": 0,
                            },
                            "missing zero-call replay receipt",
                        )
                else:
                    require(
                        (out / job["result"]).is_file(), "missing evaluation result"
                    )
            outcome.update(
                status="complete",
                result_sha256=digest(out / job["result"]),
                replay_archive_unchanged=True,
            )
        except Exception as exc:
            close_admission()
            outcome["error"] = f"{type(exc).__name__}: {exc}"
        with lock:
            if outcome["status"] != "complete":
                admission_closed.set()
            save(directory / "terminal.json", outcome)
        return outcome

    pending = iter(plan["jobs"])
    futures = {}
    coordinator_error = None
    with ThreadPoolExecutor(max_workers=plan["max_jobs"]) as pool:
        while True:
            with lock:
                while not admission_closed.is_set() and len(futures) < plan["max_jobs"]:
                    job = next(pending, None)
                    if job is None:
                        break
                    try:
                        verify_bindings(plan)
                        directory = control / job["id"]
                        directory.mkdir(exist_ok=False)
                        output = Path(job["output"])
                        # The canonical sibling claim also excludes coordinators using another control root.
                        claim = output.parent / ("." + output.name + ".scheduler-claim")
                        claim.mkdir(exist_ok=False)
                        ownership = {
                            "id": job["id"],
                            "output": job["output"],
                            "amendment_sha256": expected_sha256,
                            "admitted_at": utc(),
                        }
                        save(claim / "owner.json", ownership)
                        save(directory / "claim.json", ownership)
                        futures[pool.submit(execute, job)] = job["id"]
                    except Exception as exc:
                        coordinator_error = f"{type(exc).__name__}: {exc}"
                        admission_closed.set()
                        break
            if not futures:
                break
            done, _ = wait(futures, return_when=FIRST_COMPLETED)
            for future in done:
                job_id = futures.pop(future)
                try:
                    results[job_id] = future.result()
                except Exception as exc:
                    admission_closed.set()
                    coordinator_error = f"{type(exc).__name__}: {exc}"
                    results[job_id] = {
                        "id": job_id,
                        "status": "failed",
                        "error": coordinator_error,
                    }
    ordered = [
        results.get(j["id"], {"id": j["id"], "status": "not-admitted"})
        for j in plan["jobs"]
    ]
    summary = {
        "kind": "Stage1OutputScheduleResult.v1",
        "amendment_sha256": expected_sha256,
        "evidence_scope": plan["evidence_scope"],
        "status": "complete"
        if all(x["status"] == "complete" for x in ordered)
        else "failed-preserved",
        "jobs": ordered,
        "gate_accepted": False,
        "handoff": handoff,
    }
    if coordinator_error:
        summary["coordinator_error"] = coordinator_error
    save(control / "summary.json", summary)
    return summary
