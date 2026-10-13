"""Root priority contracts through real Resident, QueueClient and Watchdog.

Only native HTTP is synthetic; all commands use an isolated temporary mailbox.
No production policy, owner, publisher or cancellation code is duplicated here.
"""
from copy import deepcopy
import time
import unittest
from unittest.mock import patch

import test_resident_owner_chain as chain
from test_live_owner import A, R, W, P, Queue, observed
from watchdog import Watchdog
from mdcoord.owner_bridge import WatchdogOwnerBridge
from mdcoord.schema import Rejected


class RootOwnerPolicyTests(unittest.TestCase):
    setUp = chain.ResidentOwnerChainTests.setUp
    tearDown = chain.ResidentOwnerChainTests.tearDown
    capture = chain.ResidentOwnerChainTests.capture
    proposal = chain.ResidentOwnerChainTests.proposal
    start = chain.ResidentOwnerChainTests.start

    def posts(self):
        return [entry for entry in self.native.calls if entry[0] == 'POST']

    def policy(self, *, handoff=False, release=False):
        current = self.q.session()
        current['resident_policy'].update(requires_handoff=handoff, input_release_unconfirmed=release)
        current['updated_at'] = time.time()
        return patch.object(self.q, 'session', return_value=current)

    def test_constructor_requires_current_typed_policy_and_idle_root(self):
        mutations = {
            'release': lambda d, s: s['resident_policy'].update(input_release_unconfirmed=True),
            'handoff': lambda d, s: s['resident_policy'].update(requires_handoff=True),
            'missing': lambda d, s: s.pop('resident_policy'),
            'malformed': lambda d, s: s['resident_policy'].update(requires_handoff=None),
            'stale': lambda d, s: s.update(updated_at=time.time()-4),
            'future': lambda d, s: s.update(updated_at=time.time()+4),
            'pending': lambda d, s: s.update(pending=1, pending_request_ids=['foreign']),
            'active': lambda d, s: s.update(active_request_id='foreign', active_action_id='foreign'),
            'aim': lambda d, s: s['aim_lock'].update(active=True),
            'combat': lambda d, s: s['combat'].update(active=True),
            'combat_held': lambda d, s: s['combat'].update(held_mappings=['forward']),
            'release_latch': lambda d, s: setattr(d, 'input_release_latched', True),
            'handoff_latch': lambda d, s: setattr(d, 'handoff_latched', True),
            'stop': lambda d, s: setattr(d, 'stop_requested', True),
            'stopped': lambda d, s: setattr(d, 'stopped', True),
            'environment': lambda d, s: setattr(d.environment, 'active', {'id': 'environment'}),
            'ranged': lambda d, s: setattr(d, 'ranged_move', {'id': 'ranged'}),
            'recover': lambda d, s: setattr(d, 'recover_observation', True),
            'menu': lambda d, s: setattr(d, 'owner', {'id':'menu','request_id':'menu','menu_recovery':True}),
            'foreign': lambda d, s: setattr(d, 'owner', {'id':'foreign','request_id':'foreign'}),
            'rpc': lambda d, s: setattr(d, 'rpc', {'id':'foreign','kind':'fresh','started':0}),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                queue = Queue(); dog = Watchdog(queue); dog.reason = 'existing_' + name
                mutate(dog, queue.data)
                with self.assertRaises((ValueError, KeyError, TypeError)):
                    WatchdogOwnerBridge(dog)
                self.assertIsNone(getattr(dog, '_coordination_owner', None))
                self.assertEqual(queue.commands, [])
                if name in ('release_latch','handoff_latch','stop','stopped','environment','ranged','recover','menu','foreign'):
                    self.assertEqual(dog.reason, 'existing_' + name)

    def test_first_session_read_failure_is_closed_without_claim(self):
        queue = Queue(); dog = Watchdog(queue)
        with patch.object(queue, 'session', side_effect=OSError('offline_first_read')):
            with self.assertRaises(OSError): WatchdogOwnerBridge(dog)
        self.assertFalse(dog.armed)
        self.assertIsNone(getattr(dog, '_coordination_owner', None))
        self.assertEqual(queue.commands, [])

    def test_all_current_conflicts_block_prepared_dispatch_permanently(self):
        mutations = {
            'release': lambda d, s: s['resident_policy'].update(input_release_unconfirmed=True),
            'handoff': lambda d, s: s['resident_policy'].update(requires_handoff=True),
            'missing': lambda d, s: s.pop('resident_policy'),
            'session': lambda d, s: s.update(session_id='wrong'),
            'process': lambda d, s: s['bridge_identity'].update(process_id=999),
            'stale': lambda d, s: s.update(updated_at=time.time()-4),
            'pending': lambda d, s: s.update(pending=1, pending_request_ids=['foreign']),
            'active': lambda d, s: s.update(active_request_id='foreign',active_action_id='foreign'),
            'combat': lambda d, s: s['combat'].update(active=True),
            'environment': lambda d, s: setattr(d.environment,'active',{'id':'environment'}),
            'ranged': lambda d, s: setattr(d,'ranged_move',{'id':'ranged'}),
            'menu': lambda d, s: setattr(d,'owner',{'id':'menu','request_id':'menu','menu_recovery':True}),
            'recover': lambda d, s: setattr(d,'recover_observation',True),
            'stop': lambda d, s: setattr(d,'stop_requested',True),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                case = chain.ResidentOwnerChainTests('test_actual_completed_scan_and_successful_one_writer_chain')
                case.setUp()
                try:
                    snapshot=case.capture();case.owner.propose(case.proposal(snapshot))
                    current=case.q.session();mutate(case.dog,current)
                    with patch.object(case.q,'session',return_value=current): case.owner.advance()
                    self.assertIsNone(case.owner.active)
                    self.assertEqual(case.owner.result('step')['status'],'rejected')
                    # Restoring Resident clear state never resurrects the consumed proposal.
                    case.owner.advance()
                    self.assertIsNone(case.owner.active)
                    self.assertFalse(any(call[0]=='POST' for call in case.native.calls))
                finally:
                    case.tearDown()

    def test_policy_wall_age_boundary_is_three_seconds_and_not_boolean(self):
        for stamp, accepted in ((97.0,True),(96.999,False),(100.001,False),(True,False),(float('nan'),False)):
            with self.subTest(stamp=stamp):
                queue=Queue();queue.data['updated_at']=stamp;dog=Watchdog(queue)
                with patch('mdcoord.owner_bridge.time.time',return_value=100.0):
                    if accepted:
                        self.assertIs(WatchdogOwnerBridge(dog),dog._coordination_owner)
                    else:
                        with self.assertRaises(Rejected):WatchdogOwnerBridge(dog)
                self.assertEqual(queue.commands,[])

    def test_pre_dispatch_current_release_wins_handoff_with_zero_native_posts(self):
        snapshot = self.capture(); self.owner.propose(self.proposal(snapshot))
        with self.policy(handoff=True, release=True):
            self.owner.advance(); self.dog.tick()
        self.assertEqual(self.posts(), [])
        self.assertTrue(self.dog.input_release_latched)
        self.assertEqual(self.dog.reason, 'owner_input_release_unconfirmed')
        self.assertFalse(self.dog.armed)
        result = deepcopy(self.owner.result('step'))
        self.owner.advance()
        self.assertEqual(self.owner.result('step'), result)
        self.assertEqual(self.posts(), [])

    def blocked_capture(self, *, handoff, release):
        self.bridge.refresh(); self.resident.tick()
        with self.policy(handoff=handoff, release=release): self.dog.tick()
        self.assertTrue(self.bridge.publisher_fault)
        self.assertEqual(self.owner.snapshots.read()['sections'], {})
        self.assertFalse(self.dog.armed)
        self.assertEqual(self.posts(), [])

    def test_completed_capture_checks_current_handoff_before_publication(self):
        self.blocked_capture(handoff=True, release=False)
        self.assertTrue(self.dog.handoff_latched)
        self.assertEqual(self.dog.reason, 'encounter_requires_handoff')

    def test_completed_capture_checks_release_before_handoff(self):
        self.blocked_capture(handoff=True, release=True)
        self.assertTrue(self.dog.input_release_latched)
        self.assertEqual(self.dog.reason, 'owner_input_release_unconfirmed')

    def test_capture_and_dispatch_reject_wrong_or_stale_current_identity(self):
        snapshot = self.capture(); proposal = self.proposal(snapshot)
        for key, value in (('session_id','wrong'),('updated_at',time.time()-4),('resident_policy',{})):
            with self.subTest(key=key):
                current = self.q.session(); current[key] = value
                with patch.object(self.q,'session',return_value=current):
                    with self.assertRaises((ValueError,KeyError,TypeError)): self.bridge.refresh()
                self.assertEqual(self.posts(), [])
        self.owner.propose(proposal)
        self.assertEqual(self.owner.pending['step']['observation_error'], 'sole_owner_not_ready')
        self.owner.advance()
        self.assertEqual(self.owner.result('step')['status'], 'rejected')
        self.assertEqual(self.posts(), [])

    def test_no_effect_only_releases_proposal_and_preserves_current_global_lock(self):
        self.capture(); self.owner.propose(self.proposal(self.owner.snapshots.read())); self.owner.advance()
        with patch('resident_controller.coordination_contract.time.monotonic',return_value=time.monotonic()+2):
            self.resident.tick()
        with self.policy(handoff=True,release=True):
            self.dog.tick(); self.owner.reconcile()
        self.assertIsNone(self.owner.active)
        self.assertFalse(self.owner.recovery_blocked)
        self.assertEqual(self.posts(), [])
        self.assertTrue(self.dog.input_release_latched)
        self.assertEqual(self.dog.reason,'owner_input_release_unconfirmed')
        self.assertFalse(self.dog.armed)

    def test_existing_action_late_success_does_not_clear_handoff_or_release(self):
        active = self.start()
        with self.policy(handoff=True,release=True): self.dog.tick()
        self.native.finish(); self.resident.active.wake_at=0; self.resident.tick(); self.resident.tick()
        with self.policy(handoff=True,release=True):
            self.dog.tick(); self.owner.reconcile()
        self.assertIsNone(self.owner.active)
        self.assertTrue(self.dog.input_release_latched)
        self.assertEqual(self.dog.reason,'owner_input_release_unconfirmed')
        self.assertFalse(self.dog.armed)
        self.assertEqual([post[1] for post in self.posts()], ['/control/action'])

    def test_foreign_owner_during_result_read_is_preserved_and_not_cancelled(self):
        active = self.start(); self.native.finish(); self.resident.active.wake_at=0
        self.resident.tick(); self.resident.tick()
        foreign={'id':'new-menu','request_id':'new-menu','menu_recovery':True}
        original_result=self.q.result
        def read(rid):
            result=original_result(rid)
            self.dog.owner=foreign;self.dog.reason='new-menu-reason';self.dog.recover_observation=True
            return result
        with patch.object(self.q,'result',side_effect=read): self.dog.tick()
        self.assertIs(self.dog.owner,foreign)
        self.assertEqual(self.dog.reason,'new-menu-reason')
        self.owner.cancel_current()
        self.resident.tick()
        self.assertEqual([post[1] for post in self.posts()], ['/control/action'])
        self.assertIs(self.dog.owner,foreign)

    def test_foreign_rpc_during_capture_read_is_never_cleared(self):
        rid = self.bridge.refresh(); self.resident.tick()
        foreign = {'id': 'new-menu-rpc', 'kind': 'menu', 'started': self.dog.clock()}
        original_result = self.q.result
        def read(request_id):
            result = original_result(request_id)
            self.dog.rpc = foreign; self.dog.reason = 'menu-rpc-current'; self.dog.recover_observation = True
            return result
        with patch.object(self.q, 'result', side_effect=read): self.dog.tick()
        self.assertIs(self.dog.rpc, foreign)
        self.assertEqual(self.dog.reason, 'menu-rpc-current')
        self.assertEqual(self.owner.snapshots.read()['sections'], {})
        self.assertEqual(self.posts(), [])

    def test_ongoing_environment_conflict_preserves_original_request_and_reason(self):
        active=self.start(); original=deepcopy(self.posts()[0])
        self.dog.environment.active={'id':'environment'};self.dog.reason='environment-current'
        self.dog.tick();self.owner.cancel_current();self.resident.tick();self.dog.tick();self.owner.reconcile()
        self.assertEqual(self.posts()[0],original)
        self.assertEqual([post[1] for post in self.posts()],['/control/action','/control/action/cancel'])
        self.assertEqual(self.posts()[1][2]['action_id'],active['action_id'])
        self.assertEqual(self.dog.reason,'environment-current')
        self.assertEqual(self.dog.environment.active,{'id':'environment'})

    def test_unknown_capture_timeout_never_retries_or_runs_generic_cleanup(self):
        rid = self.bridge.refresh()
        self.dog.rpc['started'] = self.dog.clock() - 3
        before = deepcopy(self.dog.rpc)
        self.dog.tick(); self.dog.tick()
        self.assertEqual(self.dog.rpc, before)
        self.assertEqual(self.dog.rpc['id'], rid)
        self.assertTrue(self.bridge.interrupted)
        self.assertFalse(self.dog.armed)
        self.assertEqual(self.posts(), [])

    def test_cancel_session_read_race_cannot_cancel_new_foreign_owner(self):
        active = self.start(); before = deepcopy(self.posts())
        current = self.q.session()
        foreign = {'id': 'foreign', 'request_id': 'foreign'}
        def session():
            self.dog.owner = foreign; self.dog.reason = 'foreign-won'
            return deepcopy(current)
        with patch.object(self.q, 'session', side_effect=session):
            self.owner.cancel_current()
        self.resident.tick()
        self.assertIs(self.dog.owner, foreign)
        self.assertEqual(self.dog.reason, 'foreign-won')
        self.assertEqual(self.posts(), before)
        self.assertEqual(self.owner.active['action_id'], active['action_id'])

    def test_exact_result_current_policy_read_race_retains_release_priority(self):
        active = self.start(); self.native.finish(); self.resident.active.wake_at = 0
        self.resident.tick(); self.resident.tick()
        current = self.q.session(); original_result = self.q.result
        def result(rid):
            raw = original_result(rid)
            current['resident_policy'].update(requires_handoff=True, input_release_unconfirmed=True)
            return raw
        with patch.object(self.q, 'result', side_effect=result), patch.object(self.q, 'session', return_value=current):
            self.owner.reconcile()
        self.assertIsNone(self.owner.active)
        self.assertTrue(self.dog.input_release_latched)
        self.assertEqual(self.dog.reason, 'owner_input_release_unconfirmed')
        self.assertEqual(len(self.posts()), 1)

    def test_history_failed_receipt_does_not_relock_explicitly_clear_session(self):
        self.resident.last_action_result={'status':'failed','action_schema_version':1,'action_session':A,
            'action_id':'historic','result':{'input_release_confirmed':False,'requires_handoff':True}}
        # Current typed policy is the authority after an explicit resume.
        current=self.q.session()
        current['resident_policy'].update(requires_handoff=False,input_release_unconfirmed=False)
        with patch.object(self.q,'session',return_value=current):
            self.bridge.refresh()
        self.assertFalse(self.bridge.interrupted)
        self.assertFalse(self.dog.input_release_latched)
        self.assertFalse(self.dog.handoff_latched)
        self.assertEqual(self.posts(),[])


if __name__ == '__main__': unittest.main()
