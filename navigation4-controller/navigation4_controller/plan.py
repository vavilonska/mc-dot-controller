"""Read-only, hash-pinned local PLAN data. Not a remote authorization service."""
import copy
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import stat
from .legacy import Refused,strict_json,legacy
from .schema import integer,finite,fingerprint
import re

MAX_PLAN_BYTES=16384
BOUNDS={'min_x','min_y','min_z','max_x','max_y','max_z'}


def validate(data):
    if not isinstance(data,dict) or set(data)!={'version','kind','context','stages'} or type(data['version']) is not int or data['version']!=2 or data['kind']!='navigation':raise Refused('closed navigation PLAN2 required')
    context=data['context']
    if not isinstance(context,dict) or set(context)!={'session','world_generation','player_uuid','owner_id'}:raise Refused('closed PLAN native context required')
    for value in context.values():legacy.uuid(value)
    stages=data['stages']
    if not isinstance(stages,list) or not 1<=len(stages)<=16:raise Refused('PLAN requires1..16 reviewed stages')
    seen=set()
    for t in stages:
        if not isinstance(t,dict) or set(t)!={'id','source_bounds','target','yaw','pitch','forward','strafe','jump_first','max_samples','max_moves','max_looks'}:raise Refused('closed navigation stage required')
        if not isinstance(t['id'],str) or not re.fullmatch('[A-Za-z0-9._:-]{1,64}',t['id']) or t['id'] in seen:raise Refused('unique bounded stage ID required')
        seen.add(t['id']);box=t['source_bounds'];target=t['target']
        if not isinstance(box,dict) or set(box)!=BOUNDS or any(not finite(v,-3e7,3e7) for v in box.values()) or any(not 0<box['max_'+k]-box['min_'+k]<=(2 if k=='y' else 8) for k in 'xyz'):raise Refused('finite ordered local source bounds required')
        if not finite(box['min_y'],-2048,2048) or not finite(box['max_y'],-2048,2048):raise Refused('source feet height range invalid')
        if not isinstance(target,dict) or set(target)!={'x','y','z'} or any(not finite(v,-3e7,3e7) for v in target.values()) or not finite(target['y'],-2048,2048):raise Refused('finite fractional feet target required')
        if not finite(t['yaw'],-180,180) or t['yaw']==180 or not finite(t['pitch'],-90,90) or not finite(t['forward'],-1,1) or not finite(t['strafe'],-1,1) or t['forward']==t['strafe']==0:raise Refused('bounded stage heading/input required')
        if type(t['jump_first']) is not bool or not integer(t['max_samples'],1,8) or not integer(t['max_moves'],1,8) or not integer(t['max_looks'],0,2) or t['jump_first'] and t['max_moves']!=1:raise Refused('finite stage budgets required; jump is one attempt')
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
    def stage(self,stage_id):
        for stage in self.data['stages']:
            if stage['id']==stage_id:return copy.deepcopy(stage)
        raise Refused('stage outside reviewed PLAN')


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
    plan.stage(req['stage_id'])
    return plan
