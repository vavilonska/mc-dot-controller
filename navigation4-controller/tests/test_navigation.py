import copy
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4
from navigation4_controller.controller import Controller
from navigation4_controller.legacy import Refused,encode,strict_json,V3Controller,PROFILE,MAX_RESPONSE,RawReply
from navigation4_controller.plan import Plan,load_plan
from navigation4_controller.schema import request_valid,receipt_valid,payload_digest
from navigation4_controller.geometry import observation_geometry,covered
from navigation4_controller.policy import gate
from support import *

class NavigationTests(unittest.TestCase):
 def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'ledger';clone(self.path);self.f=Fake();self.c=Controller(self.path,self.f,PLAN)
 def tearDown(self):self.c.close();self.tmp.cleanup()
 def submit(self,kind='move',plan=None,**updates):
  if plan:self.c.plan=plan
  q=request(kind,plan or self.c.plan);q.update(updates);self.c.observe();return q,self.c.start(q)
 def test_actual101_original_readers_digests_encoded_owner_preserved(self):
  self.assertEqual(len(ORIGINAL['actions']),101);self.assertEqual(self.c.report(),ORIGINAL)
  for r in ORIGINAL['actions'].values():V3Controller.validate_request(r['request']);V3Controller._validate_receipt(r['terminal_native'],r['request'])
  self.submit();self.submit('look');self.c.close();self.c=Controller(self.path,self.f,PLAN)
  for aid,r in ORIGINAL['actions'].items():self.assertEqual(encode(self.c.report(aid)),encode(r))
  self.assertEqual(strict_json((self.path/'owner.json').read_bytes())['owner_id'],OWNER)
 def test_stage_digest_echo_and_only_move_look(self):
  q=request();r=receipt(q);receipt_valid(r,q);changed=dict(q,stage_id='other');self.assertNotEqual(payload_digest(q),payload_digest(changed))
  with self.assertRaises(Refused):receipt_valid(r,changed)
  for kind in ('break_block','select_hotbar','place_block','combat'):
   with self.assertRaises(Refused):request_valid(dict(q,kind=kind))
  with self.assertRaises(Refused):request_valid(dict(q,plan_version=1))
 def test_old_effects_disabled_and_shared_ids_no_replay(self):
  q,_=self.submit();self.c.start(q);self.assertEqual(len(self.f.posts()),1)
  with self.assertRaises(Refused):self.c.start(dict(q,stage_id='changed-stage'))
  self.assertEqual(len(self.f.posts()),1)
  old=next(iter(ORIGINAL['actions'].values()));self.c.start(old['request'])
  with self.assertRaises(Refused):self.c.start(dict(q,id=old['request']['id']))
  legacy_new=dict(old['request'],id=str(uuid4()))
  with self.assertRaises(Refused):self.c.start(legacy_new)
 def test_pending_restart_unknown_and_different_plan_cannot_unlock(self):
  aid=next(iter(ORIGINAL['actions']));self.c.ledger.data['actions'][aid]['state']='PENDING';self.c.ledger.save();self.c.close();self.c=Controller(self.path,self.f,PLAN)
  d=copy.deepcopy(PLAN_DATA);d['stages'][0]['id']='other-reviewed-stage';other=make_plan(d)
  with self.assertRaises(Refused):self.submit(plan=other)
  self.assertNotEqual(other.sha256,PLAN.sha256)
  self.assertTrue(self.c.report()['unknown_lock']);self.assertEqual(self.f.posts(),[])
 def test_lost_response_stop_and_restart_never_reissues(self):
  self.f.fail=True;q,r=self.submit();self.assertEqual(r['state'],'UNKNOWN');self.f.fail=False;self.c.status(q['id']);self.c.stop(q['id']);self.c.stop(q['id']);self.c.start(q)
  self.assertEqual(len(self.f.posts()),2);self.assertEqual(self.c.report(q['id'])['state'],'UNKNOWN')
 def test_durable_intent_before_post_and_fsync_fault(self):
  def before(method,path,body):
   if path.endswith('start'):self.assertEqual(strict_json((self.path/'ledger.json').read_bytes())['actions'][body['id']]['state'],'PENDING')
  self.f.before=before;self.submit();n=len(self.f.posts());q=request();self.c.observe()
  with patch.object(self.c.ledger,'save',side_effect=OSError('fixture')):
   with self.assertRaises(OSError):self.c.start(q)
  self.assertEqual(len(self.f.posts()),n)
 def test_jump_knownzero_consumes_one_attempt_without_protocol_unknown(self):
  d=copy.deepcopy(PLAN_DATA);d['stages'][0].update(jump_first=True,max_moves=1);plan=make_plan(d);self.f.count=0
  q,r=self.submit(plan=plan);self.assertEqual(r['state'],'CLOSED');self.assertFalse(self.c.report()['unknown_lock'])
  with self.assertRaises(Refused):self.submit(plan=plan)
  self.assertEqual(len(self.f.posts()),1)
 def test_stage_move_and_look_budgets_all_intents(self):
  for _ in range(3):self.submit()
  with self.assertRaises(Refused):self.submit()
  for _ in range(2):self.submit('look')
  with self.assertRaises(Refused):self.submit('look')
 def test_target_not_reached_remains_known_gameplay(self):
  _,r=self.submit();self.assertEqual(r['state'],'CLOSED');self.assertEqual(r['local_risk']['arrival'],'not_assessed');self.assertEqual(self.f.obs['pose']['z'],0.)
 def test_source_current_partial_support_with_real_top_contact(self):
  # One current cell is lowered0.125, adjacent support still contacts actualfeet.
  for cell in self.f.obs['local_blocks']:
   if cell['dy']==-1 and cell['dx']==-1:cell['collision_boxes']=[[0.,0.,0.,1.,.875,1.]]
  self.submit('look')
 def test_target_hole_union_or_current_embedded_rejected(self):
  self.f.obs['local_blocks'][0]['collision_boxes']=[[0.,0.,0.,1.,1.,1.]]
  for cell in self.f.obs['local_blocks']:
   if cell['dx']==0 and cell['dy']==-1 and cell['dz']==-1:cell['collision_boxes']=[[0.,0.,0.,.2,1.,1.]]
  with self.assertRaises(Refused):self.submit()
  self.f.obs=observation()
  next(c for c in self.f.obs['local_blocks'] if (c['dx'],c['dy'],c['dz'])==(0,0,0)).update(collision=True,collision_boxes=[[0.,0.,0.,1.,1.,1.]],id='minecraft:stone')
  with self.assertRaises(Refused):self.submit('look')
 def test_fractional_bed_step_uses_real_shape_and_step_height(self):
  d=copy.deepcopy(PLAN_DATA);s=d['stages'][0];s['source_bounds']=dict(min_x=0.,max_x=1.,min_y=54.9,max_y=55.7,min_z=-1.,max_z=1.5);s['target']=dict(x=.5,y=55.5625,z=-.5);plan=make_plan(d)
  o=self.f.obs;o['pose'].update(x=.5,z=.5);o['player_bbox'].update(min_x=.2,max_x=.8,min_z=.2,max_z=.8)
  next(c for c in o['local_blocks'] if (c['dx'],c['dy'],c['dz'])==(0,0,-1)).update(id='minecraft:white_bed',collision=True,collision_boxes=[[0.,0.,0.,1.,.5625,1.]])
  self.submit(plan=plan);self.f.obs['step_height']=.5
  with self.assertRaises(Refused):self.submit(plan=plan)
 def test_strafe_jump_and_low_ceiling_not_ideal_arc_proof(self):
  d=copy.deepcopy(PLAN_DATA);s=d['stages'][0];s.update(forward=0.,strafe=-.5,jump_first=True,max_moves=1,target=dict(x=1.,y=55.,z=0.));s['source_bounds']['max_x']=2.;plan=make_plan(d)
  # Ceiling at feet+2: standing bodyclear but ideal jump arc intersects it. Allowed ordinary collision.
  for c in self.f.obs['local_blocks']:
   if c['dy']==2:c.update(id='minecraft:stone',collision=True,collision_boxes=[[0.,0.,0.,1.,1.,1.]])
  self.submit(plan=plan)
 def test_wrong_heading_direction_sprint_drop_and_unloaded_refused(self):
  self.f.obs['sprinting']=True
  with self.assertRaises(Refused):self.submit()
  self.f.obs=observation();self.f.obs['pose']['yaw']=0.
  with self.assertRaises(Refused):self.submit()
  self.f.obs=observation();d=copy.deepcopy(PLAN_DATA);d['stages'][0]['target']['y']=53.;p=make_plan(d)
  with self.assertRaises(Refused):self.submit(plan=p)
  self.f.obs['local_blocks'][0].update(loaded=False,id=None,fluid=None,collision=None,collision_boxes=None);self.f.obs.update(collision_boxes_complete=False,ready=False)
  with self.assertRaises(Refused):self.submit()
 def test_bad_shape_counts_nulls_and_false_ready(self):
  for update in ({'step_height':True},{'sprinting':None},{'collision_boxes_complete':False}):
   o=observation();o.update(update)
   with self.assertRaises(Refused):observation_geometry(o)
  o=observation();o['local_blocks'][0]['collision_boxes']=[[0,0,0,1,float('nan'),1]]
  with self.assertRaises(Refused):observation_geometry(o)
  o=observation();o['local_blocks'][0].update(collision=None,collision_boxes=None);o.update(collision_boxes_complete=False,ready=False);observation_geometry(o)
 def test_footprint_union_rejects_middle_gap_not_just_corners(self):
  self.assertFalse(covered((0,0,1,1),[(0,0,.4,1),(.6,0,1,1)]));self.assertTrue(covered((0,0,1,1),[(0,0,.5,1),(.5,0,1,1)]))
 def test_near_byte_ceiling_refuses_before_intent_with_history_kept(self):
  data=self.c.ledger.data;r=next(iter(data['actions'].values()));r['test_padding']='';r['test_padding']='x'*(self.c.ledger.MAX_BYTES-3*MAX_RESPONSE*2-1000-len(encode(data)));self.c.ledger.save();q=request();self.c.observe()
  with self.assertRaises(Refused):self.c.start(q)
  self.assertNotIn(q['id'],self.c.report()['actions']);self.assertEqual(self.f.posts(),[])
 def test_plan_closed_bounds_hash_context_and_snapshot(self):
  for update in ({'version':1},{'targets':[]},{'kind':'mining'}):
   d=copy.deepcopy(PLAN_DATA);d.update(update)
   with self.assertRaises(Refused):make_plan(d)
  for update in ({'max_moves':9},{'max_looks':3},{'jump_first':True},{'max_samples':9}):
   d=copy.deepcopy(PLAN_DATA);d['stages'][0].update(update)
   with self.assertRaises(Refused):make_plan(d)
  d=copy.deepcopy(PLAN_DATA);d['context']['world_generation']=str(uuid4());p=make_plan(d)
  with self.assertRaises(Refused):self.submit(plan=p)
  file=Path(self.tmp.name)/'plan.json';file.write_bytes(PLAN.raw);self.assertEqual(load_plan(file,PLAN.sha256).snapshot(),PLAN.snapshot())
  with self.assertRaises(Refused):load_plan(file,'0'*64)

 def test_count_ceiling_and_old_routes_without_new_plan(self):
  by_profile={r['request']['profile']:r for r in ORIGINAL['actions'].values()}
  for old in by_profile.values():
   with patch.object(self.f,'request',return_value=RawReply(200,encode(old['terminal_native']))) as call:
    self.c.status(old['request']['id']);self.assertTrue(call.call_args.args[1].startswith(V3Controller.route(old['request'])))
  for _ in range(256-len(self.c.ledger.data['actions'])):
   q=request();self.c.ledger.data['actions'][q['id']]=dict(request=q,state='CLOSED',unknown_reasons=[],terminal_native=receipt(q),latest_native=receipt(q),evidence=[],stop_attempted=False,plan=PLAN.snapshot())
  self.c.ledger.save()
  with self.assertRaises(Refused):self.submit()
  self.assertEqual(len(self.c.report()['actions']),256)
 def test_known_closed_bad_later_status_does_not_erase_terminal(self):
  q,r=self.submit();old=copy.deepcopy(r['terminal_native']);self.f.modify=lambda value:dict(value,stage_id='wrong');self.c.status(q['id'])
  self.assertEqual(self.c.report(q['id'])['terminal_native'],old);self.assertEqual(self.c.report(q['id'])['state'],'CLOSED')
 def test_pending_reply_reserve_can_still_status_stop(self):
  self.f.state='ACTIVE';q,_=self.submit();data=self.c.ledger.data;old=next(iter(data['actions'].values()));old['test_padding']='';old['test_padding']='x'*(self.c.ledger.MAX_BYTES-3*MAX_RESPONSE*2-10000-len(encode(data)));self.c.ledger.save()
  self.c.status(q['id']);self.f.state='SETTLED';self.c.stop(q['id']);self.c.status(q['id']);self.assertEqual(self.c.report(q['id'])['state'],'CLOSED')
 def test_no_new_owner_or_missing_navigation_plan(self):
  with self.assertRaises(Refused):Controller(Path(self.tmp.name)/'new',self.f,PLAN)
  self.c.plan=None;self.c.observe()
  with self.assertRaises(Refused):self.c.start(request())
  self.assertEqual(self.f.posts(),[])

 def test_persisted_stage_must_exist_in_original_plan(self):
  from navigation4_controller.plan import validate_snapshot
  q=request();validate_snapshot(PLAN.snapshot(),q)
  with self.assertRaises(Refused):validate_snapshot(PLAN.snapshot(),dict(q,stage_id='absent'))
