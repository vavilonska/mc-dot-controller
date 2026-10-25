"""Read-only, hash-pinned local PLAN data. Not a remote authorization service."""
import copy
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import stat
from .legacy import Refused,strict_json,legacy
from .schema import integer,fingerprint,FACES

MAX_PLAN_BYTES=16384
MATERIALS={'minecraft:cobblestone','minecraft:nether_wart_block'}


def validate(data):
    if not isinstance(data,dict) or set(data)!={'version','context','targets'} or type(data['version']) is not int or data['version']!=1:raise Refused('closed PLAN version1 required')
    context=data['context']
    if not isinstance(context,dict) or set(context)!={'session','world_generation','player_uuid','owner_id'}:raise Refused('closed PLAN native context required')
    for value in context.values():legacy.uuid(value)
    targets=data['targets']
    if not isinstance(targets,list) or not 1<=len(targets)<=8:raise Refused('PLAN requires1..8 exact targets')
    seen=set()
    for t in targets:
        if not isinstance(t,dict) or set(t)!={'pos','face','block_id','feet_y','min_break_y'}:raise Refused('closed PLAN target required')
        p=t['pos']
        if not isinstance(p,dict) or set(p)!={'x','y','z'} or any(not integer(v,-30000000,30000000) for v in p.values()):raise Refused('exact integral PLAN position required')
        if t['face'] not in FACES or t['block_id'] not in MATERIALS or not integer(t['feet_y'],-2048,2048) or not integer(t['min_break_y'],-2048,2048):raise Refused('PLAN target bounds invalid')
        if t['min_break_y']<t['feet_y']+1 or p['y']<t['min_break_y']:raise Refused('PLAN cannot authorize floor excavation')
        key=tuple(p[k] for k in ('x','y','z'))
        if key in seen:raise Refused('duplicate PLAN position')
        seen.add(key)
    return data


@dataclass(frozen=True)
class Plan:
    raw:bytes
    sha256:str
    def __post_init__(self):
        if type(self.raw) is not bytes or len(self.raw)>MAX_PLAN_BYTES or not fingerprint(self.sha256) or hashlib.sha256(self.raw).hexdigest()!=self.sha256:raise Refused('PLAN raw/hash mismatch')
        validate(strict_json(self.raw))
    @property
    def data(self):return validate(strict_json(self.raw))
    def snapshot(self):return {'raw_utf8':self.raw.decode('utf-8'),'parsed':self.data,'sha256':self.sha256}
    def bind(self,obs):
        if any((obs.get('bound_owner_id') if k=='owner_id' and 'bound_owner_id' in obs else obs.get(k))!=v for k,v in self.data['context'].items()):raise Refused('PLAN bound native context mismatch')
    def target(self,x,y,z,face):
        for t in self.data['targets']:
            if t['pos']==dict(x=x,y=y,z=z) and t['face']==face:return copy.deepcopy(t)
        raise Refused('target/face outside reviewed PLAN')


def load_plan(path,expected_sha256):
    if not fingerprint(expected_sha256):raise Refused('explicit lowercase PLAN SHA256 pin required')
    path=Path(path).absolute()
    if any(p.is_symlink() for p in (path,*path.parents)):raise Refused('PLAN symlink paths forbidden')
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    try:
        st=os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_uid!=os.getuid() or st.st_size>MAX_PLAN_BYTES:raise Refused('bounded owner-regular PLAN file required')
        raw=os.read(fd,MAX_PLAN_BYTES+1)
    finally:os.close(fd)
    return Plan(raw,expected_sha256)


def validate_snapshot(snapshot,req):
    if not isinstance(snapshot,dict) or set(snapshot)!={'raw_utf8','parsed','sha256'} or not isinstance(snapshot['raw_utf8'],str):raise Refused('original PLAN proof missing')
    plan=Plan(snapshot['raw_utf8'].encode('utf-8'),snapshot['sha256'])
    if snapshot['parsed']!=plan.data or req['plan_sha256']!=plan.sha256 or req['plan_version']!=plan.data['version']:raise Refused('original PLAN proof differs')
    plan.bind(req)
    return plan
