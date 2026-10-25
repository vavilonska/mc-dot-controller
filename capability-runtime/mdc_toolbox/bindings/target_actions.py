"""Closed public single-target primitives. No encounter/campaign composite registration."""
from copy import deepcopy
from mdc_skills import scoped_target_action, threats
from mdc_toolbox.contracts import ToolboxError, obj, validate_schema
from .tactical import UUID, default, number, definition, _SCHEMAS as LEGACY_SCHEMAS

_SCHEMAS = {
    'strike': deepcopy(LEGACY_SCHEMAS['strike']),
    'remove_crystal': obj({'target_uuid': UUID, 'min_health': default(number(12, 20), 12)}, ('target_uuid',)),
}


def definitions():
    result = []
    for name, schema in _SCHEMAS.items():
        value = definition(name, schema, group='combat_threats' if name == 'strike' else 'dimensions',
            level='primitive', profile='entities', sources=(scoped_target_action, threats),
            actions=('attack_entity', 'shoot_entity') if name == 'strike' else ('shoot_entity',),
            description='One exact stationary selected-axe melee attack or fully drawn selected-bow release with independently observed outcome.'
                if name == 'strike' else 'One exact selected-bow crystal shot with loaded-area removal verification.',
            bounds={'native_offense_effects': 1, 'native_offense_packets': 1,
                    'native_timeout_ms': 20000, 'callback_budget_ms': 50,
                    'shared_budget': 'original_job_ledger'})
        value.update(adapter_status='scoped_native', public_support='negotiated_profile_required')
        value['native_features'] += ['scoped-native-preflight/1', 'profile:' + scoped_target_action.PROFILE]
        value['known_limits'] = [
            'Melee requires an already selected vanilla axe, zero client knockback and no sweep; swords are refused before dispatch.',
            'Only one explicitly selected target. No movement, auto-equipping, pursuit, retry, or resume.',
            'Enderman shelter, blaze safety window, creeper fuse, cave-spider poison, crystal clearance and dragon phase/head-ray restrictions remain mandatory.',
            'Target health loss is observed, not causally attributed; missing living targets are not kills.',
            'Crystal removal is local loaded-area evidence only, never global crystal absence.',
            'Unknown effect or input cleanup quarantines the original owner until explicit reconciliation.',
            'Offline validation does not establish live ordinary-world completion.']
        result.append(value)
    return result


def invoke(capability, runtime, arguments, control):
    if capability not in _SCHEMAS:
        raise ToolboxError('capability_unavailable', 'Unknown stationary target primitive')
    validate_schema(arguments, _SCHEMAS[capability])
    control.checkpoint()
    result = getattr(scoped_target_action, capability)(runtime, **deepcopy(arguments))
    control.emit('target_action_observed' if result.ok else 'target_action_stopped',
        {'capability': capability, 'status': result.status, 'reason': result.reason,
         'request_ids': list(result.request_ids), 'automatic_replay_allowed': False})
    return result


def execute(adapter, name, args, budget):
    return invoke(name, adapter, args, budget)
