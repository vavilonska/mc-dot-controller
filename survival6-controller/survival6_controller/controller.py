"""Independent v6 admission; all v5 raw proof kinds remain original mixed readers."""
import copy,os,stat,time
from pathlib import Path
from .legacy import OriginalController,MaintenanceLedger,SNAPSHOT_READERS as ORIGINAL_SNAPSHOT_READERS,legacy,Refused,strict_json,encode,MAX_RESPONSE,PROFILE,ROOT
from .storage import SurvivalLedger, _StartCapacityProof
from . import schema
from .policy import gate,survival_valid
from .plan import Plan,validate_snapshot
from maintenance5_controller.geometry import observation_geometry,primed_valid
SNAPSHOT_READERS=dict(ORIGINAL_SNAPSHOT_READERS)
SNAPSHOT_READERS[PROFILE]=validate_snapshot

class Controller(OriginalController):
    MAX_ACTIONS=SurvivalLedger.MAX_ACTIONS # V6 runtime only; byte+cleanup reserve remains independent.

    def __init__(self, directory, transport, plan=None):
        if plan is not None and not isinstance(plan,Plan):raise Refused('loaded hash-pinned survival PLAN required')
        self.plan=plan
        directory=Path(directory)
        # Check before Ledger: its legacy constructor can initialize new storage;
        # this successor deliberately cannot use that capability.
        for filename in ('ledger.json','owner.json','owner.lock'):
            path=directory/filename
            if not path.exists() or path.is_symlink(): raise Refused('existing original ledger and owner are required')
        self.ledger=SurvivalLedger(directory)
        self._start_capacity_proof=None
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
        if req.get('profile')!=PROFILE:return OriginalController.validate_request(req)
        return schema.request_valid(req)

    @staticmethod
    def _validate_receipt(receipt,request):return schema.receipt_valid(receipt,request)

    @staticmethod
    def route(request):
        if request['profile']==PROFILE:return ROOT
        return OriginalController.route(request)

    def start(self,request):
        self.validate_request(request)
        data=self.ledger.data;original=data['actions'].get(request['id'])
        if original is not None:
            if original['request']!=request:raise Refused('shared original ID full payload mismatch')
            return self.report(request['id'])
        if request['profile']!=PROFILE:raise Refused('historical profile effect submission unavailable')
        if not isinstance(self.plan,Plan):raise Refused('explicit survival PLAN required; old PLAN cannot submit new effects')
        if request['owner_id']!=self.owner_id:raise Refused('original owner required')
        if data['unknown_lock'] or any(r['state'] in ('PENDING','UNKNOWN') for r in data['actions'].values()):raise Refused('any-profile original action locks new dispatch')
        if len(data['actions'])>=self.MAX_ACTIONS:raise Refused('V6 shared4096 count ceiling reached')
        if self.plan is None or request['plan_version']!=4 or request['plan_sha256']!=self.plan.sha256:raise Refused('new effect requires original reviewed PLAN binding')
        observation=self._last_observation
        if observation is None or observation.get('observation_id')!=request['observation_id']:raise Refused('fresh original native observation required')
        risk=gate(observation,request,self.owner_id,data['actions'],self.plan)
        rec={'request':copy.deepcopy(request),'state':'PENDING','unknown_reasons':[],'evidence':[],
             'latest_native':None,'terminal_native':None,'stop_attempted':False,'observation':copy.deepcopy(observation),'local_risk':risk,'plan':self.plan.snapshot()}
        if len(rec['evidence']) >= self.MAX_EVIDENCE-2:raise Refused('evidence capacity exhausted; preserve ledger')
        proof=self.ledger._save_pending(rec,self.MAX_ACTIONS)
        self._exchange(rec,'start','POST',ROOT+'start',request,_capacity_proof=proof)
        return self.report(request['id'])

    def _exchange(self,rec,kind,method,path,body=None,*,_capacity_proof=None):
        if self._start_capacity_proof is not None:
            if type(_capacity_proof) is _StartCapacityProof:_capacity_proof.used=True
            raise Refused('nested capacity proof scope; no dispatch')
        if _capacity_proof is not None:
            if (type(_capacity_proof) is not _StartCapacityProof or kind!='start'
                    or method!='POST' or path!=ROOT+'start'
                    or rec['request']['profile']!=PROFILE or body!=rec['request']):
                if type(_capacity_proof) is _StartCapacityProof:_capacity_proof.used=True
                raise Refused('invalid same-start exchange; no dispatch')
            self._start_capacity_proof=_capacity_proof
        try:
            return super()._exchange(rec,kind,method,path,body)
        finally:
            if type(_capacity_proof) is _StartCapacityProof:_capacity_proof.used=True
            self._start_capacity_proof=None

    def _room(self,rec,reserved=0):
        proof=self._start_capacity_proof
        if proof is None:return super()._room(rec,reserved)
        # Consume and clear before the first transport call. Raw receipt saves,
        # subsequent status/stop, and future starts never inherit this proof.
        self._start_capacity_proof=None
        if reserved!=2:raise Refused('invalid same-start reserve; no dispatch')
        proof.consume(self.ledger,rec)
        if len(rec['evidence']) >= self.MAX_EVIDENCE-reserved:
            raise Refused('evidence capacity exhausted; preserve ledger')

    def observe(self):
        raw=self.transport.request('GET',ROOT+'observe')
        if not raw.complete or len(raw.body)>MAX_RESPONSE or raw.status!=200:raise Refused('observation unavailable')
        obs=strict_json(raw.body)
        if not isinstance(obs,dict) or set(obs)!=schema.OBS_KEYS or type(obs.get('schema_version')) is not int or obs['schema_version']!=1 or obs['profile']!=PROFILE:raise Refused('closed v6 observation required')
        schema.refusal_valid(obs['observation_refusal'],observe=True)
        observation_geometry(obs)
        primed_valid(obs)
        if obs['observation_refusal'] is not None and (obs['world_generation'] is None or obs['ready'] is not False or obs['reason']!='observation_context_changed'):raise Refused('observation refusal readiness contradiction')
        if obs['world_generation'] is None:
            if obs['client_tick'] is not None or any(obs[k] is not None for k in ('player_bbox','selected_slot','ray')) or obs['hotbar']!=[]:raise Refused('no-world nullable observation mismatch')
        else:
            if not schema.integer(obs['client_tick'],0,9007199254740991):raise Refused('native frame invalid')
            from interaction2_controller.policy import hotbar
            hotbar(obs) # unchanged metadata read, no slot/selection authority.
        survival_valid(obs)
        self._last_observation=copy.deepcopy(obs)
        return obs

    def finish_one_step(self,action_id,*,clock=time.monotonic,sleep=time.sleep):
        rec=self.ledger.data['actions'].get(action_id)
        if rec is None:raise Refused('unknown original ID')
        if rec['request']['profile']!=PROFILE or rec['request'].get('kind')!='consume_bread':
            return super().finish_one_step(action_id,clock=clock,sleep=sleep)
        # Only the new finite consume operation: report window, never a native lease renewal.
        deadline=clock()+rec['request']['ttl_ms']/1000+.5
        while rec['state']=='PENDING' and clock()<deadline and len(rec['evidence'])<self.MAX_EVIDENCE-2:
            try:self.status(action_id)
            except Refused:
                self._unknown(rec,'bounded_read_capacity_exhausted');break
            if rec['state']=='PENDING':sleep(.25)
        if rec['state']=='PENDING':self._unknown(rec,'bounded_settlement_not_observed')
        if rec['state']!='CLOSED':
            self.stop(action_id)
            self.status(action_id)
        return self.report(action_id)
