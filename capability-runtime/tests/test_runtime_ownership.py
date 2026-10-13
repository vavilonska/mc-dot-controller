"""Core durable ownership controls. Real gateway chaining is covered separately."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from mdc_skills.core import Runtime, SkillError
from support_core import Clock, Client, SESSION, NATIVE, move, arrived


class LeaseClient(Client):
    def __init__(self, clock, journal):
        super().__init__(clock)
        self.epoch = 7
        self.journal = Path(journal) / 'execution.json'
        self.lease = None
        self.controls = []
        self.fault = False
        self.stop_count = 0
        self.context_ready = True
        self.control_patch = lambda value: value
    def session(self):
        result = super().session()
        result.update(capability_lease_schema_version=1, capability_lease=deepcopy(self.lease),
            capability_context={'world_generation':'world-one','dimension':'minecraft:overworld',
                                'player_uuid':'player-one','action_session':NATIVE} if self.context_ready else None)
        return result
    def _check_reserved(self, rid, command):
        data = json.loads(self.journal.read_text())
        assert data['pending'] == rid
        assert data['records'][rid]['command'] == command
        self.controls.append((command, rid))
        if self.fault: raise OSError('ACK lost')
    def acquire_capability(self, owner_id, duration_ms, timeout, *, request_id, expected_context, expected_defense_epoch):
        self._check_reserved(request_id, {'op':'capability_acquire','owner_id':owner_id,'duration_ms':duration_ms,
            'expected_context':expected_context,'expected_defense_epoch':expected_defense_epoch})
        self.lease = {'owner_id':owner_id,'state':'active','context':deepcopy(expected_context),
            'defense_epoch':expected_defense_epoch,'resident_session':SESSION,'remaining_ms':duration_ms,'heartbeat_remaining_ms':3000}
        return self.control_patch({'request_id':request_id,'session_id':SESSION,'queue_request_id':None,
            'status':'succeeded','capability_lease':deepcopy(self.lease)})
    def release_capability(self, owner_id, timeout, *, request_id):
        self._check_reserved(request_id, {'op':'capability_release','owner_id':owner_id,'expected_defense_epoch':self.epoch})
        self.lease = None
        return self.control_patch({'request_id':request_id,'session_id':SESSION,'queue_request_id':None,
            'status':'succeeded','capability_lease':None})
    def close_capability(self): self.stop_count += 1


class RuntimeOwnershipTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.clock = Clock()
        self.client = LeaseClient(self.clock, self.temp.name)
        self.runtime = Runtime(self.client, self.temp.name, clock=self.clock, sleeper=self.clock.sleep)
    def tearDown(self):
        self.runtime.close()
        self.temp.cleanup()
    def test_durable_acquisition_tags_all_reads_and_actions_and_safe_release(self):
        outcome = self.runtime.execute('move', move(), arrived)
        self.assertTrue(outcome.ok, outcome)
        owner = self.runtime._owner
        for command, _ in self.client.calls:
            self.assertEqual(command['_capability_owner_id'], owner)
            self.assertEqual(command['_navigation_defense_epoch'], 7)
        self.runtime.close()
        self.assertTrue(self.runtime.close_outcome.ok)
        self.assertEqual([c['op'] for c,_ in self.client.controls], ['capability_acquire','capability_release'])
        self.assertEqual(self.client.calls[-1][0]['op'], 'observe')
        self.assertEqual(self.client.action_count, 1)
    def test_unknown_acquisition_never_resends_or_releases(self):
        self.client.fault = True
        with self.assertRaises(SkillError): self.runtime.observe()
        rid = self.runtime.pending_request_id
        with self.assertRaises(SkillError): self.runtime.observe()
        self.runtime.close()
        self.assertEqual(self.runtime.pending_request_id, rid)
        self.assertEqual(len(self.client.controls), 1)
        self.assertEqual(self.client.calls, [])
    def test_unready_context_does_not_reserve_or_submit(self):
        self.client.context_ready = False
        with self.assertRaisesRegex(SkillError,'context_not_ready'): self.runtime.observe()
        self.assertIsNone(self.runtime.pending_request_id)
        self.assertFalse(self.client.controls)
    def test_unknown_game_action_stops_heartbeat_without_releasing(self):
        self.client.fail_after_submit = True
        outcome = self.runtime.execute('move', move(), arrived)
        self.assertEqual(outcome.status, 'unknown')
        self.runtime.close()
        self.assertEqual(self.runtime.close_outcome.status, 'unknown')
        self.assertEqual(len(self.client.controls), 1)
        self.assertEqual(self.client.action_count, 1)
    def test_unknown_release_is_journaled_and_never_retried(self):
        self.runtime.observe()
        self.client.fault = True
        self.runtime.close()
        self.assertEqual(self.runtime.close_outcome.status,'unknown')
        self.assertIsNotNone(self.runtime.pending_request_id)
        self.runtime.close()
        self.assertEqual(len(self.client.controls),2)
    def test_expired_ownership_blocks_goal_success_and_old_preflight_action(self):
        before = self.runtime.observe()
        self.client.lease['remaining_ms'] = 0
        with self.assertRaisesRegex(SkillError,'ownership_lost'): self.runtime.result('goal',[before])
        self.assertFalse(self.runtime.execute('move',move(),arrived,before=before).ok)
        self.assertEqual(self.client.action_count,0)
    def test_exact_control_identity_and_uncertainty_required(self):
        self.client.control_patch = lambda r: {**r,'requires_handoff':True}
        with self.assertRaisesRegex(SkillError,'receipt_unconfirmed'): self.runtime.observe()
        self.assertIsNotNone(self.runtime.pending_request_id)
        self.assertFalse(self.runtime.reconcile().ok)
    def test_original_lease_epoch_cannot_be_rebound(self):
        before = self.runtime.observe()
        self.client.epoch += 1
        self.client.lease['defense_epoch'] = self.client.epoch
        self.assertFalse(self.runtime.execute('move',move(),arrived,before=before).ok)
        self.assertEqual(self.client.action_count,0)
    def test_constructor_duration_is_bounded(self):
        with self.assertRaisesRegex(SkillError,'ownership_duration'):
            Runtime(self.client, self.temp.name, capability_duration_seconds=86401)

if __name__ == '__main__': unittest.main()
