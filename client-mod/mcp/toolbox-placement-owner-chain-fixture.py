"""Offline placement subprocess: actual owner/Resident components, synthetic native only.

All queues are new TemporaryDirectory fixtures. No installed runtime, native
process, credentials, network or game is accessed.
"""
from copy import deepcopy
import json
from pathlib import Path
import sys
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'capability-runtime'),str(ROOT/'capability-runtime/tests'),
             str(ROOT/'capability-runtime/tests/placement'),str(ROOT/'resident-controller'),str(ROOT/'defense-watchdog')]
import base_watchdog
import test_capability_ownership as owners
from mdc_skills.core import Runtime
from mdc_toolbox import ToolboxService
from mdc_toolbox.runtime_adapter import OwnerRuntimeBackend
from resident_controller.capability_snapshot import validate_scoped_witness
from resident_controller.transport import BridgeError
from placement_fixture import placement_fixture

PROFILE='placement-local-observed-v1'
CASE=sys.argv[1] if len(sys.argv)>1 else 'success'
MODE='success' if CASE in ('table_success','furnace_success') else CASE
MATERIAL='minecraft:crafting_table' if CASE=='table_success' else 'minecraft:furnace' if CASE=='furnace_success' else 'minecraft:cobblestone'
PROPERTIES={'facing':'south','lit':'false'} if MATERIAL=='minecraft:furnace' else {}
PUBLIC_ARGUMENTS={'support':{'x':2,'y':63,'z':0},'face':'up',
    'expected_support_id':'minecraft:stone','expected_support_properties':{},
    'expected_block_id':MATERIAL,'expected_block_properties':PROPERTIES}

class PlacementEndpoint(owners.CombatEndpoint):
    def __init__(self):
        super().__init__()
        self.placement_mode=MODE
        base=placement_fixture()[3]
        base.update(expected_block_id=MATERIAL,expected_block_properties=deepcopy(PROPERTIES))
        base['expected_held_item']['id']=MATERIAL
        base['placement_footprint'][0].update(block_id=MATERIAL,properties=deepcopy(PROPERTIES))
        template=placement_fixture(intent_override=base)[0]
        self.facts=deepcopy(template['result']['scoped_native_preflight']['facts'])
        self.initial_count=self.facts['inventory'][0]['item']['count']
        self.placed=False;self.decrements=0;self.fixture_error=None
    def snapshot(self):
        value=super().snapshot();facts=deepcopy(self.facts)
        if self.placed and self.placement_mode!='no_decrement':
            item=facts['inventory'][0]['item'];item['count']=self.initial_count-1
            item['empty']=item['count']==0
            item['item_fingerprint']='99999999-9999-4999-8999-999999999999'
            if item['empty']:item.update(id='',max_stack_size=0)
            facts['equipment']['mainhand']=deepcopy(item);facts['menu']['slots'][36]['item']=deepcopy(item)
        value['player'].update(inventory=[{'slot':r['slot'],**r['item']} for r in facts['inventory'][:36]],
            inventory_total=36,inventory_truncated=False,mainhand=deepcopy(facts['equipment']['mainhand']),
            offhand=deepcopy(facts['equipment']['offhand']))
        value['menu']={k:deepcopy(v) for k,v in facts['menu'].items() if k!='slot_permissions'}
        value['scoped_native_preflight']={'version':'scoped-native-preflight/1','same_callback_capture_validate_admit':True,
            'private_singleplayer_only':True,'capability_guard_schema_version':1,
            'profiles':{} if self.placement_mode=='profile_missing' else {PROFILE:['place_block']},
            'guarded_actions':['place_block']}
        return value
    def request(self,method,path,body=None):
        if path=='/control/scoped-action':
            self.posts.append((path,deepcopy(body)))
            intent,scope=body['intent'],body['preflight']
            native,_,_,_=placement_fixture(intent_override=intent,scope_override=scope)
            native.update(action_schema_version=1,ok=True,status='running',reason='synthetic_placement_admitted',server_confirmed=False)
            self.success_proof=deepcopy(native['result']['placement'])
            native['result']['placement'].update(effect_attempted=False,effect_count=0,packet_count=0,block_placed=False,protected_inventory_unchanged=False,final_count=self.initial_count)
            native['result']['input_release_confirmed']=False
            self.action=native
            try:validate_scoped_witness(native,scope,intent['action_id'],intent)
            except ValueError as exc:self.fixture_error=str(exc);raise
            if self.placement_mode=='late409':
                self.placed=True;self.decrements=1
                self.action['result']['placement']=deepcopy(self.success_proof)
                raise BridgeError('synthetic_post_use_http409',status=409,uncertain=False)
            if self.placement_mode=='lost':raise BridgeError('synthetic_lost_placement_admission',uncertain=True)
            return deepcopy(self.action)
        if path.startswith('/control/action/status') and self.action['status']=='running':
            if self.placement_mode=='cancel':return deepcopy(self.action)
            self.placed=True
            if self.placement_mode!='no_decrement':self.decrements+=1
            self.action.update(status='succeeded',reason='synthetic_placement_verified')
            self.action['result']['placement']=deepcopy(self.success_proof)
            self.action['result']['input_release_confirmed']=True
            if self.placement_mode=='effect_unknown':
                self.action.update(status='failed',reason='synthetic_post_effect_uncertainty')
                self.action['result']['unknown_outcome']=True
                self.action['result']['placement'].update(unknown_outcome=True,block_placed=False,protected_inventory_unchanged=False)
            return deepcopy(self.action)
        if path=='/control/action/cancel':
            self.posts.append((path,deepcopy(body)))
            self.action.update(status='cancelled',reason='cancel_requested')
            self.action['result']['input_release_confirmed']=True
            return deepcopy(self.action)
        return super().request(method,path,body)

class PlacementHarness(owners.ActualGatewayOwnershipTests):
    def setUp(self):
        run=base_watchdog.run
        def request_only(*args,**kwargs):kwargs['execution_policy']='request_only';return run(*args,**kwargs)
        with patch.object(owners,'CombatEndpoint',PlacementEndpoint),patch.object(base_watchdog,'run',request_only):
            super().setUp()
        self.runtime=Runtime(self.client,self.root/'placement-runtime',wait_timeout=2)
        self.runtime.required_execution_policy='request_only'
        self.backend=OwnerRuntimeBackend(self.runtime);self.service=ToolboxService(self.backend,self.root/'toolbox')
    def tearDown(self):
        self.service.close();self.runtime.close();super().tearDown()
    def finish(self,job):
        def done():
            self.result=self.service.call('mdc_job',{'api_version':'mdc.toolbox/1','operation':'status',
                'job_id':job['job_id'],'session_ref':job['session_ref'],'wait_ms':0})
            return self.result['state'] not in ('accepted','running','stopping')
        self.until(done,timeout=8);return self.result


def emit(value):print(json.dumps(value,allow_nan=False),flush=True)

def main():
    harness=PlacementHarness();harness.setUp();calls=[]
    try:
        desc=harness.backend.describe()
        emit({'ready':True,'session_ref':desc['session_ref'],'context_ref':desc['context_ref'],
              'arguments':PUBLIC_ARGUMENTS,'synthetic_native':True,'execution_policy':harness.client.session()['execution_policy']})
        for line in sys.stdin:
            command=json.loads(line)
            if command.get('command')=='proof':
                bridge=harness.bridge
                result={'calls':calls,'scoped_posts':[b for p,b in bridge.posts if p=='/control/scoped-action'],
                    'cancel_posts':[b for p,b in bridge.posts if p=='/control/action/cancel'],
                    'legacy_posts':[b for p,b in bridge.posts if p=='/control/action'],
                    'placed':bridge.placed,'decrements':bridge.decrements,'initial_count':bridge.initial_count,
                    'final_count':bridge.snapshot()['player']['inventory'][0]['count'],
                    'fixture_error':bridge.fixture_error,'capability_lease':harness.client.session()['capability_lease'],
                    'synthetic_native':True}
            else:
                name,args=command['name'],command['arguments'];calls.append({'name':name,'arguments':args})
                result=harness.service.call(name,args)
                if 'job_id' in result:
                    if MODE=='cancel' and args.get('operation')=='submit':
                        harness.until(lambda:bool(harness.bridge.posts))
                        result=harness.service.call('mdc_job',{'api_version':'mdc.toolbox/1','operation':'status',
                            'job_id':result['job_id'],'session_ref':result['session_ref'],'wait_ms':0})
                    else:result=harness.finish(result)
            emit({'id':command['id'],'result':result})
    finally:harness.tearDown()

if __name__=='__main__':main()
