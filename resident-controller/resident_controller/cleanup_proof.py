"""Read-only neutral proof for finishing an existing owner, never admission.

Explicit pause is permitted here only. No missing/malformed pause, controller,
input or old-owner evidence is replaced with an inferred neutral value.
"""
import math
from .fall_rescue_status import validate as validate_fall

CONTEXT = ('world_generation', 'dimension', 'player_uuid', 'action_session')
TERMINAL = frozenset(('idle', 'succeeded', 'failed', 'cancelled'))


def validate_cleanup(payload, context, *, last_fall=None, owner_id=None):
    try:
        s = payload['state']; p, w, a = s['player'], s['world'], s['client_action']
        actual = dict(zip(CONTEXT, (w['world_generation'], w['dimension'], p['uuid'], a['action_session'])))
        if (type(context) is not dict or actual != context
                or any(not isinstance(v, str) or not v for v in actual.values())
                or s.get('private_singleplayer') is not True or s.get('focused') is not True
                or type(s.get('screen_open')) is not bool or type(s.get('paused')) is not bool
                or p.get('alive') is not True or type(p.get('health')) not in (int, float)
                or not math.isfinite(p['health']) or p['health'] <= 0
                or p.get('dimension') != w['dimension']
                or type(w.get('game_time')) is not int or w['game_time'] < 0
                or a.get('status') not in TERMINAL or payload.get('action', {}).get('status') not in TERMINAL
                or payload.get('combat', {}).get('active') is not False
                or payload.get('status', {}).get('held_mappings') != []):
            raise ValueError('cleanup_context_or_owner_not_idle')
        held = s.get('held_inputs', {})
        if held.get('neutral') is not True:
            raise ValueError('cleanup_input_not_neutral')
        if s['paused'] and (held.get('keys') != [] or type(held.get('raw_keys')) is not int
                or held['raw_keys'] != 0 or type(held.get('world_mouse_buttons')) is not int
                or held['world_mouse_buttons'] != 0):
            raise ValueError('paused_cleanup_input_proof_missing')
        # Older active-only clients retain their old compatibility contract.
        # A paused exception always needs positive current external-idle proof.
        if s['paused'] or 'external_controller' in s:
            external = s.get('external_controller')
            if (type(external) is not dict or type(external.get('schema_version')) is not int
                    or external['schema_version'] != 1 or external.get('idle_proven') is not True
                    or any(external.get(k) != actual[k] for k in ('world_generation','player_uuid','action_session'))
                    or type(external.get('source_tick')) is not int or external['source_tick'] != w.get('game_time')):
                raise ValueError('cleanup_external_idle_unproven')
        for feature in ('external_navigation', 'managed_navigation'):
            if feature in s or feature + '_status' in s:
                navigation = s.get(feature + '_status')
                schema = feature + '_schema_version'
                if (type(navigation) is not dict or type(navigation.get(schema)) is not int
                        or navigation[schema] != 1 or navigation.get('input_owned') is not False
                        or navigation.get('unknown_outcome_quarantined') is not False):
                    raise ValueError('cleanup_' + feature + '_owner_unresolved')
        if last_fall is not None or 'native_fall_rescue_status' in s or 'native_fall_rescue' in s:
            fall = s.get('native_fall_rescue_status')
            if (type(fall) is not dict or type(fall.get('fall_rescue_schema_version')) is not int
                    or fall['fall_rescue_schema_version'] != 1 or fall.get('armed') is not False
                    or fall.get('input_owned') is not False or fall.get('automation_blocked') is not False
                    or fall.get('unknown_outcome_quarantined') is not False):
                raise ValueError('cleanup_native_rescue_not_disarmed')
            if owner_id is not None and fall.get('owner_id') == owner_id and last_fall is None:
                raise ValueError('cleanup_original_disarm_proof_missing')
            if last_fall is not None:
                if ((owner_id is not None and last_fall.get('owner_id') != owner_id)
                        or any(last_fall.get(key) is not False for key in
                               ('armed','input_owned','automation_blocked','unknown_outcome_quarantined'))):
                    raise ValueError('cleanup_original_disarm_unconfirmed')
                validate_fall(fall, arm_id=last_fall['arm_id'], owner_id=last_fall['owner_id'],
                              context=context, ttl_ms=5000, previous=last_fall)
                if (fall.get('arm_revision') != last_fall['arm_revision']
                        or fall.get('episodes_used') != last_fall['episodes_used']):
                    raise ValueError('cleanup_native_rescue_revision_changed')
        return {'schema_version': 1, 'paused': s['paused'], 'context': actual,
                'neutral_proven': True, 'gameplay_admission': False, 'automatic_resume': False}
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValueError('cleanup_proof_malformed') from exc
