"""Optional local reading translations; never written into Harness artifacts."""
import json
from pathlib import Path


def load_translations(path=None):
    if path is None:
        return {'schema_version': 1, 'packets': []}
    data = Path(path).read_bytes()
    if len(data) > 2 * 1024 * 1024:
        raise ValueError('display translations exceed 2 MiB')
    value = json.loads(data)
    if not isinstance(value, dict) or value.get('schema_version') != 1 or not isinstance(value.get('packets'), list):
        raise ValueError('invalid display translation bundle')
    if len(value['packets']) > 100:
        raise ValueError('too many translation packets')
    seen = set()
    for packet in value['packets']:
        sha = packet.get('packet_file_sha256', '')
        if len(sha) != 64 or any(c not in '0123456789abcdef' for c in sha) or sha in seen:
            raise ValueError('invalid or duplicate translation packet identity')
        seen.add(sha)
        fields = packet.get('fields')
        if not isinstance(fields, list) or len(fields) > 2000:
            raise ValueError('invalid translated fields')
        keys = set()
        for field in fields:
            key = (field.get('candidate_id'), field.get('version'), field.get('path'))
            if not isinstance(key[0], str) or type(key[1]) is not int or not isinstance(key[2], str) or key in keys:
                raise ValueError('invalid or duplicate translated field')
            keys.add(key)
            source, translations = field.get('source'), field.get('translations')
            def text_shape(item):
                return isinstance(item, str) or isinstance(item, list) and all(isinstance(x, str) for x in item)
            if not text_shape(source) or not isinstance(translations, dict) or not translations:
                raise ValueError('invalid translation text')
            for locale, text in translations.items():
                if locale not in ('zh', 'en', 'tw') or not text_shape(text) or type(text) is not type(source):
                    raise ValueError('invalid translation locale or shape')
                if isinstance(source, list) and len(source) != len(text):
                    raise ValueError('translation list membership differs')
    return value


def translation_script(value):
    return ('const n9TranslationBundle=' + json.dumps(value, ensure_ascii=False, separators=(',', ':')) + ';\n').encode('utf-8')
