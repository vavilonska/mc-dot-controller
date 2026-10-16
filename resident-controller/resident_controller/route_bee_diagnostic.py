"""Closed refusal-only bee facts. Nothing here grants movement or retry authority.

The captured source may be absent, stale or inconsistent. Preserve those facts
as diagnostics instead of treating them as an admission witness or repairing
them. Legacy rejection and authoritative bee schemas are deliberately separate.
"""
import json
import re
from .capability_snapshot import _integer, _number, _require, exact, signed_long_string

MAX_BYTES = 8192
REASONS = frozenset(('observed', 'context_unavailable', 'dimension_changed',
    'inspection_limit', 'row_limit', 'duplicate_entity_uuid', 'native_read_failed',
    'entity_not_observed', 'entity_identity_changed', 'source_expired',
    'source_tick_mismatch', 'invalid_anger_time', 'invalid_rabbit_variant',
    'unrecognized', 'unavailable'))
READ_STATUSES = frozenset(('observed', 'not_exact_bee', 'hive_position_class_untrusted',
    'flower_position_class_untrusted', 'positions_class_untrusted', 'not_recorded', 'row_unavailable'))
UUID = re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}')


def _uuid(value):
    return type(value) is str and UUID.fullmatch(value) is not None


def _registry(value):
    return (type(value) is str and len(value) <= 128
            and re.fullmatch(r'[a-z0-9_.-]+:[a-z0-9_./-]+', value) is not None)


def _array(value, count):
    return type(value) is list and len(value) == count and all(_number(v) for v in value)


def _long(value):
    return _integer(value, -(2**63), 2**63 - 1)


def _nano(value):
    return signed_long_string(value) and value != '-0'


def valid_native_bee_diagnostic(value):
    """Accept exactly the bounded native schema, including explicit unknowns."""
    if (type(value) is not dict or set(value) != {'schema_version', 'entity', 'native', 'route', 'source', 'context'}
            or type(value['schema_version']) is not int or value['schema_version'] != 1):
        return False
    entity, native, route, source, context = (value[k] for k in ('entity', 'native', 'route', 'source', 'context'))
    if (type(entity) is not dict or set(entity) != {'id', 'uuid', 'type', 'position', 'aabb', 'velocity', 'lerp_target'}
            or not _integer(entity['id'], -(2**31), 2**31 - 1) or not _uuid(entity['uuid'])
            or entity['type'] != 'minecraft:bee'):
        return False
    geometry = ('position', 'aabb', 'velocity', 'lerp_target')
    if not (all(entity[k] is None for k in geometry)
            or all(_array(entity[k], 6 if k == 'aabb' else 3) for k in geometry)):
        return False
    # An invalid but finite source box remains an explanatory fact; it cannot
    # become movement authority. Do not silently replace or normalize geometry.
    if (type(native) is not dict or set(native) != {'present', 'known', 'reason', 'coverage_complete', 'inspected',
            'sample_tick', 'sample_nano', 'source_tick', 'source_nano', 'sample_age_ms'}
            or type(native['present']) is not bool
            or any(native[k] is not None and type(native[k]) is not bool for k in ('known', 'coverage_complete'))
            or type(native['reason']) is not str or native['reason'] not in REASONS
            or native['inspected'] is not None and not _integer(native['inspected'], 0, 4097)
            or any(native[k] is not None and not _long(native[k]) for k in ('sample_tick', 'source_tick'))
            or any(native[k] is not None and not _nano(native[k]) for k in ('sample_nano', 'source_nano'))
            or native['sample_age_ms'] is not None and not _number(native['sample_age_ms'])):
        return False
    if (type(route) is not dict or set(route) != {'present', 'captured', 'read_status'}
            or any(type(route[k]) is not bool for k in ('present', 'captured'))
            or type(route['read_status']) is not str or route['read_status'] not in READ_STATUSES):
        return False
    flags = {'context_current', 'batch_present', 'batch_context_matches', 'row_present', 'row_identity_matches'}
    if (type(source) is not dict or set(source) != flags | {'source_radius_blocks'}
            or any(type(source[k]) is not bool for k in flags)
            or type(source['source_radius_blocks']) is not int or source['source_radius_blocks'] != 128):
        return False
    if (type(context) is not dict or set(context) != {'dimension', 'world_generation', 'player_uuid',
            'client_tick', 'frame_nano', 'player_position', 'prism', 'swept_aabb'}
            or not _registry(context['dimension']) or not _uuid(context['world_generation'])
            or not _uuid(context['player_uuid']) or not _long(context['client_tick'])
            or not _nano(context['frame_nano']) or not _array(context['player_position'], 3)
            or not _array(context['prism'], 6) or not _array(context['swept_aabb'], 6)):
        return False
    return len(json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode('utf-8')) <= MAX_BYTES


def matches_request(value, intent):
    """Bind new refusal evidence to this POST's original expected context."""
    if value.get('schema_version') != 2:
        return True
    context = value['native_bee_diagnostic']['context']
    return type(intent) is dict and all(exact(context[k], intent.get('expected_' + k))
                                       for k in ('dimension', 'world_generation', 'player_uuid'))


def validate_terminal(value, witness, native):
    """Bind new diagnostics to the unsuccessful action, never its calm rows."""
    if value.get('schema_version') != 2:
        return
    from .action_safety import native_release_unconfirmed
    uncertain = (native_release_unconfirmed(native) or any(container.get(key) is True
        for container in (native, native.get('result', {}))
        for key in ('requires_handoff', 'unknown_outcome', 'post_uncertain', 'uncertain', 'input_release_unconfirmed')))
    context = value['native_bee_diagnostic']['context']
    movement = witness['facts']['local_segment']
    frame = movement['entity_guard']
    _require(value['profile'] == witness['profile'] and native.get('action') == 'follow_path'
             and (native.get('status') == 'cancelled' and native.get('reason') == value['rejection_code']
                  or native.get('status') == 'failed' and native.get('reason') == 'client_action_error'
                  or native.get('status') in ('cancelled', 'failed') and uncertain)
             and all(exact(context[k], witness['context'][k])
                     for k in ('dimension', 'world_generation', 'player_uuid'))
             and exact(context['prism'], frame['prism']) and exact(context['swept_aabb'], frame['swept_aabb']),
             'route_bee_rejection_binding')
