"""Authenticated material routes; execution remains owned by Harness."""
import json
import re
from urllib.parse import quote
from manual_materials import Materials

def install_materials(host, projects, root, incoming, entries=()):
    from research_workspace_native.session_api import SessionApiError
    store=Materials(root,incoming,list(entries))
    host.materials=store
    inherited=host.RequestHandlerClass

    class V9Handler(inherited):
        def manual(self, method):
            try:
                credential,length=self._headers(method)
                if self.headers.get('Sec-Fetch-Site') not in (None,'none','same-origin'):
                    raise SessionApiError('cross-site-rejected',403)
                if self.server.authenticate(credential) is None:
                    raise SessionApiError('credential-rejected',401)
                if method=='GET':
                    if length: raise SessionApiError('invalid-read-request',400)
                    if self.path=='/api/v9/materials':
                        return self._reply(200,store.catalog())
                    match=re.fullmatch(r'/api/v9/packets/((?:packet|delivery)-[0-9a-f]{32})',self.path)
                    if match: return self._reply(200,store.packet_view(match[1]))
                    match=re.fullmatch(r'/api/v9/workflows/(workflow-[0-9a-f]{32})',self.path)
                    if match: return self._reply(200,store.inspect(match[1]))
                    match=re.fullmatch(r'/api/v9/files/(file-[0-9a-f]{32})',self.path)
                    if match:
                        item=store._get('materials',match[1]); data=store.file_bytes(match[1])
                        self.close_connection=True;self.send_response(200)
                        self.send_header('Content-Type','application/octet-stream')
                        self.send_header('Content-Disposition',"attachment; filename*=UTF-8''"+quote(item['name'],safe=''))
                        self.send_header('X-Content-Type-Options','nosniff')
                        self.send_header('Content-Length',str(len(data)))
                        self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(data);return
                    raise SessionApiError('unknown-material-route',404)
                if self.headers.get('Content-Type','').lower()!='application/json' or not length:
                    raise SessionApiError('json-body-required',415)
                self._remaining(); data=self.rfile.read(length)
                if len(data)!=length: raise SessionApiError('partial-body',400)
                body=json.loads(data)
                if not isinstance(body,dict): raise SessionApiError('object-required',400)
                operation=self.path.removeprefix('/api/v9/')
                methods={'register':store.register_delivery,'upload/start':store.begin_upload,
                    'upload/chunk':store.upload_chunk,'upload/finish':store.finish_upload,
                    'import-packet':store.import_packet,'workflow/prepare':store.workflow,'draft':store.draft}
                if operation not in methods: raise SessionApiError('unknown-material-operation',404)
                if operation in {'register','upload/start','import-packet'}:
                    ref=body.get('project_ref')
                    if not isinstance(ref,str): raise SessionApiError('project-required',400)
                    if ref.startswith('view:'):
                        if ref[5:] not in {v['ref'] for v in host.views}: raise SessionApiError('saved-project-unknown',409)
                    else:
                        projects.read(credential,ref)
                self._remaining()
                value=methods[operation](body)
                return self._reply(200,value)
            except SessionApiError as error:
                return self._reply(error.status,{'error':error.code})
            except (ValueError,KeyError,TypeError,OSError) as error:
                return self._reply(409,{'error':str(error),'execution_authorized':False})
        def do_GET(self):
            if self.path.startswith('/api/v9/'): return self.manual('GET')
            return super().do_GET()
        def do_POST(self):
            if self.path.startswith('/api/v9/'): return self.manual('POST')
            return super().do_POST()

    host.RequestHandlerClass=V9Handler
    return store
