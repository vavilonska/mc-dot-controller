"""Explicit v5 maintenance admission; all historical profiles retain their original readers."""
import copy
from .legacy import V4Controller,V4_PROFILE,v4_schema,legacy,Refused,strict_json,encode,MAX_RESPONSE,PROFILE,ROOT
from . import schema
from .policy import gate
from .geometry import observation_geometry,witness_valid,primed_valid,latest_valid,eye_valid
from .plan import Plan,validate_snapshot
import os
import stat
from pathlib import Path
from .legacy import Ledger
from interaction2_controller.plan import validate_snapshot as snapshot2
from interaction3_controller.plan import validate_snapshot as snapshot3
from navigation4_controller.plan import validate_snapshot as snapshot4
class MaintenanceLedger(Ledger):
    MAX_BYTES=24*1024*1024 # Explicit v5 capacity; no monkeypatch of old readers.
SNAPSHOT_READERS={'recovery_interaction_v2':snapshot2,'recovery_interaction_v3':snapshot3,'recovery_navigation_v4':snapshot4,PROFILE:validate_snapshot}


class Controller(V4Controller):
    MAX_ACTIONS=512 # v5-only bounded count; not a promise all records fit 24MiB.

    def __init__(self, directory, transport, plan=None):
        if plan is not None and not isinstance(plan,Plan):raise Refused('loaded hash-pinned maintenance PLAN required')
        self.plan=plan
        directory=Path(directory)
        # Check before Ledger: its legacy constructor can initialize new storage;
        # this successor deliberately cannot use that capability.
        for filename in ('ledger.json','owner.json','owner.lock'):
            path=directory/filename
            if not path.exists() or path.is_symlink(): raise Refused('existing original ledger and owner are required')
        self.ledger=MaintenanceLedger(directory)
        self.transport=transport
        self._last_observation=None
        try:
            data=self.ledger.data
            if data['endpoint'] != transport.endpoint or not data['actions']:
                raise Refused('original endpoint and nonempty history required')
            fd=os.open(directory/'owner.json',os.O_RDONLY|os.O_NOFOLLOW)
            with os.fdopen(fd,'rb') as stream:
                st=os.fstat(stream.fileno())
                if not stat.S_ISREG(st.st_mode) or st.st_uid!=os.getuid() or stat.S_IMODE(st.st_mode)&0o077:
                    raise Refused('original owner file must remain private')
                raw=stream.read(4097)
            if len(raw)>4096: raise Refused('owner file bound exceeded')
            owner=strict_json(raw)
            if not isinstance(owner,dict) or set(owner)!={'owner_id'}: raise Refused('original owner malformed')
            self.owner_id=owner['owner_id'];legacy.uuid(self.owner_id)
            for record in data['actions'].values():
                self.validate_request(record['request'])
                if record['request']['owner_id'] != self.owner_id: raise Refused('original owner mismatch')
                if record['state']=='CLOSED':
                    terminal=record.get('terminal_native')
                    self._validate_receipt(terminal,record['request'])
                    if terminal['state']!='SETTLED': raise Refused('original terminal missing')
                profile=record['request']['profile']
                validator=SNAPSHOT_READERS.get(profile)
                if validator is not None:validator(record.get('plan'),record['request'])
        except BaseException:
            self.close()
            raise

    @staticmethod
    def validate_request(req):
        if not isinstance(req,dict):raise Refused('closed request object required')
        if req.get('profile')!=PROFILE:return V4Controller.validate_request(req)
        return schema.request_valid(req)

    @staticmethod
    def _validate_receipt(receipt,request):return schema.receipt_valid(receipt,request)

    @staticmethod
    def route(request):
        if request['profile']==PROFILE:return ROOT
        return V4Controller.route(request)

    def start(self,request):
        self.validate_request(request)
        data=self.ledger.data;original=data['actions'].get(request['id'])
        if original is not None:
            if original['request']!=request:raise Refused('shared original ID full payload mismatch')
            return self.report(request['id'])
        if request['profile']!=PROFILE:raise Refused('historical profile effect submission unavailable')
        if request['owner_id']!=self.owner_id:raise Refused('original owner required')
        if data['unknown_lock'] or any(r['state'] in ('PENDING','UNKNOWN') for r in data['actions'].values()):raise Refused('any-profile original action locks new dispatch')
        if len(data['actions'])>=self.MAX_ACTIONS:raise Refused('shared512 count ceiling reached')
        if self.plan is None or request['plan_version']!=3 or request['plan_sha256']!=self.plan.sha256:raise Refused('new effect requires original reviewed PLAN binding')
        observation=self._last_observation
        if observation is None or observation.get('observation_id')!=request['observation_id']:raise Refused('fresh original native observation required')
        risk=gate(observation,request,self.owner_id,data['actions'],self.plan)
        rec={'request':copy.deepcopy(request),'state':'PENDING','unknown_reasons':[],'evidence':[],
             'latest_native':None,'terminal_native':None,'stop_attempted':False,'observation':copy.deepcopy(observation),'local_risk':risk,'plan':self.plan.snapshot()}
        self._room(rec,2)
        # Include the complete request/observation/PLAN record BEFORE adding a PENDING intent.
        # Existing _room reserves all three bounded reply slots; never spend that reserve on the new record.
        projected=len(encode(data))+len(encode(request['id']))+len(encode(rec))+2
        if projected+MAX_RESPONSE*2*3>self.ledger.MAX_BYTES:raise Refused('byte ceiling prevents new intent; original evidence retained')
        data['actions'][request['id']]=rec
        self.ledger.save()
        self._exchange(rec,'start','POST',ROOT+'start',request)
        return self.report(request['id'])

    def observe(self):
        raw=self.transport.request('GET',ROOT+'observe')
        if not raw.complete or len(raw.body)>MAX_RESPONSE or raw.status!=200:raise Refused('observation unavailable')
        obs=strict_json(raw.body)
        if not isinstance(obs,dict) or set(obs)!=schema.OBS_KEYS or type(obs.get('schema_version')) is not int or obs['schema_version']!=1 or obs['profile']!=PROFILE:raise Refused('closed v5 observation required')
        schema.refusal_valid(obs['observation_refusal'],observe=True)
        observation_geometry(obs)
        witness_valid(obs)
        primed_valid(obs)
        latest_valid(obs)
        eye_valid(obs)
        if obs['observation_refusal'] is not None and (obs['world_generation'] is None or obs['ready'] is not False or obs['reason']!='observation_context_changed'):raise Refused('observation refusal readiness contradiction')
        if obs['world_generation'] is None:
            if obs['client_tick'] is not None or any(obs[k] is not None for k in ('player_bbox','selected_slot','ray')) or obs['hotbar']!=[]:raise Refused('no-world nullable observation mismatch')
        else:
            if not schema.integer(obs['client_tick'],0,9007199254740991):raise Refused('native frame invalid')
            from interaction2_controller.policy import hotbar
            hotbar(obs) # unchanged metadata read, no slot/selection authority.
        self._last_observation=copy.deepcopy(obs)
        return obs
