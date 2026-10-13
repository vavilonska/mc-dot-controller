"""Root/coordination boundaries using real Resident and synthetic native reads."""
from copy import deepcopy
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
for directory in ('multiagent-coordination', 'multiagent-coordination/tests', 'defense-watchdog'):
    sys.path.insert(0, str(ROOT / directory))
from test_resident_owner_chain import NativeFixture
from test_runtime_timing_merge import TimedNative
from resident_controller.controller import Resident, Running
from resident_controller.coordination_contract import digest_command, native_action_id
from resident_controller.ipc import QueueClient
from resident_controller.transport import BridgeError
import test_navigation_snapshot as snapshot_tests
from test_navigation_binding_producers import state


class ResidentCoordinationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.native = NativeFixture()
        self.resident = Resident(self.native, self.tmp.name)
        self.resident.start()
        self.addCleanup(self.resident.lock.close)
        self.client = QueueClient(self.tmp.name)
        self.sequence = 0

    def command(self):
        self.sequence += 1
        r = self.resident
        state = self.native.state()
        request = 'coord-' + str(self.sequence)
        now = time.monotonic()
        command = dict(op='action', action='follow_path', timeout_ms=1000,
            request_id=request, session_id=r.session_id, submitted_at=time.time(),
            waypoints=[dict(x=1.5, y=64, z=.5)],
            expected_world_generation=state['world']['world_generation'],
            expected_action_session=r.bridge_identity['action_session'],
            expected_player_uuid=state['player']['uuid'], expected_navigation_epoch=1,
            expected_origin=dict(x=.5,y=64,z=.5),
            coordination_step=dict(schema_version=1, source_tick=20, source_nano='-123'))
        command['_coordination'] = dict(schema_version=1, owner_session='owner',
            resident_session=r.session_id, run_id='run', process_id=123,
            action_session=r.bridge_identity['action_session'],
            world_generation=command['expected_world_generation'], player_uuid=command['expected_player_uuid'],
            dimension='minecraft:overworld', navigation_epoch=1, defense_epoch=0,
            origin=command['expected_origin'], source_id='source', source_tick=20, source_nano='-123',
            captured_mono=now, expires_mono=now+.5, request_id=request,
            native_action_id=native_action_id(r.session_id,request), command_sha256=digest_command(command))
        return command

    def execute(self, command):
        try:
            self.resident.command(command)
        except (BridgeError, ValueError, KeyError, TypeError) as exc:
            self.resident.command_error(command, exc)
        return self.client.result(command['request_id'])

    def start(self):
        command=self.command();self.execute(command);self.resident.advance()
        self.assertIsNotNone(self.resident.active)
        self.assertEqual(len(self.posts('/control/action')),1)
        return command

    def exact(self, original, op):
        return dict(op=op,request_id=op+'-'+str(self.sequence),session_id=self.resident.session_id,
            submitted_at=time.time(),expected_resident_session=self.resident.session_id,
            expected_request_id=original['request_id'],expected_action_id=original['_coordination']['native_action_id'],
            expected_action_session=original['_coordination']['action_session'])

    def posts(self, path=None):
        return [c for c in self.native.calls if c[0]=='POST' and (path is None or c[1]==path)]

    def test_idle_admits_exact_self_running_and_preserves_native_body(self):
        command=self.start()
        body=self.posts()[0][2]
        self.assertNotIn('_coordination',body)
        self.assertEqual(body['coordination_step'],command['coordination_step'])
        self.assertEqual(body['expected_origin'],command['expected_origin'])
        self.native.finish();self.resident.active.wake_at=0
        self.resident.advance();self.resident.advance()
        self.assertEqual(self.client.result(command['request_id'])['status'],'succeeded')
        self.assertEqual(len(self.posts()),1)

    def test_admission_rejects_foreign_owners_without_cleanup(self):
        for owner in ('active','pending','aim','combat','handoff','release','malformed'):
            with self.subTest(owner=owner):
                command=self.command();r=self.resident
                foreign=dict(op='action',request_id='foreign',action='follow_path',body={'preserve':True})
                r.active=Running(foreign, iter(())) if owner=='active' else None
                r.pending.clear()
                if owner=='pending':r.pending.append(foreign)
                r.aim.active=owner=='aim';r.combat.active=owner=='combat'
                r.paused=owner in ('handoff','release')
                r.reason='input_release_unconfirmed' if owner=='release' else 'encounter_requires_handoff' if owner=='handoff' else None
                original=r.coordination_context()
                with patch.object(r,'observation_policy',return_value={}) if owner=='malformed' else patch.object(r,'publish',wraps=r.publish):
                    result=self.execute(command)
                self.assertEqual(result['status'],'failed')
                self.assertEqual(r.coordination_context(),original)
                self.assertFalse(self.posts())
                self.assertIs(result['coordination_admission']['admitted'],False)
        r.active=None;r.pending.clear();r.aim.active=False;r.combat.active=False;r.paused=False;r.reason=None

    def test_launch_read_foreign_pending_is_preserved(self):
        command=self.command();self.execute(command)
        request=self.native.request
        foreign=dict(op='action',request_id='foreign',action='break_block')
        def changed(method,path,body=None):
            result=request(method,path,body)
            if path=='/control/status':self.resident.pending.append(foreign)
            return result
        self.native.request=changed;self.resident.advance()
        self.assertEqual(list(self.resident.pending),[foreign]);self.assertIsNone(self.resident.active)
        self.assertFalse(self.posts());self.assertEqual(self.client.result(command['request_id'])['status'],'failed')

    def test_before_post_foreign_pending_is_preserved(self):
        command=self.command();foreign=dict(op='action',request_id='foreign',action='break_block')
        def recipe():
            self.resident.pending.append(foreign)
            yield dict(step='action',body={k:v for k,v in command.items() if k not in ('_coordination','op','request_id','session_id','submitted_at')})
        self.resident.active=Running(command,recipe())
        self.resident.advance()
        self.assertEqual(list(self.resident.pending),[foreign]);self.assertIsNone(self.resident.active)
        self.assertFalse(self.posts())

    def test_unknown_cancel_then_failed_or_running_get_never_reposts(self):
        command=self.start();self.native.lose_cancel=True
        result=self.execute(self.exact(command,'coordination_cancel'))
        self.assertEqual(result['status'],'uncertain')
        self.assertEqual(self.resident.reason,'input_release_unconfirmed')
        task=self.resident.active;before=deepcopy(task.command);request=self.native.request
        for failure in (False,True,False):
            def read(method,path,body=None):
                if failure and path.startswith('/control/action/status?action_id='):
                    raise BridgeError('offline_read_failure',uncertain=True)
                return request(method,path,body)
            self.native.request=read;task.wake_at=0;self.resident.advance()
        self.assertEqual(len(self.posts('/control/action/cancel')),1)
        self.assertEqual(len(self.posts('/control/action')),1)
        self.assertEqual(task.command,before);self.assertEqual(task.action_id,command['_coordination']['native_action_id'])
        self.assertEqual(self.resident.reason,'input_release_unconfirmed')

    def test_release_false_missing_and_malformed_terminal_stay_blocked(self):
        for kind in ('false','missing','wrong-world','wrong-kind','wrong-marker'):
            with self.subTest(kind=kind):
                # A distinct Resident avoids sharing any action authority.
                if self.resident.active:self.resident.active=None
                self.resident.paused=False;self.resident.reason=None;self.native.calls.clear()
                command=self.start();request=self.native.request
                def cancel(method,path,body=None):
                    out=request(method,path,body)
                    if method=='POST' and path=='/control/action/cancel':
                        if kind=='false':out['result']['input_release_confirmed']=False
                        if kind=='missing':out['result'].pop('input_release_confirmed')
                        if kind=='wrong-world':out['result']['world_generation']='foreign'
                        if kind=='wrong-kind':out['action']='place_block'
                        if kind=='wrong-marker':out['result']['coordination_step_schema_version']=True
                    return out
                self.native.request=cancel
                result=self.execute(self.exact(command,'coordination_cancel'))
                self.assertEqual(result['status'],'uncertain');self.assertEqual(self.resident.reason,'input_release_unconfirmed')
                self.assertEqual(len(self.posts('/control/action/cancel')),1)
                self.native.request=request

    def test_auto_cancel_then_exact_cancel_is_read_only_and_retains_original_result(self):
        self.native.lose_action=True;self.native.lose_cancel=True;command=self.start()
        old=self.client.result(command['request_id'])
        self.assertEqual(old['status'],'uncertain')
        self.execute(self.exact(command,'coordination_cancel'))
        self.assertEqual(len(self.posts('/control/action/cancel')),1)
        self.assertEqual(self.client.result(command['request_id']),old)

    def test_pending_cancel_and_wrong_ids_never_post(self):
        command=self.command();self.execute(command)
        wrong=self.exact(command,'coordination_cancel');wrong['expected_action_id']='foreign'
        self.assertEqual(self.execute(wrong)['status'],'failed')
        self.assertEqual(len(self.resident.pending),1)
        valid=self.exact(command,'coordination_cancel');valid['request_id']='valid-cancel'
        result=self.execute(valid)
        self.assertEqual(result['status'],'succeeded');self.assertFalse(self.resident.pending)
        self.assertEqual(self.client.result(command['request_id'])['status'],'cancelled')
        self.assertFalse(self.posts())

    def test_exact_reads_preserve_new_owners_policy_and_prior_terminal(self):
        command=self.start();task=self.resident.active
        task.wake_at=time.monotonic()+100
        original_request=self.native.request
        for op in ('coordination_status','coordination_cancel'):
            for change in ('identity','active','pending','aim','combat','handoff','release'):
                for failed in (False,True):
                    with self.subTest(op=op,change=change,failed=failed):
                        r=self.resident;r.active=task;r.pending.clear();r.aim.active=False;r.combat.active=False;r.paused=False;r.reason=None
                        task.last_action_result={'preserve':'receipt'}
                        def changed(method,path,body=None):
                            out=original_request(method,path,body)
                            if path=='/control/status':
                                if change=='identity':out['process_id']=999
                                if change=='active':r.active=Running({'request_id':'foreign','body':{'exact':1}},iter(()))
                                if change=='pending':r.pending.append({'request_id':'foreign','body':{'exact':1}})
                                if change=='aim':r.aim.active=True
                                if change=='combat':r.combat.active=True
                                if change in ('handoff','release'):
                                    r.paused=True;r.reason='input_release_unconfirmed' if change=='release' else 'encounter_requires_handoff'
                                if failed:raise BridgeError('read_failed',uncertain=True)
                            return out
                        self.native.request=changed
                        result=self.execute(self.exact(command,op))
                        self.assertIn(result['status'],('failed','uncertain'))
                        self.assertEqual(task.last_action_result,{'preserve':'receipt'})
                        self.assertEqual(len(self.posts()),1)
                        if change=='active':self.assertEqual(r.active.command['request_id'],'foreign')
                        if change=='pending':self.assertEqual(r.pending[0]['request_id'],'foreign')
                        if change=='aim':self.assertTrue(r.aim.active)
                        if change=='combat':self.assertTrue(r.combat.active)
                        if change in ('release','handoff'):self.assertTrue(r.paused)
        self.native.request=original_request

    def test_409_definite_and_uncertain_keep_root_admission_provenance(self):
        for uncertain in (False,True):
            with self.subTest(uncertain=uncertain):
                self.resident.active=None;self.resident.paused=False;self.resident.reason=None;self.native.calls.clear()
                command=self.command();request=self.native.request
                def reject(method,path,body=None):
                    if method=='POST' and path=='/control/action':
                        if uncertain:request(method,path,body)
                        else:self.native.calls.append((method,path,deepcopy(body)))
                        raise BridgeError('navigation_origin_changed',status=409,uncertain=uncertain)
                    return request(method,path,body)
                self.native.request=reject;self.execute(command);self.resident.advance()
                result=self.client.result(command['request_id'])
                self.assertEqual(result['status'],'uncertain' if uncertain else 'failed')
                self.assertEqual('coordination_admission' in result,not uncertain)
                self.assertEqual('action_admission' in result,not uncertain)
                if not uncertain:self.assertTrue(self.resident.cache.native_binding.seen)
                self.native.request=request

    def test_original_expiry_no_effect_does_not_clear_current_handoff(self):
        command=self.command();command['_coordination']['expires_mono']=time.monotonic()-1
        self.resident.paused=True;self.resident.reason='encounter_requires_handoff'
        result=self.execute(command)
        self.assertEqual(result['status'],'failed');self.assertTrue(result['resident_policy']['requires_handoff'])
        self.assertEqual(self.resident.reason,'encounter_requires_handoff');self.assertFalse(self.posts())

    def test_status_second_read_and_cancel_post_races_preserve_new_policy(self):
        command=self.start();task=self.resident.active;request=self.native.request
        for op in ('coordination_status','coordination_cancel'):
            for failed in (False,True):
                for reason in ('encounter_requires_handoff','input_release_unconfirmed'):
                    with self.subTest(op=op,failed=failed,reason=reason):
                        self.resident.paused=False;self.resident.reason=None
                        task.coordination_cancel_attempted=False;task.coordination_unknown=False
                        self.native.action['status']='running'
                        self.native.action['result']['input_release_confirmed']=False
                        task.last_action_result={'old':'receipt'}
                        def raced(method,path,body=None):
                            result=request(method,path,body)
                            if path.startswith('/control/action/status?action_id=') or path=='/control/action/cancel':
                                self.resident.paused=True;self.resident.reason=reason
                                self.resident.pending.append({'request_id':'new-owner','body':{'preserve':True}})
                                if failed:raise BridgeError('response_lost',uncertain=True)
                            return result
                        self.native.request=raced
                        result=self.execute(self.exact(command,op))
                        self.assertIn(result['status'],('failed','uncertain'))
                        self.assertEqual(self.resident.reason,reason)
                        self.assertIs(self.resident.active,task)
                        self.assertEqual(self.resident.pending[-1]['request_id'],'new-owner')
                        self.assertEqual(task.last_action_result,{'old':'receipt'})
                        self.resident.pending.clear()
        self.assertFalse(self.posts('/control/release-all'))

    def test_new_owner_during_lost_action_response_prevents_automatic_cancel(self):
        command=self.command();request=self.native.request
        foreign={'request_id':'foreign','body':{'keep':True}}
        def lost(method,path,body=None):
            result=request(method,path,body)
            if method=='POST' and path=='/control/action':
                self.resident.pending.append(foreign)
                self.resident.paused=True;self.resident.reason='encounter_requires_handoff'
                raise BridgeError('lost_response_after_owner_change',uncertain=True)
            return result
        self.native.request=lost;self.execute(command);self.resident.advance()
        self.assertEqual(list(self.resident.pending),[foreign]);self.assertEqual(self.resident.reason,'encounter_requires_handoff')
        self.assertEqual(len(self.posts()),1)

    def test_foreign_native_running_owner_and_wrong_session_reject_exact_cancel(self):
        command=self.start();native_action=deepcopy(self.native.action)
        self.native.action['action_id']='foreign'
        result=self.execute(self.exact(command,'coordination_cancel'))
        self.assertEqual(result['status'],'failed');self.assertEqual(len(self.posts()),1)
        self.native.action=native_action
        exact=self.exact(command,'coordination_cancel');exact['expected_action_session']='foreign'
        self.assertEqual(self.execute(exact)['status'],'failed');self.assertEqual(len(self.posts()),1)

    def test_cancel_terminal_race_keeps_success_and_does_not_replay(self):
        command=self.start();self.native.finish();request=self.native.request
        def terminal(method,path,body=None):
            if method=='POST' and path=='/control/action/cancel':
                self.native.calls.append((method,path,deepcopy(body)));return deepcopy(self.native.action)
            return request(method,path,body)
        self.native.request=terminal
        self.assertEqual(self.execute(self.exact(command,'coordination_cancel'))['status'],'succeeded')
        self.assertEqual(self.client.result(command['request_id'])['status'],'succeeded')
        self.assertIsNone(self.resident.active);self.assertEqual(len(self.posts()),2)

    def test_native_terminal_handoff_and_release_precedence_stay_current(self):
        for released in (True,False):
            self.resident.active=None;self.resident.paused=False;self.resident.reason=None;self.native.calls.clear()
            command=self.start();self.native.finish()
            self.native.action.update(status='cancelled',reason='position_discontinuity_rebind_required')
            self.native.action['result'].update(input_release_confirmed=released,combat={'encounter':{}})
            self.resident.active.wake_at=0;self.resident.advance()
            self.assertTrue(self.resident.paused)
            self.assertEqual(self.resident.reason,'encounter_requires_handoff' if released else 'input_release_unconfirmed')

    def test_immediate_terminal_is_retained_without_extra_status_or_cancel(self):
        command=self.command();request=self.native.request
        def immediate(method,path,body=None):
            out=request(method,path,body)
            if method=='POST' and path=='/control/action':
                self.native.finish();return deepcopy(self.native.action)
            return out
        self.native.request=immediate;self.execute(command);self.resident.advance()
        task=self.resident.active;task.wake_at=0;self.resident.advance();self.resident.advance()
        self.assertEqual(self.client.result(command['request_id'])['status'],'succeeded')
        self.assertFalse([c for c in self.native.calls if c[1].startswith('/control/action/status?action_id=')])
        self.assertEqual(len(self.posts()),1)

    def test_post_action_observation_failure_retains_known_terminal_without_no_effect(self):
        command=self.start();self.native.finish();request=self.native.request
        terminal=deepcopy(self.native.action)
        def lost_state(method,path,body=None):
            if path.startswith('/control/state?'):
                raise BridgeError('postcondition_read_failed')
            return request(method,path,body)
        self.native.request=lost_state;self.resident.active.wake_at=0;self.resident.advance()
        result=self.client.result(command['request_id'])
        self.assertEqual(result['status'],'failed')
        self.assertEqual(result['action'],terminal)
        self.assertEqual(result['resolved_action'],terminal)
        self.assertNotIn('coordination_admission',result)
        self.assertNotIn('action_admission',result)
        self.assertFalse(result['resident_policy']['input_release_unconfirmed'])
        self.assertEqual(len(self.posts()),1)

    def test_native_unknown_flags_are_strict_and_preserve_raw_without_second_cancel(self):
        for key in ('unknown_outcome','uncertain','post_uncertain'):
            for value in (None,1,True,0):
                with self.subTest(key=key,value=value):
                    self.resident.active=None;self.resident.paused=False;self.resident.reason=None
                    self.native.calls.clear()
                    command=self.start();task=self.resident.active
                    trusted=deepcopy(task.last_action_result)
                    self.native.finish();self.native.action[key]=value
                    raw=deepcopy(self.native.action)
                    task.wake_at=0;self.resident.advance()
                    result=self.client.result(command['request_id'])
                    self.assertEqual(result['status'],'uncertain')
                    self.assertEqual(result['unconfirmed_action'],raw)
                    self.assertEqual(result['action'],trusted)
                    self.assertIsNone(result['resolved_action'])
                    self.assertIs(self.resident.active,task)
                    self.assertTrue(self.resident.observation_policy()['input_release_unconfirmed'])
                    for _ in range(3):
                        task.wake_at=0;self.resident.advance()
                    self.execute(self.exact(command,'coordination_cancel'))
                    self.assertEqual(self.client.result(command['request_id']),result)
                    self.assertEqual(len(self.posts('/control/action')),1)
                    self.assertEqual(len(self.posts('/control/action/cancel')),1)

    def test_explicit_false_native_flags_allow_original_success(self):
        command=self.start();self.native.finish()
        self.native.action.update(unknown_outcome=False,uncertain=False,post_uncertain=False)
        self.resident.active.wake_at=0;self.resident.advance();self.resident.advance()
        result=self.client.result(command['request_id'])
        self.assertEqual(result['status'],'succeeded')
        self.assertIsNone(self.resident.active)
        self.assertFalse(self.resident.observation_policy()['input_release_unconfirmed'])
        self.assertEqual(len(self.posts()),1)

    def test_unknown_post_metadata_is_original_read_only_copy(self):
        self.native.lose_action=True;self.native.lose_cancel=True
        request=self.native.request
        def metadata(method,path,body=None):
            self.native.last_response_metadata={'route':path,'opaque':['original']}
            return request(method,path,body)
        self.native.request=metadata;command=self.start()
        result=self.client.result(command['request_id'])
        self.assertEqual(result['status'],'uncertain')
        diagnostic=result['action_request_diagnostics']
        self.assertTrue(diagnostic['diagnostics_only'])
        self.assertEqual(diagnostic['post_action']['response_metadata'],
                         {'route':'/control/action','opaque':['original']})
        self.native.last_response_metadata['opaque'].append('later')
        self.resident.active.wake_at=0;self.resident.advance()
        self.assertEqual(self.client.result(command['request_id']),result)
        self.assertEqual([p[1] for p in self.posts()],['/control/action','/control/action/cancel'])

    def test_current_release_reason_precedes_payload_in_poll_and_exact_cancel(self):
        cases=(('failed','input_release_unconfirmed',True),
               ('failed','position_discontinuity_rebind_required',True),
               ('cancelled','position_discontinuity_rebind_required',False),
               ('succeeded','completed',False))
        request=self.native.request
        for operation in ('poll','coordination_cancel'):
            for status,reason,blocked in cases:
                with self.subTest(operation=operation,status=status,reason=reason):
                    self.resident.active=None;self.resident.paused=False;self.resident.reason=None
                    self.native.calls.clear();self.native.request=request
                    command=self.start();task=self.resident.active
                    self.native.finish();self.native.action.update(status=status,reason=reason)
                    raw=deepcopy(self.native.action)
                    if operation=='coordination_cancel':
                        def terminal(method,path,body=None):
                            if method=='POST' and path=='/control/action/cancel':
                                self.native.calls.append((method,path,deepcopy(body)))
                                return deepcopy(raw)
                            return request(method,path,body)
                        self.native.request=terminal
                        result=self.execute(self.exact(command,operation))
                        self.assertEqual(result['status'],'uncertain' if blocked else 'succeeded')
                        self.assertEqual(result['unconfirmed_action'] if blocked else result['result'],raw)
                    else:
                        task.wake_at=0;self.resident.advance();self.resident.advance()
                        result=self.client.result(command['request_id'])
                        receipt=result.get('action') or result.get('result',{}).get('action')
                        self.assertEqual(receipt,raw)
                    self.assertEqual(self.resident.observation_policy()['input_release_unconfirmed'],blocked)
                    if blocked:self.assertEqual(self.resident.reason,'input_release_unconfirmed')
                    self.assertEqual(len(self.posts()),2 if operation=='coordination_cancel' else 1)
        self.native.request=request

    def test_automatic_cancel_release_reason_cannot_clear_owner(self):
        request=self.native.request
        for status,reason,blocked in (('failed','input_release_unconfirmed',True),
                ('failed','position_discontinuity_rebind_required',True),
                ('cancelled','position_discontinuity_rebind_required',False)):
            with self.subTest(status=status,reason=reason):
                self.resident.active=None;self.resident.paused=False;self.resident.reason=None
                self.native.calls.clear();command=self.command()
                def terminal(method,path,body=None):
                    out=request(method,path,body)
                    if method=='POST' and path=='/control/action':
                        raise BridgeError('lost_action_ack',uncertain=True)
                    if method=='POST' and path=='/control/action/cancel':
                        out.update(status=status,reason=reason)
                        out['result']['input_release_confirmed']=True
                    return out
                self.native.request=terminal;self.execute(command);self.resident.advance()
                result=self.client.result(command['request_id'])
                self.assertEqual(result['status'],'uncertain')
                self.assertEqual(result['resolved_action']['reason'],reason)
                self.assertEqual(result['resolved_action']['result']['input_release_confirmed'],True)
                self.assertEqual(self.resident.observation_policy()['input_release_unconfirmed'],blocked)
                self.assertEqual(self.resident.active is not None,blocked)
                self.assertEqual([p[1] for p in self.posts()],['/control/action','/control/action/cancel'])
        self.native.request=request

    def test_observation_historical_release_reason_does_not_latch_current_policy(self):
        self.native.action.update(status='failed',reason='input_release_unconfirmed',
                                  result={'input_release_confirmed':True})
        result=self.resident.snapshot({'coordination_step':True})
        self.assertEqual(result['action']['reason'],'input_release_unconfirmed')
        self.assertFalse(result['resident_policy']['input_release_unconfirmed'])
        self.assertFalse(self.resident.paused)
        self.assertIsNone(self.resident.reason)
        self.assertFalse(self.posts())


class CoordinationSnapshotTests(snapshot_tests.NavigationSnapshotTests):
    def resident(self, states):
        resident,bridge=super().resident(states)
        original=resident.snapshot
        resident.snapshot=lambda command:original({**command,'coordination_step':True})
        return resident,bridge

    def test_invalid_final_guard_never_publishes_coordination_capture(self):
        resident,_bridge=self.resident([state(),state(),state(navigation_guard={'schema_version':True})])
        with self.assertRaises(ValueError):
            resident.snapshot({'terrain':True,'radius':1,'vertical':2})
        self.assertIsNone(resident.cache.grid)
        self.assertIsNone(resident.cache.state_capture)
        self.assertFalse((resident.root/'observation.json').exists())

    def test_same_c_metadata_survives_later_frame_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            native=TimedNative();r=Resident(native,tmp);r.start()
            self.addCleanup(r.lock.close);request=native.request
            def frame(method,path,body=None):
                if path=='/control/frame':
                    native.last_response_metadata={'path':path};return b'frame'
                return request(method,path,body)
            native.request=frame
            out=r.snapshot({'terrain':True,'radius':1,'vertical':2,'coordination_step':True,'frame':True})
            self.assertIn('/control/state?',out['state_read_diagnostics']['response_metadata']['path'])
            self.assertEqual(out['coordination_capture']['started_mono'],out['state_read_diagnostics']['started_monotonic'])
            self.assertEqual(len([c for c in native.calls if c[1].startswith('/control/state?')]),3)


class CoordinationTerrainAndTransportTests(unittest.TestCase):
    def test_opt_in_page_reversal_is_nonrefreshable(self):
        from resident_controller.world import WorldCache
        from navigation_controller.fake import FakeClock, FakeWorld
        from navigation_controller.terrain import TerrainError
        from test_terrain_recovery import ScriptedBridge
        for prior_stale in (False,True):
            with self.subTest(prior_stale=prior_stale):
                clock=FakeClock();cache=WorldCache()
                def reversed_pages(bridge):
                    tick=100+int(round((bridge.clock.now-100)*20))
                    pages=FakeWorld().pages(radius=3,limit=64,tick=tick,tick_per_page=1)
                    pages[2]['game_time']=pages[2]['response_game_time']=tick
                    return pages
                scripts=([FakeWorld().pages(radius=3,tick=99)] if prior_stale else [])+[reversed_pages]
                bridge=ScriptedBridge(clock,scripts)
                with patch('time.monotonic',clock.monotonic),patch('time.sleep',clock.sleep):
                    with self.assertRaisesRegex(TerrainError,'tick'):
                        cache.scan(bridge,radius=3,vertical=2,coordination=True)
                self.assertEqual(bridge.scan_count,2 if prior_stale else 1)
                self.assertIsNone(cache.grid);self.assertEqual(cache.terrain_read['outcome'],'failed')
                self.assertFalse([c for c in bridge.calls if c[0]=='POST'])

    def test_sample_headers_diagnostic_only_and_do_not_leak_to_next_response(self):
        from resident_controller.transport import Bridge,read_sample_timing
        from test_server_timing import Response
        headers={'X-MDC-Sample-Timing-Version':'1','X-MDC-Sample-Point':'state_world_game_time_read',
                 'X-MDC-Sample-Game-Time':'20','X-MDC-Sample-Nano-Time':'-123'}
        sample=read_sample_timing(Response(headers))
        self.assertTrue(sample['diagnostics_only']);self.assertEqual(sample['nano_time'],-123)
        responses=[headers,{}]
        class NativeResponse(Response):
            status=200
            def read(self,limit):return b'{"coordination_step":{"source_nano":"-999"}}'
        class Connection:
            def __init__(self,*a,**k):pass
            def request(self,*a,**k):pass
            def getresponse(self):return NativeResponse(responses.pop(0))
            def close(self):pass
        bridge=Bridge('http://127.0.0.1:12345','synthetic')
        with patch('resident_controller.transport.http.client.HTTPConnection',Connection):
            out=bridge.request('GET','/control/state?coordination_step=1')
            self.assertEqual(out['coordination_step']['source_nano'],'-999')
            self.assertEqual(bridge.last_response_metadata['sample_timing']['nano_time'],-123)
            bridge.request('GET','/control/state')
        self.assertNotIn('sample_timing',bridge.last_response_metadata)
        for bad in ('NaN',str(2**63),str(-2**63-1)):
            self.assertEqual(read_sample_timing(Response({**headers,'X-MDC-Sample-Nano-Time':bad}))['status'],'invalid_sample_timing')
