"""Closed typed item witness: independent inventory, block and one-packet evidence."""
import math
from .capability_snapshot import _require, _integer, exact, signed_long_string, validate_movement_entity_guard
from .mining_snapshot import coordinate, AIR, LEGACY_STATIC

PROFILE='item-on-block-observed-v1'
COMMON={'action_id','action','timeout_ms','expected_navigation_epoch','expected_origin','capability_guard',
    'expected_world_generation','expected_dimension','expected_player_uuid','expected_action_session','expected_hotbar_slot','expected_held_item'}
INTENT=COMMON|{'target','face','expected_block_id','expected_block_properties','typed_item_interaction','item_hit','item_footprint'}
KEYS={'profile','source','kind','target','standing_support','typed_item_interaction','item_hit','item_footprint',
    'selected_slot','initial_count','initial_damage','min_x','max_x','min_y','max_y','min_z','max_z','expected_cells','cells',
    'all_loaded','complete','callbacks_installed','maximum_action_ticks','maximum_timeout_ms','deadline_nano','entity_guard'}
TERMINAL={'profile','kind','target','effect_attempted','use_count','local_effect_count','packet_count','unknown_outcome',
    'consumption_verified','durability_verified','block_outcome_verified','input_neutral','protected_inventory_unchanged',
    'selected_slot','initial_count','final_count','initial_damage','final_damage','local_checks','guard_reason','deadline_nano',
    'automatic_replay_allowed','server_confirmed'}
STACK=('id','count','empty','item_fingerprint','component_fingerprint','max_stack_size')
CELL={'x','y','z','id','state','block_class','loaded','fluid','properties'}
STATIC=LEGACY_STATIC|{'minecraft:obsidian','minecraft:netherrack','minecraft:end_stone'}


def offset(p,x=0,y=0,z=0):
    v={k:p[k]+n for k,n in zip(('x','y','z'),(x,y,z))}
    _require(coordinate(v),'item_interaction_coordinate_bounds');return v


def row(p,before,props,after,final):
    return {'position':p,'expected_id':before,'expected_properties':props,'block_id':after,'properties':final}


def expected_footprint(intent):
    _require(type(intent) is dict and INTENT<=set(intent)<=INTENT|{'hotbar_slot','jump','sneak'}
        and intent['action']=='interact_block' and _integer(intent['timeout_ms'],50,3000)
        and exact(intent.get('hotbar_slot',-1),-1) and intent.get('jump',False) is False and intent.get('sneak',False) is False
        and intent['face']=='up' and coordinate(intent['target']), 'item_interaction_closed_intent')
    m=intent['typed_item_interaction'];target=intent['target'];out=[]
    _require(type(m) is dict,'item_interaction_typed_metadata')
    if m.get('kind')=='ignite_nether_portal':
        _require(set(m)=={'kind','interior_base','axis','width','height'} and coordinate(m['interior_base'])
            and m['axis'] in ('x','z') and _integer(m['width'],2,4) and _integer(m['height'],3,4)
            and intent['expected_dimension'] in ('minecraft:overworld','minecraft:the_nether'), 'item_interaction_ignition_geometry')
        base=m['interior_base'];w=m['width'];h=m['height'];axis=m['axis']
        def point(u,v):return offset(base,x=u if axis=='x' else 0,y=v,z=u if axis=='z' else 0)
        _require(exact(target,point(0,-1)) and intent['expected_block_id']=='minecraft:obsidian'
            and exact(intent['expected_block_properties'],{}),'item_interaction_ignition_target')
        for u,v in [(u,v) for u in range(w) for v in (-1,h)]+[(u,v) for u in (-1,w) for v in range(h)]:
            out.append(row(point(u,v),'minecraft:obsidian',{},'minecraft:obsidian',{}))
        for u in range(w):
            for v in range(h):out.append(row(point(u,v),'minecraft:air',{},'minecraft:nether_portal',{'axis':axis}))
    else:
        _require(m.get('kind')=='insert_end_eye' and set(m)=={'kind','interior_corner'} and coordinate(m['interior_corner'])
            and intent['expected_dimension']=='minecraft:overworld','item_interaction_eye_geometry')
        supplied=intent['item_footprint'];base=m['interior_corner'];missing=0;found=False
        _require(type(supplied) is list and len(supplied)==21,'item_interaction_end_ring_coverage')
        for i in range(3):
            for side,(p,facing) in enumerate([(offset(base,x=i,z=-1),'south'),(offset(base,x=i,z=3),'north'),
                    (offset(base,x=-1,z=i),'east'),(offset(base,x=3,z=i),'west')]):
                r=supplied[i*4+side];props=r.get('expected_properties') if type(r) is dict else None
                _require(type(props) is dict and set(props)=={'facing','eye'} and props['facing']==facing
                    and props['eye'] in ('true','false'),'item_interaction_end_frame_properties')
                missing+=props['eye']=='false';final=dict(props)
                if p==target:
                    _require(props['eye']=='false' and exact(intent['expected_block_properties'],props),'item_interaction_eye_target_properties')
                    found=True;final['eye']='true'
                out.append(row(p,'minecraft:end_portal_frame',props,'minecraft:end_portal_frame',final))
        _require(found and intent['expected_block_id']=='minecraft:end_portal_frame','item_interaction_eye_target')
        for x in range(3):
            for z in range(3):out.append(row(offset(base,x=x,z=z),'minecraft:air',{},'minecraft:end_portal' if missing==1 else 'minecraft:air',{}))
    hit={'x':target['x']+.5,'y':target['y']+(13/16 if m['kind']=='insert_end_eye' else 1),'z':target['z']+.5}
    _require(exact(intent['item_footprint'],out) and exact(intent['item_hit'],hit),'item_interaction_exact_hit_and_footprint')
    return out


def validate_cells(p,bounds,allowed,expected_rows=None):
    coords=[(x,y,z) for x in range(bounds['min_x'],bounds['max_x']+1)
        for y in range(bounds['min_y'],bounds['max_y']+1) for z in range(bounds['min_z'],bounds['max_z']+1)]
    _require(type(p['cells']) is list and len(p['cells'])==len(coords)==p['expected_cells'],'item_interaction_complete_cells')
    rows={}
    for c,xyz in zip(p['cells'],coords):
        _require(type(c) is dict and set(c)==CELL and all(exact(c[k],n) for k,n in zip(('x','y','z'),xyz))
            and c['id'] in allowed and c['loaded'] is True and c['fluid']=='minecraft:empty'
            and type(c['state']) is str and 0<len(c['state'])<=512 and type(c['properties']) is dict,'item_interaction_cell')
        cls={'minecraft:grass_block':'GrassBlock','minecraft:netherrack':'NetherrackBlock','minecraft:end_portal_frame':'EndPortalFrameBlock',
            'minecraft:nether_portal':'NetherPortalBlock','minecraft:end_portal':'EndPortalBlock'}.get(c['id'],'AirBlock' if c['id'] in AIR else 'Block')
        _require(c['block_class']=='net.minecraft.world.level.block.'+cls,'item_interaction_cell_class')
        props=c['properties'];id=c['id']
        valid=(set(props)=={'snowy'} and props['snowy'] in ('true','false') if id=='minecraft:grass_block' else
            set(props)=={'facing','eye'} and props['facing'] in ('north','south','east','west') and props['eye'] in ('true','false') if id=='minecraft:end_portal_frame' else
            set(props)=={'axis'} and props['axis'] in ('x','z') if id=='minecraft:nether_portal' else props=={})
        _require(valid,'item_interaction_cell_properties');rows[xyz]=c
    if expected_rows is not None:
        for row in expected_rows:
            c=rows[tuple(row['position'][k] for k in ('x','y','z'))]
            _require(c['id']==row['expected_id'] and exact(c['properties'],row['expected_properties']),'item_interaction_source_footprint')
    return rows


def validate_request(scope,intent):
    _require(type(scope) is dict and type(intent) is dict,'item_interaction_request_objects')
    if scope.get('profile')!=PROFILE:
        _require(not {'typed_item_interaction','item_hit','item_footprint'}&set(intent),'item_interaction_profile_mismatch')
        return
    expected_footprint(intent)


def validate_item_interaction(witness,intent,native):
    validate_request({"profile":PROFILE},intent)
    expected=expected_footprint(intent);facts=witness['facts'];p=facts.get('item_interaction')
    _require(type(p) is dict and set(p)==KEYS and p['profile']==PROFILE and p['source']=='native-client-loaded-level'
        and all(exact(p[k],intent[k]) for k in ('target','typed_item_interaction','item_hit','item_footprint'))
        and p['kind']==intent['typed_item_interaction']['kind'],'item_interaction_closed_coverage')
    standing={'x':math.floor(facts['x']),'y':math.floor(facts['y']-.01),'z':math.floor(facts['z'])}
    _require(exact(p['standing_support'],standing) and abs(facts['y']-standing['y']-1)<1e-7
        and all(exact(intent['expected_origin'][k],facts[k]) for k in ('x','y','z')),'item_interaction_origin')
    positions=[standing]+[r['position'] for r in expected]
    bounds={prefix+k:func(v[k]+(3 if k=='y' and prefix=='max_' and v is standing else 0) for v in positions)+delta
        for k in ('x','y','z') for prefix,func,delta in (('min_',min,-1),('max_',max,1))}
    count=math.prod(bounds['max_'+k]-bounds['min_'+k]+1 for k in ('x','y','z'))
    _require(0<count<=512 and all(exact(p[k],v) for k,v in bounds.items()) and exact(p['expected_cells'],count),'item_interaction_bounds')
    rows=validate_cells(p,bounds,STATIC|{'minecraft:end_portal_frame'},expected)
    _require(rows[tuple(standing[k] for k in ('x','y','z'))]['id'] in STATIC-AIR
        and all(rows[(standing['x'],standing['y']+dy,standing['z'])]['id'] in AIR for dy in (1,2)), 'item_interaction_standing_support')
    _require(all(p[k] is True for k in ('all_loaded','complete','callbacks_installed')) and exact(p['maximum_action_ticks'],60)
        and exact(p['maximum_timeout_ms'],3000) and signed_long_string(p['deadline_nano'])
        and int(p['deadline_nano'])==int(witness['source_nano'])+intent['timeout_ms']*1000000,'item_interaction_fixed_deadline')
    validate_movement_entity_guard(p['entity_guard'],p,witness)
    slot=facts['selected_slot'];held=facts['inventory'][slot]['item'];eye=p['kind']=='insert_end_eye'
    _require(exact(p['selected_slot'],slot) and exact(intent['expected_hotbar_slot'],slot)
        and all(exact(intent['expected_held_item'].get(k),held.get(k)) for k in STACK)
        and held['id']==('minecraft:ender_eye' if eye else 'minecraft:flint_and_steel') and held['empty'] is False
        and exact(held['max_stack_size'],64 if eye else 1) and exact(p['initial_count'],held['count'])
        and _integer(p['initial_count'],1,64 if eye else 1) and _integer(p['initial_damage'],0,0 if eye else 62)
        and facts['screen_class']=='' and facts['effects']==[] and facts['hurt_time']==0
        and all(facts[k] is False for k in ('on_fire','in_water','in_lava','powder_snow','using_item'))
        and facts['menu']['menu_class']=='net.minecraft.world.inventory.InventoryMenu' and facts['menu']['container_id']==0
        and facts['menu']['carried']['empty'] is True,'item_interaction_selected_stack_and_player')
    if native.get('status') in ('succeeded','cancelled','failed'):
        result=native.get('result',{});t=result.get('item_interaction')
        _require(type(t) is dict and set(t)==TERMINAL and t['profile']==PROFILE and t['kind']==p['kind']
            and exact(t['target'],p['target']) and all(type(t[k]) is bool for k in ('effect_attempted','unknown_outcome','consumption_verified',
                'durability_verified','block_outcome_verified','input_neutral','protected_inventory_unchanged'))
            and t['automatic_replay_allowed'] is False and t['server_confirmed'] is False
            and all(_integer(t[k],0,1) for k in ('use_count','local_effect_count','packet_count'))
            and t['packet_count']<=t['use_count'] and (not eye or t['local_effect_count']==0)
            and all(exact(t[k],p[k]) for k in ('selected_slot','initial_count','initial_damage','deadline_nano'))
            and _integer(t['final_count'],0,64) and _integer(t['final_damage'],0,63) and _integer(t['local_checks'])
            and type(t['guard_reason']) is str,'item_interaction_terminal')
        if native['status']=='succeeded':
            _require(all(t[k] is True for k in ('effect_attempted','consumption_verified','durability_verified','block_outcome_verified','input_neutral','protected_inventory_unchanged'))
                and t['unknown_outcome'] is False and t['use_count']==t['packet_count']==1
                and t['local_effect_count']==(0 if eye else 1) and result.get('input_release_confirmed') is True
                and t['final_count']==t['initial_count']-(1 if eye else 0)
                and t['final_damage']==t['initial_damage']+(0 if eye else 1),'item_interaction_success_requires_all_outcomes')
        elif t['effect_attempted']:_require(t['unknown_outcome'] is True,'item_interaction_attempted_failure_unknown')
