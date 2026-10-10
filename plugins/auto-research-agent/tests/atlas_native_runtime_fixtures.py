"""Python fake child only; never Codex, models or actual commands."""

import atlas_test_paths  # noqa: F401 -- standalone discovery needs the local CLI.

from pathlib import Path
import sys
import tempfile
import time
import unittest
from research_workspace_native.codex_probe import _file_sha
from test_workspace_atlas import payload
from test_research_workspace_stage2_presentation import attachment
from copy import deepcopy
from stage1_deliverable.common import canonical, sha


def cross_project_case(spec, config, root):
    """Synthetic second project with first store deliberately inside its source."""
    other = root / "other-source"
    other.mkdir()
    index, research_input = other / "index.json", other / "input.json"
    index.write_bytes(canonical(dict(project_id="second-project")))
    research_input.write_bytes(b"synthetic-input")
    second = dict(
        spec,
        project_ref="other-case",
        project_id="second-project",
        source_root=other.as_posix(),
        index_path=index.as_posix(),
        index_sha256=sha(index.read_bytes()),
        input_path=research_input.as_posix(),
        input_version=sha(research_input.read_bytes()),
        store_path=(root / "runtime" / "second.sqlite").as_posix(),
    )
    first = deepcopy(spec)
    first["store_path"] = (other / "first.sqlite").as_posix()
    config.write_bytes(canonical(first))
    second_path = root / "second.json"
    second_path.write_bytes(canonical(second))
    return [
        (config, sha(config.read_bytes())),
        (second_path, sha(second_path.read_bytes())),
    ], (first["store_path"], second["store_path"])


SCRIPT = """import json,sys
turn=0
pending=None
def emit(value):print(json.dumps(value),flush=True)
def finish(t):
 emit({'method':'item/completed','params':{'threadId':'synthetic-thread','turnId':t,'item':{'id':'item-'+t,'type':'agentMessage','text':'Synthetic reply; no model executed.'}}})
 emit({'method':'turn/completed','params':{'threadId':'synthetic-thread','turn':{'id':t,'status':'completed'}}})
for line in sys.stdin.buffer:
 m=json.loads(line)
 with open('received.jsonl','ab') as saved:saved.write(line)
 method=m.get('method')
 if method=='initialized':continue
 if method=='initialize':r={'userAgent':'synthetic-fake'}
 elif method=='account/read':r={'requiresOpenaiAuth':True,'account':{'type':'apiKey'}}
 elif method=='thread/start':
  p=m['params'];r={'thread':{'id':'synthetic-thread'},'cwd':p['cwd'],'model':p['model'],'approvalPolicy':p['approvalPolicy'],'sandbox':{'type':'readOnly','networkAccess':False}}
 elif method=='turn/start':
  turn+=1;t='synthetic-turn-'+str(turn)
  emit({'id':m['id'],'result':{'turn':{'id':t}}})
  text=m['params']['input'][0]['text']
  if text in ('question','approval'):
   pending=t;p={'threadId':'synthetic-thread','turnId':t,'itemId':'synthetic-item'}
   if text=='question':p['questions']=[{'id':'q','question':'Synthetic scope?'}];name='item/tool/requestUserInput'
   else:p.update(command='synthetic-no-op',reason='Synthetic approval fixture');name='item/commandExecution/requestApproval'
   emit({'id':83,'method':name,'params':p})
  else:finish(t)
  continue
 elif method=='turn/interrupt':
  emit({'id':m['id'],'result':{}})
  emit({'method':'turn/completed','params':{'threadId':'synthetic-thread','turn':{'id':pending,'status':'interrupted'}}})
  continue
 elif method is None:
  emit({'method':'serverRequest/resolved','params':{'threadId':'synthetic-thread','requestId':83}})
  finish(pending);pending=None;continue
 else:continue
 emit({'id':m['id'],'result':r})
"""


class CompositionCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.source = self.root / "source"
        self.storage = self.root / "runtime"
        self.source.mkdir()
        self.storage.mkdir()
        self.value = payload()
        self.value["stage2"] = (
            attachment()
        )  # Existing repository case, still synthetic.
        self.index = self.source / "workspace-index.json"
        self.index.write_bytes(canonical(self.value["index"]))
        self.input = self.source / "input.json"
        self.input.write_bytes(
            canonical({"case": "repository-stage1-stage2-synthetic"})
        )
        self.child = self.source / "app-server"
        self.child.write_bytes(SCRIPT.encode())
        self.token = "synthetic-local-token-" + "x" * 24
        self.spec = dict(
            kind="NativeAtlasRuntimeSpec",
            schema_version="1.0.0",
            project_ref="repo-case",
            project_id=self.value["index"]["project_id"],
            principals=["local-viewer"],
            source_root=self.source.as_posix(),
            index_path=self.index.as_posix(),
            index_sha256=sha(self.index.read_bytes()),
            input_path=self.input.as_posix(),
            input_version=sha(self.input.read_bytes()),
            store_path=(self.storage / "session.sqlite").as_posix(),
            executable=Path(sys.executable).resolve().as_posix(),
            executable_sha256=_file_sha(Path(sys.executable)),
            model="synthetic-model",
            approval_policy="on-request",
            permit_sha256=sha(b"synthetic-only-test-permit"),
            limits=dict(
                lifetime_seconds=30,
                max_stream_bytes=65536,
                max_text_bytes=4096,
                max_starts=4,
                timeout_seconds=10,
            ),
        )
        self.config = self.root / "runtime.json"
        self.pin = self.save()
        self.observed = []
        self.source_ok = True
        self.allowed = True
        self.allow_accept = False
        self.gates = {
            "repo-case": {
                "verify_source": self.verify,
                **{
                    name: self.admit
                    for name in (
                        "admit_spawn",
                        "admit_lifecycle",
                        "admit_attach",
                        "admit_action",
                    )
                },
            }
        }
        self.runtime = None

    def save(self):
        self.config.write_bytes(canonical(self.spec))
        return sha(self.config.read_bytes())

    def verify(self, value):
        self.observed.append(deepcopy(value))
        return self.source_ok and self.child.read_bytes() == SCRIPT.encode()

    def admit(self, value):
        self.observed.append(deepcopy(value))
        return self.allowed

    def compose(self, **options):
        from research_workspace_native.runtime_factory import compose_runtime

        defaults = dict(
            enabled=True,
            gates=self.gates,
            authenticate=lambda token: "local-viewer" if token == self.token else None,
        )
        defaults.update(options)
        self.runtime = compose_runtime([(self.config, self.pin)], **defaults)
        self.addCleanup(self.runtime.shutdown)
        return self.runtime

    def view(self):
        return self.runtime.api.view(self.token, "repo-case")

    def wait(self, predicate):
        until = time.monotonic() + 3
        while time.monotonic() < until:
            if predicate():
                return
            time.sleep(0.01)
        self.fail("synthetic condition not observed")

    def pending(self):
        return next(
            (q for q in self.view()["requests"] if q["status"] == "pending"), None
        )

    def message(self, text, key="message-1"):
        offer = self.runtime.api.offer(self.token, "repo-case")
        body = dict(
            key=key,
            revision=offer["revision"],
            offer_ref=offer["offer_ref"],
            offer_sha256=offer["offer_sha256"],
            text=text,
        )
        return body, self.runtime.api.message(self.token, "repo-case", body)

    def answer(self, result):
        question = self.pending()
        return dict(
            key="answer-1",
            revision=self.view()["revision"],
            index_sha256=self.spec["index_sha256"],
            input_version=self.spec["input_version"],
            request_ref=question["request_ref"],
            request_sha256=question["request_sha256"],
            result=result,
        )

    def count(self):
        return len((self.source / "received.jsonl").read_bytes().splitlines())
