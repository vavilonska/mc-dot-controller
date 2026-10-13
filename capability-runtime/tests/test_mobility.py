"""Synthetic policy and real command wiring; deliberately not a live gameplay claim."""
import copy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from mdc_skills import mobility, reach
from mdc_skills.core import SkillError, Outcome
from test_reach_inventory_resources import observation,cell,stack,FakeRuntime

class Advancing(FakeRuntime):
    def execute(self,skill,command,verify,**options):
        self.commands.append(command)
        new=copy.deepcopy(self.before)
        if command['action']=='follow_path':
            end=command['waypoints'][-1]
            new.player.update({k:end[k] for k in ('x','y','z')})
        result=Outcome(self.outcome,'synthetic',('id'+str(len(self.commands)),),{},new)
        if not verify(options['before'],new):return Outcome('failed','semantic',result.request_ids,{},new)
        self.before=new
        return result

class MobilityTests(unittest.TestCase):
    def test_cardinal_step_up_and_down_are_loaded_and_headroom_bound(self):
        obs=observation()
        next(c for c in obs.terrain['cells'] if (c['x'],c['y'],c['z'])==(1,64,0)).update(cell(1,64,0,'minecraft:stone'))
        obs.terrain['cells'].append(cell(1,67,0))
        grid,_=reach._grid(obs);a=reach.Block(0,64,0);b=reach.Block(1,65,0)
        self.assertTrue(mobility.safe_edge(grid,a,b));self.assertTrue(mobility.safe_edge(grid,b,a))
        head=next(c for c in obs.terrain['cells'] if (c['x'],c['y'],c['z'])==(0,66,0));head['known']=False
        grid,_=reach._grid(obs);self.assertFalse(mobility.safe_edge(grid,a,b))
    def test_diagonal_corner_and_void_block_routes(self):
        obs=observation();obs.terrain['cells']=[c for c in obs.terrain['cells'] if (c['x'],c['y'],c['z'])!=(1,63,0)]
        grid,_=reach._grid(obs)
        self.assertFalse(mobility.safe_edge(grid,reach.Block(0,64,0),reach.Block(1,64,1)))
        self.assertFalse(mobility.safe_edge(grid,reach.Block(0,64,0),reach.Block(1,64,0)))
    def test_navigation_emits_guarded_adjacent_route_and_real_arrival(self):
        rt=Advancing(observation());result=mobility.navigate_loaded(rt,{'x':3,'y':64,'z':0})
        self.assertTrue(result.ok);cmd=rt.commands[0]
        self.assertEqual(cmd['action'],'follow_path');self.assertTrue(cmd['capability_route'])
        self.assertEqual(cmd['waypoints'][-1],dict(x=3.5,y=64,z=.5,jump=False))
        self.assertEqual(cmd['min_health'],12)
    def test_failed_segment_never_replayed(self):
        rt=Advancing(observation(),outcome='unknown')
        result=mobility.navigate_loaded(rt,{'x':30,'y':64,'z':0})
        self.assertFalse(result.ok);self.assertEqual(result.status,'unknown');self.assertEqual(len(rt.commands),1)
    def test_far_goal_has_finite_segment_budget(self):
        rt=Advancing(observation())
        with self.assertRaisesRegex(SkillError,'segment_budget_exhausted'):
            mobility.navigate_loaded(rt,{'x':30,'y':64,'z':0},max_segments=1)
        self.assertEqual(len(rt.commands),1)
    def test_end_requires_actual_pumpkin_and_calm_endermen(self):
        obs=observation(dimension='minecraft:the_end')
        with self.assertRaisesRegex(SkillError,'pumpkin'):mobility._safety(obs,12)
        obs.player['armor']=[{**stack('minecraft:carved_pumpkin',1),'slot':'head'}]
        obs.state['nearby']['entities']=[{'type':'minecraft:enderman','alive':True,'aggressive':False}]
        self.assertTrue(mobility._safety(obs,12)['require_pumpkin'])
        obs.state['nearby']['entities'][0]['aggressive']=True
        with self.assertRaisesRegex(SkillError,'aggressive'):mobility._safety(obs,12)
    def test_pillar_rejects_unknown_headroom_before_mutation(self):
        rt=FakeRuntime(observation())
        with patch.object(mobility,'_material',return_value=0):
            with self.assertRaisesRegex(SkillError,'headroom'):mobility.pillar_up(rt)
        self.assertFalse(rt.commands)
    def test_descent_never_mines_into_unknown_or_void(self):
        rt=FakeRuntime(observation())
        with self.assertRaisesRegex(SkillError,'lower_support'):mobility.pillar_down(rt,'minecraft:stone')
        self.assertFalse(rt.commands)
    def test_descent_requires_exact_expected_pillar_block(self):
        obs=observation();obs.terrain['cells'].append(cell(0,62,0,'minecraft:stone'))
        rt=FakeRuntime(obs)
        with self.assertRaisesRegex(SkillError,'support_changed'):mobility.pillar_down(rt,'minecraft:cobblestone')
        self.assertFalse(rt.commands)
    def test_bridge_uses_native_bounded_sneak_edge_then_no_replay(self):
        obs=observation();c=next(c for c in obs.terrain['cells'] if(c['x'],c['y'],c['z'])==(1,63,0));c.update(cell(1,63,0))
        obs.player['inventory'][0].update(stack('minecraft:cobblestone',4))
        rt=FakeRuntime(obs,outcome='unknown')
        with patch.object(mobility,'_material',return_value=0):
            with self.assertRaises(SkillError):mobility.bridge_step(rt,{'x':1,'z':0})
        self.assertEqual(len(rt.commands),1);self.assertTrue(rt.commands[0]['capability_bridge']);self.assertTrue(rt.commands[0]['sneak'])
    def test_water_corridor_needs_two_source_layers_and_three_air_layers(self):
        obs=observation();obs.terrain['cells']=[]
        for x in range(-1,2):
            for z in range(-1,2):
                for y in range(62,67):
                    c=cell(x,y,z)
                    if y<64:c.update(id='minecraft:water',fluid='minecraft:water',fluid_source=True,air=False,hazards=['water'])
                    obs.terrain['cells'].append(c)
        self.assertTrue(mobility.water_column(obs,0,0,64))
        obs.terrain['cells'][0]['fluid_source']=False
        self.assertFalse(mobility.water_column(obs,0,0,64))
    def test_boat_identity_must_be_sole_ordinary_driver(self):
        obs=observation();obs.player['uuid']='player';obs.player['vehicle']={
            'riding':True,'ordinary_boat':True,'controlling_seat':True,'alive':True,'type':'minecraft:boat','passengers':['player'],'uuid':'boat'}
        self.assertEqual(mobility._vehicle(obs)['uuid'],'boat')
        obs.player['vehicle']['passengers'].append('other')
        with self.assertRaisesRegex(SkillError,'sole_boat_passenger'):mobility._vehicle(obs)
    def test_real_empty_hand_selector_is_exact_and_allows_mount_preparation(self):
        before=observation(selected=0);after=observation(12,selected=1)
        rt=FakeRuntime(before,after)
        result=mobility._select_empty(rt,1)
        self.assertTrue(result.ok);self.assertEqual(rt.commands[0]['action'],'select_hotbar')
        self.assertTrue(rt.commands[0]['expected_held_item']['empty'])
        with self.assertRaisesRegex(SkillError,'exact_empty'):mobility._select_empty(FakeRuntime(before),0)
    def test_stair_top_treads_and_top_slabs_keep_real_height_and_no_partial_diagonal(self):
        obs=observation()
        a=next(c for c in obs.terrain['cells'] if(c['x'],c['y'],c['z'])==(0,63,0))
        a.update(id='minecraft:oak_stairs',properties={'facing':'north','half':'bottom','shape':'outer_left','waterlogged':'false'},full_top_support=False)
        grid,_=reach._grid(obs)
        self.assertTrue(grid.standable(reach.Block(0,64,0)))
        self.assertTrue(mobility.safe_edge(grid,reach.Block(0,64,0),reach.Block(1,64,0)))
        self.assertFalse(mobility.safe_edge(grid,reach.Block(0,64,0),reach.Block(1,64,1)))
        a.update(id='minecraft:oak_slab',properties={'type':'bottom','waterlogged':'false'},collision_bounds=[0,0,0,1,.5,1])
        self.assertFalse(reach._grid(obs)[0].standable(reach.Block(0,64,0)))
        a.update(properties={'type':'top','waterlogged':'false'},collision_bounds=[0,.5,0,1,1,1])
        self.assertTrue(reach._grid(obs)[0].standable(reach.Block(0,64,0)))
        a['properties']['waterlogged']='true'
        self.assertFalse(reach._grid(obs)[0].standable(reach.Block(0,64,0)))
    def test_gateway_does_not_accept_missing_fresh_discovery(self):
        obs=observation(dimension='minecraft:the_end');obs.player['armor']=[{**stack('minecraft:carved_pumpkin',1),'slot':'head'}]
        rt=FakeRuntime(obs)
        with patch('mdc_skills.inventory.ensure_hotbar',return_value=Outcome('succeeded','selected',(),{},obs)):
            with self.assertRaisesRegex(SkillError,'gateway_discovery'):mobility.gateway_pearl(rt,dict(x=3,y=65,z=0))
        self.assertFalse(rt.commands)

if __name__=='__main__':unittest.main()
