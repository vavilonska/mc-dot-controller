"""Independent synthetic receipt fixtures. Pure memory only; never a QueueClient."""
import copy
from receipt_binding import Binding, CONTRACT
R='a1111111-1111-4111-8111-111111111111'
S='a2222222-2222-4222-8222-222222222222'
W='a3333333-3333-4333-8333-333333333333'
P='a4444444-4444-4444-8444-444444444444'
SCOPE=[{'entity_id':101,'uuid':'b5555555-5555-4555-8555-555555555555','type':'minecraft:zombie'},
       {'entity_id':202,'uuid':'b6666666-6666-4666-8666-666666666666','type':'minecraft:zombie'}]
MODE='two_zombie_retreat_v1'
OUTCOME='two_scoped_living_zombies_beyond_8_for_3_samples'
CONTEXT=dict(resident_session=R,action_session=S,world_generation=W,player_uuid=P,action_id_contract=CONTRACT)
def base_binding(rid='independent-encounter-request'):
 return Binding(rid,R,S,W,P,'combat_entity')
def action_body():
 return {'action':'combat_entity','encounter_mode':MODE,'encounter_scope':copy.deepcopy(SCOPE),
         'target_entity_id':101,'target_uuid':SCOPE[0]['uuid'],'target_type':'minecraft:zombie',
         'approach':False,'shield':False}
def command_body():
 return {**action_body(),'op':'action','timeout_ms':10000,'expected_world_generation':W,
         'expected_action_session':S,'expected_player_uuid':P,
         'expected_navigation_epoch':7,'expected_origin':{'x':1.,'y':64.,'z':2.}}
def request_body():
 return {k:v for k,v in command_body().items() if k!='op'}
def native(b=None,status='succeeded',reason=None):
 b=b or base_binding()
 reason=reason or {'succeeded':'encounter_clearance_observed','failed':'retreat_budget_risk_remaining',
                   'cancelled':'inputs_released','running':'encounter_retreating_risk_remaining'}[status]
 encounter={'encounter_schema_version':1,'encounter_mode':MODE,'encounter_scope':copy.deepcopy(SCOPE),
            'offense_disabled':True,'risk_remaining':True,'requires_handoff':True,'safety_assured':False,
            'danger_radius':8,'clearance_observations':3 if status=='succeeded' else 0,
            'outcome_scope':OUTCOME if status=='succeeded' else None,
            'scoped_living_threats':[{**x,'known':True,'alive':True,'clearance':9.125} for x in SCOPE]}
 if status!='running':encounter.update(terminal_status=status,terminal_reason=reason)
 combat={'encounter':encounter,'attack_completed':False,'attack_dispatches':0,
         'target_dead_observed':False,'hits_confirmed':False,'server_confirmed':False,
         'safety_assured':False,'risk_remaining':True,'target_entity_id':101,
         'target_uuid':SCOPE[0]['uuid'],'target_type':'minecraft:zombie','player_health_lost_observed':0}
 return {'action_schema_version':1,'action_id':b.expected_action_id,'action_session':S,
         'action':'combat_entity','status':status,'reason':reason,'ticks':12,'ok':True,'server_confirmed':False,
         'result':{'world_generation':W,'input_release_confirmed':True,'combat':combat}}
def observation(b=None,a=None):
 b=b or base_binding()
 if a is None:
  a=native(b);a['action_id']='retained-unrelated';a['result']['combat']['attack_dispatches']=99
 return {'state':{'world':{'world_generation':W,'navigation_guard':{'epoch':7,'rebind_ready':True}},
                  'player':{'uuid':P,'x':1.,'y':64.,'z':2.,'health':20.,'yaw':0.,'pitch':0.,
                            'using_item':False,'sprinting':False},
                  'client_action':{'action_session':S},'screen_open':False,'paused':False},
         'action':copy.deepcopy(a),'status':{'held_mappings':[],'mouse':{'held_world_buttons':[]}}}
def receipt(b=None,a=None,status='succeeded',path='result.action'):
 b=b or base_binding()
 r={'request_id':b.request_id,'session_id':R,'status':status,'finished_at':100.,
    'risk_remaining':True,'requires_handoff':True,'safety_assured':False}
 if a is not None:
  if path=='result.action':r['result']={'action':copy.deepcopy(a)}
  else:r[path]=copy.deepcopy(a)
  if status!='succeeded':r['reason']=a['reason']
 return r
def rejection(b=None):
 return {**receipt(b,status='failed'),'reason':'encounter_stage1_disabled','action_id':None,
         'action':None,'resolved_action':None,'cancellation':None,'task_completed':False,
         'postcondition_observed':False,'action_step':1,'original_error':'encounter_stage1_disabled'}
class Clock:
 def __init__(self):self.t=0.
 def __call__(self):self.t+=.2;return self.t
class FakeQueue:
 def __init__(self,mode='success',mutator=None):
  self.mode=mode;self.mutator=mutator;self.calls=[];self.reads={};self.polls=0
  self.b=base_binding();self.active=False;self.terminal=False;self.interrupt=None
 def session(self):
  return {'session_id':R,'bridge_identity':{'action_session':S},'state':'ready',
          'active_request_id':None,'pending':0}
 def submit(self,body,request_id=None):
  self.calls.append(copy.deepcopy(body));self.reads[request_id]=copy.deepcopy(body)
  if body['op']=='action':
   self.active=True;self.b=base_binding(request_id)
   if self.mode=='submit_error':raise OSError('synthetic submit ambiguity')
  if body['op'] in ('cancel','direct'):self.interrupt=body['op']
  return request_id
 def action_record(self,status=None):
  status=status or ('cancelled' if self.interrupt else ('failed' if self.mode=='native_failure' else 'succeeded') if self.terminal else 'running')
  reason='direct_takeover' if self.interrupt=='direct' else None
  a=native(self.b,status,reason)
  if self.mutator:self.mutator(a)
  return a
 def current_observation(self):
  if not self.active or self.mode in ('rejected','pending'):return observation(self.b)
  if self.mode=='foreign_running' and not self.terminal:
   a=self.action_record('running');a['action_id']='foreign';return observation(self.b,a)
  return observation(self.b,self.action_record())
 def final_receipt(self):
  if self.mode=='rejected':return rejection(self.b)
  if self.mode=='unknown':return receipt(self.b,native(self.b),status='uncertain')
  if self.mode=='pending':return {'request_id':self.b.request_id,'status':'pending'}
  if self.interrupt:
   return {**receipt(self.b,status='cancelled'),
           'reason':'direct_takeover' if self.interrupt=='direct' else 'cancel_requested'}
  status='failed' if self.mode=='native_failure' else 'succeeded'
  return receipt(self.b,self.action_record(status),status=status)
 def result(self,rid):
  self.polls+=1
  if self.mode=='wait_error':raise OSError('synthetic result ambiguity')
  if self.mode=='pending':return None
  if self.mode in ('running','cancel','direct','foreign_running') and self.polls==1:return None
  self.terminal=True;return self.final_receipt()
 def wait(self,rid,timeout):
  if rid==self.b.request_id:self.terminal=True;return self.final_receipt()
  body=self.reads[rid]
  if body['op']=='observe':result=self.current_observation()
  else:result={'ok':True,'released':True}
  return {'request_id':rid,'session_id':R,'status':'succeeded','result':result,
          'reason':'direct_input_dispatched' if body['op']=='direct' else None}
