"""Authenticated chat on the current UI, using a separately owned trial store.

The operator pins an explicit grant outside HTTP assets. The retained chat
service owns all reservations, native calls, turn recovery and tool dispatch.
This adapter does not implement or claim the missing Stage1 research executor.
"""
from pathlib import Path
from email.message import Message
import hashlib
import json
import secrets
import sys
import time

from local_reuse_chat_tools import LocalReuseChatTools

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
TRIAL_ROOT=ROOT/'UI/runtime/stage1-topic-trial-20261023'
PROJECT='view:stage1-a03-v3-d62'
TOPIC='U.S. population aging and household consumption in a two-way LLM-driven agent simulation'


class TrialTools(LocalReuseChatTools):
    def context(self, project, stage):
        if project != PROJECT or type(stage) is not int or stage != 1:
            raise ValueError('trial-scope-is-original-topic-stage1-only')
        value=super().context(project, stage)
        value['trial_scope']={'topic':TOPIC,'max_calls':5,'max_seconds':600,
            'research_execution_authorized':True,'research_executor_installed':False,
            'stop_after':'Stage1 delivery for user review','stage2_execution_authorized':False}
        return value

    def validate(self, session, args):
        self.context(session['project_ref'], session['stage'])
        return super().validate(session,args)

    def call(self,session,args):
        value=super().call(session,args)
        value['trial_scope']=self.context(session['project_ref'],session['stage'])['trial_scope']
        return value


def load_grant(registration):
    from harness_chat import load_config
    from native_stage1 import _private
    registration=Path(registration)
    expected=TRIAL_ROOT/'registration.json'
    if registration != expected or registration.resolve()!=expected or not registration.is_file():
        raise ValueError('current-chat-fixed-registration-required')
    _private(TRIAL_ROOT)
    entry=json.loads(registration.read_text(encoding='utf-8'))
    scope_path=TRIAL_ROOT/'authorization-scope.json'
    raw=scope_path.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=entry['scope_sha256']:
        raise ValueError('current-chat-scope-pin-differs')
    scope=json.loads(raw)
    if (scope.get('max_calls'),scope.get('max_seconds'),scope.get('topic'),scope.get('stage2_execution')) != (5,600,TOPIC,False):
        raise ValueError('current-chat-authorized-scope-differs')
    spec=load_config(TRIAL_ROOT/'operator-config.json',entry['config_sha256'])
    if (spec['max_calls'],spec['max_turns'],spec['max_seconds'],spec['previous_calls'],spec['previous_seconds'],spec['turn_seconds'])!=(5,5,600,0,0,120):
        raise ValueError('current-chat-independent-budget-differs')
    if Path(spec['budget_path'])!=TRIAL_ROOT/'chat/quota.sqlite3':
        raise ValueError('current-chat-budget-must-not-use-old-store')
    if spec['pins'].get(str(scope_path))!=entry['scope_sha256']:
        raise ValueError('current-chat-scope-not-bound')
    return spec,scope


def install_current_chat(server, portable, reuse, default_api, registration=None, *, test_spec=None, rpc_factory=None, test_root=None):
    # This verifies and loads only the fixed shipped Core dependency.
    binding=default_api.gateway._verify_backend()
    cli=Path(binding['plugin_root'])/'cli'
    if str(cli) not in sys.path:sys.path.insert(0,str(cli))
    native=ROOT/'UI/work/v7-functional-candidate'
    if str(native) not in sys.path:sys.path.insert(0,str(native))
    from harness_chat_http import install_chat
    from research_workspace_native.session_api import SessionApiError
    service_root=TRIAL_ROOT/'chat'
    scope=None;disabled=None
    if test_spec is not None:
        if rpc_factory is None or test_root is None:
            raise ValueError('isolated-chat-requires-explicit-rpc-and-root')
        service_root=Path(test_root);spec=test_spec
    elif registration:
        try:spec,scope=load_grant(registration)
        except (ValueError,OSError,KeyError) as exc:spec=None;disabled=str(exc)
    else:spec=None;disabled='current-chat-independent-grant-not-installed'
    if spec is not None and scope is not None:
        from harness_chat_rpc import Rpc
        from harness_chat_tools import encoded
        class AccountBoundRpc(Rpc):
            def request(self, method, params, timeout=10):
                value=super().request(method,params,timeout)
                if method=='account/read':
                    account=value.get('account') or {}
                    identity=account.get('accountId') or account.get('id') or account.get('email')
                    if not isinstance(identity,str) or not identity.strip():raise ValueError('trial-account-identity-missing')
                    pin=hashlib.sha256(encoded(dict(type=account.get('type'),identity=identity.strip().casefold()))).hexdigest()
                    if pin!=scope['account_identity_sha256']:raise ValueError('trial-account-binding-differs')
                return value
        rpc_factory=lambda record:AccountBoundRpc(spec,service_root,record)
    token=secrets.token_urlsafe(32)
    server.authenticate=lambda credential: 'local-viewer' if type(credential) is str and secrets.compare_digest(credential,token) else None
    parent=server.RequestHandlerClass
    class AuthHandler(parent):
        def _headers(self,method):
            lengths=self.headers.get_all('Content-Length',[])
            if len(lengths)>1 or (method=='POST' and len(lengths)!=1):raise SessionApiError('chat-length-header-invalid',400)
            length=int(lengths[0]) if lengths else 0
            if length<0 or length>20000:raise SessionApiError('chat-length-invalid',400)
            headers=Message()
            for k,v in self.headers.raw_items():headers[k]='0' if k.lower()=='content-length' else v
            rejected=portable.request_gate(headers,self.path,server.expected_host,server.expected_origin)
            if rejected:raise SessionApiError(rejected[1],rejected[0])
            if method=='POST' and self.headers.get('Origin')!=server.expected_origin:raise SessionApiError('chat-explicit-origin-required',403)
            auth=self.headers.get_all('Authorization',[])
            if len(auth)!=1 or not auth[0].startswith('Bearer '):raise SessionApiError('credential-required',401)
            self.connection.settimeout(5)
            return auth[0][7:],length
        def _remaining(self):return 5
        def _reply(self,status,value):
            if status>=400:self.close_connection=True
            return self.reply(status,json.dumps(value,ensure_ascii=False,allow_nan=False,separators=(',',':')).encode())
    server.RequestHandlerClass=AuthHandler
    service=install_chat(server,None,service_root,spec,rpc_factory=rpc_factory,tool_adapter=TrialTools(reuse))
    original_status=service.status
    def status(project,stage):
        value=original_status(project,stage)
        value.update(independent_trial=True,old_last_turn_reserved=True,registered_config_activated=spec is not None,
            research_authorized=scope is not None,research_executor_installed=False,trial_topic=TOPIC,
            stage1_full_delivery=False,formal_stage2_received=False)
        if disabled:value.update(disabled_reason=disabled,admission_blockers=[disabled])
        completed=[t for t in value['turns'] if t['status']=='completed' and t.get('native_turn_id') and t.get('outputs')]
        value['real_tool_round_trip_verified']=bool(completed)
        return value
    service.status=status
    old_connection=reuse.connection_status
    def connection():
        value=old_connection()
        state=status(PROJECT,1)
        value.update(chat_http_service_installed=True,authenticated_chat_host_installed=True,
            permit_loaded=spec is not None,budget_database_opened=True,old_budget_database_opened=False,
            can_send=state['local_admission_ready'],blockers=state['admission_blockers'],
            real_codex_round_trip_verified=state['real_tool_round_trip_verified'],
            live_codex_connected=bool(service.running),live_connection_observed=bool(state['turns']),
            codex_process_started=any(t.get('preflight') for t in state['turns']),
            independent_trial=dict(max_calls=5,max_seconds=600,reserved_calls=state['reserved_turns'],
                reserved_seconds=state['reserved_seconds'],remaining_calls=state['remaining_turns'],
                topic=TOPIC,authorized=scope is not None,research_executor_installed=False),
            model_calls=sum(bool(t.get('native_turn_id')) for t in state['turns']))
        return value
    reuse.connection_status=connection
    default_api.connection_status=connection
    server.current_chat_token=token
    server.current_chat_scope=scope
    return service
