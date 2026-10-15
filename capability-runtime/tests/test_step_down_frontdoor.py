"""Real production MCP stdio -> configured Python -> Owner/Intent/Watchdog/Resident.

Only the native Bridge endpoint is synthetic. These tests do not run Minecraft,
establish collision/physics correctness or access an installed runtime.
"""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import sys
import threading
import unittest
from unittest.mock import patch
import base_watchdog
import test_capability_ownership as owners
from resident_controller.capability_snapshot import validate_scoped_witness
from resident_controller.transport import BridgeError
from step_down_fixture import fixture,terminal,PROFILE
from mining_collect.collect.collect_fixture import collect_fixture
from mining_collect.collect.movement_fixture import movement_fixture

ROOT=Path(__file__).resolve().parents[2]


class Endpoint(owners.CombatEndpoint):
    mode_name='success'
    def __init__(self):
        super().__init__();self.mode_name=type(self).mode_name;self.landed=False;self.fixture_error=None
        self.facts=fixture()[0]['result']['scoped_native_preflight']['facts']
    def snapshot(self):
        value=super().snapshot();f=deepcopy(self.facts)
        value['player'].update(inventory=[{'slot':r['slot'],**r['item']} for r in f['inventory'][:36]],
            inventory_total=36,inventory_truncated=False,mainhand=deepcopy(f['equipment']['mainhand']),
            offhand=deepcopy(f['equipment']['offhand']))
        value['menu']={k:deepcopy(v) for k,v in f['menu'].items() if k!='slot_permissions'}
        value['movement_budget']={'schema_version':1,'status':'armed' if self.mode_name=='meter_armed' else 'unarmed',
            'position_hook_seen':True,'move_hook_seen':True}
        value['scoped_native_preflight']={'version':'scoped-native-preflight/1','same_callback_capture_validate_admit':True,
            'private_singleplayer_only':True,'capability_guard_schema_version':1,
            'profiles':{} if self.mode_name=='profile_missing' else {PROFILE:['follow_path']},'guarded_actions':['follow_path']}
        if self.mode_name=='flat_regression':
            value['scoped_native_preflight']['profiles']['movement-flat-observed-v2']=['follow_path']
        if self.landed:
            value['player'].update(x=1.5,y=64. if self.mode_name=='flat_regression' else 63.,z=.5,on_ground=self.mode_name!='not_grounded')
            if self.mode_name=='moving':value['player']['velocity']['x']=.01
        return value
    def request(self,method,path,body=None):
        if path=='/control/scoped-action':
            self.posts.append((path,deepcopy(body)));intent,scope=body['intent'],body['preflight']
            if scope['profile']=='movement-flat-observed-v2':
                native,_,_,_=movement_fixture(intent,scope)
                w=native['result']['scoped_native_preflight'];m=w['facts']['movement'];m['profile']=scope['profile']
                for k in ('entity_limit','live_other_entities','entity_scope'):m.pop(k)
                m['entity_guard']=collect_fixture(False)[0]['result']['scoped_native_preflight']['facts']['movement']['entity_guard']
                m['entity_guard'].update(source_tick=w['source_tick'],source_nano=w['source_nano'])
            else:native,_,_,_=fixture(intent,scope)
            native.update(action_schema_version=1,ok=True,status='running',reason='synthetic_descent_admitted',server_confirmed=False)
            self.action=native
            try:validate_scoped_witness(native,scope,intent['action_id'],intent)
            except ValueError as exc:self.fixture_error=str(exc);raise
            if self.mode_name=='lost':raise BridgeError('synthetic_lost_descent_submit',uncertain=True)
            return deepcopy(self.action)
        if path.startswith('/control/action/status') and self.action['status']=='running':
            if self.mode_name=='cancel':return deepcopy(self.action)
            self.landed=True;self.action.update(status='succeeded',reason='synthetic_descent_landed')
            self.action['result']['input_release_confirmed']=True
            if self.mode_name!='flat_regression':self.action['result']['step_down']=terminal(self.action)
            if self.mode_name=='forged_terminal':self.action['result']['step_down']['profile']='movement-flat-observed-v2'
            return deepcopy(self.action)
        if path=='/control/action/cancel':
            self.posts.append((path,deepcopy(body)));self.action.update(status='cancelled',reason='cancel_requested')
            self.action['result']['input_release_confirmed']=True
            self.action['result']['step_down']=terminal(self.action,landed=False)
            return deepcopy(self.action)
        return super().request(method,path,body)


class StepDownFrontdoorTests(unittest.TestCase):
    until=owners.ActualGatewayOwnershipTests.until
    mode='success'
    def setUp(self):
        self.mode=self._testMethodName.removeprefix('test_')
        run=base_watchdog.run
        def request_only(*args,**kwargs):kwargs['execution_policy']='request_only';return run(*args,**kwargs)
        with patch.object(Endpoint,'mode_name',self.mode),patch.object(owners,'CombatEndpoint',Endpoint),patch.object(base_watchdog,'run',request_only):
            owners.ActualGatewayOwnershipTests.setUp(self)
        executable=Path(sys.executable).resolve()
        config={'schema_version':1,'python_executable':str(executable),'python_sha256':hashlib.sha256(executable.read_bytes()).hexdigest(),
            'control_directory':str(self.root/'watchdog'),'journal_directory':str(self.root/'toolbox'),
            'runtime_journal_directory':str(self.root/'runtime')}
        config_path=self.root/'operator.json';config_path.write_text(json.dumps(config))
        env=dict(os.environ,MINECLIENT_TOOLBOX_CONFIG=str(config_path),NODE_ENV='test',
            MINECLIENT_BRIDGE_TEST_NAMESPACE='self-test-stepdown-'+self.mode)
        self.stderr=(self.root/'mcp-stderr.log').open('w+')
        self.process=subprocess.Popen([shutil.which('node'),str(ROOT/'client-mod/mcp/mineclient-bridge-mcp.mjs')],
            stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=self.stderr,text=True,env=env,cwd=ROOT)
        self.replies=queue.Queue();self.sequence=0
        self.transcript=[]
        def receive():
            for line in self.process.stdout:
                try:self.replies.put(json.loads(line))
                except ValueError:self.replies.put({'invalid':line})
        self.reader=threading.Thread(target=receive,daemon=True);self.reader.start()
    def tearDown(self):
        try:
            if getattr(self,'process',None):
                self.process.stdin.close();self.process.wait(timeout=15);self.reader.join(timeout=2)
                self.process.stdout.close();self.stderr.seek(0);stderr=self.stderr.read();self.stderr.close()
                destination=os.environ.get('MDC_STEP_DOWN_TEST_RESULTS')
                if destination:
                    output=Path(destination)/self.mode;output.mkdir(parents=True,exist_ok=True)
                    (output/'frontdoor-transcript.json').write_text(json.dumps(self.transcript,indent=2))
                    (output/'native-endpoint-proof.json').write_text(json.dumps({'synthetic_native':True,'posts':self.bridge.posts,
                        'fixture_error':self.bridge.fixture_error,'mcp_exit_code':self.process.returncode,
                        'capability_lease':self.client.session().get('capability_lease')},indent=2))
                    for name in ('runtime','toolbox'):
                        if (self.root/name).is_dir():shutil.copytree(self.root/name,output/name,dirs_exist_ok=True)
                self.assertEqual(self.process.returncode,2 if self.mode in ('lost','forged_terminal') else 0,stderr)
        finally:
            owners.ActualGatewayOwnershipTests.tearDown(self)
    def call(self,name,args):
        self.sequence+=1;identity=self.sequence
        request={'jsonrpc':'2.0','id':identity,'method':'tools/call','params':{'name':name,'arguments':args}}
        self.process.stdin.write(json.dumps(request)+'\n');self.process.stdin.flush()
        response=self.replies.get(timeout=20)
        self.transcript.append({'request':request,'response':response})
        self.assertEqual(response.get('id'),identity,response)
        self.assertNotIn('error',response,response)
        return json.loads(response['result']['content'][0]['text'])
    def submit(self,**changes):
        catalog=self.call('mdc_catalog',{'api_version':'mdc.toolbox/1','capability_ids':['navigate_step_down','navigate_local','navigate_loaded'],'detail':'contracts'})
        desc=catalog['runtime_binding_availability'];self.catalog=catalog
        args={'api_version':'mdc.toolbox/1','operation':'submit','request_id':'descent-'+self.mode,
            'session_ref':desc['session_ref'],'expected_context_ref':desc['context_ref'],
            'capability':'navigate_step_down','capability_version':1,'arguments':{'goal':{'x':1,'y':63,'z':0},'min_health':12},
            'policy':{'version':1,'execution_mode':'request_only','reactions':'stop'},
            'budgets':{'deadline_seconds':60,'max_actions':2,'max_observations':64,'cleanup_reserve_actions':1,'reflex_reserve_actions':0},'wait_ms':10000}
        args.update(changes);return self.call('mdc_job',args)
    def finish(self,result):
        while result.get('state') in ('accepted','running','stopping'):
            result=self.call('mdc_job',{'api_version':'mdc.toolbox/1','operation':'status',
                'session_ref':result['session_ref'],'job_id':result['job_id'],'wait_ms':10000})
        return result
    def posts(self):return [b for p,b in self.bridge.posts if p=='/control/scoped-action']
    def test_success(self):
        result=self.finish(self.submit());self.assertEqual(result['state'],'succeeded',(self.bridge.fixture_error,result))
        self.assertEqual(result['cleanup_certainty'],'confirmed');self.assertEqual(result['effect_certainty'],'known')
        self.assertEqual(len(self.posts()),1);body=self.posts()[0]
        self.assertEqual(body['preflight']['profile'],PROFILE);self.assertEqual(body['intent']['waypoints'],[{'x':1.5,'y':63,'z':.5,'jump':False}])
        self.assertIsNone(self.client.session()['capability_lease'])
        self.assertFalse([p for p,b in self.bridge.posts if p=='/control/action'])
        unavailable={e['capability']:e for e in self.catalog['capabilities']}
        self.assertFalse(unavailable['navigate_loaded']['runtime_available']);self.assertFalse(unavailable['navigate_local']['runtime_available'])
    def test_lost(self):
        result=self.finish(self.submit());self.assertEqual(result['state'],'unknown',result);self.assertEqual(len(self.posts()),1)
        self.assertFalse([p for p,b in self.bridge.posts if p=='/control/action/cancel'])
        again=self.call('mdc_job',{'api_version':'mdc.toolbox/1','operation':'status','session_ref':result['session_ref'],'job_id':result['job_id']})
        self.assertEqual(again['state'],'unknown');self.assertEqual(len(self.posts()),1)
    def test_flat_regression(self):
        result=self.finish(self.submit(capability='navigate_local',arguments={'goal':{'x':1,'y':64,'z':0}}))
        self.assertEqual(result['state'],'succeeded',(self.bridge.fixture_error,result));self.assertEqual(len(self.posts()),1)
        self.assertEqual(self.posts()[0]['preflight']['profile'],'movement-flat-observed-v2')
        self.assertNotIn('step_down',self.bridge.action['result']['scoped_native_preflight']['facts'])
        available={e['capability']:e['runtime_available'] for e in self.catalog['capabilities']}
        self.assertTrue(available['navigate_step_down']);self.assertTrue(available['navigate_local'])
    def test_cancel(self):
        result=self.submit(wait_ms=0);self.until(lambda:bool(self.posts()))
        result=self.call('mdc_job',{'api_version':'mdc.toolbox/1','operation':'cancel','session_ref':result['session_ref'],
            'job_id':result['job_id'],'cancel_request_id':'descent-cancel-once','wait_ms':10000})
        result=self.finish(result);self.assertEqual(result['state'],'cancelled',result);self.assertEqual(len(self.posts()),1)
        cancels=[b for p,b in self.bridge.posts if p=='/control/action/cancel'];self.assertEqual(len(cancels),1)
        self.assertEqual(cancels[0]['action_id'],self.posts()[0]['intent']['action_id'])
    def test_profile_missing(self):
        result=self.submit();self.assertEqual(result['error']['code'],'capability_unavailable',result);self.assertFalse(self.posts())
    def test_meter_armed(self):
        result=self.finish(self.submit());self.assertEqual(result['state'],'blocked',result);self.assertFalse(self.posts())
    def test_wrong_policy(self):
        result=self.finish(self.submit(policy={'version':1,'execution_mode':'noncombat','reactions':'stop'}))
        self.assertEqual(result['state'],'blocked',result);self.assertFalse(self.posts())
    def test_invalid_goal(self):
        result=self.finish(self.submit(arguments={'goal':{'x':1,'y':64,'z':0}}));self.assertEqual(result['state'],'blocked',result);self.assertFalse(self.posts())
    def test_forged_terminal(self):
        result=self.finish(self.submit());self.assertEqual(result['state'],'unknown',result);self.assertEqual(len(self.posts()),1)
    def test_not_grounded(self):
        result=self.finish(self.submit());self.assertNotEqual(result['state'],'succeeded',result);self.assertEqual(len(self.posts()),1)
    def test_moving(self):
        result=self.finish(self.submit());self.assertNotEqual(result['state'],'succeeded',result);self.assertEqual(len(self.posts()),1)

if __name__=='__main__':unittest.main()
