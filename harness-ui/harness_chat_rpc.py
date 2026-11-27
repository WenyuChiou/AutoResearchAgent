"""Codex app-server conversation transport owned by the local Harness adapter."""
import json
import os
from pathlib import Path
import time
import tomllib
import hashlib
import re
from harness_chat_tools import encoded, require


class Rpc:
    def __init__(self, spec, cwd, record, channel_factory=None):
        from native_stage1 import _ProcessChannel
        config = tomllib.loads(Path(spec['config_path']).read_text(encoding='utf-8-sig'))
        require(all(isinstance(n, str) and re.fullmatch(r'[A-Za-z0-9_-]+', n)
                    for n in config.get('mcp_servers', {})), 'chat-mcp-name-unsafe-for-process-override')
        self.config = {'web_search': 'disabled', 'model_reasoning_effort': spec['effort'],
                       'memories.use_memories': False, 'memories.generate_memories': False,
                       'agents.enabled': False, 'tools.experimental_request_user_input.enabled': True,
                       **{f'features.{n}': False for n in (
                           'shell_tool', 'unified_exec', 'apply_patch_freeform', 'apps', 'plugins',
                           'hooks', 'multi_agent', 'enable_mcp_apps', 'code_mode', 'search_tool')},
                       **{f'mcp_servers.{n}.enabled': False for n in config.get('mcp_servers', {})}}
        # Overrides are process-local; the user's actual Codex configuration is never edited.
        argv = [spec['executable'], 'app-server', '--listen', 'stdio://']
        for key, value in self.config.items():
            argv += ['-c', key + '=' + json.dumps(value)]
        self.channel = (channel_factory() if channel_factory else _ProcessChannel(
            argv, cwd, dict(os.environ, CODEX_HOME=str(Path(spec['config_path']).parent))))
        self.record, self.buffer, self.ident = record, b'', 0
        self.backlog = []

    def send(self, frame):
        data = encoded(frame) + b'\n'
        require(len(data) <= 1024 * 1024, 'chat-rpc-frame-too-large')
        self.record('outgoing', frame)
        require(self.channel.write(data, 2) == len(data), 'chat-rpc-partial-write')

    def read(self, timeout=1):
        deadline = time.monotonic() + timeout
        while b'\n' not in self.buffer:
            chunk = self.channel.read(65536, max(0, deadline - time.monotonic()))
            require(chunk, 'chat-rpc-eof')
            self.buffer += chunk
            require(len(self.buffer) <= 1024 * 1024, 'chat-rpc-frame-too-large')
        raw, self.buffer = self.buffer.split(b'\n', 1)
        def unique(pairs):
            value = {}
            for key, item in pairs:
                require(key not in value, 'chat-rpc-duplicate-key')
                value[key] = item
            return value
        value = json.loads(raw, object_pairs_hook=unique)
        require(isinstance(value, dict), 'chat-rpc-frame-invalid')
        encoded(value)
        self.record('incoming', value)
        return value

    def request(self, method, params, timeout=10):
        self.ident += 1
        identity = 'chat-rpc-' + str(self.ident)
        self.send(dict(id=identity, method=method, params=params))
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            value = self.read(max(0, deadline - time.monotonic()))
            if value.get('id') == identity and 'method' not in value:
                require('result' in value, 'chat-rpc-rejected:' + method + ':' + str(value.get('error', {}).get('message', ''))[:400])
                return value['result']
            self.backlog.append(value)
        raise TimeoutError('chat-rpc-reply-unknown:' + method)

    def next(self):
        return self.backlog.pop(0) if self.backlog else self.read(.3)

    def close(self):
        return self.channel.close()


def preflight(rpc, spec):
    rpc.request('initialize', {'clientInfo': {'name': 'ara-v9-harness-chat', 'title': 'V9 Harness chat', 'version': '1'},
                               'capabilities': {'experimentalApi': True}})
    rpc.send({'method': 'initialized'})
    account = rpc.request('account/read', {'refreshToken': False})
    require(account.get('account') is not None, 'codex-login-required')
    if spec.get('_continuation'):
        observed = account['account']
        identity = observed.get('accountId') or observed.get('id') or observed.get('email')
        require(isinstance(identity, str) and identity.strip(), 'chat-native-account-identity-missing')
        canonical = {'type': observed.get('type'), 'identity': identity.strip().casefold()}
        require(hashlib.sha256(encoded(canonical)).hexdigest() == spec['expected_account_sha256'],
                'chat-native-account-binding-differs')
    limits = rpc.request('account/rateLimits/read', {})
    windows = []
    buckets = limits.get('rateLimitsByLimitId') or {'codex': limits.get('rateLimits', {})}
    for bucket in buckets.values():
        for key in ('primary', 'secondary'):
            window = (bucket or {}).get(key)
            if window and type(window.get('usedPercent')) in (int, float):
                windows.append(100 - window['usedPercent'])
    require(windows, 'codex-quota-unknown')
    require(min(windows) >= 15, 'codex-quota-below-15')
    models = rpc.request('model/list', {'includeHidden': True})
    model = next((m for m in models.get('data', []) if m.get('id') == spec['model'] or m.get('model') == spec['model']), None)
    require(model is not None, 'codex-requested-model-unavailable')
    efforts = [e.get('reasoningEffort') for e in model.get('supportedReasoningEfforts', [])]
    require(spec['effort'] in efforts, 'codex-requested-effort-unavailable')
    return dict(connected=True, model=spec['model'], effort=spec['effort'], remaining_percent=min(windows),
                other_windows='Unknown when absent', research_execution=False)
