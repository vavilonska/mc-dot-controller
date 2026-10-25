"""Finite new-profile actions share historical ownership, dedup and UNKNOWN lock."""
import base64
import copy
from .legacy import legacy, Refused, strict_json, MAX_RESPONSE
from .journal import JournalController, NEW_PROFILE, NEW_ROOT
from . import schema
from .policy import gate


class Controller(JournalController):
    @staticmethod
    def validate_request(req):
        if not isinstance(req,dict):raise Refused('closed request object required')
        if req.get('profile')==legacy.PROFILE:return legacy.request_valid(req)
        return schema.request_valid(req)

    @staticmethod
    def _validate_receipt(receipt,request):return schema.receipt_valid(receipt,request)

    def _exchange(self,rec,kind,method,path,body=None):
        if rec['request']['profile']==legacy.PROFILE:
            return super()._exchange(rec,kind,method,path,body)
        reserve=2 if kind=='start' or (kind=='status' and rec['state']!='CLOSED' and not rec['stop_attempted']) else 1 if kind=='stop' else 0
        self._room(rec,reserve)
        try:raw=self.transport.request(method,path,body)
        except Exception:
            self._unknown(rec,kind+'_transport_uncertain');return None
        rec['evidence'].append({'kind':kind,'http_status':raw.status,'complete':raw.complete,'raw_base64':base64.b64encode(raw.body[:MAX_RESPONSE]).decode('ascii')})
        self.ledger.save()
        try:
            if not raw.complete or len(raw.body)>MAX_RESPONSE or not 200<=raw.status<300:raise Refused('incomplete or unsuccessful receipt')
            receipt=strict_json(raw.body);self._validate_receipt(receipt,rec['request'])
            previous=rec['latest_native']
            if previous is not None and (receipt['applied_calls']<previous['applied_calls'] or receipt['cancellation_generation']<previous['cancellation_generation']):raise Refused('native evidence regressed')
        except (Refused,KeyError,TypeError):
            self._unknown(rec,kind+'_receipt_uncertain');return None
        rec['latest_native']=receipt
        if receipt['unknown_lock'] or receipt['state']=='UNKNOWN':self._unknown(rec,kind+'_native_unknown')
        elif kind!='stop' and rec['state']!='UNKNOWN' and receipt['state']=='SETTLED' and receipt['release_proven'] and receipt['protocol_terminal']:
            rec['state']='CLOSED'
            if rec.get('terminal_native') is None:rec['terminal_native']=copy.deepcopy(receipt)
            self.ledger.save()
        else:self.ledger.save()
        return receipt

    def start(self,request):
        self.validate_request(request)
        data=self.ledger.data
        original=data['actions'].get(request['id'])
        if original is not None:
            if original['request']!=request:raise Refused('shared original ID payload/profile/kind mismatch')
            return self.report(request['id'])
        if request['profile']!=NEW_PROFILE:raise Refused('legacy effect submission is unavailable in successor')
        if request['owner_id']!=self.owner_id:raise Refused('original owner required')
        if data['unknown_lock'] or any(r['state'] in ('PENDING','UNKNOWN') for r in data['actions'].values()):raise Refused('any-profile original action blocks new dispatch')
        if len(data['actions'])>=self.MAX_ACTIONS:raise Refused('shared history capacity exhausted')
        observation=self._last_observation
        if observation is None or observation.get('observation_id')!=request['observation_id']:raise Refused('fresh original native observation required')
        risk=gate(observation,request,self.owner_id,data['actions'])
        rec={'request':copy.deepcopy(request),'state':'PENDING','unknown_reasons':[],'evidence':[],
             'latest_native':None,'terminal_native':None,'stop_attempted':False,'observation':copy.deepcopy(observation),'local_risk':risk}
        self._room(rec,2)
        data['actions'][request['id']]=rec
        self.ledger.save() # Complete file+directory fsync before first possible gameplay POST.
        self._exchange(rec,'start','POST',NEW_ROOT+'start',request)
        return self.report(request['id'])

    def observe(self):
        raw=self.transport.request('GET',NEW_ROOT+'observe')
        if not raw.complete or len(raw.body)>MAX_RESPONSE or raw.status!=200:raise Refused('observation unavailable')
        obs=strict_json(raw.body)
        if not isinstance(obs,dict) or set(obs)!=schema.OBS_KEYS or type(obs.get('schema_version')) is not int or obs['schema_version']!=1 or obs['profile']!=NEW_PROFILE:raise Refused('closed interaction observation required')
        if obs['world_generation'] is None:
            if obs['client_tick'] is not None or any(obs[k] is not None for k in ('player_bbox','selected_slot','ray')) or obs['hotbar']!=[]:raise Refused('no-world nullable observation mismatch')
        elif not schema.integer(obs['client_tick'],0,9007199254740991):raise Refused('native frame identity invalid')
        self._last_observation=copy.deepcopy(obs)
        return obs
