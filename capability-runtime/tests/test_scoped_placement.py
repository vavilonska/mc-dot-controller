"""Producer and public binding tests; no native geometry or game effects."""
from copy import deepcopy
from types import SimpleNamespace
import unittest
from mdc_skills import scoped_placement as p
from mdc_skills.core import Outcome, SkillError
from mdc_toolbox.catalog import CapabilityCatalog
from mdc_toolbox.runtime_adapter import OwnerRuntimeBackend
from mdc_toolbox.contracts import ToolboxError

ARGS = {'support':{'x':2,'y':63,'z':0},'face':'up','expected_support_id':'minecraft:stone',
        'expected_support_properties':{},'expected_block_id':p.BLOCK,'expected_block_properties':{}}

def observation(count=5):
    empty={'id':'minecraft:air','count':0,'empty':True,'item_fingerprint':'e','component_fingerprint':'e','max_stack_size':0}
    rows=[dict(empty,slot=i) for i in range(36)]
    if count: rows[0].update(id=p.BLOCK,count=count,empty=False,item_fingerprint='count-'+str(count),component_fingerprint='plain',max_stack_size=64)
    player={'inventory':rows,'inventory_total':36,'inventory_truncated':False,'selected_slot':0}
    return SimpleNamespace(context=('w','minecraft:overworld','p','s'),player=player,state={})

class Runtime:
    required_execution_policy='request_only'
    _job_scoped_profiles={'place_block':p.PROFILE}
    def __init__(self):self.before=observation();self.calls=[]
    def observe(self,**kwargs):self.calls.append(('observe',kwargs));return self.before
    def execute(self,name,command,verify,**kwargs):
        self.calls.append(('execute',name,command,verify,kwargs));return Outcome('cancelled','test-no-effect')

class ProducerTests(unittest.TestCase):
    def test_single_exact_intent_and_no_movement(self):
        r=Runtime();out=p.place_local(r,**ARGS)
        self.assertEqual(out.status,'cancelled');self.assertIs(out.evidence['automatic_replay_allowed'],False)
        self.assertEqual(len(r.calls),2);c=r.calls[1][2]
        self.assertEqual(c['placement_hit'],{'x':2.5,'y':64.,'z':.5})
        self.assertEqual(c['placement_footprint'],[{'position':{'x':2,'y':64,'z':0},'expected_id':'minecraft:air',
            'expected_properties':{},'block_id':p.BLOCK,'properties':{}}])
        self.assertEqual(c['timeout_ms'],2000)
        for k in ('hotbar_slot','jump','sneak','capability_bridge','coordination_step','placement_yaw'):self.assertNotIn(k,c)
    def test_profile_policy_and_material_fail_before_dispatch(self):
        for attr,value in [('_job_scoped_profiles',{}),('required_execution_policy','standard')]:
            r=Runtime();setattr(r,attr,value)
            with self.assertRaises(SkillError):p.place_local(r,**ARGS)
            self.assertFalse(r.calls)
        for changed in ({'expected_block_id':'minecraft:dirt'},{'expected_support_properties':{'snowy':'false'}},
                        {'face':'bad'},{'support':{'x':2,'y':63,'z':0,'extra':1}}):
            r=Runtime()
            with self.assertRaises(SkillError):p.place_local(r,**{**ARGS,**changed})
            self.assertFalse(r.calls)
    def test_independent_exact_decrement_and_other_inventory(self):
        before,after=observation(),observation(4);target={'x':2,'y':64,'z':0}
        proof={'profile':p.PROFILE,'target':target,'block_placed':True,'effect_attempted':True,'effect_count':1,
               'packet_count':1,'input_neutral':True,'unknown_outcome':False,'protected_inventory_unchanged':True,
               'automatic_replay_allowed':False,'server_confirmed':False,'initial_count':5,'final_count':4,'selected_slot':0}
        after.state={'client_action':{'action':'place_block','status':'succeeded','result':{'input_release_confirmed':True,'placement':proof}}}
        self.assertTrue(p._placed(before,after,target,0))
        for count in (3,5,6):
            bad=deepcopy(after);bad.player['inventory'][0]['count']=count
            self.assertFalse(p._placed(before,bad,target,0))
        bad=deepcopy(after);bad.player['inventory'][1]['component_fingerprint']='changed'
        self.assertFalse(p._placed(before,bad,target,0))
        for key,value in [('packet_count',True),('effect_count',2),('unknown_outcome',True),('protected_inventory_unchanged',False)]:
            bad=deepcopy(after);bad.state['client_action']['result']['placement'][key]=value
            self.assertFalse(p._placed(before,bad,target,0))
    def test_public_schema_closed_and_build_stays_unavailable(self):
        c=CapabilityCatalog();entry=c.validate('place_local',1,ARGS)
        self.assertEqual(entry['level'],'primitive');self.assertEqual(entry['group'],'building')
        self.assertFalse(entry['planner_available']);self.assertFalse(entry['resume_supported'])
        for key in ('hotbar_slot','placement_hit','placement_footprint','jump','timeout_ms'):
            with self.assertRaises(ToolboxError):c.validate('place_local',1,{**ARGS,key:1})
        self.assertNotIn('build',OwnerRuntimeBackend.INITIAL_CAPABILITIES)
        self.assertNotIn('build_with_materials',OwnerRuntimeBackend.INITIAL_CAPABILITIES)
        backend=OwnerRuntimeBackend(SimpleNamespace())
        self.assertEqual(backend._profile_actions({'scoped_profiles':{p.PROFILE:['place_block']}}),{'place_block':p.PROFILE})
        self.assertEqual(backend._profile_actions({'scoped_profiles':{p.PROFILE:['place_block','follow_path']}}),{})


class WorkstationTests(unittest.TestCase):
    def arguments(self, material, properties):
        return {**ARGS, 'expected_block_id': material, 'expected_block_properties': properties}

    def test_exact_workstation_intent_material_and_inventory_binding(self):
        for material, properties in [('minecraft:crafting_table', {})] + [
                ('minecraft:furnace', {'facing': face, 'lit': 'false'}) for face in p.HORIZONTAL_FACES]:
            with self.subTest(material=material, properties=properties):
                args=self.arguments(material, properties)
                CapabilityCatalog().validate('place_local', 1, args)
                r=Runtime();r.before.player['inventory'][0]['id']=material
                p.place_local(r, **args)
                command=r.calls[1][2]
                self.assertEqual(command['expected_block_id'],material)
                self.assertEqual(command['expected_block_properties'],properties)
                self.assertEqual(command['placement_footprint'][0]['block_id'],material)
                self.assertEqual(command['placement_footprint'][0]['properties'],properties)
                properties['extra']='caller-mutation'
                self.assertNotIn('extra',command['expected_block_properties'])
                self.assertNotIn('extra',command['placement_footprint'][0]['properties'])

    def test_materials_properties_and_original_support_vocab_are_closed(self):
        invalid=[('minecraft:furnace', {}), ('minecraft:furnace', {'facing':'up','lit':'false'}),
                 ('minecraft:furnace', {'facing':'north','lit':False}),
                 ('minecraft:furnace', {'facing':'north','lit':'true'}),
                 ('minecraft:furnace', {'facing':'north','lit':'false','extra':'x'}),
                 ('minecraft:crafting_table', {'facing':'north'}),
                 ('minecraft:blast_furnace', {'facing':'north','lit':'false'}),
                 ('minecraft:smoker', {'facing':'north','lit':'false'}), ('minecraft:chest', {})]
        for material, properties in invalid:
            args=self.arguments(material,properties);r=Runtime()
            with self.subTest(args=args), self.assertRaises(SkillError):p.place_local(r,**args)
            self.assertFalse(r.calls)
            with self.assertRaises(ToolboxError):CapabilityCatalog().validate('place_local',1,args)
        for support in ('minecraft:jungle_log','minecraft:iron_ore','minecraft:crafting_table','minecraft:furnace'):
            args={**ARGS,'expected_support_id':support};r=Runtime()
            with self.assertRaises(SkillError):p.place_local(r,**args)
            self.assertFalse(r.calls)
            with self.assertRaises(ToolboxError):CapabilityCatalog().validate('place_local',1,args)

    def test_wrong_selected_material_cannot_dispatch(self):
        for material in ('minecraft:crafting_table','minecraft:furnace'):
            properties={'facing':'north','lit':'false'} if material.endswith('furnace') else {}
            r=Runtime()
            with self.assertRaises(SkillError):p.place_local(r,**self.arguments(material,properties))
            self.assertEqual([call[0] for call in r.calls],['observe'])

    def test_workstation_selected_decrement_accepts_only_same_material(self):
        for material in ('minecraft:crafting_table','minecraft:furnace'):
            before,after=observation(),observation(4);target={'x':2,'y':64,'z':0}
            before.player['inventory'][0]['id']=material;after.player['inventory'][0]['id']=material
            proof={'profile':p.PROFILE,'target':target,'block_placed':True,'effect_attempted':True,'effect_count':1,
                'packet_count':1,'input_neutral':True,'unknown_outcome':False,'protected_inventory_unchanged':True,
                'automatic_replay_allowed':False,'server_confirmed':False,'initial_count':5,'final_count':4,'selected_slot':0}
            after.state={'client_action':{'action':'place_block','status':'succeeded','result':{'input_release_confirmed':True,'placement':proof}}}
            self.assertTrue(p._placed(before,after,target,0,material))
            after.player['inventory'][0]['id']=p.BLOCK
            self.assertFalse(p._placed(before,after,target,0,material))

if __name__=='__main__':unittest.main()
