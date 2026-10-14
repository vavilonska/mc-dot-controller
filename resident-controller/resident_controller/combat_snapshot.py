"""Closed action-local combat admission witness; never authority to resume or retarget."""
import re
from .capability_snapshot import _require, _integer, _number, exact, signed_long_string

PROFILE = 'combat-local-observed-v1'
TYPES = frozenset('minecraft:' + name for name in
                  ('zombie', 'husk', 'zombie_villager', 'skeleton', 'stray', 'bogged'))
FIELDS = frozenset(('profile', 'target_entity_id', 'target_uuid', 'target_type',
                    'target_health', 'x', 'y', 'z', 'alive', 'approach', 'shield',
                    'min_health', 'timeout_ms'))


def validate_combat(witness, intent, native):
    facts = witness['facts']
    combat = facts.get('combat')
    _require(type(combat) is dict and set(combat) == FIELDS
             and combat['profile'] == PROFILE, 'combat_schema')
    _require(intent.get('action') == native.get('action') == 'combat_entity'
             and _integer(combat['target_entity_id'], 0, 2**31 - 1)
             and type(combat['target_uuid']) is str
             and re.fullmatch(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}',
                              combat['target_uuid']) is not None
             and combat['target_uuid'] != facts['context']['player_uuid']
             and type(combat['target_type']) is str and combat['target_type'] in TYPES
             and _number(combat['target_health']) and combat['target_health'] > 0
             and combat['alive'] is True, 'combat_target')
    _require(all(_number(combat[k]) and abs(combat[k]) <= limit
                 for k, limit in (('x', 30000000), ('y', 2048), ('z', 30000000))),
             'combat_target_position')
    _require(type(combat['approach']) is bool and type(combat['shield']) is bool
             and _number(combat['min_health']) and 14 <= combat['min_health'] <= 20
             and _integer(combat['timeout_ms'], 50, 30000), 'combat_bounds')
    # Native represents health as a double, while canonical JSON may encode an integer.
    # Both must independently be finite numbers; boolean/numeric coercion is forbidden.
    _require(all(exact(combat[k], intent.get(k)) for k in
                 ('target_entity_id', 'target_uuid', 'target_type', 'approach', 'shield', 'timeout_ms'))
             and _number(intent.get('min_health')) and combat['min_health'] == intent['min_health'],
             'combat_intent_binding')
    required = {'action', 'action_id', 'target_entity_id', 'target_uuid', 'target_type',
                'approach', 'shield', 'min_health', 'timeout_ms', 'capability_guard',
                'expected_world_generation', 'expected_dimension', 'expected_player_uuid',
                'expected_action_session', 'expected_hotbar_slot', 'expected_held_item'}
    navigation = {'expected_navigation_epoch', 'expected_origin'}
    _require(set(intent) in (required, required | navigation), 'combat_closed_intent')
    _require(exact(intent['expected_hotbar_slot'], facts['selected_slot']), 'combat_selected_slot')
    held = intent['expected_held_item']
    actual = facts['inventory'][facts['selected_slot']]['item']
    _require(type(held) is dict and all(exact(held.get(k), actual.get(k)) for k in
                 ('id', 'count', 'empty', 'item_fingerprint', 'component_fingerprint', 'max_stack_size')),
             'combat_held_binding')
    if 'expected_origin' in intent:
        origin = intent['expected_origin']
        _require(_integer(intent['expected_navigation_epoch']) and type(origin) is dict
                 and set(origin) == {'x', 'y', 'z'}
                 and all(_number(origin[k]) and abs(origin[k] - facts[k]) <= .03 for k in origin),
                 'combat_origin_binding')
    _require(facts['health'] > combat['min_health'] and facts['screen_class'] == ''
             and facts['using_item'] is False
             and facts['menu']['menu_class'] == 'net.minecraft.world.inventory.InventoryMenu'
             and facts['menu']['container_id'] == 0 and facts['menu']['carried']['empty'] is True,
             'combat_player_context')
    guard = intent.get('capability_guard')
    _require(type(guard) is dict and set(guard) == {'schema_version', 'source_tick', 'source_nano'}
             and exact(guard['schema_version'], 1) and _integer(guard['source_tick'])
             and guard['source_tick'] <= witness['source_tick']
             and signed_long_string(guard['source_nano'])
             and int(guard['source_nano']) <= int(witness['source_nano']), 'combat_planning_guard')
