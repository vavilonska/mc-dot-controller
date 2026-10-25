from copy import deepcopy
import unittest
from test_threats_dimensions import observation as base_observation, mob, FakeRuntime
from mdc_skills import scoped_target_action as target
from mdc_skills.core import SkillError
from mdc_toolbox.bindings import target_actions
from mdc_toolbox.contracts import validate_schema, ToolboxError

def observation(**kwargs):
    value=base_observation(**kwargs)
    value.player['inventory']=[{'slot':0,'id':'minecraft:iron_axe','count':1}]
    value.player['inventory_total']=1
    return value

class Runtime(FakeRuntime):
    required_execution_policy='request_only'
    _job_scoped_profiles={action:target.PROFILE for action in target.ACTIONS}

def proof(after,kind='minecraft:zombie',ranged=False):
    after.state['client_action']={'status':'succeeded','action':'shoot_entity' if ranged else 'attack_entity',
        'result':{'input_release_confirmed':True,'target_scope':dict(profile=target.PROFILE,target_entity_id=1,
        target_uuid='target',target_type=kind,offense_effects=1,offense_packets=1,draw_effects=int(ranged),draw_packets=int(ranged),
        shield_use_effects=0,shield_use_packets=0,shield_release_effects=0,shield_release_packets=0,
        input_neutral=True,unknown_outcome=False,automatic_replay_allowed=False,server_confirmed=False)}}
    return after

class ProducerTests(unittest.TestCase):
    def test_strike_needs_damage_and_exact_native_effect_cleanup(self):
        for hp,good in ((20,False),(19,True),(0,True)):
            rt=Runtime([observation(mobs=[mob()])],[proof(observation(tick=2,mobs=[mob(health=hp)]))])
            self.assertEqual(target.strike(rt,'target').ok,good);self.assertEqual(len(rt.commands),1)
        rt=Runtime([observation(mobs=[mob()])],[observation(tick=2,mobs=[mob(health=19)])])
        self.assertFalse(target.strike(rt,'target').ok)
    def test_unknown_no_retry_and_profile_before_reads(self):
        rt=Runtime([observation(mobs=[mob()])],status='unknown')
        self.assertEqual(target.strike(rt,'target').status,'unknown');self.assertEqual(len(rt.commands),1)
        for key,value in (('required_execution_policy','standard'),('_job_scoped_profiles',{})):
            rt=Runtime([]);setattr(rt,key,value)
            with self.assertRaises(SkillError):target.strike(rt,'target')
            self.assertFalse(rt.commands)
    def test_wrong_identity_or_duplicate_packet_not_success(self):
        for key,value in (('target_uuid','other'),('offense_packets',2),('offense_effects',True),('input_neutral',False),('unknown_outcome',True)):
            after=proof(observation(tick=2,mobs=[mob(health=18)]));after.state['client_action']['result']['target_scope'][key]=value
            rt=Runtime([observation(mobs=[mob()])],[after]);self.assertFalse(target.strike(rt,'target').ok)
    def test_crystal_selected_bow_single_action_and_local_removal(self):
        crystal=mob(kind='minecraft:end_crystal');crystal.update(x=13.5,z=.5)
        for missing in (False,True):
            before=observation(mobs=[crystal]);before.player['inventory']=[{'slot':0,'id':'minecraft:bow','count':1}]
            after=proof(observation(tick=2,mobs=[] if missing else [crystal]),'minecraft:end_crystal',True)
            rt=Runtime([before],[after]);out=target.remove_crystal(rt,'target')
            self.assertEqual(out.ok,missing);self.assertEqual(len(rt.commands),1)
            self.assertFalse(out.evidence['all_world_crystals_absent']);self.assertFalse(out.evidence['destruction_attributed_to_action'])
            self.assertNotIn('hotbar_slot',rt.commands[0][1])
    def test_crystal_no_equipment_setup_or_weak_reserve(self):
        crystal=mob(kind='minecraft:end_crystal');crystal.update(x=13.5,z=.5)
        rt=Runtime([observation(mobs=[crystal])])
        with self.assertRaisesRegex(SkillError,'selected_bow'):target.remove_crystal(rt,'target')
        self.assertFalse(rt.commands)
        with self.assertRaises(SkillError):target.remove_crystal(Runtime([]),'target',min_health=10)
    def test_sword_refused_before_native_dispatch(self):
        before=observation(mobs=[mob()]);before.player['inventory'][0]['id']='minecraft:iron_sword'
        rt=Runtime([before])
        with self.assertRaisesRegex(SkillError,'nonsweeping_axe'):target.strike(rt,'target')
        self.assertFalse(rt.commands)
    def test_public_definitions_exact_two_primitives(self):
        values=target_actions.definitions();self.assertEqual({v['capability'] for v in values},{'strike','remove_crystal'})
        for v in values:
            self.assertEqual(v['level'],'primitive');self.assertFalse(v['planner_available']);self.assertFalse(v['resume_supported'])
        for name,args in [('strike',{'target_uuid':'target','max_actions':2}),('remove_crystal',{'target_uuid':'target','hotbar_slot':0})]:
            with self.assertRaises(ToolboxError):validate_schema(args,target_actions._SCHEMAS[name])

if __name__=='__main__':unittest.main()
