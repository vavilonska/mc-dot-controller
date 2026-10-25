"""Synthetic observations only: real public bindings and production semantic predicates."""
from copy import deepcopy
from types import SimpleNamespace
import unittest
from mdc_skills import scoped_item_interaction as item, scoped_portal_entry as portal
from mdc_skills.core import Outcome,SkillError
from mdc_toolbox.bindings import typed_portals as binding
from mdc_toolbox.contracts import validate_schema,ToolboxError


def cell(p,id='minecraft:air',props=None):
    return {**p,'id':id,'properties':props or {},'status':'loaded','known':True,'id_truncated':False,'properties_truncated':False,
        'collision_known':True,'fluid':'minecraft:empty','fluid_truncated':False,'hazards':[],
        'full_top_support':id in ('minecraft:stone','minecraft:obsidian'),'collision_empty':id in ('minecraft:air','minecraft:nether_portal','minecraft:end_portal')}


def observation(which='flint'):
    empty={'id':'minecraft:air','count':0,'empty':True,'item_fingerprint':'e','component_fingerprint':'e','max_stack_size':0}
    rows=[dict(empty,slot=i) for i in range(36)]
    rows[0].update(id='minecraft:flint_and_steel' if which=='flint' else 'minecraft:ender_eye',count=1 if which=='flint' else 3,
        empty=False,item_fingerprint='held',component_fingerprint='plain',max_stack_size=1 if which=='flint' else 64,damage=4 if which=='flint' else 0,max_damage=64 if which=='flint' else 0)
    p={'inventory':rows,'inventory_total':36,'inventory_truncated':False,'selected_slot':0,'x':.5,'y':64.,'z':.5,
        'offhand':empty,'armor':[],'alive':True,'on_ground':True,'health':20}
    p.update({k:False for k in portal.dimensions.threats.ENVIRONMENT_FLAGS})
    world={'world_generation':'w','dimension':'minecraft:overworld','integrated_server_instance':'server'}
    o=SimpleNamespace(context=('w','minecraft:overworld','p','s'),player=p,state={'world':world},
        terrain={'complete':True,'world_generation':'w','dimension':'minecraft:overworld','cells':[]})
    if which=='flint':
        base={'x':2,'y':64,'z':0}
        for u,v in [(u,v) for u in range(2) for v in (-1,3)]+[(u,v) for u in (-1,2) for v in range(3)]:o.terrain['cells'].append(cell({'x':base['x']+u,'y':base['y']+v,'z':0},'minecraft:obsidian'))
        for u in range(2):
            for v in range(3):o.terrain['cells'].append(cell({'x':base['x']+u,'y':base['y']+v,'z':0}))
    else:
        base={'x':3,'y':63,'z':0}
        for p,facing in item.dimensions.end_portal_frames(base):o.terrain['cells'].append(cell(p,'minecraft:end_portal_frame',{'facing':facing,'eye':'false'}))
        for x in range(3):
            for z in range(3):o.terrain['cells'].append(cell(item.dimensions._offset(base,x=x,z=z)))
    return o


class Runtime:
    required_execution_policy='request_only'
    def __init__(self,before):self.before=before;self.calls=[];self.profile=item.PROFILE
    def scoped_profile(self,action):return self.profile
    def observe(self,**kwargs):self.calls.append(('observe',kwargs));return self.before
    def execute(self,name,command,verify,**kwargs):self.calls.append(('execute',name,command,verify,kwargs));return Outcome('cancelled','synthetic-no-effect')


class Tests(unittest.TestCase):
    def test_flint_one_closed_use(self):
        r=Runtime(observation());out=item.ignite_portal_local(r,{'x':2,'y':64,'z':0});c=r.calls[-1][2]
        self.assertEqual(c['action'],'interact_block');self.assertEqual(c['target'],{'x':2,'y':63,'z':0});self.assertEqual(c['item_hit']['y'],64)
        self.assertEqual(len(c['item_footprint']),16);self.assertNotIn('hotbar_slot',c);self.assertFalse(out.evidence['automatic_replay_allowed'])
    def test_eye_exact_one_insertion_and_last_eye_footprint(self):
        for last in (False,True):
            r=Runtime(observation('eye'));target={'x':3,'y':63,'z':-1}
            if last:
                for c in r.before.terrain['cells']:
                    if c['id']=='minecraft:end_portal_frame' and any(c[k]!=target[k] for k in target):c['properties']['eye']='true'
            item.insert_end_eye_local(r,{'x':3,'y':63,'z':0},target);command=r.calls[-1][2]
            self.assertEqual(command['item_hit']['y'],63+13/16)
            changed=[row for row in command['item_footprint'] if row['expected_id']!=row['block_id'] or row['expected_properties']!=row['properties']]
            self.assertEqual(len(changed),10 if last else 1)
            self.assertEqual(sum(row['block_id']=='minecraft:end_portal_frame' and row['expected_properties']!=row['properties'] for row in changed),1)
    def test_refuse_wrong_profile_and_malformed_geometry_before_execute(self):
        for mutate in (lambda r:setattr(r,'profile','block-menu-v1'),lambda r:setattr(r,'required_execution_policy','standard'),
                       lambda r:r.before.player['inventory'][0].update(damage=63),lambda r:r.before.terrain['cells'].pop()):
            r=Runtime(observation());mutate(r)
            with self.assertRaises(SkillError):item.ignite_portal_local(r,{'x':2,'y':64,'z':0})
            self.assertFalse(any(c[0]=='execute' for c in r.calls))
    def test_flint_semantic_outcomes_are_independent(self):
        r=Runtime(observation());item.ignite_portal_local(r,{'x':2,'y':64,'z':0});c=r.calls[-1][2]
        before=r.before;after=deepcopy(before);after.player['inventory'][0].update(damage=5,component_fingerprint='damage5')
        for row in c['item_footprint']:
            found=next(v for v in after.terrain['cells'] if all(v[k]==row['position'][k] for k in ('x','y','z')));found.update(id=row['block_id'],properties=row['properties'])
        proof={'profile':item.PROFILE,'kind':'ignite_nether_portal','target':c['target'],'effect_attempted':True,'use_count':1,'packet_count':1,'local_effect_count':1,'selected_slot':0,
            'input_neutral':True,'unknown_outcome':False,'protected_inventory_unchanged':True,'consumption_verified':True,'durability_verified':True,
            'block_outcome_verified':True,'automatic_replay_allowed':False,'server_confirmed':False,'initial_damage':4,'final_damage':5,'initial_count':1,'final_count':1}
        after.state['client_action']={'action':'interact_block','status':'succeeded','result':{'input_release_confirmed':True,'item_interaction':proof}}
        verify=r.calls[-1][3];self.assertTrue(verify(before,after))
        for key,value in [('packet_count',True),('use_count',2),('consumption_verified',False),('durability_verified',False),('block_outcome_verified',False),('unknown_outcome',True)]:
            bad=deepcopy(after);bad.state['client_action']['result']['item_interaction'][key]=value;self.assertFalse(verify(before,bad))
        bad=deepcopy(after);bad.player['inventory'][0]['damage']=4;self.assertFalse(verify(before,bad))
        bad=deepcopy(after);bad.player['inventory'][1]['component_fingerprint']='tampered';self.assertFalse(verify(before,bad))
        bad=deepcopy(after);next(v for v in bad.terrain['cells'] if v['id']=='minecraft:nether_portal')['id']='minecraft:fire';self.assertFalse(verify(before,bad))
    def test_public_definitions_closed_no_composites(self):
        definitions=binding.definitions();self.assertEqual({d['capability'] for d in definitions},set(binding._SCHEMAS))
        for d in definitions:
            self.assertEqual(d['level'],'primitive');self.assertFalse(d['resume_supported']);self.assertFalse(d['planner_available'])
        for name,args in [('ignite_portal_local',{'interior_base':{'x':2,'y':64,'z':0}}),
                          ('insert_end_eye_local',{'interior_corner':{'x':3,'y':63,'z':0},'target':{'x':3,'y':63,'z':-1}}),
                          ('enter_portal_local',{'portal_cell':{'x':1,'y':64,'z':0},'destination':'minecraft:the_nether'})]:
            validate_schema(args,binding._SCHEMAS[name])
            for key in ('hotbar_slot','raw_input','item_footprint','expected_dimension','allow_drop'):
                with self.assertRaises(ToolboxError):validate_schema({**args,key:True},binding._SCHEMAS[name])
    def test_portal_prepared_corridor_and_destination_binding(self):
        o=observation();o.terrain['cells']=[cell({'x':x,'y':y,'z':0},'minecraft:stone' if y==63 else 'minecraft:nether_portal' if x==1 and y==64 else 'minecraft:air',{'axis':'x'} if x==1 and y==64 else {}) for x in (0,1) for y in (63,64,65)]
        r=Runtime(o);r.profile=portal.PROFILE;portal.enter_portal_local(r,{'x':1,'y':64,'z':0},'minecraft:the_nether')
        c=r.calls[-1][2];self.assertEqual(c['typed_portal_entry']['destination'],'minecraft:the_nether');self.assertEqual(r.calls[-1][4]['allowed_dimension'],'minecraft:the_nether')
        self.assertNotIn('capability_route',c);self.assertEqual(c['waypoints'],[{'x':1.5,'y':64,'z':.5,'jump':False}])
        for v in o.terrain['cells']:
            if v['x']==1 and v['y']==63:v['full_top_support']=False
        with self.assertRaises(SkillError):portal.enter_portal_local(r,{'x':1,'y':64,'z':0},'minecraft:the_nether')

if __name__=='__main__':unittest.main()
