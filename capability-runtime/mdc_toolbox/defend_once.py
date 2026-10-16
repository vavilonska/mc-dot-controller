"""Explicit one-target, terminal-only defense within the original Runtime job."""
import math
from mdc_skills.core import Runtime, require
from mdc_skills import threats
from mdc_skills.danger_policy import _nano
from .terminal_defense import TerminalDefensiveSupervisor
from .control import ControlStop

SUPPORTED_TASKS = frozenset({'navigate_local', 'navigate_step_down', 'mine_local', 'collect_local', 'navigate_route_local'})


def attacking_player(observation, row):
    """Require fresh integrated-server target facts tied to this exact observation."""
    facts = row.get('native_living', {})
    require(isinstance(facts, dict), 'defense_attacker_facts_missing')
    require(type(facts.get('schema_version')) is int and facts['schema_version'] == 1
        and facts.get('known') is True and facts.get('coverage_complete') is True
        and facts.get('source') == 'integrated_server_tick' and facts.get('reason') == 'observed'
        and facts.get('alive') is True and facts.get('current_target_known') is True
        and type(facts.get('entity_id')) is int
        and type(facts.get('inspected')) is int and 1 <= facts['inspected'] <= 4096,
        'defense_attacker_facts_unconfirmed')
    require(all(facts.get(k) == v for k, v in (
        ('entity_uuid', row.get('uuid')), ('entity_id', row.get('entity_id')),
        ('entity_type', row.get('type')), ('world_generation', observation.context[0]),
        ('dimension', observation.context[1]), ('player_uuid', observation.context[2]))),
        'defense_attacker_identity_changed')
    target = facts.get('current_target')
    require(isinstance(target, dict) and target.get('uuid') == observation.context[2]
        and target.get('type') == 'minecraft:player', 'defense_target_not_attacking_player')
    age = facts.get('sample_age_ms')
    guard = observation.state.get('capability_guard', {})
    require(type(facts.get('sample_tick')) is int and facts['sample_tick'] == observation.tick
        and type(facts.get('source_tick')) is int and facts['source_tick'] >= 0
        and abs(observation.tick - facts['source_tick']) <= 5
        and type(age) in (int, float) and math.isfinite(age) and 0 <= age <= 250
        and type(guard.get('schema_version')) is int and guard['schema_version'] == 1
        and type(guard.get('source_tick')) is int and guard['source_tick'] == observation.tick,
        'defense_attacker_facts_stale')
    try:
        source, sample, state = (_nano(facts.get('source_nano')), _nano(facts.get('sample_nano')),
                                 _nano(guard.get('source_nano')))
    except ValueError:
        require(False, 'defense_attacker_clock_invalid')
    require(0 <= sample-source <= 250_000_000 and 0 <= sample-state <= 250_000_000
        and abs(age-(sample-source)/1_000_000) <= .000001, 'defense_attacker_clock_stale')


def run(runtime, control, policy, ordinary):
    """Only invoked on a returned known native damage or typed threat stop; never resubmits work."""
    native = ordinary.evidence.get('native', {})
    previous = ordinary.last_observation
    if (runtime.has_unresolved_execution or runtime._job_control is not control
            or not runtime._lease_active or runtime._job_effect_certainty != 'known'
            or Runtime._unsafe_flags(native) or Runtime._unsafe_flags(native.get('result'))
            or native.get('result', {}).get('input_release_confirmed') is not True):
        raise ControlStop('defense_original_owner_or_release_unconfirmed', status='unknown')
    require(ordinary.status in ('failed', 'cancelled') and ordinary.reason in ('capability_damage_observed', 'capability_threat_observed')
        and native.get('reason') == ordinary.reason
        and native.get('status') in ('failed', 'cancelled')
        and native.get('action') in ('follow_path', 'break_block')
        and native.get('result', {}).get('input_release_confirmed') is True
        and previous is not None and native.get('action_session') == previous.context[3]
        and isinstance(native.get('action_id'), str), 'defense_exact_terminal_damage_receipt_required')
    if ordinary.reason == 'capability_threat_observed':
        from resident_controller.spatial_threat_snapshot import validate_defense_stop
        try:
            validate_defense_stop(native, policy['defense']['target_uuid'])
        except (ValueError, KeyError, TypeError):
            require(False, 'defense_typed_threat_stop_unconfirmed')
    preempted = (ordinary.reason == 'capability_threat_observed'
        and native['result']['route_threat_stop']['preempted_before_motion'] is True)
    control.emit('ordinary_interrupted', {'reason':ordinary.reason,
        'native_action_id':native['action_id'], 'native_action_session':native['action_session'],
        'request_ids':list(ordinary.request_ids), 'input_release_confirmed':True,
        'ordinary_resume_allowed':False, 'preempted_before_motion':preempted})
    owner = runtime.owner_context()
    config = policy['defense']

    def handler(_, original_control):
        require(original_control.budget.snapshot()['remaining']['observations'] >= 15,
                'defense_observations_and_cleanup_reserve_required')
        before = runtime.observe(entity_radius=16)
        require(before.context == previous.context, 'defense_context_changed')
        current_owner = runtime.owner_context()
        require(all(current_owner.get(k) == owner.get(k) for k in
            ('owner_id', 'owner_generation', 'gateway_session', 'world_context')), 'defense_owner_changed')
        last_action = before.state.get('client_action', {})
        require(last_action.get('action_id') == native['action_id']
            and last_action.get('action_session') == native['action_session']
            and last_action.get('status') == native['status'], 'defense_ordinary_action_replaced')
        minimum = config['min_health']
        threats._health(before, minimum)
        target = threats.entity(before, config['target_uuid'])
        require(target.get('type') in threats.NATIVE_COMBAT_TYPES
            and target.get('alive') is True and threats._number(target.get('health'))
            and target['health'] > 0, 'defense_supported_living_hostile_required')
        attacking_player(before, target)
        if ordinary.reason == 'capability_threat_observed':
            stopped = native['result']['route_threat_stop']
            require(target.get('entity_id') == stopped['entity_id']
                and target.get('type') == stopped['entity_type']
                and target.get('uuid') == stopped['target_uuid'], 'defense_stopped_attacker_replaced')
        defense_range = 3 if ordinary.reason == 'capability_threat_observed' else 6
        require(math.dist(threats.position(before.player), threats.position(target)) <= defense_range,
                'defense_attacker_out_of_range')
        if minimum > 14:
            threats._require_combat_capability(before, 'caller_health_reserve_guard_schema_version')
        ident, uid, kind = threats._identity(target)
        # No approach or retargeting. Existing native shield/retreat/collateral and
        # per-tick owner/context/health guards remain authoritative.
        command = {'op':'action', 'action':'combat_entity', 'target_entity_id':ident,
            'target_uuid':uid, 'target_type':kind, 'timeout_ms':config['timeout_ms'],
            'approach':False, 'shield':True, 'min_health':minimum}
        def verified(_, after):
            current = threats._same_target(target, after)
            return threats._dead(current) or (current is None and threats._combat_evidence(before, after, target))
        result = runtime.execute('defense.engage_once', command, verified, before=before, max_samples=12)
        # Runtime validates terminal input release independently of semantic success.
        cleanup = not runtime.has_unresolved_execution and runtime._job_effect_certainty != 'unknown'
        return {'status': result.status, 'reason':result.reason, 'cleanup_confirmed':cleanup,
                'request_ids':list(result.request_ids), 'target_uuid':uid, 'ordinary_resume_allowed':False}

    supervisor = TerminalDefensiveSupervisor(control, policy, reflexes={'defend_once':handler})
    supervisor.defend_once(reason=ordinary.reason, cleanup_confirmed=True, owner_known=True,
                          context_same=True, facts={'preempted_before_motion':preempted})
