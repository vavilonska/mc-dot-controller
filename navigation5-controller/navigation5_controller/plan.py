"""Explicit navigation-only PLAN3; native v5 wire unchanged, no worksite authority."""
import copy
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import stat
from maintenance5_controller.legacy import Refused,strict_json,legacy
from maintenance5_controller.schema import fingerprint
from navigation4_controller.plan import validate as navigation_validate

MAX_PLAN_BYTES=16384
def validate(data):
    if not isinstance(data,dict) or set(data)!={'version','kind','context','navigation','worksites'} or type(data['version']) is not int or data['version']!=3 or data['kind']!='navigation':raise Refused('closed explicit navigation PLAN3 required')
    if type(data['worksites']) is not list or data['worksites']!=[]:raise Refused('navigation PLAN cannot contain worksites or maintenance targets')
    navigation_validate(dict(version=2,kind='navigation',context=data['context'],stages=data['navigation']))
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
    if req['kind'] not in ('move','look'):raise Refused('navigation proof cannot authorize other effects')
    return p
