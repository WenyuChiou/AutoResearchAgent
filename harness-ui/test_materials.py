"""Offline contract tests using Harness's own explicitly synthetic fixture."""
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

REPO = Path(os.environ.get('HARNESS_REPO', Path(__file__).resolve().parents[1]))
sys.path[:0] = [str(REPO/'plugins/auto-research-agent/cli'), str(REPO/'plugins/auto-research-agent/tests')]
from stage2_fixture_helpers import write_stage2_fixture
from manual_materials import Materials, MaterialError


class MaterialProjection(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.incoming = self.root/'incoming'
        self.packet = write_stage2_fixture(self.incoming)
        self.path = self.incoming/'packet.json'
        self.path.write_text(json.dumps(self.packet), encoding='utf-8')
        self.pin = hashlib.sha256(self.path.read_bytes()).hexdigest()
        self.store = Materials(self.root/'state', self.incoming, [])
        self.material = self.store.import_packet(dict(project_ref='project-test', packet_path=str(self.path),
            source_root=str(self.incoming), sha256=self.pin))

    def tearDown(self):
        self.temp.cleanup()

    def test_projection_retains_originals_and_no_authority(self):
        view = self.store.packet_view(self.material['id'])
        self.assertEqual(json.loads(view['packet_text']), self.packet)
        self.assertEqual(view['packet_file_sha256'], self.pin)
        self.assertFalse(view['formal_selection']['available'])
        self.assertFalse(view['research_generated'])
        self.assertEqual(len(view['cards']), len(self.packet['sources']))
        for card, source in zip(view['cards'], self.packet['sources']):
            self.assertEqual(card['saved_text'], (self.incoming/source['path']).read_text(encoding='utf-8'))

    def test_mutated_packet_and_source_fail_closed(self):
        source = self.incoming/self.packet['sources'][0]['path']
        original = source.read_bytes()
        source.write_bytes(original+b'changed')
        with self.assertRaises(ValueError): self.store.packet_view(self.material['id'])
        source.write_bytes(original)
        self.path.write_bytes(self.path.read_bytes()+b'\n')
        with self.assertRaises(MaterialError): self.store.packet_view(self.material['id'])

    def test_project_identity_and_path_containment(self):
        other = self.store.import_packet(dict(project_ref='project-other', packet_path=str(self.path),
            source_root=str(self.incoming), sha256=self.pin))
        self.assertNotEqual(other['id'], self.material['id'])
        self.assertEqual(self.store.packet_view(other['id'])['project_ref'], 'project-other')
        outside = self.root/'outside.json'
        outside.write_bytes(self.path.read_bytes())
        with self.assertRaises(MaterialError):
            self.store.import_packet(dict(project_ref='project-test', packet_path=str(outside),
                source_root=str(self.incoming), sha256=self.pin))

    def test_workflow_and_comparison_survive_restart(self):
        state = self.store.workflow(dict(id=self.material['id'], expected_sha256=self.pin))
        choice = dict(packet_sha256=self.pin, source_ids=['src-1'], candidates=[{'candidate_id':'candidate-1','version':1}])
        request = dict(id=self.material['id'], target_stage=2, revision=0, note='Local review only', selection=choice)
        saved = self.store.draft(request)
        self.assertEqual(self.store.draft(request), saved)
        fresh = Materials(self.root/'state', self.incoming, [])
        self.assertEqual(fresh.catalog()['drafts'], [saved])
        self.assertEqual(fresh.inspect(state['id'])['event_head'], state['event_head'])
        self.assertEqual(fresh.inspect(state['id'])['actions'], 0)
        self.assertFalse(saved['submitted_to_harness'])
        for wrong in ({**choice, 'packet_sha256':'0'*64}, {**choice, 'source_ids':['absent']},
                      {**choice, 'candidates':[{'candidate_id':'candidate-1','version':99}]}):
            with self.assertRaises(MaterialError): self.store.draft({**request,'revision':1,'selection':wrong})
        with self.assertRaises(MaterialError): self.store.draft({**request,'note':'conflict'})


if __name__ == '__main__':
    unittest.main(verbosity=2)
