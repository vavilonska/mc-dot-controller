"""Exact pre-install refusal, real owner chain, and unproven UNKNOWN negatives."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from base_watchdog import Watchdog
from capability_ownership import context_of
from intent_client import IntentClient
from resident_controller.acquisition_refusal import validate, REASON
from mdc_skills.core import Runtime, SkillError
from mdc_toolbox import ToolboxService
from mdc_toolbox.runtime_adapter import OwnerRuntimeBackend
from support_core import state
import test_capability_ownership as ownership

class Queue:
    def __init__(self): self.reads = 0
    def session(self):
        self.reads += 1
        return {'session_id': 'resident', 'state': 'ready', 'pending': 0, 'active_request_id': None,
                'resident_policy': {'schema_version': 1, 'requires_handoff': False, 'input_release_unconfirmed': False}}

def gateway(directory, age=.801):
    q = Queue(); dog = Watchdog(q, clock=lambda: 100., execution_policy='request_only')
    dog.capability_directory = Path(directory)
    s = state(); s['screen_open'] = True
    s['menu'] = {'carried': {'id': 'minecraft:dirt', 'count': 14}}
    dog.latest = {'state': s, 'action': {'status': 'idle'}, 'combat': {'active': False}, 'status': {'held_mappings': []}}
    dog.observed_at = 100 - age
    command = {'op': 'capability_acquire', 'owner_id': 'a'*32, 'expected_defense_epoch': 0,
               'expected_context': context_of(s), 'duration_ms': 10000}
    return dog, command

def normalized(row):
    return {**deepcopy(row['result']), 'request_id': row['intent_id'], 'session_id': row['session_id'],
            'queue_request_id': row['queue_request_id'], 'queue_session_id': row['result'].get('session_id')}

class RefusalProofTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.dog, self.command = gateway(self.temp.name)
        self.dog.capability_control('b'*32, self.command)
        self.receipt = normalized(self.dog.completed[-1])
    def test_exact_stale_refusal_has_original_readiness_and_no_install(self):
        self.assertTrue(validate(self.receipt, self.command, 'b'*32, self.dog.session_id))
        self.assertIsNone(self.dog.capability_lease); self.assertEqual(self.dog.q.reads, 0)
        readiness = self.receipt['acquisition_refusal']['readiness']
        self.assertAlmostEqual(readiness['observation_age_ms'], 801)
        self.assertEqual(readiness['max_observation_age_ms'], 800)
        self.assertIs(readiness['checks']['observation_fresh'], False)
        self.assertIsNone(readiness['checks']['idle_predicate'])
        self.assertTrue(self.dog.latest['state']['screen_open'])
        self.assertEqual(self.dog.latest['state']['menu']['carried']['count'], 14)
    def test_original_800ms_predicate_unchanged(self):
        dog, cmd = gateway(self.temp.name, .799)
        dog.capability_control('c'*32, cmd)
        self.assertEqual(dog.completed[-1]['result']['status'], 'succeeded')
        self.assertNotIn('acquisition_refusal', dog.completed[-1]['result'])
        self.assertEqual(dog.capability_lease['owner_id'], cmd['owner_id'])
    def test_post_install_checkpoint_failure_has_no_refusal_proof(self):
        dog, cmd = gateway(self.temp.name, .1)
        dog.capability_checkpoint = lambda *_: (_ for _ in ()).throw(OSError('injected checkpoint failure'))
        with self.assertRaises(OSError): dog.capability_control('c'*32, cmd)
        self.assertIsNotNone(dog.capability_lease); self.assertEqual(dog.completed, [])
    def test_owner_installed_during_last_callback_cannot_get_proof(self):
        dog, cmd = gateway(self.temp.name)
        def changed():
            dog.capability_lease = {'owner_id': 'replacement'}
            return 100.
        dog.clock = changed
        dog.capability_control('c'*32, cmd)
        self.assertNotIn('acquisition_refusal', dog.completed[-1]['result'])
        self.assertEqual(dog.capability_lease, {'owner_id': 'replacement'})
    def test_session_or_command_replaced_at_last_callback_cannot_get_proof(self):
        for what in ('session', 'command', 'epoch', 'context'):
            dog, cmd = gateway(self.temp.name)
            def changed():
                if what == 'session': dog.session_id = 'replacement'
                elif what == 'command': cmd['expected_context']['dimension'] = 'replacement'
                elif what == 'epoch': dog.defense_epoch += 1
                else: dog.latest['state']['world']['dimension'] = 'replacement'
                return 100.
            dog.clock = changed
            dog.capability_control('c'*32, cmd)
            self.assertNotIn('acquisition_refusal', dog.completed[-1]['result'])
    def test_closed_proof_fault_matrix(self):
        mutations = [lambda r:r.pop('acquisition_refusal'), lambda r:r.update(queue_request_id='queued'),
            lambda r:r.update(queue_session_id='resident'), lambda r:r.update(capability_lease={}),
            lambda r:r.update(gameplay_effect_confirmed=True), lambda r:r.update(status='uncertain'),
            lambda r:r.update(reason='different_failure'), lambda r:r.update(request_id='different'),
            lambda r:r.update(session_id='different'), lambda r:r.update(extra=True),
            lambda r:r['acquisition_refusal'].update(schema_version=True),
            lambda r:r['acquisition_refusal'].update(stage='lease_installed'),
            lambda r:r['acquisition_refusal'].update(lease_installed=True),
            lambda r:r['acquisition_refusal'].update(resident_queue_submitted=True),
            lambda r:r['acquisition_refusal'].update(effects_none_proven=False),
            lambda r:r['acquisition_refusal'].update(command_sha256='0'*64),
            lambda r:r['acquisition_refusal']['command']['expected_context'].update(dimension='other'),
            lambda r:r['acquisition_refusal']['readiness'].update(max_observation_age_ms=801),
            lambda r:r['acquisition_refusal']['readiness'].update(observation_age_ms=float('nan')),
            lambda r:r['acquisition_refusal']['readiness']['checks'].update(idle_predicate=True)]
        for i, mutate in enumerate(mutations):
            with self.subTest(i=i):
                result = deepcopy(self.receipt); mutate(result)
                self.assertFalse(validate(result, self.command, 'b'*32, self.dog.session_id))
    def client(self, result):
        client = IntentClient(self.temp.name)
        client.session = lambda: {'session_id': self.dog.session_id, 'capability_lease_schema_version': 1,
                                  'defense_epoch': 0, 'capability_context': deepcopy(self.command['expected_context'])}
        client.submit = lambda command,request_id=None: request_id
        client.wait = lambda *a,**kw: deepcopy(result)
        return client
    def test_client_known_refusal_does_not_fault_or_start_heartbeat(self):
        client = self.client(self.receipt)
        result = client.acquire_capability('a'*32, 10000, request_id='b'*32)
        self.assertEqual(result, self.receipt); self.assertIsNone(client._capability_fault)
        self.assertIsNone(client._capability_owner); self.assertIsNone(client._capability_thread)
    def test_client_generic_malformed_and_timeout_keep_fault(self):
        for kind in ('old', 'malformed', 'timeout'):
            result = deepcopy(self.receipt)
            if kind == 'old': result.pop('acquisition_refusal')
            elif kind == 'malformed': result['acquisition_refusal']['command_sha256'] = '0'*64
            else: result = {'request_id': 'b'*32, 'status': 'pending'}
            client = self.client(result)
            with self.assertRaises(ValueError): client.acquire_capability('a'*32, 10000, request_id='b'*32)
            self.assertIsNotNone(client._capability_fault); self.assertIsNone(client._capability_owner)
    def test_wrapper_wrong_original_id_rejected(self):
        root = Path(self.temp.name); (root/'results').mkdir()
        wrapped = deepcopy(self.dog.completed[-1]); wrapped['intent_id'] = 'wrong'
        (root/'results'/('b'*32+'.json')).write_text(json.dumps(wrapped))
        with self.assertRaises(ValueError): IntentClient(root).result('b'*32)
    def test_runtime_revalidates_and_archives_exact_refusal(self):
        for corrupt in (False, True):
            with self.subTest(corrupt=corrupt), tempfile.TemporaryDirectory() as root:
                client = SimpleNamespace(close_capability=lambda:None)
                runtime = Runtime(client, root)
                runtime._session_id = self.dog.session_id; runtime._owner = 'a'*32
                record = runtime._reserve('capability_acquire', deepcopy(self.command))
                result = deepcopy(self.receipt); result['request_id'] = record['request_id']
                result['acquisition_refusal']['request_id'] = record['request_id']
                if corrupt: result['acquisition_refusal']['lease_installed'] = True
                client.acquire_capability = lambda *a,**kw: result
                with self.assertRaises(SkillError) as caught: runtime._ownership_exchange(record)
                self.assertEqual(caught.exception.status, 'unknown' if corrupt else 'blocked')
                self.assertEqual(runtime.has_unresolved_execution, corrupt)
                if not corrupt:
                    self.assertIn('receipt_ref', record); self.assertEqual(runtime.audit_evidence()['receipts'], 1)
                self.assertFalse(runtime._lease_active); runtime.close()

class MenuEndpoint(ownership.CombatEndpoint):
    def snapshot(self):
        s = super().snapshot(); s['screen_open'] = True
        s['menu'] = {'menu_class': 'InventoryMenu', 'container_id': 0, 'state_id': 0,
            'slots': [], 'carried': {'id': 'minecraft:dirt', 'count': 14, 'empty': False}}
        return s

class RefusalPublicTests(unittest.TestCase):
    until = ownership.ActualGatewayOwnershipTests.until
    def setUp(self):
        with patch.object(ownership, 'CombatEndpoint', MenuEndpoint):
            ownership.ActualGatewayOwnershipTests.setUp(self)
        self.runtime = Runtime(self.client, self.root/'runtime', wait_timeout=2)
        self.backend = OwnerRuntimeBackend(self.runtime)
        self.service = ToolboxService(self.backend, self.root/'jobs')
        self.session_ref = self.backend.describe()['session_ref']
        self.acquire_ids = []
        self.force_stale = True; self.corrupt = False
        original = self.dog.capability_control
        def controlled(rid, command):
            if command.get('op') != 'capability_acquire': return original(rid, command)
            self.acquire_ids.append(rid)
            old = self.dog.observed_at
            if self.force_stale: self.dog.observed_at = self.dog.clock() - .801
            try:
                result = original(rid, command)
                if self.corrupt and 'acquisition_refusal' in self.dog.completed[-1]['result']:
                    self.dog.completed[-1]['result']['acquisition_refusal']['command_sha256'] = '0'*64
                return result
            finally: self.dog.observed_at = old
        self.dog.capability_control = controlled
    def tearDown(self):
        self.service.close(); self.runtime.close()
        ownership.ActualGatewayOwnershipTests.tearDown(self)
    def observe(self, rid):
        return self.service.call('mdc_observe', {'api_version':'mdc.toolbox/1','request_id':rid,
            'session_ref':self.session_ref,'profile':'menu','bounds':{'radius':1}})
    def test_menu_known_refusal_no_phantom_owner_and_separate_fresh_read(self):
        first = self.observe('refused-menu')
        self.assertEqual(first['state'], 'blocked', first)
        self.assertEqual(first['effect_certainty'], 'none_proven')
        self.assertEqual(first['cleanup_certainty'], 'confirmed')
        self.assertIsNone(self.dog.capability_lease); self.assertIsNone(self.client._capability_fault)
        self.assertFalse(self.runtime.has_unresolved_execution); self.assertFalse(self.runtime._lease_active)
        self.assertFalse(self.bridge.posts)
        self.assertEqual(len(self.acquire_ids), 1)
        self.assertTrue(any(e['event']=='ownership_acquisition_refused' for e in first['events']))
        repeated = self.observe('refused-menu')
        self.assertEqual(repeated['job_id'], first['job_id']); self.assertEqual(len(self.acquire_ids), 1)
        self.force_stale = False
        self.until(lambda: self.dog.observed_at is not None and 0 <= self.dog.clock()-self.dog.observed_at < .2)
        second = self.observe('separately-requested-fresh-menu')
        self.assertEqual(second.get('job_state'), 'succeeded', second)
        self.assertEqual(second['cleanup_certainty'], 'confirmed')
        self.assertTrue(second['state']['screen_open']); self.assertEqual(second['state']['menu']['carried']['count'],14)
        self.assertNotEqual(second['job_id'], first['job_id']); self.assertEqual(len(self.acquire_ids),2)
        self.assertEqual(len(set(self.acquire_ids)),2); self.assertFalse(self.bridge.posts)
    def test_malformed_refusal_keeps_unknown_and_blocks_new_work(self):
        self.corrupt = True
        first = self.observe('malformed-menu')
        self.assertEqual(first['state'], 'unknown', first)
        self.assertEqual(first['cleanup_certainty'], 'unknown')
        self.assertIsNotNone(self.client._capability_fault); self.assertTrue(self.runtime.has_unresolved_execution)
        self.assertFalse(self.bridge.posts); self.assertEqual(len(self.acquire_ids),1)
        again = self.observe('different-menu')
        self.assertIn('error',again); self.assertEqual(len(self.acquire_ids),1)

if __name__ == '__main__': unittest.main()
