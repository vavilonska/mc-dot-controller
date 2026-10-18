"""Closed combat/threat bindings to current guarded skills, not live acceptance.

Only the injected Runtime can write. Core owns checkpoints and charging on every
nested observe/execute; these wrappers neither acquire ownership nor retry.
"""
from copy import deepcopy
import hashlib
from pathlib import Path

from mdc_skills import threats, combat_goals
from mdc_toolbox.contracts import ToolboxError, validate_schema, obj, integer


def number(low, high):
    return {'type': 'number', 'minimum': low, 'maximum': high}


def default(schema, value):
    return {**schema, 'default': value}


UUID = {'type': 'string', 'minLength': 1, 'maxLength': 128, 'pattern': '^[A-Za-z0-9-]+$'}
COORD = obj({'x': integer(-30000000, 30000000), 'y': integer(-2048, 2048),
             'z': integer(-30000000, 30000000)}, ('x', 'y', 'z'))
HEALTH = number(8, 20)
RESULT = obj({
    'status': {'enum': ['succeeded', 'blocked', 'failed', 'cancelled', 'interrupted', 'unknown']},
    'reason': {'type': 'string', 'maxLength': 4096},
    'request_ids': {'type': 'array', 'items': {'type': 'string'}, 'maxItems': 32768},
    'evidence': {'type': 'object'}, 'server_confirmed': {'const': False},
    'observation_ref': {'type': ['object', 'null']}},
    ('status', 'reason', 'request_ids', 'evidence', 'server_confirmed'))


def definition(name, schema, *, group, level, profile, sources, actions=(),
               description, limits=(), bounds=None, experimental=False):
    root = Path(__file__).resolve().parents[2]
    paths = [Path(source.__file__) for source in sources]
    paths.extend((Path(__file__), root / 'mdc_toolbox' / 'tactical_policy.py'))
    return {
        'capability': name, 'capability_version': 1, 'group': group, 'level': level,
        'description': description, 'input_schema': deepcopy(schema), 'result_schema': deepcopy(RESULT),
        'observation_profile': profile, 'native_features': ['capability_guard/1'] + ['action:' + x for x in actions],
        'bounds': deepcopy(bounds or {}),
        'prerequisites': ['private_singleplayer', 'same_guarded_runtime_owner',
                          'fresh_complete_operation_facts', 'known_previous_action_outcome',
                          'original_shared_budget_and_deadline'],
        'cancel_granularity': 'native_exact_action_and_between_verified_steps',
        'resume_supported': False, 'planner_available': False,
        'implementation_status': 'experimental' if experimental else 'implemented',
        'adapter_status': 'legacy_limited',
        'known_limits': [
            'Engage requires combat-local-observed-v1. Explicit defend_once exists only for supported tasks after a known released terminal stop.',
            'Existing guarded legacy skill path only; no scoped entity/terrain/transition admission is implemented here.',
            'Registration and offline fixtures do not imply live readiness; private singleplayer only.',
            'Shared Runtime charges every nested action/observation. No new writer, callbacks, retry or auto-resume.',
            'Semantic effects and ownership/input cleanup remain separate; unknown never means no effect.', *limits],
        'source_fingerprints': [{'path': 'capability-runtime/' + str(path.relative_to(root)),
            'sha256': hashlib.sha256(path.read_bytes()).hexdigest()} for path in dict.fromkeys(paths)],
        'validation': {'offline': 'focused_tests_available', 'live': 'not_run',
                       'scope': 'closed_schema_dispatch_and_local_policy_only'}}


_SCHEMAS = {
    'engage': obj({'target_uuid': UUID, 'timeout_ms': default(integer(50, 30000), 15000),
        'approach': default({'type': 'boolean'}, True), 'shield': default({'type': 'boolean'}, True),
        'min_health': default(number(14, 20), 14)}, ('target_uuid',)),
    'strike': obj({'target_uuid': UUID, 'ranged': default({'type': 'boolean'}, False),
        'min_health': default(HEALTH, 10),
        'timeout_ms': {'oneOf': [integer(50, 10000), integer(18000, 20000)]},
        'expected_dragon_phase': {'enum': [6, 7]},
        'blaze_safety_mode': {'enum': ['fire_resistance', 'shield_window']}}, ('target_uuid',)),
    'defeat': obj({'target_uuid': UUID, 'max_actions': default(integer(1, 64), 8),
        'ranged': default({'type': 'boolean'}, False), 'min_health': default(HEALTH, 10)}, ('target_uuid',)),
    'recover_hazard': obj({'max_waypoints': default(integer(1, 128), 64),
        'timeout_ms': default(integer(50, 30000), 10000)}),
    'retreat': obj({'target_uuid': UUID, 'timeout_ms': default(integer(50, 10000), 5000)}, ('target_uuid',)),
    'discover_mobs': obj({'species': {'enum': sorted(combat_goals.SPECIES)}}),
    'defeat_nearby': obj({'species': {'enum': sorted(combat_goals.SPECIES)},
        'max_targets': default(integer(1, 64), 1), 'max_actions': default(integer(1, 4096), 32),
        'max_search_steps': default(integer(0, 256), 16), 'max_walk_distance': default(integer(0, 4096), 128),
        'timeout_seconds': default(number(1, 3600), 120), 'min_health': default(number(12, 20), 12)}, ('species',)),
    'hunt_resource': obj({'item_id': {'enum': sorted(combat_goals.MOB_DROPS)}, 'count': default(integer(1, 2304), 1),
        'max_targets': default(integer(1, 64), 16), 'max_actions': default(integer(1, 4096), 256),
        'max_search_steps': default(integer(0, 256), 32), 'max_walk_distance': default(integer(0, 4096), 256),
        'timeout_seconds': default(number(1, 3600), 600), 'min_health': default(number(12, 20), 12)}, ('item_id',)),
}
# Omitted timeout keeps the existing species-aware 5s/20s default. Explicit
# shield-window requests must budget a complete existing native cycle.
_SCHEMAS['strike']['allOf'] = [
    {'if': {'required': ['blaze_safety_mode'], 'properties': {'blaze_safety_mode': {'const': 'shield_window'}}},
     'then': {'properties': {'ranged': {'const': True}, 'timeout_ms': integer(18000, 20000)}, 'required': ['ranged']}},
    {'if': {'required': ['expected_dragon_phase']}, 'then': {'properties': {'ranged': {'const': False}}}},
    {'if': {'required': ['timeout_ms'], 'properties': {'timeout_ms': integer(18000, 20000)}},
     'then': {'required': ['ranged'], 'properties': {'ranged': {'const': True}}}},
    {'if': {'required': ['blaze_safety_mode'], 'properties': {'blaze_safety_mode': {'const': 'fire_resistance'}}},
     'then': {'properties': {'timeout_ms': integer(50, 10000)}}},
]

_SPECS = {
    'engage': ('local_controller', 'entities', ('combat_entity',), 'Run existing bounded native combat against one explicit supported hostile.',
        ['Only zombie/husk/zombie-villager/skeleton/stray/bogged; native bounded combat reserve is at least 14.',
         'Higher caller reserve requires fresh native caller-health-reserve support; never silently lowered.']),
    'strike': ('primitive', 'entities', ('attack_entity', 'shoot_entity'), 'One guarded attack with later target health-loss or exact death evidence.',
        ['Missing target alone is not death. Observed health loss is not causal damage attribution.',
         'Species, shell, fuse, shelter, phase/head-ray, LOS, ammunition and collateral guards remain native/skill prerequisites.',
         'Blaze shield window requires the full native cycle; no caller observation or verifier accepted.']),
    'defeat': ('bounded_composite', 'entities', ('attack_entity', 'shoot_entity'), 'Finite independently verified attacks against one explicit target.',
        ['Stops after the first failed or unknown strike; does not collect or infer loot.']),
    'recover_hazard': ('local_controller', 'local_terrain', ('recover_environment',), 'Use existing observed loaded-geometry environmental escape.',
        ['Supports only observed water/fire/lava/powder-snow escape; unknown egress refuses.']),
    'retreat': ('local_controller', 'local_terrain', ('follow_path',), 'Use existing checked short retreat from one explicit threat.',
        ['At most two cells; must increase observed separation on dry supported geometry.']),
    'discover_mobs': ('query', 'local_terrain', (), 'Discover currently loaded supported mobs and explicit risk blockers.',
        ['Read-only discovery does not authorize attack, prove a firing station, or prove global absence.']),
    'defeat_nearby': ('bounded_composite', 'local_terrain', ('follow_path', 'attack_entity', 'shoot_entity', 'select_hotbar', 'click_slot'),
        'Select observed supported targets and execute finite guarded local encounters.',
        ['Existing finite species vocabulary; local station/route planning only, not full-world pursuit.',
         'max_walk_distance bounds submitted planned route lengths, not strict actual physical distance.']),
    'hunt_resource': ('bounded_composite', 'local_terrain', ('follow_path', 'attack_entity', 'shoot_entity', 'select_hotbar', 'click_slot'),
        'Meet an actual inventory total through bounded existing mob/drop mechanics.',
        ['Target death never proves loot. Zero-drop outcomes spend budget; actual stable inventory total proves acquisition.',
         'max_walk_distance bounds submitted planned route lengths, not strict actual physical distance.']),
}


def definitions():
    values = [definition(name, _SCHEMAS[name], group='combat_threats', level=spec[0], profile=spec[1],
        sources=(threats, combat_goals), actions=spec[2], description=spec[3], limits=spec[4],
        bounds={'argument_bounds': 'input_schema', 'shared_budget': 'original_job_ledger'})
        for name, spec in _SPECS.items()]
    engage = next(value for value in values if value['capability'] == 'engage')
    engage['native_features'] += ['scoped-native-preflight/1', 'profile:combat-local-observed-v1']
    engage['adapter_status'] = 'scoped_native'
    engage['combat_coverage'] = {'target_types':sorted(threats.NATIVE_COMBAT_TYPES),'modes':['engage'],
        'dimension_policy':'same_bound_private_singleplayer_dimension_dry_loaded_geometry',
        'campaign_targets_supported':[],'projectile_prediction_supported':False}
    for value in values:
        value['public_support']='negotiated_profile_required' if value['capability']=='engage' else 'legacy_binding_not_enabled'
        if value['capability']!='engage':value['known_limits'].append('Source implementation only; unavailable in the production scoped Runtime allowlist.')
    engage['bounds'].update(native_timeout_ms=30000, native_area_radius=12,
        native_attack_dispatches=16, native_effect_packets=64, callback_budget_ms=50)
    engage['known_limits'] = [line for line in engage['known_limits']
        if not line.startswith('Existing guarded legacy skill path only;')]
    engage['known_limits'] += [
        'Explicit target only: zombie, husk, zombie_villager, skeleton, stray or bogged. Allies are forbidden.',
        'Caller min_health is explicitly 14..20, default 14. No silent weakening of requested reserve.',
        'One native controller action uses the original job ledger; internal effects have native finite limits.',
        'Explicit defend_once is terminal-only and separately opted in. No suspended ordinary task is resumed after combat.',
        'Native checks are same-callback current evidence; future safety and hard real-time scheduling are not guaranteed.']
    return values


_DISPATCH = {name: getattr(threats if hasattr(threats, name) else combat_goals, name) for name in _SCHEMAS}


def invoke(capability, runtime, arguments, control):
    if capability not in _SCHEMAS:
        raise ToolboxError('capability_unavailable', 'Unknown tactical capability')
    validate_schema(arguments, _SCHEMAS[capability])
    control.checkpoint()
    result = _DISPATCH[capability](runtime, **deepcopy(arguments))
    control.emit('tactical_goal_observed' if result.ok else 'tactical_goal_stopped', {
        'capability': capability, 'status': result.status, 'reason': result.reason,
        'request_ids': list(result.request_ids)})
    # Preserve the exact semantic result even if final cleanup later becomes unknown.
    return result
