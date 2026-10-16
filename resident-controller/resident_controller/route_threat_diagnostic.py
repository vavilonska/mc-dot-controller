"""Bounded refusal-only native route-threat facts; never action/retry authority.

Missing, stale, or inconsistent native clocks remain explanatory facts. These
diagnostics cannot replace a spatial witness, stop proof, or input release.
"""
import json
import re

from .capability_snapshot import _integer, _number, exact, signed_long_string
from .spatial_threat_snapshot import PROFILE, POLICY, valid_uuid

MAX_BYTES = 4096
REJECTION_CODES = frozenset(('route_spatial_native_target_unconfirmed',
    'route_spatial_native_target_stale', 'route_spatial_clock_invalid',
    'route_spatial_targetless_aggression_unknown', 'route_spatial_target_unknown',
    'route_spatial_other_target_unknown'))
PHASES = frozenset(('capture', 'recheck', 'final_fence'))
REASONS = frozenset(('observed', 'context_unavailable', 'dimension_changed',
    'inspection_limit', 'row_limit', 'duplicate_entity_uuid', 'native_read_failed',
    'entity_not_observed', 'entity_identity_changed', 'source_expired',
    'source_tick_mismatch', 'invalid_anger_time', 'invalid_rabbit_variant',
    'unavailable', 'unrecognized'))


def _long(value):
    return _integer(value, -(2**63), 2**63 - 1)


def _nano(value):
    return signed_long_string(value) and value != '-0'


def _reason(value):
    return type(value) is str and value in REASONS


def valid_rejection_diagnostic(value):
    """Accept only the complete closed native diagnostic, without repairing it."""
    if (type(value) is not dict or set(value) != {'schema_version', 'profile', 'policy',
            'rejection_code', 'phase', 'entity', 'context', 'native', 'source'}
            or type(value['schema_version']) is not int or value['schema_version'] != 1
            or value['profile'] != PROFILE or value['policy'] != POLICY
            or type(value['rejection_code']) is not str or value['rejection_code'] not in REJECTION_CODES
            or type(value['phase']) is not str or value['phase'] not in PHASES):
        return False
    entity, context, native, source = (value[k] for k in ('entity', 'context', 'native', 'source'))
    if (type(context) is not dict or set(context) != {'dimension', 'world_generation',
            'player_uuid', 'selected_target_uuid', 'frame_tick', 'frame_nano', 'final_check_nano'}
            or type(context['dimension']) is not str or len(context['dimension']) > 128
            or re.fullmatch(r'[a-z0-9_.-]+:[a-z0-9_./-]+', context['dimension']) is None
            or any(not valid_uuid(context[k]) for k in ('world_generation', 'player_uuid', 'selected_target_uuid'))
            or not _integer(context['frame_tick'], 0, 2**63 - 1) or not _nano(context['frame_nano'])
            or (context['final_check_nano'] is not None) != (value['phase'] == 'final_fence')
            or context['final_check_nano'] is not None and not _nano(context['final_check_nano'])):
        return False
    if (type(entity) is not dict or set(entity) != {'id', 'uuid', 'type', 'selected'}
            or not _integer(entity['id'], -(2**31), 2**31 - 1) or not valid_uuid(entity['uuid'])
            or entity['type'] != 'minecraft:zombie' or type(entity['selected']) is not bool
            or entity['selected'] != (entity['uuid'] == context['selected_target_uuid'])):
        return False
    if (type(native) is not dict or set(native) != {'present', 'known', 'reason', 'coverage_complete',
            'inspected', 'sample_tick', 'sample_nano', 'source_tick', 'source_nano', 'sample_age_ms',
            'alive', 'current_target_known'}
            or type(native['present']) is not bool or not _reason(native['reason'])
            or any(native[k] is not None and type(native[k]) is not bool
                   for k in ('known', 'coverage_complete', 'alive', 'current_target_known'))
            or native['inspected'] is not None and not _integer(native['inspected'], 0, 4097)
            or any(native[k] is not None and not _long(native[k]) for k in ('sample_tick', 'source_tick'))
            or any(native[k] is not None and not _nano(native[k]) for k in ('sample_nano', 'source_nano'))
            or native['sample_age_ms'] is not None and not _number(native['sample_age_ms'])):
        return False
    if not native['present'] and (native['reason'] != 'unavailable'
            or any(native[k] is not None for k in native if k not in ('present', 'reason'))):
        return False
    if (type(source) is not dict or set(source) != {'batch_present', 'batch_context_matches', 'row_present',
            'row_identity_matches', 'batch_complete', 'batch_reason', 'row_tick', 'row_nano'}
            or any(type(source[k]) is not bool for k in ('batch_present', 'batch_context_matches',
                                                        'row_present', 'row_identity_matches'))
            or source['batch_complete'] is not None and type(source['batch_complete']) is not bool
            or not _reason(source['batch_reason'])
            or source['row_present'] and not source['batch_present']
            or source['row_identity_matches'] and not source['row_present']
            or any((source[k] is not None) != source['row_present'] for k in ('row_tick', 'row_nano'))
            or source['row_tick'] is not None and not _long(source['row_tick'])
            or source['row_nano'] is not None and not _nano(source['row_nano'])):
        return False
    if not source['batch_present'] and (source['batch_context_matches']
            or source['batch_complete'] is not None or source['batch_reason'] != 'unavailable'):
        return False
    return len(json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode('utf-8')) <= MAX_BYTES


def matches_request(value, intent):
    """Bind a validated refusal to the original POST, never a later observation."""
    context = value['context']
    guard = intent.get('route_threat_guard') if type(intent) is dict else None
    return (type(intent) is dict and intent.get('action') == 'follow_path'
            and type(guard) is dict and set(guard) == {'schema_version', 'target_uuid'}
            and type(guard['schema_version']) is int and guard['schema_version'] == 1
            and exact(guard['target_uuid'], context['selected_target_uuid'])
            and all(exact(context[k], intent.get('expected_' + k))
                    for k in ('dimension', 'world_generation', 'player_uuid')))
