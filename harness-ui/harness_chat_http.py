"""Local authenticated UI routes; native execution never runs in HTTP threads."""
import json
from urllib.parse import parse_qs, urlsplit
from harness_chat import ChatService
from harness_chat_tools import HarnessChatTools


def install_chat(host, materials, root, spec=None, *, rpc_factory=None, connection_only=False, stage_registry=None, tool_adapter=None):
    from research_workspace_native.session_api import SessionApiError
    # Trusted host injection only. This does not activate a spec or weaken the
    # original authenticated HTTP, binding, lease or cumulative quota gates.
    if tool_adapter is not None:
        from local_reuse_chat_tools import LocalReuseChatTools
        if not isinstance(tool_adapter, LocalReuseChatTools):
            raise ValueError('chat-current-reader-adapter-required')
    chat_tools = tool_adapter if tool_adapter is not None else HarnessChatTools(host, materials, stage_registry)
    if spec and spec.get('_continuation'):
        from pathlib import Path
        root = Path(spec['_owner']).parent
    service = ChatService(root, chat_tools, spec,
                          rpc_factory=rpc_factory, recover_on_start=not connection_only)
    host.harness_chat = service
    parent = host.RequestHandlerClass

    class Handler(parent):
        def chat(self, method):
            try:
                credential, length = self._headers(method)
                if self.headers.get('Sec-Fetch-Site') not in (None, 'none', 'same-origin'):
                    raise SessionApiError('cross-site-rejected', 403)
                if self.server.authenticate(credential) is None:
                    raise SessionApiError('credential-rejected', 401)
                if method == 'GET':
                    if length:
                        raise SessionApiError('invalid-read-request', 400)
                    parsed = urlsplit(self.path)
                    query = parse_qs(parsed.query, strict_parsing=True)
                    if parsed.path != '/api/v9/chat/state' or set(query) != {'project', 'stage'} or any(len(x) != 1 for x in query.values()):
                        raise SessionApiError('unknown-chat-route', 404)
                    value = service.status(query['project'][0], int(query['stage'][0]))
                else:
                    if self.headers.get('Content-Type', '').lower() != 'application/json' or not 0 < length <= 20000:
                        raise SessionApiError('small-json-body-required', 415)
                    self._remaining()
                    raw = self.rfile.read(length)
                    if len(raw) != length:
                        raise SessionApiError('partial-body', 400)
                    body = json.loads(raw)
                    if not isinstance(body, dict):
                        raise SessionApiError('object-required', 400)
                    if self.path == '/api/v9/chat/send':
                        value = service.start(body)
                    elif self.path == '/api/v9/chat/answer':
                        value = service.answer(body)
                    elif self.path in {'/api/v9/chat/stop', '/api/v9/chat/reconcile'} and set(body) == {'turn_id'}:
                        value = (service.stop if self.path.endswith('/stop') else service.reconcile)(body['turn_id'])
                    else:
                        raise SessionApiError('unknown-chat-route', 404)
                return self._reply(200, value)
            except SessionApiError as exc:
                return self._reply(exc.status, {'error': exc.code})
            except (ValueError, KeyError, TypeError, OSError) as exc:
                return self._reply(409, {'error': str(exc), 'research_execution': False})

        def do_GET(self):
            if self.path.startswith('/api/v9/chat/'):
                return self.chat('GET')
            return super().do_GET()

        def do_POST(self):
            if self.path.startswith('/api/v9/chat/'):
                return self.chat('POST')
            return super().do_POST()

    host.RequestHandlerClass = Handler
    return service
