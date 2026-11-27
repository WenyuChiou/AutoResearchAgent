"""Versioned chat-only continuation; never renews a lease or resets a ledger.

The trusted embedding host supplies actual module locations and a permit
verifier. Neither a JSON boolean nor the CLI can substitute for that verifier.
Loading reads files only. Existing SQLite rows are checked by ChatService.
"""
import hashlib
import json
import math
from pathlib import Path
import re
import time
from copy import deepcopy

from harness_chat_binding import load_binding

LIMIT = 64 * 1024
PIN = re.compile(r'[0-9a-f]{64}\Z')
READ_ACTIONS = frozenset({'state', 'materials', 'read_material', 'read_saved_stage',
                          'read_paper', 'inspect_workflow', 'handoff_status'})
LEGACY_FIELDS = {'executable', 'config_path', 'model', 'effort', 'expires_at', 'max_turns',
                 'turn_seconds', 'previous_calls', 'previous_seconds', 'max_calls',
                 'max_seconds', 'pins', 'authorization', 'budget_path'}


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False,
                      separators=(',', ':')).encode()


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def read_json(path, pin):
    require(type(pin) is str and PIN.fullmatch(pin), 'chat-continuation-sha256-invalid')
    with Path(path).open('rb') as stream:
        raw = stream.read(LIMIT + 1)
    require(len(raw) <= LIMIT and digest(raw) == pin, 'chat-continuation-file-pin-differs')

    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, 'chat-continuation-duplicate-key')
            result[key] = value
        return result

    value = json.loads(raw, object_pairs_hook=unique,
                       parse_constant=lambda value: (_ for _ in ()).throw(ValueError('chat-continuation-nonfinite')))
    require(type(value) is dict, 'chat-continuation-object-required')
    return value


def _absolute(value):
    require(type(value) is str and Path(value).is_absolute(), 'chat-continuation-absolute-path-required')
    return Path(value).resolve()


def _integer(value):
    return type(value) is int and value >= 0


def load_continuation(path, pin, *, actual_modules, verify_permission=None, precheck_only=False):
    """Validate a new independent lease against the unchanged predecessor identity."""
    value = read_json(path, pin)
    require(set(value) == {'kind', 'version', 'predecessor', 'budget', 'binding', 'scope', 'authorization'},
            'chat-continuation-fields-invalid')
    require(value['kind'] == 'V9ChatContinuation' and type(value['version']) is int and value['version'] == 2,
            'chat-continuation-version-unsupported')
    predecessor, budget, binding, scope = (value[k] for k in ('predecessor', 'budget', 'binding', 'scope'))
    require(type(predecessor) is dict and set(predecessor) == {'path', 'sha256'}, 'chat-predecessor-fields-invalid')
    old_path = _absolute(predecessor['path'])
    old = read_json(old_path, predecessor['sha256'])
    require(set(old) == LEGACY_FIELDS, 'chat-predecessor-legacy-required')
    require(type(budget) is dict and set(budget) == {'path', 'owner', 'identity_pin', 'minimum_turns', 'minimum_seconds'},
            'chat-continuation-budget-fields-invalid')
    budget_path, owner = _absolute(budget['path']), _absolute(budget['owner'])
    require(budget_path == _absolute(old['budget_path']), 'chat-continuation-budget-path-differs')
    require(budget['identity_pin'] == predecessor['sha256'], 'chat-continuation-budget-identity-differs')
    require(budget_path.is_file() and owner.is_file(), 'chat-continuation-existing-stores-required')
    require(all(_integer(budget[k]) for k in ('minimum_turns', 'minimum_seconds')),
            'chat-continuation-counter-floor-invalid')
    require(type(binding) is dict and set(binding) == {'path', 'sha256'}, 'chat-continuation-binding-fields-invalid')
    fields = {'id', 'issued_at', 'expires_at', 'projects', 'stages', 'actions', 'model', 'effort',
              'expected_account_sha256', 'model_messages_authorized', 'research_execution',
              'max_turns', 'turn_seconds', 'previous_calls', 'previous_seconds', 'max_calls', 'max_seconds'}
    require(type(scope) is dict and set(scope) == fields, 'chat-continuation-scope-fields-invalid')
    require(type(scope['id']) is str and 12 <= len(scope['id']) <= 128, 'chat-continuation-scope-id-required')
    require(all(type(scope[k]) in (int, float) and math.isfinite(scope[k]) for k in ('issued_at', 'expires_at'))
            and 0 < scope['issued_at'] < scope['expires_at'], 'chat-continuation-time-invalid')
    require(scope['issued_at'] <= time.time() < scope['expires_at'], 'chat-operator-lease-expired')
    require(type(scope['projects']) is list and 1 <= len(scope['projects']) <= 32
            and all(type(x) is str and 0 < len(x) <= 200 for x in scope['projects'])
            and len(set(scope['projects'])) == len(scope['projects']), 'chat-continuation-projects-invalid')
    require(type(scope['stages']) is list and scope['stages']
            and all(type(x) is int and 1 <= x <= 6 for x in scope['stages'])
            and len(set(scope['stages'])) == len(scope['stages']), 'chat-continuation-stages-invalid')
    require(type(scope['actions']) is list and scope['actions']
            and all(type(x) is str and x in READ_ACTIONS for x in scope['actions'])
            and len(set(scope['actions'])) == len(scope['actions']), 'chat-continuation-read-actions-only')
    require(scope['model_messages_authorized'] is True and scope['research_execution'] is False,
            'chat-continuation-chat-only-permit-required')
    require(type(scope['model']) is str and scope['model'] and type(scope['effort']) is str and scope['effort'],
            'chat-continuation-model-required')
    require(type(scope['expected_account_sha256']) is str and PIN.fullmatch(scope['expected_account_sha256']),
            'chat-continuation-current-account-binding-required')
    require(all(_integer(scope[k]) for k in ('max_turns', 'turn_seconds', 'previous_calls', 'previous_seconds',
                                           'max_calls', 'max_seconds')), 'chat-budget-invalid')
    require(1 <= scope['max_turns'] <= 100 and 1 <= scope['turn_seconds'] <= 120, 'chat-batch-bounds-invalid')
    require(all(_integer(old.get(k)) and scope[k] == old[k] for k in ('previous_calls', 'previous_seconds')),
            'chat-continuation-predecessor-counts-differ')
    require(scope['max_turns'] >= budget['minimum_turns']
            and scope['max_calls'] >= scope['previous_calls'] + budget['minimum_turns']
            and scope['max_seconds'] >= scope['previous_seconds'] + budget['minimum_seconds'],
            'chat-continuation-limits-below-history')
    require(type(value['authorization']) is dict and set(value['authorization']) == {'ref'}
            and type(value['authorization']['ref']) is str and 1 <= len(value['authorization']['ref']) <= 200,
            'chat-continuation-authorization-reference-required')
    manifest = read_json(_absolute(binding['path']), binding['sha256'])
    modules = actual_modules() if callable(actual_modules) else actual_modules
    runtime = load_binding(binding['path'], binding['sha256'], modules,
                           old['executable'], old['config_path'])
    require(callable(verify_permission) or precheck_only, 'chat-continuation-permit-verifier-required')
    spec = dict(scope, executable=manifest['executable']['path'], config_path=manifest['config']['path'],
                budget_path=str(budget_path), pins={}, _path=str(_absolute(str(path))), _pin=pin,
                _continuation=True, _precheck_only=bool(precheck_only), _raw_contract=value,
                _old_path=str(old_path), _old_sha256=predecessor['sha256'],
                _budget_identity=budget['identity_pin'], _owner=str(owner),
                _minimum_turns=budget['minimum_turns'], _minimum_seconds=budget['minimum_seconds'],
                _runtime_binding=runtime, _actual_modules=actual_modules,
                _verify_permission=verify_permission)
    if not precheck_only:
        verify_continuation(spec)
    return spec


def verify_continuation(spec):
    require(spec.get('_precheck_only') is False, 'chat-continuation-precheck-not-activation')
    current = read_json(spec['_path'], spec['_pin'])
    require(current == spec['_raw_contract'], 'chat-continuation-contract-changed')
    require(Path(spec['_old_path']).resolve() == _absolute(current['predecessor']['path'])
            and spec['_old_sha256'] == current['predecessor']['sha256'], 'chat-continuation-predecessor-mutated')
    read_json(spec['_old_path'], spec['_old_sha256'])
    require(current['scope']['issued_at'] <= time.time() < current['scope']['expires_at'], 'chat-operator-lease-expired')
    # Runtime dictionaries are internal, but never let a caller alter a flattened gate.
    require(all(spec.get(key) == val for key, val in current['scope'].items()), 'chat-continuation-scope-mutated')
    require(spec.get('_budget_identity') == current['budget']['identity_pin']
            and Path(spec['budget_path']).resolve() == _absolute(current['budget']['path'])
            and Path(spec['_owner']).resolve() == _absolute(current['budget']['owner'])
            and spec['_minimum_turns'] == current['budget']['minimum_turns']
            and spec['_minimum_seconds'] == current['budget']['minimum_seconds'],
            'chat-continuation-budget-mutated')
    require(spec['executable'] == read_json(current['binding']['path'], current['binding']['sha256'])['executable']['path']
            and spec['config_path'] == read_json(current['binding']['path'], current['binding']['sha256'])['config']['path'],
            'chat-continuation-runtime-mutated')
    modules = spec['_actual_modules']() if callable(spec['_actual_modules']) else spec['_actual_modules']
    require(Path(spec['_runtime_binding'].manifest_path).resolve() == _absolute(current['binding']['path'])
            and spec['_runtime_binding'].manifest_sha256 == current['binding']['sha256'],
            'chat-continuation-binding-object-mutated')
    spec['_runtime_binding'].verify(actual_modules=modules, expected_executable=spec['executable'],
                                   expected_config=spec['config_path'])
    verifier = spec.get('_verify_permission')
    require(callable(verifier), 'chat-continuation-permit-verifier-required')
    request = {'kind': 'V9ChatContinuationPermissionCheck', 'contract_sha256': spec['_pin'],
               'contract': current, 'research_execution': False}
    expected_request_sha256 = digest(encoded(request))
    receipt = verifier(deepcopy(request))
    require(type(receipt) is dict and set(receipt) == {'kind', 'request_sha256', 'model_messages_authorized', 'research_execution'}
            and receipt['kind'] == 'V9VerifiedChatOnlyPermit'
            and receipt['request_sha256'] == expected_request_sha256
            and receipt['model_messages_authorized'] is True and receipt['research_execution'] is False,
            'chat-continuation-permit-binding-differs')


def verify_budget(spec, row, owner):
    """Validate an existing row inside the caller's atomic reservation transaction."""
    require(row is not None, 'chat-continuation-existing-budget-row-required')
    pin, turns, seconds, actual_owner = row
    require(pin == spec['_budget_identity'], 'chat-budget-config-differs')
    require(actual_owner == str(Path(owner).resolve()) == spec['_owner'], 'chat-budget-owned-by-another-store')
    require(_integer(turns) and _integer(seconds), 'chat-continuation-ledger-counts-invalid')
    require(turns >= spec['_minimum_turns'] and seconds >= spec['_minimum_seconds'], 'chat-continuation-ledger-regressed')
    return turns, seconds


def verify_request_scope(spec, project, stage, action=None):
    require(project in spec['projects'] and type(stage) is int and stage in spec['stages'],
            'chat-continuation-project-stage-not-authorized')
    if action is not None:
        require(action in spec['actions'], 'chat-continuation-action-not-authorized')
