"""Closed reusable navigation/traversal bindings over the same guarded Runtime."""
from copy import deepcopy
from mdc_skills import mobility as skills, reach, scoped_mobility
from .production import (_object, _integer, _number, _enum, _COORD,
                         _definition, _invoke, _validate)

_HEALTH = _number(8, 20)
_XZ = _object({'x': _integer(-30000000, 30000000), 'z': _integer(-30000000, 30000000)}, ('x', 'z'))
_DIRECTION = {'type': 'object', 'properties': {'x': _integer(-1, 1), 'z': _integer(-1, 1)},
              'required': ['x', 'z'], 'additionalProperties': False,
              'oneOf': [{'const': value} for value in
                       ({'x': 1, 'z': 0}, {'x': -1, 'z': 0}, {'x': 0, 'z': 1}, {'x': 0, 'z': -1})]}
_MATERIAL = _enum(skills.BUILD_BLOCKS)
_LOCAL_SCHEMA = _object({'goal':_COORD,'min_health':_HEALTH}, ('goal',))
_SCHEMAS = {
    'navigate': _object({'goal': _COORD, 'max_steps': _integer(1, 128)}, ('goal',)),
    'navigate_loaded': _object({'goal': _COORD, 'max_segments': _integer(1, 128),
        'max_steps': _integer(1, 64), 'min_health': _HEALTH, 'max_unstuck': _integer(0, 4)}, ('goal',)),
    'boat_mount': _object({'vehicle_uuid': {'type': 'string', 'minLength': 1, 'maxLength': 128,
        'pattern': '^[A-Za-z0-9-]+$'}, 'min_health': _HEALTH}, ('vehicle_uuid',)),
    'boat_dismount': _object({'min_health': _HEALTH}),
    'boat_travel': _object({'goal': _XZ, 'water_surface_y': _integer(-2048, 2048),
        'max_segments': _integer(1, 128), 'min_health': _HEALTH}, ('goal', 'water_surface_y')),
    'pillar_up': _object({'block_id': _MATERIAL, 'hotbar_slot': _integer(0, 8), 'min_health': _HEALTH}),
    'pillar_down': _object({'expected_block_id': _MATERIAL, 'hotbar_slot': _integer(0, 8),
        'min_health': _HEALTH}, ('expected_block_id',)),
    'bridge_step': _object({'direction': _DIRECTION, 'block_id': _MATERIAL,
        'hotbar_slot': _integer(0, 8), 'min_health': _HEALTH}, ('direction',)),
    'gateway_pearl': _object({'target': _COORD, 'hotbar_slot': _integer(0, 8),
        'min_health': _number(12, 20)}, ('target',)),
}
_DISPATCH = {'navigate': reach.navigate, **{name: getattr(skills, name) for name in _SCHEMAS if name != 'navigate'}}


def definitions():
    result = [_definition(name, 'mobility', 'local_controller' if name in ('navigate_loaded', 'boat_travel') else 'primitive',
        schema, (skills, reach), prerequisites=(
            'Fresh complete loaded route geometry and original runtime owner/context.',
            'Known terminal/released preceding action; failed or unknown movement is never replayed.'),
        limits=('Dry cardinal one-block elevation and supported top surfaces only; no universal traversal.',
            'Boat travel requires observed ordinary sole-driver source-water corridors.',
            'Optional max_unstuck enables finite alternate-frontier plans only after known settled movement and a later fresh tick.',
            'Planned route steps are reported separately from actual physical displacement.',
            'No automatic resume after pause, cancellation, process restart or uncertainty.'),
        features=('action:' + {'navigate': 'follow_path', 'navigate_loaded': 'follow_path',
            'boat_mount': 'boat_mount', 'boat_dismount': 'boat_dismount', 'boat_travel': 'boat_drive',
            'pillar_up': 'place_block', 'pillar_down': 'break_block', 'bridge_step': 'place_block',
            'gateway_pearl': 'gateway_pearl'}[name],),
        bounds={'segments': 128, 'route_steps': 128 if name == 'navigate' else 64,
                'unstuck_alternatives': 4, 'local_expansions': 2048})
        for name, schema in _SCHEMAS.items()]
    local = _definition('navigate_local','mobility','local_controller',_LOCAL_SCHEMA,(scoped_mobility,),
        prerequisites=('Negotiated movement-flat-observed-v2 native admission and original owner/context.',
            'Closed inventory in private Overworld survival, centered stationary origin.'),
        limits=('Exactly one cardinal flat block; no obstacle bypass, jump, sprint or unstuck.',
            'Full expanded 150-cell corridor requires dry literal air and supported ordinary full-cube floors.',
            'Complete loaded-entity observations exclude current corridor, interpolation and projected-motion risks; unsupported entities and projectiles refuse globally.',
            'Supported distant ordinary entities may pass; same-callback facts do not certify future impulses, acceleration or teleports.',
            'Neutral input release is distinct from stopped velocity; later stable goal/motion observations required.',
            'No replay or resume; no generic physical-distance budget metric.'),
        features=('scoped-native-preflight/1','profile:movement-flat-observed-v2','action:follow_path'),
        bounds={'route_steps':1,'footprint_cells':150,'native_timeout_ms':8000,
                'maximum_action_ticks':160,'entity_limit':1024,'max_horizontal_speed':.30})
    local.update(adapter_status='implemented',observation_profile='player',cancel_granularity='exact_native_action',
                 known_limits=list(local['known_limits'][:-1]))
    result.append(local)
    return result


def invoke(capability, runtime, arguments, control):
    if capability == 'navigate_local':
        return _invoke(capability,runtime,arguments,control,{'navigate_local':_LOCAL_SCHEMA},
                       {'navigate_local':scoped_mobility.navigate_local},skill_kwargs={'control':control})
    private = {'control': control} if capability == 'navigate_loaded' else {}
    return _invoke(capability, runtime, arguments, control, _SCHEMAS, _DISPATCH, skill_kwargs=private)


def plan(capability, arguments, observation=None):
    _validate(capability, arguments, {**_SCHEMAS,'navigate_local':_LOCAL_SCHEMA})
    return {'capability': capability, 'status': 'unavailable', 'execution_authority': False,
            'reason': 'route_selection_requires_fresh_runtime_local_facts',
            'bounds': deepcopy({key: value for key, value in arguments.items() if key.startswith('max_')}),
            'observation_used': False}
