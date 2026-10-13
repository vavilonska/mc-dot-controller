"""Independent safety boundary review. FakeQueue and TemporaryDirectory only."""
import copy,json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(Path(__file__).resolve().parent)]
sys.dont_write_bytecode=True
from independent_safety_fixture import *
from post_trial_safety import PostTrialSafety,SafetyHalt,NO_SUCCESS

class SafetyTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.p,self.q,self.o,self.report=configured(self.tmp.name)
  self.case=self.p.root/'case-000001';self.first=ENTITIES[0]['uuid'];self.second=ENTITIES[1]['uuid']
 def cleanup(self,uid=None):return self.p.cleanup_uuid(uid or self.first,'explicit-cleanup-auth')
 def assert_no_dispatch(self,fn):
  before=len(self.q.mutations)
  with self.assertRaises((SafetyHalt,ValueError,KeyError,TypeError)):fn()
  self.assertEqual(len(self.q.mutations),before)
 def edit(self,name,fn):
  path=self.case/name;x=json.loads(path.read_text());fn(x);path.write_text(json.dumps(x))
 def test_exact_uuid_kill_once(self):
  r=self.cleanup();self.assertTrue(r['effect_confirmed']);self.assertEqual(self.q.mutations,[{'op':'direct','endpoint':'command','body':{'command':'kill '+self.first}}])
 def test_cleanup_never_promotes_success(self):
  r=self.cleanup()
  for k in NO_SUCCESS:self.assertIs(r[k],False)
  self.assertIs(r['ordinary_mutation_permission'],False)
 def test_both_exact_uuid_cleanup(self):
  self.cleanup();self.cleanup(self.second);self.assertEqual(len(self.q.mutations),2)
 def test_repeated_uuid_not_resent(self):
  self.cleanup();self.assert_no_dispatch(lambda:self.cleanup())
 def test_selector_refused(self):self.assert_no_dispatch(lambda:self.cleanup('@e[type=zombie]'))
 def test_command_injection_refused(self):self.assert_no_dispatch(lambda:self.cleanup(self.first+'; say nope'))
 def test_uppercase_uuid_refused(self):self.assert_no_dispatch(lambda:self.cleanup(self.first.upper()))
 def test_third_uuid_refused(self):self.assert_no_dispatch(lambda:self.cleanup('c7777777-7777-4777-8777-777777777777'))
 def test_blank_authorization_refused(self):self.assert_no_dispatch(lambda:self.p.cleanup_uuid(self.first,''))
 def test_main_report_change_refused(self):
  path=self.o.out/'trial1.json';path.write_text(path.read_text()+' ');self.assert_no_dispatch(lambda:self.cleanup())
 def test_main_report_removal_refused(self):
  (self.o.out/'trial1.json').unlink();self.assert_no_dispatch(lambda:self.cleanup())
 def test_ordinary_mutation_blocked_after_resolution(self):
  self.assert_no_dispatch(lambda:self.p.assert_mutation_allowed(request_id='new',body={'op':'cancel'}))
 def test_scope_registration_tamper_cannot_kill_third(self):
  third=dict(ENTITIES[0],uuid='c7777777-7777-4777-8777-777777777777',entity_id=303)
  self.edit('registration.json',lambda x:x['entities'].__setitem__(0,third))
  self.q.obs['state']['nearby']['entities'][0]=dict(third,alive=True,health=20.)
  self.assert_no_dispatch(lambda:self.cleanup(third['uuid']))
 def test_registration_authority_tamper_rejected(self):
  self.edit('registration.json',lambda x:x.update(authorization_ref='replacement-not-original'))
  self.assert_no_dispatch(lambda:self.cleanup())
 def test_resolution_authority_tamper_rejected(self):
  self.edit('trial-resolution.json',lambda x:x.update(release_observed=False))
  self.assert_no_dispatch(lambda:self.cleanup())
 def test_reservation_command_tamper_rejected(self):
  self.edit('trial-reservation.json',lambda x:x['command'].update(timeout_ms=9999))
  self.assert_no_dispatch(lambda:self.cleanup())
 def test_context_tamper_refused(self):
  path=self.p.root/'context.json';x=json.loads(path.read_text());x['player_uuid']=W;path.write_text(json.dumps(x))
  self.assert_no_dispatch(lambda:self.cleanup())
 def test_context_removal_with_existing_case_refused(self):
  (self.p.root/'context.json').unlink();self.assert_no_dispatch(lambda:self.cleanup())
 def test_partial_registration_refused(self):
  (self.case/'registration.json').write_text('{');self.assert_no_dispatch(lambda:self.cleanup())
 def test_partial_intent_refused(self):
  (self.case/'cleanup-partial.intent.json').write_text('{');self.assert_no_dispatch(lambda:self.cleanup())
 def test_unclosed_mutation_intent_refused(self):
  (self.case/'cleanup-partial.intent.json').write_text(json.dumps({'body':{'op':'direct'},'read_only':False}))
  self.assert_no_dispatch(lambda:self.cleanup())
 def test_stop_marker_preserved(self):
  path=self.case/'SAFETY-STOP.json';path.write_text('{"reason":"original"}')
  self.assert_no_dispatch(lambda:self.cleanup());self.assertEqual(path.read_text(),'{"reason":"original"}')
 def test_old_operator_stop_preserved(self):
  path=self.o.out/'STOP-RECONCILE.json';path.write_text('{"reason":"original"}')
  self.cleanup();self.assertEqual(path.read_text(),'{"reason":"original"}')
 def test_intent_is_present_before_submit(self):
  original=self.q.submit
  def check(body,request_id=None):
   if body['op']=='direct':
    p=self.case/('cleanup-'+self.first+'.intent.json');self.assertTrue(p.is_file());x=json.loads(p.read_text());self.assertEqual(x['body'],body);self.assertEqual(x['request_id'],request_id)
   return original(body,request_id=request_id)
  self.q.submit=check;self.cleanup()
 def test_dispatch_receipt_and_effect_separate(self):
  self.cleanup();prefix=self.case/('cleanup-'+self.first)
  for suffix in ('.intent.json','.receipt.json','.effect.json'):self.assertTrue(Path(str(prefix)+suffix).is_file())
 def test_unknown_submit_no_replay(self):
  self.q.mutation_mode='submit_exception'
  with self.assertRaises(SafetyHalt):self.cleanup()
  self.assertEqual(len(self.q.mutations),1);self.q.mutation_mode='ok';self.assert_no_dispatch(lambda:self.cleanup())
 def test_unknown_wait_no_replay(self):
  self.q.mutation_mode='wait_exception'
  with self.assertRaises(SafetyHalt):self.cleanup()
  self.assertEqual(len(self.q.mutations),1);self.assertTrue((self.case/'SAFETY-STOP.json').exists());self.assert_no_dispatch(lambda:self.cleanup())
 def test_wrong_submit_id_no_replay(self):
  self.q.mutation_mode='wrong_submit_id'
  with self.assertRaises(SafetyHalt):self.cleanup()
  self.assertEqual(len(self.q.mutations),1);self.assert_no_dispatch(lambda:self.cleanup())
 def test_pending_receipt_no_replay(self):
  self.q.mutation_mode='pending'
  with self.assertRaises(SafetyHalt):self.cleanup()
  self.assert_no_dispatch(lambda:self.cleanup())
 def test_failed_receipt_no_replay(self):
  self.q.mutation_mode='failed'
  with self.assertRaises(SafetyHalt):self.cleanup()
  self.assert_no_dispatch(lambda:self.cleanup())
 def test_uncertain_receipt_no_replay(self):
  self.q.mutation_mode='uncertain'
  with self.assertRaises(SafetyHalt):self.cleanup()
  self.assert_no_dispatch(lambda:self.cleanup())
 def test_submitted_without_effect_not_success(self):
  self.q.mutation_mode='no_effect'
  with self.assertRaises(SafetyHalt):self.cleanup()
  self.assertFalse((self.case/('cleanup-'+self.first+'.effect.json')).exists());self.assertEqual(len(self.q.mutations),1)
 def test_restart_after_unknown_no_replay(self):
  self.q.mutation_mode='wait_exception'
  with self.assertRaises(SafetyHalt):self.cleanup()
  self.p=PostTrialSafety(self.o,self.p.root);self.assert_no_dispatch(lambda:self.cleanup())
 def test_new_output_same_ledger_cannot_reset(self):
  self.o.out=Path(self.tmp.name)/'new-output';self.o.out.mkdir();fresh=PostTrialSafety(self.o,self.p.root)
  self.assert_no_dispatch(lambda:fresh.reserve_trial(self.q.b,command_body(),'new-trial'))
 def test_new_output_after_success_cannot_replay_kill(self):
  self.cleanup();self.o.out=Path(self.tmp.name)/'new-output';self.o.out.mkdir();self.p=PostTrialSafety(self.o,self.p.root)
  self.assert_no_dispatch(lambda:self.cleanup())
 def test_held_key_refused(self):
  self.q.obs['status']['held_mappings']=['key.up'];self.assert_no_dispatch(lambda:self.cleanup())
 def test_held_mouse_refused(self):
  self.q.obs['status']['mouse']['held_world_buttons']=['left'];self.assert_no_dispatch(lambda:self.cleanup())
 def test_using_item_refused(self):
  self.q.obs['state']['player']['using_item']=True;self.assert_no_dispatch(lambda:self.cleanup())
 def test_sprinting_refused(self):
  self.q.obs['state']['player']['sprinting']=True;self.assert_no_dispatch(lambda:self.cleanup())
 def test_wrong_world_refused(self):
  self.q.obs['state']['world']['world_generation']=P;self.assert_no_dispatch(lambda:self.cleanup())
 def test_wrong_player_refused(self):
  self.q.obs['state']['player']['uuid']=W;self.assert_no_dispatch(lambda:self.cleanup())
 def test_wrong_action_session_refused(self):
  self.q.obs['state']['client_action']['action_session']=W;self.assert_no_dispatch(lambda:self.cleanup())
 def test_active_resident_refused(self):
  self.q.session_mutator=lambda x:x.update(active_request_id='foreign');self.assert_no_dispatch(lambda:self.cleanup())
 def test_pending_resident_refused(self):
  self.q.session_mutator=lambda x:x.update(pending=1);self.assert_no_dispatch(lambda:self.cleanup())
 def test_missing_pending_refused(self):
  self.q.session_mutator=lambda x:x.pop('pending');self.assert_no_dispatch(lambda:self.cleanup())
 def test_active_native_session_refused(self):
  self.q.session_mutator=lambda x:x.update(active_action_id='foreign');self.assert_no_dispatch(lambda:self.cleanup())
 def test_aim_lock_refused(self):
  self.q.obs['aim_lock']['active']=True;self.assert_no_dispatch(lambda:self.cleanup())
 def test_combat_auto_refused(self):
  self.q.obs['combat']['active']=True;self.assert_no_dispatch(lambda:self.cleanup())
 def test_auto_held_keys_refused(self):
  self.q.obs['combat']['held_mappings']=['key.use'];self.assert_no_dispatch(lambda:self.cleanup())
 def test_running_native_refused(self):
  self.q.obs['action']=native(self.q.b,'running');self.assert_no_dispatch(lambda:self.cleanup())
 def test_terminal_id_changed_refused(self):
  self.q.obs['action']['action_id']='foreign';self.assert_no_dispatch(lambda:self.cleanup())
 def test_nearby_truncated_refused(self):
  self.q.obs['state']['nearby']['truncated']=True;self.assert_no_dispatch(lambda:self.cleanup())
 def test_nearby_missing_total_refused(self):
  self.q.obs['state']['nearby'].pop('total');self.assert_no_dispatch(lambda:self.cleanup())
 def test_nearby_count_mismatch_refused(self):
  self.q.obs['state']['nearby']['returned']=1;self.assert_no_dispatch(lambda:self.cleanup())
 def test_nearby_duplicate_uuid_refused(self):
  values=self.q.obs['state']['nearby']['entities'];values[1]['uuid']=values[0]['uuid'];self.assert_no_dispatch(lambda:self.cleanup())
 def test_nearby_duplicate_entity_id_refused(self):
  values=self.q.obs['state']['nearby']['entities'];values[1]['entity_id']=values[0]['entity_id'];self.assert_no_dispatch(lambda:self.cleanup())
 def test_target_id_reuse_refused(self):
  self.q.obs['state']['nearby']['entities'][0]['uuid']='c7777777-7777-4777-8777-777777777777';self.assert_no_dispatch(lambda:self.cleanup())
 def test_target_type_change_refused(self):
  self.q.obs['state']['nearby']['entities'][0]['type']='minecraft:pig';self.assert_no_dispatch(lambda:self.cleanup())
 def test_target_absent_before_dispatch_refused(self):
  n=self.q.obs['state']['nearby'];n['entities']=n['entities'][1:];n.update(total=1,returned=1);self.assert_no_dispatch(lambda:self.cleanup())
 def test_target_outside_radius_refused(self):
  self.q.obs['state']['nearby']['entities'][0]['x']=100.;self.assert_no_dispatch(lambda:self.cleanup())
 def test_already_dead_target_not_rekilled(self):
  self.q.obs['state']['nearby']['entities'][0]['alive']=False;self.assert_no_dispatch(lambda:self.cleanup())
 def test_target_health_zero_not_rekilled(self):
  self.q.obs['state']['nearby']['entities'][0]['health']=0;self.assert_no_dispatch(lambda:self.cleanup())
 def test_effect_player_movement_refused(self):
  self.q.observation_mutator=lambda x:x['state']['player'].update(x=2.) if self.q.mutations else None
  with self.assertRaises(SafetyHalt):self.cleanup()
  self.assertFalse((self.case/('cleanup-'+self.first+'.effect.json')).exists())
 def test_effect_radius_change_refused(self):
  self.q.observation_mutator=lambda x:x['state']['nearby'].update(radius=9.) if self.q.mutations else None
  with self.assertRaises(SafetyHalt):self.cleanup()
 def test_native_escape_real_screen_shape(self):
  r=self.p.pause_once('explicit-pause-auth');self.assertTrue(r['effect_confirmed']);self.assertEqual(self.q.mutations,[{'op':'direct','endpoint':'raw-key','body':{'key':'key.keyboard.escape','action':'click'}}])
 def test_already_paused_never_toggles(self):
  self.q.obs['state'].update(paused=True,screen_open=True);self.q.obs['screen']={'open':True,'class':pts.PAUSE_SCREEN}
  r=self.p.pause_once('explicit-pause-auth');self.assertFalse(r['dispatched']);self.assertEqual(self.q.mutations,[])
 def test_non_pause_screen_refused(self):
  self.q.obs['state'].update(paused=True,screen_open=True);self.q.obs['screen']={'open':True,'class':'net.minecraft.client.gui.screens.ChatScreen'}
  self.assert_no_dispatch(lambda:self.p.pause_once('explicit-pause-auth'))
 def test_external_escape_evidence_never_release_or_success(self):
  r=self.p.record_external_escape({'operator_executed':True,'method':'cua_escape','evidence_ref':'screen-frame','authorization_ref':'explicit-rescue'})
  self.assertIs(r['native_release_proven'],False);self.assertIs(r['native_outcome_proven'],False);self.assertEqual(self.q.mutations,[])
 def test_native_escape_cannot_masquerade_as_cua(self):
  self.assert_no_dispatch(lambda:self.p.record_external_escape({'operator_executed':True,'method':'raw_key_escape','evidence_ref':'native-receipt','authorization_ref':'auth'}))
 def test_external_escape_does_not_clear_stop(self):
  path=self.case/'SAFETY-STOP.json';path.write_text('{"reason":"original"}')
  self.p.record_external_escape({'operator_executed':True,'method':'cua_escape','evidence_ref':'screen-frame','authorization_ref':'explicit-rescue'})
  self.assertEqual(path.read_text(),'{"reason":"original"}');self.assert_no_dispatch(lambda:self.cleanup())

 def test_corrupt_first_effect_blocks_second_uuid(self):
  self.cleanup();(self.case/('cleanup-'+self.first+'.effect.json')).write_text('{broken')
  self.assert_no_dispatch(lambda:self.cleanup(self.second))
 def test_corrupt_first_effect_blocks_pause(self):
  self.cleanup();(self.case/('cleanup-'+self.first+'.effect.json')).write_text('{broken')
  self.assert_no_dispatch(lambda:self.p.pause_once('explicit-pause'))
 def test_corrupt_first_receipt_blocks_second_uuid(self):
  self.cleanup();(self.case/('cleanup-'+self.first+'.receipt.json')).write_text('{broken')
  self.assert_no_dispatch(lambda:self.cleanup(self.second))
 def test_deleted_first_intent_with_effect_never_replays_uuid(self):
  self.cleanup();intent=self.case/('cleanup-'+self.first+'.intent.json');intent.unlink();Path(str(intent)+'.sha256').unlink()
  entities=[dict(e,alive=True,health=20.) for e in ENTITIES];self.q.obs['state']['nearby'].update(entities=entities,total=2,returned=2)
  self.assert_no_dispatch(lambda:self.cleanup())

if __name__=='__main__':unittest.main(verbosity=2)
