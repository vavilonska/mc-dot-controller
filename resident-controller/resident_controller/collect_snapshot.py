"""Independent validator for the collect-only identity exemption in movement witnesses."""
import math
import re
from .capability_snapshot import _require, _integer, _number, exact

PROFILE = 'collect-local-observed-v1'
ITEMS = {'minecraft:' + name for name in
         ('stone','cobblestone','dirt','oak_planks','coal','stick','iron_nugget')}
UUID = r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}'
KEYS = {'entity_id','uuid','item_id','count','item_fingerprint','component_fingerprint','x','y','z'}


def validate_pickup(movement, witness, intent):
    target = movement.get('pickup_target')
    requested = intent.get('pickup_target')
    _require(witness.get('profile') == PROFILE and type(target) is dict and set(target) == KEYS | {'simple_components','on_ground','resting_envelope'}
             and target.get('simple_components') is True and target.get('on_ground') is True
             and target.get('resting_envelope') == 'vanilla-grounded-item-v1' and type(requested) is dict and set(requested) == KEYS
             and all(exact(target[k], requested[k]) for k in KEYS), 'collect_target_contract')
    _require(target.get('item_id') in ITEMS and _integer(target.get('entity_id'), -(2**31), 2**31-1)
             and _integer(target.get('count'),1,64)
             and all(type(target.get(k)) is str and re.fullmatch(UUID,target[k])
                     for k in ('uuid','item_fingerprint','component_fingerprint'))
             and all(_number(target.get(k)) for k in ('x','y','z')), 'collect_target_identity')
    point = intent['waypoints'][0]
    _require(all(math.floor(target[k]) == math.floor(point[k]) for k in ('x','y','z'))
             and point['y'] <= target['y'] <= point['y'] + .25,
             'collect_target_goal_cell')
    guard = movement.get('entity_guard')
    _require(type(guard) is dict and type(guard.get('rows')) is list, 'collect_entity_guard_required')
    matches = [r for r in guard['rows'] if type(r) is dict and r.get('uuid') == target['uuid']]
    _require(len(matches) == 1 and matches[0].get('type') == 'minecraft:item'
             and matches[0].get('class') == 'net.minecraft.world.entity.item.ItemEntity'
             and matches[0].get('id') == target['entity_id'] and matches[0].get('removed') is False
             and matches[0].get('verdict') == 'pickup_target'
             and type(matches[0].get('position')) is list and len(matches[0]['position']) == 3
             and all(_number(v) and abs(v-target[k]) <= .03 and math.floor(v) == math.floor(point[k])
                     for k,v in zip(('x','y','z'),matches[0]['position']))
             and point['y'] <= matches[0]['position'][1] <= point['y'] + .25
             and exact(matches[0].get('lerp_target'),matches[0]['position'])
             and type(matches[0].get('velocity')) is list and len(matches[0]['velocity']) == 3
             and all(_number(v) for v in matches[0]['velocity'])
             and math.hypot(matches[0]['velocity'][0],matches[0]['velocity'][2]) <= .003
             and -.120000001 <= matches[0]['velocity'][1] <= 0,
             'collect_target_entity_agreement')
