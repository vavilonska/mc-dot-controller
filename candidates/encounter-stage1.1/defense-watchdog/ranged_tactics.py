"""Observed all-hostile engagement budgets and small dry-ground retreat plans. No game I/O."""
import math
from collections import deque
from base_watchdog import HOSTILES

RANGED = frozenset('minecraft:'+name for name in (
    'witch','skeleton','stray','bogged','pillager','blaze','ghast','guardian','elder_guardian','shulker','evoker'))
REENGAGE_DELAY = 30.0
MELEE_REENGAGE_DELAY = 10.0
NO_ATTACK_LIMIT = 5.0
NO_CLOSING_LIMIT = 2.5
NO_HEALTH_PROGRESS_LIMIT = 6.0


def xyz(value):
    try:
        coords=tuple(value[k] for k in ('x','y','z'))
        if all(type(v) in (float,int) and math.isfinite(v) for v in coords):return coords
    except (KeyError,TypeError):pass
    raise ValueError('position_unavailable')


def horizontal(a,b):
    x,_,z=xyz(a);u,_,v=xyz(b)
    return math.hypot(x-u,z-v)


def in_melee(state,target):
    try:
        eye=xyz(state['player']['eye_position'])
        hit=state.get('crosshair',{})
        if hit.get('type')=='entity' and hit.get('uuid')==target.get('uuid') and 'location' in hit:
            if math.dist(eye,xyz(hit['location']))<=3:return True
        box=target['bounding_box'];lo=xyz(box['min']);hi=xyz(box['max'])
        if any(a>b for a,b in zip(lo,hi)):return False
        return math.sqrt(sum(max(a-p,0,p-b)**2 for p,a,b in zip(eye,lo,hi))) <= 2.8
    except (ValueError,KeyError,TypeError):return False


class RangedMemory:
    """Historical name; this budget now covers every admitted hostile type."""
    def __init__(self):self.world=None;self.records={}
    def context(self,state):
        world=state.get('world',{}).get('world_generation')
        if world!=self.world:self.world=world;self.records={}
    def begin(self,state,target,now):
        self.context(state)
        r=self.records.get(target['uuid'])
        if r is None or (r.get('suppressed_until',0)>0 and now >= r['suppressed_until']):
            r={'entity_type':target['type'],'started_at':now,'last_closing_at':now,'best_distance':target['distance'],
               'last_health_progress_at':now,'lowest_health':target.get('health'),
               'dispatches':0,'last_counter':0,'request_id':None,'loss_requests':set(),
               'suppressed_until':0,'reason':'closing_for_melee'}
            self.records[target['uuid']]=r
        return r
    def observe(self,state,target,combat,now,damaged):
        self.context(state)
        identity=combat.get('target_uuid')
        r=self.records.get(identity)
        if r is None and target:r=self.begin(state,target,now)
        if not r:return None
        count=combat.get('attack_dispatches',0)
        request=combat.get('request_id')
        if type(count) is int:
            delta=count if request!=r['request_id'] else max(0,count-r['last_counter'])
            r['dispatches']+=delta;r['last_counter']=count;r['request_id']=request
        if target:
            distance=target.get('distance',math.inf)
            if r['best_distance'] is None or distance<r['best_distance']-.2:
                r['best_distance']=distance;r['last_closing_at']=now
            if not in_melee(state,target):
                if damaged and now-r['started_at']>=1:return 'health_falling_outside_melee'
                if now-r['last_closing_at']>=NO_CLOSING_LIMIT and not r['dispatches']:return 'no_observed_closing_progress'
        health=target.get('health') if target else combat.get('observed_target_health')
        if type(health) in (int,float) and (r['lowest_health'] is None or health<r['lowest_health']-.05):
            # Explicit resident observation is useful when its wider nearby list
            # contains the target; this still does not attribute damage to us.
            r['lowest_health']=health;r['last_health_progress_at']=now
        reason=str(combat.get('reason',''))
        if not combat.get('active') and ('target_missing' in reason or 'target_lost' in reason):
            r['loss_requests'].add(request or 'unknown')
            if len(r['loss_requests'])>=2 and not r['dispatches']:return 'repeated_target_loss_without_attack'
        if 'flat_approach_blocked' in reason:return 'observed_approach_blocked'
        if now-r['started_at']>=NO_ATTACK_LIMIT and not r['dispatches']:return 'no_attack_dispatch_before_deadline'
        if r['dispatches'] and now-r['last_health_progress_at']>=NO_HEALTH_PROGRESS_LIMIT:return 'no_observed_target_health_progress'
        return None
    def suppress(self,identity,now,reason):
        r=self.records.setdefault(identity,{})
        delay=REENGAGE_DELAY if r.get('entity_type') in RANGED else MELEE_REENGAGE_DELAY
        r.update(suppressed_until=now+delay,reason=reason)
        return r['suppressed_until']
    def summary(self):
        return {k:{a:v for a,v in r.items() if a!='loss_requests'} for k,r in self.records.items()}


def retreat_plan(state,terrain,target):
    """At most two cardinal dry, flat waypoints; never invent unseen landing cells."""
    if terrain.get('complete') is not True or terrain.get('world_generation')!=state.get('world',{}).get('world_generation'):
        return None
    p=state.get('player',{})
    if p.get('on_ground') is not True:return None
    try:x,y,z=xyz(p);tx,ty,tz=xyz(target)
    except ValueError:return None
    if abs(y-round(y))>.05:return None
    y=round(y);cells={(c.get('x'),c.get('y'),c.get('z')):c for c in terrain.get('cells',[])}
    def clear_column(x,z):
        for h in (-1,0,1):
            c=cells.get((x,y+h,z),{})
            if (c.get('status')!='loaded' or c.get('known') is not True or c.get('collision_known') is not True
                    or c.get('fluid')!='minecraft:empty' or c.get('hazards')!=[]):return False
            if h==-1 and c.get('full_top_support') is not True:return False
            if h!=-1 and c.get('collision_empty') is not True:return False
        return True
    def swept(a,b):
        # Conservative full swept rectangle: finite point sampling can miss a
        # corner column while the player's body crosses two grid boundaries.
        xs=range(math.floor(min(a[0],b[0])-.31),math.floor(max(a[0],b[0])+.31)+1)
        zs=range(math.floor(min(a[1],b[1])-.31),math.floor(max(a[1],b[1])+.31)+1)
        return all(clear_column(cx,cz) for cx in xs for cz in zs)
    def occluded(px,pz):
        # A known full cube intersects a straight line, not a potion-blocking guarantee.
        try:
            top=xyz(target['bounding_box']['max'])[1]
            eye_y=xyz(p['eye_position'])[1]
        except (ValueError,KeyError,TypeError):return False
        source=(tx,top-.1,tz);dest=(px,eye_y,pz)
        length=math.dist(source,dest)
        for i in range(1,max(2,math.ceil(length/.2))):
            f=i/max(2,math.ceil(length/.2));pos=tuple(math.floor(a+(b-a)*f) for a,b in zip(source,dest))
            c=cells.get(pos,{})
            if (c.get('status')=='loaded' and c.get('known') is True and c.get('collision_known') is True
                    and c.get('collision_bounds')==[0,0,0,1,1,1]):return True
        return False
    start=(math.floor(x),math.floor(z));base=math.hypot(x-tx,z-tz)
    paths=deque([(start,[],(x,z))]);seen={start};candidates=[]
    others=[e for e in state.get('nearby',{}).get('entities',[]) if e.get('uuid')!=target.get('uuid')
            and e.get('alive') is True and e.get('type') in HOSTILES]
    while paths:
        cell,path,actual=paths.popleft()
        if len(path)>=2:continue
        for dx,dz in ((1,0),(-1,0),(0,1),(0,-1)):
            dest=(cell[0]+dx,cell[1]+dz);center=(dest[0]+.5,dest[1]+.5)
            if dest in seen or not swept(actual,center):continue
            distance=math.hypot(center[0]-tx,center[1]-tz)
            if distance<base-.25:continue
            point={'x':center[0],'y':y,'z':center[1]}
            try:
                if any(horizontal(point,e)<horizontal(p,e)-.25 for e in others):continue
            except ValueError:continue
            seen.add(dest);new_path=path+[point];paths.append((dest,new_path,center))
            cover=occluded(*center)
            if distance>=base+1 or (cover and distance>=base-.1):
                candidates.append((cover,distance,len(new_path),new_path))
    if not candidates:return None
    cover,distance,_,path=max(candidates,key=lambda c:(c[0],c[1],-c[2]))
    return {'waypoints':path,'observed_straight_line_obstruction':cover,
            'initial_distance':base,'planned_distance':distance,'safe_position_guaranteed':False}
