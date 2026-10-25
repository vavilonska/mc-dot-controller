"""Authorized journal-only fixture + explicitly synthetic future observations; no game I/O."""
import copy
import hashlib
import math
from pathlib import Path
from uuid import uuid4
from interaction2_controller.legacy import strict_json,encode,RawReply,legacy,PROFILE,ROOT
from interaction2_controller.schema import payload_digest,requested_calls
from interaction2_controller.plan import Plan

FIXTURES=Path(__file__).resolve().parents[3]/'results'/'legacy94-fixtures'
ORIGINAL=strict_json((FIXTURES/'public-ledger.json').read_bytes())
OWNER=strict_json((FIXTURES/'public-owner.json').read_bytes())['owner_id']
ENDPOINT=ORIGINAL['endpoint']
SESSION='aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';WORLD='bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';PLAYER='cccccccc-cccc-4ccc-8ccc-cccccccccccc';OBS='dddddddd-dddd-4ddd-8ddd-dddddddddddd'

PLAN_DATA={'version':1,'context':dict(session=SESSION,world_generation=WORLD,player_uuid=PLAYER,owner_id=OWNER),'targets':[dict(pos=dict(x=-635,y=61,z=16),face='SOUTH',block_id='minecraft:nether_wart_block',feet_y=60,min_break_y=61)]}
PLAN_RAW=encode(PLAN_DATA)
PLAN=Plan(PLAN_RAW,hashlib.sha256(PLAN_RAW).hexdigest())


def clone(directory):
    directory.mkdir(mode=0o700)
    for name,raw in (('ledger.json',encode(ORIGINAL)),('owner.json',encode({'owner_id':OWNER}))):
        (directory/name).write_bytes(raw);(directory/name).chmod(0o600)
    (directory/'owner.lock').touch(mode=0o600)


def observation():
    o=dict(schema_version=1,profile=PROFILE,session=SESSION,world_generation=WORLD,player_uuid=PLAYER,owner_generation=95,bound_owner_id=OWNER,unknown_lock=False,active_id=None,ready=True,reason='ready',paused=False,screen_open=False,alive=True,on_ground=True,health=20.,client_tick=100,observation_id=OBS,
        pose=dict(x=-634.5243,y=60.,z=18.94168,yaw=-180.,pitch=-16.4),velocity=dict(x=0.,y=0.,z=0.),
        player_bbox=dict(min_x=-634.8243,max_x=-634.2243,min_y=60.,max_y=61.8,min_z=18.64168,max_z=19.24168),selected_slot=2,
        hotbar=[dict(slot=i,item_id='minecraft:stone_pickaxe' if i==2 else 'minecraft:air',count=1 if i==2 else 0,damage=106 if i==2 else 0,max_damage=131 if i==2 else 0,stack_fingerprint=('a' if i==2 else '0')*64) for i in range(9)],
        ray=dict(kind='block',x=-635,y=61,z=16,face='SOUTH',point=dict(x=-634.5,y=61.5,z=17.),block_id='minecraft:nether_wart_block'),local_blocks=[],nearby_living=[],nearby_truncated=False,terrain_complete=True)
    for dy in range(-2,4):
        for dz in range(-2,3):
            for dx in range(-2,3):
                pos=(-635+dx,60+dy,18+dz)
                block='minecraft:nether_bricks' if dy<0 else 'minecraft:nether_wart_block' if pos==(-635,61,16) else 'minecraft:air'
                o['local_blocks'].append(dict(dx=dx,dy=dy,dz=dz,loaded=True,id=block,collision=block!='minecraft:air',fluid='minecraft:empty'))
    return o


def request(kind='break_block'):
    r=dict(schema_version=1,profile=PROFILE,kind=kind,id=str(uuid4()),session=SESSION,world_generation=WORLD,player_uuid=PLAYER,owner_id=OWNER,owner_generation=95,ttl_ms=2000 if kind=='break_block' else 1000,observation_id=OBS,plan_version=1,plan_sha256=PLAN.sha256)
    if kind=='move':r.update(forward=.5,strafe=0.,samples=4,jump_first=False)
    elif kind=='look':r.update(yaw=-180.,pitch=4.)
    elif kind=='select_hotbar':r.update(slot=2,stack_fingerprint='a'*64)
    else:r.update(x=-635,y=61,z=16,face='SOUTH',block_id='minecraft:nether_wart_block',stack_fingerprint='a'*64,max_calls=32)
    return r


def receipt(req,state='SETTLED',count=None,outcome=None):
    if count is None:count=0 if state=='QUEUED' else requested_calls(req)
    terminal=state=='SETTLED'
    return dict(schema_version=1,profile=PROFILE,kind=req['kind'],plan_version=req['plan_version'],plan_sha256=req['plan_sha256'],**{k:req[k] for k in legacy.IDENTITY},payload_digest=payload_digest(req),state=state,protocol_state=state,reason='calls_complete',requested_calls=requested_calls(req),applied_calls=count,cancellation_generation=1 if terminal else 0,input_invalidated=terminal,release_proven=terminal or count==0,settled=terminal,protocol_terminal=terminal,unknown_lock=state=='UNKNOWN',effect_state='unknown' if state=='UNKNOWN' else 'calls_completed' if count else 'not_started',release_state='proven' if terminal and count else 'not_needed' if count==0 else 'pending',settlement_state='not_observed',gameplay_outcome=outcome or ('target_unchanged' if req['kind']=='break_block' else 'not_assessed'))


def record(req):
    terminal=receipt(req)
    return dict(plan=PLAN.snapshot(),request=req,state='CLOSED',unknown_reasons=[],evidence=[],latest_native=terminal,terminal_native=copy.deepcopy(terminal),stop_attempted=False)


class Fake:
    endpoint=ENDPOINT
    def __init__(self):self.calls=[];self.obs=observation();self.req=None;self.state='SETTLED';self.fail=False;self.modify=None;self.before=None
    def request(self,method,path,body=None):
        self.calls.append((method,path,copy.deepcopy(body)))
        if path==ROOT+'observe':return RawReply(200,encode(self.obs))
        if self.before:self.before(method,path,body)
        if path.endswith('start'):
            self.req=copy.deepcopy(body)
            if self.fail:return RawReply(0,b'',False)
        r=receipt(self.req,self.state)
        if self.modify:r=self.modify(r)
        return RawReply(202 if path.endswith('start') else 200,encode(r))
    def posts(self):return [x for x in self.calls if x[0]=='POST']
