"""Bounded schema3 construction previews, never a new construction authority.

Only embedded blueprint content is accepted. No approved blueprint registry is
present in this source tree, so paths and reference resolution are unsupported.
The existing executors and progress reconciliation are intentionally not called
until the owner adapter has accepted terrain/move/place admission profiles.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from mdc_skills import building_v3 as skills, construction, scoped_placement
from .inventory import _definition
from .interaction import COORDINATE
from mdc_skills.core import Observation, Survey, Outcome, SkillError
from mdc_toolbox.contracts import ToolboxError, obj, integer, validate_schema, json_data

_PLACE_SCHEMA = obj({'support': COORDINATE, 'face': {'enum': sorted(scoped_placement.reach.FACES)},
    'expected_support_id': {'enum': list(scoped_placement.BLOCKS)}, 'expected_support_properties': obj(),
    'expected_block_id': {'const': scoped_placement.BLOCK}, 'expected_block_properties': obj()},
    ('support','face','expected_support_id','expected_support_properties','expected_block_id','expected_block_properties'))

MAX_CELLS = 512
MAX_REGION_VOLUME = 8192
MAX_MATERIAL_TYPES = 32
MAX_BLUEPRINT_BYTES = 256 * 1024
_SCHEMA_PATH = Path(__file__).resolve().parents[2] / 'schemas' / 'building-v3.schema.json'


def _inline_schema():
    """Reuse the pinned schema, inlining its local definitions for P1's parser."""
    source = json.loads(_SCHEMA_PATH.read_text())

    def expand(value):
        if isinstance(value, list):
            return [expand(child) for child in value]
        if not isinstance(value, dict):
            return value
        if '$ref' in value:
            if set(value) != {'$ref'} or not value['$ref'].startswith('#/$defs/'):
                raise RuntimeError('unsupported_internal_blueprint_schema_reference')
            return expand(source['$defs'][value['$ref'].split('/')[-1]])
        return {key: expand(child) for key, child in value.items() if key != '$defs'}

    schema = expand(source)
    for key in ('cells', 'clearance', 'light_checks', 'access_points'):
        schema['properties'][key]['maxItems'] = MAX_CELLS
    return schema


_BLUEPRINT = _inline_schema()
_BUILD_OPTIONS = {
    'blueprint': _BLUEPRINT,
    'max_placements': integer(1, MAX_CELLS),
    'max_moves': integer(0, 1024),
    'max_steps': integer(1, 64),
    'hotbar_slot': integer(0, 8),
}
_SCHEMAS = {
    'build': obj(_BUILD_OPTIONS, ('blueprint',)),
    'build_with_materials': obj({**_BUILD_OPTIONS,
        'max_actions': integer(1, 32768),
        'timeout_seconds': {'type': 'number', 'minimum': 1, 'maximum': 3600},
        'max_nodes': integer(1, 1024), 'max_blocks': integer(1, 1024),
        'max_batches': integer(1, 1024), 'max_search_steps': integer(0, 512),
        'max_walk_distance': integer(0, 8192)}, ('blueprint',)),
}
_RESULT = obj({
    'status': {'type': 'string', 'enum': ['blocked']},
    'reason': {'const': 'building_scoped_execution_unavailable'},
    'request_ids': {'type': 'array', 'maxItems': 0},
    'evidence': obj({
        'blueprint_identity': deepcopy(_BLUEPRINT['properties']['identity']),
        'effect_certainty': {'const': 'none_proven'},
        'execution_authority': {'const': False},
        'actions_replayed': {'const': 0},
    }, ('blueprint_identity', 'effect_certainty', 'execution_authority', 'actions_replayed')),
    'server_confirmed': {'const': False},
}, ('status', 'reason', 'request_ids', 'evidence', 'server_confirmed'))


def _sources():
    paths = [('capability-runtime/mdc_skills/' + Path(module.__file__).name,
              Path(module.__file__)) for module in (skills, construction)]
    paths.append(('capability-runtime/schemas/building-v3.schema.json', _SCHEMA_PATH))
    return [{'path': name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
            for name, path in paths]


def definitions():
    local = _definition('place_local', _PLACE_SCHEMA, group='building', level='primitive', profile='player',
        description='Place one selected plain cobblestone against an explicit full-cube support face while stationary.',
        source='scoped_placement.py', actions=['place_block'], bounds={'placement_items':1,'native_timeout_ms':2000,
            'maximum_action_ticks':40,'max_mutations':1},
        limits=['Requires request_only and negotiated placement-local-observed-v1; no legacy fallback.',
            'Exact support, face and empty target; selected plain cobblestone only, no hotbar switch or procurement.',
            'No movement, bridge/pillar jump, retries, blueprint automation or whole-building execution.',
            'Exact one-item decrement and protected other inventory plus stable native target-state proof.'])
    local['native_features'] += ['scoped-native-preflight/1','profile:placement-local-observed-v1']
    local['cancel_granularity'] = 'exact_native_action'
    local['source_fingerprints'].append({'path':'capability-runtime/mdc_toolbox/bindings/building.py',
        'sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()})
    return [local] + [{
        'capability': name, 'capability_version': 1, 'group': 'building',
        'level': 'bounded_composite', 'input_schema': deepcopy(schema),
        'result_schema': deepcopy(_RESULT), 'observation_profile': 'local_terrain',
        'native_features': ['capability_guard/1', 'scoped-native-preflight/1',
                            'profile:place-v1', 'profile:move-segment-v1'],
        'bounds': {'blueprint_bytes': MAX_BLUEPRINT_BYTES, 'blockstate_cells': MAX_CELLS,
                   'acceptance_entries_per_kind': MAX_CELLS, 'region_volume': MAX_REGION_VOLUME,
                   'region_horizontal_span': 31, 'region_vertical_span': 15,
                   'material_types': MAX_MATERIAL_TYPES, 'placement_items': MAX_CELLS},
        'prerequisites': ['Exact schema3 content hash and supported blockstate/footprint.',
                          'Fresh complete terrain, support, access and native placement admission.'],
        'cancel_granularity': 'unavailable', 'resume_supported': False,
        'planner_available': True, 'implementation_status': 'preview_implemented',
        'adapter_status': 'legacy_limited',
        'known_limits': [
            'Execution is unavailable; current owner adapter supports state/menu only.',
            'Public preview computes an exact total bill without inventory or existing-world credit.',
            'Terrain/access/placement preview requires a trusted historical survey; caller JSON cannot supply it.',
            'Embedded content only; no blueprint references, arbitrary host paths, writes or auto-resume.',
            'No excavation, replacement, inventory staging or strategic house design.',
            'Existing build, build_with_materials and progress reconciliation remain unchanged and unexposed here.',
        ],
        'source_fingerprints': _sources(),
        'validation': {'offline': 'p6_building_memory_contract_tests',
                       'live': 'not_validated_for_toolbox_v1'},
    } for name, schema in _SCHEMAS.items()]


def _parse(capability, arguments):
    if capability not in _SCHEMAS:
        raise ToolboxError('capability_unavailable', 'No building binding for this capability')
    validate_schema(arguments, _SCHEMAS[capability])
    if len(json_data(arguments['blueprint'])) > MAX_BLUEPRINT_BYTES:
        raise ToolboxError('invalid_request', 'blueprint_byte_budget_exceeded')
    try:
        blueprint = skills.VersionedBlueprint.parse(arguments['blueprint'])
        low, high = blueprint.region.minimum, blueprint.region.maximum
        dimensions = tuple(getattr(high, axis) - getattr(low, axis) + 1 for axis in ('x', 'y', 'z'))
        if (dimensions[0] > 31 or dimensions[1] > 15 or dimensions[2] > 31
                or dimensions[0] * dimensions[1] * dimensions[2] > MAX_REGION_VOLUME):
            raise SkillError('blueprint_region_budget_exceeded')
        for point in blueprint.value['access_points']:
            if not all(getattr(low, axis) - margin <= point[axis] <= getattr(high, axis) + margin
                       for axis, margin in (('x', 4), ('y', 2), ('z', 4))):
                raise SkillError('blueprint_access_point_outside_bounded_region')
        bill = skills.material_requirements(blueprint)
        if len(bill['items']) > MAX_MATERIAL_TYPES or bill['placement_items'] > MAX_CELLS:
            raise SkillError('blueprint_material_budget_exceeded')
    except SkillError as exc:
        raise ToolboxError('invalid_request', exc.reason) from None
    return blueprint, bill


def invoke(capability, runtime, arguments, control):
    """Fail closed even when called outside the central availability allowlist."""
    if capability == 'place_local':
        validate_schema(arguments, _PLACE_SCHEMA)
        control.checkpoint()
        result = scoped_placement.place_local(runtime, **deepcopy(arguments))
        control.emit('capability_result', {'capability':capability,'status':result.status,
                                          'reason':result.reason,'request_ids':list(result.request_ids)})
        return result
    blueprint, _ = _parse(capability, arguments)
    control.checkpoint()
    result = Outcome('blocked', 'building_scoped_execution_unavailable', evidence={
        'blueprint_identity': deepcopy(blueprint.value['identity']),
        'effect_certainty': 'none_proven', 'execution_authority': False, 'actions_replayed': 0})
    control.emit('capability_result', {'capability': capability, 'status': result.status,
                                      'reason': result.reason, 'request_ids': []})
    return result


def plan(capability, arguments, observation=None):
    """Effect-free exact bill, plus the existing planner only for typed history.

    P1 currently supplies no observation. The optional typed path is an internal
    seam, not a caller observation parser and not action-time verification.
    It uses the same execution_plan kernel as existing plan_build; it never
    synthesizes a runtime, refreshes history or calls a mutation/reconciler.
    """
    blueprint, bill = _parse(capability, arguments)
    result = {
        'capability': capability, 'status': 'partial', 'preview_kind': 'schema3_material_bill',
        'executed': False, 'executable': False, 'execution_authority': False,
        'construction_authority': False, 'server_confirmed': False,
        'material_bill': bill, 'region': blueprint.region.json(),
        'materials': [{'item_id': item, 'count': count} for item, count in bill['items'].items()],
        'blockers': ['trusted_terrain_survey_required_for_access_and_placement_preview'],
        'terrain_preview': {'status': 'unavailable', 'reason': 'trusted_terrain_survey_unavailable'},
        'observation_used': False, 'requires_fresh_execution_preflight': True,
        'provenance': {'evidence_kind': 'caller_blueprint_content',
                       'blueprint_identity': deepcopy(blueprint.value['identity']),
                       'content_hash_verified': True, 'world_evidence': False},
        'source_fingerprints': _sources(),
    }
    if bill['placement_items'] > arguments.get('max_placements', MAX_CELLS):
        result['blockers'].append('total_bill_exceeds_placement_budget_without_existing_world_credit')
    if observation is None:
        return result
    if not isinstance(observation, (Observation, Survey)):
        raise ToolboxError('invalid_request', 'trusted_typed_historical_observation_required', stage='plan')
    # Original timestamp/context survive unchanged. No age is fabricated from
    # an unrelated current clock and no historical observation grants authority.
    result['observation_used'] = True
    result['provenance']['historical_observation'] = {
        'request_id': observation.request_id, 'source_tick': observation.tick,
        'context': list(observation.context), 'source_capture_monotonic': observation.captured_at,
        'historical_only': True, 'action_evidence': False, 'age_ms': None,
        'age_status': 'clock_not_compared',
        'coverage': deepcopy((observation.terrain or {}).get('source_pages', [])),
    }
    try:
        terrain = skills.execution_plan(blueprint, observation, historical=True,
            max_steps=arguments.get('max_steps', 64),
            planning_materials=bill['items'] if capability == 'build_with_materials' else None)
        terrain.pop('existing', None)  # Contains Pos keys; public representation stays JSON.
        result['terrain_preview'] = {'status': 'available', **terrain}
        result['blockers'] = [b for b in result['blockers']
                              if b != 'trusted_terrain_survey_required_for_access_and_placement_preview']
        result['status'] = 'available' if not result['blockers'] else 'partial'
    except SkillError as exc:
        result['terrain_preview'] = {'status': 'blocked', 'reason': exc.reason}
        result['blockers'] = [exc.reason]
    json_data(result)
    return result
