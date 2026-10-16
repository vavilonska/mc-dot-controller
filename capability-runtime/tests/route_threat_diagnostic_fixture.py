"""Synthetic refusal diagnostics; no native execution or gameplay claim."""
from resident_controller.route_threat_diagnostic import PROFILE, POLICY

WORLD = '11111111-2222-4333-8444-555555555555'
PLAYER = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
TARGET = '44444444-4444-4444-8444-444444444444'


def diagnostic_fixture():
    return dict(schema_version=1, profile=PROFILE, policy=POLICY,
        rejection_code='route_spatial_native_target_unconfirmed', phase='capture',
        entity=dict(id=9, uuid=TARGET, type='minecraft:zombie', selected=True),
        context=dict(dimension='minecraft:overworld', world_generation=WORLD, player_uuid=PLAYER,
                     selected_target_uuid=TARGET, frame_tick=200, frame_nano='1000000000', final_check_nano=None),
        native=dict(present=True, known=False, reason='entity_not_observed', coverage_complete=True,
                    inspected=1, sample_tick=None, sample_nano=None, source_tick=None, source_nano=None,
                    sample_age_ms=None, alive=None, current_target_known=None),
        source=dict(batch_present=True, batch_context_matches=True, row_present=False,
                    row_identity_matches=False, batch_complete=True, batch_reason='observed',
                    row_tick=None, row_nano=None))


def request_fixture(value):
    c = value['context']
    return {'preflight':{'profile':PROFILE}, 'intent':{
        'action':'follow_path', 'route_threat_guard':{'schema_version':1, 'target_uuid':c['selected_target_uuid']},
        **{'expected_' + k:c[k] for k in ('dimension', 'world_generation', 'player_uuid')}}}
