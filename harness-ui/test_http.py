"""Start the actual loopback host against synthetic input, with zero research limits."""
import hashlib
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading
import unittest
import uuid
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from test_materials import REPO, write_stage2_fixture

HERE = Path(__file__).resolve().parent


class PortableHost(unittest.TestCase):
    def test_authenticated_material_to_workflow(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            incoming = root/'incoming'
            packet = write_stage2_fixture(incoming)
            packet_path = incoming/'packet.json'
            packet_path.write_text(json.dumps(packet), encoding='utf-8')
            pin = hashlib.sha256(packet_path.read_bytes()).hexdigest()
            helper = REPO/'plugins/auto-research-agent/cli/research_workspace_native/atlas_local_source.py'
            startup_probe = (
                "import faulthandler,os,runpy,sys;"
                "faulthandler.dump_traceback_later(20);"
                "script=sys.argv.pop(1);sys.path.insert(0,os.path.dirname(script));"
                "runpy.run_path(script,run_name='__main__')"
            )
            command = [sys.executable, '-X', 'utf8', '-c', startup_probe, str(HERE/'run_v9.py'),
                       '--repo', str(REPO), '--source-helper-sha256', hashlib.sha256(helper.read_bytes()).hexdigest(),
                       '--projects-root', str(root/'projects'), '--ui-state-root', str(root/'state'),
                       '--incoming-root', str(incoming), '--run-limits', str(HERE/'zero-limits.json'), '--port', '0']
            with (root/'stderr.log').open('w+', encoding='utf-8') as errors:
                process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=errors,
                                           text=True, encoding='utf-8', env={**os.environ, 'PYTHONDONTWRITEBYTECODE':'1'})
                output = queue.Queue()
                reader = threading.Thread(target=lambda: output.put(process.stdout.readline()), daemon=True)
                reader.start()
                try:
                    try:
                        line = output.get(timeout=30)
                    except queue.Empty:
                        errors.seek(0)
                        self.fail('No startup receipt within 30 seconds; child stderr:\n'+errors.read())
                    if not line:
                        errors.seek(0)
                        self.fail(errors.read())
                    receipt = json.loads(line)
                    self.assertEqual(receipt['model_calls'], 0)
                    base = receipt['url'].rstrip('/')
                    with urlopen(base+'/project-bootstrap.js', timeout=5) as response:
                        bootstrap = response.read().decode()
                    token = json.loads(bootstrap.split('=', 1)[1].strip().removesuffix(';'))['credential']

                    def call(path, body=None, auth=True, origin=None):
                        headers = {'Origin':origin or base}
                        if auth:
                            headers['Authorization'] = 'Bearer '+token
                        if body is not None:
                            headers['Content-Type'] = 'application/json'
                        request = Request(base+path, None if body is None else json.dumps(body).encode(), headers)
                        try:
                            with urlopen(request, timeout=5) as response:
                                return response.status, json.loads(response.read())
                        except HTTPError as error:
                            return error.code, json.loads(error.read())

                    def ok(path, body=None):
                        status, value = call(path, body)
                        self.assertEqual(status, 200, value)
                        return value

                    self.assertEqual(call('/api/v9/materials', auth=False)[0], 401)
                    self.assertEqual(call('/api/v9/import-packet', {}, origin='https://invalid.example')[0], 403)
                    project = ok('/api/projects', {'key':str(uuid.uuid4()), 'topic':'Synthetic V9 adapter test'})
                    material = ok('/api/v9/import-packet', dict(project_ref=project['project_ref'],
                        packet_path=str(packet_path), source_root=str(incoming), sha256=pin))
                    view = ok('/api/v9/packets/'+material['id'])
                    self.assertEqual(json.loads(view['packet_text']), packet)
                    self.assertFalse(view['formal_selection']['available'])
                    self.assertFalse(view['research_generated'])
                    selection = dict(packet_sha256=pin, source_ids=['src-1'],
                                     candidates=[{'candidate_id':'candidate-1', 'version':1}])
                    draft = ok('/api/v9/draft', dict(id=material['id'], revision=0, note='test',
                                                   target_stage=2, selection=selection))
                    self.assertEqual(draft['selection'], {**selection, 'kind':'comparison-shortlist-not-human-selection'})
                    self.assertFalse(draft['submitted_to_harness'])
                    operation = ok('/api/v9/workflow/prepare', dict(id=material['id'], expected_sha256=pin))
                    restored = ok('/api/v9/workflows/'+operation['id'])
                    self.assertEqual(restored['event_head'], operation['event_head'])
                    self.assertEqual(restored['actions'], 0)
                    self.assertEqual(ok('/api/v9/workflow/prepare', dict(id=material['id'], expected_sha256=pin))['event_head'], operation['event_head'])
                    self.assertEqual(call('/api/v9/human-record', {})[0], 404)
                    invalid = {**selection, 'source_ids':['absent']}
                    self.assertEqual(call('/api/v9/draft', dict(id=material['id'], revision=1,
                        note='', target_stage=2, selection=invalid))[0], 409)
                finally:
                    process.terminate()
                    process.wait(timeout=10)
                    reader.join(timeout=2)
                    process.stdout.close()


if __name__ == '__main__':
    unittest.main(verbosity=2)
