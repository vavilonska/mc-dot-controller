"""Strict block-menu-v1 wire validation, never an alternate admission authority."""
from math import dist, floor, hypot, isfinite

FAMILIES = {'minecraft:crafting_table': ('CraftingMenu', '', set()),
    'minecraft:furnace': ('FurnaceMenu', 'FurnaceBlockEntity', {'facing','lit'}),
    'minecraft:blast_furnace': ('BlastFurnaceMenu', 'BlastFurnaceBlockEntity', {'facing','lit'}),
    'minecraft:smoker': ('SmokerMenu', 'SmokerBlockEntity', {'facing','lit'}),
    'minecraft:dispenser': ('DispenserMenu', 'DispenserBlockEntity', {'facing','triggered'}),
    'minecraft:dropper': ('DispenserMenu', 'DropperBlockEntity', {'facing','triggered'}),
    'minecraft:barrel': ('ChestMenu', 'BarrelBlockEntity', {'facing','open'})}
STATIC_IDS = set(FAMILIES) | {'minecraft:' + v for v in ('air','cave_air','void_air','stone',
    'cobblestone','dirt','grass_block','smooth_stone','stone_bricks','bedrock',
    'oak_planks','spruce_planks','birch_planks')}
FACES = {'down': (0,-1,0), 'up': (0,1,0), 'north': (0,0,-1), 'south': (0,0,1), 'west': (-1,0,0), 'east': (1,0,0)}

def require(ok, reason):
    if not ok:
        raise ValueError('block_menu_' + reason)

def number(v):
    return type(v) in (int,float) and isfinite(v)

def coord(v):
    return type(v) is dict and set(v) == {'x','y','z'} and all(type(v[k]) is int and abs(v[k]) <= 30000000 for k in v)

def vector(v):
    return type(v) is dict and set(v) == {'x','y','z'} and all(number(n) for n in v.values())

def xyz(v):
    return tuple(v[k] for k in ('x','y','z'))

def cell(v):
    if type(v) is not dict or set(v) != {'x','y','z','id','properties','loaded','fluid','collision','outline'}:
        return False
    if not coord({k:v[k] for k in ('x','y','z')}) or v['id'] not in STATIC_IDS or v['loaded'] is not True or v['fluid'] != 'minecraft:empty':
        return False
    if type(v['properties']) is not dict or len(v['properties']) > 32 or not all(type(k) is str and type(n) is str for k,n in v['properties'].items()):
        return False
    for key in ('collision','outline'):
        if type(v[key]) is not list or len(v[key]) > 32:
            return False
        for box in v[key]:
            if type(box) is not list or len(box) != 6 or not all(number(n) and 0 <= n <= 1 for n in box) or not all(box[i] < box[i+3] for i in range(3)):
                return False
    return True

def validate(value, native, intent):
    """Bind exact native target/geometry coverage and final post-hook ray to original intent."""
    facts = value['facts']; b = facts.get('block_menu'); result = native.get('result', {})
    require(type(b) is dict and set(b) == {'version','topology','target','block_entity_class','expected_open_menu_class',
        'menu_footprint','ray_cells','body_cells','support','eye','expected_hit','face','reach','line_of_sight_clear',
        'on_ground','stationary','velocity','body_bounds','not_riding_or_flying','empty_hands','support_and_body_safe'}, 'coverage_fields')
    require(b['version'] == 'block-menu-v1' and b['topology'] == 'vanilla-single-cell/1', 'topology')
    require(intent.get('expected_block_id') in FAMILIES and cell(b['target']), 'supported_target')
    target = b['target']; name, entity, props = FAMILIES[intent['expected_block_id']]
    require(coord(intent.get('target')) and xyz(target) == xyz(intent['target']) and target['id'] == intent['expected_block_id']
        and type(intent.get('expected_block_properties')) is dict and target['properties'] == intent['expected_block_properties']
        and set(target['properties']) == props, 'exact_target_binding')
    require(b['expected_open_menu_class'] == intent.get('expected_open_menu_class') == 'net.minecraft.world.inventory.' + name
        and b['block_entity_class'] == ('net.minecraft.world.level.block.entity.' + entity if entity else ''), 'menu_family_binding')
    require(b['menu_footprint'] == [target], 'exact_single_cell_footprint')
    require(b['face'] == intent.get('face') and b['face'] in FACES and vector(b['eye']) and vector(b['expected_hit'])
        and number(b['reach']) and 0 < b['reach'] <= 6, 'ray_binding')
    expected = tuple(target[k]+.5+FACES[b['face']][i]*.5 for i,k in enumerate(('x','y','z')))
    require(xyz(b['expected_hit']) == expected and dist(xyz(b['eye']), expected) <= b['reach'], 'native_reach')
    require(all(b[k] is True for k in ('line_of_sight_clear','on_ground','stationary','not_riding_or_flying','empty_hands','support_and_body_safe')),
        'safety_predicates')
    require(vector(b['velocity']) and hypot(b['velocity']['x'],b['velocity']['z']) <= .0001 and abs(b['velocity']['y']) <= .1,
        'stationary_velocity')
    lo = tuple(floor(min(b['eye'][k],expected[i])) for i,k in enumerate(('x','y','z')))
    hi = tuple(floor(max(b['eye'][k],expected[i])) for i,k in enumerate(('x','y','z')))
    coords = [(x,y,z) for x in range(lo[0],hi[0]+1) for y in range(lo[1],hi[1]+1) for z in range(lo[2],hi[2]+1)]
    require(1 <= len(coords) <= 512 and type(b['ray_cells']) is list and len(b['ray_cells']) == len(coords)
        and all(cell(v) and xyz(v) == c for v,c in zip(b['ray_cells'],coords)), 'complete_ray_footprint')
    bounds = b['body_bounds']; support = b['support']
    require(type(bounds) is list and len(bounds) == 6 and all(number(v) for v in bounds) and coord(support)
        and all(bounds[i] < bounds[i+3] for i in range(3)) and bounds[0] >= support['x'] and bounds[3] <= support['x']+1
        and bounds[2] >= support['z'] and bounds[5] <= support['z']+1 and abs(bounds[1]-support['y']-1) < .001,
        'body_support_topology')
    body_coords = [(support['x'], y, support['z']) for y in range(support['y'], floor(bounds[4])+1)]
    require(2 <= len(body_coords) <= 4 and type(b['body_cells']) is list and len(b['body_cells']) == len(body_coords)
        and all(cell(v) and xyz(v) == c for v,c in zip(b['body_cells'],body_coords))
        and b['body_cells'][0]['collision'] == [[0.0,0.0,0.0,1.0,1.0,1.0]]
        and all(v['collision'] == [] for v in b['body_cells'][1:]), 'complete_body_support_footprint')
    overlap = {}
    for row in b['ray_cells'] + b['body_cells'] + b['menu_footprint']:
        key = xyz(row); require(key not in overlap or overlap[key] == row, 'overlapping_cell_disagreement'); overlap[key] = row
    require(facts['screen_class'] == '' and facts['menu']['menu_class'] == 'net.minecraft.world.inventory.InventoryMenu'
        and facts['menu']['container_id'] == 0 and facts['menu']['carried']['empty'] is True
        and facts['equipment']['mainhand']['empty'] is True and facts['equipment']['offhand']['empty'] is True
        and facts['hurt_time'] == 0 and not any(facts[k] for k in ('on_fire','in_water','in_lava','powder_snow','using_item')),
        'state_safety')
    require(value.get('effect_callback') == 'native-post-use-hooks-packet/1', 'post_hook_seam')
    require(result.get('local_use_started') is not True or native.get('status') == 'succeeded', 'late_native_rejection_unknown')
    if result.get('dispatched') is True:
        ray = value.get('final_ray')
        require(value.get('dispatch_fence_confirmed') is True and type(ray) is dict
            and set(ray) == {'target','face','hit','eye','reach','yaw','pitch','line_of_sight_clear'}
            and ray['target'] == intent['target'] and ray['face'] == intent['face'] and vector(ray['hit'])
            and vector(ray['eye']) and ray['eye'] == b['eye'] and ray['reach'] == b['reach']
            and dist(xyz(ray['hit']),expected) <= .0001 and number(ray['yaw']) and number(ray['pitch'])
            and -90 <= ray['pitch'] <= 90 and ray['line_of_sight_clear'] is True, 'final_actual_ray')
    else:
        # Native local hooks may already have side effects even if its packet was withheld.
        require(native.get('status') in ('failed','cancelled') and result.get('dispatched') is False
            and result.get('local_use_started') is not True and result.get('local_click_hooks_started') is not True
            and value.get('dispatch_fence_confirmed') is False and 'final_ray' not in value,
            'late_local_effect_unknown')
    return b
