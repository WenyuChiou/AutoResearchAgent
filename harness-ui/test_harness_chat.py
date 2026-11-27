"""Real Harness operations with deterministic native-protocol injection; no model."""
import json
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest

HERE=Path(__file__).resolve().parent
UI=HERE.parents[1]
REPO=UI.parent/'harness_building/worktrees/v9-team-launch-20261017'
sys.path.insert(0,str(REPO/'harness-ui'))
sys.path.insert(0,str(REPO/'plugins/auto-research-agent/cli'))
sys.path.insert(0,str(HERE))
from harness_chat import ChatService
from harness_chat_tools import HarnessChatTools
from manual_materials import Materials
from test_materials import write_stage2_fixture


class FakeRpc:
    config={}
    def __init__(self,record,action=None,wrong_binding=False,question=False,duplicate=False):
        self.record,self.action,self.wrong,self.question,self.duplicate=record,action,wrong_binding,question,duplicate
        self.sent,self.methods,self.events=[],[],[]
        self.resumed=None

    def request(self,method,params,timeout=10):
        self.methods.append(method)
        if method=='initialize':return {}
        if method=='account/read':return {'account':{'type':'chatgpt'}}
        if method=='account/rateLimits/read':return {'rateLimits':{'primary':{'usedPercent':20}}}
        if method=='model/list':return {'data':[{'id':'gpt-6.1-sol','supportedReasoningEfforts':[{'reasoningEffort':'high'}]}]}
        if method in ('thread/start','thread/resume'):
            self.resumed=params.get('threadId')
            return {'thread':{'id':self.resumed or 'native-thread-test'},'model':'gpt-6.1-sol','reasoningEffort':'high',
                    'approvalPolicy':'on-request','sandbox':{'type':'readOnly'}}
        if method=='turn/start':
            base={'threadId':'wrong-thread' if self.wrong else 'native-thread-test','turnId':'native-turn-test'}
            if self.action:
                frame={'id':'request-1','method':'item/tool/call','params':dict(base,tool='harness',namespace=None,callId='call-1',arguments=self.action)}
                self.events.append(frame)
                if self.duplicate:self.events.append(frame)
            elif self.question:
                self.events.append({'id':'question-1','method':'item/tool/requestUserInput','params':dict(base,questions=[dict(id='scope',question='Which scope?',options=[])])})
            else:self.events += self.terminal()
            return {'turn':{'id':'native-turn-test'}}
        if method=='turn/interrupt':self.events=self.terminal('interrupted');return {}
        if method=='thread/read':return {'thread':{'id':'native-thread-test','turns':[dict(id='native-turn-test',status='completed',items=[dict(type='agentMessage',text='Recovered final')])]}}
        raise AssertionError(method)

    def terminal(self,status='completed'):
        return [dict(method='item/completed',params=dict(threadId='native-thread-test',turnId='native-turn-test',item=dict(type='agentMessage',text='Harness response saved.'))),
                dict(method='turn/completed',params=dict(threadId='native-thread-test',turn=dict(id='native-turn-test',status=status)))]

    def send(self,frame):
        self.sent.append(frame)
        if 'result' in frame and not any(x.get('method')=='turn/completed' for x in self.events):self.events+=self.terminal()
    def next(self):
        if self.events:return self.events.pop(0)
        time.sleep(.01);raise TimeoutError()
    def close(self):return {'leader_stopped':True}


class ChatTests(unittest.TestCase):
    def setUp(self):
        base=UI/'t/v9-chat-20261017';base.mkdir(parents=True,exist_ok=True)
        self.tmp=tempfile.TemporaryDirectory(dir=base);self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name); incoming=self.root/'incoming';incoming.mkdir()
        self.store=Materials(self.root/'materials',incoming,[])
        value=write_stage2_fixture(incoming)
        packet,source_root=incoming/'packet.json',incoming
        packet.write_text(json.dumps(value),encoding='utf-8')
        import hashlib
        self.material=self.store.import_packet(dict(project_ref='view:test',packet_path=str(packet),source_root=str(source_root),sha256=hashlib.sha256(packet.read_bytes()).hexdigest()))
        self.host=SimpleNamespace(views=[dict(ref='test',manifest_sha256='a'*64),dict(ref='other',manifest_sha256='b'*64)])
        self.tools=HarnessChatTools(self.host,self.store)
        self.spec=dict(expires_at=time.time()+120,max_turns=3,turn_seconds=10,previous_calls=5,previous_seconds=840,
                       max_calls=8,max_seconds=1200,pins={},model='gpt-6.1-sol',effort='high',budget_path=str(self.root/'quota.sqlite3'))
        self.rpcs=[]

    def service(self,**kwargs):
        def factory(record):
            rpc=FakeRpc(record,**kwargs);self.rpcs.append(rpc);return rpc
        service=ChatService(self.root/'chat',self.tools,self.spec,rpc_factory=factory)
        self.addCleanup(service.close)
        return service

    def start(self,service,key='unique-request-0001',session=None):
        return service.start(dict(project_ref='view:test',stage=2,text='Inspect my material',key=key,session_id=session))

    def wait(self,service,turn,status):
        deadline=time.monotonic()+8
        while time.monotonic()<deadline:
            row=service.get('turns',turn['id'])
            if row['status'] in status:return row
            time.sleep(.02)
        self.fail(str(row))

    def finished(self,service,turn):
        row=self.wait(service,turn,{'completed','failed','interrupted','unknown'})
        worker=service.running.get(turn['id'],{}).get('thread')
        if worker:worker.join(2)
        return row

    def test_real_harness_tool_persistent_thread_and_stage_isolation(self):
        service=self.service(action=dict(action='read_material',id=self.material['id'],note=''))
        first=self.finished(service,self.start(service));self.assertEqual(first['status'],'completed',first)
        self.assertEqual(first['outputs'][0]['value']['material_id'],self.material['id'])
        self.assertFalse(first['outputs'][0]['value']['research_generated'])
        second=self.finished(service,self.start(service,'unique-request-0002',first['session_id']))
        self.assertEqual(second['thread_id'],first['thread_id']);self.assertEqual(self.rpcs[-1].resumed,first['thread_id'])
        self.assertEqual(len(service.status('view:test',1)['turns']),0)
        restored=self.service()
        self.assertEqual(len(restored.status('view:test',2)['turns']),2)
        self.assertFalse(restored.running)

    def test_approval_then_actual_harness_prepare_and_duplicate_call(self):
        service=self.service(action=dict(action='prepare_workflow',id=self.material['id'],note=''),duplicate=True)
        first=self.start(service);waiting=self.wait(service,first,{'waiting','unknown'});self.assertEqual(waiting['status'],'waiting',waiting)
        self.assertEqual(self.store.catalog()['operations'],[])
        pending=waiting['pending'];body=dict(turn_id=first['id'],request_id=pending['id'],request_sha256=pending['sha256'],value=True)
        with self.assertRaisesRegex(ValueError,'binding'):service.answer(dict(body,request_sha256='wrong'))
        service.answer(body)
        result=self.finished(service,first);self.assertEqual(result['status'],'completed',result)
        self.assertEqual(len(result['outputs']),1);self.assertEqual(len(self.store.catalog()['operations']),1)
        with self.assertRaisesRegex(ValueError,'not-live'):service.answer(body)
        repeat=self.start(service);self.assertEqual(repeat['id'],first['id']);self.assertEqual(len(self.rpcs),1)

    def test_decline_does_not_write(self):
        service=self.service(action=dict(action='save_review',id=self.material['id'],note='Review note'))
        turn=self.start(service);p=self.wait(service,turn,{'waiting'})['pending']
        service.answer(dict(turn_id=turn['id'],request_id=p['id'],request_sha256=p['sha256'],value=False))
        self.assertEqual(self.finished(service,turn)['status'],'completed')
        self.assertEqual(self.store.catalog()['drafts'],[])

    def test_native_question_and_interrupt(self):
        service=self.service(question=True);turn=self.start(service);p=self.wait(service,turn,{'waiting'})['pending']
        service.answer(dict(turn_id=turn['id'],request_id=p['id'],request_sha256=p['sha256'],value={'scope':'Current topic only'}))
        self.assertEqual(self.finished(service,turn)['status'],'completed')
        next_turn=self.start(service,'unique-request-0002',turn['session_id']);self.wait(service,next_turn,{'waiting'})
        service.stop(next_turn['id']);self.assertEqual(self.finished(service,next_turn)['status'],'interrupted')

    def test_wrong_native_binding_held_and_readonly_recovery(self):
        service=self.service(action=dict(action='state',id='',note=''),wrong_binding=True)
        turn=self.finished(service,self.start(service));self.assertEqual(turn['status'],'unknown')
        with self.assertRaisesRegex(ValueError,'unresolved'):self.start(service,'unique-request-0002')
        result=service.reconcile(turn['id']);self.assertEqual(result['status'],'completed')
        self.assertNotIn('turn/start',self.rpcs[-1].methods)
        self.assertNotIn('thread/resume',self.rpcs[-1].methods)
        self.assertEqual(service.status('view:test',2)['reserved_turns'],1)

    def test_other_project_material_and_expired_lease(self):
        context=self.tools.context('view:other',2);context['project_pin']='b'*64
        with self.assertRaisesRegex(ValueError,'binding'):self.tools.call(context,dict(action='read_material',id=self.material['id'],note=''))
        self.spec['expires_at']=time.time()-1
        service=self.service()
        with self.assertRaisesRegex(ValueError,'lease-expired'):self.start(service)

    def test_shared_budget_cannot_be_reset_by_new_material_root(self):
        service=self.service()
        self.finished(service,self.start(service))
        with self.assertRaisesRegex(ValueError,'another-store'):
            ChatService(self.root/'other-chat',self.tools,self.spec,rpc_factory=lambda r:FakeRpc(r))
        self.assertEqual(service.status('view:test',2)['reserved_turns'],1)

    def test_changed_confirmation_state_does_not_mutate(self):
        service=self.service(action=dict(action='save_review',id=self.material['id'],note='Proposed note'))
        turn=self.start(service);p=self.wait(service,turn,{'waiting'})['pending']
        self.store.draft(dict(id=self.material['id'],target_stage=2,note='Newer human note',revision=0))
        service.answer(dict(turn_id=turn['id'],request_id=p['id'],request_sha256=p['sha256'],value=True))
        self.assertEqual(self.finished(service,turn)['status'],'completed')
        self.assertEqual(self.store.catalog()['drafts'][0]['note'],'Newer human note')
        self.assertFalse(self.rpcs[-1].sent[-1]['result']['success'])

    def test_two_service_instances_cannot_admit_concurrent_turns(self):
        from concurrent.futures import ThreadPoolExecutor
        import threading
        first,second=self.service(question=True),self.service(question=True)
        gate=threading.Barrier(2)
        def submit(service,key):
            gate.wait()
            try:return self.start(service,key)
            except ValueError as exc:return str(exc)
        with ThreadPoolExecutor(2) as pool:
            a=pool.submit(submit,first,'concurrent-key-0001');b=pool.submit(submit,second,'concurrent-key-0002')
            results=[a.result(),b.result()]
        self.assertEqual(sum(isinstance(x,dict) for x in results),1,results)
        self.assertIn('chat-unresolved-turn-must-be-reconciled',results)
        winner=next(x for x in results if isinstance(x,dict))
        owner=first if winner['id'] in first.running else second
        self.wait(owner,winner,{'waiting'});owner.stop(winner['id']);self.finished(owner,winner)
        self.assertEqual(owner.status('view:test',2)['reserved_turns'],1)


if __name__=='__main__':unittest.main(verbosity=2)
