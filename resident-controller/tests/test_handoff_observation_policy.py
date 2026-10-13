"""Current policy through real mailbox/Resident/Watchdog; no native game or network."""
import copy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import uuid

sys.path.insert(0,str(Path(__file__).resolve().parent))
from test_encounter_handoff_chain import Chain, Watchdog, BridgeError


class ObservationPolicyTests(unittest.TestCase):
    def chain(self, mode='running'):
        c=Chain(mode);self.addCleanup(c.close);return c
    def dog(self,c):
        now=[100.0];c.dog=Watchdog(c.q,clock=lambda:now[0]);return now
    def test_four_restart_edges_preserve_original_id_body_and_current_policy(self):
        for mode in ('running','failed'):
            for entry in ('error','pending'):
                with self.subTest(mode=mode,entry=entry):
                    c=self.chain(mode);c.start()
                    if mode=='failed':c.finish_native()
                    original=copy.deepcopy(c.posts('/control/action')[0][2]);now=self.dog(c)
                    if entry=='error':
                        request=c.bridge.request
                        def failing(method,path,body=None):
                            if path=='/control/state?radius=8':raise BridgeError('read_timeout',uncertain=True)
                            return request(method,path,body)
                        c.bridge.request=failing;c.pump(8)
                    else:
                        c.dog.tick();pending=c.dog.rpc['id'];now[0]=103;c.dog.tick()
                        self.assertEqual(pending,c.dog.rpc['id']);c.resident.read_commands()
                    self.assertEqual([original],[v[2] for v in c.posts('/control/action')])
                    self.assertEqual([],c.posts('/control/release-all'));self.assertEqual([],c.posts('/control/action/cancel'))
                    if mode=='failed':
                        self.assertTrue(c.resident.paused);self.assertEqual('encounter_requires_handoff',c.resident.reason)
                    else:self.assertIsNotNone(c.resident.active.encounter_request)
    def test_missing_stale_wrong_session_or_bad_policy_never_authorizes_fallback(self):
        changes=[lambda s:s.pop('resident_policy'),lambda s:s.update(updated_at=s['updated_at']-4),
                 lambda s:s.update(updated_at=s['updated_at']+4),lambda s:s.update(session_id='foreign'),
                 lambda s:s['bridge_identity'].update(action_session='foreign'),
                 lambda s:s['resident_policy'].update(requires_handoff=0),
                 lambda s:s['resident_policy'].update(schema_version=True)]
        for change in changes:
            with self.subTest(change=changes.index(change)):
                c=self.chain();now=self.dog(c);c.dog.tick();rid=c.dog.rpc['id']
                data=copy.deepcopy(c.q.session());change(data)
                with patch.object(c.q,'session',return_value=data):now[0]=103;c.dog.tick()
                self.assertEqual(rid,c.dog.rpc['id']);self.assertTrue(c.dog.handoff_latched)
                self.assertEqual('resident_policy_unconfirmed',c.dog.reason);self.assertEqual([],c.posts())
    def test_missing_session_before_initial_observe_stops_without_submission(self):
        c=self.chain();self.dog(c)
        with patch.object(c.q,'session',side_effect=FileNotFoundError('synthetic')):c.dog.tick()
        self.assertIsNone(c.dog.rpc);self.assertTrue(c.dog.handoff_latched)
        self.assertEqual([],list((c.resident.root/'inbox').glob('*.json')))
        self.assertEqual([],c.posts())
    def test_explicit_ready_policy_ignores_historical_encounter_and_keeps_legacy_cancel(self):
        c=self.chain('failed');c.start();c.finish_native()
        resume=c.q.submit({'op':'resume'});c.pump(1)
        self.assertEqual('succeeded',c.q.result(resume)['status'])
        self.assertFalse(c.q.session()['resident_policy']['requires_handoff'])
        now=self.dog(c);c.dog.tick();now[0]=103;c.dog.tick();c.resident.read_commands()
        self.assertEqual(1,len(c.posts('/control/release-all')))
        self.assertFalse(c.dog.handoff_latched)
    def test_resident_rechecks_clear_policy_after_new_pending_encounter(self):
        c=self.chain();now=self.dog(c);c.dog.tick()
        rid=c.q.submit(c.bridge.command(),request_id='new-encounter')
        now[0]=103;c.dog.tick();fallback=c.dog.rpc['id']
        c.resident.read_commands()
        self.assertEqual('failed',c.q.result(fallback)['status'])
        self.assertTrue(c.q.result(fallback)['requires_handoff'])
        self.assertEqual([rid],[v['request_id'] for v in c.resident.pending])
        self.assertEqual([],c.posts())
        c.resident.advance()
        self.assertEqual(1,len(c.posts('/control/action')))
        expected=uuid.uuid5(uuid.UUID(c.resident.session_id),rid+':1').hex
        self.assertEqual(expected,c.bridge.accepted['action_id'])
        c.dog.tick();self.assertTrue(c.dog.handoff_latched)
        self.assertEqual([],c.posts('/control/release-all'))
        self.assertEqual([],c.posts('/control/action/cancel'))
    def test_explicit_operator_stop_is_not_the_automatic_fallback(self):
        c=self.chain();c.start();now=self.dog(c);c.dog.tick();now[0]=103;c.dog.tick()
        self.assertTrue(c.dog.handoff_latched)
        c.dog.stop();c.dog.tick();c.resident.read_commands();c.dog.tick()
        self.assertEqual(1,len(c.posts('/control/release-all')))
        self.assertTrue(c.dog.stopped)
    def test_failed_read_result_preserves_unknown_status_reason_and_policy(self):
        c=self.chain('failed');c.start();c.finish_native();request=c.bridge.request
        def failing(method,path,body=None):
            if path=='/control/state?radius=8':raise BridgeError('read_timeout',uncertain=True)
            return request(method,path,body)
        c.bridge.request=failing;rid=c.q.submit({'op':'observe'});c.resident.read_commands()
        result=c.q.result(rid)
        self.assertEqual('uncertain',result['status']);self.assertEqual('read_timeout',result['reason'])
        self.assertTrue(result['resident_policy']['requires_handoff'])
        self.assertEqual('encounter_requires_handoff',c.resident.reason)
        self.assertEqual([],c.posts('/control/release-all'))

    def test_current_non_encounter_failed_read_keeps_original_cancel_behavior(self):
        c=self.chain();now=self.dog(c);request=c.bridge.request
        def failing(method,path,body=None):
            if path=='/control/state?radius=8':raise BridgeError('ordinary_read_timeout',uncertain=True)
            return request(method,path,body)
        c.bridge.request=failing;c.pump(8)
        self.assertEqual(1,len(c.posts('/control/release-all')))
        self.assertFalse(c.dog.handoff_latched)
        self.assertEqual([],c.posts('/control/action'))
    def test_restarted_resident_also_publishes_preexisting_encounter_ownership(self):
        c=self.chain();c.start();c.resident.lock.close()
        from resident_controller.controller import Resident
        c.resident=Resident(c.bridge,c.temp.name);c.resident.start()
        self.assertTrue(c.q.session()['resident_policy']['requires_handoff'])
        now=self.dog(c);c.dog.tick();now[0]=103;c.dog.tick();c.resident.read_commands()
        self.assertEqual([],c.posts('/control/release-all'))
        self.assertEqual([],c.posts('/control/action/cancel'))
        self.assertEqual(1,len(c.posts('/control/action')))

    def test_current_release_uncertainty_wins_when_queued_fallback_is_rejected(self):
        c=self.chain();now=self.dog(c);c.dog.tick();now[0]=103;c.dog.tick()
        fallback=c.dog.rpc['id']
        c.resident.paused=True;c.resident.reason='input_release_unconfirmed'
        c.resident.read_commands();result=c.q.result(fallback)
        self.assertEqual('failed',result['status'])
        self.assertTrue(result['resident_policy']['input_release_unconfirmed'])
        self.assertFalse(result['requires_handoff'])
        c.dog.tick()
        self.assertTrue(c.dog.input_release_latched)
        self.assertEqual('owner_input_release_unconfirmed',c.dog.reason)
        self.assertEqual([],c.posts())

    def test_first_successful_observation_marks_already_pending_encounter(self):
        c=self.chain();c.hostile()
        command=c.bridge.command();rid=c.q.submit(command,request_id='encounter-before-first-observe')
        self.dog(c);c.dog.tick();c.pump(8)
        expected={k:copy.deepcopy(v) for k,v in command.items() if k!='op'}
        expected['action_id']=uuid.uuid5(uuid.UUID(c.resident.session_id),rid+':1').hex
        self.assertEqual([expected],[v[2] for v in c.posts('/control/action')])
        self.assertEqual([],c.posts('/control/release-all'));self.assertEqual([],c.posts('/control/action/cancel'))
        self.assertIsNone(c.q.result(rid));self.assertEqual(rid,c.resident.active.command['request_id'])
        self.assertTrue(c.dog.handoff_latched)

    def test_new_pending_handoff_does_not_borrow_old_release_failure(self):
        c=self.chain('cleanup_failed');c.start();c.finish_native()
        resume=c.q.submit({'op':'resume'});c.pump(1)
        self.assertEqual('succeeded',c.q.result(resume)['status'])
        new=c.q.submit(c.bridge.command(),request_id='fresh-after-old-cleanup')
        self.dog(c);c.dog.tick();c.pump(8)
        self.assertTrue(c.dog.handoff_latched);self.assertFalse(c.dog.input_release_latched)
        self.assertEqual('encounter_requires_handoff',c.dog.reason)
        self.assertEqual(new,c.resident.active.command['request_id'])
        self.assertEqual(2,len(c.posts('/control/action')))
        self.assertEqual([],c.posts('/control/release-all'));self.assertEqual([],c.posts('/control/action/cancel'))
    def test_current_release_failure_still_wins_on_successful_observation(self):
        c=self.chain('cleanup_failed');c.start();c.finish_native()
        self.dog(c);c.dog.tick();c.pump(4)
        self.assertTrue(c.dog.input_release_latched)
        self.assertEqual('owner_input_release_unconfirmed',c.dog.reason)
        self.assertEqual([],c.posts('/control/release-all'))
