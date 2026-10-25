import copy
import tempfile
from pathlib import Path
from uuid import uuid4
from unittest.mock import patch
import unittest
from support import *
from maintenance5_controller.controller import Controller,MaintenanceLedger
from maintenance5_controller.legacy import Refused,V4Controller,MAX_RESPONSE,Ledger
from maintenance5_controller.plan import validate_snapshot,Plan
from maintenance5_controller.schema import request_valid,receipt_valid,payload_digest
from maintenance5_controller.geometry import witness_valid

class MaintenanceTests(unittest.TestCase):
 def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.d=Path(self.tmp.name)/'ledger';clone(self.d);self.f=Fake();self.c=Controller(self.d,self.f,PLAN)
 def tearDown(self):self.c.close();self.tmp.cleanup()
 def submit(self,kind='look',**changes):
  q=request(kind);q.update(changes);prepare(self.f.obs,q);self.c.observe();return q,self.c.start(q)
 def test_actual101_all_original_record_digest_terminal_owner_preserved(self):
  self.assertEqual(len(self.c.report()['actions']),101)
  for r in ORIGINAL['actions'].values():V4Controller.validate_request(r['request']);V4Controller._validate_receipt(r['terminal_native'],r['request'])
  self.submit();self.c.close();self.c=Controller(self.d,self.f,PLAN)
  for aid,r in ORIGINAL['actions'].items():self.assertEqual(encode(self.c.report(aid)),encode(r))
  self.assertEqual(self.c.owner_id,OWNER);self.assertEqual(Ledger.MAX_BYTES,8*1024*1024);self.assertEqual(MaintenanceLedger.MAX_BYTES,24*1024*1024)
 def test_five_kind_dispatch_single_place_and_status(self):
  for kind in ('move','look','select_hotbar','break_block','place_block'):
   q,r=self.submit(kind);self.assertEqual(r['state'],'CLOSED');receipt_valid(r['terminal_native'],q)
  self.assertEqual(len(self.f.posts()),5)
 def test_exact_same_id_reads_original_changed_stage_or_anchor_rejects(self):
  q,r=self.submit('place_block');self.c.start(q)
  for delta in ({'stage_id':'wrong'},{'hit_y':54.5},{'anchor_block_id':'minecraft:andesite'}):
   with self.assertRaises(Refused):self.c.start(dict(q,**delta))
  self.assertEqual(len(self.f.posts()),1)
 def test_knownzero_consumes_target_once_not_unknown(self):
  self.f.count=0;q,r=self.submit('break_block');self.assertEqual(r['state'],'CLOSED')
  with self.assertRaises(Refused):self.submit('break_block')
  self.assertFalse(self.c.report()['unknown_lock']);self.assertEqual(len(self.f.posts()),1)
 def test_place_pass_fail_still_completed_one_call(self):
  self.f.modify=lambda r:dict(r,gameplay_outcome='place_fail_target_unchanged')
  q,r=self.submit('place_block');self.assertEqual(r['state'],'CLOSED');self.assertEqual(r['terminal_native']['applied_calls'],1)
  with self.assertRaises(Refused):self.submit('place_block')
 def test_original_unknown_blocks_any_new_plan_profile(self):
  self.f.fail=True;q,r=self.submit();self.assertEqual(r['state'],'UNKNOWN');self.f.fail=False;self.c.stop(q['id']);self.c.status(q['id']);self.c.close();self.c=Controller(self.d,self.f,PLAN)
  d=copy.deepcopy(PLAN_DATA);d['worksites'][0]['id']='other';self.c.plan=make_plan(d)
  with self.assertRaises(Refused):self.submit()
  self.assertTrue(self.c.report()['unknown_lock']);self.assertEqual(len(self.f.posts()),2)
 def test_lost_place_response_never_reissues(self):
  self.f.fail=True;q,r=self.submit('place_block');self.f.fail=False;self.c.start(q);self.c.stop(q['id']);self.c.stop(q['id']);self.assertEqual(len(self.f.posts()),2);self.assertEqual(self.c.report(q['id'])['state'],'UNKNOWN')
 def test_raw_and_preintent_fence(self):
  def before(method,path,body):
   if path.endswith('start'):self.assertEqual(strict_json((self.d/'ledger.json').read_bytes())['actions'][body['id']]['state'],'PENDING')
  self.f.before=before;q,r=self.submit('place_block');self.assertTrue(r['evidence'][0]['raw_base64'])
  q=request();self.c.observe();n=len(self.f.posts())
  with patch.object(self.c.ledger,'save',side_effect=OSError('fixture')):
   with self.assertRaises(OSError):self.c.start(q)
  self.assertEqual(len(self.f.posts()),n)
 def test_tnt_current_false_facts_and_outside150_exact_ray(self):
  d=copy.deepcopy(PLAN_DATA);d['worksites'][0]['break_targets'][1].update(z=3,face='SOUTH');p=make_plan(d);self.c.plan=p;q=request('break_block',p,1);prepare(self.f.obs,q);self.c.observe();self.assertEqual(self.c.start(q)['state'],'CLOSED')
 def test_tnt_unstable_power_heat_and_missing_neighbors_reject(self):
  for fact in ('unstable','neighbor_signal','adjacent_fire_or_lava'):
   q=request('break_block',target_index=1);prepare(self.f.obs,q);self.f.obs['ray_target_witness'][fact]=True;self.c.observe()
   with self.assertRaises(Refused):self.c.start(q)
  q=request('break_block',target_index=1);prepare(self.f.obs,q);self.f.obs['ray_target_witness']['complete']=False;self.f.obs['ray_target_witness']['neighbor_signal']=None;self.f.obs['ready']=False;self.c.observe()
  with self.assertRaises(Refused):self.c.start(q)
  self.assertEqual(self.f.posts(),[])
 def test_place_wrong_hit_occupied_target_wrong_stack_anchor_reject(self):
  for mode in ('hit','occupied','stack','ray'):
   self.f.obs=observation();q=request('place_block');prepare(self.f.obs,q)
   if mode=='hit':self.f.obs['ray']['point']['y']-=.1
   if mode=='occupied':next(c for c in self.f.obs['local_blocks'] if (c['dx'],c['dy'],c['dz'])==(0,-1,1)).update(id='minecraft:stone',collision=True,collision_boxes=[[0,0,0,1,1,1]])
   if mode=='stack':self.f.obs['hotbar'][3]['item_id']='minecraft:flint_and_steel'
   if mode=='ray':self.f.obs['ray']['face']='EAST'
   self.c.observe()
   with self.assertRaises(Refused):self.c.start(q)
  self.assertEqual(self.f.posts(),[])
 def test_current_support_cannot_be_broken(self):
  d=copy.deepcopy(PLAN_DATA);d['worksites'][0]['break_targets'][0]['z']=0;p=make_plan(d);self.c.plan=p;q=request('break_block',p);prepare(self.f.obs,q);self.c.observe()
  with self.assertRaises(Refused):self.c.start(q)
 def test_embedded_tnt_below_intact_floor_not_global_rejection(self):
  c=next(c for c in self.f.obs['local_blocks'] if (c['dx'],c['dy'],c['dz'])==(0,-2,0));c['id']='minecraft:tnt';self.submit('look')
 def test_no_unsupported_items_kinds_hand_or_batch(self):
  q=request('place_block')
  for delta in ({'item_id':'minecraft:tnt'},{'hand':'OFF_HAND'},{'samples':2},{'kind':'attack_entity'},{'anchor_block_id':'minecraft:chest'}):
   with self.assertRaises(Refused):request_valid(dict(q,**delta))
 def test_plan_global_counts_duplicates_context_snapshot(self):
  for change in ({'version':2},{'kind':'navigation'},{'targets':[]}):
   d=copy.deepcopy(PLAN_DATA);d.update(change)
   with self.assertRaises(Refused):make_plan(d)
  d=copy.deepcopy(PLAN_DATA);d['worksites'][0]['break_targets']*=2
  with self.assertRaises(Refused):make_plan(d)
  q=request('place_block');validate_snapshot(PLAN.snapshot(),q)
  with self.assertRaises(Refused):validate_snapshot(PLAN.snapshot(),dict(q,stage_id='absent'))
  with self.assertRaises(Refused):validate_snapshot(PLAN.snapshot(),dict(q,hit_y=54.5))
 def test_navigation_budgets_preserve_one_jump(self):
  d=copy.deepcopy(PLAN_DATA);d['navigation'][0].update(jump_first=True,max_moves=1);p=make_plan(d);self.c.plan=p;q=request('move',p);self.c.observe();self.c.start(q)
  with self.assertRaises(Refused):self.c.start(dict(q,id=str(uuid4())))
 def test_byte_near24m_preintent_and_cleanup_reserve(self):
  r=next(iter(self.c.ledger.data['actions'].values()));r['fixture_padding']='';r['fixture_padding']='x'*(self.c.ledger.MAX_BYTES-3*MAX_RESPONSE*2-1000-len(encode(self.c.ledger.data)));self.c.ledger.save();q=request();self.c.observe()
  with self.assertRaises(Refused):self.c.start(q)
  self.assertNotIn(q['id'],self.c.report()['actions']);self.assertEqual(self.f.posts(),[])
 def test_old_known_terminal_after_bad_get_remains_known(self):
  q,r=self.submit();terminal=copy.deepcopy(r['terminal_native']);self.f.fail=True;self.c.status(q['id']);self.assertEqual(self.c.report(q['id'])['state'],'CLOSED');self.assertEqual(self.c.report(q['id'])['terminal_native'],terminal)
 def test_current_primed_or_overflow_blocks_planned_effect_not_status(self):
  q,r=self.submit();terminal=copy.deepcopy(r['terminal_native'])
  for state in ({'count':1,'complete':True,'overflow':False},{'count':32,'complete':False,'overflow':True},{'count':0,'complete':False,'overflow':False}):
   self.f.obs['local_primed_tnt']=state;self.c.observe()
   with self.assertRaises(Refused):self.c.start(request())
  self.c.status(q['id']);self.assertEqual(self.c.report(q['id'])['state'],'CLOSED');self.assertEqual(self.c.report(q['id'])['terminal_native'],terminal)
 def test_actual_hit_tolerance_bound_to_plan_and_digest(self):
  q=request('place_block');q['hit_y']+=.00005;prepare(self.f.obs,q);self.c.observe();self.assertEqual(self.c.start(q)['state'],'CLOSED')
  changed=dict(q,hit_y=q['hit_y']+.0001)
  with self.assertRaises(Refused):validate_snapshot(PLAN.snapshot(),changed)
  self.assertNotEqual(payload_digest(q),payload_digest(changed))
 def test_partial_known_break_consumes_target_and_preserves_protocol(self):
  self.f.count=1;self.f.modify=lambda r:dict(r,gameplay_outcome='target_unchanged',reason='deadline_reached')
  q,r=self.submit('break_block');self.assertEqual(r['state'],'CLOSED');self.assertFalse(self.c.report()['unknown_lock'])
  with self.assertRaises(Refused):self.submit('break_block')
 def test_pending_cleanup_near24m_and_reopen_above_old8m(self):
  self.f.state='ACTIVE';q,_=self.submit();data=self.c.ledger.data;r=next(iter(data['actions'].values()));r['fixture_padding']='';r['fixture_padding']='x'*(self.c.ledger.MAX_BYTES-3*MAX_RESPONSE*2-10000-len(encode(data)));self.c.ledger.save();self.c.status(q['id']);self.f.state='SETTLED';self.c.stop(q['id']);self.c.status(q['id']);self.assertEqual(self.c.report(q['id'])['state'],'CLOSED')
  self.c.close();self.c=Controller(self.d,self.f,PLAN);self.assertGreater(len(encode(self.c.report())),8*1024*1024);self.assertEqual(self.c.report(q['id'])['state'],'CLOSED')
 def test_512_count_bound_before_intent(self):
  for _ in range(512-len(self.c.ledger.data['actions'])):
   q=request();r=receipt(q);self.c.ledger.data['actions'][q['id']]=dict(request=q,state='CLOSED',unknown_reasons=[],evidence=[],latest_native=r,terminal_native=r,stop_attempted=False,plan=PLAN.snapshot())
  self.c.ledger.save();self.c.observe();q=request()
  with self.assertRaises(Refused):self.c.start(q)
  self.assertNotIn(q['id'],self.c.report()['actions']);self.assertEqual(self.f.posts(),[])
 def test_predecessor_v4_original_plan_reader_and_route(self):
  from navigation4_controller.plan import Plan as OldPlan
  from navigation4_controller.schema import payload_digest as old_digest
  olddata=dict(version=2,kind='navigation',context=PLAN_DATA['context'],stages=[STAGE]);raw=encode(olddata);p=OldPlan(raw,hashlib.sha256(raw).hexdigest());q=request('move');q.update(profile='recovery_navigation_v4',plan_version=2,plan_sha256=p.sha256)
  r=receipt(q);r['payload_digest']=old_digest(q)
  record=dict(request=q,state='CLOSED',unknown_reasons=[],evidence=[],latest_native=r,terminal_native=r,stop_attempted=False,plan=p.snapshot());self.c.ledger.data['actions'][q['id']]=record;self.c.ledger.save();self.c.close();self.c=Controller(self.d,self.f,PLAN)
  self.assertEqual(encode(self.c.report(q['id'])),encode(record));self.assertEqual(self.c.route(q),V4Controller.route(q));self.c.start(q);self.assertEqual(self.f.posts(),[])
 def test_post_target_witness_is_current_fact_not_unknown_unlock(self):
  from maintenance5_controller.assessment import assess_target
  q,r=self.submit('place_block');o=copy.deepcopy(self.f.obs);o['client_tick']+=1;o['latest_target_witness']=dict(action_id=q['id'],x=q['x'],y=q['y'],z=q['z'],id='minecraft:andesite',fluid='minecraft:empty',loaded=True,complete=True)
  c=next(c for c in o['local_blocks'] if (c['dx'],c['dy'],c['dz'])==(0,-1,1));c.update(id='minecraft:andesite',collision=True,collision_boxes=[[0,0,0,1,1,1]])
  self.assertTrue(assess_target(r,o)['qualification']);r['state']='UNKNOWN';self.assertFalse(assess_target(r,o)['qualification']);self.assertTrue(assess_target(r,o)['target_observed_expected'])
  r['state']='CLOSED';o['local_primed_tnt']['count']=1;self.assertFalse(assess_target(r,o)['qualification']);o['local_primed_tnt']['count']=0;o['latest_target_witness']['action_id']=str(uuid4())
  with self.assertRaises(Refused):assess_target(r,o)
 def test_post_air_requires_matching_original_current_context_and_no_other_diff(self):
  from maintenance5_controller.assessment import assess_target
  q,r=self.submit('break_block');o=copy.deepcopy(self.f.obs);o['client_tick']+=1;o['latest_target_witness']=dict(action_id=q['id'],x=q['x'],y=q['y'],z=q['z'],id='minecraft:air',fluid='minecraft:empty',loaded=True,complete=True)
  self.assertTrue(assess_target(r,o)['qualification']);o['local_blocks'][0]['id']='minecraft:andesite';self.assertFalse(assess_target(r,o)['qualification']);o['world_generation']=str(uuid4())
  with self.assertRaises(Refused):assess_target(r,o)

 def test_changed_plan_cannot_reissue_target_or_jump_same_context(self):
  self.f.count=0;self.submit('break_block');d=copy.deepcopy(PLAN_DATA);d['worksites'][0]['max_looks']+=1;p=make_plan(d);self.c.plan=p;q=request('break_block',p);prepare(self.f.obs,q);self.c.observe()
  with self.assertRaises(Refused):self.c.start(q)
  d=copy.deepcopy(PLAN_DATA);d['navigation'][0].update(jump_first=True,max_moves=1);p=make_plan(d);self.c.plan=p;q=request('move',p);self.c.observe();self.c.start(q)
  d['worksites'][0]['max_looks']+=2;p=make_plan(d);self.c.plan=p;q=request('move',p);self.c.observe()
  with self.assertRaises(Refused):self.c.start(q)

 def test_tnt_one_native_call_plan_request_and_history(self):
  q=request('break_block',target_index=1)
  with self.assertRaises(Refused):request_valid(dict(q,max_calls=2))
  d=copy.deepcopy(PLAN_DATA);d['worksites'][0]['break_targets'][1]['max_calls']=32
  with self.assertRaises(Refused):make_plan(d)
  with self.assertRaises(Refused):Controller.validate_request(dict(q,max_calls=32))
 def test_incomplete_witness_preserves_partial_facts_without_admission(self):
  q=request('break_block',target_index=1);prepare(self.f.obs,q);self.f.obs['ray_target_witness']['complete']=False;self.f.obs['ready']=False;self.c.observe()
  with self.assertRaises(Refused):self.c.start(q)
  self.f.obs['ray_target_witness'].update(id=None,fluid=None);self.c.observe()
  self.f.obs['latest_target_witness']=dict(action_id=q['id'],x=0,y=53,z=1,id=None,fluid=None,loaded=True,complete=False);self.c.observe()
  self.assertEqual(self.f.posts(),[])

 def test_normal_navigation_move_look_budgets_survive_changed_plan(self):
  for _ in range(PLAN_DATA['navigation'][0]['max_moves']):self.submit('move')
  d=copy.deepcopy(PLAN_DATA);d['worksites'][0]['max_looks']+=1;p=make_plan(d);self.c.plan=p;q=request('move',p);self.c.observe()
  with self.assertRaises(Refused):self.c.start(q)
  for _ in range(PLAN_DATA['navigation'][0]['max_looks']):
   q=request('look',p);q['stage_id']='north';self.c.observe();self.c.start(q)
  d['worksites'][0]['max_looks']+=1;p=make_plan(d);self.c.plan=p;q=request('look',p);q['stage_id']='north';self.c.observe()
  with self.assertRaises(Refused):self.c.start(q)

 def test_worksite_look_select_budgets_survive_derived_plan(self):
  for kind,budget in (('look','max_looks'),('select_hotbar','max_selects')):
   for _ in range(PLAN_DATA['worksites'][0][budget]):self.submit(kind)
   d=copy.deepcopy(PLAN_DATA);d['navigation'][0]['target']['z']=-1.1;p=make_plan(d);self.c.plan=p;q=request(kind,p);self.c.observe()
   with self.assertRaises(Refused):self.c.start(q)
   self.c.plan=PLAN

 def test_place_result_before_completecall_is_not_known_zero(self):
  q=request('place_block')
  for state in ('ACTIVE','STOPPING','UNKNOWN'):
   r=receipt(q,state,0);r['gameplay_outcome']='place_pass_target_unchanged';receipt_valid(r,q)
  r=receipt(q,'SETTLED',0);r['gameplay_outcome']='place_pass_target_unchanged'
  with self.assertRaises(Refused):receipt_valid(r,q)

 def test_v5_refusal_2second_40tick_bounds_do_not_change_old_readers(self):
  from maintenance5_controller.schema import refusal_valid
  from navigation4_controller.schema import refusal_valid as old_refusal
  valid=dict(stage='admit',age_ns=1500000000,tick_delta=30,predicate_mask=15);refusal_valid(valid)
  with self.assertRaises(Refused):old_refusal(valid)
  refusal_valid(dict(stage='admit',age_ns=2000000001,tick_delta=0,predicate_mask=1))
  refusal_valid(dict(stage='admit',age_ns=2000000000,tick_delta=41,predicate_mask=7))
  with self.assertRaises(Refused):refusal_valid(dict(stage='admit',age_ns=1000000001,tick_delta=0,predicate_mask=1))
  with self.assertRaises(Refused):refusal_valid(dict(stage='admit',age_ns=1,tick_delta=21,predicate_mask=7))
