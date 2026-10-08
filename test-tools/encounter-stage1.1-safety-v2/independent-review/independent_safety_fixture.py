"""Independent FakeQueue fixtures; no real transport import or construction."""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
from independent_fixture_v2 import *
import encounter_binding as eb
import post_trial_safety as pts

ENTITIES=[dict(x,x=2.+i,y=64.,z=2.) for i,x in enumerate(SCOPE)]
def full_observation(binding=None,action=None,entities=None,paused=False,health=20):
    x=observation(binding,action)
    x['state']['player']['health']=health
    values=deepcopy(entities if entities is not None else [dict(e,alive=True,health=20.) for e in ENTITIES])
    x['state']['nearby']={'radius':8.,'total':len(values),'returned':len(values),'truncated':False,'entities':values}
    x['state']['paused']=paused;x['state']['screen_open']=paused
    x['screen']={'open':paused,**({'class':pts.PAUSE_SCREEN} if paused else {})}
    x['aim_lock']={'active':False};x['combat']={'active':False,'held_mappings':[]}
    return x
class Queue:
    def __init__(self):
        self.b=eb.bind_command(eb.build_binding('independent-case-request',R,S,W,P,action_body(),10000),command_body())
        self.obs=full_observation(self.b)
        self.calls=[];self.requests={};self.mutation_mode='ok';self.read_mode='ok';self.session_mutator=None;self.observation_mutator=None
    def session(self):
        s={'session_id':R,'bridge_identity':{'action_session':S},'state':'ready','active_request_id':None,'active_action_id':None,'pending':0,'aim_lock':{'active':False},'combat':{'active':False,'held_mappings':[]}}
        if self.session_mutator:self.session_mutator(s)
        return s
    def submit(self,body,request_id=None):
        self.calls.append(deepcopy(body));self.requests[request_id]=deepcopy(body)
        if body['op']=='direct':
            if self.mutation_mode=='submit_exception':raise OSError('synthetic ambiguity')
            if self.mutation_mode=='wrong_submit_id':return 'unexpected-id'
            if self.mutation_mode=='ok':
                if body['endpoint']=='command':
                    uid=body['body']['command'].split()[1]
                    self.obs['state']['nearby']['entities']=[e for e in self.obs['state']['nearby']['entities'] if e['uuid']!=uid]
                    n=len(self.obs['state']['nearby']['entities']);self.obs['state']['nearby'].update(total=n,returned=n)
                elif body['endpoint']=='raw-key':
                    self.obs['state'].update(paused=True,screen_open=True)
                    self.obs['screen']={'open':True,'class':pts.PAUSE_SCREEN}
        return request_id
    def wait(self,rid,timeout):
        body=self.requests[rid]
        r={'request_id':rid,'session_id':R,'status':'succeeded'}
        if body['op']=='observe':
            if self.read_mode=='exception':raise OSError('synthetic read failure')
            r['result']=deepcopy(self.obs)
            if self.observation_mutator:self.observation_mutator(r['result'])
        else:
            if self.mutation_mode=='wait_exception':raise OSError('synthetic wait ambiguity')
            r.update(reason='direct_input_dispatched',result={'ok':True,'submitted':True,'key':'key.keyboard.escape','action':'click','down':False})
            if self.mutation_mode=='pending':r['status']='pending'
            if self.mutation_mode=='failed':r['status']='failed'
            if self.mutation_mode=='uncertain':r['unknown_outcome']=True
        return r
    def result(self,rid):return None
    @property
    def mutations(self):return [x for x in self.calls if x['op']!='observe']

def configured(directory, *, resolved=True):
    root=Path(directory);out=root/'out';out.mkdir(parents=True,exist_ok=True)
    q=Queue();o=SimpleNamespace(c=q,out=out,resident=R,session=S,world=W,player=P)
    p=pts.PostTrialSafety(o,root/'queue-ledger')
    p.register_noai_case('case1',deepcopy(ENTITIES),deepcopy(q.obs),evidence_ref='synthetic-observation',noai_proof={'entities':[{'uuid':e['uuid'],'no_ai':True,'evidence_ref':'synthetic-noai'} for e in ENTITIES]},authorization_ref='explicit-synthetic-auth')
    p.reserve_trial(q.b,command_body(),'trial1');p.claim_trial_dispatch(q.b.request_id,command_body(),owned_request=q.b.request_id)
    before=deepcopy(q.obs);q.obs=full_observation(q.b,native(q.b))
    report={'name':'trial1','request_id':q.b.request_id,'binding':q.b.wire(),'command':command_body(),'samples':[], 'before':before,'after':deepcopy(q.obs),'response':receipt(q.b,native(q.b)),'interrupt_proof':None}
    (out/'trial1.json').write_text(json.dumps(report))
    if resolved:p.record_trial(report)
    return p,q,o,report
