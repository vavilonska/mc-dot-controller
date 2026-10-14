from copy import deepcopy
from types import SimpleNamespace
import unittest
from mdc_skills.core import Outcome, SkillError
from mdc_skills import scoped_collect as collect
from mdc_toolbox.catalog import CapabilityCatalog
from mdc_toolbox.runtime_adapter import OwnerRuntimeBackend
from resident_controller.capability_snapshot import validate_scoped_witness
from .collect_fixture import collect_fixture, redigest, UUID, FP

CTX=('world','minecraft:overworld','player','session')
def observation(tick=1, count=0, item='minecraft:coal', component=FP):
    rows=[{'slot':i,'empty':True,'id':'','count':0,'max_stack_size':64,'identity_complete':True} for i in range(36)]
    if count:rows[0].update(empty=False,id=item,count=count,component_fingerprint=component,item_fingerprint=FP)
    stack={'id':'minecraft:coal','count':3,'empty':False,'max_stack_size':64,
           'identity_complete':True,'component_fingerprint':FP,'item_fingerprint':FP}
    target={'uuid':UUID,'entity_id':7,'type':'minecraft:item','class':'net.minecraft.world.entity.item.ItemEntity',
            'alive':True,'x':1.5,'y':64.,'z':.5,'item':stack}
    player={'x':.5,'y':64.,'z':.5,'inventory':rows,'inventory_total':36,'inventory_truncated':False}
    state={'player':player,'nearby':{'truncated':False,'entities':[target]},
           'client_action':{'action_id':'native','action_session':'session'}}
    return SimpleNamespace(player=player,state=state,tick=tick,context=CTX,request_id='obs'+str(tick))

class Runtime:
    _job_scoped_profiles={'follow_path':collect.PROFILE}
    def __init__(self,counts=(3,3,3),status='cancelled',reason='scoped_collect_target_absent',release=True):
        self.first=observation();self.counts=list(counts);self.status=status;self.reason=reason
        self.release=release;self.observes=0;self.actions=[];self.modifier=lambda x:x
    def observe(self,**kw):
        self.observes+=1
        if self.observes==1:return self.first
        sample=observation(self.observes,self.counts[min(self.observes-2,len(self.counts)-1)])
        return self.modifier(sample)
    def sleeper(self,x):pass
    def execute(self,skill,command,verify,**kw):
        self.actions.append(command)
        native={'status':self.status,'action_id':'native','result':{'input_release_confirmed':self.release}}
        return Outcome(self.status,self.reason,('action',),{'native':native,'native_action_id':'native'},self.first)
    def result(self,skill,observations,**evidence):
        return Outcome('succeeded','proof',tuple(o.request_id for o in observations),evidence,observations[-1])

def run(rt,**kwargs):return collect.collect_local(rt,UUID,'minecraft:coal',**kwargs)

class SkillTests(unittest.TestCase):
    def test_target_disappearance_with_typed_delta_preserves_cancellation(self):
        r=Runtime();v=run(r)
        self.assertTrue(v.ok);self.assertEqual(v.evidence['inventory_delta'],3)
        self.assertEqual(v.evidence['movement']['reason'],'scoped_collect_target_absent')
        self.assertFalse(v.evidence['causal_drop_attribution']);self.assertEqual(len(r.actions),1)
        self.assertEqual(r.observes,4)
    def test_external_removal_without_gain_fails_no_retry(self):
        r=Runtime((0,));v=run(r);self.assertFalse(v.ok);self.assertEqual(len(r.actions),1)
    def test_wrong_item_and_component_gain_do_not_count(self):
        for field,value in [('id','minecraft:dirt'),('component_fingerprint','different')]:
            r=Runtime();r.modifier=lambda o,f=field,v=value:(o.player['inventory'][0].update({f:v}) or o)
            self.assertFalse(run(r).ok)
    def test_partial_below_requested_minimum_fails(self):
        self.assertFalse(run(Runtime((1,)),minimum=3).ok)
    def test_partial_above_minimum_reports_actual_only(self):
        v=run(Runtime((1,)),minimum=1);self.assertTrue(v.ok);self.assertEqual(v.evidence['inventory_delta'],1)
    def test_full_inventory_blocks_before_motion(self):
        r=Runtime()
        for row in r.first.player['inventory']:row.update(empty=False,id='minecraft:dirt',count=64,component_fingerprint=FP)
        with self.assertRaisesRegex(SkillError,'capacity'):run(r)
        self.assertFalse(r.actions)
    def test_entire_stack_capacity_even_for_minimum_one(self):
        r=Runtime()
        for row in r.first.player['inventory']:row.update(empty=False,id='minecraft:dirt',count=64,component_fingerprint=FP)
        r.first.player['inventory'][0].update(id='minecraft:coal',count=63)
        with self.assertRaisesRegex(SkillError,'capacity'):run(r)
    def test_unknown_arbitrary_cancel_and_unconfirmed_release_never_verify(self):
        for kw in ({'status':'unknown'}, {'reason':'owner_cancelled'}, {'reason':'scoped_collect_target_identity_changed'},
                   {'reason':'scoped_collect_target_stack_changed'}, {'release':False}):
            r=Runtime(**kw);v=run(r);self.assertFalse(v.ok);self.assertEqual(r.observes,1);self.assertEqual(len(r.actions),1)
    def test_context_or_action_replacement_blocks(self):
        for mutate in (lambda o:setattr(o,'context',('new',*CTX[1:])),
                       lambda o:o.state['client_action'].update(action_id='other')):
            r=Runtime();r.modifier=lambda o:(mutate(o) or o)
            with self.assertRaises(SkillError):run(r)
    def test_stale_ticks_and_unstable_gain_fail(self):
        r=Runtime();r.modifier=lambda o:(setattr(o,'tick',1) or o);self.assertFalse(run(r).ok)
        r=Runtime((1,2,1,2,1,2,1,2,1,2,1,2,1,2,1,2));self.assertFalse(run(r).ok)
    def test_unsupported_and_unnegotiated_block(self):
        r=Runtime();r._job_scoped_profiles={}
        with self.assertRaises(SkillError):run(r)
        self.assertEqual(r.observes,0)
        with self.assertRaises(SkillError):collect.collect_local(Runtime(),UUID,'minecraft:diamond')
    def test_uuid_missing_wrong_type_and_far_target_block(self):
        for change in ({'uuid':'other'},{'type':'minecraft:sheep'},{'x':3.5},{'entity_id':True}):
            r=Runtime();r.first.state['nearby']['entities'][0].update(change)
            with self.assertRaises(SkillError):run(r)
            self.assertFalse(r.actions)
    def test_user_cancel_during_verification_cannot_be_success(self):
        class Control:
            count=0
            def checkpoint(self):
                self.count+=1
                if self.count>1:raise SkillError('owner_cancelled',status='cancelled')
        r=Runtime()
        with self.assertRaisesRegex(SkillError,'owner_cancelled'):run(r,control=Control())

class WitnessTests(unittest.TestCase):
    def test_collect_and_old_movement_witnesses_valid(self):
        for flag in (True,False):validate_scoped_witness(*collect_fixture(flag))
    def test_identity_components_and_request_tampering_rejected(self):
        mutations=[lambda d:d[0]['result']['scoped_native_preflight']['facts']['movement']['pickup_target'].update(count=2),
          lambda d:d[0]['result']['scoped_native_preflight']['facts']['movement']['pickup_target'].update(simple_components=False),
          lambda d:d[0]['result']['scoped_native_preflight']['facts']['movement']['entity_guard']['rows'][0].update(id=9),
          lambda d:d[0]['result']['scoped_native_preflight']['facts']['movement']['entity_guard'].update(permitted_pickup_uuid=FP),
          lambda d:d[0]['result']['scoped_native_preflight']['facts']['movement']['entity_guard']['rows'].clear()]
        for mutation in mutations:
            d=collect_fixture();mutation(d)
            with self.assertRaises(ValueError):validate_scoped_witness(*d)
    def test_living_projectile_or_second_item_not_exempt(self):
        for typ,cls in [('minecraft:sheep','net.minecraft.world.entity.animal.Sheep'),('minecraft:arrow','net.minecraft.world.entity.projectile.Arrow'),('minecraft:item','net.minecraft.world.entity.item.ItemEntity')]:
            d=collect_fixture();g=d[0]['result']['scoped_native_preflight']['facts']['movement']['entity_guard']
            row=deepcopy(g['rows'][0]);row.update(id=8,uuid=FP,type=typ,**{'class':cls},verdict='outside')
            g['rows'].append(row);g.update(enumerated_count=3,live_other_count=2)
            with self.assertRaises(ValueError):validate_scoped_witness(*d)
    def test_moving_or_drifted_target_witness_rejected(self):
        for key,value in [('velocity',[.004,0.,0.]),('velocity',[0.,-.16,0.]),('velocity',[0.,.001,0.]),('position',[1.531,64.,.5]),('lerp_target',[1.6,64.,.5])]:
            d=collect_fixture();d[0]['result']['scoped_native_preflight']['facts']['movement']['entity_guard']['rows'][0][key]=value
            with self.assertRaises(ValueError):validate_scoped_witness(*d)
    def test_authentic_grounded_gravity_cycle_and_bounded_horizontal_rest(self):
        for vy in (0.,-.04,-.08,-.12):
            d=collect_fixture();g=d[0]['result']['scoped_native_preflight']['facts']['movement']['entity_guard']
            r=g['rows'][0];r.update(position=[1.51,64.,.5],lerp_target=[1.51,64.,.5],velocity=[.001,vy,0.])
            r['aabb']=[1.385,64.,.375,1.635,64.25,.625]
            r['projected_aabb']=[1.385,64.+160*vy,.375,1.635+160*.001,64.25,.625]
            validate_scoped_witness(*d)
    def test_resting_proof_flags_required(self):
        for change in ({'on_ground':False},{'resting_envelope':'moving-allowed'}):
            d=collect_fixture();d[0]['result']['scoped_native_preflight']['facts']['movement']['pickup_target'].update(change)
            with self.assertRaises(ValueError):validate_scoped_witness(*d)
    def test_old_movement_cannot_borrow_pickup_exemption(self):
        d=collect_fixture();d[1]['profile']='movement-flat-observed-v2'
        w=d[0]['result']['scoped_native_preflight'];w['profile']=d[1]['profile'];w['facts']['movement']['profile']=d[1]['profile']
        with self.assertRaises(ValueError):validate_scoped_witness(*d)

class CatalogTests(unittest.TestCase):
    def test_schema_only_explicit_target_no_planner(self):
        cat=CapabilityCatalog();self.assertFalse(cat.load_errors)
        args={'target_uuid':UUID,'item_id':'minecraft:coal'};cat.validate('collect_local',1,args)
        for extra in ({'max_targets':2},{'auto_move':True},{'item_id':'minecraft:diamond'},{'target_uuid':'bad'}):
            with self.assertRaises(Exception):cat.validate('collect_local',1,{**args,**extra})
    def test_profile_negotiation_separate_from_movement(self):
        session={'state':'ready','session_id':'s','private_singleplayer':True,'capability_lease_schema_version':1,
          'capability_context':dict(zip(('world_generation','dimension','player_uuid','action_session'),CTX)),
          'scoped_native_preflight':{'version':'scoped-native-preflight/1','same_callback_capture_validate_admit':True,
            'private_singleplayer_only':True,'profiles':{'movement-flat-observed-v2':['follow_path']}}}
        rt=SimpleNamespace(client=SimpleNamespace(session=lambda:session),has_unresolved_execution=False)
        b=OwnerRuntimeBackend(rt);self.assertNotIn('collect_local',b.describe()['supported_capabilities'])
        session['scoped_native_preflight']['profiles'][collect.PROFILE]=['follow_path']
        self.assertIn('collect_local',b.describe()['supported_capabilities'])
        self.assertEqual(b._profile_actions(b.describe())['follow_path'],'movement-flat-observed-v2')

if __name__=='__main__':unittest.main()
