import copy,json,unittest,uuid
from pathlib import Path
from receipt_binding import Binding,resolve,summarize,release_observed,CONTRACT
R='11111111-1111-4111-8111-111111111111';S='22222222-2222-4222-8222-222222222222';W='33333333-3333-4333-8333-333333333333';P='44444444-4444-4444-8444-444444444444'
def binding(kind='combat_entity'):return Binding('request-1',R,S,W,P,kind)
def native(b,status='succeeded',reason=None,attacks=4):
 return {'action_schema_version':1,'action_id':b.expected_action_id,'action_session':S,'action':b.action_kind,'status':status,'reason':reason or ('target_dead_observed' if status=='succeeded' else 'deadline_exceeded' if status=='failed' else 'inputs_released' if status=='cancelled' else 'running'),'ticks':12,'result':{'world_generation':W,'input_release_confirmed':True,'combat':{'attack_dispatches':attacks,'target_dead_observed':status=='succeeded','player_health_lost_observed':0}}}
def observation(b,a=None):
 return {'state':{'world':{'world_generation':W,'navigation_guard':{'epoch':0,'rebind_ready':True}},'player':{'uuid':P,'x':0.,'y':64.,'z':0.,'health':20.,'yaw':0.,'pitch':0.,'using_item':False,'sprinting':False},'client_action':{'action_session':S},'screen_open':False,'paused':False},'action':a or {**native(b),'action_id':'previous-action','result':{'world_generation':W,'combat':{'attack_dispatches':99,'target_dead_observed':True}}},'status':{'held_mappings':[],'mouse':{'held_world_buttons':[]}}}
def receipt(b,a=None,status='succeeded'):
 r={'request_id':b.request_id,'session_id':R,'status':status,'finished_at':100.}
 if a is not None:
  if status=='succeeded':r['result']={'action':a}
  else:r['action']=a;r['reason']=a.get('reason')
 return r
def rejection(b):return {**receipt(b,status='failed'),'reason':'unsupported_passenger_dimensions','action_id':None,'action':None,'resolved_action':None,'cancellation':None,'task_completed':False,'postcondition_observed':False,'action_step':1,'original_error':'unsupported_passenger_dimensions'}
def proof(kind):return {'kind':kind,'request_id':'interrupt-1','response':{'request_id':'interrupt-1','session_id':R,'status':'succeeded','reason':'direct_input_dispatched','result':{'ok':True,'released':True}}}
class ReceiptTests(unittest.TestCase):
 def setUp(self):self.b=binding();self.before=observation(self.b);self.action=native(self.b);self.after=observation(self.b,self.action)
 def check_empty(self,o):
  s=summarize(self.b,o,self.before);self.assertFalse(s['task_success']);self.assertIsNone(s['action_id']);self.assertIsNone(s['attack_dispatches']);self.assertIsNone(s['target_dead_observed'])
 def test_uuid5_is_expected_not_admission(self):self.assertEqual(self.b.expected_action_id,uuid.uuid5(uuid.UUID(R),'request-1:1').hex)
 def test_success_exact_request_action(self):
  o=resolve(self.b,receipt(self.b,self.action),before=self.before,after=self.after);s=summarize(self.b,o,self.after);self.assertTrue(s['task_success']);self.assertEqual(s['attack_dispatches'],4)
 def test_explicit_null_rejection_never_borrows_old_success(self):
  o=resolve(self.b,rejection(self.b),before=self.before,after=self.before);self.assertEqual(o['kind'],'admission_rejected');self.assertFalse(o['native_admission_confirmed']);self.check_empty(o)
 def test_null_incomplete_receipt_unknown(self):
  r=rejection(self.b);del r['action_step'];o=resolve(self.b,r,after=self.before);self.assertTrue(o['needs_reconciliation']);self.check_empty(o)
 def test_null_conflicts_with_bound_native(self):
  o=resolve(self.b,rejection(self.b),after=self.after);self.assertEqual(o['kind'],'receipt_conflict');self.check_empty(o)
 def test_null_conflicts_with_candidate(self):
  r=rejection(self.b);r['action']=self.action;o=resolve(self.b,r,after=self.after);self.assertEqual(o['kind'],'receipt_conflict');self.check_empty(o)
 def test_null_rejection_conflicts_with_running_even_after_old_terminal(self):
  o=resolve(self.b,rejection(self.b),after=self.before,running_evidence=[native(self.b,'running')]);self.assertEqual(o['kind'],'receipt_conflict');self.check_empty(o)
 def test_pre_admission_rejection_conflicts_with_running(self):
  r={**receipt(self.b,status='failed'),'reason':'action_world_changed'};o=resolve(self.b,r,after=self.before,running_evidence=[native(self.b,'running')]);self.assertEqual(o['kind'],'receipt_conflict');self.check_empty(o)
 def test_pre_admission_rejection_conflicts_with_final(self):
  r={**receipt(self.b,status='failed'),'reason':'action_session_changed'};o=resolve(self.b,r,after=self.after);self.assertEqual(o['kind'],'receipt_conflict');self.check_empty(o)
 def test_schema_boolean_not_integer_one(self):
  a=copy.deepcopy(self.action);a['action_schema_version']=True;o=resolve(self.b,receipt(self.b,a),after=self.after);self.assertEqual(o['kind'],'identity_mismatch');self.check_empty(o)
 def test_old_terminal_in_receipt_rejected(self):
  r=receipt(self.b,self.before['action']);o=resolve(self.b,r,after=self.after);self.assertEqual(o['kind'],'identity_mismatch');self.check_empty(o)
 def test_unknown_post_with_old_after(self):
  r={**rejection(self.b),'status':'uncertain'};o=resolve(self.b,r,after=self.before);self.assertEqual(o['kind'],'unknown_post_outcome');self.check_empty(o)
 def test_unknown_even_with_exact_resolved_success(self):
  r={**receipt(self.b,status='uncertain'),'resolved_action':self.action};o=resolve(self.b,r,after=self.after);self.assertEqual(o['kind'],'unknown_post_outcome');self.check_empty(o)
 def test_unknown_post_flag_has_precedence_over_null(self):
  r={**rejection(self.b),'post_uncertain':True};o=resolve(self.b,r,after=self.before);self.assertEqual(o['kind'],'unknown_post_outcome');self.check_empty(o)
 def test_pending_is_observer_timeout_not_native_deadline(self):
  o=resolve(self.b,{'request_id':self.b.request_id,'status':'pending','reason':'wait_timeout_not_action_failure'},after=self.after);self.assertEqual(o['kind'],'observer_wait_timeout');self.check_empty(o)
 def test_native_deadline_is_bound_failure(self):
  a=native(self.b,'failed','deadline_exceeded');o=resolve(self.b,receipt(self.b,a,'failed'),after=observation(self.b,a));self.assertEqual(o['kind'],'bound_terminal');self.assertEqual(o['native_action']['reason'],'deadline_exceeded');self.assertFalse(o['task_success'])
 def test_receipt_wrong_request(self):
  r=receipt(self.b,self.action);r['request_id']='other';o=resolve(self.b,r,after=self.after);self.assertEqual(o['kind'],'identity_mismatch');self.check_empty(o)
 def test_receipt_wrong_session(self):
  r=receipt(self.b,self.action);r['session_id']=S;o=resolve(self.b,r,after=self.after);self.assertEqual(o['kind'],'identity_mismatch');self.check_empty(o)
 def test_pending_supplied_wrong_session(self):
  o=resolve(self.b,{'request_id':self.b.request_id,'status':'pending','session_id':S});self.assertEqual(o['kind'],'identity_mismatch')
 def test_explicit_wrong_native_id(self):
  r={**receipt(self.b,self.action),'action_id':'old'};o=resolve(self.b,r,after=self.after);self.assertEqual(o['kind'],'identity_mismatch');self.check_empty(o)
 def test_conflicting_terminals_fail_closed(self):
  r=receipt(self.b,self.action);r['resolved_action']=native(self.b,'cancelled');o=resolve(self.b,r,after=self.after);self.assertEqual(o['kind'],'receipt_conflict');self.check_empty(o)
 def test_conflicting_same_id_terminal_counts_fail_closed(self):
  r=receipt(self.b,self.action);r['resolved_action']=native(self.b,attacks=99);o=resolve(self.b,r,after=self.after);self.assertEqual(o['kind'],'receipt_conflict');self.check_empty(o)
 def test_same_id_final_statistics_contradiction_fail_closed(self):
  o=resolve(self.b,receipt(self.b,self.action),after=observation(self.b,native(self.b,attacks=99)));self.assertEqual(o['kind'],'receipt_conflict');self.check_empty(o)
 def test_same_id_final_ticks_contradiction_fail_closed(self):
  a=copy.deepcopy(self.action);a['ticks']+=1;o=resolve(self.b,receipt(self.b,self.action),after=observation(self.b,a));self.assertEqual(o['kind'],'receipt_conflict');self.check_empty(o)
 def test_same_id_wrong_world_after(self):
  a=copy.deepcopy(self.action);a['result']['world_generation']=P;o=resolve(self.b,receipt(self.b,self.action),after=observation(self.b,a));self.assertEqual(o['kind'],'identity_mismatch');self.check_empty(o)
 def test_old_after_not_borrowed_even_valid_receipt(self):
  o=resolve(self.b,receipt(self.b,self.action),after=self.before);self.assertEqual(o['kind'],'identity_mismatch');self.check_empty(o)
 def test_running_only_receipt_not_completed(self):
  a=native(self.b,'running');o=resolve(self.b,receipt(self.b,a),after=observation(self.b,a));self.assertEqual(o['kind'],'nonterminal_receipt');self.check_empty(o)
 def test_outer_success_without_action_not_completed(self):
  o=resolve(self.b,receipt(self.b),after=self.after);self.assertTrue(o['needs_reconciliation']);self.check_empty(o)
 def test_preexisting_expected_id_no_replay(self):
  o=resolve(self.b,receipt(self.b,self.action),before=self.after,after=self.after);self.assertEqual(o['kind'],'identity_mismatch');self.check_empty(o)
 def test_after_context_player_mismatch(self):
  a=copy.deepcopy(self.after);a['state']['player']['uuid']=W;o=resolve(self.b,receipt(self.b,self.action),after=a);self.assertEqual(o['kind'],'identity_mismatch');self.check_empty(o)
 def test_after_context_world_mismatch(self):
  a=copy.deepcopy(self.after);a['state']['world']['world_generation']=P;o=resolve(self.b,receipt(self.b,self.action),after=a);self.assertEqual(o['kind'],'identity_mismatch');self.check_empty(o)
 def test_observation_gap_does_not_make_release_success(self):
  a=copy.deepcopy(self.after);a['status']['held_mappings']=['key.up'];o=resolve(self.b,receipt(self.b,self.action),after=a);s=summarize(self.b,o,a);self.assertFalse(s['task_success']);self.assertTrue(s['needs_reconciliation'])
 def test_cancel_closed_by_running_and_interrupt_and_terminal(self):
  a=native(self.b,'cancelled');r={**receipt(self.b,status='cancelled'),'reason':'cancel_requested','mod_cancel_confirmed':False};o=resolve(self.b,r,after=observation(self.b,a),running_evidence=[native(self.b,'running')],interrupt_proof=proof('cancel'));self.assertEqual(o['kind'],'bound_terminal');self.assertFalse(o['task_success'])
 def test_direct_closed_by_running_and_interrupt_and_terminal(self):
  a=native(self.b,'cancelled','direct_takeover');r={**receipt(self.b,status='cancelled'),'reason':'direct_takeover','mod_cancel_confirmed':False};o=resolve(self.b,r,after=observation(self.b,a),running_evidence=[native(self.b,'running')],interrupt_proof=proof('direct'));self.assertEqual(o['kind'],'bound_terminal')
 def test_cancel_without_running_not_attributed(self):
  a=native(self.b,'cancelled');r={**receipt(self.b,status='cancelled'),'reason':'cancel_requested'};o=resolve(self.b,r,after=observation(self.b,a),interrupt_proof=proof('cancel'));self.assertEqual(o['kind'],'unattributed_interrupt');self.check_empty(o)
 def test_cancel_without_interrupt_proof_not_attributed(self):
  a=native(self.b,'cancelled');r={**receipt(self.b,status='cancelled'),'reason':'cancel_requested'};o=resolve(self.b,r,after=observation(self.b,a),running_evidence=[native(self.b,'running')]);self.assertEqual(o['kind'],'unattributed_interrupt');self.check_empty(o)
 def test_cancel_old_running_cannot_be_used(self):
  a=native(self.b,'cancelled');r={**receipt(self.b,status='cancelled'),'reason':'cancel_requested'};old=native(self.b,'running');old['action_id']='old';o=resolve(self.b,r,after=observation(self.b,a),running_evidence=[old],interrupt_proof=proof('cancel'));self.assertEqual(o['kind'],'unattributed_interrupt');self.check_empty(o)
 def test_native_success_request_failed_is_not_overall_success(self):
  r=receipt(self.b,self.action,'failed');o=resolve(self.b,r,after=self.after);self.assertEqual(o['kind'],'request_native_status_conflict');self.check_empty(o)
 def test_missing_after_is_unverified(self):
  o=resolve(self.b,receipt(self.b,self.action));self.assertEqual(o['kind'],'postcondition_unverified');self.check_empty(o)
 def test_unrelated_sample_has_no_action(self):self.assertEqual(self.b.classify_observation(self.before)['relation'],'unrelated_retained_action');self.assertIsNone(self.b.classify_observation(self.before)['action'])
 def test_bound_running_sample_recognized(self):self.assertEqual(self.b.classify_observation(observation(self.b,native(self.b,'running')))['relation'],'bound')
 def test_unknown_current_status_not_release_proof(self):
  x=copy.deepcopy(self.before);x['action']['status']=None;self.assertFalse(release_observed(self.b,x))
 def test_no_mouse_observation_not_release_proof(self):
  x=copy.deepcopy(self.before);del x['status']['mouse'];self.assertFalse(release_observed(self.b,x))

def invalid_candidate_test(source,field):
 def test(self):
  a=copy.deepcopy(self.action)
  if field=='world':a['result']['world_generation']=P
  else:a[field]={'action_id':'old','action_session':W,'action':'boat_drive','action_schema_version':9}[field]
  r=receipt(self.b,status='failed');r['reason']='test'
  if source=='result.action':r['result']={'action':a}
  else:r[source]=a
  o=resolve(self.b,r,after=self.after);self.assertEqual(o['kind'],'identity_mismatch');self.check_empty(o)
 return test
for source in ['result.action','action','resolved_action','cancellation']:
 for field in ['action_id','action_session','action','world','action_schema_version']:
  setattr(ReceiptTests,'test_bad_'+source.replace('.','_')+'_'+field,invalid_candidate_test(source,field))
if __name__=='__main__':unittest.main()
