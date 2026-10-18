"""Survival vocabulary and public owner-chain checks. Native endpoint facts are synthetic."""
from copy import deepcopy
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from resident_controller.capability_snapshot import validate_scoped_witness
from resident_controller import mining_snapshot, placement_snapshot
from mdc_skills import scoped_mining, scoped_placement
from mdc_skills.core import SkillError
from mdc_toolbox.catalog import CapabilityCatalog
from .mining_fixture import mining_fixture
from .test_mining_chain import PublicMiningChainTests

LOGS=('oak','spruce','birch','jungle','acacia','dark_oak')

def fixture(block='minecraft:jungle_log',properties=None):
    old=mining_fixture();intent=deepcopy(old[3]);intent['expected_block_id']=block
    intent['expected_block_properties']=({'axis':'y'} if block.endswith('_log') else {}) if properties is None else properties
    return mining_fixture(intent)

def cell(d,xyz,block,cls,properties,full=True):
    m=d[0]['result']['scoped_native_preflight']['facts']['mining']
    row=next(r for r in m['cells'] if tuple(r[k] for k in ('x','y','z'))==xyz)
    row.update(id=block,block_class='net.minecraft.world.level.block.'+cls,properties=properties,air=False,static_full_cube=full)
    return row

class SurvivalVocabularyTests(unittest.TestCase):
    def test_each_log_axis_and_both_iron_ores(self):
        cat=CapabilityCatalog()
        for kind in LOGS:
            for axis in ('x','y','z'):
                d=fixture('minecraft:'+kind+'_log',{'axis':axis});validate_scoped_witness(*d)
                cat.validate('mine_local',1,{k:d[3][k] for k in ('target','expected_block_id','expected_block_properties')})
        for ore in ('iron_ore','deepslate_iron_ore'):
            validate_scoped_witness(*fixture('minecraft:'+ore))
    def test_natural_context_exact_leaves_plants_and_vines(self):
        cases=[('minecraft:'+kind+'_leaves','LeavesBlock',{'distance':'3','persistent':'false','waterlogged':'false'},True) for kind in LOGS]
        cases += [('minecraft:short_grass','TallGrassBlock',{},False),('minecraft:fern','TallGrassBlock',{},False),
                  ('minecraft:tall_grass','DoublePlantBlock',{'half':'lower'},False),('minecraft:large_fern','DoublePlantBlock',{'half':'upper'},False),
                  ('minecraft:poppy','FlowerBlock',{},False),('minecraft:vine','VineBlock',dict.fromkeys(('up','north','south','east','west'),'false'),False),
                  ('minecraft:coal_ore','DropExperienceBlock',{},True),('minecraft:deepslate','RotatedPillarBlock',{'axis':'y'},True)]
        for block,cls,props,full in cases:
            with self.subTest(block=block):
                d=fixture();cell(d,(1,65,1),block,cls,props,full);validate_scoped_witness(*d)
    def test_player_body_allows_only_dry_harmless_collision_empty_plant(self):
        d=fixture();cell(d,(0,64,0),'minecraft:short_grass','TallGrassBlock',{},False);validate_scoped_witness(*d)
        for block,cls,props,full in [('minecraft:jungle_leaves','LeavesBlock',{'distance':'2','persistent':'false','waterlogged':'false'},True),
                                    ('minecraft:vine','VineBlock',dict.fromkeys(('up','north','south','east','west'),'false'),False)]:
            d=fixture();cell(d,(0,64,0),block,cls,props,full)
            with self.assertRaises(ValueError):validate_scoped_witness(*d)
    def test_leaves_and_plants_cannot_support_player(self):
        for block,cls,props,full in [('minecraft:jungle_leaves','LeavesBlock',{'distance':'1','persistent':'false','waterlogged':'false'},True),
                                    ('minecraft:fern','TallGrassBlock',{},False)]:
            d=fixture();cell(d,(0,63,0),block,cls,props,full)
            with self.assertRaises(ValueError):validate_scoped_witness(*d)
    def test_schema_and_skill_reject_malformed_or_unavailable_targets_before_observe(self):
        cat=CapabilityCatalog();rt=SimpleNamespace(_job_scoped_profiles={'break_block':scoped_mining.PROFILE})
        for block,props in [('minecraft:jungle_log',{}),('minecraft:jungle_log',{'axis':'Y'}),('minecraft:jungle_log',{'axis':True}),
                ('minecraft:jungle_log',{'axis':'y','foo':'bar'}),('minecraft:iron_ore',{'axis':'y'}),
                ('minecraft:coal_ore',{}),('minecraft:deepslate_coal_ore',{}),('minecraft:diamond_ore',{}),
                ('minecraft:bamboo',{}),('minecraft:cherry_log',{'axis':'y'})]:
            args={'target':{'x':2,'y':64,'z':0},'expected_block_id':block,'expected_block_properties':props}
            with self.subTest(block=block,props=props):
                with self.assertRaises(Exception):cat.validate('mine_local',1,args)
                with self.assertRaises(SkillError):scoped_mining.mine_local(rt,**args)
    def test_wrong_class_properties_geometry_water_or_hazard_rejected(self):
        for change in [dict(block_class='custom.JungleLog'),dict(block_class='net.minecraft.world.level.block.Block'),
                       dict(properties={}),dict(properties={'axis':'z'}),dict(static_full_cube=False),dict(fluid='minecraft:water')]:
            d=fixture();m=d[0]['result']['scoped_native_preflight']['facts']['mining']
            next(r for r in m['cells'] if (r['x'],r['y'],r['z'])==(2,64,0)).update(change)
            with self.subTest(change=change):
                with self.assertRaises(ValueError):validate_scoped_witness(*d)
        for block,cls,props,full in [('minecraft:wither_rose','WitherRoseBlock',{},False),('minecraft:sand','SandBlock',{},True),
                                    ('minecraft:jungle_leaves','LeavesBlock',{'distance':'8','persistent':'false','waterlogged':'false'},True),
                                    ('minecraft:jungle_leaves','LeavesBlock',{'distance':'1','persistent':'false','waterlogged':'true'},True),
                                    ('minecraft:short_grass','TallGrassBlock',{},True)]:
            d=fixture();cell(d,(1,65,1),block,cls,props,full)
            with self.assertRaises(ValueError):validate_scoped_witness(*d)
    def test_placement_vocabulary_remains_original(self):
        self.assertEqual(set(scoped_placement.BLOCKS),set(scoped_mining.LEGACY_BLOCKS))
        self.assertEqual(placement_snapshot.BLOCKS,mining_snapshot.LEGACY_BLOCKS)
        self.assertEqual(placement_snapshot.STATIC,mining_snapshot.LEGACY_STATIC | {'minecraft:crafting_table'})
        self.assertFalse(set(scoped_mining.LOGS)&set(scoped_placement.BLOCKS))
    def test_all_python_target_and_context_properties_match(self):
        self.assertEqual(set(scoped_mining.BLOCKS),mining_snapshot.BLOCKS)
        for block in scoped_mining.BLOCKS:
            props={'axis':'y'} if block.endswith('_log') else {}
            self.assertTrue(scoped_mining.valid_target_properties(block,props))
            self.assertTrue(mining_snapshot.valid_properties(block,props))

class SurvivalPublicChainTests(PublicMiningChainTests):
    def test_jungle_log_with_natural_leaf_grass_and_vine_context(self):
        from . import test_mining_chain
        original=test_mining_chain.mining_fixture
        def natural(*args,**kwargs):
            d=original(*args,**kwargs)
            cell(d,(1,65,1),'minecraft:jungle_leaves','LeavesBlock',{'distance':'3','persistent':'false','waterlogged':'false'})
            cell(d,(0,64,0),'minecraft:short_grass','TallGrassBlock',{},False)
            cell(d,(2,65,1),'minecraft:vine','VineBlock',dict.fromkeys(('up','north','south','east','west'),'false'),False)
            return d
        args={'target':{'x':2,'y':64,'z':0},'expected_block_id':'minecraft:jungle_log','expected_block_properties':{'axis':'y'}}
        with patch.object(test_mining_chain,'mining_fixture',side_effect=natural):
            result=self.finish_job(self.submit(args))
        self.assertEqual(result['state'],'succeeded',(self.bridge.fixture_error,result))
        self.assertEqual(len([p for p,b in self.bridge.posts if p=='/control/scoped-action']),1)
        self.assertEqual(result['cleanup_certainty'],'confirmed')
    def test_jungle_log_crosses_actual_public_owner_chain(self):
        args={'target':{'x':2,'y':64,'z':0},'expected_block_id':'minecraft:jungle_log','expected_block_properties':{'axis':'y'}}
        result=self.finish_job(self.submit(args))
        self.assertEqual(result['state'],'succeeded',(self.bridge.fixture_error,result))
        posts=[body for path,body in self.bridge.posts if path=='/control/scoped-action']
        self.assertEqual(len(posts),1);self.assertEqual(posts[0]['intent']['expected_block_properties'],{'axis':'y'})
        self.assertFalse(self.bridge.terrain_responses);self.assertEqual(result['cleanup_certainty'],'confirmed')
    def test_iron_crosses_actual_public_owner_chain(self):
        args={'target':{'x':2,'y':64,'z':0},'expected_block_id':'minecraft:iron_ore','expected_block_properties':{}}
        result=self.finish_job(self.submit(args));self.assertEqual(result['state'],'succeeded',(self.bridge.fixture_error,result))
    def test_jungle_log_lost_submission_never_replays(self):
        self.bridge.mining_mode='lost'
        args={'target':{'x':2,'y':64,'z':0},'expected_block_id':'minecraft:jungle_log','expected_block_properties':{'axis':'y'}}
        result=self.finish_job(self.submit(args));self.assertEqual(result['state'],'unknown',result)
        self.assertEqual(len([p for p,b in self.bridge.posts if p=='/control/scoped-action']),1)
        self.assertFalse([p for p,b in self.bridge.posts if p=='/control/action/cancel'])
        self.assertTrue(self.runtime.has_unresolved_execution)

if __name__=='__main__':unittest.main()
