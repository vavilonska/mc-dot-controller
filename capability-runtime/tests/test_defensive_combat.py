"""Closed defensive schema and actual public owner chain; native endpoint is modeled."""
from copy import deepcopy
import unittest
from unittest.mock import patch
import test_capability_ownership as owners
import test_scoped_combat_chain as combat
from mdc_skills.core import Runtime
from mdc_skills.defensive_combat import PROFILE,_same_policy
from mdc_toolbox import ToolboxService
from mdc_toolbox.runtime_adapter import OwnerRuntimeBackend
from mdc_toolbox.catalog import CapabilityCatalog
from mdc_toolbox.bindings import defensive
from mdc_toolbox.contracts import ToolboxError,validate_schema
from resident_controller.capability_snapshot import validate_scoped_witness
from resident_controller.transport import BridgeError

SHIELD={'id':'minecraft:shield','count':1,'empty':False,'max_stack_size':1,
    'item_fingerprint':'55555555-5555-4555-8555-555555555555',
    'component_fingerprint':'66666666-6666-4666-8666-666666666666'}

def witness(intent,scope,health=6.):
    native=combat.combat_witness(intent,scope);w=native['result']['scoped_native_preflight'];f=w['facts']
    f['health']=health;f['combat']['profile']=PROFILE
    f['combat']['defensive_policy']=deepcopy(intent['defensive_policy'])
    for k in ('max_distance','minimum_separation_gain'):f['combat']['defensive_policy'][k]=float(f['combat']['defensive_policy'][k])
    f['inventory'][40]['item']=deepcopy(SHIELD);f['equipment']['offhand']=deepcopy(SHIELD);f['menu']['slots'][45]['item']=deepcopy(SHIELD)
    combat.reseal((native,scope,intent['action_id'],intent));return native

class Endpoint(combat.Endpoint):
    def __init__(self):
        super().__init__();self.health=6;self.defensive_advertise=True;self.result_fault=None;self.combat_mode='no_damage'
    def snapshot(self):
        value=super().snapshot();value['player']['offhand']=deepcopy(SHIELD)
        while len(value['player']['inventory'])<41:
            value['player']['inventory'].append({**deepcopy(value['player']['inventory'][1]),'slot':len(value['player']['inventory'])})
        value['player']['inventory'][40]={**SHIELD,'slot':40}
        # No weapon required by these modes.
        value['player']['inventory'][0].update(id='',count=0,empty=True,max_stack_size=0)
        if self.defensive_advertise:value['scoped_native_preflight']['profiles'][PROFILE]=['combat_entity']
        return value
    def request(self,method,path,body=None):
        if path=='/control/scoped-action':
            self.posts.append((path,deepcopy(body)));self.action=witness(body['intent'],body['preflight'],self.health)
            try:validate_scoped_witness(self.action,body['preflight'],body['intent']['action_id'],body['intent'])
            except ValueError as exc:self.fixture_error=str(exc)
            p=deepcopy(body['intent']['defensive_policy'])
            self.action['result']['combat']={k:body['intent'][k] for k in ('target_entity_id','target_uuid','target_type')}
            self.action['result']['combat'].update(defensive_policy=p,defensive_completed=True,attack_dispatches=0,
                offensive_effects_allowed=False,physical_safe=False,risk_remaining=True,
                defensive_blocking_samples=5,defensive_separation_gain=1.)
            if self.result_fault:self.result_fault(self.action['result']['combat'])
            if self.combat_mode=='lost':raise BridgeError('synthetic_lost_defensive_submit',uncertain=True)
            return deepcopy(self.action)
        return super().request(method,path,body)

class DefensiveOwnerChainTests(unittest.TestCase):
    until=owners.ActualGatewayOwnershipTests.until
    finish=combat.PublicCombatChainTests.finish
    def setUp(self):
        with patch.object(owners,'CombatEndpoint',Endpoint):owners.ActualGatewayOwnershipTests.setUp(self)
        self.runtime=Runtime(self.client,self.root/'defensive-runtime',wait_timeout=2)
        self.backend=OwnerRuntimeBackend(self.runtime);self.service=ToolboxService(self.backend,self.root/'toolbox')
    def tearDown(self):
        self.service.close();self.runtime.close();owners.ActualGatewayOwnershipTests.tearDown(self)
    def submit(self,capability='defend_local',arguments=None):
        d=self.backend.describe();self.assertIn(capability,d['supported_capabilities'])
        return self.service.call('mdc_job',{'api_version':'mdc.toolbox/1','operation':'submit','request_id':'defensive_one',
            'session_ref':d['session_ref'],'expected_context_ref':d['context_ref'],'capability':capability,'capability_version':1,
            'arguments':{'target_uuid':combat.TARGET,**(arguments or {})},
            'policy':{'version':1,'execution_mode':'guarded','reactions':'stop'},
            'budgets':{'max_actions':3,'max_observations':24,'deadline_seconds':10},'wait_ms':0})
    def test_shield_public_exact_owner_low_health_no_weapon(self):
        result=self.finish(self.submit());self.assertEqual(result['state'],'succeeded',(self.bridge.fixture_error,result))
        posts=[b for p,b in self.bridge.posts if p=='/control/scoped-action'];self.assertEqual(len(posts),1)
        self.assertEqual(posts[0]['preflight']['profile'],PROFILE);self.assertFalse(posts[0]['intent']['approach'])
        self.assertEqual(posts[0]['intent']['defensive_policy']['mode'],'shield_only')
        self.assertEqual(posts[0]['intent']['target_uuid'],combat.TARGET)
        self.assertFalse([p for p,b in self.bridge.posts if p=='/control/action']);self.assertIsNone(self.client.session()['capability_lease'])
    def test_evade_public_exact_bounds(self):
        result=self.finish(self.submit('evade_local',{'window_ms':2000,'max_distance':3,'minimum_separation_gain':.75}))
        self.assertEqual(result['state'],'succeeded',(self.bridge.fixture_error,result))
        body=next(b for p,b in self.bridge.posts if p=='/control/scoped-action')
        self.assertFalse(body['intent']['shield']);self.assertEqual(body['intent']['timeout_ms'],2250)
        self.assertEqual(body['intent']['defensive_policy']['max_distance'],3)
    def test_lost_submit_stays_unknown_one_post(self):
        self.bridge.combat_mode='lost';result=self.finish(self.submit());self.assertEqual(result['state'],'unknown',result)
        self.assertEqual(len([p for p,b in self.bridge.posts if p=='/control/scoped-action']),1)
        self.assertFalse([p for p,b in self.bridge.posts if p=='/control/action/cancel'])
    def test_exact_cancel_no_retry_or_resume(self):
        self.bridge.hold=True;r=self.submit();self.until(lambda:any(p=='/control/scoped-action' for p,b in self.bridge.posts))
        self.service.call('mdc_job',{'api_version':'mdc.toolbox/1','operation':'cancel','job_id':r['job_id'],'session_ref':r['session_ref'],'cancel_request_id':'stop_defensive','wait_ms':1000})
        result=self.finish(r);self.assertEqual(result['state'],'cancelled',result)
        cancels=[b for p,b in self.bridge.posts if p=='/control/action/cancel'];self.assertEqual(len(cancels),1)
        self.assertEqual(cancels[0]['action_id'],self.bridge.action['action_id'])
        self.assertEqual(len([p for p,b in self.bridge.posts if p=='/control/scoped-action']),1)
    def test_missing_new_profile_does_not_borrow_engage(self):
        self.bridge.defensive_advertise=False
        self.until(lambda:'defend_local' not in self.backend.describe()['supported_capabilities'])
        d=self.backend.describe();self.assertIn('engage',d['supported_capabilities']);self.assertNotIn('evade_local',d['supported_capabilities'])
        for name in ('strike','defeat','retreat','hunt_resource'):self.assertNotIn(name,d['supported_capabilities'])
    def test_forged_offense_receipt_not_success(self):
        self.bridge.result_fault=lambda value:value.update(attack_dispatches=1)
        self.assertNotEqual(self.finish(self.submit())['state'],'succeeded')
    def test_forged_mode_bool_not_success(self):
        self.bridge.result_fault=lambda value:value['defensive_policy'].update(schema_version=True)
        self.assertNotEqual(self.finish(self.submit())['state'],'succeeded')

class DefensivePolicyTests(unittest.TestCase):
    def test_schema_closed_and_bounded(self):
        for key,value in (('window_ms',True),('window_ms',299),('window_ms',2501),('max_distance',4.01),('max_distance',True),('minimum_separation_gain',0),('attack',True)):
            with self.subTest(key=key,value=value),self.assertRaises(ToolboxError):
                validate_schema({'target_uuid':combat.TARGET,key:value},defensive._SCHEMAS['evade_local'])
    def test_policy_numbers_allow_json_integer_double_not_bool(self):
        p={'schema_version':1,'mode':'shield_only','window_ms':1000,'max_distance':0,'minimum_separation_gain':0}
        q={**p,'max_distance':0.,'minimum_separation_gain':0.};self.assertTrue(_same_policy(q,p))
        for k in p:
            bad=deepcopy(q);bad[k]=True;self.assertFalse(_same_policy(bad,p))
    def test_witness_closed_profile_modes_and_exact_fields(self):
        native,scope,ident,intent=combat.fixture();scope['profile']=PROFILE
        intent.update(approach=False,shield=True,timeout_ms=1250,defensive_policy={'schema_version':1,'mode':'shield_only','window_ms':1000,'max_distance':0,'minimum_separation_gain':0})
        value=witness(intent,scope);validate_scoped_witness(value,scope,ident,intent)
        for field,badvalue in [('mode','attack'),('max_distance',True),('window_ms',1001),('schema_version',True),('extra',0)]:
            bad=deepcopy(value);bad['result']['scoped_native_preflight']['facts']['combat']['defensive_policy'][field]=badvalue
            with self.subTest(field=field),self.assertRaises(ValueError):validate_scoped_witness(bad,scope,ident,intent)
        oldscope={**scope,'profile':'combat-local-observed-v1'}
        with self.assertRaises(ValueError):validate_scoped_witness(value,oldscope,ident,intent)
    def test_actual_java_initial_wire_when_supplied(self):
        import os,json
        from pathlib import Path
        wire=os.environ.get('MDC_DEFENSIVE_COMBAT_WIRE')
        if not wire:self.skipTest('Requires emitted production Java policy/initial-evidence HTTP codec fixture')
        data=json.loads(Path(wire).read_text());self.assertEqual(len(data['rows']),2)
        for row in data['rows']:
            self.assertTrue(_same_policy(row['combat']['defensive_policy'],row['request']['defensive_policy']))
            self.assertEqual(row['combat']['attack_dispatches'],0)
            for key in ('offensive_effects_allowed','physical_safe','defensive_completed','server_confirmed'):
                self.assertIs(row['combat'][key],False)
            self.assertIs(row['combat']['risk_remaining'],True)
    def test_catalog_coverage_no_campaign_claim(self):
        c=CapabilityCatalog();self.assertFalse(c.load_errors)
        for name in ('engage','defend_local','evade_local'):
            coverage=c.get(name)['combat_coverage'];self.assertEqual(len(coverage['target_types']),6)
            self.assertEqual(coverage['campaign_targets_supported'],[]);self.assertFalse(coverage['projectile_prediction_supported'])
        self.assertFalse(c.get('defend_local')['combat_coverage']['offensive_effects_allowed'])

if __name__=='__main__':unittest.main()
