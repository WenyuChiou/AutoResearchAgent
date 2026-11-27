import json
import secrets
import threading
import unittest
from urllib.request import Request,urlopen
from urllib.error import HTTPError
import test_harness_chat as fixtures
from harness_chat_http import install_chat
from research_workspace_native.project_host import ProjectHost
from research_workspace_native.project_intake import ProjectIntakeService
from research_workspace_native.http import token_authenticator


class ChatHTTP(unittest.TestCase):
    def test_actual_host_auth_context_send_and_persistent_recovery(self):
        fixture=fixtures.ChatTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        token=secrets.token_urlsafe(32)
        projects=ProjectIntakeService(fixture.root/'projects',authenticate=token_authenticator({token:'local-viewer'}))
        self.addCleanup(projects.close)
        host=ProjectHost(projects=projects,credential=token,files={},views=[],port=0)
        host.views=fixture.host.views
        service=install_chat(host,fixture.store,fixture.root/'chat',fixture.spec,rpc_factory=lambda record:fixtures.FakeRpc(record,action=dict(action='prepare_workflow',id=fixture.material['id'],note='')))
        thread=threading.Thread(target=host.serve_forever,daemon=True);thread.start()
        self.addCleanup(lambda:(service.close(),host.shutdown(),host.server_close(),thread.join(2)))
        url='http://127.0.0.1:'+str(host.server_address[1])
        def call(path,body=None,auth=True,origin=None):
            headers={'Origin':origin or url}
            if auth:headers['Authorization']='Bearer '+token
            if body is not None:headers['Content-Type']='application/json'
            request=Request(url+path,data=json.dumps(body).encode() if body is not None else None,headers=headers)
            try:
                with urlopen(request,timeout=5) as result:return result.status,json.load(result)
            except HTTPError as error:return error.code,json.load(error)
        state='/api/v9/chat/state?project=view%3Atest&stage=2'
        self.assertEqual(call(state,auth=False)[0],401)
        self.assertEqual(call(state,origin='https://untrusted.example')[0],403)
        self.assertEqual(call('/api/v9/chat/state?project=view%3Amissing&stage=2')[0],409)
        code,view=call(state);self.assertEqual(code,200);self.assertTrue(view['enabled'])
        body=dict(project_ref='view:test',stage=2,text='Prepare this material workflow',key='http-unique-request-0001',session_id=None)
        code,turn=call('/api/v9/chat/send',body);self.assertEqual(code,200,turn)
        pending=fixture.wait(service,turn,{'waiting'})['pending']
        code,_=call('/api/v9/chat/answer',dict(turn_id=turn['id'],request_id=pending['id'],request_sha256=pending['sha256'],value=True))
        self.assertEqual(code,200)
        result=fixture.finished(service,turn);self.assertEqual(result['status'],'completed',result)
        self.assertEqual(call('/api/v9/chat/send',body)[1]['id'],turn['id'])
        self.assertEqual(len(fixture.store.catalog()['operations']),1)
        self.assertEqual(call(state)[1]['turns'][0]['outputs'][0]['value']['status'],'prepared')
        self.assertEqual(call('/api/v9/chat/state?project=view%3Atest&stage=1')[1]['turns'],[])


if __name__=='__main__':unittest.main(verbosity=2)
