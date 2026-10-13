"""Reusable bounded loaded exploration, boats and physical End traversal.

Every segment is a separate fresh guarded action. Unknown responses and failed
postconditions are never replayed. No coordinate writes, commands or chunk loads.
"""
from __future__ import annotations
from collections import deque
import math
from .core import Outcome, SkillError, require
from . import inventory, reach

AIR = frozenset(('minecraft:air', 'minecraft:cave_air', 'minecraft:void_air'))
BUILD_BLOCKS = frozenset(('minecraft:cobblestone','minecraft:stone','minecraft:end_stone',
    'minecraft:stone_bricks','minecraft:oak_planks','minecraft:obsidian','minecraft:purpur_block'))


def _feet(observation):
    return reach.Block(*(math.floor(observation.player[k]+(.01 if k=='y' else 0)) for k in ('x','y','z')))


def _xyz(block): return dict(x=block.x,y=block.y,z=block.z)


def _safety(observation, min_health, *, ground=True):
    require(type(min_health) in (int,float) and math.isfinite(min_health) and 8 <= min_health <= 20,
            'mobility_min_health_8_to20')
    p=observation.player
    require(type(p.get('health')) in (int,float) and math.isfinite(p['health']) and p['health']>min_health,
            'mobility_health_guard')
    if ground: require(p.get('on_ground') is True,'mobility_ground_required')
    require(not any(e.get('id')=='minecraft:levitation' for e in p.get('effects',[])), 'mobility_levitation_stop')
    if observation.context[1]=='minecraft:the_end':
        require(any(s.get('slot')=='head' and s.get('id')=='minecraft:carved_pumpkin' and s.get('count',0)>0
                    for s in p.get('armor',[])), 'end_mobility_pumpkin_required')
        nearby=observation.state.get('nearby',{})
        require(nearby.get('truncated') is False,'end_nearby_entities_truncated')
        for e in nearby.get('entities',[]):
            if e.get('type')=='minecraft:enderman' and e.get('alive') is True:
                require(e.get('aggressive') is False,'end_aggressive_or_unknown_enderman')
    return {'min_health':min_health, 'require_pumpkin':observation.context[1]=='minecraft:the_end'}


def safe_edge(grid, a, b):
    if not grid.standable(a) or not grid.standable(b):return False
    dx,dy,dz=b.x-a.x,b.y-a.y,b.z-a.z
    if max(abs(dx),abs(dz))!=1 or abs(dy)>1:return False
    if dx and dz:return (dy==0 and not any(grid.cells.get(p.offset(y=-1),reach.Cell(p)).partial for p in (a,b,a.offset(x=dx),a.offset(z=dz)))
        and grid.standable(a.offset(x=dx)) and grid.standable(a.offset(z=dz)))
    if dy==1:return grid.clear(a.offset(y=2)) and grid.clear(b.offset(y=2))
    if dy==-1:return grid.clear(b.offset(y=2))
    return True


def loaded_paths(grid,start, *, max_steps=32,max_expansions=2048):
    """Breadth-first complete local reachability under the explicit dry step policy."""
    require(grid.standable(start),'mobility_start_not_standable')
    queue=deque([start]);paths={start:(start,)}
    while queue:
        source=queue.popleft();path=paths[source]
        if len(path)-1>=max_steps:continue
        for dx,dz in ((1,0),(-1,0),(0,1),(0,-1),(1,1),(1,-1),(-1,1),(-1,-1)):
            for dy in ((0,) if dx and dz else (0,1,-1)):
                target=source.offset(x=dx,y=dy,z=dz)
                if target in paths or not safe_edge(grid,source,target):continue
                require(len(paths)<max_expansions,'mobility_expansion_budget')
                paths[target]=path+(target,);queue.append(target)
    return paths


def _path_command(route,flags):
    points=[]
    for a,b in zip(route,route[1:]):points.append({'x':b.x+.5,'y':b.y,'z':b.z+.5,'jump':b.y>a.y})
    if not points:
        b=route[-1];points=[{'x':b.x+.5,'y':b.y,'z':b.z+.5,'jump':False}]
    return {'op':'action','action':'follow_path','waypoints':points,'capability_route':True,
            'timeout_ms':min(60000,3000+1800*len(points)),**flags}


def navigate_loaded(runtime, goal, *, max_segments=128,max_steps=32,min_health=12,
                    max_unstuck=0,control=None):
    """Replan within freshly observed terrain until the goal or finite segment budget.

    Unknown terrain blocks routes; unvisited reachable frontiers guide exploration.
    This is not a claim that an arbitrary global route exists.
    """
    goal=reach.Block.parse(reach.coordinate(goal))
    require(type(max_segments)is int and 1<=max_segments<=128,'mobility_segment_budget_1_to128')
    require(type(max_steps)is int and 1<=max_steps<=64,'mobility_step_budget_1_to64')
    require(type(max_unstuck)is int and 0<=max_unstuck<=4,'mobility_unstuck_budget_0_to4')
    # max_unstuck=0 preserves legacy routing. A positive bound enables guarded
    # alternate-frontier detours after a settled segment; never retry a failed
    # or unknown move. Both modes retain the original finite segment budget.
    visited=set();ids=[];origin=None;previous=None;unstuck=0;allocated_steps=0
    for index in range(max_segments):
        if control is not None:control.checkpoint()
        before=runtime.observe(terrain=True,radius=4,vertical=4,entity_radius=16)
        flags=_safety(before,min_health);origin=origin or before.context
        require(before.context==origin,'mobility_context_changed')
        target={'x':goal.x+.5,'y':goal.y,'z':goal.z+.5}
        if reach._arrived(before.player,target):
            result=runtime.result('mobility.navigate_loaded',[before],goal=target,segments=index,
                explored_frontiers=len(visited),scope='fresh_loaded_segments')
            return Outcome(result.status,result.reason,tuple(ids)+result.request_ids,result.evidence,before)
        grid,stamp=reach._grid(before);grid.require_fresh(stamp,runtime.clock())
        start=_feet(before);paths=loaded_paths(grid,start,max_steps=max_steps)
        if goal in paths:route=paths[goal]
        else:
            candidates=[p for p in paths if p!=start and p not in visited]
            require(candidates,'mobility_no_unvisited_loaded_frontier')
            frontier=[p for p in candidates if max(abs(p.x-start.x),abs(p.z-start.z))>=2]
            selected=min(frontier or candidates,key=lambda p:(math.hypot(p.x-goal.x,p.z-goal.z)+abs(p.y-goal.y)*2,-len(paths[p]),p.x,p.y,p.z))
            route=paths[selected]
        end=route[-1];position={'x':end.x+.5,'y':end.y,'z':end.z+.5}
        distance=lambda p:math.hypot(p.x-goal.x,p.z-goal.z)+abs(p.y-goal.y)*2
        detour=previous is not None and distance(end)>=distance(start)
        if max_unstuck and detour:
            proof=previous.evidence
            ticks=proof.get('stable_game_times')
            require(previous.ok and previous.last_observation is not None
                    and proof.get('native_status')=='succeeded'
                    and proof.get('level')=='client_observed_stable'
                    and isinstance(proof.get('native_action_id'),str) and bool(proof['native_action_id'])
                    and bool(previous.request_ids)
                    and isinstance(ticks,list) and len(ticks)>=2
                    and all(type(t)is int for t in ticks)
                    and all(a<b for a,b in zip(ticks,ticks[1:]))
                    and ticks[-1]<=previous.last_observation.tick
                    and previous.last_observation.context==before.context
                    and before.tick>previous.last_observation.tick,
                    'mobility_unstuck_previous_settlement_or_freshness_unproven')
            require(unstuck<max_unstuck,'mobility_unstuck_budget_exhausted')
            unstuck+=1
            if control is not None:control.emit('route_unstuck',{
                'segment':index+1,'attempt':unstuck,'from':_xyz(start),'to':_xyz(end),
                'previous_request_ids':list(previous.request_ids),
                'fresh_game_time':before.tick,'reason':'fresh_unvisited_alternate_frontier'})
        if control is not None:
            control.checkpoint()
            control.emit('route_segment_planned',{'segment':index+1,'from':_xyz(start),
                'to':_xyz(end),'planned_steps':len(route)-1,'fresh_game_time':before.tick})
        allocated_steps+=len(route)-1
        result=runtime.execute('mobility.navigate_loaded',_path_command(route,flags),
            lambda old,new: reach._arrived(new.player,position),before=before)
        ids.extend(result.request_ids)
        if control is not None:control.emit('route_segment_result',{
            'segment':index+1,'status':result.status,'reason':result.reason,
            'request_ids':list(result.request_ids),'planned_steps_total':allocated_steps,
            'movement_accounting':'planned_route_steps_not_actual_physical_distance'})
        if not result.ok:return Outcome(result.status,result.reason,tuple(ids),result.evidence,result.last_observation)
        previous=result
        visited.add(start);visited.add(end)
        if end==goal:return Outcome(result.status,result.reason,tuple(ids),{**result.evidence,
            'segments':index+1,'goal':target,'unstuck_detours':unstuck,
            'planned_route_steps':allocated_steps},result.last_observation)
    raise SkillError('mobility_segment_budget_exhausted')


def _material(runtime,block_id,hotbar_slot):
    require(block_id in BUILD_BLOCKS,'mobility_safe_fullcube_material_required')
    selected=runtime.require_success(inventory.ensure_hotbar(runtime,block_id,hotbar_slot=hotbar_slot))
    return selected.player['selected_slot']


def _placement(before,support,target,face,block_id,slot,flags,**extra):
    base=reach.block_at(before,support);empty=reach.block_at(before,target)
    require(empty['id'] in AIR and empty.get('fluid')=='minecraft:empty','mobility_target_not_dry_air')
    return {'op':'action','action':'place_block','support':support,'face':face,'hotbar_slot':slot,
        'expected_support_id':base['id'],'expected_support_properties':base['properties'],
        'expected_target_id':empty['id'],'expected_target_properties':empty['properties'],
        'expected_block_id':block_id,'expected_block_properties':{},'timeout_ms':5000,**flags,**extra}


def pillar_up(runtime, block_id='minecraft:cobblestone', *, hotbar_slot=3,min_health=12):
    slot=_material(runtime,block_id,hotbar_slot)
    before=runtime.observe(terrain=True);flags=_safety(before,min_health);feet=_feet(before)
    require(abs(before.player['x']-feet.x-.5)<.2 and abs(before.player['z']-feet.z-.5)<.2,'pillar_centered_pose_required')
    grid,_=reach._grid(before)
    require(grid.standable(feet) and all(grid.clear(feet.offset(y=i)) for i in range(1,4)),'pillar_headroom_or_support_unknown')
    count=inventory.count(before,block_id);target=_xyz(feet)
    command=_placement(before,_xyz(feet.offset(y=-1)),target,'up',block_id,slot,flags,jump=True)
    end={'x':feet.x+.5,'y':feet.y+1,'z':feet.z+.5}
    def verify(old,new):
        try:return reach.block_at(new,target)['id']==block_id and inventory.count(new,block_id)==count-1 and reach._arrived(new.player,end)
        except SkillError:return False
    return runtime.execute('mobility.pillar_up',command,verify,before=before,max_samples=32)


def pillar_down(runtime, expected_block_id, *, hotbar_slot=2,min_health=12):
    require(expected_block_id in BUILD_BLOCKS,'descent_safe_fullcube_required')
    before=runtime.observe(terrain=True);flags=_safety(before,min_health);feet=_feet(before)
    grid,_=reach._grid(before);support=feet.offset(y=-1);lower=feet.offset(y=-2)
    require(grid.support(lower) and grid.clear(feet) and grid.clear(feet.offset(y=1)),'descent_lower_support_unknown')
    require(abs(before.player['x']-feet.x-.5)<.2 and abs(before.player['z']-feet.z-.5)<.2,'pillar_centered_pose_required')
    cell=reach.block_at(before,_xyz(support));require(cell['id']==expected_block_id,'descent_support_changed')
    command={'op':'action','action':'break_block','target':_xyz(support),'hotbar_slot':hotbar_slot,
        'expected_block_id':cell['id'],'expected_block_properties':cell['properties'],
        'require_correct_tool':True,'capability_descent':True,'timeout_ms':15000,**flags}
    end={'x':feet.x+.5,'y':feet.y-1,'z':feet.z+.5}
    def verify(old,new):
        try:return reach.block_at(new,_xyz(support))['id'] in AIR and reach._arrived(new.player,end)
        except SkillError:return False
    return runtime.execute('mobility.pillar_down',command,verify,before=before,max_samples=32)


def bridge_step(runtime, direction, block_id='minecraft:cobblestone', *, hotbar_slot=3,min_health=12):
    require(isinstance(direction,dict) and set(direction)=={'x','z'} and all(type(v)is int for v in direction.values())
            and abs(direction['x'])+abs(direction['z'])==1,'bridge_cardinal_direction_required')
    slot=_material(runtime,block_id,hotbar_slot)
    before=runtime.observe(terrain=True);flags=_safety(before,min_health);feet=_feet(before)
    grid,_=reach._grid(before);require(grid.standable(feet),'bridge_source_not_standable')
    dest=feet.offset(x=direction['x'],z=direction['z']);support=feet.offset(y=-1);target=dest.offset(y=-1)
    require(grid.clear(dest) and grid.clear(dest.offset(y=1)),'bridge_headroom_unknown')
    face=next(k for k,v in reach.FACES.items() if v==(direction['x'],0,direction['z']))
    count=inventory.count(before,block_id)
    command=_placement(before,_xyz(support),_xyz(target),face,block_id,slot,flags,sneak=True,capability_bridge=True)
    def verify(old,new):
        try:return reach.block_at(new,_xyz(target))['id']==block_id and inventory.count(new,block_id)==count-1 and new.player.get('on_ground') is True
        except SkillError:return False
    placed=runtime.execute('mobility.bridge_step',command,verify,before=before,max_samples=20)
    runtime.require_success(placed)
    moved=navigate_loaded(runtime,_xyz(dest),max_segments=1,min_health=min_health)
    return Outcome(moved.status,moved.reason,placed.request_ids+moved.request_ids,moved.evidence,moved.last_observation)


def gateway_pearl(runtime,target, *, hotbar_slot=4,min_health=12):
    require(type(min_health)in(int,float) and 12<=min_health<=20,'gateway_min_health_12_to20')
    target=reach.coordinate(target)
    selected=runtime.require_success(inventory.ensure_hotbar(runtime,'minecraft:ender_pearl',hotbar_slot=hotbar_slot))
    before=runtime.observe(terrain=True,radius=4,vertical=4,entity_radius=128);flags=_safety(before,min_health)
    require(before.context[1]=='minecraft:the_end','gateway_requires_end')
    nearby=before.state.get('nearby',{})
    require(nearby.get('end_gateways_truncated') is False,'gateway_discovery_truncated_or_unknown')
    match=[row for row in nearby.get('end_gateways',[]) if all(row.get(k)==target[k] for k in target)]
    require(len(match)==1 and match[0].get('id')=='minecraft:end_gateway' and match[0].get('cooling_down') is False,'gateway_not_fresh_or_cooling')
    eye=before.player.get('eye_position',{})
    require(all(k in eye for k in target) and math.dist([eye[k] for k in target],[target[k]+.5 for k in target ])<=4.7,'gateway_out_of_range')
    count=inventory.count(before,'minecraft:ender_pearl');origin=tuple(before.player[k] for k in ('x','y','z'))
    def verify(old,new):
        try:
            distance=math.dist(origin,tuple(new.player[k] for k in ('x','y','z')))
            grid,_=reach._grid(new);feet=_feet(new)
            native=new.state.get('client_action',{})
            proof=native.get('result',{})
            return (native.get('action')=='gateway_pearl' and proof.get('dispatched') is True
                and proof.get('gateway_aperture_envelope_proven') is True and proof.get('gateway_target')==target
                and type(proof.get('gateway_entry_tick_bound')) is int and 1<=proof['gateway_entry_tick_bound']<=4
                and new.context==old.context and 128<=distance<=4096 and new.player['health']>=old.player['health']-5
                and new.player['health']>min_health-5 and grid.standable(feet)
                and new.player.get('on_ground') is True and inventory.count(new,'minecraft:ender_pearl')==count-1
                and math.hypot(new.player.get('velocity',{}).get('x',1),new.player.get('velocity',{}).get('z',1))<=.08)
        except (SkillError,KeyError):return False
    return runtime.execute('mobility.gateway_pearl',{'op':'action','action':'gateway_pearl','target':target,
        'expected_block_id':'minecraft:end_gateway','expected_block_properties':match[0].get('properties',{}),
        'hotbar_slot':selected.player['selected_slot'],'timeout_ms':3000,**flags},verify,before=before,max_samples=128)


def _vehicle(observation,uuid=None):
    vehicle=observation.player.get('vehicle',{})
    require(vehicle.get('riding') is True and vehicle.get('ordinary_boat') is True
        and vehicle.get('controlling_seat') is True and vehicle.get('alive') is True
        and vehicle.get('type')=='minecraft:boat','sole_ordinary_boat_driver_required')
    require(vehicle.get('passengers')==[observation.player.get('uuid')],'sole_boat_passenger_required')
    require(uuid is None or vehicle.get('uuid')==uuid,'boat_vehicle_changed')
    return vehicle


def _select_empty(runtime,slot):
    before=runtime.observe()
    stack=next((s for s in inventory.items(before) if s.get('slot')==slot),{})
    require(stack.get('empty') is True and stack.get('count')==0 and isinstance(stack.get('item_fingerprint'),str),'exact_empty_hotbar_required')
    if before.player.get('selected_slot')==slot:
        return runtime.result('mobility.select_empty',[before],hotbar_slot=slot)
    return runtime.execute('mobility.select_empty',{'op':'action','action':'select_hotbar','hotbar_slot':slot,
        'expected_held_item':stack,'timeout_ms':3000},
        lambda old,new:new.player.get('selected_slot')==slot and any(s.get('slot')==slot and s.get('empty') is True and s.get('item_fingerprint')==stack['item_fingerprint'] for s in inventory.items(new)),before=before)


def boat_mount(runtime, vehicle_uuid, *, min_health=12):
    before=runtime.observe(entity_radius=8)
    require(before.player.get('vehicle',{}).get('riding') is False,'boat_mount_requires_unmounted')
    slots=[s['slot'] for s in inventory.items(before) if 0<=s.get('slot',-1)<=8 and s.get('empty') is True]
    require(slots,'boat_mount_empty_hotbar_slot_required')
    runtime.require_success(_select_empty(runtime,slots[0]))
    before=runtime.observe(entity_radius=8);_safety(before,min_health)
    rows=[e for e in before.state.get('nearby',{}).get('entities',[]) if e.get('uuid')==vehicle_uuid]
    require(before.state.get('nearby',{}).get('truncated') is False and len(rows)==1,'boat_target_not_uniquely_observed')
    boat=rows[0]
    require(boat.get('type')=='minecraft:boat' and boat.get('ordinary_boat') is True and boat.get('alive') is True
        and boat.get('passenger_count')==0,'empty_ordinary_boat_required')
    command={'op':'action','action':'boat_mount','boat_transfer_schema_version':1,'vehicle_uuid':vehicle_uuid,
        'vehicle_entity_id':boat['entity_id'],'vehicle_type':'minecraft:boat','expected_game_time':before.tick,'timeout_ms':5000}
    def verify(old,new):
        try:return _vehicle(new,vehicle_uuid)['entity_id']==boat['entity_id']
        except SkillError:return False
    return runtime.execute('mobility.boat_mount',command,verify,before=before,max_samples=20)


def boat_dismount(runtime, *, min_health=12):
    before=runtime.observe(terrain=True);_safety(before,min_health,ground=False);boat=_vehicle(before)
    # Native predicts the actual vanilla dismount candidate and requires dry support before sneak.
    command={'op':'action','action':'boat_dismount','boat_transfer_schema_version':1,'vehicle_uuid':boat['uuid'],
        'vehicle_entity_id':boat['entity_id'],'vehicle_type':'minecraft:boat','expected_game_time':before.tick,'timeout_ms':5000}
    def verify(old,new):
        try:
            grid,_=reach._grid(new)
            return new.player.get('vehicle',{}).get('riding') is False and new.player.get('on_ground') is True and grid.standable(_feet(new))
        except SkillError:return False
    return runtime.execute('mobility.boat_dismount',command,verify,before=before,max_samples=32)


def water_column(observation,x,z,surface):
    """Conservative 3x3 hull clearance; native continuously checks actual boat/passenger envelope."""
    for dx in (-1,0,1):
        for dz in (-1,0,1):
            for y in range(surface-2,surface+3):
                try:c=reach.block_at(observation,{'x':x+dx,'y':y,'z':z+dz})
                except SkillError:return False
                if c.get('collision_known') is not True or c.get('collision_empty') is not True:return False
                if y<surface:
                    if c.get('hazards')!=['water']:return False
                    if c.get('id')!='minecraft:water' or c.get('fluid')!='minecraft:water' or c.get('fluid_source') is not True:return False
                elif c.get('id') not in AIR or c.get('fluid')!='minecraft:empty' or c.get('hazards')!=[]:return False
    return True


def boat_travel(runtime, goal, *, water_surface_y,max_segments=128,min_health=12):
    require(isinstance(goal,dict) and set(goal)=={'x','z'} and all(type(v) is int for v in goal.values()),'boat_integer_goal_xz_required')
    require(type(water_surface_y) is int and -2048<=water_surface_y<=2048,'boat_water_surface_required')
    require(type(max_segments) is int and 1<=max_segments<=128,'boat_segment_budget_1_to128')
    target=(goal['x'],goal['z']);visited=set();ids=[];vehicle_id=None
    for segment in range(max_segments):
        before=runtime.observe(terrain=True,radius=4,vertical=4,entity_radius=16)
        _safety(before,min_health,ground=False);boat=_vehicle(before,vehicle_id);vehicle_id=boat['uuid']
        if math.hypot(boat['x']-target[0]-.5,boat['z']-target[1]-.5)<=.55:
            result=runtime.result('mobility.boat_travel',[before],segments=segment,destination=goal)
            return Outcome(result.status,result.reason,tuple(ids)+result.request_ids,result.evidence,before)
        start=(math.floor(boat['x']),math.floor(boat['z']));queue=deque([start]);paths={start:(start,)}
        require(water_column(before,*start,water_surface_y),'boat_start_water_corridor_unknown')
        while queue:
            at=queue.popleft()
            for dx,dz in ((1,0),(-1,0),(0,1),(0,-1)):
                next_cell=(at[0]+dx,at[1]+dz)
                if next_cell not in paths and water_column(before,*next_cell,water_surface_y):
                    require(len(paths)<512,'boat_local_expansion_budget')
                    paths[next_cell]=paths[at]+(next_cell,);queue.append(next_cell)
        if target in paths:route=paths[target]
        else:
            choices=[p for p in paths if p!=start and p not in visited]
            require(choices,'boat_no_unvisited_loaded_water_frontier')
            end=min(choices,key=lambda p:(math.hypot(p[0]-target[0],p[1]-target[1]),-len(paths[p]),p))
            route=paths[end]
        points=[{'x':p[0]+.5,'z':p[1]+.5} for p in route[1:]]
        require(points,'boat_empty_segment')
        last=points[-1]
        def verify(old,new):
            try:
                v=_vehicle(new,vehicle_id)
                return math.hypot(v['x']-last['x'],v['z']-last['z'])<=.55 and v.get('horizontal_speed',1)<=.04 and abs(v.get('yaw_rate',1))<=.25
            except SkillError:return False
        outcome=runtime.execute('mobility.boat_travel',{'op':'action','action':'boat_drive','boat_schema_version':1,
            'vehicle_uuid':vehicle_id,'vehicle_entity_id':boat['entity_id'],'vehicle_type':'minecraft:boat',
            'water_surface_y':water_surface_y,'waypoints':points,'timeout_ms':min(60000,5000+3000*len(points))},verify,before=before,max_samples=24)
        ids.extend(outcome.request_ids)
        if not outcome.ok:return Outcome(outcome.status,outcome.reason,tuple(ids),outcome.evidence,outcome.last_observation)
        visited.update((start,route[-1]))
        if route[-1]==target:return Outcome(outcome.status,outcome.reason,tuple(ids),{**outcome.evidence,'segments':segment+1},outcome.last_observation)
    raise SkillError('boat_segment_budget_exhausted')
