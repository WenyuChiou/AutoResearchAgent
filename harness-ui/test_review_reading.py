"""Scoped review-reading counterexamples; mocks do not attest a delivery."""
import copy
import hashlib
import json
from unittest.mock import patch
import unittest

from manual_materials import Materials, MaterialError
from review_reading import load_review_sources
import test_materials as material_fixtures
import test_stage2_delivery as delivery_fixtures


class ReviewReading(unittest.TestCase):
    setUp = material_fixtures.MaterialProjection.setUp
    tearDown = material_fixtures.MaterialProjection.tearDown

    def bound_reviews(self):
        from stage2_common import canonical_hash
        root = self.incoming / 'delivery'
        root.mkdir()
        candidate = self.packet['candidates'][0]
        records = [dict(candidate_id=candidate['candidate_id'],
                        candidate_version=candidate['version'], role='challenger',
                        status='complete', review={'assessment': {
                            'candidate_id': candidate['candidate_id'],
                            'candidate_version': candidate['version'],
                            'packet_sha256': canonical_hash(self.packet),
                            'reason': 'Original review <script>', 'checks': {}}}, error=None)]
        data = json.dumps(records).encode()
        (root / 'review_results.json').write_bytes(data)
        manifest_pin = 'a' * 64
        self.store.review_sources = [dict(project_ref='project-test',
            packet_file_sha256=self.pin, delivery_root=str(root),
            delivery_manifest_sha256=manifest_pin)]
        validated = dict(input_packet=self.packet, manifest=dict(manifest_sha256=manifest_pin,
            snapshot_sha256='b' * 64, batch_sha256='c' * 64,
            recommendation_candidate_versions=[],
            delivery_status='draft-not-ready', files=[dict(path='review_results.json',
                size=len(data), sha256=hashlib.sha256(data).hexdigest())]),
            reconciliation={'candidates': [{'reconciliation': {'status': 'resolution-required'}}]})
        return root, records, validated

    def test_scoped_originals_and_no_authority(self):
        root, records, validated = self.bound_reviews()
        with patch('stage2_workflow.delivery.inspect_delivery', return_value=validated) as inspector:
            view = self.store.packet_view(self.material['id'])
            inspector.assert_called_once_with(root, 'a' * 64)
        reading = view['independent_reviews']
        self.assertEqual(json.loads(reading['reviews_text']), records)
        self.assertEqual(reading['resolution_counts'], {'resolution-required': 1})
        self.assertEqual(reading['delivery_status'], 'draft-not-ready')
        self.assertFalse(reading['formal_selection_available'])
        self.assertFalse(reading['stage3_execution_authorized'])
        self.assertFalse(reading['scientific_acceptance'])
        self.assertNotIn(str(root), json.dumps(view))

    def test_other_project_and_changed_review_are_not_adopted(self):
        root, _, validated = self.bound_reviews()
        other = self.store.import_packet(dict(project_ref='other-project',
            packet_path=str(self.path), source_root=str(self.incoming), sha256=self.pin))
        with patch('stage2_workflow.delivery.inspect_delivery') as inspector:
            self.assertNotIn('independent_reviews', self.store.packet_view(other['id']))
            inspector.assert_not_called()
        (root / 'review_results.json').write_bytes(b'[]')
        with patch('stage2_workflow.delivery.inspect_delivery', return_value=validated):
            with self.assertRaisesRegex(MaterialError, 'review-file-hash-differs'):
                self.store.packet_view(self.material['id'])

    def test_validated_other_packet_and_wrong_candidate_fail_closed(self):
        root, records, validated = self.bound_reviews()
        wrong = copy.deepcopy(validated)
        wrong['input_packet']['packet_id'] = 'other-packet'
        with patch('stage2_workflow.delivery.inspect_delivery', return_value=wrong):
            with self.assertRaisesRegex(MaterialError, 'review-packet-differs'):
                self.store.packet_view(self.material['id'])
        records[0]['candidate_version'] += 1
        data = json.dumps(records).encode()
        (root / 'review_results.json').write_bytes(data)
        validated['manifest']['files'][0].update(size=len(data), sha256=hashlib.sha256(data).hexdigest())
        with patch('stage2_workflow.delivery.inspect_delivery', return_value=validated):
            with self.assertRaisesRegex(MaterialError, 'review-candidate-role-differs'):
                self.store.packet_view(self.material['id'])

    def test_config_requires_pin_and_unique_project_packet(self):
        self.bound_reviews()
        path = self.root / 'review-sources.json'
        value = {'schema_version': 1, 'entries': self.store.review_sources}
        data = json.dumps(value).encode()
        path.write_bytes(data)
        self.assertEqual(load_review_sources(path, hashlib.sha256(data).hexdigest()), value['entries'])
        with self.assertRaisesRegex(MaterialError, 'review-config-hash-differs'):
            load_review_sources(path, 'b' * 64)
        value['entries'] = value['entries'] * 2
        data = json.dumps(value).encode()
        path.write_bytes(data)
        with self.assertRaisesRegex(MaterialError, 'review-source-duplicate'):
            load_review_sources(path, hashlib.sha256(data).hexdigest())

    def test_actual_delivery_inspector_preserves_reviews_without_authority(self):
        fixture = delivery_fixtures.Stage2DeliveryTests()
        fixture.setUp()
        try:
            reviews, resolutions = fixture._complete_inputs()
            root = self.incoming / 'inspected-delivery'
            manifest = fixture._build(root, reviews, resolutions)
            packet_path = root / 'input_packet.json'
            pin = hashlib.sha256(packet_path.read_bytes()).hexdigest()
            material = self.store.import_packet(dict(project_ref='project-test',
                packet_path=str(packet_path), source_root=str(root / 'sources'), sha256=pin))
            self.store.review_sources = [dict(project_ref='project-test',
                packet_file_sha256=pin, delivery_root=str(root),
                delivery_manifest_sha256=manifest['manifest_sha256'])]
            view = self.store.packet_view(material['id'])
            self.assertEqual(json.loads(view['independent_reviews']['reviews_text']), reviews)
            self.assertFalse(view['independent_reviews']['formal_selection_available'])
            self.assertFalse(view['independent_reviews']['stage3_execution_authorized'])
        finally:
            fixture.doCleanups()


if __name__ == '__main__':
    unittest.main(verbosity=2)
