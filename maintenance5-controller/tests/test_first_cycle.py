"""Synthetic state transitions over preserved v4 production-codec cold geometry.
This is not v5 actual wire or live gameplay; ray/tool/new metadata are synthetic.
"""
import copy
import math
from pathlib import Path
import unittest
from support import *
from maintenance5_controller.policy import gate
from maintenance5_controller.legacy import Refused
from maintenance5_controller.assessment import assess_target
F=Path(__file__).parent/'cold-model/v4-cold-source-codec.json'
P=Path(__file__).resolve().parents[2]/'plans/TNT-FIRST-CYCLE-CONTEXT-UNBOUND.json'
def cold():
 o=strict_json(F.read_bytes());o.update(profile=PROFILE,session=SESSION,world_generation=WORLD,player_uuid=PLAYER,bound_owner_id=OWNER,owner_generation=102,observation_id=OBS,eye_position=dict(x=-166.5,y=56.62,z=10.5),ray_target_witness=None,latest_target_witness=None,local_primed_tnt={'count':0,'complete':True,'overflow':False});o['pose']['yaw']=-180.;o['hotbar']=observation()['hotbar'];o['selected_slot']=2
 d=strict_json(P.read_bytes());d['context']=dict(session=SESSION,world_generation=WORLD,player_uuid=PLAYER,owner_id=OWNER);return o,make_plan(d)
def cell(o,q):
 origin={k:math.floor(o['pose'][k]) for k in 'xyz'}
 return next(c for c in o['local_blocks'] if all(c['d'+k]+origin[k]==q[k] for k in 'xyz'))
class FirstCycleTests(unittest.TestCase):
 def test_real_cold_first_cycle_floor_tnt_fill_synthetic_transitions(self):
  o,p=cold();history={}
  for kind,idx in [('break_block',0),('break_block',1),('place_block',0)]:
   q=request(kind,p,idx);prepare(o,q)
   self.assertEqual(gate(o,q,OWNER,history,p)['target_result'],'not_assessed')
   before=copy.deepcopy(o);expected='minecraft:air' if kind=='break_block' else 'minecraft:andesite';c=cell(o,q);c.update(id=expected,collision=kind=='place_block',collision_boxes=[[0,0,0,1,1,1]] if kind=='place_block' else [])
   o['client_tick']+=1;o['latest_target_witness']=dict(action_id=q['id'],**{k:q[k] for k in 'xyz'},id=expected,fluid='minecraft:empty',loaded=True,complete=True)
   r=dict(request=q,state='CLOSED',terminal_native=receipt(q),observation=before)
   self.assertTrue(assess_target(r,o)['qualification']);history[q['id']]=r
  support_cell=cell(o,dict(x=-167,y=54,z=10));self.assertEqual(support_cell['id'],'minecraft:cut_sandstone')
  self.assertEqual(cell(o,dict(x=-167,y=54,z=11))['id'],'minecraft:andesite')
 def test_unbound_template_has_no_authority(self):
  raw=P.read_bytes()
  with self.assertRaises(Refused):Plan(raw,hashlib.sha256(raw).hexdigest())
