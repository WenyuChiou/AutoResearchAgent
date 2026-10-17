import json
from pathlib import Path
import tempfile
import unittest

from display_translations import load_translations


class TranslationInputTests(unittest.TestCase):
    def test_bound_bundle_and_rejected_duplicates(self):
        field = dict(candidate_id='synthetic', version=1, path='candidate.question',
                     source='original', translations={'en': 'English'})
        bundle = dict(schema_version=1, packets=[dict(packet_file_sha256='a' * 64, fields=[field])])
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'translations.json'
            path.write_text(json.dumps(bundle), encoding='utf-8')
            self.assertEqual(load_translations(path), bundle)
            bundle['packets'][0]['fields'].append(field)
            path.write_text(json.dumps(bundle), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'duplicate translated field'):
                load_translations(path)

    def test_array_translation_cannot_drop_source_items(self):
        bundle = dict(schema_version=1, packets=[dict(packet_file_sha256='a' * 64,
            fields=[dict(candidate_id='synthetic', version=1, path='candidate.limitations',
                         source=['one', 'two'], translations={'en': ['one']})])])
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'translations.json'
            path.write_text(json.dumps(bundle), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'membership differs'):
                load_translations(path)
