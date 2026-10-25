"""New navigation-only admission on unchanged v5 wire and persistence.

Only init/start are adapted; old maintenance records retain their original validator.
Inherited status/stop dispatch by stored request, never a caller-selected PLAN.
"""
import copy,os,stat
from pathlib import Path
from maintenance5_controller.controller import Controller as MaintenanceController, MaintenanceLedger
from maintenance5_controller.controller import SNAPSHOT_READERS as ORIGINAL_SNAPSHOT_READERS
from maintenance5_controller.legacy import V4Controller,legacy,Refused,strict_json,encode,MAX_RESPONSE,PROFILE,ROOT
from maintenance5_controller import schema
from maintenance5_controller.policy import gate
from maintenance5_controller.plan import validate_snapshot as maintenance_snapshot
from .plan import Plan,validate_snapshot

def v5_snapshot(snapshot,req):
    # Raw PLAN kind is only a discriminator. Each branch verifies the whole original
    # raw/hash/parsed/context/stage proof; no missing-key default to navigation.
    if not isinstance(snapshot,dict) or not isinstance(snapshot.get('raw_utf8'),str):raise Refused('original PLAN proof missing')
    raw=strict_json(snapshot['raw_utf8'])
    if not isinstance(raw,dict):raise Refused('closed original PLAN required')
    if raw.get('kind')=='maintenance':return maintenance_snapshot(snapshot,req)
    if raw.get('kind')=='navigation':return validate_snapshot(snapshot,req)
    raise Refused('unsupported original v5 PLAN discriminator')

SNAPSHOT_READERS=dict(ORIGINAL_SNAPSHOT_READERS)
SNAPSHOT_READERS[PROFILE]=v5_snapshot

class Controller(MaintenanceController):
    MAX_ACTIONS=512 # v5-only bounded count; not a promise all records fit 24MiB.

    def __init__(self, directory, transport, plan=None):
        if plan is not None and not isinstance(plan,Plan):raise Refused('loaded hash-pinned navigation PLAN required')
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
        if request['kind'] not in ('move','look'):raise Refused('navigation adapter permits new move/look only')
        if not isinstance(self.plan,Plan):raise Refused('explicit navigation PLAN required; maintenance PLAN cannot submit new effects')
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

