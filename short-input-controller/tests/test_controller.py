import base64
import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

from short_input_controller.controller import Controller, PROFILE, ROOT, payload_digest
from short_input_controller.storage import Refused, strict_json, encode
from short_input_controller.transport import RawReply
from short_input_controller.policy import local_gate

SESSION='11111111-1111-4111-8111-111111111111'
PLAYER='22222222-2222-4222-8222-222222222222'


def observation():
    return dict(schema_version=1,profile=PROFILE,session=SESSION,owner_generation=1,
        world_generation='world-1',observation_id='33333333-3333-4333-8333-333333333333',player_uuid=PLAYER,ready=True,reason='ready',unknown_lock=False,
        active_id=None,bound_owner_id=None,pose=dict(x=0.,y=64.,z=0.,yaw=0.,pitch=0.),
        velocity=dict(x=0.,y=0.,z=0.),on_ground=True,health=20.,alive=True,paused=False,screen_open=False,
        local_blocks=[dict(dx=x,dy=y,dz=z,loaded=True,collision=y<0,fluid='minecraft:empty',id='minecraft:stone' if y<0 else 'minecraft:air') for x in range(-2,3) for y in range(-2,3) for z in range(-2,3)],
        nearby_living=[],nearby_truncated=False,terrain_complete=True,client_tick=42)


def request(owner):
    return dict(schema_version=1,profile=PROFILE,id=str(uuid4()),session=SESSION,owner_id=owner,
        world_generation='world-1',player_uuid=PLAYER,owner_generation=1,forward=1.,strafe=0.,samples=1,jump_first=False,ttl_ms=1000,observation_id='33333333-3333-4333-8333-333333333333')


def receipt(req,state='ACTIVE',count=1):
    return dict(schema_version=1,profile=PROFILE,**{k:req[k] for k in ('id','owner_id','session','world_generation','player_uuid','owner_generation')},
        state=state,reason='fixture',requested_samples=req['samples'],applied_samples=count,
        input_invalidated=state=='SETTLED',release_proven=state=='SETTLED',settled=state=='SETTLED',
        gameplay_outcome='not_assessed',unknown_lock=state=='UNKNOWN',payload_digest=payload_digest(req),
        protocol_state=state,effect_state='samples_written' if count else 'not_started',
        release_state='proven' if state=='SETTLED' else 'pending',settlement_state='not_observed',cancellation_generation=0,protocol_terminal=state=='SETTLED')


class Fake:
    endpoint='http://127.0.0.1:38121'
    def __init__(self): self.calls=[];self.req=None;self.fail_start=False;self.state='ACTIVE';self.modify=None;self.obs=observation();self.hook=None
    def request(self,method,path,body=None):
        self.calls.append((method,path,copy.deepcopy(body)))
        if path==ROOT+'observe': return RawReply(200,encode(self.obs))
        if self.hook:self.hook(method,path,body)
        if path==ROOT+'start':
            self.req=copy.deepcopy(body)
            if self.fail_start: return RawReply(0,b'',False)
        r=receipt(self.req,self.state,0 if self.state=='QUEUED' else 1)
        if self.modify:r=self.modify(r)
        return RawReply(202 if path.endswith('start') else 200,encode(r))
    def posts(self):return [x for x in self.calls if x[0]=='POST']


class ControllerTests(unittest.TestCase):
    def setUp(self): self.temp=tempfile.TemporaryDirectory();self.directory=Path(self.temp.name)/'ledger';self.fake=Fake();self.c=Controller(self.directory,self.fake)
    def tearDown(self):self.c.close();self.temp.cleanup()
    def req(self):
        self.c.observe()
        return request(self.c.owner_id)
    def test_same_id_read_only_and_mismatch(self):
        q=self.req();self.c.start(q);self.c.start(q);self.assertEqual(len(self.fake.posts()),1)
        bad=dict(q,samples=2)
        with self.assertRaises(Refused):self.c.start(bad)
        self.assertEqual(len(self.fake.posts()),1)
    def test_lost_response_unknown_sticky_across_status_stop_restart(self):
        q=self.req();self.fake.fail_start=True;self.assertEqual(self.c.start(q)['state'],'UNKNOWN')
        self.fake.state='SETTLED';self.c.status(q['id']);self.c.stop(q['id']);self.c.stop(q['id'])
        self.assertEqual(len(self.fake.posts()),2);self.assertEqual(self.c.report(q['id'])['state'],'UNKNOWN')
        self.c.close();self.c=Controller(self.directory,self.fake)
        with self.assertRaises(Refused):self.c.start(self.req())
        self.assertTrue(self.c.report()['unknown_lock'])
    def test_restart_pending_locks_without_post(self):
        q=self.req();self.c.start(q);self.c.close();n=len(self.fake.posts());self.c=Controller(self.directory,self.fake)
        self.assertEqual(self.c.report(q['id'])['state'],'UNKNOWN');self.assertEqual(len(self.fake.posts()),n)
    def test_queue_cancel_and_native_expiry(self):
        q=self.req();self.fake.state='QUEUED';self.c.start(q);self.fake.state='SETTLED';self.c.stop(q['id'])
        self.assertEqual(self.c.report(q['id'])['state'],'PENDING') # stop ack is not outcome settlement
        self.c.status(q['id']);self.assertEqual(self.c.report(q['id'])['state'],'CLOSED')
    def test_native_unknown_disconnect(self):
        q=self.req();self.fake.state='UNKNOWN';self.c.start(q)
        self.assertEqual(self.c.report(q['id'])['state'],'UNKNOWN')
    def test_oldowner_mismatch_never_cleans_replacement(self):
        q=self.req();self.c.start(q);self.fake.modify=lambda r:dict(r,owner_id=str(uuid4()))
        self.c.stop(q['id']);self.assertEqual(self.c.report(q['id'])['state'],'UNKNOWN')
        self.assertEqual(self.fake.posts()[-1][2]['owner_id'],q['owner_id'])
    def test_raw_receipt_exact_and_digest_mismatch(self):
        q=self.req();self.fake.modify=lambda r:dict(r,payload_digest='0'*64);self.c.start(q)
        ev=self.c.report(q['id'])['evidence'][0];raw=base64.b64decode(ev['raw_base64'])
        self.assertEqual(strict_json(raw)['payload_digest'],'0'*64);self.assertEqual(self.c.report(q['id'])['state'],'UNKNOWN')
    def test_durable_intent_before_first_post(self):
        q=self.req()
        def check(*_):
            saved=strict_json((self.directory/'ledger.json').read_bytes())
            self.assertEqual(saved['actions'][q['id']]['state'],'PENDING');self.assertEqual(saved['actions'][q['id']]['request'],q)
        self.fake.hook=check;self.c.start(q)
    def test_ledger_crash_prevents_dispatch(self):
        q=self.req()
        with patch.object(self.c.ledger,'save',side_effect=OSError('fixture')):
            with self.assertRaises(OSError):self.c.start(q)
        self.assertEqual(len(self.fake.posts()),0)
    def test_receipt_commit_crash_restores_unknown(self):
        q=self.req();original=self.c.ledger.save;calls=0
        def crash():
            nonlocal calls
            calls+=1
            if calls==2:raise OSError('fixture')
            original()
        with patch.object(self.c.ledger,'save',side_effect=crash):
            with self.assertRaises(OSError):self.c.start(q)
        self.c.close();self.c=Controller(self.directory,self.fake)
        self.assertEqual(self.c.report(q['id'])['state'],'UNKNOWN');self.assertEqual(len(self.fake.posts()),1)
    def test_owner_lock_and_endpoint_change(self):
        with self.assertRaises(Refused): Controller(self.directory,self.fake)
        self.c.close();self.fake.endpoint='http://127.0.0.1:38122'
        with self.assertRaises(Refused): Controller(self.directory,self.fake)
    def test_one_inflight(self):
        self.c.start(self.req())
        with self.assertRaises(Refused):self.c.start(self.req())
    def test_local_not_global_gate(self):
        self.fake.obs['nearby_living']=[dict(id='e',type='minecraft:zombie',x=4.,y=64.,z=4.,alive=True)]
        self.fake.obs['terrain_complete']=False
        self.fake.obs['local_blocks'][0].update(loaded=False,id=None,collision=None,fluid=None)
        self.assertEqual(self.c.start(self.req())['state'],'PENDING')
    def test_overlap_drop_and_jump_refuse_before_post(self):
        q=self.req();self.fake.obs['nearby_living']=[dict(id='e',type='minecraft:pig',x=0.,y=64.,z=.3,alive=True)]
        self.c.observe()
        with self.assertRaises(Refused):self.c.start(q)
        self.fake.obs=observation();q['jump_first']=True
        with self.assertRaises(Refused):self.c.start(q)
        q['jump_first']=False
        for cell in self.fake.obs['local_blocks']:
            if cell['dx']==0 and cell['dz']==1 and cell['dy']<0:cell['collision']=False
        self.c.observe()
        with self.assertRaises(Refused):self.c.start(q)
        self.assertEqual(len(self.fake.posts()),0)
    def test_normal_async_settlement_without_premature_cancel(self):
        q=self.req();self.fake.state='QUEUED';self.c.start(q)
        states=iter(['ACTIVE','SETTLED'])
        def advance(method,path,body):
            if method=='GET':self.fake.state=next(states)
        self.fake.hook=advance
        self.assertEqual(self.c.finish_one_step(q['id'],sleep=lambda _:None)['state'],'CLOSED')
        self.assertEqual(len(self.fake.posts()),1)
    def test_closed_read_failure_keeps_known_original(self):
        q=self.req();self.fake.state='SETTLED';self.c.start(q)
        self.fake.modify=lambda r:dict(r,id=str(uuid4()))
        self.c.status(q['id'])
        self.assertEqual(self.c.report(q['id'])['state'],'CLOSED')
        self.assertFalse(self.c.report()['unknown_lock'])
    def test_bounded_pending_then_exact_stop_unknown(self):
        q=self.req();self.fake.state='QUEUED';self.c.start(q)
        now=[0.]
        def advance(dt):now[0]+=dt
        self.assertEqual(self.c.finish_one_step(q['id'],clock=lambda:now[0],sleep=advance)['state'],'UNKNOWN')
        self.assertEqual(len(self.fake.posts()),2)
    def test_contradictory_terminal_not_closed(self):
        for updates in ({'input_invalidated':False},{'release_state':'pending'},{'protocol_terminal':False}):
            with self.subTest(updates=updates):
                q=self.req();self.fake.state='SETTLED';self.fake.modify=lambda r:dict(r,**updates)
                # Isolate each deliberate UNKNOWN fault in a separate fixture ledger.
                with tempfile.TemporaryDirectory() as d:
                    with Controller(Path(d)/'ledger',self.fake) as c:
                        c.observe();q['owner_id']=c.owner_id
                        self.assertEqual(c.start(q)['state'],'UNKNOWN')
    def test_terminal_known_no_input_cancel(self):
        q=self.req();self.fake.modify=lambda r:dict(receipt(q,'SETTLED',0),release_state='not_needed')
        self.assertEqual(self.c.start(q)['state'],'CLOSED')
    def test_native_count_regression_unknown(self):
        q=self.req();self.c.start(q)
        self.fake.modify=lambda r:dict(receipt(q,'SETTLED',0),release_state='not_needed')
        self.c.status(q['id']);self.assertEqual(self.c.report(q['id'])['state'],'UNKNOWN')
    def test_missing_owner_does_not_replace(self):
        q=self.req();self.c.start(q);self.c.close();(self.directory/'owner.json').unlink()
        with self.assertRaises(Refused):Controller(self.directory,self.fake)
        self.assertFalse((self.directory/'owner.json').exists())
    def test_step_assessment_does_not_claim_motion_from_zero_input(self):
        from short_input_controller.__main__ import assess_step
        q=self.req()
        zero={'state':'CLOSED','latest_native':receipt(q,'SETTLED',0)}
        self.assertEqual(assess_step(zero)[0],3)
        full={'state':'CLOSED','latest_native':dict(receipt(q,'SETTLED',1),reason='samples_complete')}
        self.assertEqual(assess_step(full)[0],0)
        self.assertIn('not_verified',assess_step(full)[1])
        self.assertEqual(assess_step(dict(full,state='UNKNOWN'))[0],2)
    def test_real_fsync_failure_prevents_post(self):
        q=self.req()
        with patch('short_input_controller.storage.os.fsync',side_effect=OSError('fixture fsync failure')):
            with self.assertRaises(OSError):self.c.start(q)
        self.assertEqual(len(self.fake.posts()),0)
    def test_report_cli_needs_no_token_or_network(self):
        import contextlib,io
        from short_input_controller.__main__ import main
        self.c.close()
        with patch('short_input_controller.__main__.getpass.getpass',side_effect=AssertionError('must not prompt')), contextlib.redirect_stdout(io.StringIO()):
            code=main(['--ledger',str(self.directory),'--endpoint',self.fake.endpoint,'report'])
        self.assertEqual(code,0);self.assertEqual(self.fake.calls,[])
    def test_lost_stop_not_retried(self):
        q=self.req();self.c.start(q)
        def lost(method,path,body):
            if path.endswith('stop'): raise OSError('lost fixture response')
        self.fake.hook=lost;self.c.stop(q['id']);self.c.stop(q['id'])
        self.assertEqual(len(self.fake.posts()),2)
        self.assertEqual(self.c.report(q['id'])['state'],'UNKNOWN')
    def test_poll_reserves_stop_and_terminal_read_capacity(self):
        q=self.req();q['ttl_ms']=2000;self.fake.state='QUEUED';self.c.start(q)
        rec=self.c.ledger.data['actions'][q['id']]
        rec['evidence'] += [{'fixture':'reserved'}] * (self.c.MAX_EVIDENCE-3-len(rec['evidence']))
        self.c.ledger.save()
        result=self.c.finish_one_step(q['id'],sleep=lambda _:None)
        self.assertEqual(result['state'],'UNKNOWN');self.assertTrue(result['stop_attempted'])
        self.assertEqual(len(result['evidence']),self.c.MAX_EVIDENCE)
        self.assertEqual(len(self.fake.posts()),2)
    def test_corrupt_ledger_state_refuses_new_owner(self):
        q=self.req();self.c.start(q);self.c.close()
        path=self.directory/'ledger.json';data=strict_json(path.read_bytes())
        data['actions'][q['id']]['state']='UNRECOGNIZED';path.write_bytes(encode(data))
        with self.assertRaises(Refused):Controller(self.directory,self.fake)
        self.assertEqual(len(self.fake.posts()),1)
    def test_closed_terminal_original_survives_later_unknown_and_restart(self):
        q=self.req();self.fake.state='SETTLED';self.c.start(q)
        original=self.c.report(q['id'])['terminal_native']
        self.fake.state='UNKNOWN';self.c.status(q['id']);self.c.close();self.c=Controller(self.directory,self.fake)
        self.assertEqual(self.c.report(q['id'])['state'],'CLOSED')
        self.assertEqual(self.c.report(q['id'])['terminal_native'],original)
    def test_strict_json(self):
        for raw in (b'{"x":1,"x":2}',b'{"x":NaN}',b'{"x":1e999}',b'{"x":Infinity}'):
            with self.assertRaises(Refused):strict_json(raw)
    def test_closed_schema(self):
        q=self.req();q['attack']=True
        with self.assertRaises(Refused):self.c.start(q)
        self.assertEqual(len(self.fake.posts()),0)

if __name__=='__main__':unittest.main()
