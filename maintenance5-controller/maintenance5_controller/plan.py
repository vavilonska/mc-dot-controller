"""Finite, hash-pinned maintenance data; no automatic route or retry authority."""
import copy
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import stat
import re
from .legacy import Refused,strict_json,legacy
from .schema import integer,finite,fingerprint,BREAK_BLOCKS,ANCHOR_BLOCKS,FACES,placement_geometry
from navigation4_controller.plan import validate as navigation_validate

MAX_PLAN_BYTES=16384
BOUNDS={'min_x','min_y','min_z','max_x','max_y','max_z'}
BREAK_KEYS={'x','y','z','face','block_id','max_calls'}
PLACE_KEYS={'x','y','z','anchor_x','anchor_y','anchor_z','anchor_block_id','face','hit_x','hit_y','hit_z','item_id'}
def bounds(box):
    if not isinstance(box,dict) or set(box)!=BOUNDS or any(not finite(v,-3e7,3e7) for v in box.values()) or any(not 0<box['max_'+k]-box['min_'+k]<=(2 if k=='y' else 8) for k in 'xyz') or not finite(box['min_y'],-2048,2048) or not finite(box['max_y'],-2048,2048):raise Refused('finite ordered source feet corridor required')
def position(t):
    if any(not integer(t[k],-30000000,30000000) for k in ('x','z')) or not integer(t['y'],-2048,2048) or t['face'] not in FACES:raise Refused('exact integral target and face required')
def validate(data):
    if not isinstance(data,dict) or set(data)!={'version','kind','context','navigation','worksites'} or type(data['version']) is not int or data['version']!=3 or data['kind']!='maintenance':raise Refused('closed maintenance PLAN3 required')
    ctx=data['context']
    if not isinstance(ctx,dict) or set(ctx)!={'session','world_generation','player_uuid','owner_id'}:raise Refused('closed original PLAN context required')
    for v in ctx.values():legacy.uuid(v)
    nav=data['navigation'];sites=data['worksites']
    if not isinstance(nav,list) or len(nav)>16 or not isinstance(sites,list) or not 1<=len(sites)<=16:raise Refused('bounded navigation/worksites required')
    if nav:navigation_validate(dict(version=2,kind='navigation',context=ctx,stages=nav))
    ids={s['id'] for s in nav};broken=set();restored=set();counts={'minecraft:tnt':0,'service':0}
    for site in sites:
        if not isinstance(site,dict) or set(site)!={'id','source_bounds','max_looks','max_selects','break_targets','restore_targets'}:raise Refused('closed maintenance worksite required')
        sid=site['id']
        if not isinstance(sid,str) or not re.fullmatch('[A-Za-z0-9._:-]{1,64}',sid) or sid in ids:raise Refused('unique bounded stage ID required')
        ids.add(sid);bounds(site['source_bounds'])
        if not integer(site['max_looks'],0,64) or not integer(site['max_selects'],0,16):raise Refused('finite look/select budget required')
        if not isinstance(site['break_targets'],list) or not isinstance(site['restore_targets'],list) or len(site['break_targets'])>22 or len(site['restore_targets'])>13 or not (site['break_targets'] or site['restore_targets']):raise Refused('bounded worksite targets required')
        for t in site['break_targets']:
            if not isinstance(t,dict) or set(t)!=BREAK_KEYS:raise Refused('closed break target required')
            position(t)
            if t['block_id'] not in BREAK_BLOCKS or not integer(t['max_calls'],1,32) or t['block_id']=='minecraft:tnt' and t['max_calls']!=1:raise Refused('maintenance break catalogue/budget invalid')
            key=tuple(t[k] for k in 'xyz')
            if key in broken:raise Refused('duplicate break target across worksites')
            broken.add(key);counts['minecraft:tnt' if t['block_id']=='minecraft:tnt' else 'service']+=1
        for t in site['restore_targets']:
            if not isinstance(t,dict) or set(t)!=PLACE_KEYS:raise Refused('closed restoration target required')
            position(t)
            if t['item_id']!='minecraft:andesite' or t['anchor_block_id'] not in ANCHOR_BLOCKS or any(not integer(t['anchor_'+k],-2048 if k=='y' else -30000000,2048 if k=='y' else 30000000) for k in 'xyz') or any(not finite(t['hit_'+k],-3e7,3e7) for k in 'xyz'):raise Refused('exact static anchor and andesite required')
            placement_geometry(t);key=tuple(t[k] for k in 'xyz')
            if key in restored:raise Refused('duplicate restoration target')
            restored.add(key)
    if counts['minecraft:tnt']>9 or counts['service']>13 or len(restored)>13:raise Refused('finite reviewed maintenance catalogue exceeded')
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
    def stage(self,sid):
        for s in self.data['navigation']+self.data['worksites']:
            if s['id']==sid:return copy.deepcopy(s)
        raise Refused('stage outside reviewed PLAN')
    def target(self,req):
        site=self.stage(req['stage_id']);key='break_targets' if req['kind']=='break_block' else 'restore_targets'
        for t in site.get(key,[]):
            if all(abs(req[k]-t[k])<=1e-4 if k.startswith('hit_') else req[k]==t[k] for k in t):return copy.deepcopy(t)
        raise Refused('exact target payload outside reviewed worksite')

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
    p=Plan(snapshot['raw_utf8'].encode(),snapshot['sha256'])
    if snapshot['parsed']!=p.data or req['plan_sha256']!=p.sha256 or req['plan_version']!=3:raise Refused('original PLAN proof differs')
    p.bind(req);p.stage(req['stage_id'])
    if req['kind'] in ('break_block','place_block'):p.target(req)
    return p
