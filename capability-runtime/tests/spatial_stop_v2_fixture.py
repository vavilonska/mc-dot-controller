"""Synthetic v2 calm-bee route evidence; not native or game-physics evidence."""
from copy import deepcopy
from local_segment_fixture import fixture as legacy_fixture, terminal as legacy_terminal
from spatial_stop_fixture import (entity_row as v1_entity_row, terminal as v1_terminal,
    add_row, witness, movement, guard, project, sweep, SWEPT_KINDS, FAR_KINDS, CLASSES as V1_CLASSES)
from mining_collect.collect.collect_fixture import redigest

PROFILE = 'movement-local-segment-spatial-stop-v2'
POLICY = 'route-spatial-stop-v2'
CLASSES = {**V1_CLASSES, 'bee': 'animal.Bee'}


def fixture(intent_override=None, scope_override=None, *, dy=0, block=None):
    data = legacy_fixture(intent_override, scope_override, dy=dy, block=block)
    native, scope, aid, intent = data
    if scope_override is not None and scope_override.get('profile') != PROFILE:
        return data
    scope['profile'] = PROFILE
    w = witness(data); w['profile'] = PROFILE
    m = movement(data); m['profile'] = PROFILE
    guard(data).update(schema_version=2, policy=POLICY,
        scope='all-client-loaded-route-swept-and-far-passives-and-calm-bees', swept_aabb=sweep(m))
    redigest(native, intent)
    return data


def entity_row(data, kind='bee', *, entity_id=9, uuid=None, position=None, velocity=None, lerp_target=None):
    row = v1_entity_row(data, 'bat' if kind == 'bee' else kind, entity_id=entity_id, uuid=uuid,
                       position=position, velocity=velocity, lerp_target=lerp_target)
    if kind != 'bee':
        return row
    row.update(type='minecraft:bee', **{'class': 'net.minecraft.world.entity.animal.Bee'})
    w, frame = witness(data), guard(data)
    sample = int(frame['source_nano']) + 1
    source = sample - 100000000
    row['native_living'] = dict(schema_version=1, entity_uuid=row['uuid'], entity_id=row['id'],
        entity_type=row['type'], **{k:w['context'][k] for k in ('dimension', 'world_generation', 'player_uuid')},
        known=True, source='integrated_server_tick', reason='observed', current_target_known=True,
        coverage_complete=True, inspected=2, sample_tick=frame['source_tick'], sample_nano=str(sample),
        source_tick=frame['source_tick']-1, source_nano=str(source), sample_age_ms=100., alive=True,
        aggressive=False, current_target=None,
        bee=dict(angry=False, remaining_anger_ticks=0, persistent_anger_target_uuid=None),
        bee_route=dict(schema_version=1, server_class='net.minecraft.world.entity.animal.Bee',
                       has_stung=False, has_nectar=False, hive_pos=None, flower_pos=None))
    return row


def terminal(native, *, landed=True, effect_attempted=True):
    w = witness(native)
    if w['profile'] != PROFILE:
        return v1_terminal(native, landed=landed, effect_attempted=effect_attempted)
    t = legacy_terminal(native, landed=landed)
    t.update(profile=PROFILE, entity_guard_policy=POLICY, effect_attempted=effect_attempted,
             maximum_checked_population=guard(native)['enumerated_count'])
    if not effect_attempted:
        t.update(local_checks=1, entity_guard_checks=1, sampled_horizontal_distance=0., jump_pulses=0,
                 last_entity_check_tick=w['source_tick'], last_entity_check_nano=str(int(w['admitted_nano'])+1),
                 last_entity_check_action_tick=0)
    native['ticks'] = t['last_entity_check_action_tick']
    return t
