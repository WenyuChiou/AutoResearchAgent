"""Local V7 transport for one admitted native task; no research rules or core edits.

Only server-owned case specifications can select paths or model policy. Native
turn completion and delivery validation are distinct. Reconnect never resends.
"""
from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path
import queue
import re
import sqlite3
import stat
import subprocess
import threading
import time
import types
import uuid
from collections import deque
from contextlib import contextmanager


@contextmanager
def _connection(path, *, readonly=False):
    db=sqlite3.connect(Path(path).as_uri()+"?mode=ro",uri=True,timeout=2) if readonly else sqlite3.connect(path,timeout=2)
    try:
        with db:
            yield db
    finally:
        db.close()


def _bytes(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf8")


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _require(value, reason):
    if not value:
        raise ValueError(reason)


def _no_link(path):
    for item in (Path(path),*Path(path).parents):
        if item.exists() or item.is_symlink():
            info=item.lstat()
            _require(not stat.S_ISLNK(info.st_mode) and not (getattr(info,"st_file_attributes",0)&0x400),"linked-or-reparse-path-refused")


def _file(path, expected):
    started=time.monotonic()
    path = Path(path)
    _require(path.is_absolute() and path.is_file(), "pinned-file-required")
    _no_link(path)
    raw = path.read_bytes()
    _require(_sha(raw) == expected, "pinned-file-differs")
    _require(time.monotonic()-started <= 2,"pinned-file-2s-guard-expired")
    return raw


def _private(path):
    path = Path(path)
    _require(path.is_absolute(), "absolute-private-root-required")
    _no_link(path)
    for parent in (path, *path.parents):
        _require(not parent.is_symlink() and not (parent / ".git").exists(), "private-root-in-git-or-link")
    return path


def _pins(pins):
    started=time.monotonic()
    _require(type(pins) is dict and len(pins) <= 4096,"source-pins-invalid")
    for path,digest in pins.items():
        _file(path,digest)
    _require(time.monotonic()-started <= 2,"source-pin-pass-2s-guard-expired")


class _ProcessChannel:
    """Bounded pipes with deadline-aware read/write; no shell or automatic restart."""
    def __init__(self, argv, cwd, env, *, max_bytes=1024 * 1024):
        options = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {"start_new_session": True}
        self.process = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.PIPE,
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0, **options)
        self.reads, self.writes = queue.Queue(maxsize=128), queue.Queue(maxsize=1)
        self.buffer, self.stderr, self.count, self.max_bytes = b"", bytearray(), 0, max_bytes
        self.closed, self.failure = False, None
        try:
            threading.Thread(target=self._reader, daemon=True).start()
            threading.Thread(target=self._errors, daemon=True).start()
            threading.Thread(target=self._writer, daemon=True).start()
        except BaseException:
            self.close()
            raise

    def _reader(self):
        try:
            while not self.closed:
                raw = os.read(self.process.stdout.fileno(), 4096)
                self.count += len(raw)
                if self.count > self.max_bytes:
                    raise ValueError("native-stream-bound")
                self.reads.put(raw)
                if not raw:
                    return
        except Exception as exc:
            self.failure = type(exc).__name__
            self.reads.put(b"")

    def _errors(self):
        try:
            while not self.closed:
                raw = os.read(self.process.stderr.fileno(), 4096)
                if not raw:
                    break
                if len(self.stderr) + len(raw) > 65536:
                    self.failure = "native-stderr-bound"
                    break
                self.stderr.extend(raw)
        except (OSError, ValueError):
            pass

    def _writer(self):
        while not self.closed:
            try:
                raw, result, done = self.writes.get(timeout=.1)
            except queue.Empty:
                continue
            try:
                total = 0
                while total < len(raw):
                    count = self.process.stdin.write(raw[total:])
                    if not count:
                        raise OSError("short native write")
                    total += count
                self.process.stdin.flush()
                result.append(total)
            except Exception as exc:
                result.append(exc)
            finally:
                done.set()

    def read(self, size, timeout):
        if self.failure:
            raise ValueError(self.failure)
        if not self.buffer:
            try:
                self.buffer = self.reads.get(timeout=timeout)
            except queue.Empty:
                raise TimeoutError("native-read-idle") from None
        raw, self.buffer = self.buffer[:size], self.buffer[size:]
        return raw

    def write(self, raw, timeout):
        deadline = time.monotonic() + timeout
        result, done = [], threading.Event()
        self.writes.put((raw, result, done), timeout=timeout)
        if not done.wait(max(0, deadline-time.monotonic())):
            raise TimeoutError("native-write-unknown")
        if isinstance(result[0], Exception):
            raise result[0]
        return result[0]

    def close(self):
        self.closed = True
        if self.process.poll() is None:
            self.process.terminate()
        try:
            self.process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            self.process.kill()
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                pass
        for stream in (self.process.stdin,self.process.stdout,self.process.stderr):
            try:
                stream.close()
            except OSError:
                pass
        return {"leader_stopped": self.process.poll() is not None,
                "process_tree_containment_attested": False}


class NativeAppServerProvider:
    """Real native app-server implementation. A channel factory is a trusted test seam."""
    def __init__(self, spec, workspace, *, channel_factory=None):
        self.spec, self.workspace = spec, workspace
        self.channel_factory = channel_factory

    def run(self, job, prompt, emit, deadline, stop):
        spec = self.spec
        transport_path = Path(spec["transport_path"])
        raw = _file(transport_path, spec["transport_sha256"])
        module = types.ModuleType("v7_pinned_rpc_transport")
        module.__file__ = str(transport_path)
        exec(compile(raw, str(transport_path), "exec"), module.__dict__)
        config_raw = _file(spec["config_path"], spec["config_sha256"])
        import tomllib
        names = tomllib.loads(config_raw.decode("utf8")).get("mcp_servers", {})
        _require(type(names) is dict, "mcp-config-shape")
        config = {"web_search": "disabled", "model_reasoning_effort": spec["effort"],
                  "sandbox_workspace_write.network_access":False,
                  "sandbox_workspace_write.writable_roots":[str(self.workspace)],
                  "sandbox_workspace_write.exclude_tmpdir_env_var":True,
                  "sandbox_workspace_write.exclude_slash_tmp":True,
                  "memories.use_memories":False,"memories.generate_memories":False,
                  **{f"features.{name}": False for name in ("apps", "enable_mcp_apps", "plugins", "hooks", "multi_agent")},
                  **{f"mcp_servers.{name}.enabled": False for name in names}}
        def guard():
            started=time.monotonic()
            _require(time.monotonic() < deadline and not stop.is_set(), "native-lease-ended")
            for path, digest in ((spec["task_path"], spec["task_sha256"]), (spec["skill_path"], spec["skill_sha256"]),
                                 (spec["config_path"], spec["config_sha256"]), (spec["transport_path"], spec["transport_sha256"])):
                _file(path, digest)
            _require(time.monotonic()-started <= 2,"native-2s-guard-expired")
        env = dict(os.environ, CODEX_HOME=str(Path(spec["config_path"]).parent))
        received=deque()
        def record(event):
            emit(event)
            if event.get("direction") == "incoming":
                received.append(event)
        channel=rpc=None
        outcome, thread, turn, messages = {}, None, None, []
        def request(method, params, ident):
            guard()
            response = rpc.request(method, params, request_id=ident, timeout=min(10, deadline-time.monotonic()))
            _require("result" in response, "native-rpc-rejected:" + method)
            return response["result"]
        try:
            guard()
            channel = self.channel_factory(self.workspace) if self.channel_factory else _ProcessChannel(
                [spec["executable"], "app-server"], self.workspace, env)
            rpc = module.JsonRpcTransport(channel, connection_id=job["job_ref"], on_event=record,
                                          verify_binding=guard, max_message_bytes=1024*1024)
            request("initialize", {"clientInfo": {"name":"v7-native-stage1", "version":"1"}}, "init")
            rpc.notify("initialized", timeout=min(10, deadline-time.monotonic()))
            params = dict(cwd=str(self.workspace), model=spec["model"], approvalPolicy="on-request",
                          sandbox="workspace-write", config=config)
            result = request("thread/start", params, "thread")
            thread = result.get("thread", {}).get("id")
            sandbox = result.get("sandbox", {})
            _require(isinstance(thread, str) and thread and result.get("model") == spec["model"]
                     and result.get("approvalPolicy") == "on-request"
                     and result.get("cwd", "").replace("\\", "/") == str(self.workspace).replace("\\", "/")
                     and sandbox.get("type") == "workspaceWrite" and sandbox.get("networkAccess") is False,
                     "native-thread-policy-differs")
            roots = sandbox.get("writableRoots", [])
            _require(all(Path(p).resolve() == self.workspace.resolve() for p in roots), "native-write-root-differs")
            _require(sandbox.get("excludeTmpdirEnvVar") is True and sandbox.get("excludeSlashTmp") is True,
                     "native-temp-write-policy-differs")
            _require(result.get("reasoningEffort") in {None,spec["effort"]},"native-effort-differs")
            effective_effort=result.get("reasoningEffort")
            result = request("turn/start", dict(threadId=thread, model=spec["model"], cwd=str(self.workspace),
                             input=[{"type":"text", "text":prompt}], effort=spec["effort"]), "turn")
            turn = result.get("turn", {}).get("id")
            _require(isinstance(turn,str) and turn, "native-turn-id-missing")
            emit({"direction":"local", "kind":"binding", "message":{"thread_id":thread,"turn_id":turn,
                  "model":spec["model"], "effort_requested":spec["effort"],
                  "effort_effective":effective_effort, "network_access":False}})
            while time.monotonic() < deadline and not stop.is_set():
                if not received:
                    rpc.poll(min(.25, max(0, deadline-time.monotonic())))
                    if not received:
                        continue
                event=received.popleft()
                frame = event["message"]
                params = frame.get("params", {})
                if event["kind"] == "request":
                    if frame["method"] in {"item/commandExecution/requestApproval", "item/fileChange/requestApproval"}:
                        _require(params.get("threadId") == thread and params.get("turnId") == turn, "approval-binding-differs")
                        rpc.answer(frame["id"], {"decision":"decline"}, binding={"connection_id":job["job_ref"], "request":frame}, timeout=min(2, deadline-time.monotonic()))
                    else:
                        outcome = dict(status="execution-unknown", reason="native-request-held", pending_request=frame)
                        break
                if frame.get("method") in {"item/completed", "turn/completed"}:
                    _require(params.get("threadId") == thread, "native-event-thread-differs")
                    if "turnId" in params:
                        _require(params["turnId"] == turn, "native-event-turn-differs")
                if frame.get("method") == "item/completed":
                    _require(params.get("turnId") == turn,"native-item-turn-required")
                    item = params.get("item", {})
                    if item.get("type") == "agentMessage":
                        _require(isinstance(item.get("text"),str), "native-message-text-missing")
                        messages.append(item["text"])
                if frame.get("method") == "turn/completed":
                    terminal = params.get("turn", {})
                    _require(terminal.get("id") == turn and terminal.get("status") in {"completed","failed","interrupted"}, "native-terminal-invalid")
                    outcome = dict(status="completed" if terminal["status"] == "completed" else "failed" if terminal["status"] == "failed" else "cancelled",
                                   native_terminal=True, native_status=terminal["status"], terminal=terminal)
                    break
            if not outcome:
                outcome = dict(status="execution-unknown", reason="native-deadline-or-stop-no-terminal")
        except Exception as exc:
            outcome=dict(status="execution-unknown",reason=type(exc).__name__+":"+str(exc))
        finally:
            cleanup = channel.close() if channel is not None else {"leader_stopped":True,"process_tree_containment_attested":False}
            if channel is not None:
                (self.workspace.parent/"native-stderr.txt").write_bytes(bytes(channel.stderr))
        return dict(outcome, thread_id=thread, turn_id=turn, response="\n\n".join(messages), cleanup=cleanup,
                    internal_model_calls=None, research_complete=False)


class NativeStage1Service:
    """One private durable job store; only opaque refs cross the HTTP boundary."""
    def __init__(self, private_root, trusted_case_specs, *, provider_factory=None, on_completed=None):
        self.root = _private(private_root)
        self.root.mkdir(parents=True,exist_ok=True)
        _private(self.root)
        self.cases = {}
        for spec in trusted_case_specs:
            spec = deepcopy(spec)
            ref = spec["ref"]
            _require(re.fullmatch(r"[A-Za-z0-9_-]{1,58}",ref) and ref not in self.cases,"case-ref-invalid")
            _require(type(spec["cap_seconds"]) is int and 1 <= spec["cap_seconds"] <= 150,"native-cap-invalid")
            _require(spec["effort"] in {"low","medium","high","xhigh","max","ultra"},"effort-invalid")
            _require(type(spec["budget"]["max_calls"]) is int and 1 <= spec["budget"]["max_calls"] <= 8
                     and type(spec["budget"]["calls_reserved_before"]) is int
                     and 0 <= spec["budget"]["calls_reserved_before"] < spec["budget"]["max_calls"],"budget-invalid")
            _require(type(spec["budget"]["expires_at"]) in {int,float} and math.isfinite(spec["budget"]["expires_at"]),"budget-expiry-invalid")
            _require(type(spec["budget"]["max_seconds"]) is int and 1 <= spec["budget"]["max_seconds"] <= 1200
                     and type(spec["budget"]["seconds_reserved_before"]) is int
                     and 0 <= spec["budget"]["seconds_reserved_before"] < spec["budget"]["max_seconds"],"seconds-budget-invalid")
            self.cases[ref] = (spec, _sha(_bytes(spec)))
        self.factory = provider_factory or NativeAppServerProvider
        self.on_completed = on_completed
        self.db_path = self.root/"native-stage1.sqlite3"
        self.lock, self.workers, self.closed = threading.RLock(), {}, False
        with self._db() as db:
            db.execute("CREATE TABLE IF NOT EXISTS jobs (ref TEXT PRIMARY KEY, key TEXT UNIQUE, request_sha TEXT, case_ref TEXT, spec_sha TEXT, value TEXT)")
            db.execute("CREATE TABLE IF NOT EXISTS events (seq INTEGER PRIMARY KEY, job TEXT, previous TEXT, sha TEXT, value TEXT)")

    def _db(self):
        _no_link(self.db_path)
        return _connection(self.db_path)

    def catalogue(self):
        return [dict(ref=ref,label=s["label"],project_id=s["project_id"],topic=s["topic"],spec_sha256=h,
                     skill_sha256=s["skill_sha256"],source_sha256=_sha(_bytes(s["source_pins"])),
                     model=s["model"],effort=s["effort"],connected=True,network_access=False,
                     operation="saved-case-native-task",research_complete=False) for ref,(s,h) in self.cases.items()]

    def _put(self, ref, **changes):
        with self.lock, self._db() as db:
            row=json.loads(db.execute("SELECT value FROM jobs WHERE ref=?",(ref,)).fetchone()[0])
            row.update(changes)
            db.execute("UPDATE jobs SET value=? WHERE ref=?",(_bytes(row).decode(),ref))
            return row

    def _event(self, ref, event):
        raw = _bytes(event)
        _require(len(raw) <= 2*1024*1024,"journal-event-bound")
        with self.lock,self._db() as db:
            count=db.execute("SELECT COALESCE(SUM(LENGTH(value)),0) FROM events WHERE job=?",(ref,)).fetchone()[0]
            _require(count+len(raw) <= 16*1024*1024,"journal-total-bound")
            old=db.execute("SELECT sha FROM events WHERE job=? ORDER BY seq DESC LIMIT 1",(ref,)).fetchone()
            previous=old[0] if old else "0"*64
            digest=_sha(previous.encode()+raw)
            db.execute("INSERT INTO events(job,previous,sha,value) VALUES(?,?,?,?)",(ref,previous,digest,raw.decode()))
        message=event.get("message",{})
        if event.get("kind") == "binding":
            self._put(ref,**message)
        elif event.get("direction") == "incoming":
            params=message.get("params",{})
            self._put(ref,latest_native_event={"method":message.get("method"),"kind":event.get("kind"),
                      "item_type":params.get("item",{}).get("type"),"observed_at":time.time()})

    def start(self, case_ref, key, spec_sha):
        _require(case_ref in self.cases,"native-case-unavailable")
        _require(type(key) is str and re.fullmatch(r"[A-Za-z0-9_.-]{1,120}",key),"idempotency-key-invalid")
        spec, expected=self.cases[case_ref]
        _require(spec_sha == expected,"case-spec-differs")
        request_sha=_sha(_bytes([case_ref,key,spec_sha]))
        with self.lock,self._db() as db:
            _require(not self.closed,"native-service-closed")
            db.execute("BEGIN IMMEDIATE")
            old=db.execute("SELECT request_sha,value FROM jobs WHERE key=?",(key,)).fetchone()
            if old:
                _require(old[0] == request_sha,"idempotency-payload-differs")
                return json.loads(old[1])
            _require(not any(worker.is_alive() for worker,_ in self.workers.values()),"native-worker-or-collector-active")
            for raw, in db.execute("SELECT value FROM jobs"):
                old_job=json.loads(raw)
                _require(old_job["status"] in {"completed","failed","cancelled","refused"}
                         and old_job.get("delivery_status") != "validating"
                         and (not old_job.get("native_terminal") or old_job.get("cleanup",{}).get("leader_stopped") is True),"unsettled-native-job-held")
            ref="native-"+_sha(key.encode("utf8"))
            value=dict(job_ref=ref,case_ref=case_ref,spec_sha256=expected,project_id=spec["project_id"],topic=spec["topic"],
                       status="intent-recorded",request_sha256=request_sha,native_terminal=False,delivery_status="not-produced",research_complete=False)
            db.execute("INSERT INTO jobs VALUES(?,?,?,?,?,?)",(ref,key,request_sha,case_ref,expected,_bytes(value).decode()))
            # Commit the durable intent before registration/dispatch. close and
            # worker registration share this lock so no worker appears later.
            db.commit()
            stop=threading.Event()
            worker=threading.Thread(target=self._run,args=(value,deepcopy(spec),stop),daemon=True)
            self.workers[ref]=(worker,stop)
            worker.start()
        return value

    def _reserve(self,spec,ref):
        budget=spec["budget"]
        path=_private(budget["path"])
        path.parent.mkdir(parents=True,exist_ok=True)
        with _connection(path) as db:
            db.execute("CREATE TABLE IF NOT EXISTS budget (id INTEGER PRIMARY KEY CHECK(id=1), binding TEXT, calls INTEGER, seconds INTEGER, held TEXT)")
            db.execute("BEGIN IMMEDIATE")
            binding=_sha(_bytes(budget))
            row=db.execute("SELECT binding,calls,seconds,held FROM budget WHERE id=1").fetchone()
            calls=budget["calls_reserved_before"] if row is None else row[1]
            seconds=budget["seconds_reserved_before"] if row is None else row[2]
            _require(row is None or row[0] == binding,"global-budget-binding-differs")
            _require(row is None or row[3] is None,"global-native-unknown-held")
            _require(time.time() < budget["expires_at"] and calls < budget["max_calls"],"global-budget-exhausted-or-expired")
            allocation=min(spec["cap_seconds"],budget["max_seconds"]-seconds)
            _require(allocation >= 1,"global-seconds-budget-exhausted")
            db.execute("INSERT OR REPLACE INTO budget VALUES(1,?,?,?,?)",(binding,calls+1,seconds+allocation,ref))
            return dict(calls_reserved=calls+1,max_calls=budget["max_calls"],seconds_reserved=seconds+allocation,
                        allocated_seconds=allocation,max_seconds=budget["max_seconds"],budget_binding_sha256=binding)

    def _run(self,job,spec,stop):
        ref=job["job_ref"]
        dispatched=False
        outcome=None
        reservation=None
        try:
            _require(not stop.is_set(),"native-service-stopped-before-dispatch")
            task=_file(spec["task_path"],spec["task_sha256"]).decode("utf8")
            _file(spec["skill_path"],spec["skill_sha256"])
            _file(spec["executable"],spec["executable_sha256"])
            _require(Path(spec["executable"]).name.casefold() in {"codex","codex.exe"},"native-executable-required")
            _pins(spec["source_pins"])
            prompt=("Use the unchanged Stage 1 Harness skill at "+spec["skill_path"]+". This is a saved-public-case operation only, not new research. "
                    "No network, new search/acquisition, extra model/agent or scientific acceptance. Keep original topic/targets/Unknown. "
                    "Use only the existing documented Harness CLI/API for the explicit task below. Output files only in the current private workspace.\n\n"+task)
            _require(len(prompt.encode("utf8")) <= 10000,"native-input-over-10KB")
            with self.lock:
                _require(not self.closed and not stop.is_set(),"native-service-stopped-before-dispatch")
                reservation=self._reserve(spec,ref)
                folder=_private(self.root/ref)
                workspace=folder/"output"
                workspace.mkdir(parents=True,exist_ok=False)
                _private(workspace)
                (folder/"request.json").write_bytes(_bytes(dict(job,spec=spec,prompt_sha256=_sha(prompt.encode()))))
                self._put(ref,status="running",budget=reservation,output_dir=str(workspace))
            deadline=time.monotonic()+min(reservation["allocated_seconds"],spec["budget"]["expires_at"]-time.time())
            provider=self.factory(spec,workspace)
            _require(not stop.is_set(),"native-service-stopped-before-provider")
            dispatched=True
            outcome=provider.run(job,prompt,lambda e:self._event(ref,e),deadline,stop)
            _require(type(outcome) is dict and outcome.get("status") in {"completed","failed","cancelled","execution-unknown"},"provider-outcome-invalid")
            _require(outcome["status"] == "execution-unknown" or outcome.get("native_terminal") is True,"native-terminal-required")
            response=outcome.pop("response","")
            _require(type(response) is str and len(response.encode()) <= 1024*1024,"native-response-bound")
            output=folder/"response.txt"
            with output.open("xb") as stream:
                stream.write(response.encode("utf8"))
            self._put(ref,**outcome,response_sha256=_sha(response.encode()),response_bytes=len(response.encode()),response_path=str(output))
            _pins(spec["source_pins"])
            publishable=outcome["status"] == "completed" and outcome.get("cleanup",{}).get("leader_stopped") is True
            value=self._put(ref,**outcome,response_sha256=_sha(response.encode()),response_bytes=len(response.encode()),response_path=str(output),
                            delivery_status="validating" if publishable and self.on_completed is not None else "held-cleanup-unproven" if outcome["status"] == "completed" and not publishable else "not-produced")
            if publishable and self.on_completed is not None:
                try:
                    receipt=self.on_completed(ref,spec["ref"],str(workspace))
                    _require(type(receipt) is dict and bool(receipt),"collector-receipt-required")
                    _bytes(receipt)
                    self._put(ref,delivery_status="validated-by-collector",delivery=receipt)
                except Exception as exc:
                    self._put(ref,delivery_status="failed",delivery_error=type(exc).__name__+":"+str(exc))
        except Exception as exc:
            if type(outcome) is dict and outcome.get("native_terminal") is True:
                terminal={k:v for k,v in outcome.items() if k != "response"}
                self._put(ref,**terminal,delivery_status="failed",delivery_error=type(exc).__name__+":"+str(exc))
            else:
                self._put(ref,status="execution-unknown" if dispatched else "refused",reason=type(exc).__name__+":"+str(exc))
        finally:
            # A reservation holds the shared budget before any dispatch. Only a
            # verified terminal plus stopped leader, or a proven pre-dispatch
            # refusal, can release its concurrency latch; never refund usage.
            terminal=type(outcome) is dict and outcome.get("native_terminal") is True and outcome.get("cleanup",{}).get("leader_stopped") is True
            if reservation is not None and (terminal or not dispatched):
                try:
                    self._release_budget(spec,ref)
                except Exception as exc:
                    self._put(ref,budget_hold_error=type(exc).__name__+":"+str(exc))

    def _release_budget(self,spec,ref):
        path=_private(spec["budget"]["path"])
        if not path.exists():
            return
        with _connection(path) as db:
            db.execute("UPDATE budget SET held=NULL WHERE id=1 AND held=?",(ref,))

    def status(self, job_ref):
        _no_link(self.db_path)
        with _connection(self.db_path,readonly=True) as db:
            found=db.execute("SELECT value FROM jobs WHERE ref=?",(job_ref,)).fetchone()
            _require(found is not None,"native-job-not-found")
            row=json.loads(found[0])
            event=db.execute("SELECT seq,sha FROM events WHERE job=? ORDER BY seq DESC LIMIT 1",(job_ref,)).fetchone()
            row["events_cursor"],row["events_sha256"]=(event[0],event[1]) if event else (0,None)
            return row

    def close(self):
        with self.lock:
            self.closed=True
            workers=list(self.workers.items())
            for ref,(worker,stop) in workers:
                stop.set()
        for ref,(worker,stop) in workers:
            worker.join(timeout=5)
        for ref,(worker,_) in workers:
            if worker.is_alive():
                self._put(ref,status="execution-unknown",reason="close-worker-terminal-unobserved")
