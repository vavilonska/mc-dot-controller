"""One-process ordinary travel/idle owner. Import has no HTTP, token or game effects."""
import copy
import fcntl
import http.client
import json
import math
import time
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

TERMINAL = {'succeeded', 'failed', 'cancelled'}
MELEE = {'minecraft:zombie', 'minecraft:drowned', 'minecraft:husk',
         'minecraft:zombie_villager', 'minecraft:skeleton', 'minecraft:stray',
         'minecraft:bogged', 'minecraft:spider', 'minecraft:cave_spider',
         'minecraft:magma_cube', 'minecraft:slime'}

class KnownStop(RuntimeError): pass
class UnknownInput(RuntimeError): pass

def context(s):
    return (s['world']['world_generation'], s['world']['dimension'],
            s['player']['uuid'], s['player'].get('generation'),
            s['client_action']['action_session'])

def unknown(o):
    flags={'unknown_outcome','requires_handoff','no_auto_resume',
           'requires_reconciliation_before_retry','unknown_attack_outcome'}
    if isinstance(o,dict):
        return any((k in flags and v is not False) or unknown(v) for k,v in o.items())
    if isinstance(o,list):return any(unknown(v) for v in o)
    return False

def neutral(s):
    return s.get('held_inputs',{}).get('neutral') is True and not s['player'].get('using_item')

def released_terminal(o, b):
    if o.get('action_id') != b['action_id'] or o.get('action_session') != b['expected_action_session']:
        return False
    if o.get('status') not in TERMINAL or unknown(o): return False
    r=o.get('result') or {}
    if r.get('input_release_confirmed') is True: return True
    # Exact legacy exception; never invent a release field or clear old UNKNOWN.
    if 'input_release_confirmed' in r or 'capability_guard' in b: return False
    if b.get('action') not in ('break_block','place_block','click_slot'): return False
    if o.get('reason')=='position_discontinuity_rebind_required':return False
    if any(k in b for k in ('typed_item_interaction','coordination_step','capability_route')): return False
    if b['action'] in ('place_block','click_slot') and o['status']!='succeeded':
        if r.get('dispatched',False) is not False or r.get('click_dispatched',False) is not False: return False
    return True

class HttpTransport:
    """Token supplied by the existing operator client; never reads a credential file."""
    def __init__(self, token, host='127.0.0.1', port=38121):
        if host!='127.0.0.1': raise ValueError('loopback_only')
        self.token,self.host,self.port=token,host,port
    def __call__(self, method, path, payload=None):
        # Server MC-operation budget is 5s. POST 7s covers that budget, no retry.
        h=http.client.HTTPConnection(self.host,self.port,timeout=2 if method=='GET' else 7)
        try:
            data=None if payload is None else json.dumps(payload).encode()
            h.request(method,path,data,{'Authorization':'Bearer '+self.token,'Content-Type':'application/json'})
            r=h.getresponse(); return r.status,json.loads(r.read())
        finally: h.close()

class Supervisor:
    def __init__(self, client, transport, classify_preinput, *, weapon_slot,
                 lock_path, clock=time.monotonic, sleep=time.sleep):
        if type(weapon_slot) is not int or not 0<=weapon_slot<=8: raise ValueError('weapon_slot')
        self.c,self.transport,self.classify=client,transport,classify_preinput
        self.clock,self.sleep=clock,sleep;self.weapon_slot=weapon_slot
        self.lock_path=Path(lock_path);self.lock=None;self.previous_request=None
        self.ctx=None;self.last=None;self.last_at=-math.inf
        self.pending=None;self.raw_pending=None;self.held_use=False;self.use_binding=None
        self.last_resolution=None;self.mode='UNARMED';self.reason='not_started'
        self.last_published=None
        self.handoff_file=None;self.mission_active=False
    def handoff_requested(self):return self.handoff_file is not None and self.handoff_file.exists()
    def note(self,event,**values):
        # A disk/log failure must not discard the already received HTTP reply.
        try: self.c.note(event,**values)
        except Exception: pass
    def publish(self):
        row={'mode':self.mode,'reason':self.reason,'context':self.ctx,
             'pending_action_id':self.pending['body']['action_id'] if self.pending else None,
             'raw_unknown_path':self.raw_pending['path'] if self.raw_pending else None,
             'known_owned_use_held':self.held_use,'monotonic':self.clock()}
        row['known_use_binding']=copy.deepcopy(self.use_binding)
        try:(self.c.out/'SUPERVISOR-STATUS.json').write_text(json.dumps(row))
        except Exception:pass
        summary=(row['mode'],row['pending_action_id'],row['raw_unknown_path'])
        if summary!=self.last_published:
            self.last_published=summary;self.note('supervisor_status',**row)
    def install(self):
        self.lock_path.parent.mkdir(parents=True,exist_ok=True)
        self.lock=self.lock_path.open('a+')
        try: fcntl.flock(self.lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BaseException: self.lock.close();self.lock=None;raise
        self.previous_request=self.c.request;self.c.request=self.request
        try:
            s=self.state(0)
            if not self.available(s) or not neutral(s): raise KnownStop('arm_requires_alive_idle_neutral')
            a=s['client_action']
            if a.get('status') in TERMINAL and a.get('result',{}).get('input_release_confirmed') is not True:
                raise KnownStop('initial_last_terminal_requires_release_evidence_before_new_owner')
            self.ctx=context(s);self.mode='MISSION';return self
        except BaseException: self.close();raise
    def close(self):
        if self.previous_request is not None:self.c.request=self.previous_request;self.previous_request=None
        if self.lock is not None:fcntl.flock(self.lock,fcntl.LOCK_UN);self.lock.close();self.lock=None
    def available(self,s):
        p=s.get('player',{});a=s.get('client_action',{})
        r=a.get('result') or {}
        return (s.get('private_singleplayer') is True and p.get('alive') is True
                and isinstance(p.get('health'),(int,float)) and math.isfinite(p['health']) and p['health']>0
                and not s.get('paused') and not s.get('screen_open')
                and a.get('status')!='running' and a.get('input_owner')=='direct' and not unknown(a)
                and ('input_release_confirmed' not in r or r['input_release_confirmed'] is True)
                and (self.ctx is None or context(s)==self.ctx))
    def state(self,radius=16):
        code,s=self.request('GET','/control/state?radius='+str(radius))
        if code!=200: raise KnownStop('state_http_'+str(code))
        return s
    def _fresh(self):
        s=self.last if self.clock()-self.last_at<=.5 else self.state(0)
        if not self.available(s): raise KnownStop('current_owner_or_context_not_available')
        return s
    def _owned_inputs(self,s):
        if neutral(s): return True
        h=s.get('held_inputs',{})
        # Mouse button count is not itself ownership. Only our exact successful
        # down receipt, sent from neutral, can authorize this non-neutral state.
        return (self.held_use and self.use_binding is not None
                and set(h.get('keys',[]))=={'key.use'}
                and h.get('raw_keys')==0 and h.get('world_mouse_buttons')==1)
    def _reconcile(self,s):
        p=self.pending
        if not p or not self.available(s) or not neutral(s): return
        if p.get('exists_after_pre'):return
        b=p['body'];st=p.get('status')
        if isinstance(st,dict) and released_terminal(st,b):
            self.last_resolution={'action_id':b['action_id'],'known':True,'status':st['status'],'terminal':st}
        elif p.get('pre') and p.get('absent'):
            self.last_resolution={'action_id':b['action_id'],'known':True,'status':'not_dispatched',
                                  'original_response':p['reply'],'original_status':p['absent']}
        else:return
        self.note('supervisor_original_resolved',**self.last_resolution);self.pending=None
    def request(self,method,path,payload=None):
        if method=='GET':
            code,obj=self.transport(method,path,payload)
            self.note('supervisor_http',method=method,path=path,http_status=code,body=obj)
            p=self.pending
            if p and urlsplit(path).path=='/control/action/status':
                q=parse_qs(urlsplit(path).query)
                if q.get('action_id')==[p['body']['action_id']]:
                    if code==200 and isinstance(obj,dict):
                        p['status']=copy.deepcopy(obj)
                        if p.get('pre'):p['exists_after_pre']=True
                    if code==404 and obj.get('error')=='action_not_found':p['absent']=copy.deepcopy(obj)
            if code==200 and urlsplit(path).path=='/control/state':
                self.last=copy.deepcopy(obj);self.last_at=self.clock();self._reconcile(obj)
            return code,obj
        if method!='POST':raise KnownStop('unsupported_mutation_method')
        if self.raw_pending:raise UnknownInput('original_raw_input_unresolved_no_new_input')
        if path=='/control/action/cancel':return self._cancel(payload)
        if self.mission_active and self.handoff_requested():
            if not (path=='/control/key' and payload.get('mapping')=='key.use' and payload.get('action')=='up' and self.held_use):
                raise KnownStop('explicit_handoff_no_next_mission_input')
        if self.pending:raise UnknownInput('original_action_unresolved_no_new_input')
        if path not in ('/control/action','/control/key','/control/look'):raise KnownStop('mutation_not_in_runtime_scope')
        if path=='/control/key' and payload.get('action') in ('down','up') and payload.get('mapping')!='key.use':
            raise KnownStop('only_use_key_hold_is_owned_use_native_actions_for_travel')
        s=self._fresh()
        if not self._owned_inputs(s):raise KnownStop('foreign_held_inputs')
        if path=='/control/action':
            if not neutral(s):raise KnownStop('action_requires_neutral')
            if type(payload.get('timeout_ms')) not in (int,float) or not 50<=payload['timeout_ms']<=600000:
                raise KnownStop('explicit_finite_action_timeout_required')
            for key,value in (('expected_world_generation',self.ctx[0]),('expected_player_uuid',self.ctx[2]),('expected_action_session',self.ctx[4])):
                if payload.get(key)!=value:raise KnownStop('action_identity_mismatch_'+key)
            self.pending={'body':copy.deepcopy(payload),'before':copy.deepcopy(s),'reply':None,'pre':False,
                          'started':self.clock(),'cancel_sent':False,'deadline':self.clock()+payload.get('timeout_ms',15000)/1000+5}
        else:self.raw_pending={'path':path,'body':copy.deepcopy(payload),'before':copy.deepcopy(s)}
        # The pending record exists BEFORE transport, including synchronous failures.
        self.note('supervisor_before_post',path=path,body=payload)
        try:code,obj=self.transport(method,path,payload)
        except BaseException:
            self.note('supervisor_post_uncertain',path=path);raise
        if path=='/control/action':
            p=self.pending;p['reply']={'http_status':code,'body':copy.deepcopy(obj)}
            p['pre']=self.classify(code,obj,p['body'])
            if code in (200,202):p['status']=copy.deepcopy(obj)
        elif code==200 and isinstance(obj,dict) and obj.get('ok') is True:
            if path=='/control/key' and payload.get('mapping')=='key.use':
                if payload.get('action')=='down':
                    if not (neutral(s) and not self.held_use and obj.get('mapping')=='key.use'
                            and obj.get('action')=='down' and obj.get('scope')=='world'
                            and obj.get('key_type')=='mouse' and type(obj.get('button')) is int
                            and 0<=obj['button']<=7 and obj.get('was_down') is False
                            and obj.get('down') is True and obj.get('mapping_down') is True):
                        raise UnknownInput('known_use_delivery_but_ownership_receipt_unproven')
                    self.use_binding={k:copy.deepcopy(obj[k]) for k in ('mapping','key_type','button','was_down','down','mapping_down')}
                    self.held_use=True
                elif payload.get('action')=='up':
                    if self.held_use and not (self.use_binding is not None
                            and obj.get('mapping')=='key.use' and obj.get('action')=='up'
                            and obj.get('scope')=='world' and obj.get('key_type')=='mouse'
                            and type(obj.get('button')) is int
                            and obj.get('button')==self.use_binding['button']
                            and obj.get('down') is False and obj.get('mapping_down') is False):
                        raise UnknownInput('owned_use_release_not_confirmed_no_reissue')
                    self.held_use=False;self.use_binding=None
            self.raw_pending=None
        self.note('supervisor_http',method=method,path=path,http_status=code,body=obj)
        return code,obj
    def _cancel(self,payload):
        p=self.pending
        if not p or p['cancel_sent']:raise UnknownInput('no_confirmed_running_original_to_cancel')
        if p.get('pre') or p.get('exists_after_pre'):raise UnknownInput('preinput_id_may_belong_to_old_request_read_only')
        if payload.get('action_id')!=p['body']['action_id'] or payload.get('expected_action_session')!=self.ctx[4]:raise UnknownInput('cancel_wrong_original')
        code,st=self.request('GET','/control/action/status?action_id='+p['body']['action_id'])
        s=self.state(0);a=s['client_action']
        if (code!=200 or st.get('status')!='running' or st.get('action_id')!=p['body']['action_id']
                or st.get('action_session')!=self.ctx[4] or context(s)!=self.ctx
                or a.get('status')!='running' or a.get('action_id')!=p['body']['action_id']):
            raise UnknownInput('cancel_requires_fresh_exact_active_original')
        p['cancel_sent']=True
        self.note('supervisor_cancel_original_once',action_id=p['body']['action_id'])
        return self.transport('POST','/control/action/cancel',payload)
    def resolve_step(self,handoff=False):
        if self.raw_pending:
            self.state(0);self.mode='UNKNOWN_RAW_READ_ONLY';return
        p=self.pending
        if not p:return
        self.request('GET','/control/action/status?action_id='+p['body']['action_id'])
        self.state(0)
        if self.pending is None:return
        if not p.get('pre') and not p.get('exists_after_pre') and p.get('status',{}).get('status')=='running' and not p['cancel_sent'] and (handoff or self.clock()>=p['deadline']):
            self._cancel({'action_id':p['body']['action_id'],'expected_action_session':p['body']['expected_action_session']})
        self.mode='ORIGINAL_ID_READ_ONLY'
    def action_once(self,body):
        """Mission helper: one POST; known refusal/failure goes to run()'s guard loop."""
        self.request('POST','/control/action',body)
        while self.pending:
            try:self.resolve_step(self.handoff_requested())
            finally:self.publish()
            if self.pending:self.sleep(.1)
        if self.handoff_requested():raise KnownStop('explicit_handoff_after_original_closed')
        r=self.last_resolution
        if not r or r.get('status')!='succeeded':raise KnownStop('action_ended:'+str(r and r.get('status')))
        return r['terminal']
    def key(self,mapping,action='click'):
        code,obj=self.request('POST','/control/key',{'mapping':mapping,'action':action,'exact':False})
        if code!=200 or obj.get('ok') is not True:raise UnknownInput('key_response_not_confirmed')
    def shield(self,wanted,s):
        if wanted and s['player'].get('offhand',{}).get('id')!='minecraft:shield':return
        if wanted!=self.held_use:self.key('key.use','down' if wanted else 'up')
    @staticmethod
    def hit_ready(s,uid):
        p=s['player'];ch=s.get('crosshair',{});h=ch.get('location',{});eye=p.get('eye_position',{})
        return (ch.get('type')=='entity' and ch.get('uuid')==uid and not p.get('using_item')
                and p.get('mainhand',{}).get('id','').endswith(('_sword','_axe'))
                and p.get('attack_strength',0)>=.95 and all(k in h and k in eye for k in ('x','y','z'))
                and math.dist([h[k] for k in ('x','y','z')],[eye[k] for k in ('x','y','z')])<=min(3.,p.get('entity_interaction_range',3.)))
    def defend_step(self):
        s=self.state(16)
        if not self.available(s) or not self._owned_inputs(s):raise KnownStop('defense_owner_or_context_changed')
        item=next((v for v in s['player'].get('inventory',[]) if v.get('slot')==self.weapon_slot),{})
        if not item.get('id','').endswith(('_sword','_axe')):
            self.shield(False,s);self.mode='NO_CONFIRMED_WEAPON_NO_USE';return
        if s['player'].get('selected_slot')!=self.weapon_slot:
            self.shield(False,s);self.key('key.hotbar.'+str(self.weapon_slot+1));s=self.state(16)
        if s['player'].get('selected_slot')!=self.weapon_slot or not s['player'].get('mainhand',{}).get('id','').endswith(('_sword','_axe')):
            self.mode='WEAPON_SELECTION_NOT_YET_OBSERVED';return
        p=s['player'];self.shield(True,s)
        es=[e for e in s.get('nearby',{}).get('entities',[]) if e.get('type') in MELEE
            and e.get('alive') is True and e.get('line_of_sight') is True and e.get('distance',math.inf)<=5]
        if not es:self.mode='GUARDING';return
        e=min(es,key=lambda x:x['distance']);bb=e['bounding_box'];eye=p['eye_position']
        d=[(bb['min'][k]+bb['max'][k])/2-eye[k] for k in ('x','y','z')]
        code,obj=self.request('POST','/control/look',{'yaw':math.degrees(math.atan2(-d[0],d[2])),
            'pitch':-math.degrees(math.atan2(d[1],math.hypot(d[0],d[2]))),'relative':False})
        if code!=200 or obj.get('ok') is not True:raise UnknownInput('look_not_confirmed')
        s=self.state(16)
        item=next((v for v in s['player'].get('inventory',[]) if v.get('slot')==self.weapon_slot),{})
        if not item.get('id','').endswith(('_sword','_axe')):self.mode='NO_CONFIRMED_WEAPON_SHIELD_ONLY';return
        if s['player'].get('selected_slot')!=self.weapon_slot:
            self.shield(False,s);self.key('key.hotbar.'+str(self.weapon_slot+1));s=self.state(16)
        # Inspect the target/ray/cooldown with shield still up, then recheck after lowering.
        probe=copy.deepcopy(s);probe['player']['using_item']=False
        if self.hit_ready(probe,e['uuid']):
            self.shield(False,s);s=self.state(16)
            still_target=any(v.get('uuid')==e['uuid'] and v.get('type')==e['type'] and v.get('alive') is True
                             for v in s.get('nearby',{}).get('entities',[]))
            if self.available(s) and still_target and self.hit_ready(s,e['uuid']):self.key('key.attack')
        s=self.state(0);self.shield(True,s);self.mode='GUARDING'
    def cycle(self,handoff=False):
        try:
            if self.pending or self.raw_pending:self.resolve_step(handoff);return False
            s=self.state(0)
            if context(s)!=self.ctx:self.mode='CONTEXT_CHANGED_NO_RESUME';return True
            if not s['player'].get('alive'):self.mode='DEAD_NO_RESUME';return True
            if handoff:
                if not self.available(s) or not self._owned_inputs(s):raise KnownStop('handoff_owner_not_confirmed')
                self.shield(False,s);s=self.state(0)
                if not neutral(s):raise KnownStop('handoff_release_not_observed')
                self.mode='HANDOFF_NEUTRAL';return True
            self.defend_step()
        except Exception as e:
            self.mode='UNKNOWN_READ_ONLY' if self.pending or self.raw_pending else 'OBSERVATION_UNAVAILABLE_GUARD_PENDING'
            self.reason=type(e).__name__+':'+str(e);self.note('supervisor_cycle_error',mode=self.mode,reason=self.reason)
        finally:self.publish()
        return False
    def run(self,mission,handoff_file):
        self.handoff_file=Path(handoff_file)
        self.install()
        interrupted=False
        try:
            self.mission_active=True
            try:mission()
            except BaseException as e:
                interrupted=isinstance(e,(KeyboardInterrupt,SystemExit))
                self.note('supervisor_mission_ended',error=type(e).__name__+':'+str(e))
            finally:self.mission_active=False
            # Both success and every mission failure reach the SAME owner loop.
            while True:
                try:
                    if self.cycle(interrupted or Path(handoff_file).exists()):break
                    self.sleep(.2)
                except BaseException as e:
                    # Ctrl+C during a read/defense/sleep requests a safe handoff;
                    # it must not discard pending ownership or blindly release inputs.
                    interrupted=True
                    self.note('supervisor_interrupt_requests_handoff',error=type(e).__name__+':'+str(e))
            self.note('supervisor_terminal',mode=self.mode,reason=self.reason)
            return self.mode
        finally:self.close()
