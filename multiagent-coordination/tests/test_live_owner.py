"""Offline contracts only. No real QueueClient, network, game or existing queue."""
from copy import deepcopy
import hashlib
import sys
from pathlib import Path
import tempfile
import time
import unittest
import uuid
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
for child in ('resident-controller', 'navigation-controller', 'defense-watchdog'):
    sys.path.insert(0, str(ROOT / child))
from mdcoord import Coordinator, Rejected
from mdcoord.executor import Receipt
from mdcoord.owner_bridge import LiveResidentAdapter, WatchdogOwnerBridge
from mdcoord.schema import Context, Grant, canonical
from resident_controller.coordination_contract import envelope, digest_command, native_action_id
from support import Clock

W, P, A, R = [str(uuid.UUID(int=n)) for n in range(1, 5)]
CONTEXT = Context('minecraft:overworld', W, P, A, R)

class Queue:
    def __init__(self):
        self.data = dict(coordination_protocol=1, session_id=R, state='ready', pending=0,
                         active_request_id=None, active_action_id=None, pending_request_ids=[],
                         bridge_identity=dict(run_id='run', process_id=123, action_session=A),
                         updated_at=time.time(), resident_policy=dict(schema_version=1, requires_handoff=False, input_release_unconfirmed=False),
                         aim_lock=dict(active=False), combat=dict(active=False, held_mappings=[]))
        self.commands, self.results = [], {}
        self.lose = False
    def session(self):return deepcopy(self.data)
    def result(self, rid):return deepcopy(self.results.get(rid))
    def submit(self, command, request_id=None):
        self.commands.append((request_id, deepcopy(command)))
        if self.lose:raise TimeoutError('offline_lost_ack')
        return request_id

class Dog:
    def __init__(self, clock):
        self.clock=clock; self.q=Queue(); self.session_id='watchdog'; self.defense_epoch=0
        self.handoff_latched=False; self.recover_observation=False; self.reason='starting'
        self.input_release_latched=False; self.armed=True; self.stopped=False; self.stop_requested=False
        self.phase='watching'; self.rpc=None; self.owner=None
    def submit_owner(self, rid, command, *, queue_request_id=None):
        command=deepcopy(command); expected=command.pop('_navigation_defense_epoch')
        if expected != self.defense_epoch:return False
        self.q.submit(command, request_id=queue_request_id)
        self.owner={'id':rid,'request_id':queue_request_id};return True
    def cancel_coordinated(self, claim, rid, aid, context, cancel_id):
        assert self._coordination_owner is claim
        return self.q.submit({'op':'coordination_cancel','expected_request_id':rid,
                             'expected_action_id':aid,'expected_action_session':context.action_session},request_id=cancel_id)
    def latch_input_release(self, reason):self.input_release_latched=True


def cell(x,y,z):
    air=y>=64
    return dict(x=x,y=y,z=z,status='loaded',known=True,collision_known=True,id_truncated=False,
                fluid_truncated=False,properties_truncated=False,properties={},fluid='minecraft:empty',
                fluid_source=False,hazards=[],hazards_exhaustive=False,id='minecraft:air' if air else 'minecraft:stone',
                air=air,collision_empty=air,full_top_support=not air,collision_bounds=[] if air else [0,0,0,1,1,1])


def observed(rid='capture', tick=10, started=10, finished=10):
    action=dict(action_session=A,status='idle')
    state=dict(world=dict(dimension='minecraft:overworld',world_generation=W,game_time=tick,
                          navigation_guard=dict(schema_version=1,epoch=0,rebind_ready=True,stable_ticks=3,fresh_binding_required=False)),
               player=dict(uuid=P,x=.5,y=64,z=.5,health=20,food=20,alive=True,on_ground=True,
                           inventory=[],inventory_truncated=False),
               screen_open=False,paused=False,client_action=action,
               nearby=dict(radius=8,total=0,returned=0,truncated=False,entities=[]),
               coordination_step=dict(schema_version=1,contract='controlled_single_step_v1',source_tick=tick,
                                      source_nano='-123',world_generation=W,action_session=A,player_uuid=P,
                                      entity_scope='loaded_client_aabb8_excluding_self',entity_count=0,radius=8,singleplayer=True))
    return dict(request_id=rid,session_id=R,status='succeeded',finished_at=100+tick,
                result=dict(state=state,action=action,
                            resident_policy=dict(schema_version=1,requires_handoff=False,input_release_unconfirmed=False),status=dict(run_id='run',process_id=123,
                            coordination_step_protocol=1,client_action=action),
                            coordination_capture=dict(started_mono=started,finished_mono=finished),
                            terrain=dict(complete=True,world_generation=W,capture_started_mono=started,
                                         capture_finished_mono=finished,source_tick=tick,
                                         origin=dict(x=0,y=64,z=0),radius=1,vertical=2,
                                         cells=[cell(x,y,z) for x in range(-1,2) for y in range(62,67) for z in range(-1,2)])))


class LiveOwnerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.clock=Clock();self.clock.now=10
        self.dog=Dog(self.clock);self.bridge=WatchdogOwnerBridge(self.dog)
        self.adapter=LiveResidentAdapter(self.bridge)
        self.owner=Coordinator(self.tmp.name,executor=self.adapter,clock=self.clock)
        self.owner.activate(Grant('live-task',CONTEXT,frozenset({'follow_path'}),(-2,60,-2,3,70,3)))
    def tearDown(self):self.owner.close();self.tmp.cleanup()
    def capture(self,rid='capture',tick=10):
        t=self.adapter.publisher.begin(rid)
        return self.adapter.publisher.complete(t,observed(rid,tick,self.clock(),self.clock()))
    def proposal(self,pid='plan'):
        snap=self.owner.snapshots.read();lease=self.owner.lease_state()
        value = dict(proposal_id=pid,task_id='live-task',epoch=lease['epoch'],lease_revision=lease['revision'],role='route',
                    context=CONTEXT.wire(),based_on={'terrain':snap['sections']['terrain']['content_revision']},ttl_ms=500,
                    source_samples={n:snap['sections'][n]['sample_id'] for n in ('player','terrain','entities')},
                    intent=dict(kind='follow_path',timeout_ms=1000,waypoints=[dict(x=1.5,y=64,z=.5)]),dependencies=[],priority=10,
                    preconditions=dict(alive=True,grounded=True,screen_closed=True,min_health=5,expected_position=dict(x=.5,y=64,z=.5)),cancel_requested=False)
        source=self.owner.capture_planning_source()
        return self.owner.seal_planning_proposal(value,source['source_id'],self.clock()+.5)
    def start(self):
        self.capture();self.owner.propose(self.proposal());self.owner.advance();return deepcopy(self.owner.active)
    def finish(self,active,*,released=True,wrong=False):
        aid=active['action_id'];rid=active['request_id']
        state=observed()['result']['state'];state['player']['x']=1.5
        native=dict(action_schema_version=1,action_id=aid,action_session=A,action='follow_path',status='succeeded',ticks=4,
                    result=dict(world_generation=W,input_release_confirmed=released,coordination_step_schema_version=1))
        state['client_action']=deepcopy(native)
        self.dog.q.results[rid]=dict(request_id='wrong' if wrong else rid,session_id=R,status='succeeded',result=dict(action=native,state=state))
        self.dog.owner=None
    def test_real_shaped_capture_one_writer_fixed_both_ids_and_real_proof(self):
        a=self.start();self.assertIsNotNone(a)
        self.assertEqual(a['action_id'],native_action_id(R,a['request_id']))
        self.assertEqual(len(self.dog.q.commands),1)
        command=self.dog.q.commands[0][1]
        e=envelope(command,now=self.clock());self.assertEqual(e['source_nano'],'-123')
        self.assertEqual(command['coordination_step']['source_tick'],10)
        proof=self.owner.threats.read(next(iter(self.owner.threats._proofs)))
        self.assertEqual(proof['origin'],'native_controlled_single_step')
        self.finish(a);self.owner.advance();self.assertEqual(self.owner.result('plan')['status'],'succeeded')
    def test_missing_release_sticks_and_blocks_next_input(self):
        a=self.start();self.finish(a,released=None);self.owner.advance()
        self.assertTrue(self.dog.input_release_latched);self.assertTrue(self.owner.recovery_blocked)
        self.assertEqual(len(self.dog.q.commands),1)
    def test_wrong_queue_identity_never_unblocks(self):
        a=self.start();self.finish(a,wrong=True);self.owner.advance()
        self.assertTrue(self.owner.recovery_blocked);self.assertEqual(len(self.dog.q.commands),1)
    def test_unknown_post_not_retried(self):
        self.dog.q.lose=True;a=self.start();self.assertTrue(self.owner.recovery_blocked)
        for _ in range(4):self.owner.reconcile()
        self.assertEqual(len(self.dog.q.commands),1)
    def test_old_raw_proposal_cannot_refresh_after_new_capture(self):
        self.capture();p=self.proposal();self.clock.step(.1);self.capture('new',11)
        p['proposal_id']='relabeled';p['ttl_ms']=1000
        with self.assertRaises(Rejected):self.owner.propose(p)
        self.assertEqual(self.dog.q.commands,[])
    def test_defense_epoch_and_process_rollover_block(self):
        for change in ('epoch','process'):
            with self.subTest(change=change):
                if self.owner.pending:self.owner.pending.clear()
                if not self.owner.snapshots.read()['sections']:self.capture()
                p=self.proposal(change);self.owner.propose(p)
                if change=='epoch':self.dog.defense_epoch+=1
                else:self.dog.q.data['bridge_identity']['process_id']=999
                self.owner.advance();self.assertEqual(self.dog.q.commands,[])
    def test_stale_sample_never_dispatches(self):
        self.capture();self.owner.propose(self.proposal());self.clock.step(.6);self.owner.advance()
        self.assertEqual(self.dog.q.commands,[])
    def test_capture_duplicate_or_relabel_does_not_refresh(self):
        self.capture()
        with self.assertRaises(Rejected):self.adapter.publisher.begin('capture')
        t=self.adapter.publisher.begin('relabel')
        with self.assertRaises(Rejected):self.adapter.publisher.complete(t,observed('capture'))
    def test_entity_present_and_unknown_floor_refuse(self):
        t=self.adapter.publisher.begin('hostile');raw=observed('hostile')
        raw['result']['state']['coordination_step']['entity_count']=1
        self.adapter.publisher.complete(t,raw)
        with self.assertRaises(Rejected):self.proposal()
        self.assertEqual(self.dog.q.commands,[])
    def test_one_bridge_cannot_attach_a_second_coordinator_or_bypass_live_seal(self):
        with tempfile.TemporaryDirectory() as another:
            with self.assertRaises(Rejected):
                Coordinator(another,executor=LiveResidentAdapter(self.bridge),clock=self.clock)
        self.capture();p=self.proposal();p.pop('planning_fence')
        with self.assertRaises(Rejected):self.owner.propose(p)
        self.assertEqual(self.dog.q.commands,[])
    def test_handoff_never_means_permission_to_continue_after_release(self):
        a=self.start();self.finish(a)
        self.dog.q.results[a['request_id']]['requires_handoff']=None
        self.owner.advance()
        self.assertEqual(self.owner.result('plan')['status'],'failed')
        self.assertTrue(self.bridge.interrupted)
    def test_planner_port_has_no_owner_operations(self):
        port=self.owner.planner()
        for n in ('advance','cancel_current','refresh','publisher','executor','activate'):
            self.assertFalse(hasattr(port,n))
    def test_exact_cancel_once(self):
        a=self.start();self.owner.cancel_current();self.owner.cancel_current()
        cancels=[c for _,c in self.dog.q.commands if c.get('op')=='coordination_cancel']
        self.assertEqual(len(cancels),1);self.assertEqual(cancels[0]['expected_action_id'],a['action_id'])
        self.assertTrue(self.owner.recovery_blocked)
    def test_fixture_import_cannot_enable_live(self):
        from mdcoord.adapters import publish_recorded
        raw=observed();publish_recorded(self.owner.snapshots,raw)
        with self.assertRaises(Rejected):self.adapter.publisher.binding(self.owner.snapshots.read())

if __name__=='__main__':unittest.main()
