"""Explicit PLAN4 survival operations and original bounded navigation, no worksites."""
import copy,hashlib,re
from dataclasses import dataclass
from .legacy import legacy,Refused,strict_json
from maintenance5_controller.schema import integer,fingerprint
from navigation4_controller.plan import validate as navigation_validate
MAX_PLAN_BYTES=16384
KINDS={'select_hotbar','attack_blaze','consume_bread'}
def validate(data):
 if not isinstance(data,dict) or set(data)!={'version','kind','context','navigation','survival'} or type(data['version']) is not int or data['version']!=4 or data['kind']!='survival':raise Refused('closed explicit survival PLAN4 required')
 ctx=data['context']
 if not isinstance(ctx,dict) or set(ctx)!={'session','world_generation','player_uuid','owner_id'}:raise Refused('closed PLAN context required')
 for v in ctx.values():legacy.uuid(v)
 nav,actions=data['navigation'],data['survival']
 if type(nav)is not list or type(actions)is not list or len(nav)>16 or len(actions)>16 or not(nav or actions):raise Refused('finite nonempty PLAN required')
 if nav:navigation_validate(dict(version=2,kind='navigation',context=ctx,stages=nav))
 ids={s['id'] for s in nav}
 for s in actions:
  if not isinstance(s,dict) or s.get('kind') not in KINDS:raise Refused('closed survival stage required')
  extra={'slot'} if s['kind']=='select_hotbar' else {'max_use_ticks'} if s['kind']=='consume_bread' else set()
  if set(s)!={'id','kind','max_intents'}|extra or type(s['max_intents'])is not int or s['max_intents']!=1:raise Refused('one explicit survival intent required')
  if not isinstance(s['id'],str) or not re.fullmatch('[A-Za-z0-9._:-]{1,64}',s['id']) or s['id'] in ids:raise Refused('unique bounded stage required')
  ids.add(s['id'])
  if s['kind']=='select_hotbar' and (type(s['slot'])is not int or s['slot'] not in (1,8)):raise Refused('only bread or iron axe slot permitted')
  if s['kind']=='consume_bread' and not integer(s['max_use_ticks'],1,40):raise Refused('bounded bread use ticks required')
 return data
@dataclass(frozen=True)
class Plan:
 raw:bytes
 sha256:str
 def __post_init__(self):
  if type(self.raw)is not bytes or len(self.raw)>MAX_PLAN_BYTES or not fingerprint(self.sha256) or hashlib.sha256(self.raw).hexdigest()!=self.sha256:raise Refused('PLAN raw/hash mismatch')
  validate(strict_json(self.raw))
 @property
 def data(self):return validate(strict_json(self.raw))
 def snapshot(self):return dict(raw_utf8=self.raw.decode(),parsed=self.data,sha256=self.sha256)
 def bind(self,obs):
  if any(obs.get('bound_owner_id' if k=='owner_id' and 'bound_owner_id'in obs else k)!=v for k,v in self.data['context'].items()):raise Refused('original PLAN context mismatch')
 def stage(self,sid):
  for s in self.data['navigation']+self.data['survival']:
   if s['id']==sid:return copy.deepcopy(s)
  raise Refused('stage outside reviewed PLAN')
 def permits(self,req):
  s=self.stage(req['stage_id']);kind=req['kind']
  if 'target'in s:
   if kind not in ('move','look'):raise Refused('navigation stage cannot authorize survival operation')
   if kind=='move' and (any(req[k]!=s[k] for k in ('forward','strafe','jump_first')) or req['samples']>s['max_samples']):raise Refused('navigation payload outside PLAN')
   if kind=='look' and (s['max_looks']<1 or any(req[k]!=s[k] for k in ('yaw','pitch'))):raise Refused('look outside PLAN')
  else:
   if kind!=s['kind']:raise Refused('survival kind differs from PLAN stage')
   if kind=='select_hotbar' and req['slot']!=s['slot']:raise Refused('selected slot differs from PLAN')
   if kind=='consume_bread' and req['max_use_ticks']>s['max_use_ticks']:raise Refused('use exceeds PLAN tick bound')
  return s

def load_plan(path,expected_sha256):
 import os,stat
 from pathlib import Path
 if not fingerprint(expected_sha256):raise Refused('explicit lowercase PLAN SHA required')
 path=Path(path).absolute()
 if any(p.is_symlink()for p in(path,*path.parents)):raise Refused('PLAN symlinks forbidden')
 fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
 try:
  st=os.fstat(fd)
  if not stat.S_ISREG(st.st_mode)or st.st_uid!=os.getuid()or st.st_size>MAX_PLAN_BYTES:raise Refused('bounded owner-regular PLAN required')
  raw=os.read(fd,MAX_PLAN_BYTES+1)
 finally:os.close(fd)
 return Plan(raw,expected_sha256)

def validate_snapshot(snapshot,req):
 if not isinstance(snapshot,dict)or set(snapshot)!={'raw_utf8','parsed','sha256'}or not isinstance(snapshot['raw_utf8'],str):raise Refused('original PLAN proof missing')
 p=Plan(snapshot['raw_utf8'].encode(),snapshot['sha256'])
 if snapshot['parsed']!=p.data or req['plan_sha256']!=p.sha256 or req['plan_version']!=4:raise Refused('original PLAN proof differs')
 p.bind(req);p.permits(req);return p
