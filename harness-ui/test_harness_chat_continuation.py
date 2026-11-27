"""Isolated synthetic mirrors and in-memory protocol only. Never real Codex."""
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import time
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.append(str(REPO / 'plugins/auto-research-agent/cli'))
from harness_chat import ChatService, check_config, load_config
from harness_chat_continuation import digest, encoded, load_continuation
from harness_chat_stages import StageContextRegistry, EVIDENCE_KIND, EVIDENCE_VERSION
from harness_chat_tools import HarnessChatTools
BINDING = {'project_ref': 'project-fixture', 'project_id': 'pid-fixture', 'input_version': 1, 'brief_sha256': 'a' * 64}


def identity(path):
    return {'path': str(path), 'sha256': digest(Path(path).read_bytes())}


class MemoryRpc:
    """Deterministic protocol transcript, not an external model or native process."""
    config = {}
    def __init__(self, record, account='fixture@example.invalid', wrong_turn=False, tool_action=None):
        self.methods, self.events = [], []
        self.account, self.wrong_turn, self.tool_action = account, wrong_turn, tool_action
    def request(self, method, params, timeout=10):
        self.methods.append(method)
        if method == 'initialize': return {}
        if method == 'account/read': return {'account': {'type': 'chatgpt', 'email': self.account}}
        if method == 'account/rateLimits/read': return {'rateLimits': {'primary': {'usedPercent': 20}}}
        if method == 'model/list': return {'data': [{'id': 'fixture-model', 'supportedReasoningEfforts': [{'reasoningEffort': 'high'}]}]}
        if method in ('thread/start', 'thread/resume'):
            return {'thread': {'id': 'fixture-thread'}, 'model': 'fixture-model', 'reasoningEffort': 'high',
                    'approvalPolicy': 'on-request', 'sandbox': {'type': 'readOnly'}}
        if method == 'turn/start':
            if self.tool_action:
                self.events.append({'id': 'fixture-call', 'method': 'item/tool/call', 'params': {
                    'threadId': 'fixture-thread', 'turnId': 'fixture-turn', 'tool': 'harness', 'callId': 'fixture-call',
                    'arguments': {'action': self.tool_action, 'id': '', 'note': ''}}})
            self.events.append({'method': 'turn/completed', 'params': {'threadId': 'fixture-thread',
                'turn': {'id': 'wrong' if self.wrong_turn else 'fixture-turn', 'status': 'completed'}}})
            return {'turn': {'id': 'fixture-turn'}}
        raise AssertionError('unexpected protocol method: ' + method)
    def send(self, frame): pass
    def next(self): return self.events.pop(0)
    def close(self): return {'synthetic_channel_closed': True}


class ContinuationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='continuation-fixture-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.chat = self.root / 'original-owner'
        self.chat.mkdir()
        self.owner = self.chat / 'conversations.sqlite3'
        self.budget = self.root / 'old-budget.sqlite3'
        for path in (self.root / 'codex.exe', self.root / 'config.toml', self.root / 'module.py'):
            path.write_text('fixture-only-not-executable', encoding='utf-8')
        self.modules = {'fixture_module': str(self.root / 'module.py')}
        self.manifest = {'kind': 'V9ChatRuntimeBinding', 'version': 1,
                         'executable': identity(self.root / 'codex.exe'), 'config': identity(self.root / 'config.toml'),
                         'modules': {'fixture_module': identity(self.root / 'module.py')}}
        self.binding_path = self.root / 'binding.json'
        self.binding_path.write_bytes(encoded(self.manifest))
        old = {'executable': str(self.root / 'codex.exe'), 'config_path': str(self.root / 'config.toml'),
               'model': 'old-model', 'effort': 'high', 'expires_at': 1, 'max_turns': 3, 'turn_seconds': 120,
               'previous_calls': 5, 'previous_seconds': 840, 'max_calls': 8, 'max_seconds': 1200,
               'pins': {}, 'authorization': 'fixture-historical-only', 'budget_path': str(self.budget)}
        self.old_path = self.root / 'old-operator.json'
        self.old_path.write_bytes(encoded(old)); self.old_pin = digest(self.old_path.read_bytes())
        db = sqlite3.connect(self.owner)
        db.executescript('CREATE TABLE sessions(id TEXT PRIMARY KEY,body TEXT NOT NULL);'
                         'CREATE TABLE turns(id TEXT PRIMARY KEY,session_id TEXT,body TEXT NOT NULL);'
                         'CREATE TABLE events(seq INTEGER PRIMARY KEY,turn_id TEXT,body TEXT NOT NULL);')
        for index in range(2):
            row = {'id': 'historical-' + str(index), 'session_id': 'historical-session', 'status': 'completed',
                   'stage': 2, 'project_ref': 'project-fixture', 'response': 'synthetic historical metadata', 'pending': None}
            db.execute('INSERT INTO turns VALUES(?,?,?)', (row['id'], row['session_id'], json.dumps(row)))
        db.commit(); db.close()
        db = sqlite3.connect(self.budget)
        db.execute('CREATE TABLE budget(id INTEGER PRIMARY KEY,pin TEXT,owner TEXT,turns INTEGER,seconds INTEGER)')
        db.execute('INSERT INTO budget VALUES(1,?,?,2,240)', (self.old_pin, str(self.owner.resolve())))
        db.commit(); db.close()
        scope = {'id': 'fixture-only-chat-lease-0001', 'issued_at': time.time() - 5, 'expires_at': time.time() + 120,
                 'principal': 'local-viewer', 'bindings': [BINDING], 'money_cap_usd': None,
                 'stages': list(range(1, 7)), 'actions': ['state', 'materials', 'read_material'],
                 'model': 'fixture-model', 'effort': 'high',
                 'expected_account_sha256': digest(encoded({'type': 'chatgpt', 'identity': 'fixture@example.invalid'})),
                 'model_messages_authorized': True, 'research_execution': False,
                 'max_turns': 3, 'turn_seconds': 120, 'previous_calls': 5, 'previous_seconds': 840,
                 'max_calls': 8, 'max_seconds': 1200}
        self.contract = {'kind': 'V9ChatContinuation', 'version': 3,
                         'predecessor': identity(self.old_path),
                         'budget': {'path': str(self.budget), 'owner': str(self.owner), 'identity_pin': self.old_pin,
                                    'minimum_turns': 2, 'minimum_seconds': 240},
                         'binding': identity(self.binding_path), 'scope': scope,
                         'authorization': {'ref': 'synthetic-test-only-not-human-approval'}}
        self.contract_path = self.root / 'FIXTURE-DO-NOT-ACTIVATE.json'
        self.seal()
        self.registry = StageContextRegistry()
        for stage in range(3, 7):
            self.registry.register(stage, self.evidence, provider_id='fixture-context', implementation_sha256='b' * 64)
        self.materials = SimpleNamespace(catalog=lambda: {'materials': [], 'available_deliveries': [], 'drafts': [], 'operations': []})
        self.project = {'project_ref': 'project-fixture', 'project_id': 'pid-fixture', 'input_version': 1,
                        'brief_sha256': 'a' * 64, 'brief': {'original_description': 'fixture topic'}}
        projects = SimpleNamespace(read=lambda credential, ref: dict(self.project))
        self.tools = HarnessChatTools(SimpleNamespace(credential='fixture-token', projects=projects), self.materials, self.registry)
        self.rpcs = []
        # No test can accidentally start native or reach a non-local endpoint.
        self.addCleanup(patch.stopall)
        patch('subprocess.Popen', side_effect=AssertionError('native-process-forbidden')).start()
        patch('socket.create_connection', side_effect=AssertionError('network-forbidden')).start()

    @staticmethod
    def evidence(project, stage, pin):
        return {'kind': EVIDENCE_KIND, 'version': EVIDENCE_VERSION, 'project_ref': project, 'stage': stage,
                'project_pin': pin, 'context': {'fixture': True}, 'binding': {'manifest_sha256': 'c' * 64}, 'missing': []}

    def seal(self):
        self.contract_path.write_bytes(encoded(self.contract))
        self.pin = digest(self.contract_path.read_bytes())
        self.approved = deepcopy(self.contract)

    def verifier(self, request):
        self.assertEqual(request['contract'], self.approved)
        return {'kind': 'V9VerifiedChatOnlyPermit', 'request_sha256': digest(encoded(request)),
                'model_messages_authorized': True, 'research_execution': False}

    def spec(self, **kwargs):
        return load_config(self.contract_path, self.pin, actual_modules=self.modules,
                           verify_permission=kwargs.pop('verify_permission', self.verifier), **kwargs)

    def service(self, **kwargs):
        def factory(record):
            rpc = MemoryRpc(record, **kwargs); self.rpcs.append(rpc); return rpc
        service = ChatService(self.chat, self.tools, self.spec(), rpc_factory=factory)
        self.addCleanup(service.close)
        return service

    def row(self):
        db = sqlite3.connect(self.budget)
        try: return db.execute('SELECT pin,owner,turns,seconds FROM budget WHERE id=1').fetchone()
        finally: db.close()

    def send(self, service, stage=2, key='fixture-request-key-0001'):
        return service.start({'project_ref': 'project-fixture', 'stage': stage, 'text': 'Synthetic protocol fixture only',
                              'key': key, 'session_id': None, 'input_version': 1, 'brief_sha256': 'a' * 64}, 'local-viewer')

    def finished(self, service, turn):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            row = service.get('turns', turn['id'])
            if row['status'] in {'completed', 'failed', 'interrupted', 'unknown'}:
                worker = service.running.get(turn['id'], {}).get('thread')
                if worker: worker.join(2)
                return row
            time.sleep(.01)
        self.fail('synthetic fixture did not finish')

    def test_cumulative_reservation_and_original_identity_preserved(self):
        service = self.service()
        turn = self.send(service)
        self.assertEqual(self.finished(service, turn)['status'], 'completed')
        self.assertEqual(self.row(), (self.old_pin, str(self.owner.resolve()), 3, 360))
        self.assertEqual(self.send(service)['id'], turn['id'])
        self.assertEqual(len(self.rpcs), 1)
        with self.assertRaisesRegex(ValueError, 'cumulative-budget-exhausted'):
            self.send(service, key='fixture-request-key-0002')
        self.assertEqual(self.old_path.read_bytes(), encoded(json.loads(self.old_path.read_bytes())))

    def test_second_lease_does_not_reset(self):
        service = self.service(); self.finished(service, self.send(service))
        self.contract['scope']['id'] = 'fixture-only-chat-lease-0002'; self.seal()
        renewed = self.service()
        self.assertIn('chat-cumulative-budget-exhausted', renewed.status('project-fixture', 2, 'local-viewer')['admission_blockers'])
        self.assertEqual(self.row()[2:], (3, 360))

    def test_cleared_test_session_cannot_resume_or_consume_budget(self):
        service = self.service()
        context = self.tools.context('project-fixture', 2)
        session = dict(id='cleared-test', project_ref='project-fixture', stage=2,
                       project_pin=context['project_pin'], thread_id='archived-test-thread',
                       content_cleared=True)
        with service.db() as db: service.put(db, 'sessions', session)
        before = self.row()
        with self.assertRaisesRegex(ValueError, 'content-cleared-open-new-session'):
            service.start(dict(project_ref='project-fixture', stage=2, text='fixture', key='cleared-test-new-key',
                               session_id=session['id'], input_version=1, brief_sha256='a' * 64), 'local-viewer')
        self.assertEqual(self.row(), before)
        self.assertEqual(self.rpcs, [])

    def test_same_interface_all_six_stages_with_explicit_readonly_providers(self):
        # Independent fixture per stage is not new production budget allocation.
        for stage in range(1, 7):
            with self.subTest(stage=stage):
                self.contract['scope']['max_turns'] = 8
                self.contract['scope']['max_calls'] = 13
                self.contract['scope']['max_seconds'] = 2000
                self.seal()
                service = self.service()
                result = self.finished(service, self.send(service, stage, 'fixture-stage-key-' + str(stage)))
                self.assertEqual(result['status'], 'completed', result)
                self.assertEqual(result['stage'], stage)
                self.assertFalse(service.status('project-fixture', stage, 'local-viewer')['research_execution'])
        self.assertEqual(self.row()[2:], (8, 960))

    def test_future_stage_missing_provider_rejects_before_reservation(self):
        service = self.service(); service.tools.stage_registry = None
        before = self.budget.read_bytes()
        for stage in range(3, 7):
            with self.assertRaisesRegex(ValueError, 'provider-unregistered'): self.send(service, stage)
        self.assertEqual(self.budget.read_bytes(), before)
        self.assertFalse(self.rpcs)

    def test_missing_callback_and_precheck_never_activate(self):
        with self.assertRaisesRegex(ValueError, 'permit-verifier-required'): self.spec(verify_permission=None)
        spec = self.spec(verify_permission=None, precheck_only=True)
        with self.assertRaisesRegex(ValueError, 'precheck-not-activation'):
            ChatService(self.chat, self.tools, spec, rpc_factory=lambda r: self.fail('no rpc'))

    def test_boolean_or_mutated_callback_receipt_rejected(self):
        with self.assertRaisesRegex(ValueError, 'permit-binding-differs'): self.spec(verify_permission=lambda req: True)
        def wrong(req):
            req['contract']['scope']['max_calls'] = 100
            return {'kind': 'V9VerifiedChatOnlyPermit', 'request_sha256': digest(encoded(req)),
                    'model_messages_authorized': True, 'research_execution': False}
        with self.assertRaisesRegex(ValueError, 'permit-binding-differs'): self.spec(verify_permission=wrong)

    def test_changed_config_or_actual_source_rejected(self):
        spec = self.spec()
        (self.root / 'module.py').write_text('changed', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'binding-file-pin-differs'): check_config(spec)

    def test_owner_change_and_empty_budget_rejected_without_creation(self):
        spec = self.spec(); before = self.budget.read_bytes()
        with self.assertRaisesRegex(ValueError, 'another-store'):
            ChatService(self.root / 'other-owner', self.tools, spec)
        self.assertFalse((self.root / 'other-owner').exists())
        self.assertEqual(before, self.budget.read_bytes())
        db = sqlite3.connect(self.budget); db.execute('DELETE FROM budget'); db.commit(); db.close()
        with self.assertRaisesRegex(ValueError, 'existing-budget-row-required'): self.service()
        self.assertIsNone(self.row())

    def test_predecessor_counts_cannot_be_lowered(self):
        self.contract['scope']['previous_calls'] = 0; self.seal()
        with self.assertRaisesRegex(ValueError, 'predecessor-counts-differ'): self.spec()

    def test_regressed_counter_floor_does_not_repair_or_refund(self):
        self.contract['budget']['minimum_turns'] = 3; self.seal()
        before = self.budget.read_bytes()
        with self.assertRaisesRegex(ValueError, 'ledger-regressed'): self.service()
        self.assertEqual(self.budget.read_bytes(), before)

    def test_scope_stage_and_write_tool_are_not_implicitly_permitted(self):
        self.contract['scope']['stages'] = [1]; self.seal()
        service = self.service()
        with self.assertRaisesRegex(ValueError, 'project-stage-not-authorized'): self.send(service, 2)
        self.assertEqual(self.row()[2:], (2, 240))
        self.contract['scope']['actions'].append('prepare_advice'); self.seal()
        with self.assertRaisesRegex(ValueError, 'read-actions-only'): self.spec()

    def test_wrong_account_fails_before_synthetic_thread_or_turn(self):
        service = self.service(account='someone-else@example.invalid')
        result = self.finished(service, self.send(service))
        self.assertEqual(result['status'], 'failed')
        self.assertIn('account-binding-differs', result['error'])
        self.assertNotIn('thread/start', self.rpcs[0].methods)
        # Reservation remains; a failed preflight is never refunded.
        self.assertEqual(self.row()[2:], (3, 360))

    def test_unconfirmed_terminal_preserves_reservation_and_blocks_replay(self):
        service = self.service(wrong_turn=True)
        self.assertEqual(self.finished(service, self.send(service))['status'], 'unknown')
        with self.assertRaisesRegex(ValueError, 'unresolved'): self.send(service, key='fixture-request-key-0002')
        with self.assertRaisesRegex(ValueError, 'reconcile-not-authorized'): service.reconcile('historical-0')
        self.assertEqual(self.row()[2:], (3, 360))

    def test_internal_ancestry_and_scope_mutation_rejected(self):
        spec = self.spec(); spec['max_calls'] = 100
        with self.assertRaisesRegex(ValueError, 'scope-mutated'): check_config(spec)
        spec = self.spec(); spec['_old_sha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'predecessor-mutated'): check_config(spec)

    def test_internal_binding_object_replacement_rejected(self):
        from dataclasses import replace
        spec = self.spec()
        spec['_runtime_binding'] = replace(spec['_runtime_binding'], manifest_sha256='0' * 64)
        with self.assertRaisesRegex(ValueError, 'binding-object-mutated'): check_config(spec)

    def test_unpermitted_tool_never_reaches_harness_writer(self):
        service = self.service(tool_action='save_review')
        result = self.finished(service, self.send(service))
        self.assertEqual(result['status'], 'unknown')
        self.assertIn('action-not-authorized', result['error'])
        self.assertEqual(result['outputs'], [])

    def test_two_v2_services_cannot_reserve_same_last_allowance(self):
        from concurrent.futures import ThreadPoolExecutor
        first, second = self.service(), self.service()
        barrier = threading.Barrier(2)

        def submit(service, key):
            barrier.wait()
            try: return self.send(service, key=key)
            except ValueError as error: return str(error)

        with ThreadPoolExecutor(2) as pool:
            a = pool.submit(submit, first, 'fixture-parallel-key-0001')
            b = pool.submit(submit, second, 'fixture-parallel-key-0002')
            values = [a.result(), b.result()]
        winners = [item for item in values if isinstance(item, dict)]
        self.assertEqual(len(winners), 1, values)
        owner = first if winners[0]['id'] in first.running else second
        # A fast in-memory worker may already have completed and left running.
        self.finished(owner, winners[0])
        self.assertEqual(self.row()[2:], (3, 360))

    def test_duplicate_json_and_bool_integer_rejected(self):
        raw = encoded(self.contract)
        bad = raw[:-1] + b',"version":2}'
        self.contract_path.write_bytes(bad)
        with self.assertRaisesRegex(ValueError, 'duplicate-key'):
            load_continuation(self.contract_path, digest(bad), actual_modules=self.modules, precheck_only=True)
        self.contract['scope']['max_calls'] = True; self.seal()
        with self.assertRaisesRegex(ValueError, 'budget-invalid'): self.spec()


if __name__ == '__main__': unittest.main(verbosity=2)
