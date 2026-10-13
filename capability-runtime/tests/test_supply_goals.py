"""Recursive goal/recipe tests; slot clicks use the real production algorithm.

Mining/station interaction are explicit deterministic models, not live evidence.
The independent shaped-grid model decides recipe output, never supply's result.
"""
from collections import Counter
from copy import deepcopy
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import patch
import unittest
from mdc_skills import supply, production
from mdc_skills.core import Outcome, SkillError
from test_production_capability import ProductionRuntime, FurnaceClient, _fixture, item

class MaterialClient(_fixture.FakeQueueClient):
    def update_output(self):
        super().update_output()
        grid=[self.slots[i]['id'] for i in range(1,self.width*self.width+1)]
        if grid[0]=='minecraft:oak_log' and all(not x for x in grid[1:]):self.slots[0]=item('oak_planks',4)
        if self.width==3 and grid==['minecraft:oak_planks']*4+['']+['minecraft:oak_planks']*4:self.slots[0]=item('chest',1)
        if self.width==3 and grid==['minecraft:glass']*6+['']*3:self.slots[0]=item('glass_pane',16)

class MaterialRuntime(ProductionRuntime):
    def __init__(self,stock=None):
        super().__init__(MaterialClient(width=2,stock=stock or {}));self.stations={};self.mined=0;self.approaches=0
    def observe(self,**kwargs):
        value=super().observe(**kwargs)
        value.player.update(x=.5,y=64,z=.5,selected_slot=0,inventory_total=len(value.player["inventory"]))
        if kwargs.get('terrain'):
            value.terrain={'complete':True,'cells':[{'x':2,'y':64,'z':0,'id':'minecraft:oak_log','known':True,'status':'loaded'}]}
        return value
    def width(self,n):
        storage={slot:deepcopy(self.client.slots[slot]) for slot in self.client.storage.values()}
        self.client.width=n;self.client.container=0 if n==2 else 7
        self.client.slots={i:item() for i in range(n*n+1)};self.client.slots.update(storage)
    def execute(self,skill,command,verify,**kwargs):
        if command['action']=='close_menu':
            self.actions.append(deepcopy(command));self.width(2)
            after=self.observe();assert verify(kwargs['before'],after)
            return Outcome('succeeded','closed',('close-'+str(len(self.actions)),),{},after)
        return super().execute(skill,command,verify,**kwargs)
    def add(self,item_id,n):
        slot=next((i for i in self.client.storage.values() if self.client.slots[i]['id']==item_id),None)
        if slot is None:slot=next(i for i in self.client.storage.values() if self.client.slots[i]['empty'])
        self.client.slots[slot]=item(item_id,self.client.slots[slot]['count']+n)
    def subtract(self,item_id,n):
        for slot in self.client.storage.values():
            old=self.client.slots[slot]
            if old['id']==item_id:
                used=min(n,old['count']);self.client.slots[slot]=item(item_id,old['count']-used);n-=used
                if not n:return
        raise AssertionError('fixture missing material')
    def totals(self):return supply._counts(self.observe())

class SupplyTests(unittest.TestCase):
    def setUp(self):
        self.runtime=MaterialRuntime();self.patches=ExitStack();self.addCleanup(self.patches.close)
        def discover(rt,station_ids):
            rows=[{'position':{'x':1,'y':64,'z':0},'block_id':block,'face':'up',
                'approach':{'goal':{'x':0,'y':64,'z':0},'route_steps':0}} for block in self.runtime.stations if block in station_ids]
            return rt.result('discover',[rt.observe()],stations=rows)
        def place(rt,block_id,**kwargs):
            self.runtime.subtract(block_id,1);self.runtime.stations[block_id]=True
            return rt.result('place',[rt.observe()],station={'position':{'x':1,'y':64,'z':0},'block_id':block_id,'face':'up'})
        def open_station(rt,position,block_id,**kwargs):
            assert block_id in self.runtime.stations;self.runtime.width(3)
            return rt.result('open',[rt.observe()])
        def acquire(rt,item_id,*,count,max_blocks,excluded_positions=()):
            assert item_id=='minecraft:oak_log'
            extra=count-self.runtime.totals()[item_id];assert 0<extra<=max_blocks
            self.runtime.mined+=extra;self.runtime.add(item_id,extra)
            return rt.result('mined',[rt.observe()],item_id=item_id)
        def navigate(rt,goal,**kwargs):
            self.runtime.approaches+=1
            return rt.result('approached',[rt.observe()])
        for target,value in [('mdc_skills.supply.planning.discover_workstations',discover),
                ('mdc_skills.supply.place_workstation',place),('mdc_skills.supply.production.open_workstation',open_station),
                ('mdc_skills.supply.planning.acquire_nearby',acquire),('mdc_skills.supply.mobility.navigate_loaded',navigate),
                ('mdc_skills.supply.planning._approach',lambda *a,**k:{'goal':{'x':0,'y':64,'z':0},'route_steps':0}),
                ('mdc_skills.supply.reach.block_at',lambda *a,**k:{'id':'minecraft:crafting_table'})]:
            self.patches.enter_context(patch(target,value))
    def test_bare_log_bootstrap_pickaxe_preserves_sibling_planks(self):
        outcome=supply.ensure_items(self.runtime,{'minecraft:wooden_pickaxe':1},max_nodes=512)
        self.assertTrue(outcome.ok);self.assertEqual(self.runtime.totals()['minecraft:wooden_pickaxe'],1)
        self.assertIn('minecraft:crafting_table',self.runtime.stations)
        self.assertGreaterEqual(self.runtime.mined,3)
        self.assertTrue(any(c['action']=='click_slot' for c in self.runtime.actions))
        self.assertGreater(self.runtime.approaches,0)
    def test_final_material_reservation_survives_chest_consumption(self):
        outcome=supply.ensure_items(self.runtime,{'minecraft:oak_planks':8,'minecraft:chest':1},max_nodes=512)
        self.assertTrue(outcome.ok);totals=self.runtime.totals()
        self.assertGreaterEqual(totals['minecraft:oak_planks'],8);self.assertEqual(totals['minecraft:chest'],1)
    def test_expired_original_deadline_stops_nested_recipe_clicks(self):
        original=self.runtime.execute
        def slow(*args,**kwargs):
            result=original(*args,**kwargs);self.runtime.time+=.6;return result
        self.runtime.execute=slow
        with self.assertRaisesRegex(SkillError,'supply_deadline_exceeded'):
            supply.ensure_items(self.runtime,{'minecraft:wooden_pickaxe':1},max_nodes=512,timeout_seconds=1)
        self.assertLessEqual(len(self.runtime.actions),2)
    def test_unknown_recipe_click_never_replayed(self):
        self.runtime.failure_at=1
        with self.assertRaises(SkillError) as caught:supply.ensure_items(self.runtime,{'minecraft:chest':1},max_nodes=512)
        self.assertEqual(caught.exception.status,'unknown');self.assertEqual(len(self.runtime.actions),1)
    def test_exact_ingredient_binding_does_not_take_reserved_other_wood(self):
        runtime=ProductionRuntime(_fixture.FakeQueueClient(width=2,stock={0:('oak_planks',2),1:('birch_planks',2)}))
        self.assertTrue(production.craft(runtime,'stick',ingredients={'M':'minecraft:birch_planks'}).ok)
        self.assertEqual(sum(x['count'] for x in runtime.observe().player['inventory'] if x['id']=='minecraft:oak_planks'),2)
    def test_invalid_ingredient_binding_rejected_before_mutation(self):
        with self.assertRaisesRegex(SkillError,'invalid_recipe_ingredient_binding'):
            production.craft(self.runtime,'stick',ingredients={'M':'minecraft:stone'})
        self.assertEqual(self.runtime.actions,[])
    def test_large_recipe_output_is_observed_from_slot_transfers(self):
        runtime=ProductionRuntime(MaterialClient(width=3,stock={0:('glass',6)}))
        result=production.craft(runtime,'glass_pane')
        self.assertTrue(result.ok)
        self.assertEqual(result.evidence['added'],16)
        self.assertEqual(sum(x['count'] for x in runtime.observe().player['inventory'] if x['id']=='minecraft:glass_pane'),16)
    def test_deadline_guard_stops_inside_real_smelting_algorithm(self):
        runtime=ProductionRuntime(FurnaceClient(stock={0:('raw_iron',2),1:('coal',1)}))
        execute=runtime.execute
        def slow(*args,**kwargs):
            result=execute(*args,**kwargs);runtime.time+=.6;return result
        runtime.execute=slow
        bounded=supply._DeadlineRuntime(runtime,1,64)
        with self.assertRaisesRegex(SkillError,'supply_deadline_exceeded'):
            production.smelt(bounded,'minecraft:raw_iron',count=2,fuel_id='minecraft:coal')
        self.assertLessEqual(len(runtime.actions),2)
    def test_exact_official_building_recipe_counts(self):
        for name,count in [('oak_stairs',4),('oak_slab',6),('oak_door',3),('oak_fence',3),('glass_pane',16),('iron_door',3)]:
            self.assertEqual(production.CRAFT_RECIPES[name].count,count)
        r=production.CRAFT_RECIPES['oak_fence'];self.assertEqual(sum(c!=' ' for row in r.pattern for c in row),6)

if __name__=='__main__':unittest.main()
