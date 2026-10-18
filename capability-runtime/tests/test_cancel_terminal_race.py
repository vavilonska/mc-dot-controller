"""Completion/cancel race, exact no-dispatch proof, and the real public owner chain.
The native endpoint is modeled. No game, replay, native cancel or timing relaxation.
"""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
import uuid
from unittest.mock import patch

from base_watchdog import Watchdog
from capability_ownership import context_of
from intent_client import IntentClient
from resident_controller.cancel_terminal import validate, normalized, REASON
from support_core import state
import test_scoped_combat_chain as chain
import test_inventory_recovery_chain as inventory_chain
import test_inventory_recovery as recovery_model
import test_toolbox_inventory_container as container_model

RID = 'original_click'
QID = 'resident_original'
CANCEL = 'cancel_original'
RESIDENT = '11111111-1111-4111-8111-111111111111'
OWNER = 'a' * 32

class Queue:
    def __init__(self, result):
        self.original = deepcopy(result); self.hook = lambda: None; self.writes = []
    def result(self, request_id):
        assert request_id == QID
        return deepcopy(self.original)
    def session(self):
        self.hook()
        return {'session_id': RESIDENT, 'state': 'ready', 'pending': 0, 'active_request_id': None,
                'resident_policy': {'schema_version': 1, 'requires_handoff': False, 'input_release_unconfirmed': False}}
    def submit(self, *args, **kwargs):
        self.writes.append((args, kwargs)); raise AssertionError('terminal proof must never submit')

def setup_gateway(directory):
    s = state(); ctx = context_of(s)
    original = {'request_id': QID, 'session_id': RESIDENT, 'status': 'succeeded', 'finished_at': 99.,
        'result': {'action': {'action_schema_version': 1, 'action_id': uuid.uuid5(uuid.UUID(RESIDENT), QID + ':1').hex,
            'action_session': ctx['action_session'], 'action': 'click_slot', 'status': 'succeeded',
            'reason': 'click_dispatched', 'result': {'input_release_confirmed': True, 'dispatched': True}}}}
    q = Queue(original); dog = Watchdog(q, clock=lambda: 100., execution_policy='request_only')
    dog.capability_directory = Path(directory)
    dog.latest = {'state': s}; dog.capability_lease = {'owner_id': OWNER, 'context': ctx,
        'resident_session': RESIDENT, 'defense_epoch': 0, 'state': 'active', 'owner_mode': 'ordinary',
        'deadline': 200., 'heartbeat': 200., 'last_mutation': {'intent_id': RID, 'queue_request_id': QID,
            'resident_session': RESIDENT}, 'post_observation_required': True}
    cmd = {'op': 'capability_cancel', 'owner_id': OWNER, 'expected_defense_epoch': 0,
           'expected_intent_id': RID, 'expected_action_session': ctx['action_session']}
    return dog, cmd, normalized(original, RID, dog.session_id, QID)

def ack(dog):
    row = dog.completed[-1]
    return normalized(row['result'], row['intent_id'], row['session_id'], row['queue_request_id'])

class TerminalProofTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
    def gateway(self):return setup_gateway(self.temp.name)
    def test_exact_last_terminal_is_proved_without_cancel_or_release(self):
        d, c, original = self.gateway(); lease = deepcopy(d.capability_lease)
        d.capability_cancel(CANCEL, c); result = ack(d)
        self.assertTrue(validate(result, c, CANCEL, d.session_id, original=original, context=lease['context']))
        self.assertEqual(result['reason'], REASON); self.assertEqual(d.q.writes, [])
        self.assertIsNone(d.owner); self.assertEqual(d.capability_lease['state'], 'active')
        self.assertTrue(d.capability_lease['post_observation_required'])
        self.assertEqual(d.capability_lease['last_mutation'], lease['last_mutation'])
        self.assertEqual(json.loads((Path(self.temp.name)/'capability-owner.json').read_text())['owner_id'], OWNER)
    def test_duplicate_different_cancel_id_never_queues(self):
        d, c, original = self.gateway(); d.capability_cancel(CANCEL, c); d.capability_cancel('different', c)
        self.assertEqual(ack(d)['status'], 'failed'); self.assertEqual(d.q.writes, [])
    def test_unknown_missing_wrong_original_or_release_does_not_get_proof(self):
        for fault in ('absent', 'request', 'session', 'status', 'native_id', 'native_session', 'native_schema', 'release', 'unsafe', 'quarantine', 'automation'):
            with self.subTest(fault=fault):
                d, c, _ = self.gateway(); o=d.q.original; n=o['result']['action']
                if fault=='absent':d.q.original=None
                elif fault=='request':o['request_id']='another'
                elif fault=='session':o['session_id']='another'
                elif fault=='status':o['status']='uncertain'
                elif fault=='native_id':n['action_id']='a'*32
                elif fault=='native_session':n['action_session']='another'
                elif fault=='native_schema':n['action_schema_version']=True
                elif fault=='release':n['result']['input_release_confirmed']=False
                elif fault=='quarantine':n['result']['unknown_outcome_quarantined']=True
                elif fault=='automation':n['result']['automation_blocked']=True
                else:n['result']['unknown_outcome']=True
                d.capability_cancel(CANCEL,c);self.assertNotIn('exact_cancel_terminal',ack(d));self.assertEqual(d.q.writes,[])
    def test_after_io_current_owner_lease_context_epoch_and_deadline_fences(self):
        for fault in ('owner','lease','last','session','context','latest','epoch','deadline','heartbeat','rpc','command','cancel','stopped'):
            with self.subTest(fault=fault):
                d,c,_=self.gateway()
                def change():
                    if fault=='owner':d.owner={'id':RID,'capability_owner':OWNER}
                    elif fault=='lease':d.capability_lease=deepcopy(d.capability_lease)
                    elif fault=='last':d.capability_lease['last_mutation']['intent_id']='replacement'
                    elif fault=='session':d.session_id='replacement'
                    elif fault=='context':d.capability_lease['context']['dimension']='replacement'
                    elif fault=='latest':d.latest['state']['world']['dimension']='replacement'
                    elif fault=='epoch':d.defense_epoch+=1
                    elif fault in ('deadline','heartbeat'):d.capability_lease[fault]=99
                    elif fault=='rpc':d.rpc={'id':'replacement'}
                    elif fault=='command':c['expected_intent_id']='replacement'
                    elif fault=='cancel':d.capability_lease['cancel_control']={'state':'submitted'}
                    else:d.stopped=True
                d.q.hook=change;d.capability_cancel(CANCEL,c)
                self.assertNotIn('exact_cancel_terminal',ack(d));self.assertEqual(d.q.writes,[])
    def test_post_persistence_replacement_or_failure_never_acknowledges(self):
        for fault in ('replacement','error'):
            d,c,_=self.gateway()
            def changed(lease):
                if fault=='error':raise OSError('injected')
                d.capability_lease=deepcopy(lease)
            d.capability_checkpoint=changed;d.capability_cancel(CANCEL,c)
            self.assertNotIn('exact_cancel_terminal',ack(d));self.assertEqual(d.q.writes,[])
    def test_last_clock_callback_cannot_replace_owner_after_persistence(self):
        d,c,_=self.gateway();calls=[]
        def clock():
            calls.append(1)
            if len(calls)==3:d.owner={'id':'replacement'}
            return 100.
        d.clock=clock;d.capability_cancel(CANCEL,c)
        self.assertEqual(len(calls),3);self.assertNotIn('exact_cancel_terminal',ack(d))
        self.assertEqual(d.owner,{'id':'replacement'});self.assertEqual(d.q.writes,[])
    def test_closed_proof_digest_and_original_negative_matrix(self):
        d,c,original=self.gateway();d.capability_cancel(CANCEL,c);good=ack(d)
        for mutation in [lambda x:x.update(status='failed'),lambda x:x.update(queue_request_id='queued'),
            lambda x:x.update(extra=True),lambda x:x['exact_cancel_terminal'].update(schema_version=True),
            lambda x:x['exact_cancel_terminal'].update(cancel_dispatched=True),
            lambda x:x['exact_cancel_terminal'].update(semantic_postcondition_confirmed=True),
            lambda x:x['exact_cancel_terminal'].update(original_result_sha256='0'*64),
            lambda x:x['exact_cancel_terminal']['command'].update(expected_intent_id='other')]:
            bad=deepcopy(good);mutation(bad);self.assertFalse(validate(bad,c,CANCEL,d.session_id,original=original))
        other=deepcopy(original);other['finished_at']+=1
        self.assertFalse(validate(good,c,CANCEL,d.session_id,original=other))
    def test_public_client_rejects_forged_wrapper_and_malformed_proof(self):
        d,c,_=self.gateway();d.capability_cancel(CANCEL,c);row=d.completed[-1]
        root=Path(self.temp.name)/'client';(root/'results').mkdir(parents=True);client=IntentClient(root)
        path=root/'results'/(CANCEL+'.json');path.write_text(json.dumps(row));self.assertEqual(client.result(CANCEL)['reason'],REASON)
        for fault in ('wrapper','schema'):
            value=deepcopy(row)
            if fault=='wrapper':value['intent_id']='replacement'
            else:value['result']['exact_cancel_terminal']['schema_version']=True
            path.write_text(json.dumps(value))
            with self.assertRaises(ValueError):client.result(CANCEL)

class PublicTerminalRaceTests(unittest.TestCase):
    until=chain.PublicCombatChainTests.until
    setUp=chain.PublicCombatChainTests.setUp
    tearDown=chain.PublicCombatChainTests.tearDown
    submit=chain.PublicCombatChainTests.submit
    finish=chain.PublicCombatChainTests.finish
    def run_race(self, corrupt=False):
        original_result=self.client.result;injected=[]
        def read(rid):
            result=original_result(rid)
            record=self.runtime._journal.get('records',{}).get(rid,{})
            if (result is not None and record.get('kind')=='mutation' and not injected
                    and result.get('status')=='succeeded'):
                injected.append(rid)
                self.assertIsNone(self.dog.owner) # Completed original was published and current action owner cleared.
                self.runtime._job_control.request_cancel('race_cancel')
                return None # Original became visible immediately after the preceding read/stop check.
            if corrupt and result and 'exact_cancel_terminal' in result:
                if corrupt == 'client_error':raise ValueError('exact_cancel_terminal_proof_invalid')
                elif corrupt == 'old':
                    result.pop('exact_cancel_terminal');result.update(status='failed',reason='exact_cancel_owner_or_target_mismatch')
                elif corrupt == 'queued':result['queue_request_id']='a_possible_queued_cancel'
                else:result['exact_cancel_terminal']['original_result_sha256']='0'*64
            return result
        self.client.result=read
        result=self.finish(self.submit())
        self.assertEqual(len(injected),1)
        record=self.runtime._journal['records'][injected[0]]
        self.assertIn('receipt_ref',record)
        self.assertEqual(len([p for p,b in self.bridge.posts if p=='/control/scoped-action']),1)
        self.assertFalse([p for p,b in self.bridge.posts if p=='/control/action/cancel'])
        self.assertFalse(result['server_confirmed'])
        if corrupt:
            self.assertEqual(result['state'],'unknown',result)
            self.assertIn(record['reason'],('exact_cancel_terminal_proof_unconfirmed','exact_cancel_receipt_unconfirmed','queue_exchange_unknown:ValueError'))
            self.assertIsNotNone(self.client.session()['capability_lease'])
        else:
            self.assertEqual(result['state'],'cancelled',result)
            self.assertEqual(result['effect_certainty'],'known',result)
            self.assertEqual(result['cleanup_certainty'],'confirmed',result)
            self.assertEqual(result['result']['evidence']['semantic_verification'],'incomplete',result)
            self.assertIsNone(self.client.session()['capability_lease'])
            self.assertIsNone(self.runtime._journal['pending']);self.assertIsNone(self.runtime._journal['semantic_pending'])
    def test_completed_original_stops_goal_and_uses_normal_cleanup(self):self.run_race()
    def test_malformed_terminal_proof_keeps_unknown_and_original_receipt(self):self.run_race(corrupt=True)
    def test_client_parse_failure_preserves_original_and_unknown(self):self.run_race(corrupt='client_error')
    def test_old_unproven_mismatch_still_keeps_unknown(self):self.run_race(corrupt='old')
    def test_potential_queued_cancel_keeps_unknown(self):self.run_race(corrupt='queued')

class ContainerEndpoint(inventory_chain.Endpoint):
    def __init__(self):
        super().__init__()
        obs=recovery_model.ready(container_model.storage_observation(source_count=0,destination_count=16))
        obs.state['menu']['slots'][0]['item']=recovery_model.stack()
        self.model=container_model.ClickRuntime(obs)
        inventory_chain.normalize(self.model.current)

class PublicContainerRaceTests(unittest.TestCase):
    until=chain.PublicCombatChainTests.until
    tearDown=inventory_chain.InventoryRecoveryChainTests.tearDown
    submit=inventory_chain.InventoryRecoveryChainTests.submit
    finish=inventory_chain.InventoryRecoveryChainTests.finish
    def setUp(self):
        with patch.object(inventory_chain,'Endpoint',ContainerEndpoint):
            inventory_chain.InventoryRecoveryChainTests.setUp(self)
    def test_second_click_terminal_then_cancel_does_not_claim_transfer_success(self):
        original_result=self.client.result;injected=[]
        def read(rid):
            result=original_result(rid);record=self.runtime._journal.get('records',{}).get(rid,{})
            if (result and result.get('status')=='succeeded' and record.get('kind')=='mutation'
                    and len(self.bridge.model.commands)==2 and not injected):
                injected.append(rid);self.runtime._job_control.request_cancel('container_race_cancel');return None
            return result
        self.client.result=read
        arguments={'container_id':7,'menu_state_id':11,'source_slot':54,'destination_slot':0,'quantity':3}
        first=self.submit('container_deposit',arguments,'deposit-race')
        result=self.finish(first)
        self.assertEqual(result['state'],'cancelled',result)
        self.assertEqual(result['cleanup_certainty'],'confirmed',result)
        self.assertEqual(result['effect_certainty'],'known',result)
        evidence=result['result']['evidence']
        self.assertEqual(evidence['completed_clicks'],1)
        self.assertEqual(evidence['stages'][1]['evidence']['semantic_verification'],'incomplete')
        self.assertNotIn('total_conserved',evidence);self.assertNotIn('cursor_empty',evidence)
        self.assertEqual(evidence['last_observed_carried']['count'],16) # Explicit historical observation, not current.
        self.assertEqual(self.bridge.model.current.state['menu']['carried']['count'],15)
        self.assertEqual(self.bridge.model.current.state['menu']['slots'][0]['item']['count'],1)
        self.assertEqual(len(self.bridge.model.commands),2)
        self.assertFalse([p for p,b in self.bridge.posts if p=='/control/action/cancel'])
        self.assertIsNone(self.client.session()['capability_lease'])
        again=self.submit('container_deposit',arguments,'deposit-race')
        self.assertEqual(again['job_id'],first['job_id']);self.assertEqual(len(self.bridge.model.commands),2)
        fresh=self.service.call('mdc_observe',{'api_version':'mdc.toolbox/1','request_id':'fresh-menu-after-race',
            'session_ref':first['session_ref'],'profile':'menu','bounds':{'radius':1}})
        self.assertEqual(fresh['job_state'],'succeeded',fresh)
        self.assertEqual(fresh['cleanup_certainty'],'confirmed')
        self.assertEqual(fresh['state']['menu']['carried']['count'],15)
        self.assertEqual(len(self.bridge.model.commands),2)
        # A separately requested new recovery obtains another fresh owned menu observation.
        recovered=self.finish(self.submit('recover_cursor',recovery_model.cursor_args(self.bridge.model.current),'recover-after-race'))
        self.assertEqual(recovered['state'],'succeeded',recovered)
        self.assertEqual(recovered['cleanup_certainty'],'confirmed',recovered)
        self.assertTrue(self.bridge.model.current.state['menu']['carried']['empty'])
        self.assertEqual(len(self.bridge.model.commands),3)

if __name__=='__main__':unittest.main()
