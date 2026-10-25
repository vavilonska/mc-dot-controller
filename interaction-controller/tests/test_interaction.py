import base64
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs,urlsplit
from uuid import uuid4
from interaction_controller.controller import Controller
from interaction_controller.journal import NEW_PROFILE,NEW_ROOT
from interaction_controller.legacy import legacy,encode,Refused,RawReply,strict_json
from interaction_controller.schema import payload_digest,requested_calls
from interaction_controller.__main__ import assess
from test_legacy import synthetic_legacy,OWNER,ENDPOINT

SESSION='aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
WORLD='bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'
PLAYER='cccccccc-cccc-4ccc-8ccc-cccccccccccc'
OBS='dddddddd-dddd-4ddd-8ddd-dddddddddddd'


def observation():
    result=dict(schema_version=1,profile=NEW_PROFILE,session=SESSION,world_generation=WORLD,player_uuid=PLAYER,owner_generation=58,bound_owner_id=OWNER,unknown_lock=False,active_id=None,ready=True,reason='ready',paused=False,screen_open=False,alive=True,on_ground=True,health=20.,client_tick=100,observation_id=OBS,
        pose=dict(x=-635.5,y=59.,z=34.5,yaw=180.,pitch=0.),velocity=dict(x=0.,y=0.,z=0.),
        player_bbox=dict(min_x=-635.8,max_x=-635.2,min_y=59.,max_y=60.8,min_z=34.2,max_z=34.8),selected_slot=2,
        hotbar=[dict(slot=i,item_id='minecraft:stone_pickaxe' if i==2 else 'minecraft:andesite' if i==3 else 'minecraft:air',count=1 if i==2 else 64 if i==3 else 0,damage=104 if i==2 else 0,stack_fingerprint=('a' if i==2 else 'b' if i==3 else '0')*64) for i in range(9)],
        ray=dict(kind='block',x=-636,y=60,z=33,face='SOUTH',point=dict(x=-635.5,y=60.5,z=34.),block_id='minecraft:cobblestone'),local_blocks=[],nearby_living=[],nearby_truncated=False,terrain_complete=True)
    for dy in range(-2,4):
        for dz in range(-2,3):
            for dx in range(-2,3):
                pos=(-636+dx,59+dy,34+dz)
                block='minecraft:nether_bricks' if dy<0 or pos in {(-636,59,33),(-636,59,32)} else 'minecraft:cobblestone' if pos in {(-636,60,33),(-636,61,34)} else 'minecraft:air'
                result['local_blocks'].append(dict(dx=dx,dy=dy,dz=dz,loaded=True,id=block,collision=block!='minecraft:air',fluid='minecraft:empty'))
    return result


def request(kind='look'):
    r=dict(schema_version=1,profile=NEW_PROFILE,kind=kind,id=str(uuid4()),session=SESSION,world_generation=WORLD,player_uuid=PLAYER,owner_id=OWNER,owner_generation=58,ttl_ms=1000,observation_id=OBS)
    if kind=='move':r.update(forward=.5,strafe=0.,samples=1,jump_first=False)
    elif kind=='look':r.update(yaw=-180.,pitch=10.)
    elif kind=='select_hotbar':r.update(slot=2,stack_fingerprint='a'*64)
    else:r.update(x=-636,y=60,z=33,face='SOUTH',block_id='minecraft:cobblestone',stack_fingerprint='a'*64,max_calls=32)
    return r


def receipt(req,state='SETTLED',count=None,outcome=None):
    if count is None:count=0 if state=='QUEUED' else requested_calls(req)
    terminal=state=='SETTLED'
    return dict(schema_version=1,profile=NEW_PROFILE,kind=req['kind'],**{k:req[k] for k in legacy.IDENTITY},payload_digest=payload_digest(req),state=state,protocol_state=state,reason='calls_complete',requested_calls=requested_calls(req),applied_calls=count,cancellation_generation=1 if terminal else 0,input_invalidated=terminal,release_proven=terminal or count==0,settled=terminal,protocol_terminal=terminal,unknown_lock=state=='UNKNOWN',effect_state='unknown' if state=='UNKNOWN' else 'calls_completed' if count else 'not_started',release_state='proven' if terminal and count else 'not_needed' if count==0 else 'pending',settlement_state='not_observed',gameplay_outcome=outcome or ('target_unchanged' if req['kind']=='break_block' else 'not_assessed'))


class Fake:
    endpoint=ENDPOINT
    def __init__(self):self.calls=[];self.obs=observation();self.req=None;self.state='SETTLED';self.fail=False;self.modify=None;self.before=None
    def request(self,method,path,body=None):
        self.calls.append((method,path,copy.deepcopy(body)))
        if path==NEW_ROOT+'observe':return RawReply(200,encode(self.obs))
        if self.before:self.before(method,path,body)
        if path.endswith('start'):
            self.req=copy.deepcopy(body)
            if self.fail:return RawReply(0,b'',False)
        r=receipt(self.req,self.state)
        if self.modify:r=self.modify(r)
        return RawReply(202 if path.endswith('start') else 200,encode(r))
    def posts(self):return [x for x in self.calls if x[0]=='POST']


class InteractionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.directory=Path(self.tmp.name)/'ledger';self.original=synthetic_legacy(self.directory);self.f=Fake();self.c=Controller(self.directory,self.f)
    def tearDown(self):self.c.close();self.tmp.cleanup()
    def submit(self,kind='look',**updates):
        req=request(kind);req.update(updates);self.c.observe();return req,self.c.start(req)
    def test_each_kind_retains_all_57_original_records(self):
        for kind in ('look','select_hotbar','move','break_block'):
            req,result=self.submit(kind);self.assertEqual(result['state'],'CLOSED')
        for aid,rec in self.original['actions'].items():self.assertEqual(self.c.report(aid),rec)
        self.assertEqual(self.c.owner_id,OWNER);self.assertEqual(len(self.f.posts()),4)
        self.c.close();self.c=Controller(self.directory,self.f)
        self.assertEqual(len(self.c.report()['actions']),61)
    def test_same_id_cross_kind_and_old_profile_collision(self):
        req,result=self.submit();self.c.start(req);self.assertEqual(len(self.f.posts()),1)
        changed=request('move');changed['id']=req['id']
        with self.assertRaises(Refused):self.c.start(changed)
        changed['id']=next(iter(self.original['actions']))
        with self.assertRaises(Refused):self.c.start(changed)
        old=self.original['actions'][changed['id']]['request'];self.c.start(old)
        self.assertEqual(len(self.f.posts()),1)
    def test_old_unknown_blocks_new_kind(self):
        aid=next(iter(self.original['actions']));self.c.ledger.data['actions'][aid]['state']='UNKNOWN';self.c.ledger.data['unknown_lock']=True;self.c.ledger.save();self.c.close();self.c=Controller(self.directory,self.f)
        with self.assertRaises(Refused):self.submit('look')
        self.assertEqual(self.f.posts(),[])
    def test_lost_response_unknown_status_stop_no_reissue(self):
        self.f.fail=True;req,result=self.submit('break_block');self.assertEqual(result['state'],'UNKNOWN')
        self.c.status(req['id']);self.c.stop(req['id']);self.c.stop(req['id']);self.c.start(req)
        self.assertEqual(self.c.report(req['id'])['state'],'UNKNOWN');self.assertEqual(len(self.f.posts()),2)
        self.c.close();self.c=Controller(self.directory,self.f)
        with self.assertRaises(Refused):self.submit('select_hotbar')
    def test_pending_restart_keeps_shared_lock(self):
        self.f.state='ACTIVE';req,_=self.submit('move');self.c.close();self.c=Controller(self.directory,self.f)
        self.assertEqual(self.c.report(req['id'])['state'],'UNKNOWN')
        with self.assertRaises(Refused):self.submit('look')
    def test_known_incomplete_break_not_unknown(self):
        req,result=self.submit('break_block');self.assertEqual(result['state'],'CLOSED');self.assertEqual(assess(result)[0],4)
        self.assertFalse(self.c.report()['unknown_lock']);self.assertEqual(result['terminal_native']['gameplay_outcome'],'target_unchanged')
    def test_actual_ray_face_and_stack_required(self):
        for field,value in [('face','NORTH'),('kind','entity')]:
            self.f.obs['ray']=dict(observation()['ray'],**{field:value})
            with self.assertRaises(Refused):self.submit('break_block')
        self.f.obs=observation();self.f.obs['hotbar'][2]['stack_fingerprint']='c'*64
        with self.assertRaises(Refused):self.submit('break_block')
        self.assertEqual(self.f.posts(),[])
    def test_task_target_and_floor_bounds(self):
        for change in ({'y':59},{'x':-635},{'max_calls':33},{'block_id':'minecraft:nether_bricks'}):
            with self.assertRaises(Refused):self.submit('break_block',**change)
        self.assertEqual(self.f.posts(),[])
    def test_look_and_slot_are_bounded(self):
        for change in ({'yaw':0.},{'yaw':180.},{'pitch':float('nan')}):
            with self.assertRaises(Refused):self.submit('look',**change)
        with self.assertRaises(Refused):self.submit('select_hotbar',slot=3)
        self.assertEqual(self.f.posts(),[])
    def cleared_jump_observation(self):
        obs=observation()
        for cell in obs['local_blocks']:
            if cell['id']=='minecraft:cobblestone':cell.update(id='minecraft:air',collision=False)
        return obs
    def test_jump_fresh_swept_headroom_bbox_and_one_attempt(self):
        with self.assertRaises(Refused):self.submit('move',jump_first=True)
        self.f.obs=self.cleared_jump_observation();self.f.obs['player_bbox']['min_z']=33.99
        with self.assertRaises(Refused):self.submit('move',jump_first=True)
        self.f.obs=self.cleared_jump_observation()
        for cell in self.f.obs['local_blocks']:
            if (cell['dx'],cell['dy'],cell['dz'])==(0,3,0):cell.update(loaded=False,id=None,collision=None,fluid=None)
        with self.assertRaises(Refused):self.submit('move',jump_first=True)
        self.f.obs=self.cleared_jump_observation();req,result=self.submit('move',jump_first=True);self.assertEqual(result['state'],'CLOSED')
        with self.assertRaises(Refused):self.submit('move',jump_first=True)
        self.assertEqual(len(self.f.posts()),1)
    def test_jump_known_test_world_history_does_not_consume_formal_world(self):
        self.f.obs=self.cleared_jump_observation();old,result=self.submit('move',jump_first=True)
        formal=str(uuid4());self.f.obs['world_generation']=formal
        req,result=self.submit('move',jump_first=True,world_generation=formal)
        self.assertEqual(result['state'],'CLOSED');self.assertEqual(self.c.report(old['id'])['state'],'CLOSED')
        with self.assertRaises(Refused):self.submit('move',jump_first=True,world_generation=formal)
        self.c.ledger.data['actions'][old['id']]['state']='UNKNOWN';self.c.ledger.data['unknown_lock']=True;self.c.ledger.save()
        self.f.obs['world_generation']=str(uuid4())
        with self.assertRaises(Refused):self.submit('move',jump_first=True,world_generation=self.f.obs['world_generation'])
        self.assertEqual(len(self.f.posts()),2)
    def test_jump_rejects_z35_crossing_dy3_solid_and_wrong_support(self):
        self.f.obs=self.cleared_jump_observation();self.f.obs['player_bbox'].update(min_z=34.41,max_z=35.01);self.f.obs['pose']['z']=34.71
        with self.assertRaises(Refused):self.submit('move',jump_first=True)
        for coordinate in ((0,3,0),(0,3,-1),(0,0,-1),(0,0,0)):
            self.f.obs=self.cleared_jump_observation()
            for cell in self.f.obs['local_blocks']:
                if (cell['dx'],cell['dy'],cell['dz'])==coordinate:cell.update(id='minecraft:cobblestone',collision=True)
            with self.assertRaises(Refused):self.submit('move',jump_first=True)
        self.assertEqual(self.f.posts(),[])
    def test_jump_z32_adjacent_landing_missing_or_blocked_refuses(self):
        for dy,update in ((0,dict(loaded=False,id=None,collision=None,fluid=None)),(0,dict(id='minecraft:cobblestone',collision=True)),(1,dict(id='minecraft:cobblestone',collision=True)),(3,dict(id='minecraft:cobblestone',collision=True))):
            with self.subTest(dy=dy,update=update):
                self.f.obs=self.cleared_jump_observation()
                for cell in self.f.obs['local_blocks']:
                    if (cell['dx'],cell['dy'],cell['dz'])==(0,dy,-2):cell.update(update)
                with self.assertRaises(Refused):self.submit('move',jump_first=True,forward=1.,samples=8)
        self.assertEqual(self.f.posts(),[])
    def test_durable_full_kind_before_first_post(self):
        def check(method,path,body):
            if path.endswith('start'):
                data=strict_json((self.directory/'ledger.json').read_bytes());self.assertEqual(data['actions'][body['id']]['request'],body);self.assertEqual(data['actions'][body['id']]['state'],'PENDING')
        self.f.before=check;self.submit('break_block')
    def test_fsync_failure_no_post(self):
        req=request();self.c.observe()
        with patch.object(self.c.ledger,'save',side_effect=OSError('offline fault')):
            with self.assertRaises(OSError):self.c.start(req)
        self.assertEqual(self.f.posts(),[])
    def test_digest_all_kind_fields_and_negative_zero(self):
        for kind in ('move','look','select_hotbar','break_block'):
            req=request(kind);original=payload_digest(req)
            key={'move':'samples','look':'pitch','select_hotbar':'slot','break_block':'max_calls'}[kind]
            changed=dict(req);changed[key]+=1
            self.assertNotEqual(original,payload_digest(changed))
            self.assertNotEqual(original,payload_digest(dict(req,observation_id=str(uuid4()))))
        q=request('move');self.assertEqual(payload_digest(q),payload_digest(dict(q,strafe=-0.)))
    def test_new_receipt_cannot_rewrite_old_semantics(self):
        old=next(iter(self.original['actions'].values()))
        malformed=dict(old['terminal_native'],profile=NEW_PROFILE,kind='move')
        with self.assertRaises(Refused):self.c._validate_receipt(malformed,old['request'])
    def test_stop_target_original_no_new_owner_cleanup(self):
        req,result=self.submit('look');self.f.modify=lambda r:dict(r,owner_id=str(uuid4()));self.c.stop(req['id'])
        self.assertEqual(self.f.posts()[-1][2]['owner_id'],OWNER);self.assertEqual(self.c.report(req['id'])['state'],'CLOSED')
    def test_async_natural_completion_only_one_effect_post(self):
        self.f.state='QUEUED';req,_=self.submit('move');self.f.state='SETTLED';result=self.c.finish_one_step(req['id'],sleep=lambda _:None)
        self.assertEqual(result['state'],'CLOSED');self.assertEqual(len(self.f.posts()),1)

if __name__=='__main__':unittest.main()
