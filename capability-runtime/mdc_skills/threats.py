"""Observed combat and environmental recovery through the existing gateway.

No daemon, target acquisition, raw key dispatch or automatic replay. The older
bounded native combat still owns its CombatThreats/health/sweep policy. The new
single-shot adapter is deliberately stricter about target and collateral scope.
"""
from __future__ import annotations

from functools import lru_cache
import importlib.util
import math
from pathlib import Path
import sys
from .core import Outcome, SkillError, require

NATIVE_COMBAT_TYPES = frozenset('minecraft:' + x for x in
    ('zombie', 'husk', 'zombie_villager', 'skeleton', 'stray', 'bogged'))
MELEE_TYPES = NATIVE_COMBAT_TYPES | {'minecraft:shulker', 'minecraft:spider', 'minecraft:enderman'}
RANGED_TYPES = (MELEE_TYPES - {'minecraft:enderman'}) | {'minecraft:creeper','minecraft:blaze','minecraft:cave_spider'}
ENVIRONMENT_FLAGS = ('in_water', 'eye_in_water', 'in_lava', 'in_powder_snow', 'on_fire')
_SPECIES_HEALTH_FLOOR = frozenset('minecraft:' + kind for kind in
    ('enderman', 'blaze', 'creeper', 'cave_spider'))
_DEFAULT_TIMEOUT = object()


def _number(value):
    return type(value) in (int, float) and math.isfinite(value)


def position(value):
    require(isinstance(value, dict) and all(_number(value.get(k)) for k in ('x', 'y', 'z')),
            'position_unavailable')
    return tuple(value[k] for k in ('x', 'y', 'z'))


def entities(observation):
    nearby = observation.state.get('nearby', {})
    values = nearby.get('entities')
    require(nearby.get('truncated') is False and isinstance(values, list), 'complete_entity_snapshot_required')
    require(type(nearby.get('returned')) is int and nearby['returned'] == len(values)
            and nearby.get('total') == len(values), 'entity_snapshot_count_mismatch')
    require(len(values) <= 128, 'entity_snapshot_budget')
    return values


def entity(observation, target_uuid, *, required=True):
    require(isinstance(target_uuid, str) and bool(target_uuid), 'explicit_target_uuid_required')
    matches = [e for e in entities(observation) if e.get('uuid') == target_uuid]
    require(len(matches) <= 1, 'duplicate_target_identity')
    if required:
        require(bool(matches), 'target_not_observed')
    return matches[0] if matches else None


def _identity(value):
    require(type(value.get('entity_id')) is int and value['entity_id'] >= 0
            and isinstance(value.get('uuid'), str) and isinstance(value.get('type'), str), 'target_identity_unavailable')
    return value['entity_id'], value['uuid'], value['type']


def _same_target(before, after):
    value = entity(after, before['uuid'], required=False)
    if value is not None:
        require(_identity(value) == _identity(before), 'target_identity_changed')
    return value


def _dead(value):
    return (value is not None and value.get('alive') is False
            and _number(value.get('health')) and value['health'] <= 0)


def _health(observation, minimum):
    require(_number(minimum) and 8 <= minimum <= 20, 'min_health_8_to_20')
    require(_number(observation.player.get('health')) and observation.player['health'] > minimum,
            'health_reserve_required')
    require(all(type(observation.player.get(k)) is bool for k in ENVIRONMENT_FLAGS),
            'environment_observation_required')
    require(not any(observation.player[k] for k in ENVIRONMENT_FLAGS), 'environment_recovery_required')
    require(observation.player.get('on_ground') is True, 'stable_ground_required')


def _effective_min_health(minimum, kind=None, *, shield_window=False, bounded=False):
    """One reserve for both Python admission and the native ongoing guard."""
    require(_number(minimum) and 8 <= minimum <= 20, 'min_health_8_to_20')
    floor = 18 if shield_window else 14 if bounded else 12 if kind in _SPECIES_HEALTH_FLOOR else 8
    return max(minimum, floor)


def _require_combat_capability(observation, name):
    """Only this fresh state's native advertisement authorizes the new contract."""
    capabilities = observation.state.get('combat_capabilities')
    require(isinstance(capabilities, dict)
            and type(capabilities.get('schema_version')) is int and capabilities['schema_version'] == 1
            and type(capabilities.get(name)) is int and capabilities[name] == 1,
            'native_' + name + '_required')


def _command(observation, action, target, timeout_ms, *, maximum=10000):
    require(type(timeout_ms) is int and 50 <= timeout_ms <= maximum, 'target_timeout_outside_action_budget')
    ident, uid, kind = _identity(target)
    return {'op': 'action', 'action': action, 'target_entity_id': ident, 'target_uuid': uid,
            'target_type': kind, 'timeout_ms': timeout_ms}


def _combat_evidence(before, observation, target):
    """Only exact target native death evidence, not target disappearance, can close a kill."""
    action = observation.state.get('client_action', {})
    combat = action.get('result', {}).get('combat', {})
    return (action.get('status') == 'succeeded'
            and isinstance(action.get('action_id'), str)
            and action['action_id'] != before.state.get('client_action', {}).get('action_id')
            and action.get('action_session') == before.context[3]
            and combat.get('target_uuid') == target['uuid']
            and combat.get('target_entity_id') == target['entity_id']
            and combat.get('target_dead_observed') is True)


def engage(runtime, target_uuid, *, timeout_ms=15000, approach=True, shield=True, min_health=10):
    """Existing real bounded combat: supported single hostile, explicit observed death.

    BoundedCombat itself replans short dry approach/retreat and checks threats every tick.
    Missing targets, safety retreat, timeout and merely dispatching attacks are not victory.
    The effective reserve is at least the native bounded-combat floor of 14;
    raising it requires this fresh native sample to advertise caller-reserve support.
    """
    require(type(timeout_ms) is int and 50 <= timeout_ms <= 30000, 'combat_timeout_50_to_30000')
    require(type(approach) is bool and type(shield) is bool, 'combat_flags_boolean')
    before = runtime.observe(entity_radius=16)
    minimum = _effective_min_health(min_health, bounded=True)
    _health(before, minimum)
    if minimum > 14:
        _require_combat_capability(before, 'caller_health_reserve_guard_schema_version')
    target = entity(before, target_uuid)
    require(target.get('type') in NATIVE_COMBAT_TYPES, 'bounded_combat_target_unsupported')
    require(target.get('alive') is True and _number(target.get('health')) and target['health'] > 0,
            'living_target_required')
    ident, uid, kind = _identity(target)
    command = {'op': 'action', 'action': 'combat_entity', 'target_entity_id': ident,
               'target_uuid': uid, 'target_type': kind, 'timeout_ms': timeout_ms,
               'approach': approach, 'shield': shield, 'min_health': minimum}
    def verified(_, after):
        current = _same_target(target, after)
        return _dead(current) or (current is None and _combat_evidence(before, after, target))
    result = runtime.execute('threats.engage', command, verified, before=before, max_samples=12)
    if not result.ok:
        return result
    after = result.last_observation
    current = _same_target(target, after)
    combat = after.state.get('client_action', {}).get('result', {}).get('combat', {})
    return Outcome(result.status, result.reason, result.request_ids, {**result.evidence,
        'target_uuid': target_uuid, 'target_initial_health': target['health'],
        'target_observed_health': current.get('health') if current else combat.get('target_health'),
        'target_dead_observed': True, 'damage_attributed_to_action': False}, after)


def _species_policy(observation,target,ranged,blaze_safety_mode=None):
    """Match native species guards; missing risk facts never become safe defaults."""
    kind=target['type'];distance=math.dist(position(observation.player),position(target))
    if kind=='minecraft:shulker':
        _require_combat_capability(observation, 'shulker_open_shell_guard_schema_version')
        require(target.get('shell_open') is True, 'shulker_requires_observed_open_shell')
        return {}
    if kind=='minecraft:enderman':
        shelter=observation.player.get('enderman_shelter',{})
        require(not ranged and shelter.get('schema_version')==1 and shelter.get('safe') is True,
                'enderman_requires_observed_two_block_shelter')
        return {'enderman_shelter_required':True}
    if kind=='minecraft:creeper':
        risk=target.get('creeper',{})
        require(ranged and type(risk.get('powered')) is bool and risk.get('ignited') is False
                and type(risk.get('swell_ticks')) is int and risk['swell_ticks']==0
                and type(risk.get('swell_direction')) is int and risk['swell_direction']<=0
                and type(risk.get('fuse_ticks')) is int and risk['fuse_ticks']>0
                and distance >= (16 if risk['powered'] else 12), 'creeper_requires_idle_fuse_and_ranged_standoff')
        return {'creeper_safety_required':True}
    if kind=='minecraft:cave_spider':
        effects=observation.player.get('effects')
        require(isinstance(effects,list) and ranged and distance>=8
                and not any(e.get('id')=='minecraft:poison' for e in effects), 'cave_spider_requires_ranged_poison_guard')
        return {'poison_guard_required':True}
    if kind=='minecraft:blaze':
        effects=observation.player.get('effects')
        require(ranged and isinstance(effects,list) and observation.player.get('effects_truncated') is False,
                'blaze_effect_observation_required')
        require(type(target.get('blaze',{}).get('charged'))is bool,'blaze_charge_observation_required')
        resistant=any(e.get('id')=='minecraft:fire_resistance' and type(e.get('duration_ticks'))is int
                and (e['duration_ticks']==-1 or e['duration_ticks']>=60) for e in effects)
        mode=('fire_resistance' if resistant else 'shield_window') if blaze_safety_mode is None else blaze_safety_mode
        require(mode in ('fire_resistance','shield_window'),'invalid_blaze_safety_mode')
        if mode=='fire_resistance':
            require(distance>=12 and resistant,'blaze_requires_observed_fire_resistance')
            return {'fire_resistance_required':True,'blaze_safety_mode':mode}
        shield=observation.player.get('offhand',{})
        require(16<=distance<=32 and observation.player['health']>18
                and shield.get('id')=='minecraft:shield' and shield.get('count')==1
                and isinstance(shield.get('item_fingerprint'),str), 'blaze_requires_shield_health_and_standoff')
        require(type(shield.get('max_damage'))is int and type(shield.get('damage'))is int
                and shield['max_damage']-shield['damage']>=64,'blaze_shield_durability_reserve')
        return {'blaze_safety_mode':mode,'expected_offhand_item':shield}
    return {}


def _recorded_target_death(before,after,target):
    """An exact native living-entity witness may outlive the dead render entity.

    Missing/disappearing alone remains insufficient. Runtime additionally binds
    this native action to its submitted request and every later sample.
    """
    action=after.state.get('client_action',{})
    witness=action.get('result',{}).get('target_action',{})
    previous=before.state.get('client_action',{})
    tick=witness.get('observation_tick')
    if (action.get('status')!='succeeded' or action.get('action') not in ('attack_entity','shoot_entity')
            or not isinstance(action.get('action_id'),str) or not action['action_id']
            or action['action_id']==previous.get('action_id') or action.get('action_session')!=before.context[3]
            or witness.get('target_uuid')!=target['uuid'] or witness.get('target_entity_id')!=target['entity_id']
            or witness.get('target_type')!=target['type'] or witness.get('target_dead_observed') is not True
            or not _number(witness.get('target_initial_health')) or witness['target_initial_health']<=0
            or not _number(witness.get('target_min_observed_health')) or witness['target_min_observed_health']>0
            or before.context!=after.context or type(tick)is not int or not before.tick<=tick<after.tick):
        return None
    return witness


def strike(runtime, target_uuid, *, ranged=False, min_health=10, timeout_ms=_DEFAULT_TIMEOUT,
           expected_dragon_phase=None, blaze_safety_mode=None, before=None):
    """One attack. Success requires later actual target health loss/death, not an attack receipt.

    Dragon use is restricted to the explicitly observed perched phase and native head
    ray. Crystal shots use dimensions.remove_crystal, whose outcome is observed removal.
    Species reserves are at least 12, and blaze shield-window reserve is at least 18.
    An omitted deadline selects 20 seconds for that shield cycle, 5 seconds otherwise.
    Explicit invalid deadlines are rejected rather than replaced by defaults.
    A composed caller may pass its current owned observation so a terrain proof
    and command share one frame. Runtime still validates ownership, unchanged
    bytes, latest observation identity and original freshness before submission.
    """
    require(type(ranged) is bool, 'ranged_boolean_required')
    if before is None:
        before = runtime.observe(entity_radius=48)
    target = entity(before, target_uuid)
    allowed = RANGED_TYPES if ranged else MELEE_TYPES | {'minecraft:ender_dragon'}
    require(target.get('type') in allowed, 'strike_target_unsupported')
    require(target.get('alive') is True and _number(target.get('health')) and target['health'] > 0,
            'living_target_health_required')
    minimum = _effective_min_health(min_health, target['type'])
    _health(before, minimum)
    require(blaze_safety_mode is None or target['type']=='minecraft:blaze','blaze_mode_requires_blaze_target')
    policy=_species_policy(before,target,ranged,blaze_safety_mode)
    shield_window=policy.get('blaze_safety_mode')=='shield_window'
    minimum = _effective_min_health(min_health, target['type'], shield_window=shield_window)
    _health(before, minimum)
    if timeout_ms is _DEFAULT_TIMEOUT:
        timeout_ms = 20000 if shield_window else 5000
    if shield_window:
        require(type(timeout_ms) is int and 18000<=timeout_ms<=20000,
                'blaze_shield_requires_complete_cycle_deadline')
    command = _command(before, 'shoot_entity' if ranged else 'attack_entity', target, timeout_ms,
                       maximum=20000 if shield_window else 10000)
    command['min_health'] = minimum
    command.update(policy)
    if ranged:
        command['draw_ticks'] = 20
    if target['type'] == 'minecraft:ender_dragon':
        require(type(expected_dragon_phase) is int and expected_dragon_phase in (6, 7)
                and target.get('phase_id') == expected_dragon_phase, 'dragon_requires_safe_perched_phase')
        command['expected_dragon_phase'] = expected_dragon_phase
    def verified(_, after):
        if shield_window:
            from .combat_goals import _shield_window_completed
            if not _shield_window_completed(before,after,target):return False
        current = _same_target(target, after)
        if current is None:
            return _recorded_target_death(before,after,target) is not None
        return (_dead(current) or (_number(current.get('health'))
                and current['health'] < target['health'] - .01))
    result = runtime.execute('threats.strike', command, verified, before=before,
                             max_samples=60 if ranged else 16, stable_samples=2)
    if not result.ok:
        return result
    after = result.last_observation
    current = _same_target(target, after)
    witness=_recorded_target_death(before,after,target) if current is None else None
    observed_health=current['health'] if current is not None else witness['target_min_observed_health']
    return Outcome(result.status, result.reason, result.request_ids, {**result.evidence,
        'target_uuid': target_uuid, 'target_initial_health': target['health'],
        'target_observed_health': observed_health,
        'observed_health_loss': target['health'] - observed_health,
        'target_dead_observed': _dead(current) or witness is not None,
        'native_death_witness':witness,'damage_attributed_to_action': False}, after)


def defeat(runtime, target_uuid, *, max_actions=8, ranged=False, min_health=10):
    """Bounded sequential attacks; each next strike needs independently observed damage.

    Stops on the first failure/unknown, even if the original target remains visible.
    This is never a retry of an unconfirmed action.
    """
    require(type(max_actions) is int and 1 <= max_actions <= 64, 'combat_action_budget_1_to_64')
    ids, observations = [], []
    for _ in range(max_actions):
        observation = runtime.observe(entity_radius=48)
        target = entity(observation, target_uuid)
        if _dead(target):
            return runtime.result('threats.defeat', observations=observations + [observation],
                                  action_request_ids=ids, target_uuid=target_uuid,
                                  outcome='target_dead_observed', damage_attributed_to_action=False)
        # The strike's own fresh observation selects its reserve and blaze mode.
        # A prior sample cannot select an obsolete mode/deadline or open shell.
        result = strike(runtime, target_uuid, ranged=ranged, min_health=min_health)
        ids.extend(result.request_ids)
        if not result.ok:
            return result
        after = runtime.require_success(result)
        observations.append(after)
        if _dead(entity(after, target_uuid, required=False)) or result.evidence.get('target_dead_observed') is True:
            return runtime.result('threats.defeat', observations=observations, action_request_ids=ids,
                                  target_uuid=target_uuid, outcome='target_dead_observed',
                                  damage_attributed_to_action=False)
    return Outcome('failed', 'combat_action_budget_exhausted', tuple(ids),
                   {'target_uuid': target_uuid, 'goal_completed': False, 'server_confirmed': False},
                   observations[-1] if observations else None)


@lru_cache(maxsize=1)
def _environment():
    path = Path(__file__).resolve().parents[2] / 'defense-watchdog' / 'environment_recovery.py'
    require(path.is_file(), 'existing_environment_recovery_missing')
    spec = importlib.util.spec_from_file_location('_mdc_existing_environment_recovery', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@lru_cache(maxsize=1)
def _retreat_planner():
    # Reuse the audited pure terrain planner. Imports instantiate no controller/queue.
    root = Path(__file__).resolve().parents[2]
    old = list(sys.path)
    try:
        sys.path[:0] = [str(root / 'defense-watchdog'), str(root / 'resident-controller')]
        from ranged_tactics import retreat_plan
        return retreat_plan
    finally:
        sys.path[:] = old


def recover_hazard(runtime, *, max_waypoints=64, timeout_ms=10000):
    """Exit currently observed water/fire/lava/powder snow using loaded collision geometry."""
    require(type(max_waypoints) is int and 1 <= max_waypoints <= 128, 'egress_waypoint_budget_1_to_128')
    require(type(timeout_ms) is int and 50 <= timeout_ms <= 30000, 'egress_timeout_50_to_30000')
    before = runtime.observe(terrain=True, radius=4, vertical=4)
    legacy = _environment()
    require(legacy.supported(before.state), 'environment_schema_required')
    if legacy.dry(before.state):
        return runtime.result('threats.recover_hazard', observations=[before], outcome='dry_ground_observed')
    require(bool(legacy.hazards(before.state)), 'no_observed_recoverable_hazard')
    points = legacy.egress_plan(before.state, before.terrain or {})
    require(points is not None and 0 < len(points) <= max_waypoints, 'no_bounded_observed_egress')
    frozen = before.player.get('frozen_ticks')
    return runtime.execute('threats.recover_hazard',
        {'op': 'action', 'action': 'recover_environment', 'waypoints': points, 'timeout_ms': timeout_ms},
        lambda _, after: legacy.dry(after.state) and type(after.player.get('frozen_ticks')) is int
                and after.player['frozen_ticks'] <= frozen,
        before=before, max_samples=16, stable_samples=3)


def retreat(runtime, target_uuid, *, timeout_ms=5000):
    """Two-cell maximum retreat, checked against every observed hostile and dry terrain."""
    require(type(timeout_ms) is int and 50 <= timeout_ms <= 10000, 'retreat_timeout_50_to_10000')
    before = runtime.observe(terrain=True, radius=4, vertical=3)
    target = entity(before, target_uuid)
    plan = _retreat_planner()(before.state, before.terrain or {}, target)
    require(plan is not None, 'no_observed_dry_retreat')
    original_distance = math.dist(position(before.player), position(target))
    goal = position(plan['waypoints'][-1])
    def verified(_, after):
        current = _same_target(target, after)
        return (current is not None and math.dist(position(after.player), goal) <= .45
                and math.dist(position(after.player), position(current)) >= original_distance + .5
                and all(after.player.get(k) is False for k in ENVIRONMENT_FLAGS))
    return runtime.execute('threats.retreat',
        {'op': 'action', 'action': 'follow_path', 'waypoints': plan['waypoints'], 'timeout_ms': timeout_ms},
        verified, before=before)
