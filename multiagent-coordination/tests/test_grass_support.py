"""Ordinary-world grass compatibility; no loosening of loaded/air/full-cube facts."""
from copy import deepcopy
import json,os
from pathlib import Path
import unittest
from test_live_owner import cell
from mdcoord.publisher import narrow_terrain,SUPPORT
from mdcoord.schema import Rejected
import test_resident_owner_chain as chain


def terrain():
    cells=[cell(x,y,z) for y in range(62,67) for z in range(-1,2) for x in range(-1,2)]
    for c in cells:
        if c['y']==63:c['id']='minecraft:grass_block';c['properties']={'snowy':'false'}
    return {'complete':True,'cells':cells,'origin':{'x':0,'y':64,'z':0},'radius':1,'vertical':2}

class GrassSupportTests(unittest.TestCase):
    def test_exactly_four_support_ids_and_45_known_cells(self):
        self.assertEqual(SUPPORT,frozenset({'minecraft:stone','minecraft:cobblestone','minecraft:dirt','minecraft:grass_block'}))
        out=narrow_terrain(terrain());self.assertTrue(out['complete']);self.assertEqual(len(out['cells']),45)
    def test_snowy_property_is_not_snow_layer_but_actual_snow_and_plants_reject(self):
        t=terrain()
        for c in t['cells']:
            if c['id']=='minecraft:grass_block':c['properties']['snowy']='true'
        self.assertTrue(narrow_terrain(t)['complete'])
        for name in ('minecraft:snow','minecraft:short_grass','minecraft:tall_grass'):
            t=terrain();c=next(c for c in t['cells'] if c['y']==64);c['id']=name;c['air']=False
            if name=='minecraft:snow':c['collision_empty']=False;c['collision_bounds']=[0,0,0,1,.125,1]
            self.assertFalse(narrow_terrain(t)['complete'],name)
    def test_water_unknown_truncation_hazard_and_nonfull_grass_reject(self):
        for change in ({'fluid':'minecraft:water','fluid_source':True},{'status':'unloaded'},
                       {'known':False},{'collision_known':False},{'properties_truncated':True},
                       {'id_truncated':True},{'full_top_support':False},
                       {'collision_bounds':[0,0,0,1,.5,1]},{'hazards':['danger']}):
            t=terrain();next(c for c in t['cells'] if c['y']==63).update(change)
            self.assertFalse(narrow_terrain(t)['complete'],change)
    def test_unrelated_unknown_id_in_any_of_45_cells_keeps_incomplete(self):
        t=terrain();t['cells'][0]['id']='minecraft:granite'
        self.assertFalse(narrow_terrain(t)['complete'])
    def test_missing_duplicate_extra_shifted_and_mistyped_coordinates_never_complete(self):
        variants=[]
        t=terrain();t['cells'].pop(0);variants.append(t)
        t=terrain();t['cells'][-1]=deepcopy(t['cells'][0]);variants.append(t)
        t=terrain();extra=deepcopy(t['cells'][0]);extra['x']=2;t['cells'].append(extra);variants.append(t)
        t=terrain();t['cells'][0]['x']=2;variants.append(t)
        t=terrain();t['cells'][0]['x']=True;variants.append(t)
        t=terrain();t['radius']=True;variants.append(t)
        t=terrain();t['origin']['x']='0';variants.append(t)
        for t in variants:
            with self.subTest(t=t):
                with self.assertRaises(ValueError):narrow_terrain(t)
    def test_actual_worldcache_filtered_unloaded_corner_never_reaches_post(self):
        c=chain.ResidentOwnerChainTests('test_actual_completed_scan_and_successful_one_writer_chain');c.setUp();self.addCleanup(c.tearDown)
        original=c.native.request
        def request(method,path,body=None):
            out=original(method,path,body)
            if path.startswith('/control/terrain?'):
                for item in out['cells']:
                    if item['y']==63:item['id']='minecraft:grass_block'
                out['cells'][0].update(status='unloaded',known=False);out['unknown_cells']=1
            return out
        c.native.request=request
        c.bridge.refresh();c.resident.tick();c.dog.tick()
        self.assertTrue(c.bridge.publisher_fault)
        self.assertTrue(c.bridge.interrupted)
        self.assertFalse(any(call[0]=='POST' for call in c.native.calls))
    def test_actual_resident_owner_chain_on_grass_preserves_one_post_and_signed_nano(self):
        c=chain.ResidentOwnerChainTests('test_actual_completed_scan_and_successful_one_writer_chain');c.setUp();self.addCleanup(c.tearDown)
        original=c.native.request
        def request(method,path,body=None):
            out=original(method,path,body)
            if path.startswith('/control/terrain?'):
                for item in out['cells']:
                    if item['y']==63:item['id']='minecraft:grass_block';item['properties']={'snowy':'false'}
            return out
        c.native.request=request
        c.test_actual_completed_scan_and_successful_one_writer_chain()
    def test_actual_java_support_ids_when_wire_artifact_is_supplied(self):
        path=os.environ.get('MDC_GRASS_SUPPORT_WIRE')
        if not path:self.skipTest('Native wire comparison runs after the current Java build')
        wire=json.loads(Path(path).read_text());self.assertEqual(set(wire['support_ids']),set(SUPPORT));self.assertTrue(wire['full_grass_clear'])
