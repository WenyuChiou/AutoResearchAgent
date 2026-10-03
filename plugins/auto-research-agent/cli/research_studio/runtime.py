"""Bound native Stage 1 execution. No synthetic runtime or automatic retry."""

import importlib.metadata
import hashlib
import codecs
import json
import os
from pathlib import Path
import re
import signal
import stat
import subprocess
import sys
import threading
import time
import uuid

from .store import StudioError, canonical, safe_path, sha
from .supervision import Supervision

MAX_ARTIFACT = 64 * 1024 * 1024
MAX_LOG = 8 * 1024 * 1024
PRODUCTION = (
    "cli",
    "skills",
    "references",
    "schemas",
    "gates",
    "validators",
    "plugin.json",
    "requirements-test.txt",
)


def file_sha(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def reject_bytecode(path):
    """Source hashes cannot authenticate executable caches, even valid stale ones."""
    if path.is_file() and path.suffix.lower() in {".pyc", ".pyo"}:
        raise StudioError(
            "unbound Python bytecode cache; remove caches before service startup"
        )


def dependency_binding(plugin):
    """Read the committed lock, rejecting unknown marker syntax rather than guessing."""
    environment = {
        "sys_platform": sys.platform,
        "python_full_version": tuple(sys.version_info[:3]),
        "implementation_name": sys.implementation.name,
        "platform_python_implementation": "CPython"
        if sys.implementation.name == "cpython"
        else "PyPy",
    }
    result = {}
    for row in (
        (plugin / "requirements-test.txt").read_text(encoding="utf-8").splitlines()
    ):
        if not row or row[0].isspace() or row.startswith("#"):
            continue
        requirement, _, marker = row.partition(" ; ")
        applies = True
        for condition in marker.split(" and ") if marker else []:
            match = re.fullmatch(r"(\w+) (==|!=|>=|<) '([^']+)'", condition)
            if not match or match[1] not in environment:
                raise StudioError("unsupported dependency marker; review updated lock")
            left, right = environment[match[1]], match[3]
            if match[1] == "python_full_version":
                right = tuple(int(x) for x in right.split("."))
            applies &= {
                "==": left == right,
                "!=": left != right,
                ">=": left >= right,
                "<": left < right,
            }[match[2]]
        if not applies:
            continue
        if "==" in requirement:
            package, expected = requirement.split("==")
            actual = importlib.metadata.version(package)
            if actual != expected:
                raise StudioError(f"dependency version differs from lock: {package}")
            result[package] = actual
        else:
            match = re.fullmatch(
                r"research-hub-pipeline @ git\+https://github.com/WenyuChiou/research-hub@([0-9a-f]{40})",
                requirement,
            )
            if not match:
                raise StudioError("unsupported dependency lock entry")
            distribution = importlib.metadata.distribution("research-hub-pipeline")
            direct = json.loads(distribution.read_text("direct_url.json") or "{}")
            if (
                direct.get("vcs_info", {}).get("commit_id") != match[1]
                or direct.get("url") != "https://github.com/WenyuChiou/research-hub"
            ):
                raise StudioError("research-hub source pin differs from lock")
            files = {}
            for name in distribution.files or []:
                reject_bytecode(Path(distribution.locate_file(name)).absolute())
                if str(name).endswith(".py"):
                    path = Path(distribution.locate_file(name)).absolute()
                    safe_path(path.parent, path.name)
                    reject_bytecode(path.with_suffix(".pyc"))
                    reject_bytecode(path.with_suffix(".pyo"))
                    cache = path.parent / "__pycache__"
                    for cached in cache.glob(path.stem + ".*.pyc"):
                        safe_path(path.parent, cached.relative_to(path.parent))
                        reject_bytecode(cached)
                    files[str(name)] = file_sha(path)
            if not files:
                raise StudioError("research-hub installed source inventory missing")
            result["research-hub-pipeline"] = {
                "source": direct,
                "python_sha256": sha(canonical(files).encode()),
            }
    return result


def child_environment(home, cli, temp):
    names = {
        "PATH",
        "SystemRoot",
        "SYSTEMROOT",
        "WINDIR",
        "COMSPEC",
        "PATHEXT",
        "HOME",
        "USERPROFILE",
        "APPDATA",
        "LOCALAPPDATA",
        "LANG",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
    }
    env = {key: value for key, value in os.environ.items() if key in names}
    env.update(
        CODEX_HOME=str(home),
        PYTHONPATH=str(cli),
        TEMP=str(temp),
        TMP=str(temp),
        TMPDIR=str(temp),
        PYTHONIOENCODING="utf-8",
        PYTHONDONTWRITEBYTECODE="1",
    )
    env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + env.get("PATH", "")
    return env


def fingerprint(plugin, codex, expected_sha, env):
    repository = next(
        (p for p in [plugin, *plugin.parents] if (p / ".git").exists()), plugin
    )

    def git(*args):
        return (
            subprocess.check_output(
                ["git", "-c", f"safe.directory={repository}", "-C", str(plugin), *args],
                env=env,
                stderr=subprocess.DEVNULL,
                timeout=10,
            )
            .decode()
            .strip()
        )

    head = git("rev-parse", "HEAD")
    if head != expected_sha:
        raise StudioError("harness revision differs from expected_harness_sha")
    if git("status", "--porcelain", "--untracked-files=all", "--", *PRODUCTION):
        raise StudioError("harness production files are dirty")
    files = {}
    for name in PRODUCTION:
        source = safe_path(plugin, name)
        for path in sorted(source.rglob("*") if source.is_dir() else [source]):
            safe_path(plugin, path.relative_to(plugin))
            reject_bytecode(path)
            if "__pycache__" not in path.parts and path.is_file():
                files[path.relative_to(plugin).as_posix()] = file_sha(path)
    binary = safe_path(codex.parent, codex.name)
    with binary.open("rb") as stream:
        header = stream.read(2)
    if (
        binary.suffix.lower() in {".ps1", ".cmd", ".bat", ".js", ".sh"}
        or header == b"#!"
    ):
        raise StudioError("standalone native Codex binary required")
    version = (
        subprocess.check_output([str(binary), "--version"], env=env, timeout=10)
        .decode()
        .strip()
    )
    rules = Path(env["CODEX_HOME"]) / "rules"
    rule_files = {}
    if rules.exists():
        for path in sorted(rules.rglob("*.rules")):
            safe_path(rules, path.relative_to(rules))
            rule_files[path.relative_to(rules).as_posix()] = file_sha(path)
    return {
        "harness_sha": head,
        "production_sha256": sha(canonical(files).encode()),
        "files": files,
        "codex_sha256": file_sha(binary),
        "codex_version": version,
        "python_sha256": file_sha(Path(sys.executable)),
        "python_version": sys.version,
        "dependencies": dependency_binding(plugin),
        "execpolicy_rules": rule_files,
    }


def validate_request(request):
    required = {
        "request_id",
        "topic",
        "scope",
        "scope_confirmed",
        "stage",
        "timeout_seconds",
    }
    if not isinstance(request, dict) or set(request) != required:
        raise StudioError("unsupported or missing request fields", 400)
    try:
        if str(uuid.UUID(request["request_id"])) != request["request_id"]:
            raise ValueError()
    except (ValueError, TypeError, AttributeError) as error:
        raise StudioError("request_id must be a canonical UUID", 400) from error
    if (
        type(request["stage"]) is not int
        or request["stage"] != 1
        or request["scope_confirmed"] is not True
    ):
        raise StudioError("only explicitly confirmed Stage 1 is supported", 400)
    if any(
        not isinstance(request[k], str)
        or not request[k].strip()
        or len(request[k]) > 4000
        for k in ("topic", "scope")
    ):
        raise StudioError("topic and scope must each contain 1 to 4000 characters", 400)
    if (
        type(request["timeout_seconds"]) is not int
        or not 60 <= request["timeout_seconds"] <= 3600
    ):
        raise StudioError("timeout_seconds must be an integer from 60 to 3600", 400)


class Engine:
    def __init__(
        self,
        store,
        codex,
        home,
        expected_sha,
        token,
        *,
        model=None,
        reasoning="high",
        plugin=None,
    ):
        self.store, self.codex, self.home = (
            store,
            Path(codex).absolute(),
            Path(home).absolute(),
        )
        self.expected_sha, self.token, self.model, self.reasoning = (
            expected_sha,
            token,
            model,
            reasoning,
        )
        self.plugin = Path(plugin or Path(__file__).resolve().parents[2]).resolve()
        self.lock, self.stop_event = threading.Lock(), threading.Event()
        self.health_lock = threading.RLock()
        self.active = self.thread = None
        self.supervisor = Supervision()
        self.health = None
        self.temp = safe_path(store.root, "temp")
        self.temp.mkdir(exist_ok=True)
        self.env = child_environment(self.home, self.plugin / "cli", self.temp)

    def preflight(self):
        with self.health_lock:
            return self._preflight()

    def _preflight(self):
        if sys.platform != "linux" or sys.version_info[:2] != (3, 11):
            raise StudioError(
                "execution requires a supervised Linux host with Python 3.11"
            )
        if safe_path(self.store.root, "reconciliation-required").exists():
            raise StudioError("operator reconciliation required after interruption")
        self.supervisor.preflight()
        safe_path(self.home)
        if not self.home.is_dir():
            raise StudioError("Codex profile is missing")
        identity = fingerprint(self.plugin, self.codex, self.expected_sha, self.env)
        result = subprocess.run(
            [str(self.codex), "login", "status"],
            env=self.env,
            capture_output=True,
            timeout=10,
            check=False,
        )
        if result.returncode:
            raise StudioError("Codex authentication unavailable")
        return identity

    def status(self, refresh=False):
        with self.health_lock:
            return self._status(refresh)

    def _status(self, refresh=False):
        if not refresh and self.active and self.health:
            return {**self.health[1], "active_run_id": self.active}
        if not refresh and self.health and time.monotonic() - self.health[0] < 30:
            return {**self.health[1], "active_run_id": self.active}
        try:
            runtime, reason = self.preflight(), None
        except (
            StudioError,
            OSError,
            ValueError,
            subprocess.SubprocessError,
            importlib.metadata.PackageNotFoundError,
        ) as error:
            runtime, reason = None, str(error)
        result = {
            "available": reason is None,
            "reason": reason,
            "runtime": runtime,
            "active_run_id": self.active,
            "stages": [
                {
                    "id": i,
                    "name": f"Stage {i}",
                    "enabled": i == 1 and reason is None,
                    "reason": reason if i == 1 else "executor not connected",
                }
                for i in range(1, 7)
            ],
        }
        self.health = (time.monotonic(), result)
        return result

    def submit(self, request):
        validate_request(request)
        if self.token in canonical(request):
            raise StudioError("API credential must not appear in research input", 400)
        with self.lock:
            try:
                existing = self.store.get(request["request_id"])
            except StudioError as error:
                if error.status != 404:
                    raise
            else:
                if any(existing[k] != v for k, v in request.items()):
                    raise StudioError("request_id already binds different input")
                return existing
            if self.active:
                raise StudioError("another run is active")
            self.store.create(request)
            availability = self.status(refresh=True)
            if not availability["available"]:
                self.store.update(
                    request["request_id"], "blocked", error=availability["reason"]
                )
                return self.store.get(request["request_id"])
            self.active = request["request_id"]
            self.stop_event.clear()
            self.thread = threading.Thread(
                target=self._work, args=(request, availability["runtime"]), daemon=False
            )
            self.thread.start()
            return self.store.get(self.active)

    def stop(self, run_id):
        with self.lock:
            self.store.get(run_id)
            if self.active == run_id:
                self.stop_event.set()
            return self.store.get(run_id)

    def command(self, workspace):
        argv = [
            str(self.codex),
            "exec",
            "--json",
            "--ignore-user-config",
            "--sandbox",
            "workspace-write",
            "-c",
            'approval_policy="never"',
            "-c",
            "sandbox_workspace_write.network_access=true",
            "-c",
            'web_search="live"',
            "-c",
            f"model_reasoning_effort={json.dumps(self.reasoning)}",
            "--skip-git-repo-check",
            "-C",
            str(workspace),
            "-o",
            str(workspace / "final.md"),
        ]
        return argv + (["--model", self.model] if self.model else []) + ["-"]

    @staticmethod
    def kill(process):
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=10,
            )
        else:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        process.wait(timeout=10)

    def monitor(self, process, root, run_id, timeout):
        offsets = {"stdout.jsonl": 0, "stderr.txt": 0}
        pending = {name: b"" for name in offsets}
        decoders = {
            name: codecs.getincrementaldecoder("utf-8")("replace") for name in offsets
        }
        started, stopped, settled = time.monotonic(), None, False
        while True:
            any_chunk = False
            finished = process.poll() is not None
            if finished and not settled:
                with self.health_lock:
                    self.supervisor.cleanup()
                settled = True
            for name in offsets:
                with (root / name).open("rb") as stream:
                    stream.seek(offsets[name])
                    chunk = stream.read(
                        max(0, min(8192, MAX_LOG - sum(offsets.values())))
                    )
                any_chunk |= bool(chunk)
                offsets[name] += len(chunk)
                pending[name] = (pending[name] + chunk).replace(
                    self.token.encode(), b"[redacted]"
                )
                final = finished and not chunk
                size = (
                    len(pending[name])
                    if final
                    else max(0, len(pending[name]) - len(self.token) + 1)
                )
                text = decoders[name].decode(pending[name][:size], final=final)
                pending[name] = pending[name][size:]
                if text:
                    self.store.event(run_id, name.split(".")[0], text)
            limit = sum((root / name).stat().st_size for name in offsets) > MAX_LOG
            if stopped is None and (
                self.stop_event.is_set()
                or time.monotonic() - started > timeout
                or limit
            ):
                stopped = (
                    "stopped"
                    if self.stop_event.is_set()
                    else "failed"
                    if limit
                    else "timed-out"
                )
                self.kill(process)
            if finished and not any_chunk:
                break
            if not finished:
                time.sleep(0.05)
        if os.name != "nt":
            self.kill(process)  # A leader can finish while group members survive.
        return stopped

    def _work(self, request, identity):
        run_id, process = request["request_id"], None
        status, error, code, artifacts = "failed", None, None, []
        workspace = safe_path(self.store.root, f"runs/{run_id}/workspace")
        try:
            workspace.mkdir(parents=True, exist_ok=False)
            prompt = (
                f"Read and follow {self.plugin / 'skills/stage1-literature/SKILL.md'}. "
                "Perform only Stage 1 within the user's confirmed scope. Preserve the original direction; "
                "ask for unresolved material scope in final.md and stop if necessary. "
                "Use native tools and existing Harness CLIs, never evaluator or benchmark inputs. "
                "Write research files only in this workspace. Preserve real source/evidence and failures. "
                "Do not authorize later stages, invent receipts, or equate process success with science. "
                "The timeout is an execution limit, not evidence of sufficient coverage. "
                "User request JSON follows:\n" + canonical(request)
            )
            command = self.command(workspace)
            manifest = {
                "kind": "ResearchStudioExecutionIndex",
                "version": 1,
                "runtime": identity,
                "producer_run_id": run_id,
                "stage": 1,
                "command": command,
                "request_sha256": sha(canonical(request).encode()),
                "prompt_sha256": sha(prompt.encode()),
                "canonical_artifact_ref": False,
                "scientific_complete": False,
                "artifacts": [],
            }
            (workspace.parent / "request.json").write_text(
                canonical(request), encoding="utf-8"
            )
            (workspace.parent / "prompt.txt").write_text(prompt, encoding="utf-8")
            if self.preflight() != identity:
                raise StudioError("runtime changed before launch")
            if self.stop_event.is_set():
                status, error = "stopped", "stopped before launch"
                return
            self.store.update(run_id, "running", manifest=manifest)
            options = (
                {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
                if os.name == "nt"
                else {"start_new_session": True}
            )
            with (
                (workspace.parent / "stdout.jsonl").open("xb") as out,
                (workspace.parent / "stderr.txt").open("xb") as err,
                (workspace.parent / "prompt.txt").open("rb") as prompt_file,
            ):
                process = subprocess.Popen(
                    command,
                    cwd=workspace,
                    env=self.env,
                    stdin=prompt_file,
                    stdout=out,
                    stderr=err,
                    shell=False,
                    **options,
                )
                stopped = self.monitor(
                    process, workspace.parent, run_id, request["timeout_seconds"]
                )
                if stopped:
                    status, error = (
                        stopped,
                        "execution or log limit reached"
                        if stopped == "failed"
                        else stopped,
                    )
                code = process.wait()
            if error is None:
                status = "human-review" if code == 0 else "failed"
                error = None if code == 0 else f"Codex exited with code {code}"
            if (
                fingerprint(self.plugin, self.codex, self.expected_sha, self.env)
                != identity
            ):
                raise StudioError("runtime bytes changed during execution")
        except Exception as caught:
            status, error = "failed", str(caught).replace(self.token, "[redacted]")
            if process is not None and process.poll() is None:
                self.kill(process)
        finally:
            settled = False
            if process is not None:
                try:
                    with self.health_lock:
                        self.supervisor.cleanup()
                    settled = True
                except (StudioError, OSError) as cleanup_error:
                    status, error = "failed", str(cleanup_error)
                    safe_path(self.store.root, "reconciliation-required").write_text(
                        error, encoding="utf-8"
                    )
                    self.health = None
            try:
                safe_path(self.store.root, f"runs/{run_id}/workspace")
                paths = workspace.rglob("*") if workspace.exists() and settled else []
                for index, path in enumerate(paths):
                    if index >= 1000:
                        status, error = (
                            "failed",
                            "artifact inventory exceeds 1000 entries",
                        )
                        break
                    try:
                        safe_path(workspace, path.relative_to(workspace))
                        if path.is_dir():
                            continue
                        data = self._bytes(workspace, path.relative_to(workspace))
                        artifacts.append(
                            {
                                "id": sha(
                                    path.relative_to(workspace).as_posix().encode()
                                ),
                                "path": path.relative_to(workspace).as_posix(),
                                "sha256": sha(data),
                                "size": len(data),
                                "version": 1,
                                "stage": 1,
                                "producer_run_id": run_id,
                                "harness_sha": identity["harness_sha"],
                            }
                        )
                    except (StudioError, OSError) as invalid:
                        status, error = "failed", str(invalid)
                        self.store.event(
                            run_id, "artifact-rejected", path.name + ": " + str(invalid)
                        )
            except (StudioError, OSError) as invalid:
                status, error = "failed", str(invalid)
            if status == "human-review" and not any(
                a["path"] == "final.md" and a["size"] for a in artifacts
            ):
                status, error = "failed", "Codex returned no final message"
            if "manifest" in locals():
                manifest["artifacts"] = artifacts
            self.store.update(
                run_id,
                status,
                error=error,
                exit_code=code,
                manifest=locals().get("manifest"),
            )
            with self.lock:
                self.active = None

    def _bytes(self, workspace, relative):
        path = safe_path(workspace, relative)
        descriptor = os.open(
            path,
            os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOFOLLOW", 0),
        )
        with os.fdopen(descriptor, "rb") as stream:
            info = os.fstat(stream.fileno())
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_nlink != 1
                or info.st_size > MAX_ARTIFACT
            ):
                raise StudioError("artifact is not a bounded regular private file")
            data = stream.read(MAX_ARTIFACT + 1)
        if len(data) > MAX_ARTIFACT or self.token.encode() in data:
            raise StudioError("artifact exceeds limits or contains API credential")
        return data

    def artifact(self, run_id, artifact_id):
        run = self.store.get(run_id)
        if self.active == run_id:
            raise StudioError("artifacts are available after execution stops")
        item = next(
            (a for a in run["manifest"].get("artifacts", []) if a["id"] == artifact_id),
            None,
        )
        if item is None:
            raise StudioError("artifact not found", 404)
        data = self._bytes(
            safe_path(self.store.root, f"runs/{run_id}/workspace"), item["path"]
        )
        if sha(data) != item["sha256"] or len(data) != item["size"]:
            raise StudioError("artifact changed after indexing")
        return data
