"""Independent transition, uncertain-admission, crash and race cases. 0 live."""
import copy,hashlib,json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(Path(__file__).resolve().parent)]
sys.dont_write_bytecode=True
from independent_safety_fixture import *
from post_trial_safety import PostTrialSafety,SafetyHalt

NEW_ENTITIES=[dict(e,uuid='c7777777-7777-4777-8777-777777777777' if i==0 else 'c8888888-8888-4888-8888-888888888888',entity_id=303+i) for i,e in enumerate(ENTITIES)]
def proof(entities):return {'entities':[{'uuid':e['uuid'],'no_ai':True,'evidence_ref':'explicit-fresh-noai'} for e in entities]}
class TransitionTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.p,self.q,self.o,self.report=configured(self.tmp.name,resolved=False);self.case=self.p.root/'case-000001'
 def resolve(self):
  (self.o.out/'trial1.json').write_text(json.dumps(self.report));return self.p.record_trial(self.report)
 def complete(self):
  self.resolve()
  for e in ENTITIES:self.p.cleanup_uuid(e['uuid'],'cleanup-exact-pair')
  self.p.pause_once('pause-after-pair-cleanup')
 def next(self,oldauth='explicit-next-case-auth',entities=None,caseid='case2'):
  entities=copy.deepcopy(NEW_ENTITIES if entities is None else entities)
  qobs=copy.deepcopy(self.q.obs)
  qobs['state']['nearby'].update(entities=[dict(e,alive=True,health=20.) for e in entities],total=2,returned=2)
  self.q.obs=qobs
  return self.p.register_noai_case(caseid,entities,copy.deepcopy(qobs),evidence_ref='fresh-new-case-observation',noai_proof=proof(entities),authorization_ref='new-case-trial-auth',previous_case_authorization_ref=oldauth)
 def no_cleanup(self):
  before=len(self.q.mutations)
  with self.assertRaises((SafetyHalt,ValueError,KeyError,TypeError)):self.p.cleanup_uuid(ENTITIES[0]['uuid'],'cleanup-exact-pair')
  self.assertEqual(before,len(self.q.mutations))
 def test_unknown_envelope_blocks_cleanup(self):
  self.report['response']['status']='uncertain'
  with self.assertRaises(SafetyHalt):self.resolve()
  self.no_cleanup()
 def test_pending_envelope_blocks_cleanup(self):
  self.report['response']['status']='pending'
  with self.assertRaises(SafetyHalt):self.resolve()
  self.no_cleanup()
 def test_missing_terminal_blocks_cleanup(self):
  self.report['response'].pop('result')
  with self.assertRaises(SafetyHalt):self.resolve()
  self.no_cleanup()
 def test_mismatched_native_blocks_cleanup(self):
  self.report['response']['result']['action']['action_id']='foreign'
  with self.assertRaises(SafetyHalt):self.resolve()
  self.no_cleanup()
 def test_missing_after_blocks_cleanup(self):
  self.report['after']=None
  with self.assertRaises(SafetyHalt):self.resolve()
  self.no_cleanup()
 def test_unreleased_terminal_blocks_cleanup(self):
  self.report['after']['status']['held_mappings']=['key.up']
  with self.assertRaises(SafetyHalt):self.resolve()
  self.no_cleanup()
 def test_known_null_admission_allows_exact_cleanup(self):
  self.report['response']=rejection(self.q.b);self.report['after']=copy.deepcopy(self.report['before']);self.q.obs=copy.deepcopy(self.report['after'])
  r=self.resolve();self.assertTrue(r['narrow_safety_eligible']);self.p.cleanup_uuid(ENTITIES[0]['uuid'],'cleanup-exact-pair');self.assertEqual(len(self.q.mutations),1)
 def test_null_admission_same_action_conflict_blocks_cleanup(self):
  self.report['response']=rejection(self.q.b)
  with self.assertRaises(SafetyHalt):self.resolve()
  self.no_cleanup()
 def test_native_failed_terminal_allows_safety_only(self):
  a=native(self.q.b,'failed');self.report['response']=receipt(self.q.b,a,status='failed');self.report['after']=full_observation(self.q.b,a);self.q.obs=copy.deepcopy(self.report['after'])
  r=self.resolve();self.assertTrue(r['narrow_safety_eligible']);self.assertIs(r['controlled_trial_accepted'],False)
 def test_process_death_after_reservation_blocks_second_trial(self):
  p=PostTrialSafety(self.o,self.p.root)
  with self.assertRaises(SafetyHalt):p.reserve_trial(self.q.b,command_body(),'repeat')
 def test_process_death_after_dispatch_before_resolution_blocks_cleanup(self):self.no_cleanup()
 def test_write_intent_failure_prevents_dispatch(self):
  self.resolve();original=pts._write
  def failing(path,value):
   if str(path).endswith('cleanup-'+ENTITIES[0]['uuid']+'.intent.json'):raise OSError('disk-full-before-intent')
   return original(path,value)
  with patch.object(pts,'_write',side_effect=failing):
   with self.assertRaises(SafetyHalt):self.p.cleanup_uuid(ENTITIES[0]['uuid'],'cleanup-exact-pair')
  self.assertEqual(self.q.mutations,[])
 def test_receipt_write_failure_preserves_consumed_intent(self):
  self.resolve();original=pts._write
  def failing(path,value):
   if str(path).endswith('cleanup-'+ENTITIES[0]['uuid']+'.receipt.json'):raise OSError('disk-full-after-dispatch')
   return original(path,value)
  with patch.object(pts,'_write',side_effect=failing):
   with self.assertRaises(SafetyHalt):self.p.cleanup_uuid(ENTITIES[0]['uuid'],'cleanup-exact-pair')
  self.assertEqual(len(self.q.mutations),1);self.no_cleanup()
 def test_effect_write_failure_preserves_consumed_intent(self):
  self.resolve();original=pts._write
  def failing(path,value):
   if str(path).endswith('cleanup-'+ENTITIES[0]['uuid']+'.effect.json'):raise OSError('disk-full-after-effect-read')
   return original(path,value)
  with patch.object(pts,'_write',side_effect=failing):
   with self.assertRaises(SafetyHalt):self.p.cleanup_uuid(ENTITIES[0]['uuid'],'cleanup-exact-pair')
  self.assertEqual(len(self.q.mutations),1);self.no_cleanup()
 def test_dead_effect_explicitly_confirmed(self):
  self.resolve();self.q.mutation_mode='dead_effect'
  def effect(x):
   if self.q.mutations:x['state']['nearby']['entities'][0]['alive']=False
  self.q.observation_mutator=effect
  r=self.p.cleanup_uuid(ENTITIES[0]['uuid'],'cleanup-exact-pair');self.assertEqual(r['effect'],'exact_uuid_dead_observed')
 def test_zero_health_effect_explicitly_confirmed(self):
  self.resolve();self.q.mutation_mode='health0_effect'
  def effect(x):
   if self.q.mutations:x['state']['nearby']['entities'][0]['health']=0
  self.q.observation_mutator=effect
  r=self.p.cleanup_uuid(ENTITIES[0]['uuid'],'cleanup-exact-pair');self.assertEqual(r['effect'],'exact_uuid_dead_observed')
 def test_posttrial_health_decrease_latches_without_promoting_cleanup(self):
  self.resolve();self.q.obs['state']['player']['health']=19.99
  r=self.p.cleanup_uuid(ENTITIES[0]['uuid'],'cleanup-exact-pair')
  self.assertTrue((self.case/'POST-HEALTH-STOPPED-SAFETY.json').exists());self.assertIs(r['controlled_trial_accepted'],False)
 def test_next_case_without_previous_complete_refused(self):
  self.resolve()
  with self.assertRaises(SafetyHalt):self.next()
 def test_next_case_without_new_authorization_refused(self):
  self.complete()
  with self.assertRaises(SafetyHalt):self.next(oldauth=None)
 def test_next_case_reused_old_authorization_refused(self):
  self.complete()
  with self.assertRaises(SafetyHalt):self.next(oldauth='explicit-synthetic-auth')
 def test_next_case_current_pause_lost_refused(self):
  self.complete();self.q.obs['state'].update(paused=False,screen_open=False);self.q.obs['screen']={'open':False}
  with self.assertRaises(SafetyHalt):self.next()
 def test_next_case_explicit_new_authorization_allowed(self):
  self.complete();record=self.next();self.assertEqual(record['case_id'],'case2');self.assertIs(record['ordinary_mutation_permission'],False);self.assertIs(record['controlled_trial_accepted'],False)
 def test_next_case_does_not_clear_prior_markers(self):
  self.complete();snap={x.name:x.read_bytes() for x in self.case.glob('*.json')};self.next()
  for name,data in snap.items():self.assertEqual((self.case/name).read_bytes(),data)
 def test_next_case_needs_full_health_again(self):
  self.complete();self.q.obs['state']['player']['health']=19.9
  with self.assertRaises(SafetyHalt):self.next()
 def test_registration_digest_missing_refused(self):
  self.resolve();Path(str(self.case/'registration.json')+'.sha256').unlink();self.no_cleanup()
 def test_registration_tamper_with_recomputed_digest_still_refused(self):
  self.resolve();path=self.case/'registration.json';value=json.loads(path.read_text());value['entities'][0]['uuid']='c7777777-7777-4777-8777-777777777777';path.write_text(json.dumps(value));Path(str(path)+'.sha256').write_text(hashlib.sha256(path.read_bytes()).hexdigest()+'\n');self.no_cleanup()
 def test_resolution_tamper_with_recomputed_digest_still_refused(self):
  self.resolve();path=self.case/'trial-resolution.json';value=json.loads(path.read_text());value['resolved_outcome']['needs_reconciliation']=True;path.write_text(json.dumps(value));Path(str(path)+'.sha256').write_text(hashlib.sha256(path.read_bytes()).hexdigest()+'\n');self.no_cleanup()
 def test_cancel_already_terminal_at_authorization_refused(self):
  self.q.obs=full_observation(self.q.b,native(self.q.b,'running'));self.q.result=lambda _:receipt(self.q.b,native(self.q.b))
  with self.assertRaises(SafetyHalt):self.p.authorize_running_cancel(self.q.obs,reason='health-drop',authorization_ref='explicit-synthetic-auth')
 def test_cancel_terminal_after_authorization_before_dispatch_refused(self):
  self.q.obs=full_observation(self.q.b,native(self.q.b,'running'))
  rid=self.p.authorize_running_cancel(self.q.obs,reason='health-drop',authorization_ref='explicit-synthetic-auth')
  self.q.result=lambda _:receipt(self.q.b,native(self.q.b));self.q.obs=full_observation(self.q.b,native(self.q.b))
  with self.assertRaises(SafetyHalt):self.p.claim_trial_dispatch(rid,{'op':'cancel'},owned_request=self.q.b.request_id)
 def test_cancel_cannot_be_other_command(self):
  self.q.obs=full_observation(self.q.b,native(self.q.b,'running'))
  rid=self.p.authorize_running_cancel(self.q.obs,reason='health-drop',authorization_ref='explicit-synthetic-auth')
  with self.assertRaises(SafetyHalt):self.p.claim_trial_dispatch(rid,{'op':'direct','endpoint':'command','body':{'command':'kill @e'}},owned_request=self.q.b.request_id)

 def test_renamed_unresolved_case_never_resets_budget(self):
  self.case.rename(self.p.root/'case-000001-interrupted')
  with self.assertRaises(SafetyHalt):self.p.assert_mutation_allowed(request_id='new',body={'op':'direct','endpoint':'command','body':{'command':'say blocked'}})
 def test_deleted_unresolved_case_never_resets_budget(self):
  import shutil
  shutil.rmtree(self.case)
  with self.assertRaises(SafetyHalt):self.p.assert_mutation_allowed(request_id='new',body={'op':'direct','endpoint':'command','body':{'command':'say blocked'}})
 def test_case_symlink_replacement_rejected(self):
  self.resolve();real=self.p.root/'moved-case';self.case.rename(real);self.case.symlink_to(real,target_is_directory=True)
  self.no_cleanup()

 def test_deleted_whole_ledger_never_resets_budget(self):
  import shutil
  shutil.rmtree(self.p.root)
  with self.assertRaises(SafetyHalt):self.p.assert_mutation_allowed(request_id='new',body={'op':'cancel'})
 def test_renamed_whole_ledger_never_resets_budget(self):
  self.p.root.rename(self.p.root.with_name('renamed-ledger'))
  with self.assertRaises(SafetyHalt):self.p.assert_mutation_allowed(request_id='new',body={'op':'cancel'})
 def test_root_anchor_removed_refused(self):
  next(self.p.root.glob('ledger-case-*.anchor.json')).unlink()
  with self.assertRaises(SafetyHalt):self.p.assert_mutation_allowed(request_id='new',body={'op':'cancel'})
 def test_sibling_everused_removed_refused(self):
  self.p.ever_used.unlink()
  with self.assertRaises(SafetyHalt):self.p.assert_mutation_allowed(request_id='new',body={'op':'cancel'})

 def test_root_symlink_to_fresh_empty_target_refused(self):
  root=self.p.root;root.rename(root.with_name('saved-ledger'));fresh=root.with_name('fresh-ledger');fresh.mkdir();root.symlink_to(fresh,target_is_directory=True)
  with self.assertRaises(SafetyHalt):PostTrialSafety(self.o,root).assert_mutation_allowed(request_id='new',body={'op':'cancel'})
 def test_ancestor_symlink_alias_refused(self):
  alias=Path(self.tmp.name)/'parent-alias';alias.symlink_to(self.p.root.parent,target_is_directory=True)
  with self.assertRaises(SafetyHalt):PostTrialSafety(self.o,alias/self.p.root.name).assert_mutation_allowed(request_id='new',body={'op':'cancel'})

if __name__=='__main__':unittest.main(verbosity=2)
