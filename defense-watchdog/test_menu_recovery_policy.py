"""Current policy and finite intake around the explicit menu-only exception."""
import copy
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
from base_watchdog import cancel_waiting_intents, write_json
from intent_client import IntentClient
import test_menu_recovery as fixtures


class MenuPolicyTests(unittest.TestCase):
    def ready(self):
        c = fixtures.MenuRecoveryChecks(); c.setUp(); c.recover()
        while c.d.rpc: c.tick()
        return c

    def test_current_owner_flags_and_unknown_observation_never_offer_escape(self):
        changes = [lambda c:setattr(c.d,'input_release_latched',True),
                   lambda c:setattr(c.d,'handoff_latched',True),
                   lambda c:setattr(c.d.environment,'active',True),
                   lambda c:setattr(c.d,'ranged_move',{'id':'old-ranged'}),
                   lambda c:c.d.latest.pop('resident_policy'),
                   lambda c:c.d.latest['resident_policy'].update(requires_handoff=1),
                   lambda c:c.d.latest['resident_policy'].update(input_release_unconfirmed=True),
                   lambda c:c.d.latest['resident_policy'].update(requires_handoff=True),
                   lambda c:c.d.latest['state'].pop('paused'),
                   lambda c:c.d.latest['state'].update(paused=1),
                   lambda c:c.d.latest['state']['client_action'].pop('status'),
                   lambda c:c.d.latest['state']['client_action'].update(status='unknown'),
                   lambda c:c.d.latest['state']['client_action'].update(status='running'),
                   lambda c:c.d.latest['action'].update(status='unknown'),
                   lambda c:c.d.latest['combat'].pop('active'),
                   lambda c:c.d.latest.update(state=None),
                   lambda c:c.d.latest.update(status=None)]
        for index,change in enumerate(changes):
            with self.subTest(index=index):
                c=self.ready();change(c);before=copy.deepcopy(c.q.calls)
                self.assertFalse(c.d.menu_close_ready())
                self.assertFalse(c.d.submit_owner('close',c.close()))
                self.assertEqual(before,c.q.calls)

    def test_clear_current_policy_does_not_borrow_historical_release_failure(self):
        c=self.ready()
        c.d.latest['action']={'status':'failed','reason':'input_release_unconfirmed',
                             'result':{'input_release_confirmed':False}}
        self.assertTrue(c.d.menu_close_ready())
        self.assertTrue(c.d.submit_owner('close',c.close()))
        rid=c.d.owner['request_id']
        c.q.results[rid]['action']=copy.deepcopy(c.d.latest['action'])
        c.d.tick()
        self.assertFalse(c.d.input_release_latched)
        self.assertFalse(c.d.handoff_latched)
        self.assertTrue(c.d.recover_observation)

    def test_adapter_only_accepts_exact_close_in_current_paused_recovery(self):
        c=self.ready()
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for name in ('inbox','working','results'):(root/name).mkdir()
            client=IntentClient(root)
            for state in ('ready','busy','starting','stopped'):
                write_json(root/'state.json',{**c.d.status(),'state':state,'updated_at':time.time()})
                with self.assertRaisesRegex(ValueError,'not_accepting'):client.submit(fixtures.CLOSE,'bad')
                self.assertEqual([],list((root/'inbox').iterdir()))
            write_json(root/'state.json',{**c.d.status(),'updated_at':time.time()})
            with self.assertRaisesRegex(ValueError,'invalid_recovery'):client.submit({**fixtures.CLOSE,'body':{}},'bad')
            client.submit(fixtures.CLOSE,'new')
            command=json.loads((root/'inbox/new.json').read_text())
            self.assertEqual(c.d.session_id,command['_watchdog_session_id'])
            self.assertEqual(c.d.defense_epoch,command['_navigation_defense_epoch'])
            self.assertLessEqual(abs(time.time()-command['_menu_recovery_requested_at']),.8)

    def test_stale_or_unbound_intent_cannot_wait_for_a_later_recovery_period(self):
        c=self.ready();before=copy.deepcopy(c.q.calls)
        for stamp in (None,True,float('nan'),float('inf'),time.time()-1,time.time()+1):
            with self.subTest(stamp=stamp):
                command=c.close();command['_menu_recovery_requested_at']=stamp
                with self.assertRaisesRegex(ValueError,'stale_menu'):c.d.submit_owner('old',command)
        command=c.close();command.pop('_navigation_defense_epoch')
        with self.assertRaisesRegex(ValueError,'stale_menu'):c.d.submit_owner('missing',command)
        command=c.close();command['_navigation_defense_epoch']-=1
        self.assertTrue(c.d.submit_owner('old-epoch',command))
        self.assertEqual('navigation_defense_epoch_changed',c.d.completed[-1]['result']['reason'])
        self.assertEqual(before,c.q.calls)

    def test_inbox_preserves_only_same_session_epoch_and_unexpired_explicit_close(self):
        c=self.ready()
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for name in ('inbox','working','results'):(root/name).mkdir()
            valid={**c.close(),'_watchdog_session_id':c.d.session_id}
            edits={'old-session':{'_watchdog_session_id':'old'},'old-epoch':{'_navigation_defense_epoch':-1},
                   'expired':{'_menu_recovery_requested_at':time.time()-1},'wrong-bool':{'_navigation_defense_epoch':True},
                   'arbitrary':{'body':{}}}
            write_json(root/'inbox/new.json',valid)
            for name,change in edits.items():write_json(root/'inbox'/f'{name}.json',{**valid,**change})
            cancel_waiting_intents(root,c.d)
            self.assertEqual(['new.json'],[p.name for p in (root/'inbox').iterdir()])
            self.assertEqual(set(edits),{p.stem for p in (root/'results').iterdir()})
            c.d.defense_epoch+=1;cancel_waiting_intents(root,c.d)
            self.assertEqual([],list((root/'inbox').iterdir()))

    def test_current_release_evidence_wins_over_handoff_for_menu_result(self):
        c=self.ready();self.assertTrue(c.d.submit_owner('close',c.close()))
        rid=c.d.owner['request_id'];c.q.results[rid].update(status='failed',reason='current-policy')
        c.q.results[rid]['resident_policy'].update(requires_handoff=True,input_release_unconfirmed=True)
        before=copy.deepcopy(c.q.calls);c.d.tick()
        self.assertTrue(c.d.input_release_latched)
        self.assertEqual('owner_input_release_unconfirmed',c.d.reason)
        self.assertEqual(before,c.q.calls)

    def test_uncertain_metadata_never_rearms_or_submits_generic_cancel(self):
        for field in ('unknown_outcome','post_uncertain','uncertain'):
            c=self.ready();c.d.submit_owner('close',c.close());rid=c.d.owner['request_id']
            c.q.results[rid][field]=True;before=copy.deepcopy(c.q.calls);c.d.tick()
            self.assertFalse(c.d.armed);self.assertFalse(c.d.recover_observation)
            self.assertEqual('menu_recovery_outcome_unconfirmed',c.d.reason)
            self.assertEqual(before,c.q.calls)

    def test_mailbox_submission_unknown_retains_original_id_without_replay(self):
        c=self.ready();original=c.q.submit
        def lost_ack(command,request_id=None):
            original(command,request_id=request_id)
            c.q.results.pop(request_id,None)
            raise OSError('synthetic write acknowledgement lost')
        with patch.object(c.q,'submit',side_effect=lost_ack):
            with self.assertRaises(OSError):c.d.submit_owner('close',c.close())
        rid=c.d.owner['request_id'];self.assertEqual(rid,c.q.calls[-1][0])
        before=copy.deepcopy(c.q.calls)
        for _ in range(10):c.d.tick()
        self.assertEqual(rid,c.d.owner['request_id']);self.assertEqual(before,c.q.calls)
        self.assertFalse(c.d.recover_observation)

    def test_unknown_submission_claims_original_inbox_until_late_result_publication(self):
        for late_before_claim in (False,True):
            with self.subTest(late_before_claim=late_before_claim):
                c=self.ready();original=c.q.submit;late=[]
                with tempfile.TemporaryDirectory() as tmp:
                    root=Path(tmp)
                    for folder in ('inbox','working','results'):(root/folder).mkdir()
                    write_json(root/'state.json',{**c.d.status(),'updated_at':time.time()})
                    client=IntentClient(root);client.submit(fixtures.CLOSE,'exact-close')
                    intent=json.loads((root/'inbox/exact-close.json').read_text());intent.pop('_watchdog_session_id')
                    def lost_ack(command,request_id=None):
                        original(command,request_id=request_id);late.append(c.q.results.pop(request_id))
                        raise OSError('synthetic committed mailbox acknowledgement lost')
                    with patch.object(c.q,'submit',side_effect=lost_ack):
                        with self.assertRaises(OSError):c.d.submit_owner('exact-close',intent)
                    rid=c.d.owner['request_id'];before=copy.deepcopy(c.q.calls)
                    if late_before_claim:c.q.results[rid]=late[0]
                    c.d.tick();cancel_waiting_intents(root,c.d)
                    self.assertFalse((root/'inbox/exact-close.json').exists())
                    self.assertTrue((root/'working/exact-close.json').exists())
                    self.assertIsNone(client.result('exact-close'))
                    if not late_before_claim:
                        c.q.results[rid]=late[0];c.d.tick();cancel_waiting_intents(root,c.d)
                    self.assertEqual(1,len(c.d.completed));done=c.d.completed[0]
                    self.assertEqual('exact-close',done['intent_id']);self.assertEqual(rid,done['queue_request_id'])
                    self.assertEqual(late[0],done['result'])
                    write_json(root/'results/exact-close.json',done)
                    (root/'working/exact-close.json').unlink()
                    c.d.completed.clear();cancel_waiting_intents(root,c.d)
                    self.assertEqual('succeeded',client.result('exact-close')['status'])
                    self.assertEqual(rid,client.result('exact-close')['queue_request_id'])
                    self.assertEqual(before,c.q.calls)
                    self.assertFalse(c.d.recover_observation)
                    self.assertEqual('menu_recovery_submission_unconfirmed',c.d.reason)

    def test_malformed_success_result_is_a_hard_pause_without_generic_cancel(self):
        for raw in (None,[],True,'unknown'):
            c=self.ready();c.d.submit_owner('close',c.close());rid=c.d.owner['request_id']
            c.q.results[rid]['result']=raw;before=copy.deepcopy(c.q.calls);c.d.tick()
            self.assertFalse(c.d.armed);self.assertFalse(c.d.recover_observation)
            self.assertEqual('menu_recovery_outcome_unconfirmed',c.d.reason)
            self.assertEqual(before,c.q.calls)

    def test_explicit_stop_remains_available_for_a_pending_menu_owner(self):
        c=self.ready();c.d.submit_owner('close',c.close());rid=c.d.owner['request_id'];c.q.results.pop(rid)
        before=len([v for _,v in c.q.calls if v['op']=='cancel'])
        c.d.stop();c.tick(3)
        self.assertTrue(c.d.stopped)
        self.assertEqual(before+1,len([v for _,v in c.q.calls if v['op']=='cancel']))

    def test_post_menu_samples_cannot_hide_current_action_behind_old_outer_terminal(self):
        for status in ('running','unknown',None,'missing'):
            with self.subTest(status=status):
                c=self.ready();c.d.submit_owner('close',c.close());c.d.tick()
                self.assertEqual('menu_recovery_awaiting_two_fresh_samples',c.d.reason)
                c.q.obs['state']['screen_open']=False
                if status=='missing':c.q.obs['state']['client_action'].pop('status')
                else:c.q.obs['state']['client_action']['status']=status
                before=len([v for _,v in c.q.calls if v['op'] in ('direct','cancel')]);c.tick(25)
                self.assertFalse(c.d.armed);self.assertFalse(c.d.recover_observation)
                self.assertEqual('observation_recovery_context_changed',c.d.reason)
                self.assertEqual(before,len([v for _,v in c.q.calls if v['op'] in ('direct','cancel')]))

    def test_ordinary_legacy_recovery_without_current_action_field_remains_valid(self):
        c=self.ready();c.q.obs['state']['screen_open']=False
        c.q.obs['state']['client_action'].pop('status');c.tick(25)
        self.assertTrue(c.d.armed)
        self.assertEqual([], [v for _,v in c.q.calls if v['op']=='direct'])


if __name__=='__main__':unittest.main()
