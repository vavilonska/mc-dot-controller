"""Closed exact stack selectors; observation handles are never authority tokens."""
from __future__ import annotations

import re
from .core import require

ITEM_PATTERN = r'^minecraft:[a-z0-9_./-]+$'
INSTANT_EFFECTS = frozenset({'minecraft:instant_health', 'minecraft:instant_damage', 'minecraft:saturation'})
SELECTOR_SCHEMA = {'type': 'object', 'additionalProperties': False,
    'properties': {
        'inventory_slot': {'type': 'integer', 'minimum': 0, 'maximum': 35},
        'item_fingerprint': {'type': 'string', 'minLength': 1, 'maxLength': 128},
        'component_fingerprint': {'type': 'string', 'minLength': 1, 'maxLength': 128},
        'effect_id': {'type': 'string', 'pattern': ITEM_PATTERN, 'maxLength': 128}}}


def validate_selector(selector):
    if selector is None:
        return {}
    require(type(selector) is dict and set(selector) <= set(SELECTOR_SCHEMA['properties']),
            'invalid_stack_selector')
    for key, value in selector.items():
        if key == 'inventory_slot':
            require(type(value) is int and 0 <= value <= 35, 'invalid_selector_inventory_slot')
        else:
            require(type(value) is str and 1 <= len(value) <= 128, 'invalid_selector_handle')
            if key == 'effect_id':
                require(re.fullmatch(ITEM_PATTERN, value) is not None, 'invalid_selector_effect_id')
    return dict(selector)


def matches(item, selector, *, check_slot=True):
    selector = validate_selector(selector)
    if not isinstance(item, dict) or item.get('empty') is not False:
        return False
    for key, value in selector.items():
        if key == 'inventory_slot':
            if check_slot and item.get('slot') != value:
                return False
        elif key == 'effect_id':
            if not (value not in INSTANT_EFFECTS
                    and item.get('potion_effects_truncated') is False
                    and not any(e.get('id') in INSTANT_EFFECTS for e in item.get('potion_effects', []))
                    and any(e.get('id') == value and type(e.get('duration_ticks')) is int
                            and e['duration_ticks'] > 0 for e in item.get('potion_effects', []))):
                return False
        elif item.get(key) != value:
            return False
    return True


def selected_rows(observation, item_id, selector=None):
    from .inventory import items
    require(type(item_id) is str and len(item_id) <= 128
            and re.fullmatch(ITEM_PATTERN, item_id) is not None, 'item_id_required')
    selector = validate_selector(selector)
    return [r for r in items(observation) if r.get('id') == item_id
            and type(r.get('count')) is int and r['count'] > 0 and matches(r, selector)]
