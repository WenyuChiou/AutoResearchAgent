"""Authenticated local native case routes; opaque refs only, no HTTP paths/argv."""
import hashlib
import json
import re
import secrets
import sqlite3
from contextlib import closing


PREFIX = '/api/v7/stage1/'

def public_status(row):
    fields = ('job_ref', 'case_ref', 'project_id', 'topic', 'spec_sha256', 'request_sha256',
              'status', 'native_terminal', 'native_status', 'delivery_status', 'delivery',
              'research_complete', 'events_cursor', 'events_sha256', 'thread_id', 'turn_id',
              'response_sha256', 'response_bytes', 'internal_model_calls', 'latest_native_event',
              'model', 'effort_requested', 'effort_effective')
    value = {key: row[key] for key in fields if key in row}
    for name in ('reason', 'delivery_error'):
        if row.get(name):
            value[name+'_sha256'] = hashlib.sha256(str(row[name]).encode('utf-8')).hexdigest()
    return value


def handle_native(handler, method):
    if not handler.path.startswith(PREFIX):
        return False
    try:
        token, length = handler._headers(method)
        if handler.headers.get('Sec-Fetch-Site') not in (None, 'none', 'same-origin'):
            return handler._reply(403, {'error': 'origin-or-host-rejected'}) or True
        if not secrets.compare_digest(token, handler.server.credential):
            return handler._reply(401, {'error': 'credential-rejected'}) or True
        service = getattr(handler.server, 'v7_native_stage1', None)
        if service is None:
            return handler._reply(200 if method == 'GET' and handler.path == PREFIX+'cases' else 409,
                {'kind': 'V7NativeStage1Catalogue', 'cases': [], 'status': 'unconfigured'}) or True
        tail = handler.path[len(PREFIX):]
        if method == 'GET':
            if length:
                return handler._reply(400, {'error': 'invalid-read-request'}) or True
            if tail == 'cases':
                rows = service.catalogue()
                for row in rows:
                    presentation = handler.server.v7_native_presentations[row['ref']]
                    if presentation['project_id'] != row['project_id']:
                        raise ValueError('native case association differs')
                    row['project_ref'] = presentation['project_ref']
                    # Pinned local service schema; GET reads an existing job only.
                    path = service.db_path
                    from native_stage1 import _no_link
                    _no_link(path)
                    with closing(sqlite3.connect(path.as_uri()+'?mode=ro', uri=True, timeout=.1)) as db:
                        found = db.execute('SELECT ref FROM jobs WHERE case_ref=? AND spec_sha=? ORDER BY rowid DESC LIMIT 1',
                                           (row['ref'], row['spec_sha256'])).fetchone()
                    row['last_job_ref'] = found[0] if found else None
                result = {'kind': 'V7NativeStage1Catalogue', 'cases': rows}
            else:
                match = re.fullmatch(r'jobs/([A-Za-z0-9_-]{1,100})(/result)?', tail)
                if not match:
                    return handler._reply(404, {'error': 'native-route-unavailable'}) or True
                state = service.status(match[1])
                result = (handler.server.v7_native_results.get(match[1], state.get('delivery'))
                          if match[2] else public_status(state))
                if result is None:
                    return handler._reply(404, {'error': 'native-result-not-delivered'}) or True
        elif method == 'POST' and tail == 'runs':
            if handler.headers.get('Content-Type', '').lower() != 'application/json' or not 1 <= length <= 2048:
                return handler._reply(400, {'error': 'native-body-rejected'}) or True
            raw = handler.rfile.read(length)
            if len(raw) != length:
                return handler._reply(400, {'error': 'native-body-incomplete'}) or True
            def pairs(items):
                value = {}
                for k, v in items:
                    if k in value:
                        raise ValueError('duplicate-key')
                    value[k] = v
                return value
            body = json.loads(raw, object_pairs_hook=pairs)
            if (not isinstance(body, dict) or set(body) != {'case_ref', 'key', 'spec_sha256', 'confirmed'}
                    or body['confirmed'] is not True):
                return handler._reply(400, {'error': 'native-confirmation-required'}) or True
            handler._remaining()
            result = public_status(service.start(body['case_ref'], body['key'], body['spec_sha256']))
        else:
            return handler._reply(405, {'error': 'method-rejected'}) or True
        handler._remaining()
        handler._reply(200, result)
    except Exception as error:
        # Service retains detailed native/provider failures privately. Never send paths.
        status = getattr(error, 'status', 409)
        if type(status) is not int or status not in (400, 401, 403, 404, 408, 409, 413):
            status = 409
        handler._reply(status, {'error': 'native-operation-rejected',
            'diagnostic_sha256': hashlib.sha256(str(error).encode('utf-8')).hexdigest()})
    return True
