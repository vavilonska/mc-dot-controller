"""Data-only interaction goals compiled to the existing guarded verifier."""
from __future__ import annotations

import re
from . import reach
from .core import SkillError, require
from .stack_selector import ITEM_PATTERN

MENU_CLASSES = ('ChestMenu', 'HopperMenu', 'DispenserMenu', 'ShulkerBoxMenu',
                'CraftingMenu', 'FurnaceMenu', 'BlastFurnaceMenu', 'SmokerMenu',
                'AnvilMenu', 'EnchantmentMenu', 'BrewingStandMenu', 'GrindstoneMenu',
                'StonecutterMenu', 'LoomMenu', 'CartographyTableMenu', 'SmithingMenu')
MENU_NAMES = tuple('net.minecraft.world.inventory.' + name for name in MENU_CLASSES)
BLOCK_MENU_FAMILIES = {
    'minecraft:crafting_table': 'CraftingMenu', 'minecraft:furnace': 'FurnaceMenu',
    'minecraft:blast_furnace': 'BlastFurnaceMenu', 'minecraft:smoker': 'SmokerMenu',
    'minecraft:dispenser': 'DispenserMenu', 'minecraft:dropper': 'DispenserMenu',
    'minecraft:barrel': 'ChestMenu'}
BLOCK_MENU_GOAL_SCHEMA = {'type': 'object', 'additionalProperties': False,
    'required': ['kind', 'menu_class'], 'properties': {'kind': {'const': 'menu_open'},
    'menu_class': {'enum': sorted({'net.minecraft.world.inventory.' + v for v in BLOCK_MENU_FAMILIES.values()})}}}
GOAL_SCHEMA = {'oneOf': [
    {'type': 'object', 'additionalProperties': False, 'required': ['kind', 'menu_class'],
     'properties': {'kind': {'const': 'menu_open'}, 'menu_class': {'enum': list(MENU_NAMES)}}},
    {'type': 'object', 'additionalProperties': False, 'required': ['kind', 'block_id', 'properties'],
     'properties': {'kind': {'const': 'block_state'},
        'block_id': {'type': 'string', 'pattern': ITEM_PATTERN, 'maxLength': 128},
        'properties': {'type': 'object', 'minProperties': 0, 'maxProperties': 32,
            'propertyNames': {'pattern': '^[a-z0-9_]+$', 'maxLength': 64},
            'additionalProperties': {'type': 'string', 'minLength': 1, 'maxLength': 64}}}}
]}


def validate_goal(goal):
    require(type(goal) is dict, 'typed_interaction_goal_required')
    if goal.get('kind') == 'menu_open':
        require(set(goal) == {'kind', 'menu_class'} and goal['menu_class'] in MENU_NAMES,
                'unsupported_exact_menu_goal')
    else:
        require(set(goal) == {'kind', 'block_id', 'properties'} and goal.get('kind') == 'block_state',
                'unsupported_interaction_goal')
        require(type(goal['block_id']) is str and len(goal['block_id']) <= 128
                and re.fullmatch(ITEM_PATTERN, goal['block_id']), 'invalid_goal_block_id')
        props = goal['properties']
        require(type(props) is dict and len(props) <= 32 and all(type(k) is str
                and len(k) <= 64 and re.fullmatch('[a-z0-9_]+', k) and type(v) is str
                and 1 <= len(v) <= 64 for k, v in props.items()), 'invalid_goal_block_properties')
    return goal


def interact(runtime, target, *, goal, face='up', expected_block_id=None, hotbar_slot=None,
             expected_block_properties=None, stationary_menu=False):
    goal = validate_goal(goal)
    require(hotbar_slot is None or type(hotbar_slot) is int and 0 <= hotbar_slot <= 8,
            'invalid_hotbar_slot')
    if expected_block_id is not None:
        require(type(expected_block_id) is str and len(expected_block_id) <= 128
                and re.fullmatch(ITEM_PATTERN, expected_block_id), 'invalid_expected_block_id')
    if stationary_menu:
        require(goal['kind'] == 'menu_open' and expected_block_id in BLOCK_MENU_FAMILIES,
                'unsupported_stationary_menu_family')
        require(goal['menu_class'] == 'net.minecraft.world.inventory.' + BLOCK_MENU_FAMILIES[expected_block_id],
                'stationary_menu_family_goal_mismatch')
        require(type(expected_block_properties) is dict, 'exact_target_properties_required')
    if goal['kind'] == 'menu_open':
        confirmed_identity = None
        def verified(old, new):
            nonlocal confirmed_identity
            menu = new.state.get('menu', {})
            matched = (new.state.get('screen_open') is True and menu.get('menu_class') == goal['menu_class']
                    and type(menu.get('container_id')) is int and menu['container_id'] > 0
                    and menu['container_id'] != old.state.get('menu', {}).get('container_id')
                    and menu.get('slots_truncated') is False
                    and menu.get('carried', {}).get('empty') is True
                    and type(menu.get('state_id')) is int and menu['state_id'] >= 0)
            if not matched:
                return False
            identity = (menu['menu_class'], menu['container_id'], menu['state_id'])
            if confirmed_identity is None:
                confirmed_identity = identity
            return identity == confirmed_identity
    else:
        def verified(old, new):
            try:
                cell = reach.block_at(new, target)
            except SkillError:
                return False
            return (cell['id'] == goal['block_id']
                    and all(cell['properties'].get(k) == v for k, v in goal['properties'].items()))
    return reach.interact(runtime, target, face=face, expected_block_id=expected_block_id,
                          hotbar_slot=hotbar_slot, verify=verified,
                          stationary_menu=stationary_menu, expected_block_properties=expected_block_properties,
                          expected_open_menu_class=goal.get('menu_class'))
