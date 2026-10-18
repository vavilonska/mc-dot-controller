"""Public service -> owner -> Intent -> Watchdog -> Resident; only native endpoint is synthetic."""
from copy import deepcopy
import unittest
import uuid
from unittest.mock import patch
import test_capability_ownership as owners
from test_scoped_combat_chain import _fixture_module
from test_inventory_recovery import Runtime as ModelRuntime, inventory_observation, stack, cursor_args
from mdc_skills import inventory_recovery as recovery
from mdc_skills.core import Runtime
from mdc_toolbox import ToolboxService
from mdc_toolbox.runtime_adapter import OwnerRuntimeBackend
from resident_controller.capability_snapshot import validate_scoped_witness
from resident_controller.transport import BridgeError


def make_witness(before, intent, scope):
    native,_,_,_=_fixture_module.base_fixture();w=native['result']['scoped_native_preflight'];f=w['facts']
    w.update(scope);w.update(action_id=intent['action_id'],action_session=intent['expected_action_session'],
        source_tick=intent['capability_guard']['source_tick']+1,source_nano=str(int(intent['capability_guard']['source_nano'])+1),
        admitted_nano=str(int(intent['capability_guard']['source_nano'])+21))
    f['context'].update({k:intent['expected_'+k] for k in ('world_generation','dimension','player_uuid','action_session')})
    w['context']=deepcopy(f['context']);view=recovery.View(before)
    f['selected_slot']=view.selected;f['screen_class']='' if not before.state['screen_open'] else 'net.minecraft.client.gui.screens.inventory.ContainerScreen'
    f['inventory']=[{'slot':i,'item':deepcopy(value)} for i,value in view.inventory.items()]
    for name,index in {'mainhand':view.selected,'offhand':40,'feet':36,'legs':37,'chest':38,'head':39}.items():
        f['equipment'][name]=deepcopy(view.inventory[index])
    f['menu']=deepcopy(view.menu)
    f['menu']['slot_permissions']=[{'may_pickup':True,'may_place_carried':True,'max_stack_size':64} for row in view.slots.values()]
    native.update(action_id=intent['action_id'],action_session=intent['expected_action_session'],action='click_slot',
        ok=True,action_schema_version=1,status='succeeded',reason='synthetic_click_dispatched',server_confirmed=False)
    _fixture_module.reseal((native,scope,intent['action_id'],intent))
    validate_scoped_witness(native,scope,intent['action_id'],intent)
    return native


def normalize(observation):
    values = [observation.state['menu']['carried'], *observation.player['inventory'],
              observation.player['offhand'], *observation.player['armor'],
              *(row['item'] for row in observation.state['menu']['slots'])]
    for value in values:
        component = value['component_fingerprint']
        try: uuid.UUID(component)
        except ValueError: component = str(uuid.uuid5(uuid.NAMESPACE_OID, component))
        value['component_fingerprint'] = component
        value['item_fingerprint'] = str(uuid.uuid5(uuid.NAMESPACE_OID, component + '/' + str(value['count'])))


class Endpoint(owners.CombatEndpoint):
    def __init__(self):
        super().__init__();self.model=ModelRuntime(inventory_observation(offhand=stack('minecraft:torch',2)))
        normalize(self.model.current)
        self.advertise=True;self.fixture_error=None;self.lose=False
    def snapshot(self):
        state=super().snapshot();current=deepcopy(self.model.current.state)
        state['menu']=current['menu'];state['screen_open']=current['screen_open']
        state['player'].update(current['player']);state['player']['mainhand']=state['player']['inventory'][state['player']['selected_slot']]
        state['scoped_native_preflight']={'version':'scoped-native-preflight/1','private_singleplayer_only':True,
            'same_callback_capture_validate_admit':True,'capability_guard_schema_version':1,
            'inventory_recovery_schema_version':1 if self.advertise else 0,
            'profiles':{'state-menu-v1':['click_slot','close_menu','select_hotbar']},'guarded_actions':['click_slot','close_menu','select_hotbar']}
        return state
    def request(self,method,path,body=None):
        if path=='/control/scoped-action':
            self.posts.append((path,deepcopy(body)));intent=body['intent'];before=deepcopy(self.model.current)
            try:self.action=make_witness(before,intent,body['preflight'])
            except ValueError as exc:self.fixture_error=str(exc);raise
            self.model.execute('native',intent,lambda *_:True,before=before)
            normalize(self.model.current)
            if self.hold:self.action['status']='running'
            if self.lose:raise BridgeError('synthetic_lost_click',uncertain=True)
            return deepcopy(self.action)
        return super().request(method,path,body)


class InventoryRecoveryChainTests(unittest.TestCase):
    until=owners.ActualGatewayOwnershipTests.until
    def setUp(self):
        with patch.object(owners,'CombatEndpoint',Endpoint):owners.ActualGatewayOwnershipTests.setUp(self)
        self.runtime=Runtime(self.client,self.root/'recovery-runtime',wait_timeout=2)
        self.backend=OwnerRuntimeBackend(self.runtime);self.service=ToolboxService(self.backend,self.root/'toolbox')
    def tearDown(self):
        self.service.close();self.runtime.close();owners.ActualGatewayOwnershipTests.tearDown(self)
    def submit(self,capability='clear_hand',arguments=None,request_id='clear-one'):
        d=self.backend.describe()
        return self.service.call('mdc_job',{'api_version':'mdc.toolbox/1','operation':'submit','request_id':request_id,
            'session_ref':d['session_ref'],'expected_context_ref':d['context_ref'],'capability':capability,'capability_version':1,
            'arguments':arguments or {},'policy':{'version':1,'execution_mode':'guarded','reactions':'stop'},
            'budgets':{'max_actions':7,'max_observations':64,'deadline_seconds':30},'wait_ms':0})
    def finish(self,r):
        self.assertIn('job_id',r,r)
        def terminal():
            self.result=self.service.call('mdc_job',{'api_version':'mdc.toolbox/1','operation':'status','job_id':r['job_id'],'session_ref':r['session_ref']})
            return self.result['state'] not in ('accepted','running','stopping')
        self.until(terminal,timeout=12);return self.result
    def test_full_public_clear_hand_and_dedup(self):
        first=self.submit();result=self.finish(first)
        self.assertEqual(result['state'],'succeeded',(self.bridge.fixture_error,result))
        self.assertEqual(result['cleanup_certainty'],'confirmed');self.assertEqual(result['effect_certainty'],'known')
        posts=[body for path,body in self.bridge.posts if path=='/control/scoped-action'];self.assertEqual(len(posts),4)
        self.assertEqual(len({p['preflight']['job_id'] for p in posts}),1)
        self.assertEqual(len({p['preflight']['owner_generation'] for p in posts}),1)
        self.assertTrue(all(p['preflight']['profile']=='state-menu-v1' for p in posts))
        again=self.submit();self.assertEqual(again['job_id'],first['job_id']);self.assertEqual(len(self.bridge.model.commands),4)
        self.assertIsNone(self.client.session()['capability_lease'])
        self.assertFalse([p for p,b in self.bridge.posts if p=='/control/action'])
    def test_cancel_then_explicit_cursor_recovery_under_new_identity(self):
        self.bridge.hold=True;first=self.submit()
        self.until(lambda:any(p=='/control/scoped-action' for p,b in self.bridge.posts))
        self.service.call('mdc_job',{'api_version':'mdc.toolbox/1','operation':'cancel','job_id':first['job_id'],
            'session_ref':first['session_ref'],'cancel_request_id':'cancel-clear','wait_ms':1000})
        stopped=self.finish(first);self.assertEqual(stopped['state'],'cancelled',stopped)
        self.assertEqual(len(self.bridge.model.commands),1);self.assertFalse(self.bridge.model.current.state['menu']['carried']['empty'])
        self.bridge.hold=False
        recovered=self.finish(self.submit('recover_cursor',cursor_args(self.bridge.model.current),'recover-one'))
        self.assertEqual(recovered['state'],'succeeded',recovered);self.assertEqual(recovered['cleanup_certainty'],'confirmed')
        self.assertTrue(self.bridge.model.current.state['menu']['carried']['empty'])
        self.assertEqual(len(self.bridge.model.commands),2)
    def test_unknown_original_blocks_new_recovery(self):
        self.bridge.lose=True;result=self.finish(self.submit())
        self.assertEqual(result['state'],'unknown',result)
        again=self.submit('recover_cursor',cursor_args(self.bridge.model.current),'new-not-authorized-by-unknown')
        self.assertIn(again['error']['code'],('capability_unavailable','owner_busy'))
        self.assertEqual(len(self.bridge.model.commands),1)

if __name__=='__main__':unittest.main()
