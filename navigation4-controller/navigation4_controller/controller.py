"""Explicit v4 navigation admission; all historical profiles retain their original readers."""
import copy
from .legacy import V3Controller,V3_PROFILE,v3_schema,legacy,Refused,strict_json,encode,MAX_RESPONSE,PROFILE,ROOT
from . import schema
from .policy import gate
from .geometry import observation_geometry
from .plan import Plan,validate_snapshot


class Controller(V3Controller):
    MAX_ACTIONS=256 # Count ceiling, never a promise that 256 records fit the unchanged 8MiB ledger.

    def __init__(self,directory,transport,plan=None):
        if plan is not None and not isinstance(plan,Plan):raise Refused('loaded hash-pinned PLAN required')
        self.plan=plan
        super().__init__(directory,transport,None)
        self.plan=plan
        try:
            for record in self.ledger.data['actions'].values():
                if record['request']['profile']==PROFILE:validate_snapshot(record.get('plan'),record['request'])
        except BaseException:
            self.close();raise

    @staticmethod
    def validate_request(req):
        if not isinstance(req,dict):raise Refused('closed request object required')
        if req.get('profile')!=PROFILE:return V3Controller.validate_request(req)
        return schema.request_valid(req)

    @staticmethod
    def _validate_receipt(receipt,request):return schema.receipt_valid(receipt,request)

    @staticmethod
    def route(request):
        if request['profile']==PROFILE:return ROOT
        return V3Controller.route(request)

    def start(self,request):
        self.validate_request(request)
        data=self.ledger.data;original=data['actions'].get(request['id'])
        if original is not None:
            if original['request']!=request:raise Refused('shared original ID full payload mismatch')
            return self.report(request['id'])
        if request['profile']!=PROFILE:raise Refused('historical profile effect submission unavailable')
        if request['owner_id']!=self.owner_id:raise Refused('original owner required')
        if data['unknown_lock'] or any(r['state'] in ('PENDING','UNKNOWN') for r in data['actions'].values()):raise Refused('any-profile original action locks new dispatch')
        if len(data['actions'])>=self.MAX_ACTIONS:raise Refused('shared256 count ceiling reached')
        if self.plan is None or request['plan_version']!=2 or request['plan_sha256']!=self.plan.sha256:raise Refused('new effect requires original reviewed PLAN binding')
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
        if not isinstance(obs,dict) or set(obs)!=schema.OBS_KEYS or type(obs.get('schema_version')) is not int or obs['schema_version']!=1 or obs['profile']!=PROFILE:raise Refused('closed v4 observation required')
        schema.refusal_valid(obs['observation_refusal'],observe=True)
        observation_geometry(obs)
        if obs['observation_refusal'] is not None and (obs['world_generation'] is None or obs['ready'] is not False or obs['reason']!='observation_context_changed'):raise Refused('observation refusal readiness contradiction')
        if obs['world_generation'] is None:
            if obs['client_tick'] is not None or any(obs[k] is not None for k in ('player_bbox','selected_slot','ray')) or obs['hotbar']!=[]:raise Refused('no-world nullable observation mismatch')
        else:
            if not schema.integer(obs['client_tick'],0,9007199254740991):raise Refused('native frame invalid')
            from interaction2_controller.policy import hotbar
            hotbar(obs) # unchanged metadata read, no slot/selection authority.
        self._last_observation=copy.deepcopy(obs)
        return obs
