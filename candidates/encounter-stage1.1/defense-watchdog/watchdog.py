"""v5.1: deduplicate terminal failures and recover observed in-range melee.

No game I/O on import. Only the existing authorized game operator runs this file.
"""
import argparse
from collections import OrderedDict, deque
import re
import json
import math
from pathlib import Path
import time
import uuid

import base_watchdog as base
from resident_controller.native_combat import crosshair_target_in_reach
from ranged_tactics import RangedMemory, horizontal, retreat_plan

OWNER_OPS, write_json = base.OWNER_OPS, base.write_json
cancel_waiting_intents = base.cancel_waiting_intents

class Watchdog(base.Watchdog):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.ranged_memory=RangedMemory()
        self.ranged_context=None
        self.ranged_terrain=None
        self.ranged_move=None
        self.ranged_last=None
        self.retreat_lease=None
        self.handled_terminal=OrderedDict()
        self.melee_recovery_target=None
        self.trace=deque(maxlen=96)
        self.trace_sequence=0
        self.trace_saved=-1
        self.trace_frozen=False

    def status(self):
        data=super().status()
        data.update(schema_version=5,implementation='native-defense-watchdog-v5',
                    ranged={'encounters':self.ranged_memory.summary(),'last_maneuver':self.ranged_last,
                            'movement_request':self.ranged_move['id'] if self.ranged_move else None,
                            'shield_blocks_potions_confirmed':False})
        data['engagement']={**data['ranged'],'scope':'all_observed_hostiles'}
        data['watchdog_revision']='v5.1-live-hit-recovery'
        data['terminal_events_handled']=len(self.handled_terminal)
        data['combat_telemetry']={'samples':len(self.trace),'frozen_after_death':self.trace_frozen,
                                 'file':'combat-trace-'+self.session_id+'.json'}
        if self.armed and not self.stopped and (self.ranged_move or (self.rpc and self.rpc['kind'].startswith('ranged_'))):
            data['state']='busy'
        return data

    def target(self,state,identity):
        return next((e for e in state.get('nearby',{}).get('entities',[])
                     if e.get('uuid')==identity and e.get('type') in base.HOSTILES and e.get('alive') is True),None)

    def send(self,kind,command):
        if kind=='start_combat':
            state=(self.latest or {}).get('state',{})
            target=self.target(state,command.get('target_uuid'))
            if target:
                recovering=self.melee_recovery_target==target['uuid']
                if recovering and not self.live_hit(state,target):
                    self.melee_recovery_target=None
                    self.phase,self.reason='watching','fresh_entity_hit_lost_no_recovery'
                    self.next_observe=0
                    return
                record=self.ranged_memory.begin(state,target,self.clock())
                if record.get('suppressed_until',0)>self.clock() and not recovering:
                    self.targeting.excluded[target['uuid']]=record['suppressed_until']
                    self.started_target=None
                    self.phase,self.reason='watching','hostile_target_temporarily_suppressed'
                    self.next_observe=0
                    return
                if (self.latest or {}).get('combat',{}).get('melee_closing_schema_version')!=2:
                    self.begin_disengage(target['uuid'],'patched_melee_closing_required')
                    return
                # Existing resident already checks actual flat, dry corridor data
                # before forward input. Never freeze at range waiting for any hostile.
                if recovering:
                    record['suppressed_until']=0
                    self.targeting.excluded.pop(target['uuid'],None)
                self.melee_recovery_target=None
                command={**command,'approach':not recovering}
                if target['type']=='minecraft:witch':command['shield']=False
        return super().send(kind,command)

    def begin_disengage(self,identity,reason):
        now=self.clock()
        context=base.recovery_context((self.latest or {}).get('state',{}))
        self.ranged_context={'target_uuid':identity,'reason':reason,'started':now,
                             'identity':context[0] if context else None}
        until=self.ranged_memory.suppress(identity,now,reason)
        self.targeting.release(now,'hostile_disengagement')
        self.targeting.preferred_uuid=None
        self.targeting.excluded[identity]=until
        self.started_target=None
        self.phase,self.reason='disengaging',reason
        self.defense_epoch+=1
        super().send('ranged_cancel',{'op':'cancel'})

    def live_hit(self,state,target):
        return (target is not None and state.get('player',{}).get('alive') is True
                and state.get('screen_open') is False and state.get('paused') is False
                and crosshair_target_in_reach(state,target['uuid'],target.get('entity_id'),target['type']))

    def terminal_event(self,state,combat):
        if combat.get('active') is not False:return None
        return (state.get('world',{}).get('world_generation'),
                state.get('client_action',{}).get('action_session'),combat.get('request_id'),
                combat.get('target_uuid'),combat.get('reason'))

    def remember_terminal(self,event):
        if event is None:return
        self.handled_terminal[event]=True
        self.handled_terminal.move_to_end(event)
        while len(self.handled_terminal)>256:self.handled_terminal.popitem(last=False)

    def recover_live_melee(self,state,target):
        if self.melee_recovery_target is not None or not self.live_hit(state,target):return False
        identity=target['uuid']
        self.targeting.release(self.clock(),'live_entity_hit_recovered')
        self.targeting.preferred_uuid=identity
        # Preserve exclusion/progress until the post-cancel observation confirms hit.
        self.started_target=None
        self.melee_recovery_target=identity
        self.phase,self.reason='engaging','live_entity_hit_recovered_no_path_needed'
        self.send('cancel_threat',{'op':'cancel'})
        return True

    def observation_received(self,payload,kind):
        state=payload.get('state',{});player=state.get('player',{});combat=payload.get('combat',{})
        identity=combat.get('target_uuid') or self.started_target
        target=self.target(state,identity)
        if self.trace_frozen:return
        if not (combat.get('active') or target or self.trace):return
        pick=lambda value,keys:{k:value.get(k) for k in keys if k in value}
        self.trace.append({'observed_at':time.time(),'game_time':state.get('world',{}).get('game_time'),
            'kind':kind,'watchdog_phase':self.phase,'watchdog_reason':self.reason,
            'player':pick(player,('x','y','z','eye_position','yaw','pitch','alive','health','on_ground','selected_slot')),
            'target':pick(target or {},('uuid','entity_id','type','x','y','z','bounding_box','distance','alive','health')),
            'crosshair':pick(state.get('crosshair',{}),('type','uuid','entity_id','entity_type','location','id','x','y','z','face')),
            'combat':pick(combat,('request_id','active','phase','reason','target_uuid','attack_attempts','attack_dispatches')),
            'aim':pick(payload.get('aim_lock',{}),('active','reason','target_uuid','center'))})
        self.trace_sequence+=1
        if player.get('alive') is False or player.get('health')==0:self.trace_frozen=True

    def persist_telemetry(self,directory):
        if self.trace_sequence==self.trace_saved or not self.trace:return
        path=directory/('combat-trace-'+self.session_id+'.json')
        write_json(path,{'schema_version':1,'revision':'v5.1-live-hit-recovery',
                         'frozen_after_death':self.trace_frozen,'samples':list(self.trace)})
        self.trace_saved=self.trace_sequence
        # Only this helper's generated traces, never arbitrary operator files.
        files=[p for p in directory.glob('combat-trace-*.json')
               if re.fullmatch(r'combat-trace-[a-f0-9]{32}\.json',p.name)]
        for old in sorted(files,key=lambda p:p.stat().st_mtime)[:-4]:old.unlink()

    def observe_tactics(self,state,combat,damaged,kind):
        self.observe_escape_progress(state)
        if kind=='fresh' and self.melee_recovery_target is not None:
            target=self.target(state,self.melee_recovery_target)
            if target is None or not self.live_hit(state,target):
                self.melee_recovery_target=None
                self.targeting.preferred_uuid=None
                identity=combat.get('target_uuid')
                record=self.ranged_memory.records.get(identity,{})
                if identity and record.get('suppressed_until',0)<=0:
                    until=self.ranged_memory.suppress(identity,self.clock(),'fresh_entity_hit_lost')
                    self.targeting.excluded[identity]=until
                self.phase,self.reason='watching','fresh_entity_hit_lost_no_recovery'
                return True
            if self.latest.get('action',{}).get('status')=='running':
                self.melee_recovery_target=None
                self.attention('navigation_cancel_not_observed')
                return True
            self.send('start_combat',{'op':'combat_start','target_uuid':target['uuid'],
                                    'radius':8,'approach':False,'shield':True})
            return True
        if self.ranged_move:
            self.phase,self.reason='retreating','following_observed_dry_route'
            return True  # Do not stop the escape just because poison keeps ticking.
        identity=combat.get('target_uuid') or self.started_target
        target=self.target(state,identity)
        event=self.terminal_event(state,combat)
        if event is not None:
            eligible=any(word in str(combat.get('reason','')) for word in ('flat_approach_blocked','target_missing','target_lost'))
            if eligible:
                already_handled=event in self.handled_terminal
                historical=self.started_target is None and identity not in self.ranged_memory.records
                self.remember_terminal(event)
                if historical:return False
                if self.recover_live_melee(state,target):return True
                if already_handled:return False
        record=self.ranged_memory.records.get(identity)
        if record is None and target is None and identity and combat.get('target_type') in base.HOSTILES:
            # An inherited lock can be outside the lightweight nearby list.
            # Bound it using explicit combat metadata without inventing a position.
            record=self.ranged_memory.begin(state,{'uuid':identity,'type':combat['target_type'],
                            'distance':None,'health':combat.get('observed_target_health')},self.clock())
        if target is None and record is None:return False
        reason=str(combat.get('reason',''))
        if not combat.get('active') and any(w in reason for w in ('target_dead','target_no_longer_alive')):
            return False
        if not combat.get('active') and not any(w in reason for w in ('target_missing','target_lost','flat_approach_blocked')):
            return False  # Manual takeover/menu/uncertainty retain their hard stops.
        problem=self.ranged_memory.observe(state,target,combat,self.clock(),damaged)
        if combat.get('active') and self.live_hit(state,target) and problem in (
                'no_observed_closing_progress','no_attack_dispatch_before_deadline'):
            # A current real hit gets native melee priority over historical path budgets.
            self.phase,self.reason='combat','verified_entity_hit_native_melee_priority'
            return True
        if problem:
            self.begin_disengage(identity,problem)
            return True
        return False

    def observe_escape_progress(self,state):
        lease=self.retreat_lease
        if not lease:return
        lease['progressing']=False
        lease['observation']=state
        if not self.owner or lease['until']<=self.clock():return
        target=self.target(state,lease['target_uuid'])
        try:
            if target:
                distance=horizontal(state['player'],target)
                lease['progressing']=distance>lease['last_distance']+.05
                lease['last_distance']=distance
        except (KeyError,ValueError):pass
        lease['observed_at']=self.clock()

    def damage_requires_cancel(self,state):
        lease=self.retreat_lease
        return not (lease and self.owner and lease['until']>self.clock()
                    and lease.get('observation') is state and lease.get('progressing') is True
                    and 0 <= self.clock()-lease.get('observed_at',-math.inf) <= .5)

    def submit_owner(self,intent_id,command):
        if self.ranged_move:return False
        accepted=super().submit_owner(intent_id,command)
        if accepted and self.owner and self.owner['id']==intent_id:
            self.retreat_lease=None
            if command.get('op')=='action' and command.get('action')=='follow_path':
                state=(self.latest or {}).get('state',{});points=command.get('waypoints',[])
                if points:
                    for identity,record in self.ranged_memory.records.items():
                        target=self.target(state,identity)
                        if target and record.get('suppressed_until',0)>self.clock():
                            try:
                                initial=horizontal(state['player'],target)
                                distances=[horizontal(point,target) for point in points]
                                if min(distances)>=initial-.25 and distances[-1]>=initial+.5:
                                    self.retreat_lease={'target_uuid':identity,'initial_distance':initial,'last_distance':initial,'until':self.clock()+4}
                                    break
                            except (ValueError,KeyError):pass
        return accepted

    def yield_navigation(self,reason):
        self.ranged_context=None;self.ranged_terrain=None;self.ranged_move=None
        self.phase,self.reason='watching',reason
        self.next_observe=0

    def capture(self,result):
        self.latest=result['result'];self.observed_at=self.clock()
        self.observation_received(self.latest,'ranged_observe')
        self.next_observe=self.clock()+self.interval
        state=self.latest.get('state',{})
        if (not base.alive(state) or state.get('screen_open') is not False or state.get('paused') is not False):
            raise ValueError('ranged_player_context_unavailable')
        context=base.recovery_context(state)
        expected=(self.ranged_context or {}).get('identity')
        if context is None or expected is None or context[0]!=expected:
            raise ValueError('ranged_context_changed')
        if (self.latest.get('action',{}).get('status')=='running'
                or self.latest.get('combat',{}).get('active') is True
                or self.latest.get('status',{}).get('held_mappings')!=[]):
            raise ValueError('ranged_new_input_owner')
        return state

    def handle_ranged_rpc(self):
        rpc=self.rpc
        result=self.q.result(rpc['id'])
        if result is None:
            if self.clock()-rpc['started']>2:
                # Read-only timeout after a confirmed cancel: no imagined route.
                self.rpc=None
                if rpc['kind']=='ranged_cancel':
                    self.attention('ranged_cancel_unconfirmed')
                else:self.yield_navigation('ranged_observation_delayed_no_blind_movement')
            return
        self.rpc=None;kind=rpc['kind']
        if kind!='ranged_cancel' and self.clock()-rpc['started']>2:
            self.yield_navigation('ranged_late_observation_no_blind_movement');return
        if result.get('status')!='succeeded':
            if kind=='ranged_cancel':self.attention('ranged_cancel_unconfirmed')
            else:self.yield_navigation('ranged_observation_failed_no_blind_movement')
            return
        if kind=='ranged_cancel':
            if result.get('result',{}).get('ok') is not True:
                self.attention('ranged_cancel_unconfirmed');return
            super().send('ranged_terrain',{'op':'observe','terrain':True,'radius':3,'vertical':2})
            return
        if kind=='ranged_terrain':
            self.observation_received(result.get('result',{}),kind)
            self.ranged_terrain={'data':result.get('result',{}).get('terrain',{}),'received':rpc['started']}
            super().send('ranged_fresh',{'op':'observe'})
            return
        try:state=self.capture(result)
        except (ValueError,KeyError,TypeError):
            self.attention('ranged_player_context_unavailable');return
        if kind=='ranged_verify':
            context=self.ranged_context or {};target=self.target(state,context.get('target_uuid'))
            actual=None
            if target:
                try:actual=horizontal(state['player'],target)
                except (KeyError,ValueError):pass
            if self.ranged_last is not None:self.ranged_last.update(actual_distance=actual,
                                                                  verified_position={k:state.get('player',{}).get(k) for k in ('x','y','z','health')})
            self.yield_navigation('ranged_retreat_observed_replan_navigation')
            return
        context=self.ranged_context or {};target=self.target(state,context.get('target_uuid'))
        if target is None or not self.ranged_terrain or self.clock()-self.ranged_terrain['received']>1.5:
            self.yield_navigation('ranged_no_current_target_or_terrain');return
        plan=retreat_plan(state,self.ranged_terrain['data'],target)
        if not plan:
            self.ranged_last={'result':'no_verified_dry_route','target_uuid':context.get('target_uuid')}
            self.yield_navigation('ranged_no_verified_route_navigation_released');return
        self.ranged_last={**plan,'target_uuid':target['uuid'],'result':'retreat_dispatched'}
        request=self.q.submit({'op':'action','action':'follow_path','waypoints':plan['waypoints'],'timeout_ms':2000})
        self.ranged_move={'id':request,'started':self.clock()}
        self.phase,self.reason='retreating','following_observed_dry_route'

    def tick(self):
        if self.stopped:return
        if self.stop_requested:return super().tick()
        if self.rpc and self.rpc['kind'].startswith('ranged_'):
            self.handle_ranged_rpc();return
        if self.ranged_move:
            result=self.q.result(self.ranged_move['id'])
            if result is None and self.clock()-self.ranged_move['started']>2.5:
                self.ranged_move=None
                self.attention('ranged_retreat_completion_unconfirmed')
                super().send('attention_cancel',{'op':'cancel'});return
            if result is not None:
                self.ranged_move=None
                if result.get('status')=='uncertain':
                    self.attention('ranged_retreat_uncertain')
                    super().send('attention_cancel',{'op':'cancel'});return
                if result.get('status')!='succeeded':
                    reason=result.get('reason') or result.get('action',{}).get('reason')
                    if result.get('status')=='failed' and reason in ('stuck','deadline_exceeded'):
                        self.yield_navigation('ranged_retreat_failed_navigation_released')
                    else:self.attention('ranged_retreat_interrupted_owner_control')
                    return
                super().send('ranged_verify',{'op':'observe'});return
        return super().tick()


def main():
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='mode',required=True)
    start=sub.add_parser('run');start.add_argument('--queue',required=True);start.add_argument('--control',type=Path,required=True)
    send=sub.add_parser('submit');send.add_argument('--control',type=Path,required=True);send.add_argument('--json',required=True)
    stop=sub.add_parser('stop');stop.add_argument('--control',type=Path,required=True)
    a=p.parse_args()
    if a.mode=='run':base.run(a.queue,a.control,watchdog_class=Watchdog)
    elif a.mode=='stop':(a.control/'STOP').write_text('operator_stop\n');print(json.dumps({'stop_requested':True}))
    else:
        body=json.loads(a.json)
        if not isinstance(body,dict) or body.get('op') not in OWNER_OPS:raise ValueError('unsupported_owner_intent')
        if (a.control/'STOP').exists():raise ValueError('watchdog_stopping_or_stopped')
        if len(list((a.control/'inbox').glob('*.json')))>=1:raise ValueError('one_pending_owner_intent_only')
        identity=uuid.uuid4().hex;write_json(a.control/'inbox'/(identity+'.json'),body)
        print(json.dumps({'intent_id':identity}))

if __name__=='__main__':main()
