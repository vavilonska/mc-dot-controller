"""Synthetic refusal-only facts; never native execution or ordinary-world proof."""
from copy import deepcopy
from spatial_stop_v2_fixture import fixture, entity_row, witness, guard, PROFILE, POLICY
from mining_collect.collect.collect_fixture import redigest

WORLD = '11111111-1111-4111-8111-111111111111'
PLAYER = '22222222-2222-4222-8222-222222222222'


def canonical_fixture():
    data = fixture()
    w = witness(data)
    for key, value in (('world_generation', WORLD), ('player_uuid', PLAYER)):
        data[3]['expected_' + key] = value
        w['context'][key] = value
        w['facts']['context'][key] = value
    redigest(data[0], data[3])
    return data


def diagnostic_fixture(data=None, *, reason='entity_not_observed', rejection_code='route_bee_native_unconfirmed'):
    data = canonical_fixture() if data is None else data
    w, frame = witness(data), guard(data)
    row = entity_row(data, position=[40., 64., 40.])
    detail = dict(schema_version=1,
        entity={k:deepcopy(row[k]) for k in ('id', 'uuid', 'type', 'position', 'aabb', 'velocity', 'lerp_target')},
        native=dict(present=True, known=False, reason=reason, coverage_complete=True, inspected=7,
                    sample_tick=None, sample_nano=None, source_tick=None, source_nano=None, sample_age_ms=None),
        route=dict(present=False, captured=False, read_status='row_unavailable'),
        source=dict(context_current=True, batch_present=True, batch_context_matches=True,
                    row_present=False, row_identity_matches=False, source_radius_blocks=128),
        context={**{k:w['context'][k] for k in ('dimension', 'world_generation', 'player_uuid')},
                 'client_tick':frame['source_tick'], 'frame_nano':frame['source_nano'],
                 'player_position':[w['facts'][k] for k in ('x', 'y', 'z')],
                 'prism':deepcopy(frame['prism']), 'swept_aabb':deepcopy(frame['swept_aabb'])})
    return dict(schema_version=2, profile=PROFILE, policy=POLICY, phase='policy', entity_type='minecraft:bee',
                exception_type='rejected', rejection_code=rejection_code, native_bee_diagnostic=detail)


def request_fixture(diagnostic):
    """Synthetic matching request context for an isolated transport boundary test."""
    context = diagnostic['native_bee_diagnostic']['context']
    return {'preflight':{'profile':PROFILE}, 'intent':{
        'expected_' + k:context[k] for k in ('dimension', 'world_generation', 'player_uuid')}}
