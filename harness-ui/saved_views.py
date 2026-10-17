"""Adapt already verified Harness Atlas snapshots to V7; no research execution.

The upstream load_views reader has checked the caller-pinned manifest and every
served byte. This adapter reads only that immutable in-memory allowlist. It never
accepts a path, command, project alias, permission or source material from HTTP.
"""
import hashlib
import json
import re


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _canonical(value):
    # Exact Harness stage1_deliverable.common.canonical representation.
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def _object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError('duplicate saved-view JSON key')
        value[key] = item
    return value


def _decode(raw):
    value = json.loads(raw, object_pairs_hook=_object,
                       parse_constant=lambda value: (_ for _ in ()).throw(ValueError('nonfinite saved-view JSON')))
    _canonical(value)  # Also rejects numeric exponent overflow in any nested field.
    return value


def snapshot_saved_views(files, views):
    """Return read-only JSON assets without relabeling fixtures or old projects."""
    entries, assets = [], {}
    if len(views) > 16:
        raise ValueError('too many saved views')
    for view in views:
        ref = view['ref']
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', ref) or any(v['ref'] == ref for v in entries):
            raise ValueError('saved view reference differs')
        prefix = '/views/' + ref + '/'
        manifest_raw = files[prefix + 'view-manifest.json']
        if _sha(manifest_raw) != view['manifest_sha256']:
            raise ValueError('saved view manifest differs')
        manifest = _decode(manifest_raw)
        for name in ('atlas-data.js', 'atlas-binding.json', 'workspace-index.json'):
            if _sha(files[prefix + name]) != manifest['files'][name]:
                raise ValueError('saved view bytes differ')
        index_raw = files[prefix + 'workspace-index.json']
        index = _decode(index_raw)
        atlas_binding = _decode(files[prefix + 'atlas-binding.json'])
        raw = files[prefix + 'atlas-data.js']
        start, end = b'window.WORKSPACE_VIEW = ', b';\n'
        if not raw.startswith(start) or not raw.endswith(end):
            raise ValueError('saved view data envelope differs')
        payload_raw = raw[len(start):-len(end)]
        payload = _decode(payload_raw)
        if (_canonical(payload.get('index')) != _canonical(index) or payload.get('index_sha256') != _sha(index_raw)
                or view['index_sha256'] != _sha(index_raw)
                or index.get('project_id') != view['project_id']
                or atlas_binding.get('project_id') != view['project_id']
                or atlas_binding.get('index_sha256') != view['index_sha256']
                or atlas_binding.get('execution_authority') is not False):
            raise ValueError('saved view project/index binding differs')
        stage2 = payload.get('stage2')
        attachment_sha = _sha(_canonical(stage2)) if stage2 is not None else None
        if atlas_binding.get('stage2_attachment_sha256') != attachment_sha:
            raise ValueError('saved Stage2 attachment differs')
        if stage2 is not None:
            if (stage2.get('project_id') != view['project_id']
                    or stage2.get('stage1_index_sha256') != view['index_sha256']
                    or stage2.get('bridge_receipt', {}).get('project_id') != view['project_id']
                    or stage2.get('bridge_receipt', {}).get('stage1_index_sha256') != view['index_sha256']):
                raise ValueError('saved Stage2 project binding differs')
        if type(view['fixture']) is not bool:
            raise ValueError('saved fixture classification missing')
        binding = dict(kind='V7CanonicalSavedViewBinding', schema_version='1.0.0',
                       view_ref=ref, project_id=view['project_id'],
                       index_sha256=view['index_sha256'], manifest_sha256=view['manifest_sha256'],
                       payload_sha256=_sha(payload_raw), stage2_attachment_sha256=attachment_sha,
                       fixture=view['fixture'])
        route = '/v7-saved-runs/' + ref + '.json'
        assets[route] = _canonical(dict(kind='V7CanonicalSavedView', binding=binding,
                                       payload_json=payload_raw.decode('utf-8'),
                                       execution_authority=False))
        entries.append(dict(ref=ref, project_ref='view:' + ref, project_id=view['project_id'],
                            label=view['label'], fixture=view['fixture'],
                            index_sha256=view['index_sha256'], manifest_sha256=view['manifest_sha256'],
                            stage2_available=stage2 is not None, payload_url=route,
                            original_view_url=view['url'], execution_authority=False))
    assets['/v7-saved-runs.json'] = _canonical(dict(kind='V7CanonicalSavedViewList', views=entries,
                                                  execution_authority=False))
    return assets
