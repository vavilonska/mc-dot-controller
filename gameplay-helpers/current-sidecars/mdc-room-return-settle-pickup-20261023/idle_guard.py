#!/usr/bin/env python3
"""Explicit, exclusive idle watch; one known-route retreat, never an unknown-action replay."""
import argparse, copy, datetime, hashlib, http.client, json, math, time, uuid
from pathlib import Path

B = Path('/workspace/scratch/5f333e5a575b')
TOKEN = B/'MDC-RECOVERY-LIVE-F1220-20261022/polymc-data/instances/MDC-RECOVERY-F1220-20261022/minecraft/config/mineclient-bridge.token'
TERMINAL = {'succeeded','failed','cancelled'}
HOSTILES = {'blaze','wither_skeleton','skeleton','stray','bogged','zombie','husk','zombie_villager','ghast','creeper','spider','cave_spider','wither','witch','evoker','vindicator','pillager','slime','magma_cube','phantom','endermite','silverfish','hoglin','piglin_brute'}
PROJECTILES = {'small_fireball','fireball','wither_skull','dragon_fireball','shulker_bullet','arrow','spectral_arrow','trident'}

class Refused(Exception): pass

def context(s):
    return dict(world_generation=s['world']['world_generation'],player_uuid=s['player']['uuid'],
                player_generation=s['player'].get('generation'),action_session=s['client_action']['action_session'])
def point(p): return {k:p[k] for k in ('x','y','z')}
def distance(a,b): return math.dist([a[k] for k in ('x','y','z')],[b[k] for k in ('x','y','z')])
def position_ok(p): return isinstance(p,dict) and all(type(p.get(k)) in (int,float) and math.isfinite(p[k]) for k in ('x','y','z'))
def valid_world(s): return s.get('private_singleplayer') is True and not s.get('paused') and not s.get('screen_open')
def neutral(s): return s.get('held_inputs',{}).get('neutral') is True and not s['player'].get('using_item')
def active(s): return s['client_action'].get('status')=='running'
def health(s):
    n=s['player']['health']
    if type(n) not in (int,float) or not math.isfinite(n): raise Refused('invalid_health')
    return n

def validate(cfg):
    if cfg.get('arm') is not True or cfg.get('exclusive_control') is not True: raise Refused('explicit_arm_and_exclusive_control_required')
    if cfg.get('known_tunnel') is not True or not cfg.get('route_evidence'): raise Refused('explicit_known_route_evidence_required')
    c=cfg.get('expected_context')
    if not isinstance(c,dict) or set(c)!={'world_generation','player_uuid','player_generation','action_session'} or any(not isinstance(v,str) or not v for v in c.values()): raise Refused('fresh_exact_context_required')
    points=cfg.get('waypoints')
    if not isinstance(points,list) or not points or len(points)>64 or not all(position_ok(p) for p in points): raise Refused('explicit_finite_retreat_waypoints_required')
    if not position_ok(cfg.get('cover_anchor')) or not position_ok(cfg.get('exposure_origin')): raise Refused('explicit_origin_and_cover_required')
    if distance(points[-1],cfg['cover_anchor'])>.05: raise Refused('last_waypoint_must_be_cover')
    if type(cfg.get('retreat_timeout_ms',15000)) is not int or not 50<=cfg.get('retreat_timeout_ms',15000)<=30000: raise Refused('bounded_retreat_timeout_required')
    for key,default,lo,hi in [('origin_tolerance',1.25,.1,3),('threat_radius',16,1,32),('projectile_radius',24,1,32)]:
        n=cfg.get(key,default)
        if type(n) not in (int,float) or not math.isfinite(n) or not lo<=n<=hi: raise Refused('invalid_'+key)
    if 'closure_actions' in cfg:
        actions=cfg['closure_actions']
        if cfg.get('closure_verified') is not True or not cfg.get('closure_evidence'):
            raise Refused('actual_closure_pose_rays_order_must_be_verified')
        if not isinstance(actions,list) or len(actions)!=2:raise Refused('exactly_two_explicit_closure_placements_required')
        offsets={'up':(0,1,0),'down':(0,-1,0),'north':(0,0,-1),'south':(0,0,1),'east':(1,0,0),'west':(-1,0,0)}
        for a in actions:
            if not isinstance(a,dict) or set(a)-{'action','target','support','face','hotbar_slot','timeout_ms','sneak','jump','expected_block_id'}:
                raise Refused('invalid_explicit_closure_fields')
            if a.get('action')!='place_block' or a.get('face') not in offsets or a.get('jump',False) is not False:
                raise Refused('closure_is_only_nonjump_ordinary_placement')
            for key in ('target','support'):
                if not isinstance(a.get(key),dict) or set(a[key])!={'x','y','z'} or any(type(v) is not int for v in a[key].values()):
                    raise Refused('closure_requires_exact_block_cells')
            if a['target']!={k:a['support'][k]+d for k,d in zip(('x','y','z'),offsets[a['face']])}:
                raise Refused('closure_target_support_face_mismatch')
            if type(a.get('hotbar_slot')) is not int or not 0<=a['hotbar_slot']<=8:raise Refused('closure_requires_explicit_hotbar_slot')
            if type(a.get('timeout_ms',5000)) is not int or not 50<=a.get('timeout_ms',5000)<=10000:raise Refused('closure_timeout_out_of_range')
            if not isinstance(a.get('expected_block_id'),str) or not a['expected_block_id'].startswith('minecraft:'):
                raise Refused('closure_requires_actual_expected_block_id')
    return cfg

def threats(s,cfg):
    out=[]
    for e in s.get('nearby',{}).get('entities',[]):
        if not position_ok(e) or e.get('alive') is False: continue
        kind=e.get('type','').removeprefix('minecraft:');d=distance(s['player'],e)
        if (kind in PROJECTILES and d<=cfg.get('projectile_radius',24)) or (kind in HOSTILES and d<=cfg.get('threat_radius',16)):
            out.append(dict(e,distance=d,projectile=kind in PROJECTILES))
    return sorted(out,key=lambda e:(not e['projectile'],e['distance']))

def trigger(s,cfg,previous_health):
    if not s['player'].get('alive') or health(s)<=0: return 'player_dead'
    for k in ('in_lava','on_fire','in_water','eye_in_water','in_powder_snow'):
        if s['player'].get(k): return k
    if health(s)<previous_health: return 'health_decreased'
    nearby=threats(s,cfg)
    if nearby: return 'multiple_threats' if len(nearby)>1 else 'projectile_near' if nearby[0]['projectile'] else 'hostile_near'
    return None

def aim(s,e):
    p=point(e);box=e.get('bounding_box')
    if isinstance(box,dict) and position_ok(box.get('min')) and position_ok(box.get('max')):
        p={k:(box['min'][k]+box['max'][k])/2 for k in ('x','y','z')}
    eye=s['player'].get('eye_position')
    if not position_ok(eye): raise Refused('eye_position_unavailable')
    dx,dy,dz=(p[k]-eye[k] for k in ('x','y','z'))
    return dict(yaw=math.degrees(math.atan2(-dx,dz)),pitch=-math.degrees(math.atan2(dy,math.hypot(dx,dz))),relative=False)

class Client:
    def __init__(self,out): self.out=out;self.token=TOKEN.read_text().strip()
    def note(self,event,**values):
        record=dict(values);record.setdefault('utc',datetime.datetime.now(datetime.timezone.utc).isoformat());record['event']=event
        with (self.out/'events.jsonl').open('a') as f: f.write(json.dumps(record,separators=(',',':'))+'\n')
    def request(self,method,path,body=None):
        if method=='POST': self.note('one_shot_request',method=method,path=path,body=body)
        h=http.client.HTTPConnection('127.0.0.1',38121,timeout=2 if method=='GET' else 5)
        try:
            h.request(method,path,None if body is None else json.dumps(body).encode(),{'Authorization':'Bearer '+self.token,'Content-Type':'application/json'})
            r=h.getresponse();value=json.loads(r.read())
            if path!='/control/state?radius=32': self.note('response',path=path,http_status=r.status,body=value)
            return r.status,value
        except Exception as e:
            self.note('read_failed' if method=='GET' else 'request_uncertain_no_reissue',path=path,error=type(e).__name__)
            raise
        finally:h.close()
    def state(self):
        code,s=self.request('GET','/control/state?radius=32')
        if code!=200:raise Refused('state_unavailable')
        return s

def native_ready(s):
    return s.get('world',{}).get('navigation_guard',{}).get('rebind_ready') is True

def bound_pre_input_rejection(code,obj,body):
    if code not in (400,409) or not isinstance(obj,dict):return False
    p=obj.get('native_admission')
    if not isinstance(p,dict):return False
    digest=hashlib.sha256(json.dumps(body,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()).hexdigest()
    return (p.get('boundary_schema_version')==2 and type(p.get('boundary_schema_version'))is int
        and p.get('ordinary_start_entered') is True and p.get('input_transfer_entered') is False
        and p.get('registration_entered') is False and p.get('reentry_observed') is False
        and p.get('stage') in ('validation','hooks_possible') and p.get('dispatch_authority') is False and p.get('retry_authority') is False
        and isinstance(obj.get('error'),str) and p.get('reason')==obj['error']
        and p.get('action_id')==body['action_id'] and p.get('action')==body['action']
        and p.get('action_session')==body['expected_action_session']
        and p.get('digest_format')=='sorted-json-utf8/1' and p.get('request_payload_sha256')==digest)

class Watch:
    def __init__(self,c,cfg,first):
        self.c=c;self.cfg=validate(cfg);self.phase='ARMED';self.reason='idle_watch';self.retreat_sent=False
        self.admission_response=None;self.admission_deadline=None;self.admission_replacements=0;self.rejected_unregistered=[]
        self.body=None;self.pending=False;self.cancel_sent=False;self.stop_requested=False;self.stop_reason=None
        self.segment_index=0;self.completed_segments=[]
        self.handoff_deadline=None
        self.closure_index=0;self.closure_confirmed_ids=[];self.closure_confirmed=False
        self.closure_navigation_rejected=False
        self.shield_attempted=False;self.shield_release_sent=False;self.input_uncertain=False;self.terminal=None;self.done=False
        if context(first)!=cfg['expected_context'] or not valid_world(first):raise Refused('arm_context_or_world_mismatch')
        if active(first) or not neutral(first):raise Refused('arm_requires_idle_neutral')
        if not first['player'].get('alive') or health(first)<=0:raise Refused('arm_requires_alive_valid_health')
        if distance(first['player'],cfg['exposure_origin'])>cfg.get('origin_tolerance',1.25):raise Refused('arm_outside_verified_route_origin')
        self.previous_health=health(first);self.c.note('armed',context=context(first),pose=point(first['player']),known_route=cfg['waypoints'])
    def needs(self,reason):
        if self.phase!='NEEDS_OPERATOR' or self.reason!=reason:self.c.note('needs_operator',reason=reason)
        self.phase='NEEDS_OPERATOR';self.reason=reason
    def matching(self,o):return isinstance(o,dict) and self.body and o.get('action_id')==self.body['action_id'] and o.get('action_session')==self.body['expected_action_session']
    def finish_if_terminal(self,o,s):
        if self.body and self.body.get('action')=='place_block':return self.finish_closure_terminal(o)
        if not self.matching(o) or o.get('status') not in TERMINAL:return False
        self.terminal=o;r=o.get('result') if isinstance(o.get('result'),dict) else {};released=r.get('input_release_confirmed') is True
        uncertain=r.get('unknown_outcome') or r.get('requires_handoff')
        if not released:self.needs('original_terminal_release_unproven');return True
        self.pending=False
        if uncertain:self.needs('original_effect_unknown_no_reissue');return True
        if self.stop_requested:self.needs(self.stop_reason or 'disarm_requested');return True
        if context(s)!=self.cfg['expected_context'] or not valid_world(s):self.needs('context_or_world_changed');return True
        if o['status']=='succeeded':
            if self.segment_index+1<len(self.cfg['waypoints']):
                if self.handoff_deadline is None:self.handoff_deadline=time.monotonic()+3
                self.phase='SEGMENT_CHECK';self.reason='segment_settled_released_waiting_fresh_frame'
            else:
                self.phase='COVER_CHECK';self.reason='terminal_released_waiting_cover_frame'
                if distance(s['player'],self.cfg['cover_anchor'])<=.8 and not active(s):self.confirm_cover(s)
        else:self.needs('retreat_known_'+o['status']+'_no_replan')
        return True
    def confirm_cover(self,s):
        if active(s):self.needs('unexpected_input_owner_after_retreat');return
        if distance(s['player'],self.cfg['cover_anchor'])>.8:self.needs('retreat_ended_outside_cover_no_replan');return
        if self.cfg.get('closure_actions') and not self.closure_confirmed:
            self.admission_deadline=None;self.admission_replacements=0
            self.phase='CLOSURE_READY';self.reason='at_anchor_two_explicit_blocks_pending';return
        self.needs('retreated_to_cover_observed_risk_remaining');self.cover_shield(s)
    def ready_before_new_input(self,s,kind):
        if self.admission_deadline is None:self.admission_deadline=time.monotonic()+3
        if context(s)!=self.cfg['expected_context'] or not valid_world(s) or not s['player'].get('alive') or health(s)<=0:
            self.needs('navigation_wait_context_or_player_changed');return False
        if active(s) or not neutral(s):self.needs('navigation_wait_input_not_released');return False
        if time.monotonic()>self.admission_deadline:
            self.needs('navigation_wait_or_admission_deadline_exceeded_no_new_input');return False
        if not native_ready(s):
            self.phase='NAV_WAIT_'+kind;self.reason='waiting_native_rebind_ready';return False
        return True
    def original_pre_input_rejection(self):
        a=self.admission_response
        return isinstance(a,dict) and self.body is not None and bound_pre_input_rejection(a.get('http_status'),a.get('body'),self.body)
    def confirm_unregistered(self,s,o):
        if not self.original_pre_input_rejection() or not isinstance(o,dict) or o.get('error')!='action_not_found':return False
        if context(s)!=self.cfg['expected_context'] or not valid_world(s) or not s['player'].get('alive') or active(s) or not neutral(s):return False
        record=dict(action_id=self.body['action_id'],request=copy.deepcopy(self.body),original_response=copy.deepcopy(self.admission_response),original_status=copy.deepcopy(o),interpretation='request_not_registered_before_input_boundary_not_global_no_effect')
        self.rejected_unregistered.append(record);self.c.note('original_request_unregistered_no_reissue',**record)
        self.pending=False;self.terminal=copy.deepcopy(self.admission_response['body'])
        if self.stop_requested:self.needs(self.stop_reason or 'explicit_disarm');return True
        if self.admission_replacements>=1 or time.monotonic()>self.admission_deadline:
            self.needs('known_unregistered_admission_budget_exhausted');return True
        self.admission_replacements+=1
        self.phase='NAV_WAIT_CLOSURE' if self.body['action']=='place_block' else 'NAV_WAIT_SEGMENT'
        self.reason='known_unregistered_wait_fresh_native_ready_new_id';return True
    def start_closure(self,s):
        if not self.ready_before_new_input(s,'CLOSURE'):return
        if active(s) or not neutral(s):self.needs('closure_requires_actual_idle_neutral');return
        if distance(s['player'],self.cfg['cover_anchor'])>.8:self.needs('closure_pose_changed_no_replan');return
        spec=self.cfg['closure_actions'][self.closure_index]
        item=next((i for i in s['player'].get('inventory',[]) if i.get('slot')==spec['hotbar_slot']),{})
        if item.get('id')!=spec['expected_block_id'] or item.get('empty') or item.get('count',0)<1:
            self.needs('closure_actual_slot_material_unavailable');return
        self.body={k:v for k,v in spec.items() if k!='expected_block_id'}
        self.body.update(action_id=str(uuid.uuid4()),timeout_ms=spec.get('timeout_ms',5000),
            expected_world_generation=s['world']['world_generation'],expected_player_uuid=s['player']['uuid'],
            expected_action_session=s['client_action']['action_session'],
            expected_navigation_epoch=s['world']['navigation_guard']['epoch'],expected_origin=point(s['player']))
        self.closure_navigation_rejected=False;self.admission_response=None
        self.pending=True;self.cancel_sent=False;self.terminal=None;self.phase='CLOSING'
        self.reason='ordinary_closure_placement_once'
        try:
            code,o=self.c.request('POST','/control/action',self.body)
            self.admission_response=dict(http_status=code,body=copy.deepcopy(o))
            if code in (200,202):self.finish_if_terminal(o,s)
            else:
                self.pending=True;self.terminal=o;self.needs('closure_rejected_no_reissue')
        except Exception:self.reason='closure_start_response_unknown_query_original_only'
    def finish_closure_terminal(self,o):
        if not self.matching(o) or o.get('status') not in TERMINAL:return False
        self.terminal=o;r=o.get('result');spec=self.cfg['closure_actions'][self.closure_index]
        if not isinstance(r,dict):self.needs('closure_terminal_malformed_original_read_only');return True
        if r.get('input_release_confirmed') is False:
            self.needs('closure_terminal_explicit_unreleased');return True
        self.pending=False
        if r.get('unknown_outcome') or r.get('requires_handoff'):
            self.needs('closure_effect_unknown_no_reissue');return True
        if self.stop_requested:self.needs(self.stop_reason or 'disarm_requested');return True
        if o['status']!='succeeded':self.needs('closure_known_'+o['status']+'_not_confirmed');return True
        if r.get('target')!=spec['target'] or r.get('observed_block')!=spec['expected_block_id'] or r.get('placement_effect_verification')!='observed':
            self.needs('closure_target_material_observation_unconfirmed');return True
        # Plain ordinary place may omit input_release_confirmed. Never infer release:
        # wait for a later matching-context state with no active action/held use.
        self.phase='CLOSURE_CONFIRM';self.reason='placement_observed_waiting_fresh_neutral'
        return True
    def confirm_closure(self,s):
        if active(s) or not neutral(s):self.needs('closure_release_not_observed_no_next');return
        if distance(s['player'],self.cfg['cover_anchor'])>.8:self.needs('closure_pose_changed_no_next');return
        self.closure_confirmed_ids.append(self.body['action_id']);self.closure_index+=1
        self.admission_deadline=None;self.admission_replacements=0
        if self.closure_index<len(self.cfg['closure_actions']):self.start_closure(s)
        else:
            self.closure_confirmed=True
            self.needs('two_configured_door_blocks_observed_risk_remaining')
            self.cover_shield(s)
    def start_retreat(self,s,why):
        if self.retreat_sent:return
        if active(s) or not neutral(s):self.needs('unexpected_input_owner_no_takeover');return
        if not s['player'].get('alive') or not valid_world(s):self.needs('cannot_retreat_current_world');return
        # This exact caller-verified route is the sole movement plan. No chasing, bridging, or retries.
        self.retreat_sent=True;self.phase='RETREATING';self.reason=why
        self.c.note('threat_retreat_once',reason=why,pose=point(s['player']))
        self.start_segment(s)
    def next_segment(self,s):
        # A native single-waypoint success includes endpoint settling; then observe actual
        # release/location before creating the next DIFFERENT segment, never retry this one.
        if context(s)!=self.cfg['expected_context'] or not valid_world(s) or not s['player'].get('alive') or health(s)<=0:
            self.needs('segment_handoff_context_or_player_changed');return
        if active(s) or not neutral(s):self.needs('segment_release_not_observed_no_next_segment');return
        if self.handoff_deadline is None:self.handoff_deadline=time.monotonic()+3
        if time.monotonic()>self.handoff_deadline:
            self.needs('segment_handoff_native_settle_deadline_exceeded');return
        if not native_ready(s):
            # Keep this completed segment/index. NAV_WAIT_SEGMENT would start the old segment again.
            self.phase='SEGMENT_CHECK';self.reason='completed_segment_waiting_native_settle';return
        if distance(s['player'],self.cfg['waypoints'][self.segment_index])>.5:
            self.needs('settled_segment_endpoint_outside_known_route');return
        self.completed_segments.append(self.body['action_id']);self.segment_index+=1
        self.admission_deadline=self.handoff_deadline;self.handoff_deadline=None;self.admission_replacements=0
        self.start_segment(s)
    def start_segment(self,s):
        if not self.ready_before_new_input(s,'SEGMENT'):return
        self.admission_response=None
        self.phase='RETREATING';self.cancel_sent=False;self.terminal=None
        self.body=dict(action_id=str(uuid.uuid4()),action='follow_path',waypoints=[self.cfg['waypoints'][self.segment_index]],
            timeout_ms=self.cfg.get('retreat_timeout_ms',15000),sneak=True,
            expected_world_generation=s['world']['world_generation'],expected_player_uuid=s['player']['uuid'],
            expected_action_session=s['client_action']['action_session'],
            expected_navigation_epoch=s['world']['navigation_guard']['epoch'],expected_origin=point(s['player']))
        self.pending=True
        try:
            code,o=self.c.request('POST','/control/action',self.body)
            self.admission_response=dict(http_status=code,body=copy.deepcopy(o))
            if code in (200,202):self.finish_if_terminal(o,s)
            else:
                # A returned rejection is retained, never resent or disguised as successful escape.
                self.pending=True
                self.needs('retreat_admission_rejected_no_reissue');self.terminal=o
        except Exception:self.reason='retreat_start_response_unknown_query_original_only'
    def cancel_original_once(self):
        if self.cancel_sent:return
        self.cancel_sent=True
        try:self.c.request('POST','/control/action/cancel',dict(action_id=self.body['action_id'],expected_action_session=self.body['expected_action_session']))
        except Exception:pass
    def poll_original(self,s):
        if self.original_pre_input_rejection() and self.admission_deadline is not None and time.monotonic()>self.admission_deadline:
            self.needs('admission_absence_or_release_unproven_bounded_no_new_input');return
        try:
            code,o=self.c.request('GET','/control/action/status?action_id='+self.body['action_id'])
            if code==404 and self.confirm_unregistered(s,o):return
            if code==200 and self.original_pre_input_rejection():
                self.needs('pre_input_rejection_original_id_exists_no_replacement');return
            if self.original_pre_input_rejection() and self.admission_deadline is not None and time.monotonic()>self.admission_deadline:
                self.needs('admission_absence_or_release_unproven_bounded_no_new_input');return
            if code==200 and self.finish_if_terminal(o,s):return
            if self.matching(o) and o.get('status')=='running' and self.stop_requested:self.cancel_original_once()
        except Exception:pass
    def cover_shield(self,s):
        if self.shield_attempted or not neutral(s) or active(s) or not s['player'].get('alive'):return
        p=s['player'];held=p.get('mainhand',{}).get('id','')
        if p.get('offhand',{}).get('id')!='minecraft:shield' or not held.endswith(('_sword','_axe')):
            self.c.note('shield_not_available',reason='actual_offhand_shield_and_mainhand_weapon_required');return
        observed=threats(s,self.cfg)
        if observed:
            try:
                code,_=self.c.request('POST','/control/look',aim(s,observed[0]))
                if code!=200:return
            except Exception:self.input_uncertain=True;return
        self.shield_attempted=True
        try:
            code,_=self.c.request('POST','/control/key',dict(mapping='key.use',action='down'))
            if code!=200:self.input_uncertain=True
        except Exception:self.input_uncertain=True
        self.c.note('shield_attempted_not_fire_extinguished')
    def disarm(self,s):
        self.stop_requested=True;self.stop_reason='explicit_disarm'
        if self.pending:return
        if context(s)!=self.cfg['expected_context']:
            self.needs('disarm_context_changed_no_new_inputs');self.done=True;return
        if self.shield_attempted and not self.shield_release_sent:
            self.shield_release_sent=True
            try:self.c.request('POST','/control/key',dict(mapping='key.use',action='up'))
            except Exception:self.input_uncertain=True
            return  # Actual release is observed on a later state, never inferred from the POST.
        if not active(s) and neutral(s):self.phase='DISARMED';self.reason='neutral_handoff_observed';self.done=True
        else:self.needs('disarm_release_not_yet_observed')
    def step(self,s,disarm=False):
        same=context(s)==self.cfg['expected_context']
        if disarm:self.stop_requested=True;self.stop_reason='explicit_disarm'
        if not same or not valid_world(s) or not s['player'].get('alive'):
            self.stop_requested=True;self.stop_reason='context_changed' if not same else 'world_unavailable_or_player_dead'
        if self.pending:self.poll_original(s)
        elif self.phase=='NAV_WAIT_SEGMENT' and not self.stop_requested:self.start_segment(s)
        elif self.phase=='NAV_WAIT_CLOSURE' and not self.stop_requested:self.start_closure(s)
        elif self.phase=='SEGMENT_CHECK' and not self.stop_requested:self.next_segment(s)
        elif self.phase=='CLOSURE_READY' and not self.stop_requested:self.start_closure(s)
        elif self.phase=='CLOSURE_CONFIRM' and not self.stop_requested:self.confirm_closure(s)
        elif self.phase=='COVER_CHECK' and not self.stop_requested:self.confirm_cover(s)
        elif self.phase=='ARMED' and not self.stop_requested:
            if active(s) or not neutral(s):self.needs('unexpected_input_owner_no_takeover')
            else:
                why=trigger(s,self.cfg,self.previous_health)
                if why:self.start_retreat(s,why)
        if self.stop_requested:
            if disarm:self.disarm(s)
            elif not self.pending:self.needs(self.stop_reason)
        self.previous_health=health(s)
        return self.summary(s)
    def summary(self,s):
        return dict(phase=self.phase,reason=self.reason,exclusive_owner_until_disarmed=not self.done,
            retreat_sent=self.retreat_sent,original_action_id=None if not self.body else self.body['action_id'],
            segment_index=self.segment_index,segment_count=len(self.cfg['waypoints']),completed_segment_ids=self.completed_segments,
            closure_confirmed=self.closure_confirmed,closure_index=self.closure_index,closure_confirmed_ids=self.closure_confirmed_ids,
            rejected_unregistered_count=len(self.rejected_unregistered),admission_replacements=self.admission_replacements,
            original_pending=self.pending,cancel_sent=self.cancel_sent,input_attempt_uncertain=self.input_uncertain,
            pose=point(s['player']),health=health(s),alive=s['player'].get('alive'),on_fire=s['player'].get('on_fire'),
            in_lava=s['player'].get('in_lava'),blocking=s['player'].get('blocking'),using_item=s['player'].get('using_item'),
            active=s['client_action'],neutral=neutral(s),observed_threats=[dict(uuid=e.get('uuid'),type=e.get('type'),x=e['x'],y=e['y'],z=e['z'],distance=e['distance']) for e in threats(s,self.cfg)])

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--config',type=Path,required=True);p.add_argument('--run-dir',type=Path,required=True);args=p.parse_args()
    cfg=validate(json.loads(args.config.read_text()));args.run_dir.mkdir(parents=True,exist_ok=False,mode=0o700)
    c=Client(args.run_dir);c.note('config',config=cfg)
    try:watch=Watch(c,cfg,c.state())
    except Exception as e:
        result=dict(phase='REFUSED_NO_INPUT',reason=str(e) if isinstance(e,Refused) else type(e).__name__,exclusive_owner_until_disarmed=False)
        (args.run_dir/'RESULT.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result),flush=True);return 2
    while not watch.done:
        try:
            s=c.state();status=watch.step(s,(args.run_dir/'DISARM').exists())
            status['utc']=datetime.datetime.now(datetime.timezone.utc).isoformat();c.note('observation',**status)
            temp=args.run_dir/'STATUS.tmp';temp.write_text(json.dumps(status,indent=2)+'\n');temp.replace(args.run_dir/'STATUS.json')
        except Exception as e:
            c.note('observation_gap_no_new_input',error=type(e).__name__)
            # Do not leave an old healthy frame displayed as a current observation.
            gap=dict(phase='OBSERVATION_UNAVAILABLE',controller_phase=watch.phase,
                reason=type(e).__name__,exclusive_owner_until_disarmed=True,
                original_action_id=None if not watch.body else watch.body['action_id'],
                original_pending=watch.pending,utc=datetime.datetime.now(datetime.timezone.utc).isoformat())
            (args.run_dir/'STATUS.json').write_text(json.dumps(gap,indent=2)+'\n')
            # Existing original-ID status can still be queried after the next readable frame.
        time.sleep(.25)
    result=dict(**status,terminal=watch.terminal)
    (args.run_dir/'RESULT.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result),flush=True)
if __name__=='__main__':raise SystemExit(main())
