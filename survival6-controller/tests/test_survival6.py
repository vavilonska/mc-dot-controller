"""Bounded offline public tests. Actual338 retained; all new gameplay is synthetic."""
import copy,hashlib,json,sys,tempfile,unittest
from pathlib import Path
from uuid import uuid4
from fixtures import *
from survival6_controller import load_plan
from survival6_controller import schema
from survival6_controller.policy import gate,survival_valid
from survival6_controller.plan import validate_snapshot
from survival6_controller.legacy import Refused
from navigation5_controller import Controller as PreviousController
class Cases(unittest.TestCase):
 def setup(self,tmp,p=None):
  d=Path(tmp)/'ledger';clone(d);p=p or plan();f=Fake();c=Controller(d,f,p);return d,p,f,c
 def old_exact(self,c):
  for aid,r in BASE['actions'].items():self.assertEqual(encode(c.ledger.data['actions'][aid]),encode(r))
 def submit(self,c,p,f,kind,slot=1):
  f.obs['selected_slot']=8 if kind=='attack_blaze'else 1
  o=c.observe();q=request(kind,p,o,slot);return q,c.start(q)
 def test_actual338_mixed_original_readers_all_bytes_preserved(self):
  with tempfile.TemporaryDirectory()as t:
   d,p,f,c=self.setup(t)
   try:self.assertEqual(len(c.ledger.data['actions']),338);self.assertEqual((d/'ledger.json').read_bytes(),BASE_RAW);self.old_exact(c);self.assertFalse(c.ledger.data['unknown_lock']);self.assertEqual(f.calls,[])
   finally:c.close()
 def test_closed_plan_no_fake_worksites_and_finite_typed_stages(self):
  p=plan();self.assertEqual(len(p.data['survival']),4)
  for mode in ('kind','worksites','stagekind','budget','slot','ticks','duplicate','empty','nan'):
   d=copy.deepcopy(DATA)
   if mode=='kind':d['kind']='maintenance'
   elif mode=='worksites':d['worksites']=[]
   elif mode=='stagekind':d['survival'][0]['kind']='break_block'
   elif mode=='budget':d['survival'][0]['max_intents']=2
   elif mode=='slot':d['survival'][0]['slot']=3
   elif mode=='ticks':d['survival'][-1]['max_use_ticks']=41
   elif mode=='duplicate':d['survival'][0]['id']='north'
   elif mode=='empty':d['navigation']=[];d['survival']=[]
   else:d['navigation'][0]['target']['x']=float('nan')
   with self.subTest(mode=mode),self.assertRaises((Refused,ValueError)):plan(d)
  for nav_only in (True,False):
   d=copy.deepcopy(DATA);d['survival'if nav_only else'navigation']=[];plan(d)
 def test_plan_raw_duplicate_nonfinite_hash_symlink(self):
  p=plan()
  for raw in(p.raw.replace(b'"version":4',b'"version":4,"version":4'),p.raw.replace(b'"max_use_ticks":40',b'"max_use_ticks":NaN')):
   with self.assertRaises(Refused):Plan(raw,hashlib.sha256(raw).hexdigest())
  with tempfile.TemporaryDirectory()as t:
   path=Path(t)/'PLAN';path.write_bytes(p.raw);self.assertEqual(load_plan(path,p.sha256),p)
   link=Path(t)/'link';link.symlink_to(path)
   with self.assertRaises(Refused):load_plan(link,p.sha256)
   with self.assertRaises(Refused):load_plan(path,'0'*64)
 def test_request_bounds_and_complete_digest_identity(self):
  p=plan()
  for kind in ('move','look','select_hotbar','attack_blaze','consume_bread'):
   q=request(kind,p);schema.request_valid(q);r=receipt(q);schema.receipt_valid(r,q)
   for key,value in [('plan_sha256','f'*64),('stage_id','different')]:
    changed=dict(q,**{key:value});self.assertNotEqual(schema.payload_digest(q),schema.payload_digest(changed))
  q=request('attack_blaze',p)
  for key,value in [('target_entity_id',-1),('target_uuid',str(uuid4())),('stack_fingerprint','f'*64)]:
   changed=dict(q,**{key:value});schema.request_valid(changed);self.assertNotEqual(schema.payload_digest(q),schema.payload_digest(changed))
  for kind,key,value in [('attack_blaze','target_type','minecraft:zombie'),('select_hotbar','slot',2),('consume_bread','max_use_ticks',41),('attack_blaze','ttl_ms',4000),('consume_bread','ttl_ms',4001),('look','yaw',180),('move','samples',9)]:
   q=request(kind,p);q[key]=value
   with self.subTest(kind=kind,key=key),self.assertRaises(Refused):schema.request_valid(q)
 def test_five_new_kinds_and_reload_mixed_338_no_old_reader_rollback(self):
  with tempfile.TemporaryDirectory()as t:
   d,p,f,c=self.setup(t)
   try:
    for kind in ('move','look','select_hotbar','attack_blaze','consume_bread'):
     q,r=self.submit(c,p,f,kind);self.assertEqual(r['state'],'CLOSED');validate_snapshot(r['plan'],q)
    self.old_exact(c);self.assertEqual(len(f.starts()),5)
   finally:c.close()
   c=Controller(d,f,None)
   try:self.assertEqual(len(c.ledger.data['actions']),343);self.old_exact(c)
   finally:c.close()
   with self.assertRaises(Refused):PreviousController(d,f,None)
 def test_old_exact_id_reports_and_old_status_stop_need_no_new_plan(self):
  with tempfile.TemporaryDirectory()as t:
   d,p,f,c=self.setup(t)
   try:
    old=next(r for r in BASE['actions'].values()if r['request'].get('kind')=='place_block'and not r['stop_attempted']);q=old['request'];self.assertEqual(c.start(q)['request'],q);self.assertEqual(f.calls,[])
    with self.assertRaises(Refused):c.start(dict(q,ttl_ms=100))
    f.historical=old;c.plan=None;c.status(q['id']);c.stop(q['id']);c.stop(q['id']);self.assertEqual(len(f.stops()),1);self.assertEqual(c.ledger.data['actions'][q['id']]['terminal_native'],old['terminal_native'])
    self.assertEqual(c.ledger.data['actions'][q['id']]['evidence'][:len(old['evidence'])],old['evidence'])
   finally:c.close()
 def test_old_profile_new_id_and_bad_stage_cannot_dispatch(self):
  with tempfile.TemporaryDirectory()as t:
   d,p,f,c=self.setup(t)
   try:
    q=copy.deepcopy(LAST['request']);q['id']=str(uuid4())
    with self.assertRaises(Refused):c.start(q)
    c.observe();q=request('attack_blaze',p);q['stage_id']='eat'
    with self.assertRaises(Refused):c.start(q)
    self.assertEqual(f.starts(),[]);self.assertEqual(len(c.ledger.data['actions']),338)
   finally:c.close()
 def test_one_stage_budget_across_hash_knownzero_but_new_stage_explicit(self):
  with tempfile.TemporaryDirectory()as t:
   d,p,f,c=self.setup(t)
   try:
    f.mode='zero';q,r=self.submit(c,p,f,'attack_blaze');self.assertEqual(r['terminal_native']['applied_calls'],0)
    p2=plan(suffix=b' ');c.plan=p2;c.observe()
    with self.assertRaises(Refused):c.start(request('attack_blaze',p2))
    d2=copy.deepcopy(DATA);d2['survival'].append(dict(id='new-deliberate-strike',kind='attack_blaze',max_intents=1));p3=plan(d2);c.plan=p3;c.observe();q2=request('attack_blaze',p3);q2['stage_id']='new-deliberate-strike';c.start(q2)
    self.assertEqual(len(f.starts()),2);self.old_exact(c)
   finally:c.close()
 def test_current_attack_and_stack_predicates_and_low_hp_not_unknown(self):
  p=plan();o=observation();o['selected_slot']=8;q=request('attack_blaze',p,o);gate(o,q,OWNER,{},p)
  for mode in ('uuid','entity_id','type','dead','cooldown','slot','stack','using','nohit','incomplete'):
   v=copy.deepcopy(o)
   if mode in ('uuid','entity_id','type'):v['survival']['entity_hit'][mode]=str(uuid4())if mode=='uuid'else 13 if mode=='entity_id'else'minecraft:zombie'
   elif mode=='dead':v['survival']['entity_hit']['alive']=False
   elif mode=='cooldown':v['survival']['attack_strength']=.999
   elif mode=='slot':v['selected_slot']=1
   elif mode=='stack':v['hotbar'][8]['stack_fingerprint']='f'*64
   elif mode=='using':v['survival'].update(is_using_item=True,used_hand='MAIN_HAND')
   elif mode=='nohit':v['survival']['entity_hit']=None
   else:v['ready']=False;v['survival']={k:False if k=='complete'else None for k in v['survival']}
   with self.subTest(mode=mode),self.assertRaises(Refused):gate(v,q,OWNER,{},p)
  o['survival']['attack_strength']=1.0;o['health']=1.;o['survival']['hurt_time']=10;gate(o,q,OWNER,{},p)
 def test_current_bread_hunger_and_no_other_use_adoption(self):
  p=plan();o=observation();q=request('consume_bread',p,o);gate(o,q,OWNER,{},p)
  for mode in ('full','slot','item','using'):
   v=copy.deepcopy(o)
   if mode=='full':v['survival']['food_level']=20
   elif mode=='slot':v['selected_slot']=8
   elif mode=='item':v['hotbar'][1]['item_id']='minecraft:apple'
   else:v['survival'].update(is_using_item=True,used_hand='OFF_HAND',use_remaining_ticks=-2)
   with self.subTest(mode=mode),self.assertRaises(Refused):gate(v,q,OWNER,{},p)
 def test_survival_observation_nullable_signed_fields_and_closed_keys(self):
  o=observation();o['survival']['use_remaining_ticks']=-2147483648;o['survival']['entity_hit']['entity_id']=-2147483648;survival_valid(o)
  for mode in ('extra','remaining','hand','falsecomplete','provider'):
   v=copy.deepcopy(o)
   if mode=='extra':v['survival']['extra']=0
   elif mode=='remaining':v['survival']['use_remaining_ticks']=-2147483649
   elif mode=='hand':v['survival']['used_hand']='MAIN_HAND'
   elif mode=='falsecomplete':v['survival']['complete']=False
   else:v['survival']['entity_hit']['provider_class']='other.Blaze'
   with self.subTest(mode=mode),self.assertRaises(Refused):survival_valid(v)
  o['survival']['entity_hit']=None;survival_valid(o)
  o['world_generation']=None;o['ready']=False;o['survival']={k:False if k=='complete'else None for k in o['survival']};survival_valid(o)
 def test_returned_fail_and_unfinished_use_are_not_zero_or_consumed_claim(self):
  p=plan();q=request('consume_bread',p)
  for out in schema.USE_RESULTS:
   schema.receipt_valid(receipt(q,count=1,outcome='use_'+out),q)
  for state in ('ACTIVE','STOPPING','UNKNOWN'):
   r=receipt(q,state,0,outcome='use_fail');schema.receipt_valid(r,q)
  r=receipt(q,count=0,outcome='use_fail')
  with self.assertRaises(Refused):schema.receipt_valid(r,q)
  with tempfile.TemporaryDirectory()as t:
   d,p,f,c=self.setup(t)
   try:f.mode='fail_returned';q,r=self.submit(c,p,f,'consume_bread');self.assertEqual(r['state'],'CLOSED');self.assertEqual(r['terminal_native']['applied_calls'],1);self.assertEqual(len(f.starts()),1)
   finally:c.close()
 def test_consume_four_seconds_uses_quarter_second_poll_and_reserved_evidence(self):
  with tempfile.TemporaryDirectory()as t:
   d,p,f,c=self.setup(t)
   try:
    f.mode='duration';q,r=self.submit(c,p,f,'consume_bread');self.assertEqual(r['state'],'PENDING');self.assertEqual(r['latest_native']['applied_calls'],1)
    r=c.finish_one_step(q['id'],clock=f.clock,sleep=f.clock.sleep);self.assertEqual(r['state'],'CLOSED');self.assertEqual(f.clock.t,4.);self.assertTrue(all(s==.25 for s in f.clock.sleeps));self.assertLessEqual(len(r['evidence']),20);self.assertEqual(f.stops(),[]);self.assertEqual(len(f.starts()),1)
   finally:c.close()
 def test_consume_missing_terminal_exact_stop_slots_unknown_stays(self):
  with tempfile.TemporaryDirectory()as t:
   d,p,f,c=self.setup(t)
   try:
    f.mode='never';q,_=self.submit(c,p,f,'consume_bread');r=c.finish_one_step(q['id'],clock=f.clock,sleep=f.clock.sleep)
    self.assertEqual(r['state'],'UNKNOWN');self.assertEqual(f.clock.t,4.5);self.assertEqual(len(f.stops()),1);self.assertEqual(f.stops()[0][2]['id'],q['id']);self.assertLessEqual(len(r['evidence']),24)
    f.mode='normal';c.status(q['id']);self.assertEqual(c.report(q['id'])['state'],'UNKNOWN')
    c.plan=plan(suffix=b' ');c.observe()
    with self.assertRaises(Refused):c.start(request('consume_bread',c.plan))
   finally:c.close()
 def test_old_and_nonconsume_finish_delegated_unchanged(self):
  with tempfile.TemporaryDirectory()as t:
   d,p,f,c=self.setup(t)
   try:
    f.mode='never';q,_=self.submit(c,p,f,'attack_blaze');r=c.finish_one_step(q['id'],clock=f.clock,sleep=f.clock.sleep);self.assertTrue(all(s==.1 for s in f.clock.sleeps));self.assertEqual(r['state'],'UNKNOWN');self.assertEqual(len(f.stops()),1)
   finally:c.close()
 def test_lost_response_and_restart_pending_do_not_reissue(self):
  with tempfile.TemporaryDirectory()as t:
   d,p,f,c=self.setup(t)
   try:
    f.mode='lost';q,r=self.submit(c,p,f,'consume_bread');self.assertEqual(r['state'],'UNKNOWN');self.assertEqual(c.start(q)['state'],'UNKNOWN');self.assertEqual(len(f.starts()),1)
    c.ledger.data['actions'][q['id']]['state']='PENDING';c.ledger.data['unknown_lock']=False;c.ledger.save()
   finally:c.close()
   c=Controller(d,f,p)
   try:self.assertTrue(c.ledger.data['unknown_lock']);self.assertEqual(c.report(q['id'])['state'],'UNKNOWN');self.assertIn('restart_with_unsettled_original',c.report(q['id'])['unknown_reasons'])
   finally:c.close()
 def test_old_v5_pending_or_unknown_blocks_new_v6_plan(self):
  for state in ('PENDING','UNKNOWN'):
   with self.subTest(state=state),tempfile.TemporaryDirectory()as t:
    data=copy.deepcopy(BASE);aid=LAST['request']['id'];data['actions'][aid]['state']=state;data['unknown_lock']=state=='UNKNOWN'
    d=Path(t)/'ledger';clone(d,encode(data));f=Fake();p=plan();c=Controller(d,f,p)
    try:
     self.assertEqual(c.ledger.data['actions'][aid]['state'],'UNKNOWN');self.assertTrue(c.ledger.data['unknown_lock']);c.observe()
     with self.assertRaises(Refused):c.start(request('consume_bread',p))
     self.assertEqual(f.starts(),[]);self.assertEqual(c.ledger.data['actions'][aid]['request'],LAST['request']);self.assertEqual(c.ledger.data['actions'][aid]['terminal_native'],LAST['terminal_native'])
    finally:c.close()
 def test_durable_fence_before_fake_post_and_preintent_byte_refusal(self):
  with tempfile.TemporaryDirectory()as t:
   d,p,f,c=self.setup(t)
   try:
    checks=[]
    def before(method,path,body):
     if path.endswith('start'):
      saved=strict_json((d/'ledger.json').read_bytes());checks.append(saved['actions'][body['id']]['state']);self.assertTrue(all(saved['actions'][k]==v for k,v in BASE['actions'].items()))
    f.before=before;self.submit(c,p,f,'select_hotbar');self.assertEqual(checks,['PENDING']);self.old_exact(c)
    c.ledger.data['actions'][LAST['request']['id']]['unknown_reasons'].append('x'*c.ledger.MAX_BYTES);c.observe();q=request('consume_bread',p)
    with self.assertRaises(Refused):c.start(q)
    self.assertNotIn(q['id'],c.ledger.data['actions']);self.assertEqual(len(f.starts()),1)
   finally:c.close()
 def test_navigation_shape_and_cross_hash_budget_not_lost(self):
  p=plan();o=observation();q=request('move',p,o);gate(o,q,OWNER,{},p)
  history={str(i):{'request':dict(q,id=str(uuid4()),plan_sha256='e'*64)}for i in range(3)}
  with self.assertRaises(Refused):gate(o,q,OWNER,history,p)
  broken=copy.deepcopy(o);broken['local_blocks'][62]['loaded']=False;broken['local_blocks'][62].update(id=None,collision=None,fluid=None,collision_boxes=None);broken['collision_boxes_complete']=False;broken['ready']=False
  with self.assertRaises(Refused):gate(broken,q,OWNER,{},p)
 def test_original_snapshot_kind_is_not_reinterpreted(self):
  old=next(r for r in BASE['actions'].values()if r.get('plan',{}).get('parsed',{}).get('kind')=='navigation');changed=copy.deepcopy(old['plan']);changed['parsed']['kind']='survival'
  from navigation5_controller.controller import v5_snapshot
  with self.assertRaises(Refused):v5_snapshot(changed,old['request'])
  p=plan();q=request('attack_blaze',p);q['stage_id']='north'
  with self.assertRaises(Refused):validate_snapshot(p.snapshot(),q)
  d=copy.deepcopy(DATA);d['navigation'][0]['max_looks']=0;p=plan(d);q=request('look',p)
  with self.assertRaises(Refused):validate_snapshot(p.snapshot(),q)
 def test_reviewed_four_operation_template_synthetic_lifecycle(self):
  raw=(C/'source/plans/SURVIVAL-V6-FOUR-OPERATION-TEST-CONTEXT-UNBOUND.json').read_bytes();d=strict_json(raw);self.assertTrue(all(v=='00000000-0000-0000-0000-000000000000'for v in d['context'].values()))
  d['context']=CTX;p=plan(d)
  with tempfile.TemporaryDirectory()as t:
   path,p,f,c=self.setup(t,p)
   try:
    for stage in p.data['survival']:
     o=c.observe();q=request(stage['kind'],p,o,stage.get('slot',1));q['stage_id']=stage['id'];r=c.start(q);self.assertEqual(r['state'],'CLOSED');self.assertEqual(r['terminal_native']['applied_calls'],1)
     # Explicit synthetic model of the successful single selected-slot update.
     if q['kind']=='select_hotbar':f.obs['selected_slot']=q['slot']
    self.assertEqual([x[2]['kind']for x in f.starts()],['select_hotbar','attack_blaze','select_hotbar','consume_bread']);self.old_exact(c)
   finally:c.close()
if __name__=='__main__':unittest.main()
