"""Observed environmental egress through the existing single watchdog queue writer.

The client owns tick-continuous movement/flotation. This module only observes,
chooses a route from loaded collision facts, and replaces a terminal/stalled
route after confirmed cancellation. Import has no game I/O.
"""
from collections import deque
import math

FLAGS = ('in_water', 'eye_in_water', 'in_lava', 'in_powder_snow', 'on_fire')


def supported(state):
    p = state.get('player', {})
    return (p.get('environment_schema_version') == 1
            and all(type(p.get(k)) is bool for k in FLAGS)
            and type(p.get('frozen_ticks')) is int)


def hazards(state):
    if not supported(state):
        return ()
    p = state['player']
    return tuple(k for k in FLAGS if p[k])


def context(state):
    return (state.get('world', {}).get('world_generation'),
            state.get('player', {}).get('uuid'),
            state.get('client_action', {}).get('action_session'))


def dry(state):
    return supported(state) and not hazards(state) and state['player'].get('on_ground') is True


def egress_plan(state, terrain):
    """Loaded local cardinal route only. No random escape direction or unseen landing.

    Water can support swimming; dry nodes need observed full top support.
    Powder-snow nodes are used only over actual full support. Other hazards,
    partial collision geometry, unknown cells and lava beyond the occupied
    starting column are not invented into a route.
    """
    if (not supported(state) or terrain.get('complete') is not True
            or terrain.get('world_generation') != state.get('world', {}).get('world_generation')):
        return None
    p = state['player']
    try:
        pos = tuple(float(p[k]) for k in ('x', 'y', 'z'))
        if not all(math.isfinite(v) for v in pos):return None
    except (KeyError, TypeError, ValueError):return None
    start = tuple(math.floor(v) for v in pos)
    cells = {(c.get('x'), c.get('y'), c.get('z')): c for c in terrain.get('cells', [])}
    water = frozenset(('minecraft:water','minecraft:flowing_water'))
    powder = 'minecraft:powder_snow'

    def known(n):
        c = cells.get(n, {})
        if (c.get('status') == 'loaded' and c.get('known') is True
                and c.get('collision_known') is True
                and c.get('id_truncated') is False and c.get('fluid_truncated') is False
                and c.get('properties_truncated') is False):return c
        return None

    def body(n, origin=False):
        c = known(n)
        if not c:return False
        if c.get('id') == powder:
            return set(c.get('hazards', [])) <= {'powder_snow', 'freezing', 'minecraft:powder_snow'}
        if origin and n[0] == start[0] and n[2] == start[2]:
            # Leaving currently occupied fire/lava is allowed; never a new lava cell.
            if c.get('fluid') in ('minecraft:lava','minecraft:flowing_lava') or c.get('id') in ('minecraft:fire', 'minecraft:soul_fire'):
                return c.get('collision_empty') is True
        fluid=c.get('fluid')
        allowed={'water'} if fluid in water else set()
        return (c.get('collision_empty') is True and (fluid == 'minecraft:empty' or fluid in water)
                and isinstance(c.get('hazards'),list) and set(c['hazards']) <= allowed)

    def kind(n):
        x,y,z=n;foot=known(n);below=known((x,y-1,z))
        if not foot or not body(n) or not body((x,y+1,z)):return None
        if foot.get('fluid') in water or (below and below.get('fluid') in water):return 'water'
        if (below and below.get('full_top_support') is True and below.get('fluid') == 'minecraft:empty'
                and below.get('hazards') == []):
            return 'powder' if foot.get('id') == powder or cells.get((x,y+1,z),{}).get('id') == powder else 'dry'
        return None

    def swept(a,b):
        # The actual starting footprint is included; later nodes are block centers.
        ax,ay,az=pos if a==start else (a[0]+.5,a[1],a[2]+.5)
        bx,by,bz=b[0]+.5,b[1],b[2]+.5
        for x in range(math.floor(min(ax,bx)-.3+1e-7), math.ceil(max(ax,bx)+.3-1e-7)):
            for z in range(math.floor(min(az,bz)-.3+1e-7), math.ceil(max(az,bz)+.3-1e-7)):
                for y in range(math.floor(min(ay,by)+1e-7), math.ceil(max(ay,by)+1.8-1e-7)):
                    if not body((x,y,z),origin=a==start):return False
        # Horizontal dry movement must have actual full support at destination.
        return True

    source_danger = p['in_lava'] or any(cells.get((start[0], y, start[2]), {}).get('hazards')
        for y in (start[1]-1, start[1], start[1]+1))
    previous={start:None};queue=deque([start]);goals=[]
    while queue:
        a=queue.popleft()
        for dx,dz in ((1,0),(-1,0),(0,1),(0,-1)):
            for dy in (0,1,-1):
                b=(a[0]+dx,a[1]+dy,a[2]+dz)
                if b in previous or not kind(b) or not swept(a,b):continue
                previous[b]=a;queue.append(b)
                k=kind(b)
                if k=='dry' or (p['on_fire'] and k=='water'):
                    path=[];n=b
                    while previous[n] is not None:path.append(n);n=previous[n]
                    path.reverse()
                    # Burning in otherwise dry ground should seek observed water,
                    # not move arbitrarily between equivalent dry cells.
                    if p['on_fire'] and not (source_danger or p['in_water'] or p['in_powder_snow']) and k!='water':continue
                    goals.append((0 if p['on_fire'] and k=='water' else 1,len(path),path))
        # Only swimming upward into observed water/air; no invented dry jump edges.
        if (a==start and p['in_water']) or kind(a)=='water':
            b=(a[0],a[1]+1,a[2])
            if b not in previous and kind(b)=='water' and swept(a,b):
                previous[b]=a;queue.append(b)
    if not goals:return None
    _,_,nodes=min(goals,key=lambda g:(g[0],g[1],g[2]))
    return [{'x':x+.5,'y':y,'z':z+.5,'jump':True} for x,y,z in nodes]


class EnvironmentRecovery:
    def __init__(self):
        self.active=False;self.reason='not_started';self.identity=None
        self.move=None;self.plan=None;self.last_plan=None;self.last_plan_signature=None
        self.last_tick=None;self.safe_since=None;self.safe_samples=0;self.next_observe=0
        self.final_observed=False;self.action_terminal=False;self.safe_frozen=None;self.terminal_at=None

    def status(self):
        return {'schema_version':1,'active':self.active,'reason':self.reason,
                'movement_request':self.move,'safe_samples':self.safe_samples,
                'confirmation':'later_dry_observed' if self.final_observed else 'pending',
                'server_confirmed':False}

    def start(self,dog,state):
        if self.active or not hazards(state):return False
        if state.get('screen_open') is not False or state.get('paused') is not False:return False
        self.active=True;self.reason='cancel_before_environment_recovery';self.identity=context(state)
        self.safe_samples=0;self.safe_since=None;self.last_tick=None;self.final_observed=False
        dog.ranged_move=None;dog.ranged_context=None;dog.ranged_terrain=None
        dog.melee_recovery_target=None;dog.retreat_lease=None
        self.last_plan=None;self.last_plan_signature=None;self.action_terminal=False
        dog.phase,dog.reason='environment',self.reason
        dog.defense_epoch+=1
        dog.send('env_cancel',{'op':'cancel'})
        return True

    def abandon(self,reason):
        self.active=False;self.reason=reason;self.move=None;self.plan=None

    def fail(self,dog,reason):
        self.abandon(reason)
        dog.attention(reason)
        dog.send('attention_cancel',{'op':'cancel'})

    def action(self,dog,points):
        self.move=dog.q.submit({'op':'action','action':'recover_environment','waypoints':points})
        self.last_plan=points;self.action_terminal=False;self.terminal_at=None
        self.reason='following_observed_exit' if points else 'maintaining_flotation_observing_exit'
        dog.phase,dog.reason='environment',self.reason
        self.next_observe=0

    def tick(self,dog):
        if not self.active:return False
        # The ordinary owner result still needs delivery after our one cancellation.
        if dog.owner:
            result=dog.q.result(dog.owner['request_id'])
            if result is not None:
                dog.completed.append({'intent_id':dog.owner['id'],'session_id':dog.session_id,
                                      'queue_request_id':dog.owner['request_id'],'result':result})
                dog.owner=None
        if self.move:
            result=dog.q.result(self.move)
            if result is not None:
                self.move=None;self.action_terminal=True;self.terminal_at=dog.clock()
                if result.get('status')!='succeeded':
                    self.fail(dog,'environment_action_'+str(result.get('reason',result.get('status'))));return True
                self.reason='verifying_dry_after_action';self.next_observe=0
        if dog.rpc:
            rpc=dog.rpc
            if not rpc['kind'].startswith('env_'):
                self.fail(dog,'environment_control_ownership_changed');return True
            result=dog.q.result(rpc['id'])
            if result is None:
                if dog.clock()-rpc['started']>3:
                    if rpc['kind']=='env_observe':
                        # A slow read must not release flotation. The already-owned
                        # native action still checks death/menu/world every client tick.
                        self.reason='environment_observation_delayed_native_recovery_continues'
                        dog.reason=self.reason
                    else:self.fail(dog,'environment_request_uncertain_no_replay')
                return True
            dog.rpc=None
            if result.get('status')!='succeeded':
                if rpc['kind']=='env_observe':
                    # Read-only retry only; never replace/replay a movement write.
                    self.reason='environment_observation_unavailable_native_recovery_continues'
                    self.next_observe=dog.clock()+.4
                    return True
                self.fail(dog,'environment_'+str(result.get('reason',result.get('status'))));return True
            kind=rpc['kind']
            if kind in ('env_cancel','env_replace_cancel'):
                if result.get('result',{}).get('ok') is not True:
                    self.fail(dog,'environment_release_unconfirmed');return True
                # All held controls now released; combat history remains intact.
                dog.started_target=None;dog.targeting.release(dog.clock(),'environment_recovery')
                self.move=None
                if kind=='env_cancel':self.action(dog,[])
                else:self.action(dog,self.plan or [])
            elif kind=='env_observe':
                if self.action_terminal and rpc['started'] < self.terminal_at:
                    # A read queued before completion may contain the old wet
                    # state. It proves neither a dry finish nor a new hazard entry.
                    self.next_observe=0
                    return True
                payload=result.get('result',{});state=payload.get('state',{});p=state.get('player',{})
                dog.latest=payload;dog.observed_at=dog.clock()
                dog.observation_received(payload,'environment_observe')
                if (not supported(state) or context(state)!=self.identity or p.get('alive') is not True
                        or state.get('screen_open') is not False or state.get('paused') is not False):
                    self.fail(dog,'environment_context_interrupted');return True
                tick=state.get('world',{}).get('game_time')
                if type(tick) is not int or (self.last_tick is not None and tick<=self.last_tick):
                    # Stale read evidence cannot complete recovery or plan a new
                    # route, but also must not turn off native flotation.
                    self.reason='environment_observation_not_advancing_native_recovery_continues'
                    self.next_observe=dog.clock()+.2
                    return True
                self.last_tick=tick
                if self.action_terminal and hazards(state):
                    # A later observed re-entry is a new recovery step, not a replay
                    # of the completed action or an assumption that dry persisted.
                    self.safe_samples=0;self.safe_since=None;self.safe_frozen=None
                    self.action(dog,[])
                    return True
                if dry(state):
                    frozen=p['frozen_ticks']
                    if self.safe_frozen is not None and frozen>self.safe_frozen:
                        self.safe_samples=0;self.safe_since=None
                    self.safe_frozen=frozen
                    self.safe_samples+=1
                    if self.safe_since is None:self.safe_since=tick
                else:self.safe_samples=0;self.safe_since=None;self.safe_frozen=None
                if self.action_terminal and self.safe_samples>=2 and tick-self.safe_since>=2:
                    self.active=False;self.final_observed=True;self.reason='later_dry_observed'
                    dog.defense_epoch+=1;dog.phase,dog.reason='watching','environment_recovered_reobserve_navigation'
                    dog.next_observe=0;return True
                action=payload.get('action',{})
                waiting=action.get('result',{}).get('environment_waiting_for_route') is True
                # No route replacement while an observed route is making progress.
                if waiting and self.move:
                    points=egress_plan(state,payload.get('terrain',{}))
                    signature=tuple((v['x'],v['y'],v['z']) for v in points) if points else None
                    if points and signature!=self.last_plan_signature:
                        self.plan=points;self.last_plan_signature=signature
                        # Detach result before cancel: cancelled old route is expected,
                        # never interpreted as permission to replay that old request.
                        self.move=None
                        dog.defense_epoch+=1
                        dog.send('env_replace_cancel',{'op':'cancel'});return True
                    self.reason='maintaining_flotation_no_new_observed_exit'
                self.next_observe=dog.clock()+.2
        if not dog.rpc and dog.clock()>=self.next_observe:
            waiting=(dog.latest or {}).get('action',{}).get('result',{}).get('environment_waiting_for_route') is True
            scan=not self.action_terminal and (not self.last_plan or waiting)
            command={'op':'observe'}
            if scan:command.update(terrain=True,radius=4,vertical=4)
            dog.send('env_observe',command)
        dog.phase,dog.reason='environment',self.reason
        return True
