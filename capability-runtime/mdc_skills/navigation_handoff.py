"""Sampled control/survival report. A selector is advice, never execution authority.

Physics motion is not evidence of held input. Release of the exact runtime owner
is separate from both neutral controls and observed player hazards.
"""
from __future__ import annotations
import math

TERMINAL = frozenset(('idle', 'succeeded', 'failed', 'cancelled', 'rejected', 'expired'))


def _number(value):
    return type(value) in (int, float) and math.isfinite(value)


def report(observation, *, now, max_age, owner_released=False, unresolved=False):
    state, player = observation.state, observation.player
    age = now - observation.captured_at
    fresh = _number(age) and 0 <= age <= max_age
    controls, hazards, unknown = [], [], []
    native = state.get('client_action', {})
    if state.get('held_inputs', {}).get('neutral') is not True: controls.append('input_release_unproven')
    if native.get('status') not in TERMINAL: controls.append('native_action_not_settled')
    # A receipt's settled status does not override UNKNOWN execution or rescue quarantine.
    if unresolved: controls.append('execution_unresolved')
    external = state.get('external_controller', {})
    if type(external.get('schema_version')) is not int or external.get('schema_version') != 1 or external.get('idle_proven') is not True:
        controls.append('external_controller_idle_unproven')
    elif (external.get('action_session') != observation.context[3]
          or external.get('world_generation') != observation.context[0]
          or external.get('player_uuid') != observation.context[2]
          or external.get('source_tick') != observation.tick):
        controls.append('external_controller_context_mismatch')
    if 'managed_navigation' in state or 'managed_navigation_status' in state:
        navigation=state.get('managed_navigation_status')
        if (not isinstance(navigation,dict) or type(navigation.get('managed_navigation_schema_version')) is not int
                or navigation.get('managed_navigation_schema_version')!=1 or navigation.get('input_owned') is not False
                or navigation.get('unknown_outcome_quarantined') is not False):
            controls.append('managed_navigation_original_owner_unresolved')
    if 'external_navigation' in state or 'external_navigation_status' in state:
        navigation=state.get('external_navigation_status')
        if (not isinstance(navigation,dict) or type(navigation.get('external_navigation_schema_version')) is not int
                or navigation.get('external_navigation_schema_version')!=1 or navigation.get('input_owned') is not False
                or navigation.get('unknown_outcome_quarantined') is not False):
            controls.append('external_navigation_original_owner_unresolved')
    rescue = state.get('native_fall_rescue_status')
    if 'native_fall_rescue_status' in state or 'native_fall_rescue' in state:
        if (not isinstance(rescue, dict) or type(rescue.get('fall_rescue_schema_version')) is not int
                or rescue.get('fall_rescue_schema_version') != 1
                or rescue.get('input_owned') is not False or rescue.get('unknown_outcome_quarantined') is not False):
            controls.append('native_rescue_owner_or_quarantine')
    if not fresh: controls.append('sample_stale_or_clock_reversed')
    if state.get('private_singleplayer') is not True: hazards.append('private_singleplayer_required')
    for key, expected in (('focused', True), ('paused', False), ('screen_open', False)):
        if state.get(key) is not expected: hazards.append(key + '_unsafe_or_unknown')
    if player.get('alive') is not True or not _number(player.get('health')) or player['health'] <= 0:
        hazards.append('player_not_alive')
    if _number(player.get('health')) and 0 < player['health'] <= 6: hazards.append('health_critical')
    if player.get('environment_schema_version') != 1: unknown.append('environment_sample_missing')
    for key in ('in_water', 'eye_in_water', 'in_lava', 'in_powder_snow', 'on_fire', 'on_ground'):
        if type(player.get(key)) is not bool: unknown.append(key + '_unknown')
    for key in ('in_lava', 'in_powder_snow', 'on_fire'):
        if player.get(key) is True: hazards.append(key)
    air, max_air = player.get('air'), player.get('max_air')
    if not _number(air) or not _number(max_air) or max_air <= 0: unknown.append('air_unknown')
    elif air <= max(20, .2 * max_air): hazards.append('air_critical')
    elif player.get('eye_in_water') is True: hazards.append('submerged_requires_air_recovery')
    velocity = player.get('velocity', {})
    motion = all(_number(velocity.get(k)) for k in ('x', 'y', 'z'))
    if not motion: unknown.append('velocity_unknown')
    vehicle = player.get('vehicle', {})
    if vehicle.get('riding') is True:
        mode = 'boat'
        if vehicle.get('ordinary_boat') is not True or vehicle.get('controlling_seat') is not True:
            hazards.append('boat_control_seat_unproven')
        if vehicle.get('alive') is not True: hazards.append('boat_not_alive')
        if vehicle.get('water_status') not in ('in_water', 'on_land'):
            hazards.append('boat_water_status_unsafe_or_unknown')
    elif vehicle.get('riding') is not False:
        mode = 'unknown'; unknown.append('vehicle_state_unknown')
    elif player.get('in_water') is True: mode = 'swim'
    elif player.get('on_ground') is True: mode = 'walk'
    else: mode = 'airborne'; hazards.append('airborne_requires_recovery')
    if not fresh: unknown.append('sample_stale_or_clock_reversed')
    physical_safe = False if hazards else (None if unknown else True)
    released = not controls
    if unresolved or 'native_rescue_owner_or_quarantine' in controls or 'external_navigation_original_owner_unresolved' in controls or 'managed_navigation_original_owner_unresolved' in controls:
        decision, reason = 'reconcile_original_owner', 'unresolved_owner_blocks_handoff'
    elif not released: decision, reason = 'observe_controls', controls[0]
    elif owner_released is not True: decision, reason = 'wait_exact_owner_release', 'owner_release_unconfirmed'
    elif physical_safe is not True: decision, reason = 'safety_recovery_required', (hazards + unknown)[0]
    else: decision, reason = 'fresh_owner_admission_required', 'sampled_handoff_ready'
    return {'schema_version': 1, 'scope': 'sampled_player_hazards_only',
            'source_request_id': observation.request_id, 'source_tick': observation.tick,
            'source_context': list(observation.context), 'age_ms': age * 1000 if _number(age) else None,
            'fresh': fresh, 'control_released': released, 'ownership_released': owner_released is True,
            'physical_safe': physical_safe, 'mode': mode, 'control_blockers': controls,
            'hazards': hazards, 'unknowns': unknown,
            'physics_motion_present': (any(abs(velocity[k]) > .001 for k in ('x', 'y', 'z')) if motion else None),
            'selector': {'decision': decision, 'reason': reason, 'mode': mode,
                         'preferred_backend': 'existing_guarded_runtime' if mode in ('walk','swim','boat') else None,
                         'execution_authority': False, 'automatic_resume': False,
                         'requires_mode_capability_negotiation': True},
            'server_confirmed': False}
