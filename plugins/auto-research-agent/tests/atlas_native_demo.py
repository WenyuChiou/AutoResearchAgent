"""One-command repository-case demo: Python fake child, never Codex/models.

This test-only launcher composes installed repository modules. Saved Stage1/2
fixtures are independent examples, not evidence of an actual research chain.
Fresh output retains intents, raw bytes, failures and offline stage artifacts.
"""

import argparse
from copy import deepcopy
import json
from pathlib import Path
import secrets
import shutil
import sys
import threading
import time
import webbrowser


SCRIPT = """import json,sys
turn=0
pending=None
def emit(value):print(json.dumps(value),flush=True)
def finish(t):
 emit({'method':'item/completed','params':{'threadId':'synthetic-thread','turnId':t,'item':{'id':'item-'+t,'type':'agentMessage','text':'Synthetic reply; no Codex/model/command executed.'}}})
 emit({'method':'turn/completed','params':{'threadId':'synthetic-thread','turn':{'id':t,'status':'completed'}}})
for line in sys.stdin.buffer:
 m=json.loads(line)
 with open('received.jsonl','ab') as saved:saved.write(line)
 method=m.get('method')
 if method=='initialized':continue
 if method=='initialize':r={'userAgent':'synthetic-python-fake'}
 elif method=='account/read':r={'requiresOpenaiAuth':True,'account':{'type':'apiKey'}}
 elif method=='thread/start':
  p=m['params'];r={'thread':{'id':'synthetic-thread'},'cwd':p['cwd'],'model':p['model'],'approvalPolicy':p['approvalPolicy'],'sandbox':{'type':'readOnly','networkAccess':False}}
 elif method=='turn/start':
  turn+=1;t='synthetic-turn-'+str(turn)
  emit({'id':m['id'],'result':{'turn':{'id':t}}})
  text=m['params']['input'][0]['text']
  if text in ('question','approval'):
   pending=(t,83+turn);p={'threadId':'synthetic-thread','turnId':t,'itemId':'synthetic-item-'+str(turn)}
   if text=='question':p['questions']=[{'id':'q','question':'Synthetic example: which research direction should be reviewed next?'}];name='item/tool/requestUserInput'
   else:p.update(command='synthetic-no-op',reason='Demo only; no command will run.');name='item/commandExecution/requestApproval'
   emit({'id':pending[1],'method':name,'params':p})
  else:finish(t)
  continue
 elif method=='turn/interrupt':
  emit({'id':m['id'],'result':{}})
  if pending:
   emit({'method':'serverRequest/resolved','params':{'threadId':'synthetic-thread','requestId':pending[1]}})
   emit({'method':'turn/completed','params':{'threadId':'synthetic-thread','turn':{'id':pending[0],'status':'interrupted'}}})
   pending=None
  continue
 elif method is None:
  if pending and m.get('id')==pending[1]:
   emit({'method':'serverRequest/resolved','params':{'threadId':'synthetic-thread','requestId':pending[1]}})
   finish(pending[0]);pending=None
  continue
 else:continue
 emit({'id':m['id'],'result':r})
"""


def repository_cases(output):
    """Copy only newly generated repository synthetic fixture outputs."""
    from test_workspace_atlas import payload
    from test_research_brief import brief
    from test_stage1_ledger import fixture
    from test_stage2_completion import Stage2CompletionTests
    from research_workspace.stage2_import import (
        prepare_stage2_bridge,
        import_evaluated_delivery,
    )
    from stage1_deliverable.common import canonical, sha

    source = output / "views" / "repo-case"
    source.mkdir(parents=True)
    inputs = output / "inputs"
    inputs.mkdir()
    fixture(inputs / "stage1-ledger")
    saved = Stage2CompletionTests("runTest")
    try:
        saved.setUp()
        saved.deliver(disposition="park")
        evaluation = saved.evaluated()
        delivery = inputs / "stage2-delivery"
        evaluated = inputs / "stage2-evaluation"
        shutil.copytree(saved.delivery, delivery)
        shutil.copytree(saved.root / "completion-evaluation", evaluated)
        delivery_sha = saved.manifest["manifest_sha256"]
    finally:
        saved.doCleanups()
    value = payload()
    bridge = prepare_stage2_bridge(
        value["index"],
        evaluated,
        expected_manifest_sha256=evaluation["manifest_sha256"],
    )
    value["stage2"], extras = import_evaluated_delivery(
        value["index"],
        evaluated,
        bridge,
        expected_bridge_sha256=sha(canonical(bridge)),
    )
    brief_path = source / "brief.json"
    brief_path.write_bytes(canonical(brief()))
    return (
        value,
        extras,
        source,
        brief_path,
        {
            1: {"ledger_root": (inputs / "stage1-ledger").as_posix()},
            2: {
                "delivery_root": delivery.as_posix(),
                "delivery_manifest_sha256": delivery_sha,
                "evaluation_root": evaluated.as_posix(),
                "evaluation_manifest_sha256": evaluation["manifest_sha256"],
            },
        },
    )


class SyntheticAuthority:
    """Admit only this exact fresh demo spec and fixed Python child bytes."""

    def __init__(self, spec, digest, child):
        self.spec, self.digest, self.child = deepcopy(spec), digest, child

    def verify(self, event):
        return (
            event.get("spec") == self.spec
            and event.get("spec_sha256") == self.digest
            and self.spec["model"] == "synthetic-model-no-network"
            and self.child.read_bytes() == SCRIPT.encode("utf8")
        )

    def gate(self, event, kind):
        if (
            not self.verify(event)
            or event.get("permit_sha256") != self.spec["permit_sha256"]
        ):
            return False
        action = event.get("action", {})
        if kind == "approval_policy":
            request, binding = action.get("request", {}), action.get("binding", {})
            return (
                action.get("principal") == "local-viewer"
                and binding.get("project_id") == self.spec["project_id"]
                and binding.get("index_sha256") == self.spec["index_sha256"]
                and binding.get("input_version") == self.spec["input_version"]
                and request.get("payload", {}).get("command") == "synthetic-no-op"
            )
        if any(action.get(k) != self.spec[k] for k in ("project_id", "index_sha256")):
            return False
        if kind == "admit_spawn":
            argv = action.get("argv", [])
            return (
                len(argv) == 3
                and Path(argv[0]).resolve() == Path(sys.executable).resolve()
                and argv[1:] == ["app-server", "--stdio"]
                and action.get("input_version") == self.spec["input_version"]
            )
        if kind == "admit_lifecycle":
            return action.get("input_version") == self.spec[
                "input_version"
            ] and action.get("method") in {
                "new-session",
                "initialize",
                "initialized",
                "account/read",
                "thread/start",
                "handoff",
            }
        if kind == "admit_attach":
            return all(
                action.get(k) == self.spec[k]
                for k in ("project_ref", "source_root", "input_version")
            )
        return kind == "admit_action" and action.get("method") in {
            "turn/start",
            "turn/interrupt",
            "item/tool/requestUserInput",
            "item/commandExecution/requestApproval",
        }

    def callbacks(self):
        names = (
            "admit_spawn",
            "admit_lifecycle",
            "admit_attach",
            "admit_action",
            "approval_policy",
        )
        return {
            "verify_source": self.verify,
            **{
                name: (lambda event, name=name: self.gate(event, name))
                for name in names
            },
        }


def build_demo(output, *, port=0, lease=600, language="zh-Hans"):
    from research_workspace.atlas import atlas_files
    from research_workspace_native.atlas_host import AtlasHost
    from research_workspace_native.codex_probe import _file_sha
    from research_workspace_native.harness_ops import HarnessOps
    from research_workspace_native.http import token_authenticator
    from research_workspace_native.runtime_factory import compose_runtime
    from research_workspace_native.scope_api import ScopeApi
    from research_workspace_native.stage_actions import StageActions
    from research_workspace_native.stage_inputs import snapshot_inputs, source_digest
    from stage1_deliverable.common import canonical, sha, private_output

    output = private_output(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    value, extras, source, brief_path, inputs = repository_cases(output)
    raw_index = canonical(value["index"])
    assets = {**atlas_files(value), **extras, "workspace-index.json": raw_index}
    for name, raw in assets.items():
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    child = source / "app-server"
    child.write_bytes(SCRIPT.encode("utf8"))
    storage = output / "runtime"
    storage.mkdir()
    spec = dict(
        kind="NativeAtlasRuntimeSpec",
        schema_version="1.0.0",
        project_ref="repo-case",
        project_id=value["index"]["project_id"],
        principals=["local-viewer"],
        source_root=source.as_posix(),
        index_path=(source / "workspace-index.json").as_posix(),
        index_sha256=sha(raw_index),
        input_path=brief_path.as_posix(),
        input_version=sha(brief_path.read_bytes()),
        store_path=(storage / "session.sqlite").as_posix(),
        executable=Path(sys.executable).resolve().as_posix(),
        executable_sha256=_file_sha(Path(sys.executable)),
        model="synthetic-model-no-network",
        approval_policy="on-request",
        permit_sha256=sha(
            canonical(
                {
                    "kind": "SyntheticOnlyPermit",
                    "root": output.as_posix(),
                    "index_sha256": sha(raw_index),
                    "child_sha256": sha(child.read_bytes()),
                }
            )
        ),
        limits=dict(
            lifetime_seconds=lease,
            max_stream_bytes=1048576,
            max_text_bytes=4096,
            max_starts=32,
            timeout_seconds=3,
        ),
    )
    config = output / "runtime-spec.json"
    config.write_bytes(canonical(spec))
    digest = sha(config.read_bytes())
    authority = SyntheticAuthority(spec, digest, child)
    token = secrets.token_urlsafe(32)
    authenticate = token_authenticator({token: "local-viewer"})
    runtime = ops = stages = server = None
    try:
        runtime = compose_runtime(
            [(config, digest)],
            enabled=True,
            authenticate=authenticate,
            gates={"repo-case": authority.callbacks()},
        )
        scope = ScopeApi(runtime.api)
        scope.register(
            "repo-case", brief_path="brief.json", expected_sha256=spec["input_version"]
        )
        ops = HarnessOps(
            storage / "harness.sqlite",
            authenticate=authenticate,
            registrations={
                "repo-case": dict(
                    index_raw=raw_index,
                    index_sha256=sha(raw_index),
                    output_root=output / "outputs" / "harness",
                    principals=["local-viewer"],
                )
            },
        )
        source_sha256 = source_digest(snapshot_inputs(inputs))
        stages = StageActions(
            storage / "stages.sqlite",
            authenticate=authenticate,
            registrations={
                "repo-case": dict(
                    project_id=spec["project_id"],
                    index_sha256=spec["index_sha256"],
                    input_version=spec["input_version"],
                    source_sha256=source_sha256,
                    inputs=inputs,
                    output_root=output / "outputs" / "stages",
                    principals=["local-viewer"],
                )
            },
        )
        manifest = canonical(
            {
                "kind": "SyntheticAtlasDemo",
                "files": {k: sha(v) for k, v in assets.items()},
            }
        )
        files = {"/views/repo-case/" + k: v for k, v in assets.items()}
        files["/views/repo-case/view-manifest.json"] = manifest
        views = [
            dict(
                ref="repo-case",
                label="Repository Stage1/2 · synthetic · no model",
                url="/views/repo-case/atlas.html",
                project_id=spec["project_id"],
                index_sha256=spec["index_sha256"],
                manifest_sha256=sha(manifest),
                fixture=True,
            )
        ]
        server = AtlasHost(
            files=files,
            views=views,
            port=port,
            credential=token,
            native_runtime=runtime,
            scope_api=scope,
            harness_ops=ops,
            stage_actions=stages,
            presentation={"language": language, "density": "comfortable"},
            connection={"status": "synthetic-fake-child-only", "actual_codex": False},
            capability_state={"native": "synthetic-only", "maintenance": "disabled"},
        )
        runtime.start()
        offer = runtime.api.offer(token, "repo-case")
        runtime.api.message(
            token,
            "repo-case",
            {
                **{k: offer[k] for k in ("offer_ref", "offer_sha256", "revision")},
                "key": "seed-question",
                "text": "question",
            },
        )
        until = time.monotonic() + 5
        while time.monotonic() < until:
            if any(
                q["status"] == "pending"
                for q in runtime.api.view(token, "repo-case")["requests"]
            ):
                break
            time.sleep(0.01)
        else:
            raise RuntimeError("synthetic question not observed")
        receipt = dict(
            kind="SyntheticAtlasDemoReceipt",
            synthetic=True,
            actual_codex=False,
            model_executed=False,
            actual_research=False,
            original_stage1_lineage_attested=False,
            url=f"http://127.0.0.1:{server.server_port}/views/repo-case/atlas.html",
            spec_sha256=digest,
            index_sha256=spec["index_sha256"],
            source_sha256=source_sha256,
            native_lease_seconds=lease,
            source_fixture="repository synthetic test cases",
            initial_question_observed=True,
            cleanup="pending",
        )
        (output / "demo-ready.json").write_bytes(canonical(receipt))
        return server, receipt
    except BaseException as error:
        failures = []
        for name, resource in (
            ("host", server),
            ("stages", stages),
            ("ops", ops),
            ("runtime", runtime),
        ):
            if resource is None:
                continue
            try:
                (
                    resource.server_close
                    if name == "host"
                    else resource.shutdown
                    if name == "runtime"
                    else resource.close
                )()
            except BaseException as cleanup_error:
                failures.append(
                    {"resource": name, "error": type(cleanup_error).__name__}
                )
        (output / "demo-failed.json").write_bytes(
            canonical(
                {
                    "error": type(error).__name__,
                    "cleanup_errors": failures,
                    "composition_cleanup_unobserved": bool(
                        getattr(error, "runtime", None)
                        or getattr(error, "orphan", None)
                    ),
                    "partial_runtime_retained": getattr(error, "runtime", None)
                    is not None,
                    "partial_orphan_retained": getattr(error, "orphan", None)
                    is not None,
                }
            )
        )
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo", type=Path, default=Path(__file__).resolve().parents[3]
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--lease", type=int, default=600)
    parser.add_argument(
        "--seconds",
        type=float,
        default=None,
        help="Bound host for automated smoke only.",
    )
    parser.add_argument("--open", action="store_true")
    args = parser.parse_args()
    if (
        not 1 <= args.lease <= 600
        or not 0 <= args.port <= 65535
        or (args.seconds is not None and not 0 < args.seconds <= 600)
    ):
        parser.error("lease/port/host duration outside demo bounds")
    plugin = args.repo.resolve() / "plugins" / "auto-research-agent"
    if not (
        plugin / "cli" / "research_workspace_native" / "runtime_factory.py"
    ).is_file():
        parser.error("complete repository with installed runtime_factory required")
    sys.path[:0] = [str(plugin / "cli"), str(plugin / "tests")]
    # Pass the unresolved absolute path to private_output so link/reparse
    # rejection sees its original components before canonical resolution.
    server, receipt = build_demo(args.output, port=args.port, lease=args.lease)
    serve_demo(
        server, receipt, args.output, seconds=args.seconds, open_browser=args.open
    )


def serve_demo(server, receipt, output, *, seconds=None, open_browser=False):
    """Own cleanup immediately, including startup print/browser failures."""
    timer = None
    error = None
    try:
        print(json.dumps(receipt, ensure_ascii=False), flush=True)
        print(
            "SYNTHETIC ONLY: answer the seeded question; send approval for an approval example, question for another question, or interrupt a waiting turn. No Codex/model/command runs.",
            flush=True,
        )
        if open_browser:
            webbrowser.open(receipt["url"])
        if seconds is not None:
            timer = threading.Timer(seconds, server.shutdown)
            timer.daemon = True
            timer.start()
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    except BaseException as caught:
        error = type(caught).__name__
        raise
    finally:
        if timer is not None:
            timer.cancel()
        cleanup_errors = []
        try:
            server.server_close()
        except BaseException as cleanup_error:
            cleanup_errors.append(type(cleanup_error).__name__)
            raise
        finally:
            from stage1_deliverable.common import canonical

            (Path(output).resolve() / "demo-completion.json").write_bytes(
                canonical(
                    {
                        "kind": "SyntheticAtlasDemoCompletion",
                        "model_executed": False,
                        "host_error": error,
                        "cleanup_errors": cleanup_errors,
                        "native_shutdown": server.native_shutdown,
                    }
                )
            )


if __name__ == "__main__":
    main()
