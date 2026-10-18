"""Actual production Node stdio -> configured Python -> Owner/Runtime/Intent/Watchdog/Resident.

Only the native Bridge endpoint is synthetic. No native physics or live acceptance claim.
"""
from native_unknown_fixture import assert_unknown_refusal
from copy import deepcopy
import hashlib
import gzip
import json
import math
import os
from pathlib import Path
import queue
import shutil
import subprocess
import sys
import threading
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs,urlsplit
import base_watchdog
import test_capability_ownership as owners
from navigation_controller.fake import FakeWorld,cell
from navigation_controller.terrain import Block
from resident_controller.capability_snapshot import validate_scoped_witness
from resident_controller.transport import BridgeError
from local_segment_fixture import fixture,terminal,PROFILE

ROOT=Path(__file__).resolve().parents[2]

class Endpoint(owners.CombatEndpoint):
    mode_name='success_obstacle_terrace'
    def __init__(self):
        super().__init__();self.mode_name=type(self).mode_name;self.pos={'x':.5,'y':64.,'z':.5}
        self.fixture_error=None;self.moves=[];self.scopes=[];self.actions=[]
        self.facts=fixture()[0]['result']['scoped_native_preflight']['facts']
    def block(self,x,y,z):
        if y<=63:return 'minecraft:stone'
        if self.mode_name=='adjacent_stations' and (x,y,z)==(5,64,0):return 'minecraft:furnace'
        if self.mode_name=='adjacent_stations' and (x,y,z)==(5,64,1):return 'minecraft:barrel'
        if self.mode_name=='nearby_foliage' and (x,y,z)==(5,67,0):return 'minecraft:oak_leaves'
        if self.mode_name=='nearby_foliage' and (x,y,z)==(5,67,1):return 'minecraft:birch_leaves'
        if self.mode_name=='no_path' and x==2 and 64<=y<=69:return 'minecraft:stone'
        if self.mode_name=='changed_geometry' and self.moves and x==2 and 64<=y<=69:return 'minecraft:stone'
        if x==2 and -1<=z<=1 and 64<=y<=67:return 'minecraft:stone'
        if x==3 and y==64:return 'minecraft:stone'
        return 'minecraft:air'
    def snapshot(self):
        value=super().snapshot();f=deepcopy(self.facts)
        value['player'].update(inventory=[{'slot':r['slot'],**r['item']} for r in f['inventory'][:36]],
            inventory_total=36,inventory_truncated=False,mainhand=deepcopy(f['equipment']['mainhand']),
            offhand=deepcopy(f['equipment']['offhand']),**self.pos)
        value['player']['eye_position']={'x':self.pos['x'],'y':self.pos['y']+1.62,'z':self.pos['z']}
        if self.mode_name=='moving' and self.moves:value['player']['velocity']['x']=.01
        if self.mode_name=='not_centered' and self.moves:value['player']['x']+=.12
        value['menu']={k:deepcopy(v) for k,v in f['menu'].items() if k!='slot_permissions'}
        value['movement_budget']={'schema_version':1,'status':'armed' if self.mode_name=='meter_armed' else 'unarmed',
            'position_hook_seen':True,'move_hook_seen':True}
        profiles={} if self.mode_name=='profile_missing' else {PROFILE:['follow_path']}
        if self.mode_name=='flat_compatibility':profiles.update({'movement-flat-observed-v2':['follow_path'],'movement-step-down-observed-v1':['follow_path']})
        value['scoped_native_preflight']={'version':'scoped-native-preflight/1','same_callback_capture_validate_admit':True,
            'private_singleplayer_only':True,'capability_guard_schema_version':1,'profiles':profiles,'guarded_actions':['follow_path']}
        return value
    def request(self,method,path,body=None):
        if path.startswith('/control/terrain?'):
            query=parse_qs(urlsplit(path).query)
            if 'radius' in query:
                endpoint=self
                class World(FakeWorld):
                    def get(self,p):return cell(p,endpoint.block(p.x,p.y,p.z).removeprefix('minecraft:'))
                world=World();world.generation='11111111-2222-4333-8444-555555555555'
                origin=Block(*(math.floor(self.pos[k]) for k in ('x','y','z')))
                pages=world.pages(origin=origin,radius=int(query['radius'][0]),vertical=int(query['vertical'][0]),
                    limit=int(query.get('limit',['128'])[0]),tick=self.tick)
                if query.get('capability')==['1']:
                    for page in pages:page.update(capability_page_schema_version=1,page_limit=int(query['limit'][0]))
                self.terrain_pages=iter(pages)
            value=next(self.terrain_pages);self.terrain_responses.append(deepcopy(value));return value
        if path=='/control/scoped-action':
            self.posts.append((path,deepcopy(body)));intent,scope=body['intent'],body['preflight']
            if self.mode_name=='native_refusal':raise BridgeError('local_segment_clearance_or_hazard_changed',status=409,uncertain=False)
            native,_,_,_=fixture(intent,scope,block=self.block)
            native.update(action_schema_version=1,ok=True,status='running',reason='synthetic_segment_admitted',server_confirmed=False)
            self.action=native;self.scopes.append(deepcopy(scope));self.actions.append(deepcopy(intent))
            try:validate_scoped_witness(native,scope,intent['action_id'],intent)
            except ValueError as exc:self.fixture_error=str(exc);raise
            if self.mode_name=='lost_second' and len(self.actions)==2:raise BridgeError('synthetic_lost_second_segment',uncertain=True)
            return deepcopy(self.action)
        if path.startswith('/control/action/status') and self.action['status']=='running':
            if self.mode_name=='cancel':return deepcopy(self.action)
            if self.mode_name=='motion_gate_unknown':
                # The native move-hook rejected a changed post-input motion envelope.
                # Even a cancelled, neutral/released action is not a known outcome.
                self.action.update(status='cancelled',reason='local_segment_motion_gate_velocity_changed')
                self.action['result'].update(input_release_confirmed=True,local_segment=terminal(self.action,landed=False),
                    unknown_outcome=True,motion_gate_rejected=True,motion_gate_reason='local_segment_motion_gate_velocity_changed')
                return deepcopy(self.action)
            point=self.actions[-1]['waypoints'][0];self.pos={k:point[k] for k in ('x','y','z')};self.moves.append(deepcopy(self.pos))
            self.action.update(status='succeeded',reason='synthetic_segment_centered')
            self.action['result'].update(input_release_confirmed=True,local_segment=terminal(self.action))
            if self.mode_name=='forged_terminal':self.action['result']['local_segment']['profile']='movement-step-down-observed-v1'
            return deepcopy(self.action)
        if path=='/control/action/cancel':
            self.posts.append((path,deepcopy(body)));self.action.update(status='cancelled',reason='cancel_requested')
            self.action['result'].update(input_release_confirmed=True,local_segment=terminal(self.action,landed=False))
            return deepcopy(self.action)
        return super().request(method,path,body)

class RouteLocalFrontdoorTests(unittest.TestCase):
    until=owners.ActualGatewayOwnershipTests.until
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
            MINECLIENT_BRIDGE_TEST_NAMESPACE='self-test-route-local-'+self.mode)
        self.stderr=(self.root/'mcp-stderr.log').open('w+')
        self.process=subprocess.Popen([shutil.which('node'),str(ROOT/'client-mod/mcp/mineclient-bridge-mcp.mjs')],
            stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=self.stderr,text=True,env=env,cwd=ROOT)
        self.replies=queue.Queue();self.sequence=0;self.transcript=[];self.raw_requests=[];self.raw_replies=[]
        def receive():
            for line in self.process.stdout:
                self.raw_replies.append(line)
                try:self.replies.put(json.loads(line))
                except ValueError:self.replies.put({'invalid':line})
        self.reader=threading.Thread(target=receive,daemon=True);self.reader.start()
        initialized=self.rpc('initialize',{'protocolVersion':'2024-11-05','capabilities':{},'clientInfo':{'name':'route-local-offline-test','version':'1'}})
        self.assertIn('protocolVersion',initialized['result'])
        listed=self.rpc('tools/list',{})
        self.assertTrue({'mdc_catalog','mdc_observe','mdc_job'} <= {tool['name'] for tool in listed['result']['tools']})
    def tearDown(self):
        try:
            if getattr(self,'process',None):
                self.process.stdin.close();self.process.wait(timeout=15);self.reader.join(timeout=2)
                self.process.stdout.close();self.stderr.seek(0);stderr=self.stderr.read();self.stderr.close()
                destination=os.environ.get('MDC_ROUTE_LOCAL_TEST_RESULTS')
                if destination:
                    output=Path(destination)/self.mode;output.mkdir(parents=True,exist_ok=True)
                    (output/'frontdoor-transcript.json').write_text(json.dumps(self.transcript,indent=2))
                    (output/'frontdoor-transcript.json.gz').write_bytes(gzip.compress(json.dumps(self.transcript,ensure_ascii=False).encode(),mtime=0))
                    (output/'mcp-requests.ndjson.gz').write_bytes(gzip.compress(''.join(self.raw_requests).encode(),mtime=0))
                    (output/'mcp-replies.ndjson.gz').write_bytes(gzip.compress(''.join(self.raw_replies).encode(),mtime=0))
                    (output/'terrain-responses.json.gz').write_bytes(gzip.compress(json.dumps(self.bridge.terrain_responses).encode(),mtime=0))
                    (output/'native-endpoint-proof.json').write_text(json.dumps({'synthetic_native':True,'posts':self.bridge.posts,
                        'moves':self.bridge.moves,'fixture_error':self.bridge.fixture_error,'mcp_exit_code':self.process.returncode,
                        'capability_lease':self.client.session().get('capability_lease')},indent=2))
                    for name in ('runtime','toolbox'):
                        if (self.root/name).is_dir():shutil.copytree(self.root/name,output/name,dirs_exist_ok=True)
                self.assertEqual(self.process.returncode,getattr(self,'expected_mcp_exit',2 if self.mode in ('lost_second','forged_terminal','motion_gate_unknown') else 0),stderr)
        finally:owners.ActualGatewayOwnershipTests.tearDown(self)
    def rpc(self,method,params):
        self.sequence+=1;identity=self.sequence
        request={'jsonrpc':'2.0','id':identity,'method':method,'params':params}
        raw=json.dumps(request)+'\n';self.raw_requests.append(raw)
        self.process.stdin.write(raw);self.process.stdin.flush();response=self.replies.get(timeout=25)
        self.transcript.append({'request':request,'response':response});self.assertEqual(response.get('id'),identity,response)
        self.assertNotIn('error',response,response);return response
    def call(self,name,args):
        response=self.rpc('tools/call',{'name':name,'arguments':args})
        return json.loads(response['result']['content'][0]['text'])
    def submit(self,**changes):
        self.catalog=self.call('mdc_catalog',{'api_version':'mdc.toolbox/1','capability_ids':['navigate_route_local','navigate_step_down','navigate_local','navigate_loaded'],'detail':'contracts'})
        desc=self.catalog['runtime_binding_availability']
        self.initial_observation=self.call('mdc_observe',{'api_version':'mdc.toolbox/1','session_ref':desc['session_ref'],'profile':'player'})
        self.assertNotIn('error',self.initial_observation,self.initial_observation)
        args={'api_version':'mdc.toolbox/1','operation':'submit','request_id':'route-'+self.mode,
            'session_ref':desc['session_ref'],'expected_context_ref':desc['context_ref'],
            'capability':'navigate_route_local','capability_version':1,'arguments':{'goal':{'x':4,'y':64,'z':0},'radius':6,'max_segments':16,'min_health':12},
            'policy':{'version':1,'execution_mode':'request_only','reactions':'stop'},
            'budgets':{'deadline_seconds':120,'max_actions':17,'max_observations':256,'cleanup_reserve_actions':1,'reflex_reserve_actions':0},'wait_ms':10000}
        args.update(changes);self.last_submit=deepcopy(args);return self.call('mdc_job',args)
    def finish(self,result):
        while result.get('state') in ('accepted','running','stopping'):
            result=self.call('mdc_job',{'api_version':'mdc.toolbox/1','operation':'status','session_ref':result['session_ref'],'job_id':result['job_id'],'wait_ms':10000})
        return result
    def posts(self):return [b for p,b in self.bridge.posts if p=='/control/scoped-action']
    def test_success_obstacle_terrace(self):
        result=self.finish(self.submit());self.assertEqual(result['state'],'succeeded',(self.bridge.fixture_error,result))
        self.assertEqual(result['cleanup_certainty'],'confirmed');self.assertEqual(result['effect_certainty'],'known')
        self.assertGreaterEqual(len(self.posts()),8);self.assertLessEqual(len(self.posts()),12)
        self.assertEqual(self.bridge.pos,{'x':4.5,'y':64,'z':.5})
        final=self.call('mdc_observe',{'api_version':'mdc.toolbox/1','session_ref':result['session_ref'],'profile':'player'})
        self.assertNotIn('error',final,final);self.assertEqual(final['state']['player']['x'],4.5)
        self.assertLessEqual(math.hypot(final['state']['player']['x']-4.5,final['state']['player']['z']-.5),.08)
        self.assertTrue(final['state']['client_action']['result']['input_release_confirmed'])
        self.assertEqual(result['evidence']['budget']['used']['ordinary']['actions'],len(self.posts()))
        self.assertTrue(any(p['y']==65 for p in self.bridge.moves));self.assertTrue(any(abs(p['z']-.5)>=2 for p in self.bridge.moves))
        self.assertEqual(len({tuple(s[k] for k in ('owner_id','owner_generation','job_id','defense_epoch')) for s in self.bridge.scopes}),1)
        self.assertEqual(len({p['intent']['action_id'] for p in self.posts()}),len(self.posts()))
        for post in self.posts():
            self.assertEqual(post['preflight']['profile'],PROFILE);self.assertEqual(len(post['intent']['waypoints']),1)
            self.assertFalse(post['intent']['waypoints'][0]['jump'])
            origin=post['intent']['expected_origin']
            self.assertLessEqual(abs(origin['x']-math.floor(origin['x'])-.5),.10)
            self.assertLessEqual(abs(origin['z']-math.floor(origin['z'])-.5),.10)
        self.assertIsNone(self.client.session()['capability_lease']);self.assertFalse([p for p,b in self.bridge.posts if p=='/control/action'])
        available={e['capability']:e['runtime_available'] for e in self.catalog['capabilities']}
        self.assertTrue(available['navigate_route_local']);self.assertFalse(available['navigate_loaded']);self.assertFalse(available['navigate_local'])
    def test_adjacent_stations(self):
        result=self.finish(self.submit());self.assertEqual(result['state'],'succeeded',result)
        self.assertEqual(self.bridge.pos,{'x':4.5,'y':64,'z':.5})
        m=self.bridge.action['result']['scoped_native_preflight']['facts']['local_segment']
        stations=[c for c in m['cells'] if c['id'] in ('minecraft:barrel','minecraft:furnace')]
        self.assertEqual(len(stations),2);self.assertTrue(all(c['role']=='context' for c in stations))
        self.assertTrue(all(post['preflight']['profile']==PROFILE for post in self.posts()))
    def test_nearby_foliage(self):
        result=self.finish(self.submit());self.assertEqual(result['state'],'succeeded',result)
        self.assertEqual(self.bridge.pos,{'x':4.5,'y':64,'z':.5})
        m=self.bridge.action['result']['scoped_native_preflight']['facts']['local_segment']
        leaves=[c for c in m['cells'] if c['id'] in ('minecraft:oak_leaves','minecraft:birch_leaves')]
        self.assertEqual(len(leaves),2);self.assertTrue(all(c['role']=='context' for c in leaves))
        self.assertTrue(all(post['preflight']['profile']==PROFILE for post in self.posts()))
    def test_lost_second(self):
        result=self.finish(self.submit());self.assertEqual(result['state'],'unknown',result);self.assertEqual(len(self.posts()),2)
        self.assertFalse([p for p,b in self.bridge.posts if p=='/control/action/cancel'])
        again=self.call('mdc_job',{'api_version':'mdc.toolbox/1','operation':'status','session_ref':result['session_ref'],'job_id':result['job_id']})
        self.assertEqual(again['state'],'unknown');self.assertEqual(len(self.posts()),2)
    def test_motion_gate_unknown(self):
        result=self.finish(self.submit());self.assertEqual(result['state'],'unknown',result)
        self.assertEqual(result['effect_certainty'],'unknown');self.assertEqual(result['cleanup_certainty'],'unknown')
        self.assertEqual(result['continuation'],'reconcile_original_id_required')
        self.assertEqual(result['error']['code'],'outcome_unknown')
        self.assertEqual(len(self.posts()),1);self.assertFalse(self.bridge.moves)
        self.assertTrue(self.bridge.action['result']['input_release_confirmed'])
        self.assertTrue(self.bridge.action['result']['unknown_outcome'])
        self.assertTrue(self.bridge.action['result']['motion_gate_rejected'])
        again=self.call('mdc_job',{'api_version':'mdc.toolbox/1','operation':'status','session_ref':result['session_ref'],'job_id':result['job_id']})
        self.assertEqual(again['state'],'unknown');self.assertEqual(again['continuation'],'reconcile_original_id_required')
        retry=deepcopy(self.last_submit);retry['request_id']='route-gate-new-id'
        refused=self.call('mdc_job',retry);self.assertNotIn(refused.get('state'),('accepted','running','succeeded'),refused)
        self.assertEqual(len(self.posts()),1)
        self.assertFalse([p for p,b in self.bridge.posts if p in ('/control/action','/control/action/cancel')])
        self.assertFalse([p for p in self.posts() if p['intent']['action']=='combat_entity'])
    def test_cancel(self):
        result=self.submit(wait_ms=0);self.until(lambda:bool(self.posts()))
        result=self.call('mdc_job',{'api_version':'mdc.toolbox/1','operation':'cancel','session_ref':result['session_ref'],'job_id':result['job_id'],'cancel_request_id':'route-cancel-once','wait_ms':10000})
        result=self.finish(result);self.assertEqual(result['state'],'cancelled',result);self.assertEqual(len(self.posts()),1)
        cancels=[b for p,b in self.bridge.posts if p=='/control/action/cancel'];self.assertEqual(len(cancels),1)
        self.assertEqual(cancels[0]['action_id'],self.posts()[0]['intent']['action_id'])
    def test_no_path(self):
        result=self.finish(self.submit());self.assertEqual(result['state'],'blocked',result);self.assertFalse(self.posts())
    def test_changed_geometry(self):
        result=self.finish(self.submit());self.assertEqual(result['state'],'blocked',result);self.assertEqual(len(self.posts()),1)
    def test_native_refusal(self):
        self.expected_mcp_exit = 2
        result = self.finish(self.submit())
        assert_unknown_refusal(self, result)
        self.assertEqual(len(self.posts()), 1)
    def test_insufficient_budget(self):
        result=self.finish(self.submit(budgets={'deadline_seconds':120,'max_actions':2,'max_observations':256,'cleanup_reserve_actions':1,'reflex_reserve_actions':0}))
        self.assertEqual(result['state'],'interrupted',result);self.assertEqual(len(self.posts()),1)
    def test_profile_missing(self):
        result=self.submit();self.assertEqual(result['error']['code'],'capability_unavailable',result);self.assertFalse(self.posts())
    def test_meter_armed(self):
        result=self.finish(self.submit());self.assertEqual(result['state'],'blocked',result);self.assertFalse(self.posts())
    def test_wrong_policy(self):
        result=self.finish(self.submit(policy={'version':1,'execution_mode':'noncombat','reactions':'stop'}))
        self.assertEqual(result['state'],'blocked',result);self.assertFalse(self.posts())
    def test_out_of_bounds(self):
        result=self.finish(self.submit(arguments={'goal':{'x':9,'y':64,'z':0},'radius':6}))
        self.assertEqual(result['state'],'blocked',result);self.assertFalse(self.posts())
    def test_forged_terminal(self):
        result=self.finish(self.submit());self.assertEqual(result['state'],'unknown',result);self.assertEqual(len(self.posts()),1)
    def test_not_centered(self):
        result=self.finish(self.submit());self.assertNotEqual(result['state'],'succeeded',result);self.assertEqual(len(self.posts()),1)
    def test_moving(self):
        result=self.finish(self.submit());self.assertNotEqual(result['state'],'succeeded',result);self.assertEqual(len(self.posts()),1)
    def test_flat_compatibility(self):
        result=self.finish(self.submit());self.assertEqual(result['state'],'succeeded',result)
        available={e['capability']:e['runtime_available'] for e in self.catalog['capabilities']}
        self.assertTrue(available['navigate_local']);self.assertTrue(available['navigate_step_down']);self.assertFalse(available['navigate_loaded'])
        self.assertTrue(all(post['preflight']['profile']==PROFILE for post in self.posts()))

if __name__=='__main__':unittest.main()
