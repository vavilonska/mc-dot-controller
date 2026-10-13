"""Actual Python Resident+WorldCache+Watchdog+QueueClient, temporary mailbox only.

The HTTP bridge is synthetic. This proves data/ownership plumbing, not Minecraft
physics, real host inference, HTTP performance, or live acceptance.
"""
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
import uuid

from test_live_owner import ROOT, CONTEXT, W, P, A, observed, cell
from resident_controller.controller import Resident
from resident_controller.ipc import QueueClient
from resident_controller.transport import BridgeError
from watchdog import Watchdog
from mdcoord import Coordinator, Rejected
from mdcoord.owner_bridge import WatchdogOwnerBridge, LiveResidentAdapter
from mdcoord.schema import Context, Grant


class NativeFixture:
    base_url='http://offline.invalid'
    def __init__(self):
        self.calls=[];self.tick=20;self.pos=.5;self.entities=0;self.lose_action=False;self.lose_cancel=False
        self.action={'action_schema_version':1,'action_session':A,'status':'idle','action_id':None}
    def state(self):
        state=observed(tick=self.tick)['result']['state'];state['player']['x']=self.pos
        state['client_action']=deepcopy(self.action)
        state['coordination_step']['entity_count']=self.entities
        if self.entities:
            e=dict(uuid='hostile',entity_id=99,type='minecraft:zombie',alive=True,health=20,distance=1,x=1,y=64,z=1)
            state['nearby'].update(total=1,returned=1,entities=[e])
        return state
    def request(self,method,path,body=None):
        self.calls.append((method,path,deepcopy(body)))
        if path=='/control/status':
            return dict(protocol='mineclient-bridge',schema_version=2,run_id='run',process_id=123,in_world=True,
                        coordination_step_protocol=1,client_action=deepcopy(self.action),world=self.state()['world'])
        if path.startswith('/control/action/status'):return deepcopy(self.action)
        if path.startswith('/control/state?'):
            self.tick+=1;return self.state()
        if path.startswith('/control/terrain?'):
            self.tick+=1
            cells=[cell(x,y,z) for y in range(62,67) for z in range(-1,2) for x in range(-1,2)]
            return dict(ok=True,protocol='mineclient-bridge',schema_version=2,terrain_schema_version=1,
                        world_generation=W,dimension='minecraft:overworld',generation=str(uuid.uuid4()),
                        consistency='live_pages',game_time=self.tick,response_game_time=self.tick,read_only=True,
                        loaded_chunks_only=True,origin=dict(x=0,y=64,z=0),radius=1,vertical=2,order='x_then_z_then_y',
                        total_cells=45,offset=0,next_offset=45,returned=45,complete=True,next_cursor=None,
                        budget_exhausted=False,read_elapsed_micros=1,unknown_cells=0,cells=cells)
        if path=='/control/screen':return dict(ok=True,open=False)
        if path=='/control/action' and method=='POST':
            self.action=dict(action_schema_version=1,action_session=A,action_id=body['action_id'],action=body['action'],
                             status='running',ticks=0,result=dict(world_generation=W,input_release_confirmed=False,
                                                                coordination_step_schema_version=1))
            if self.lose_action:raise BridgeError('offline_lost_action_response',uncertain=True)
            return deepcopy(self.action)
        if path=='/control/action/cancel' and method=='POST':
            assert body.get('expected_action_session')==A
            assert body['action_id']==self.action['action_id']
            if self.lose_cancel:raise BridgeError('offline_lost_cancel_response',uncertain=True)
            self.action['status']='cancelled';self.action['result']['input_release_confirmed']=True
            return deepcopy(self.action)
        raise AssertionError((method,path,body))
    def finish(self):
        self.pos=1.5;self.action['status']='succeeded';self.action['ticks']=5
        self.action['result']['input_release_confirmed']=True


class ResidentOwnerChainTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();root=Path(self.tmp.name)
        self.native=NativeFixture();self.resident=Resident(self.native,root/'queue');self.resident.start()
        self.q=QueueClient(root/'queue');self.dog=Watchdog(self.q)
        self.bridge=WatchdogOwnerBridge(self.dog);self.adapter=LiveResidentAdapter(self.bridge)
        self.owner=Coordinator(root/'journal',executor=self.adapter)
        self.context=Context('minecraft:overworld',W,P,A,self.resident.session_id)
        self.owner.activate(Grant('one',self.context,frozenset({'follow_path'}),(-2,60,-2,3,70,3),max_actions=1,lease_ms=10000))
    def tearDown(self):
        self.owner.close()
        if self.resident.lock:self.resident.lock.close()
        self.tmp.cleanup()
    def capture(self):
        rid=self.bridge.refresh();self.resident.tick();self.dog.tick()
        result=self.q.result(rid)
        self.assertEqual(result['status'],'succeeded',result)
        self.assertFalse(self.bridge.publisher_fault)
        snap=self.owner.snapshots.read()
        self.assertEqual(snap['sections']['player']['source_tick'],result['result']['state']['world']['game_time'])
        self.assertEqual(result['result']['state'],self.resident.cache.state)
        return snap
    def proposal(self,snap):
        lease=self.owner.lease_state()
        value = dict(proposal_id='step',task_id='one',epoch=lease['epoch'],lease_revision=lease['revision'],role='route',
                    context=self.context.wire(),based_on={'terrain':snap['sections']['terrain']['content_revision']},
                    source_samples={n:snap['sections'][n]['sample_id'] for n in ('player','terrain','entities')},ttl_ms=500,
                    intent=dict(kind='follow_path',timeout_ms=1000,waypoints=[dict(x=1.5,y=64,z=.5)]),dependencies=[],priority=10,
                    preconditions=dict(alive=True,grounded=True,screen_closed=True,min_health=5,expected_position=dict(x=.5,y=64,z=.5)),cancel_requested=False)
        source=self.owner.capture_planning_source()
        return self.owner.seal_planning_proposal(value,source['source_id'],self.owner.clock()+.5)
    def start(self):
        s=self.capture();self.owner.propose(self.proposal(s));self.owner.advance()
        a=deepcopy(self.owner.active);self.assertIsNotNone(a,self.owner.result('step'))
        self.resident.tick();return a
    def test_actual_completed_scan_and_successful_one_writer_chain(self):
        a=self.start();posts=[c for c in self.native.calls if c[:2]==('POST','/control/action')]
        self.assertEqual(len(posts),1);body=posts[0][2]
        self.assertEqual(body['action_id'],a['action_id']);self.assertNotIn('_coordination',body)
        self.assertEqual(body['coordination_step']['source_nano'],'-123')
        self.native.finish();self.resident.active.wake_at=0;self.resident.tick();self.resident.tick()
        self.dog.tick();self.owner.advance()
        self.assertEqual(self.owner.result('step')['status'],'succeeded')
        self.assertEqual(len([c for c in self.native.calls if c[0]=='POST']),1)
    def test_exact_cancel_is_only_native_cancel_not_release_all(self):
        a=self.start();self.owner.cancel_current();self.resident.tick();self.dog.tick();self.owner.reconcile()
        self.assertEqual(self.owner.result('step')['status'],'cancelled')
        posts=[c for c in self.native.calls if c[0]=='POST']
        self.assertEqual([c[1] for c in posts],['/control/action','/control/action/cancel'])
        self.assertEqual(posts[-1][2],dict(action_id=a['action_id'],expected_action_session=A))
    def test_unknown_does_not_trigger_legacy_watchdog_cancel_or_combat(self):
        self.native.lose_action=True;self.native.lose_cancel=True;a=self.start()
        self.dog.tick();self.owner.reconcile();self.resident.tick();self.owner.reconcile()
        posts=[c for c in self.native.calls if c[0]=='POST']
        self.assertEqual([c[1] for c in posts],['/control/action','/control/action/cancel'])
        self.assertTrue(self.dog.input_release_latched);self.assertTrue(self.owner.recovery_blocked)
        # The original exact native action eventually terminates; only a read may establish release.
        self.native.action['status']='cancelled';self.native.action['result']['input_release_confirmed']=True
        self.bridge._next_read_at.clear();self.owner.reconcile();self.resident.tick();self.owner.reconcile()
        self.assertFalse(self.owner.recovery_blocked)
        self.assertEqual(len([c for c in self.native.calls if c[0]=='POST']),2)
        self.assertTrue(self.dog.input_release_latched)  # No general input re-arming.
    def test_new_hostile_only_interrupts_opt_in_scope(self):
        self.capture();self.native.entities=1
        self.bridge.refresh();self.resident.tick();self.dog.tick()
        self.assertTrue(self.bridge.interrupted)
        self.assertFalse(any(c[0]=='POST' for c in self.native.calls))
        self.dog.send('start_combat',{'op':'combat_start','target_uuid':'hostile'})
        self.assertFalse(any(c[0]=='POST' for c in self.native.calls))
        self.assertIsNone(self.dog.rpc)
    def test_old_envelope_expiry_at_resident_is_no_effect_evidence(self):
        self.capture();self.owner.propose(self.proposal(self.owner.snapshots.read()));self.owner.advance();a=deepcopy(self.owner.active)
        from unittest.mock import patch
        with patch('resident_controller.coordination_contract.time.monotonic',return_value=time.monotonic()+2):
            self.resident.tick()
        self.dog.tick();self.owner.reconcile()
        self.assertFalse(any(c[0]=='POST' for c in self.native.calls))
        self.assertEqual(self.owner.result('step')['status'],'failed')
        self.assertFalse(self.owner.recovery_blocked)

if __name__=='__main__':unittest.main()

class RuntimeChainTests(unittest.TestCase):
    def test_parallel_advice_then_independent_scan_dispatches_exactly_one_new_step(self):
        from mdcoord.runtime import ControlledStepRuntime
        from mdcoord.planning import PlannerWorker
        from threading import Barrier
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);native=NativeFixture();resident=Resident(native,root/'queue');resident.start()
            dog=Watchdog(QueueClient(root/'queue'))
            context=Context('minecraft:overworld',W,P,A,resident.session_id)
            grant=Grant('one',context,frozenset({'follow_path'}),(-2,60,-2,3,70,3),max_actions=1,lease_ms=10000)
            calls=[]
            # This scenario asserts both callbacks entered. Production may cancel
            # an alternative still queued after the first result, so make the
            # test's two-callback setup explicit before either can return.
            callbacks_entered=Barrier(2, timeout=.5)
            def compute(request):
                value=request.wire();calls.append(value['snapshot']['sections']['player']['sample_id'])
                callbacks_entered.wait()
                return {'kind':'route_goal','goal':dict(x=1.5,y=64,z=.5),
                        'based_on':{'terrain':value['snapshot']['sections']['terrain']['content_revision']}}
            runtime=ControlledStepRuntime(dog,root/'journal',grant,
                    [PlannerWorker('route_a',compute),PlannerWorker('route_b',compute)],planning_budget_ms=1000)
            try:
                for _ in range(150):
                    resident.tick()
                    if resident.active is not None:
                        native.finish();resident.active.wake_at=0
                    dog.tick();runtime.tick()
                    if runtime.phase in ('complete','blocked'):break
                    time.sleep(.001)
                self.assertEqual(runtime.phase,'complete',runtime.status())
                self.assertEqual(runtime.owner.result(runtime.proposal_id)['status'],'succeeded')
                self.assertEqual(len(calls),2)
                self.assertEqual(len([c for c in native.calls if c[:2]==('POST','/control/action')]),1)
                self.assertEqual(len([c for c in native.calls if c[1].startswith('/control/terrain?')]),2)
                self.assertEqual(len(runtime.owner.records),1)
            finally:
                runtime.scheduler.close();runtime.owner.close()
                if resident.lock:resident.lock.close()

class StopOwnerTests(unittest.TestCase):
    def test_active_and_unknown_stop_progress_exact_owner_without_global_release(self):
        # Exercise the same dog.tick / runtime.tick sequence used by both normal
        # and KeyboardInterrupt loops. A lost action response is never resubmitted.
        from mdcoord.runtime import ControlledStepRuntime
        from mdcoord.planning import PlannerWorker
        for lose in (False,True):
            with self.subTest(unknown=lose),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);native=NativeFixture();native.lose_action=lose
                resident=Resident(native,root/'queue');resident.start();dog=Watchdog(QueueClient(root/'queue'))
                context=Context('minecraft:overworld',W,P,A,resident.session_id)
                def compute(req):
                    s=req.wire()['snapshot']
                    return dict(kind='route_goal',goal=dict(x=1.5,y=64,z=.5),based_on={'terrain':s['sections']['terrain']['content_revision']})
                runtime=ControlledStepRuntime(dog,root/'journal',Grant('stop',context,frozenset({'follow_path'}),
                        (-2,60,-2,3,70,3),max_actions=1,lease_ms=10000),
                        [PlannerWorker('a',compute),PlannerWorker('b',compute)],planning_budget_ms=1000)
                try:
                    for _ in range(150):
                        resident.tick();dog.tick();runtime.tick()
                        if any(c[:2]==('POST','/control/action') for c in native.calls):break
                        time.sleep(.001)
                    self.assertTrue(any(c[:2]==('POST','/control/action') for c in native.calls))
                    dog.stop()
                    for _ in range(100):
                        if resident.active:resident.active.wake_at=0
                        resident.tick();dog.tick();runtime.tick()
                        if dog.stopped:break
                        time.sleep(.003)
                    self.assertTrue(dog.stopped,runtime.status())
                    self.assertIsNone(runtime.owner.active)
                    self.assertEqual(len([c for c in native.calls if c[:2]==('POST','/control/action')]),1)
                    self.assertEqual(len([c for c in native.calls if c[:2]==('POST','/control/action/cancel')]),1)
                    self.assertFalse(any(c[1]=='/control/release-all' for c in native.calls))
                finally:
                    runtime.scheduler.close();runtime.owner.close()
                    if resident.lock:resident.lock.close()
