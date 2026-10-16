"""Synthetic DEFAULT-STOP route evidence. Not native or game-physics evidence."""
from copy import deepcopy
from local_segment_fixture import fixture as legacy_fixture, terminal as legacy_terminal
from mining_collect.collect.collect_fixture import redigest

PROFILE = 'movement-local-segment-spatial-stop-v1'
POLICY = 'route-spatial-stop-v1'
# Literal fixture classes: deliberately independent of production consumer tables.
CLASSES = {
    'sheep': 'animal.Sheep', 'cow': 'animal.Cow', 'chicken': 'animal.Chicken', 'pig': 'animal.Pig',
    'frog': 'animal.frog.Frog', 'boat': 'vehicle.Boat', 'chest_minecart': 'vehicle.MinecartChest',
    'item': 'item.ItemEntity', 'bat': 'ambient.Bat', 'cod': 'animal.Cod', 'salmon': 'animal.Salmon',
    'tropical_fish': 'animal.TropicalFish', 'squid': 'animal.Squid', 'glow_squid': 'GlowSquid',
    'turtle': 'animal.Turtle', 'cat': 'animal.Cat', 'ocelot': 'animal.Ocelot', 'parrot': 'animal.Parrot',
    'horse': 'animal.horse.Horse', 'donkey': 'animal.horse.Donkey', 'mule': 'animal.horse.Mule',
    'villager': 'npc.Villager', 'wandering_trader': 'npc.WanderingTrader',
}
SWEPT_KINDS = frozenset(('sheep', 'cow', 'chicken', 'pig', 'frog', 'boat', 'chest_minecart', 'item'))
FAR_KINDS = frozenset(CLASSES) - SWEPT_KINDS


def witness(data): return (data if type(data) is dict else data[0])['result']['scoped_native_preflight']
def movement(data): return witness(data)['facts']['local_segment']
def guard(data): return movement(data)['entity_guard']


def sweep(m):
    return [min(m['start_x'], m['end_x']) + .5 - .400002, min(m['start_y'], m['end_y']) - .000001,
            min(m['start_z'], m['end_z']) + .5 - .400002, max(m['start_x'], m['end_x']) + .5 + .400002,
            m['start_y'] + (1.26 if m['step_dy'] > 0 else 0) + 1.800002,
            max(m['start_z'], m['end_z']) + .5 + .400002]


def project(row, horizon=160):
    output = [0.] * 6
    for i in range(3):
        l = row['lerp_target'][i] - row['position'][i]
        v = horizon * row['velocity'][i]
        output[i] = min(row['aabb'][i], row['aabb'][i] + l, row['aabb'][i] + v, (row['aabb'][i] + l) + v)
        output[i + 3] = max(row['aabb'][i + 3], row['aabb'][i + 3] + l, row['aabb'][i + 3] + v, (row['aabb'][i + 3] + l) + v)
    return output


def entity_row(data, kind='cow', *, entity_id=9, uuid=None, position=None, velocity=None, lerp_target=None):
    m = movement(data)
    if position is None:
        position = [m['start_x'] + .5, float(m['start_y']), m['start_z'] + .5]
        cross = 2 if m['start_x'] != m['end_x'] else 0
        position[cross] += 10. if kind in FAR_KINDS else 2.
    position = list(position)
    row = dict(id=entity_id, uuid=uuid or '00000000-0000-4000-8000-' + format(entity_id, '012d'),
        type='minecraft:' + kind, **{'class':'net.minecraft.world.entity.' + CLASSES[kind]}, removed=False,
        position=position, aabb=[position[0]-.3,position[1],position[2]-.3,
                                position[0]+.3,position[1]+1.,position[2]+.3],
        velocity=list(velocity or [0.,0.,0.]), lerp_target=list(lerp_target or position),
        flags=dict(living=kind not in ('boat','chest_minecart','item'),alive=True,dying=False,passenger=False,
            has_passengers=False,leashed=False,no_physics=False,on_fire=False,active_effect_count=0,
            hurt_time=0,mob_target_uuid=None), verdict='outside_context' if kind in FAR_KINDS else 'outside_swept')
    row['projected_aabb'] = project(row)
    return row


def add_row(data, row):
    frame = guard(data); frame['rows'].append(row)
    frame['rows'].sort(key=lambda r:(r['id'],r['uuid'],r['class']))
    frame.update(enumerated_count=len(frame['rows'])+1, removed_count=sum(r['removed'] for r in frame['rows']))
    frame['live_other_count'] = len(frame['rows']) - frame['removed_count']
    return row


def fixture(intent_override=None, scope_override=None, *, dy=0, block=None):
    data = legacy_fixture(intent_override, scope_override, dy=dy, block=block)
    native, scope, aid, intent = data
    if scope_override is not None and scope_override.get('profile') != PROFILE:
        return data
    scope['profile'] = PROFILE
    w = witness(data); w['profile'] = PROFILE
    m = movement(data); m['profile'] = PROFILE
    guard(data).update(policy=POLICY, scope='all-client-loaded-route-swept-and-far-passives', swept_aabb=sweep(m))
    redigest(native, intent)
    return native, scope, aid, intent


def terminal(native, *, landed=True, effect_attempted=True):
    t = legacy_terminal(native, landed=landed)
    w = native['result']['scoped_native_preflight']
    if w['profile'] != PROFILE:
        return t
    t.update(profile=PROFILE, entity_guard_policy=POLICY, effect_attempted=effect_attempted,
             maximum_checked_population=w['facts']['local_segment']['entity_guard']['enumerated_count'])
    if not effect_attempted:
        t.update(local_checks=1,entity_guard_checks=1,sampled_horizontal_distance=0.,jump_pulses=0,
            last_entity_check_tick=w['source_tick'],last_entity_check_nano=str(int(w['admitted_nano'])+1),
            last_entity_check_action_tick=0)
    native['ticks'] = t['last_entity_check_action_tick']
    return t
