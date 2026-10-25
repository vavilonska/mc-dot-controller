"""Actual codec bytes from synthetic cold shape models; NOT live capture/qualification.
Route replay changes only in-memory heading/context to synthetic reviewed PLAN.
"""
import copy
import json
import math
from pathlib import Path
import tempfile
import unittest
from navigation4_controller.controller import Controller
from navigation4_controller.policy import gate
from navigation4_controller.geometry import observation_geometry
from navigation4_controller.legacy import RawReply,Refused,strict_json,MAX_RESPONSE
from support import clone,ENDPOINT,make_plan,request
F=Path(__file__).parent/'observations'
T=Path(__file__).resolve().parents[2]/'plans/BED-DOOR-NAVIGATION-CONTEXT-UNBOUND.json'
def observed(name):return strict_json((F/(name+'.json')).read_bytes())
def scenario(name,index):
 o=python_cold_window(name) if name in ('corridor-python','south-python') else observed(name);o['pose']['yaw']=-180. # SYNTHETIC route heading, never rewrite raw fixture.
 d=strict_json(T.read_bytes());d['context']={k:o['bound_owner_id'] if k=='owner_id' else o[k] for k in d['context']};p=make_plan(d);s=p.data['stages'][index]
 q=request(plan=p);q.update({k:o[k] for k in ('session','world_generation','player_uuid','owner_generation','observation_id')});q.update(owner_id=o['bound_owner_id'],stage_id=s['id'],forward=s['forward'],strafe=s['strafe'],samples=s['max_samples'],jump_first=s['jump_first'])
 return o,q,p
def python_cold_window(name):
 """TEST-ONLY model from cold states, not production codec/native capture."""
 o=observed('door');x,y,z=(-160.5,56.,10.5 if name=='corridor-python' else 12.5)
 o['pose'].update(x=x,y=y,z=z);o['player_bbox'].update(min_x=x-.3,max_x=x+.3,min_y=y,max_y=y+1.8,min_z=z-.3,max_z=z+.3)
 raw=strict_json((F.parent/'cold-model/COLD-GEOMETRY.json').read_bytes());cells={(b['x'],b['y'],b['z']):b for b in raw['blocks']};o['local_blocks']=[]
 full={'minecraft:cut_sandstone','minecraft:stone','minecraft:sandstone','minecraft:clay','minecraft:gravel','minecraft:obsidian'}
 empty={'minecraft:nether_portal','minecraft:air','minecraft:torch','minecraft:water','minecraft:wheat'}
 for dy in range(-2,4):
  for dz in range(-2,3):
   for dx in range(-2,3):
    b=cells[(math.floor(x)+dx,math.floor(y)+dy,math.floor(z)+dz)];bid=b['Name']
    if bid in full:boxes=[[0,0,0,1,1,1]]
    elif bid in empty:boxes=[]
    elif bid=='minecraft:farmland':boxes=[[0,0,0,1,.9375,1]]
    else:raise AssertionError('Unmodelled cold block: '+bid)
    o['local_blocks'].append(dict(dx=dx,dy=dy,dz=dz,loaded=True,id=bid,collision=bool(boxes),fluid='minecraft:water' if bid=='minecraft:water' else 'minecraft:empty',collision_boxes=boxes))
 return o
@unittest.skipUnless(T.is_file() and (F.parent / "cold-model/COLD-GEOMETRY.json").is_file(),
                     "requires excluded private TEST-world geometry and campaign plan")
class ColdGeometryTests(unittest.TestCase):
 def test_all_actual_codec_observations_and_oversize_reject(self):
  class Transport:
   endpoint=ENDPOINT
   def request(self,*args):return RawReply(200,self.raw)
  with tempfile.TemporaryDirectory() as tmp:
   d=Path(tmp)/'ledger';clone(d);t=Transport()
   with Controller(d,t) as c:
    for f in F.glob('*.json'):
     if f.name=='manifest.json':continue
     t.raw=f.read_bytes()
     if f.name=='max-512-long-decimals.json':
      self.assertGreater(len(t.raw),MAX_RESPONSE)
      with self.assertRaises(Refused):c.observe()
     else:self.assertEqual(c.observe(),strict_json(t.raw))
 def test_cold_route_first_seven_source_windows(self):
  for i,name in enumerate(['source','bed-head','bed-foot','floor-north','floor-west','chest','cut-sandstone']):
   with self.subTest(stage=i):
    o,q,p=scenario(name,i);self.assertEqual(gate(o,q,o['bound_owner_id'],{},p)['arrival'],'not_assessed')
 def test_final_two_stages_python_cold_model_not_native_capture(self):
  for name,i in (('corridor-python',7),('south-python',8)):
   o,q,p=scenario(name,i);gate(o,q,o['bound_owner_id'],{},p)
 def test_actual_fractional_drop_jump_and_low_ceiling(self):
  o,q,p=scenario('bed-foot',2);self.assertAlmostEqual(p.stage(q['stage_id'])['target']['y']-o['pose']['y'],-.5625);gate(o,q,o['bound_owner_id'],{},p)
  o,q,p=scenario('floor-west',4);self.assertEqual(p.stage(q['stage_id'])['target']['y']-o['pose']['y'],.875);self.assertTrue(q['jump_first']);gate(o,q,o['bound_owner_id'],{},p)
  q['jump_first']=False
  with self.assertRaises(Refused):gate(o,q,o['bound_owner_id'],{},p)
 def test_synthetic_partial_chest_edge_current_known_support(self):
  o,q,p=scenario('chest',5);delta=-.4;o['pose']['x']+=delta
  for k in ('min_x','max_x'):o['player_bbox'][k]+=delta
  gate(o,q,o['bound_owner_id'],{},p)
 def test_required_missing_shape_and_current_floor_miss_reject(self):
  o,q,p=scenario('floor-west',4)
  c=next(c for c in o['local_blocks'] if (c['dx'],c['dy'],c['dz'])==(0,-1,0));c['collision']=None;c['collision_boxes']=None;o['collision_boxes_complete']=False;o['ready']=False
  with self.assertRaises(Refused):gate(o,q,o['bound_owner_id'],{},p)
  o,q,p=scenario('chest',5);o['pose']['y']=55.
  with self.assertRaises(Refused):gate(o,q,o['bound_owner_id'],{},p)
 def test_box_count_overflow_and_incomplete_null_sprint(self):
  o=observed('max-512-short-decimals');self.assertEqual(sum(len(c['collision_boxes'] or []) for c in o['local_blocks']),512)
  c=next(c for c in o['local_blocks'] if len(c['collision_boxes'] or [])<16);c['collision_boxes']=[[0,0,0,1,1,1]];c['collision']=True
  with self.assertRaises(Refused):observation_geometry(o)
  o=observed('shape-failed');o['sprinting']=None;observation_geometry(o)
