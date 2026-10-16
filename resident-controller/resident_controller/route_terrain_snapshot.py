"""Bounded native terrain-refusal diagnostics; never terrain-equivalence authority.

The original admitted cells remain immutable. Current fields explain one native
refusal and cannot authorize another segment, retry, defense, or resumption.
"""
import re
from .capability_snapshot import _require, _integer, _number, exact
from .route_spatial_stop_snapshot import PROFILE, PROFILES

POLICY = 'local-segment-terrain-equivalence-v1'
REJECTION_CODES = frozenset((
    'local_segment_unknown_corridor_cell',
    'local_segment_fluid_present',
    'local_segment_floor_unsupported',
    'local_segment_special_friction',
    'local_segment_clearance_or_hazard_changed',
    'local_segment_footprint_changed',
    'local_segment_corridor_unloaded_after_hooks',
    'local_segment_corridor_changed_after_hooks',
))
CHANGED_FIELDS = ('loaded', 'id', 'state', 'fluid_empty', 'full_cube', 'collision_empty', 'friction')
CELL_KEYS = {'x', 'y', 'z', 'id', 'state', 'fluid', 'role', 'full_cube', 'friction'}
CURRENT_KEYS = {'loaded', 'id', 'state', 'role', 'fluid_empty', 'full_cube', 'collision_empty', 'friction'}


def bounded_text(value, limit):
    return type(value) is str and 0 < len(value) <= limit


def registry_key(value):
    return bounded_text(value, 128) and re.fullmatch(r'[a-z0-9_.-]+:[a-z0-9_./-]+', value) is not None


def validate_diagnostic(value, witness, native):
    """Validate only a diagnostic attached to the original unsuccessful action."""
    keys = {'schema_version', 'profile', 'policy', 'phase', 'rejection_code',
            'cell', 'original', 'current', 'changed_fields'}
    _require(type(value) is dict and set(value) == keys, 'route_terrain_rejection_schema')
    from .action_safety import native_release_unconfirmed
    uncertain = (native_release_unconfirmed(native) or any(container.get(key) is True
        for container in (native, native.get('result', {}))
        for key in ('requires_handoff', 'unknown_outcome', 'post_uncertain', 'uncertain', 'input_release_unconfirmed')))
    _require(type(value['schema_version']) is int and value['schema_version'] == 1
             and type(value['profile']) is str and value['profile'] in PROFILES
             and witness.get('profile') == value['profile']
             and value['policy'] == POLICY
             and type(value['phase']) is str and value['phase'] in ('capture', 'equivalence', 'raw_fence')
             and type(value['rejection_code']) is str and value['rejection_code'] in REJECTION_CODES
             and native.get('action') == 'follow_path'
             and (native.get('status') == 'cancelled' and native.get('reason') == value['rejection_code']
                  or native.get('status') == 'failed' and native.get('reason') == 'client_action_error'
                  or native.get('status') in ('cancelled', 'failed') and uncertain),
             'route_terrain_rejection_binding')
    cell, original, current = value['cell'], value['original'], value['current']
    _require(type(cell) is dict and set(cell) == {'x', 'y', 'z'}
             and all(_integer(cell[k], -(2**31), 2**31 - 1) for k in cell), 'route_terrain_rejection_cell')
    _require(type(original) is dict and set(original) == CELL_KEYS
             and all(exact(original[k], cell[k]) for k in cell)
             and registry_key(original['id']) and bounded_text(original['state'], 512)
             and original['fluid'] == 'minecraft:empty'
             and type(original['role']) is str and original['role'] in ('support', 'clear', 'context')
             and type(original['full_cube']) is bool and _number(original['friction']),
             'route_terrain_rejection_original')
    movement = witness.get('facts', {}).get('local_segment')
    _require(type(movement) is dict and movement.get('profile') == value['profile']
             and type(movement.get('cells')) is list, 'route_terrain_rejection_movement')
    matching = [row for row in movement['cells'] if type(row) is dict
                and all(exact(row.get(k), cell[k]) for k in cell)]
    _require(len(matching) == 1 and exact(original, matching[0]), 'route_terrain_rejection_original_witness')
    _require(type(current) is dict and set(current) == CURRENT_KEYS
             and type(current['loaded']) is bool and current['role'] == original['role']
             and (current['id'] is None or registry_key(current['id']))
             and (current['state'] is None or bounded_text(current['state'], 512))
             and all(current[k] is None or type(current[k]) is bool
                     for k in ('fluid_empty', 'full_cube', 'collision_empty'))
             and (current['friction'] is None or _number(current['friction'])),
             'route_terrain_rejection_current')
    # The original admission validator already proves loaded empty-fluid cells,
    # with either full-cube geometry or collision-empty air. Do not infer any
    # unavailable current fact and do not decide equivalence from these fields.
    baseline = {'loaded': True, 'id': original['id'], 'state': original['state'],
                'fluid_empty': original['fluid'] == 'minecraft:empty',
                'full_cube': original['full_cube'], 'collision_empty': not original['full_cube'],
                'friction': original['friction']}
    changed = [key for key in CHANGED_FIELDS if current[key] is not None and current[key] != baseline[key]]
    _require(type(value['changed_fields']) is list and value['changed_fields'] == changed,
             'route_terrain_rejection_changed_fields')
    return value
