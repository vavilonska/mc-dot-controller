"""v5 candidate: bounded melee closing for every hostile, with dry retreat.

No game I/O on import. Only the existing authorized game operator runs this file.
"""
import argparse
import json
import math
from pathlib import Path
import time
import uuid

import base_watchdog as base
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

    def status(self):
        data=super().status()
        data.update(schema_version=5,implementation='native-defense-watchdog-v5',
                    ranged={'encounters':self.ranged_memory.summary(),'last_maneuver':self.ranged_last,
                            'movement_request':self.ranged_move['id'] if self.ranged_move else None,
                            'shield_blocks_potions_confirmed':False})
        data['engagement']={**data['ranged'],'scope':'all_observed_hostiles'}
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
                record=self.ranged_memory.begin(state,target,self.clock())
                if record.get('suppressed_until',0)>self.clock():
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
                command={**command,'approach':True}
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

    def observe_tactics(self,state,combat,damaged,kind):
        self.observe_escape_progress(state)
        if self.ranged_move:
            self.phase,self.reason='retreating','following_observed_dry_route'
            return True  # Do not stop the escape just because poison keeps ticking.
        identity=combat.get('target_uuid') or self.started_target
        target=self.target(state,identity)
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
