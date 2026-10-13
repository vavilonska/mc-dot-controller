"""Append-only restart transitions on temporary ledgers and fake queues only."""
import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import test_post_trial_safety as support
import test_operator_closeout as active_closeout
from encounter_binding import EncounterBinding
from encounter_contract import MODE, THREE_MODE
from post_trial_safety import PostTrialSafety, SafetyHalt, _load, _write
from receipt_binding import Binding
from session_rollover import read_chain, closed_case

ORIGINAL_SAMPLE=support.sample

def dimension_sample(*args,**kwargs):
    result=ORIGINAL_SAMPLE(*args,**kwargs);result['state']['world']['dimension']='minecraft:overworld';return result

def rewrite(path,value):
    raw=(json.dumps(value,sort_keys=True,separators=(',',':'))+'\n').encode()
    path.write_bytes(raw);Path(str(path)+'.sha256').write_text(hashlib.sha256(raw).hexdigest()+'\n')

class SessionRolloverTests(unittest.TestCase):
    def setUp(self):
        self.samples=patch.object(support,'sample',dimension_sample);self.samples.start();self.addCleanup(self.samples.stop)
        self.h=active_closeout.OperatorCloseoutTests(methodName='runTest');self.h.setUp();self.addCleanup(self.h.doCleanups)
        self.h.close();self.old=self.h.s;self.root=self.old.root
        self.baseline={p:p.read_bytes() for p in self.h.h.base.rglob('*') if p.is_file()}
        for name in ('inbox','working','results'):(self.root.parent/name).mkdir()
        self.new=self.new_safety()
    def new_safety(self,n=1):
        def u(k):return '20000000-0000-4000-8000-%012d'%(n*10+k)
        b=Binding('new-session-probe',u(1),u(2),u(3),self.old.identity['player_uuid'],'combat_entity')
        q=support.FakeQueue(self.h.b);q.root=self.root.parent;q.binding=b
        q.current=copy.deepcopy(self.h.q.current)
        q.current['state']['world']['world_generation']=b.world_generation
        q.current['state']['client_action']['action_session']=b.action_session
        q.current['action']={'action_schema_version':1,'action_session':b.action_session,'status':'idle','action_id':None,'ticks':0,'result':{}}
        q.session_data.update(session_id=b.resident_session,bridge_identity={'action_session':b.action_session},reason=None)
        o=SimpleNamespace(c=q,out=self.root.parent/('new-output-'+str(n)),resident=b.resident_session,
            session=b.action_session,world=b.world_generation,player=b.player_uuid)
        return PostTrialSafety(o,self.root)
    def roll(self,**kw):
        return self.new.rollover_session(**dict({'authorization_ref':'restart-approval-1','same_save_evidence_ref':'operator-savequit-select-same-test-world'},**kw))
    def assert_old_unchanged(self):
        for p,data in self.baseline.items():self.assertEqual(p.read_bytes(),data,str(p))
    def no_rollover(self):
        self.assertFalse(list(self.root.glob('session-*.rollover.json')))
    def register_next(self,mode=MODE,request_id='new-independent-action'):
        count=3 if mode==THREE_MODE else 2
        es=[{'entity_id':20+i,'uuid':'30000000-0000-4000-8000-%012d'%i,'type':'minecraft:zombie','x':i+1,'y':64,'z':0} for i in range(count)]
        q=self.new.o.c
        nearby=q.current['state']['nearby'];values=nearby['entities']+[dict(e,alive=True,health=20) for e in es]
        nearby.update(entities=values,total=len(values),returned=len(values))
        self.new.register_active_case('new-three' if count==3 else 'new-two',es,copy.deepcopy(q.current),
            evidence_ref='fresh-new-case',active_ai_proof={'entities':[{'uuid':e['uuid'],'no_ai':False,'is_baby':False,'evidence_ref':'new-proof'} for e in es]},
            authorization_ref='independent-new-case-approval',pause_authorization_ref='new-pause-approval',
            previous_case_authorization_ref='independent-new-case-approval',encounter_mode=mode)
        req=self.h.b.encounter_request
        req.update(expected_action_session=self.new.o.session,expected_world_generation=self.new.o.world,
            expected_player_uuid=self.new.o.player,encounter_mode=mode,
            encounter_scope=[{k:e[k] for k in ('entity_id','uuid','type')} for e in es],
            target_uuid=es[0]['uuid'],target_entity_id=es[0]['entity_id'])
        b=EncounterBinding(request_id,self.new.o.resident,self.new.o.session,self.new.o.world,self.new.o.player,'combat_entity',encounter_request=req)
        return b
    def test_append_only_transition_has_explicit_operator_same_save_source(self):
        record=self.roll();self.assert_old_unchanged()
        self.assertEqual(record['from_identity'],self.old.identity);self.assertEqual(record['to_identity'],self.new.identity)
        self.assertEqual(record['same_save_proof_source'],'independent_operator_evidence_not_native_save_id')
        self.assertFalse(record['new_case_authorized']);self.assertFalse(record['ordinary_mutation_permission'])
        self.assertEqual(self.new.o.c.mutations(),[])
        self.assertEqual(read_chain(self.new)['identity'],self.new.identity)
    def test_new_identity_blocked_before_rollover_and_old_instance_invalid_after(self):
        with self.assertRaises(SafetyHalt):
            with self.new._locked():pass
        self.roll()
        with self.assertRaisesRegex(SafetyHalt,'context_changed'):
            with self.old._locked():pass
        with self.assertRaisesRegex(SafetyHalt,'old_session'):self.new._current()
        with self.assertRaises(SafetyHalt):self.new.cleanup_uuid(self.h.h.es[0]['uuid'],'anything')
        self.assertEqual(self.new.o.c.mutations(),[])
    def test_new_two_case_retains_global_ordinal_and_exact_session_link(self):
        self.roll();b=self.register_next()
        self.new.reserve_trial(b,{'op':'action',**b.encounter_request},'new-two')
        c=self.root/'case-000002';self.assertTrue(c.is_dir());reg=_load(c/'registration.json')
        self.assertEqual(reg['session_identity'],self.new.identity)
        self.assertEqual(reg['session_rollover_sha256'],read_chain(self.new)['sha256']);self.assert_old_unchanged()
    def test_new_three_case_uses_same_rollover_without_old_two_scope_expansion(self):
        self.roll();b=self.register_next(THREE_MODE)
        self.new.reserve_trial(b,{'op':'action',**b.encounter_request},'new-three')
        self.assertEqual(len(_load(self.root/'case-000002'/'registration.json')['entities']),3)
        self.assert_old_unchanged()
    def test_old_request_id_cannot_acquire_a_new_budget_in_new_session(self):
        self.roll();b=self.register_next(request_id=self.h.b.request_id)
        with self.assertRaisesRegex(SafetyHalt,'already_consumed'):
            self.new.reserve_trial(b,{'op':'action',**b.encounter_request},'reused')
        self.assertFalse((self.root/'case-000002'/'trial-reservation.json').exists())
    def test_old_case_and_closeout_authorization_cannot_authorize_rollover(self):
        for ref in ('synthetic-active-approval','operator-closeout-approval'):
            with self.assertRaisesRegex(SafetyHalt,'new_authorization'):self.roll(authorization_ref=ref)
        self.no_rollover()
    def test_rollover_authorization_does_not_authorize_new_case(self):
        self.roll()
        q=self.new.o.c
        with self.assertRaisesRegex(SafetyHalt,'new_authorization'):
            self.new.register_active_case('illegal',self.h.h.es,q.current,evidence_ref='x',
                active_ai_proof=self.h.a.proof,authorization_ref='restart-approval-1',pause_authorization_ref='new',
                previous_case_authorization_ref='restart-approval-1')
        self.assertFalse((self.root/'case-000002').exists())
    def test_repeat_same_identity_or_return_to_historical_identity_refuses(self):
        self.roll()
        with self.assertRaises(SafetyHalt):self.roll(authorization_ref='restart-again')
        other=self.new_safety(2);other.rollover_session(authorization_ref='restart-approval-2',same_save_evidence_ref='next-restart')
        self.assertEqual(read_chain(other)['ordinal'],2)
        with self.assertRaises(SafetyHalt):self.roll(authorization_ref='return-old-generation')
        self.assertEqual(len(list(self.root.glob('session-*.rollover.json'))),2)
    def test_missing_same_save_ref_foreign_player_or_dimension_refuses(self):
        with self.assertRaises(SafetyHalt):self.roll(same_save_evidence_ref='')
        self.new.identity['player_uuid']='99999999-0000-4000-8000-000000000099'
        with self.assertRaises(SafetyHalt):self.roll()
        self.new=self.new_safety();self.new.o.c.current['state']['world']['dimension']='minecraft:the_nether'
        with self.assertRaisesRegex(SafetyHalt,'dimension_changed'):self.roll()
        self.no_rollover()
    def test_current_native_unpaused_held_or_running_refuses(self):
        for kind in ('paused','held','running'):
            self.new=self.new_safety();q=self.new.o.c
            if kind=='paused':q.current['state']['paused']=False
            if kind=='held':q.current['status']['held_mappings']=['key.forward']
            if kind=='running':q.current['action']['status']='running'
            with self.assertRaises(SafetyHalt):self.roll()
        self.no_rollover()
    def test_unknown_or_pending_current_queue_is_not_empty_by_session_claim(self):
        for directory in ('inbox','working'):
            file=self.root.parent/directory/'unclaimed.json';file.write_text('{"op":"action"}')
            with self.assertRaisesRegex(SafetyHalt,'mailbox_not_empty'):self.roll()
            file.unlink()
        self.new.o.c.session_data['pending']=1
        with self.assertRaises(SafetyHalt):self.roll()
        self.no_rollover()
    def test_foreign_pending_appearing_during_own_read_refuses(self):
        q=self.new.o.c;original=q.wait
        def changed(rid,timeout):
            result=original(rid,timeout);(q.root/'inbox'/'foreign.json').write_text('{}');return result
        q.wait=changed
        with self.assertRaisesRegex(SafetyHalt,'mailbox_not_empty'):self.roll()
        self.no_rollover()
    def test_current_session_owner_change_after_observation_refuses(self):
        q=self.new.o.c;original=q.wait
        def changed(rid,timeout):
            result=original(rid,timeout);q.session_data['active_request_id']='foreign';return result
        q.wait=changed
        with self.assertRaises(SafetyHalt):self.roll()
        self.no_rollover()
    def test_unknown_old_resume_pause_or_mutation_intent_refuses(self):
        # An orphan mutation is rejected even when main action and closeout are known.
        _write(self.h.case/'other.intent.json',{'read_only':False,'request_id':'unresolved'})
        with self.assertRaisesRegex(SafetyHalt,'unresolved_mutation'):self.roll()
        self.no_rollover()
    def test_missing_old_closeout_or_any_partial_old_record_refuses(self):
        path=self.h.case/'operator-closeout.json';saved=path.read_bytes();path.unlink()
        with self.assertRaises(SafetyHalt):self.roll()
        path.write_bytes(saved)
        (self.h.case/'interrupted.json.sha256').write_text('partial')
        with self.assertRaises(SafetyHalt):self.roll()
        self.no_rollover()
    def test_open_registered_unsubmitted_case_cannot_rollover(self):
        self.roll();self.register_next();later=self.new_safety(2)
        with self.assertRaises(SafetyHalt):later.rollover_session(authorization_ref='restart-2',same_save_evidence_ref='same')
        self.assertEqual(len(list(self.root.glob('session-*.rollover.json'))),1)
    def test_deleted_modified_or_partial_rollover_chain_is_never_reset(self):
        self.roll();p=self.root/'session-000001.rollover.json';raw=p.read_bytes();p.unlink()
        with self.assertRaises(SafetyHalt):
            with self.new._locked():pass
        p.write_bytes(raw);value=_load(p);value['to_identity']['world_generation']=self.old.identity['world_generation'];rewrite(p,value)
        with self.assertRaises(SafetyHalt):
            with self.new._locked():pass
        self.assert_old_unchanged()
    def test_missing_old_case_anchor_is_not_hidden_by_session_link(self):
        self.roll();p=self.root/'ledger-case-000001.anchor.json';p.unlink()
        with self.assertRaises(SafetyHalt):
            with self.new._locked():pass
    def test_partial_rollover_write_leaves_detectable_anchor_and_old_session_blocked(self):
        import session_rollover
        original=session_rollover._write
        def fail_record(path,value):
            if path.name.endswith('.rollover.json'):raise OSError('synthetic-crash')
            original(path,value)
        with patch.object(session_rollover,'_write',fail_record):
            with self.assertRaises(OSError):self.roll()
        for s in (self.old,self.new):
            with self.assertRaises(SafetyHalt):
                with s._locked():pass
        self.assertTrue(list(self.root.parent.glob(self.root.name+'.session-*.anchor.json')))

    def add_closed_noai_tail(self, use_new=False):
        from fixtures_support import rejection
        b0=self.h.b;req=b0.encounter_request;req.pop('encounter_pause_on_terminal',None)
        for e in req['encounter_scope']:
            e['entity_id']+=40;e['uuid']='40000000-0000-4000-8000-%012d'%e['entity_id']
        req.update(target_entity_id=req['encounter_scope'][0]['entity_id'],target_uuid=req['encounter_scope'][0]['uuid'])
        ident=self.new.identity if use_new else self.old.identity
        req.update(expected_action_session=ident['action_session'],expected_world_generation=ident['world_generation'],expected_player_uuid=ident['player_uuid'])
        b=EncounterBinding('second-known-rejected-noai',ident['resident_session'],ident['action_session'],ident['world_generation'],ident['player_uuid'],'combat_entity',encounter_request=req)
        q=support.FakeQueue(b);q.current=copy.deepcopy(self.new.o.c.current if use_new else self.h.q.current)
        es=support.entities(b);nearby=q.current['state']['nearby'];entries=nearby['entities']+[dict(e,alive=True,health=20) for e in es]
        nearby.update(entities=entries,total=len(entries),returned=len(entries))
        o=SimpleNamespace(c=q,out=self.root.parent/'second-noai-output',resident=b.resident_session,session=b.action_session,world=b.world_generation,player=b.player_uuid)
        safety=PostTrialSafety(o,self.root)
        safety.register_noai_case('second-noai',es,copy.deepcopy(q.current),evidence_ref='second-noai-evidence',
            noai_proof={'entities':[{'uuid':e['uuid'],'no_ai':True,'evidence_ref':'noai-proof'} for e in es]},
            authorization_ref='second-noai-approval',previous_case_authorization_ref='second-noai-approval')
        command={'op':'action',**req};safety.reserve_trial(b,command,'noai')
        safety.claim_trial_dispatch(b.request_id,command)
        report={'name':'noai','request_id':b.request_id,'binding':b.wire(),'command':command,
                'before':copy.deepcopy(q.current),'after':copy.deepcopy(q.current),'samples':[],
                'response':rejection(b),'interrupt_proof':None}
        o.out.mkdir();(o.out/'noai.json').write_text(json.dumps(report));safety.record_trial(report)
        for e in es:safety.cleanup_uuid(e['uuid'],'second-noai-closeout')
        safety.pause_once('second-noai-closeout')
        return safety,b
    def test_known_not_admitted_noai_with_exact_cleanup_and_pause_can_rollover(self):
        self.add_closed_noai_tail();result=self.roll()
        self.assertEqual(result['through_case_ordinal'],2)
        self.assertEqual(result['closed_cases'][1]['closed']['kind'],'noai_exact_cleanup_and_pause')
        self.assertEqual(_load(self.root/'case-000002'/'trial-resolution.json')['resolved_outcome']['kind'],'admission_rejected')
        self.assert_old_unchanged()
    def test_every_old_case_is_checked_not_only_successfully_closed_tail(self):
        self.add_closed_noai_tail();(self.h.case/'operator-closeout.json').unlink()
        with self.assertRaises(SafetyHalt):self.roll()
        self.no_rollover()
    def test_unknown_mutation_effect_is_not_resolved_by_file_existence(self):
        _write(self.h.case/'unknown.intent.json',{'read_only':False,'request_id':'unknown'})
        _write(self.h.case/'unknown.effect.json',{'effect_confirmed':True})
        with self.assertRaisesRegex(SafetyHalt,'unrecognized_mutation'):self.roll()
        self.no_rollover()
    def test_bound_old_failed_terminal_is_preserved_in_rollover(self):
        # The synthetic native fixture can be succeeded; rollover never changes it.
        before=_load(self.h.case/'trial-resolution.json')['resolved_outcome']
        self.roll();after=_load(self.h.case/'trial-resolution.json')['resolved_outcome']
        self.assertEqual(after,before)

    def test_new_session_closed_case_can_precede_a_second_real_rollover(self):
        self.roll();s,b=self.add_closed_noai_tail(use_new=True)
        self.assertEqual(_load(self.root/'case-000002'/'registration.json')['session_identity'],self.new.identity)
        later=self.new_safety(2)
        result=later.rollover_session(authorization_ref='restart-approval-2',same_save_evidence_ref='second-savequit-same-world')
        self.assertEqual(result['ordinal'],2);self.assertEqual(result['through_case_ordinal'],2)
        self.assertEqual(read_chain(later)['identity'],later.identity);self.assert_old_unchanged()

    def test_current_resident_unknown_stop_never_counts_as_idle(self):
        for state,reason,missing in [('paused','gate_probe_other_or_unknown_result',False),('ready','unknown_outcome',False),('ready',None,True)]:
            self.new=self.new_safety();self.new.o.c.session_data.update(state=state,reason=reason)
            if missing:self.new.o.c.session_data.pop('reason')
            with self.assertRaisesRegex(SafetyHalt,'not_idle'):self.roll()
            self.no_rollover()

    def test_resume_cannot_borrow_known_success_from_different_request_or_session(self):
        from session_rollover import verify_active_auxiliaries
        record=_load(self.h.case/'trial-resolution.json')
        for key,value in [('request_id','some-other-request'),('session_id','foreign'),('status','uncertain')]:
            bad=copy.deepcopy(record);bad['original_report']['resume']['response'][key]=value
            with self.assertRaises(SafetyHalt):verify_active_auxiliaries(self.h.case,self.h.b,bad)
        bad=copy.deepcopy(record);bad['original_report']['resume']['command']['body']['action']='press'
        with self.assertRaises(SafetyHalt):verify_active_auxiliaries(self.h.case,self.h.b,bad)
    def test_native_pause_echo_must_equal_exact_original_terminal_hook(self):
        from session_rollover import verify_active_auxiliaries
        bad=_load(self.h.case/'trial-resolution.json')
        bad['original_report']['pause']['native_hook']['client_paused_observed']=True
        with self.assertRaisesRegex(SafetyHalt,'native_pause_mismatch'):
            verify_active_auxiliaries(self.h.case,self.h.b,bad)
    def test_fallback_pause_validates_exact_reserved_receipt_and_native_terminal(self):
        from session_rollover import verify_active_auxiliaries
        b=self.h.b;record=_load(self.h.case/'trial-resolution.json');pause=record['original_report']['pause']
        pause.pop('source',None);pause.pop('native_hook',None);pause.pop('fallback_skipped_prior_native_attempt',None)
        _write(self.h.case/'active-pause-dispatch.json',{'request_id':pause['request_id'],'command':pause['command'],'automatic_retry':False})
        native=copy.deepcopy(record['resolved_outcome']['native_action'])
        ack={'ok':True,'protocol':'mineclient-bridge','schema_version':2,'pause_schema_version':1,
            'action':'ensure_paused','pause_requested':True,'pause_screen_installed':True,'already_pause_screen':False,
            'client_paused_observed':False,'pause_effect_confirmed':False,'server_confirmed':False,
            'action_session':b.action_session,'world_generation':b.world_generation,'player_uuid':b.player_uuid,
            'expected_action_id':b.expected_action_id,'expected_action_present':True,'client_action':native,'input_release_confirmed':True}
        pause['response']={'request_id':pause['request_id'],'session_id':b.resident_session,'status':'succeeded','result':ack}
        verify_active_auxiliaries(self.h.case,b,record)
        for key,value in [('request_id','foreign'),('session_id','foreign'),('post_uncertain',True)]:
            bad=copy.deepcopy(record);bad['original_report']['pause']['response'][key]=value
            with self.assertRaises(SafetyHalt):verify_active_auxiliaries(self.h.case,b,bad)

    def gate_claim(self):
        from gate_probe_fixture import ProbeBridge, S, W, P
        from gate_probe_contract import probe_body
        rid='intervening-gate';resident=self.old.identity['resident_session'];bridge=ProbeBridge()
        command={'op':'encounter_gate_off_probe','probe_schema_version':1,'expected_resident_session':resident,
                 'expected_action_session':S,'expected_world_generation':W,'expected_player_uuid':P}
        body=probe_body(dict(command,request_id=rid),resident)
        before={'status':bridge.status,'state':bridge.state,'screen':{'open':True,'class':'net.minecraft.client.gui.screens.PauseScreen'},'started_monotonic':1.,'finished_monotonic':1.01}
        intent={'request_id':rid,'body':body,'targets_declared_unspawned_test_identifiers':True,'fixture_observation_claimed':False,'automatic_retry':False,'before':before}
        result=dict(copy.deepcopy(intent),post_attempted=True,expected_rejection=True,http_status=409,native_error='encounter_stage1_disabled',response=None,after=copy.deepcopy(before),ownership_and_inputs_unchanged=True,transport_uncertain=False,stop_reason='gate_probe_expected_rejection',probe_passed=True)
        receipt={'request_id':rid,'session_id':resident,'status':'succeeded','reason':'gate_off_rejection_verified','result':result}
        outer={'request_id':rid,'command':command,'authorization_ref':'intervening-gate-approval','targets_are_unspawned_test_identifiers':True,'fixture_registration':False,'automatic_retry':False,'submitted':False,'result':None,'probe_passed':False}
        completed=dict(copy.deepcopy(outer),submitted=True,result=receipt,probe_passed=True)
        files={}
        for folder,a,b in [('gate-off-probes',intent,result),('gate-off-case-evidence',outer,completed)]:
            root=self.root.parent/folder;root.mkdir()
            for suffix,value in [('intent',a),('result',b)]:
                path=root/(rid+'.'+suffix+'.json');path.write_text(json.dumps(value));files[(folder,suffix)]=path
        (self.root.parent/'results'/('intervening-gate.json')).write_text(json.dumps(receipt))
        return files
    def test_ready_restart_cannot_forget_durable_uncertain_queue_result(self):
        p=self.root.parent/'results'/'old-unknown.json'
        p.write_text(json.dumps({'request_id':'old-unknown','session_id':self.old.o.resident,'status':'uncertain','post_uncertain':True}))
        with self.assertRaisesRegex(SafetyHalt,'durable_queue_outcome_unknown'):self.roll()
        self.no_rollover()
    def test_ready_restart_cannot_forget_unfinished_gate_claim(self):
        files=self.gate_claim();files[('gate-off-probes','result')].unlink()
        with self.assertRaisesRegex(SafetyHalt,'gate_claim_unfinished'):self.roll()
        self.no_rollover()
    def test_ready_restart_cannot_forget_durable_unknown_gate_post(self):
        files=self.gate_claim();p=files[('gate-off-probes','result')];d=json.loads(p.read_text())
        d.update(transport_uncertain=True,probe_passed=False,expected_rejection=False,stop_reason='gate_probe_other_or_unknown_result')
        p.write_text(json.dumps(d))
        # Even after the ordinary mailbox result expires, the durable claim blocks.
        (self.root.parent/'results'/'intervening-gate.json').unlink()
        with self.assertRaisesRegex(SafetyHalt,'gate_probe_unknown'):self.roll()
        self.no_rollover()
    def test_known_exact_gate_pass_allows_rollover_and_claim_hashes_remain_bound(self):
        files=self.gate_claim();result=self.roll()
        self.assertEqual(len(result['durable_queue_after']['durable_gate_files']),4)
        p=files[('gate-off-probes','intent')];p.write_text(p.read_text()+' ')
        with self.assertRaisesRegex(SafetyHalt,'saved_gate_claim_changed'):read_chain(self.new)
    def test_other_result_unknown_arriving_during_rollover_read_refuses(self):
        q=self.new.o.c;original=q.wait
        def changed(rid,timeout):
            result=original(rid,timeout)
            (q.root/'results'/'foreign-unknown.json').write_text(json.dumps({'request_id':'foreign-unknown','session_id':q.binding.resident_session,'status':'failed','unknown_outcome':True}))
            return result
        q.wait=changed
        with self.assertRaisesRegex(SafetyHalt,'durable_queue_outcome_unknown'):self.roll()
        self.no_rollover()

    def test_old_gate_request_id_cannot_be_reused_after_mailbox_result_expiry(self):
        self.gate_claim();self.roll();(self.root.parent/'results'/'intervening-gate.json').unlink()
        b=self.register_next(request_id='intervening-gate')
        with self.assertRaisesRegex(SafetyHalt,'already_consumed'):
            self.new.reserve_trial(b,{'op':'action',**b.encounter_request},'reused-gate')
        self.assertFalse((self.root/'case-000002'/'trial-reservation.json').exists())
