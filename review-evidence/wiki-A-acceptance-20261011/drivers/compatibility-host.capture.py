"""Test-only raw-byte saved-view host; no runtime, Codex or source execution."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import types

def main():
    repo, out = map(Path, sys.argv[1:3])
    root = Path('<LOCAL_WORKSPACE>/_private/workspace-return/consolidation-20261010-v2')
    cases = [(root/'wiki-selfcheck-v1/static-cases-v3/stage1-real-retained-r3','stage1','Real historical r3 partial/review-only',False),
             (root/'wiki-stage2-saved-case-v3/view','stage2','Original saved repository Stage2 fixture',True)]
    before = {p.relative_to(repo).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in (repo/'plugins/auto-research-agent/cli').rglob('*.py')}
    with tempfile.TemporaryDirectory(prefix='wiki-a-raw-') as temporary:
        snapshot = Path(temporary).resolve()
        target = snapshot/'plugins/auto-research-agent'
        shutil.copytree(repo/'plugins/auto-research-agent/cli',target/'cli',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
        shutil.copytree(repo/'plugins/auto-research-agent/schemas',target/'schemas')
        shutil.copytree(repo/'plugins/auto-research-agent/tests',target/'tests',ignore=shutil.ignore_patterns('__pycache__','*.pyc','.venv'))
        shutil.copytree(repo/'plugins/auto-research-agent/references/research-workspace',target/'references/research-workspace')
        files = {'cli/'+p.relative_to(target/'cli').as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in (target/'cli').rglob('*') if p.is_file()}
        # Fresh cache-free copied source; -I -B child, no preloaded owned package.
        sys.path.insert(0,str(target/'cli'))
        from research_workspace_native.atlas_host import AtlasHost, load_views
        sys.path.insert(0,str(target/'tests'))
        from research_workspace.view import write_workspace
        from test_research_workspace_view import fixture_index
        write_workspace(fixture_index(),target/'references/research-workspace',out/'current-synthetic-fixture/stage1',atlas=True)
        cases.append((out/'current-synthetic-fixture/stage1','stage1-current','Current source-generated repository Stage1 fixture',True))
        views = [dict(ref=ref,label=label,fixture=fixture,manifest=str(case/'view-manifest.json'),sha256=hashlib.sha256((case/'view-manifest.json').read_bytes()).hexdigest()) for case,ref,label,fixture in cases]
        raw=(json.dumps(dict(views=views),ensure_ascii=False,indent=2)+'\n').encode('utf8')
        config=out/'host.json'
        config.write_bytes(raw)
        assets, bound = load_views(config,hashlib.sha256(raw).hexdigest())
        server=AtlasHost(files=assets,views=bound,port=0)
        stop=out/'stop'
        def shutdown():
            deadline=time.monotonic()+120
            while not stop.exists() and time.monotonic()<deadline:
                time.sleep(.05)
            server.shutdown()
        thread=threading.Thread(target=shutdown,daemon=True)
        thread.start()
        head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo).decode().strip()
        ready=dict(origin=server.expected_origin,head=head,config_sha256=hashlib.sha256(raw).hexdigest(),source_before=before,views=bound,actual_native_or_model_calls=0)
        (out/'ready.json').write_bytes((json.dumps(ready,indent=2)+'\n').encode())
        try:
            server.serve_forever(poll_interval=.05)
        finally:
            server.server_close()
            thread.join(2)
            after={p.relative_to(repo).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in (repo/'plugins/auto-research-agent/cli').rglob('*.py')}
            (out/'host-cleanup.json').write_bytes((json.dumps(dict(source_inventory_equal=before==after,shutdown_thread_alive=thread.is_alive(),actual_native_or_model_calls=0),indent=2)+'\n').encode())
            if before != after or thread.is_alive():
                raise SystemExit(1)

if __name__=='__main__':
    main()
