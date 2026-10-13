"""Exact-key, read-only KnowledgeStore projection with original provenance.

The public read route is mdc_observe(profile='memory'). The path always comes
from the operator-bound Runtime; caller JSON cannot name a file, write memory,
refresh timestamps, instantiate an observation or grant action authority.
"""
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path

from mdc_skills import scheduler
from mdc_skills.core import Outcome, SkillError
from mdc_toolbox.contracts import ToolboxError, obj, integer, validate_schema, json_data

_KEY = {'type': 'string', 'pattern': '^[A-Za-z0-9_-]{1,80}$', 'minLength': 1, 'maxLength': 80}
_TEXT = {'type': 'string', 'minLength': 1, 'maxLength': 256}
_CONTEXT_NAMES = ('world_generation', 'dimension', 'player_uuid', 'action_session')
_CONTEXT = {'type': 'array', 'minItems': 4, 'maxItems': 4, 'items': _TEXT}
_KINDS = ('landmark', 'resource', 'workstation', 'hazard', 'portal', 'build_progress')
_INPUT = obj({'key': _KEY}, ('key',))
_SELECTORS = obj({'query': _KEY}, ('query',))
_BOUNDS = obj({'max_results': integer(1, 1)})
_RECORD = obj({
    'kind': {'type': 'string', 'enum': list(_KINDS)},
    'value': {'type': 'object'}, 'context': _CONTEXT,
    'source_tick': integer(0, 9223372036854775807), 'source_request_id': _TEXT,
    'source_capture_monotonic': {'type': 'number', 'minimum': 0},
    'capture_epoch': _TEXT,
    'historical_only': {'const': True}, 'action_evidence': {'const': False},
    'same_context': {'type': 'boolean'}, 'requires_fresh_observation': {'const': True},
}, ('kind', 'value', 'context', 'source_tick', 'source_request_id',
    'source_capture_monotonic', 'capture_epoch', 'historical_only',
    'action_evidence', 'same_context', 'requires_fresh_observation'))
_RESULT = obj({
    'status': {'type': 'string', 'enum': ['succeeded']}, 'reason': _TEXT,
    'request_ids': {'type': 'array', 'maxItems': 0}, 'evidence': {'type': 'object'},
    'server_confirmed': {'const': False},
}, ('status', 'reason', 'request_ids', 'evidence', 'server_confirmed'))


def _sources():
    path = Path(scheduler.__file__)
    return [{'path': 'capability-runtime/mdc_skills/scheduler.py',
             'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}]


def definitions():
    return [{
        'capability': 'memory_recall', 'capability_version': 1, 'group': 'goals_memory',
        'level': 'query', 'input_schema': deepcopy(_INPUT), 'result_schema': deepcopy(_RESULT),
        'observation_profile': 'memory', 'native_features': [],
        'bounds': {'records_per_read': 1, 'stored_record_capacity': 128,
                   'value_bytes': 8192, 'checkpoint_bytes': 8 * 1024 * 1024},
        'prerequisites': ['Operator-bound existing Runtime journal and KnowledgeStore.'],
        'cancel_granularity': 'read_boundary', 'resume_supported': False,
        'planner_available': False, 'implementation_status': 'implemented',
        'adapter_status': 'adapter_pending',
        'known_limits': [
            'Use mdc_observe(profile=memory, selectors.query=exact_key, bounds.max_results=1).',
            'memory_recall job submission is not in the initial mutation adapter allowlist.',
            'No writes, list-all search, file paths, native observations, lease or action dispatch.',
            'Historical hints preserve exact source/context and require fresh observation before any action.',
            'Cross-context history is labelled; incomparable capture epochs do not receive a fabricated age.',
        ],
        'source_fingerprints': _sources(),
        'validation': {'offline': 'p6_building_memory_contract_tests', 'live': 'not_required_for_local_read'},
    }]


def _context(trusted_context):
    if trusted_context is None:
        return None
    if (type(trusted_context) is not dict
            or any(key not in trusted_context for key in _CONTEXT_NAMES)):
        raise ToolboxError('observation_unavailable', 'memory_trusted_context_invalid', stage='observation')
    context = [trusted_context[key] for key in _CONTEXT_NAMES]
    try:
        validate_schema(context, _CONTEXT)
    except ToolboxError:
        raise ToolboxError('observation_unavailable', 'memory_trusted_context_invalid', stage='observation') from None
    return context


def read(runtime, selectors, bounds, *, trusted_context=None):
    """Read existing local history without a lease, observe(), remember() or write.

    trusted_context is an operator-only gateway-session mapping supplied by P2,
    never a field in selectors. None leaves current-context comparison unknown.
    """
    validate_schema(selectors, _SELECTORS)
    validate_schema(bounds, _BOUNDS)
    if scheduler.ID.fullmatch(selectors['query']) is None:
        raise ToolboxError('invalid_request', 'memory_key_must_be_exact_identifier')
    context = _context(trusted_context)
    key = selectors['query']
    try:
        with runtime._mutex:
            store = scheduler.KnowledgeStore(runtime)
            if len(store._records) > 128:
                raise SkillError('knowledge_capacity_exceeded')
            record = store.recall(key, context=context)
        if record is not None:
            validate_schema(record, _RECORD)
            # Match the existing store's value-size contract, including its
            # original JSON encoding rather than granting larger read values.
            json_data(record['value'])
            if len(json.dumps(record['value'], allow_nan=False)) > 8192:
                raise SkillError('knowledge_value_budget_exceeded')
    except (SkillError, ToolboxError, OSError, ValueError, TypeError, KeyError, AttributeError):
        # Do not expose private host paths or reflect corrupt stored text as an
        # operational instruction. Invalid provenance is never repaired in place.
        raise ToolboxError('observation_unavailable', 'historical_memory_record_unavailable_or_invalid',
                           stage='observation') from None
    result = {
        'profile': 'memory', 'status': 'available', 'key': key, 'found': record is not None,
        'records': [], 'historical': True, 'historical_only': True,
        'execution_authority': False, 'action_evidence': False, 'server_confirmed': False,
        'context_status': 'compared_to_gateway_context' if context is not None else 'current_context_unavailable',
        'coverage': {'status': 'exact_key_only', 'requested_keys': [key], 'max_results': 1},
        'provenance': {'evidence_kind': 'stored_historical_record', 'source_fingerprints': _sources(),
                       'timestamps_preserved': True, 'read_does_not_refresh': True},
    }
    if record is not None:
        age_ms, age_status = None, 'capture_epoch_not_comparable'
        if record['capture_epoch'] == getattr(runtime, '_owner', None):
            now = runtime.clock()
            if type(now) in (int, float) and math.isfinite(now) and now >= record['source_capture_monotonic']:
                age_ms = (now - record['source_capture_monotonic']) * 1000
                age_status = 'same_capture_epoch_monotonic'
        result['records'].append({'key': key, 'record': deepcopy(record),
                                  'age_ms': age_ms, 'age_status': age_status,
                                  'context_comparison_available': context is not None})
    json_data(result)
    return result


def invoke(capability, runtime, arguments, control):
    """Internal bounded query binding; public jobs remain adapter-pending."""
    if capability != 'memory_recall':
        raise ToolboxError('capability_unavailable', 'No memory binding for this capability')
    validate_schema(arguments, _INPUT)
    control.checkpoint()
    result = read(runtime, {'query': arguments['key']}, {'max_results': 1})
    control.emit('memory_read', {'key': arguments['key'], 'found': result['found'],
                               'historical_only': True})
    return Outcome('succeeded', 'historical_memory_read', evidence=result)


def plan(capability, arguments, observation=None):
    if capability != 'memory_recall':
        raise ToolboxError('capability_unavailable', 'No memory binding for this capability')
    validate_schema(arguments, _INPUT)
    return {'capability': capability, 'status': 'unavailable', 'execution_authority': False,
            'reason': 'memory_requires_operator_bound_store_read', 'observation_used': False}
