"""Synthetic spatial route evidence only. Not native physics or live safety evidence."""
from copy import deepcopy
from local_segment_fixture import fixture as legacy_fixture, terminal as legacy_terminal
from mining_collect.collect.collect_fixture import redigest

PROFILE = 'movement-local-segment-spatial-threat-v1'
POLICY = 'route-spatial-threat-v1'
TARGET = '44444444-4444-4444-8444-444444444444'


def sweep(m):
    return [min(m['start_x'], m['end_x']) + .5 - .400002, min(m['start_y'], m['end_y']) - .000001,
            min(m['start_z'], m['end_z']) + .5 - .400002, max(m['start_x'], m['end_x']) + .5 + .400002,
            m['start_y'] + (1.26 if m['step_dy'] > 0 else 0) + 1.800002,
            max(m['start_z'], m['end_z']) + .5 + .400002]


def project(row, horizon):
    output = [0.] * 6
    for i in range(3):
        l = row['lerp_target'][i] - row['position'][i]
        v = horizon * row['velocity'][i]
        output[i] = min(row['aabb'][i], row['aabb'][i] + l, row['aabb'][i] + v, (row['aabb'][i] + l) + v)
        output[i + 3] = max(row['aabb'][i + 3], row['aabb'][i + 3] + l, row['aabb'][i + 3] + v, (row['aabb'][i + 3] + l) + v)
    return output


def zombie_row(w, frame, *, active=False, uuid=None, entity_id=9, overlap=False, offset=2.):
    m = w['facts']['local_segment']
    position = list(frame['player_position'])
    cross = 2 if m['start_x'] != m['end_x'] else 0
    position[cross] += offset
    box = [position[0] - .3, position[1], position[2] - .3,
           position[0] + .3, position[1] + 1.95, position[2] + .3]
    velocity = [0., 0., 0.]
    if overlap: velocity[cross] = -.02
    c = w['context']
    living = dict(schema_version=1, entity_uuid=uuid or frame['selected_target_uuid'], entity_id=entity_id,
        entity_type='minecraft:zombie', dimension=c['dimension'], world_generation=c['world_generation'],
        player_uuid=c['player_uuid'], known=True, source='integrated_server_tick', reason='observed',
        current_target_known=True, coverage_complete=True, inspected=1, sample_tick=frame['source_tick'],
        sample_nano=frame['source_nano'], source_tick=frame['source_tick'], source_nano=frame['source_nano'],
        sample_age_ms=0., alive=True, aggressive=active,
        current_target={'uuid':c['player_uuid'], 'entity_id':1, 'type':'minecraft:player'} if active else None)
    row = dict(id=entity_id, uuid=living['entity_uuid'], type='minecraft:zombie',
        **{'class':'net.minecraft.world.entity.monster.Zombie'}, removed=False, position=position, aabb=box,
        velocity=velocity, lerp_target=list(position), flags=dict(living=True, alive=True, dying=False,
        passenger=False, has_passengers=False, leashed=False, no_physics=False, on_fire=False,
        active_effect_count=0, hurt_time=0, mob_target_uuid=None), native_living=living,
        verdict='selected_attacker' if active and living['entity_uuid'] == frame['selected_target_uuid'] else 'outside')
    row['projected_aabb'] = project(row, frame['remaining_projection_ticks'])
    if row['verdict'] == 'selected_attacker':
        row['projected_overlap'] = not any(row['projected_aabb'][i + 3] < frame['swept_aabb'][i]
            or row['projected_aabb'][i] > frame['swept_aabb'][i + 3] for i in range(3))
    return row


def fixture(intent_override=None, scope_override=None, *, dy=0, block=None, stop_only=False, projected_overlap=False):
    data = legacy_fixture(intent_override, scope_override, dy=dy, block=block)
    native, scope, aid, intent = data
    if scope_override is not None and scope_override.get('profile') != PROFILE:
        return data
    scope['profile'] = PROFILE
    intent.setdefault('route_threat_guard', {'schema_version':1, 'target_uuid':TARGET})
    w = native['result']['scoped_native_preflight']; w['profile'] = PROFILE
    if intent_override is None:
        player = '00000000-0000-4000-8000-000000000001'
        intent['expected_player_uuid'] = player
        w['context']['player_uuid'] = player
        w['facts']['context']['player_uuid'] = player
    m = w['facts']['local_segment']; m['profile'] = PROFILE
    frame = m['entity_guard']
    frame.update(policy=POLICY, scope='all-client-loaded-route-swept-body-and-threats',
        swept_aabb=sweep(m), player_position=[w['facts'][k] for k in ('x', 'y', 'z')],
        selected_target_uuid=intent['route_threat_guard']['target_uuid'], stop_only=stop_only)
    if stop_only:
        frame['rows'] = [zombie_row(w, frame, active=True, overlap=projected_overlap)]
        frame.update(enumerated_count=2, live_other_count=1, removed_count=0)
        native.update(status='cancelled', reason='capability_threat_observed', ticks=0)
        native['result'].update(input_release_confirmed=True,
            local_segment=terminal(native, landed=False, effect_attempted=False))
        native['result']['route_threat_stop'] = threat_stop(native)
    redigest(native, intent)
    return native, scope, aid, intent


def terminal(native, *, landed=True, effect_attempted=True):
    t = legacy_terminal(native, landed=landed)
    w = native['result']['scoped_native_preflight']
    if w['profile'] != PROFILE:
        return t
    t.update(profile=PROFILE, entity_guard_policy=POLICY, effect_attempted=effect_attempted, maximum_checked_population=2)
    if not effect_attempted:
        frame = w['facts']['local_segment']['entity_guard']
        t.update(local_checks=1, entity_guard_checks=1, sampled_horizontal_distance=0., jump_pulses=0,
            last_entity_check_tick=frame['source_tick'], last_entity_check_nano=str(int(w['admitted_nano'])+1),
            last_entity_check_action_tick=0, maximum_checked_population=frame['enumerated_count'])
    native['ticks'] = t['last_entity_check_action_tick']
    return t


def threat_stop(native):
    w = native['result']['scoped_native_preflight']; m = w['facts']['local_segment']
    t = native['result']['local_segment']; frame = deepcopy(m['entity_guard'])
    preempted = not t['effect_attempted']
    frame.update(source_tick=t['last_entity_check_tick'], source_nano=t['last_entity_check_nano'],
        remaining_projection_ticks=160 - t['last_entity_check_action_tick'], stop_only=True)
    if preempted:
        for row in frame['rows']:
            if 'native_living' in row:
                living = row['native_living']
                living.update(sample_tick=frame['source_tick'],sample_nano=frame['source_nano'],
                    sample_age_ms=(int(frame['source_nano'])-int(living['source_nano']))/1000000.)
    if not preempted:
        frame['rows'] = [zombie_row(w, frame, active=True)]
        frame.update(enumerated_count=2, live_other_count=1, removed_count=0)
    selected = next(row for row in frame['rows'] if row.get('verdict') == 'selected_attacker')
    return dict(schema_version=1, profile=PROFILE, policy=POLICY, target_uuid=selected['uuid'],
        entity_id=selected['id'], entity_type=selected['type'], player_uuid=w['context']['player_uuid'],
        world_generation=w['context']['world_generation'], dimension=w['context']['dimension'],
        before_next_effect=True, action_tick=t['last_entity_check_action_tick'], entity_guard=frame,
        preempted_before_motion=preempted)
