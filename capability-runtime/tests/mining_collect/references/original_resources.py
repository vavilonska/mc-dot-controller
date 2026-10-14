"""Finite resource goals; inventory acquisition and block removal stay distinct."""
from copy import deepcopy
from mdc_skills import resources as skills, supply, planning, production
from mdc_toolbox.bindings.production import (_object, _integer, _number, _enum, _ITEM, _COORD,
                         _definition, _invoke, _validate, _inventory_counts)

_EXCLUDED = {'type': 'array', 'maxItems': 32768, 'items': _COORD}
_GOALS = {'type': 'object', 'minProperties': 1, 'maxProperties': 32,
          'patternProperties': {'^minecraft:[a-z0-9_./-]{1,118}$': _integer(1, 2304)},
          'additionalProperties': False}
_SCHEMAS = {
    'find_resources': _object({'block_ids': {'type': 'array', 'minItems': 1, 'maxItems': 128,
        'uniqueItems': True, 'items': _ITEM}, 'limit': _integer(1, 128)}, ('block_ids',)),
    'mine': _object({'target': _COORD, 'expected_item_id': _ITEM, 'hotbar_slot': _integer(0, 8),
                    'require_drops': {'type': 'boolean'}}, ('target',)),
    'collect': _object({'item_id': _ITEM, 'minimum': _integer(1, 64),
        'max_targets': _integer(1, 16), 'max_steps': _integer(1, 128)}, ('item_id',)),
    'mine_and_collect': _object({'target': _COORD, 'item_id': _ITEM, 'minimum': _integer(1, 64),
        'hotbar_slot': _integer(0, 8), 'max_targets': _integer(1, 16), 'max_steps': _integer(1, 128)},
        ('target', 'item_id')),
    'acquire_nearby': _object({'item_id': _enum(planning.RESOURCE_BLOCKS), 'count': _integer(1, 2304),
        'max_blocks': _integer(1, 32), 'excluded_positions': _EXCLUDED}, ('item_id',)),
    'ensure_items': _object({'requirements': _GOALS, 'max_nodes': _integer(1, 1024),
        'max_blocks': _integer(1, 1024), 'max_batches': _integer(1, 1024),
        'timeout_seconds': _number(1, 3600), 'max_actions': _integer(1, 32768),
        'max_search_steps': _integer(0, 512), 'max_walk_distance': _integer(0, 8192),
        'excluded_positions': _EXCLUDED}, ('requirements',)),
    'place_workstation': _object({'block_id': _enum(production.STATIONS), 'position': _COORD,
        'excluded_positions': _EXCLUDED}, ('block_id',)),
}
_DISPATCH = {'find_resources': skills.find, 'mine': skills.mine, 'collect': skills.collect,
             'mine_and_collect': skills.mine_and_collect, 'acquire_nearby': planning.acquire_nearby,
             'ensure_items': supply.ensure_items, 'place_workstation': supply.place_workstation}
_MOB_SOURCES = ('minecraft:ender_pearl', 'minecraft:blaze_rod', 'minecraft:gunpowder', 'minecraft:string')


def acquisition_metadata(item_id):
    """Supported source vocabulary, never a promise of discovered raw material."""
    name = item_id.removeprefix('minecraft:')
    if name in production.CRAFT_RECIPES:
        recipe = production.CRAFT_RECIPES[name]
        return {'route': 'craft', 'recipe': name, 'output_per_batch': recipe.count,
                'ingredient_alternatives': {key: list(value) for key, value in recipe.ingredients.items()}}
    if item_id in supply.SMELT_OUTPUTS:
        return {'route': 'smelt', 'input_alternatives': list(supply.SMELT_OUTPUTS[item_id]),
                'raw_source_must_be_carried': item_id in supply.FOOD_SMELT_OUTPUTS}
    if item_id in planning.RESOURCE_BLOCKS:
        return {'route': 'mine_and_collect', 'block_ids': list(planning.RESOURCE_BLOCKS[item_id]),
                'minimum_tool': supply.MINING_TOOLS.get(item_id), 'requires_observed_loaded_source': True}
    if item_id in _MOB_SOURCES:
        return {'route': 'existing_bounded_mob_drop_policy', 'requires_explicit_combat_policy': True,
                'drop_not_guaranteed': True}
    return {'route': 'carried_only', 'unsupported_source': item_id,
            'reason': 'no_supported_acquisition_recipe'}


def definitions():
    rows = []
    for name, schema in _SCHEMAS.items():
        rows.append(_definition(name, 'resources', 'query' if name == 'find_resources' else
            'bounded_composite' if name in ('ensure_items', 'mine_and_collect', 'acquire_nearby') else 'primitive',
            schema, (skills, supply, planning), query=name == 'find_resources',
            prerequisites=('Fresh exact local cells/entities and ordinary tool/drop checks.',
                'Sufficient output capacity; requested totals use measured inventory counts.'),
            limits=('mine proves block removal only; collect proves a separate stable inventory gain without causal-drop attribution.',
                'Legacy mine.expected_item_id means the exact source BLOCK id, not an expected drop.',
                'No generic food-source, flint/gravel or feather acquisition route is implemented.',
                'Cooked food routes only from carried raw food, including protected ingredient reservations.',
                'max_walk_distance in legacy supply counts selected route allocations, not all nested physical displacement.',
                'Combat-sourced materials retain their existing safeguards; recipe support is not material availability.'),
            features=(() if name == 'find_resources' else ('action:break_block',) if name in ('mine', 'mine_and_collect', 'acquire_nearby') else ('action:place_block',) if name == 'place_workstation' else ('action:follow_path',) if name == 'collect' else ('action:click_slot', 'action:break_block', 'action:place_block')),
            bounds={'resource_query_limit': 128, 'pickup_targets': 16, 'inventory_total_per_item': 2304,
                    'requirement_items': 32, 'nested_limits': 'Original shared P2 job budget applies at every runtime boundary.'}))
    for row in rows:
        row['planner_available'] = row['capability'] in ('ensure_items', 'acquire_nearby')
    return rows


def invoke(capability, runtime, arguments, control):
    return _invoke(capability, runtime, arguments, control, _SCHEMAS, _DISPATCH)


def plan(capability, arguments, observation=None):
    _validate(capability, arguments, _SCHEMAS)
    result = {'capability': capability, 'status': 'unavailable', 'execution_authority': False,
              'reason': 'no_read_only_planner_for_capability', 'observation_used': False}
    if capability not in ('ensure_items', 'acquire_nearby'):
        return result
    goals = arguments['requirements'] if capability == 'ensure_items' else {
        arguments['item_id']: arguments.get('count', 1)}
    counts = _inventory_counts(observation)
    entries, blockers = [], []
    for item, total in sorted(goals.items()):
        source = acquisition_metadata(item)
        entry = {'item_id': item, 'requested_total': total, 'source': source}
        if counts is not None:
            entry.update(observed_total=counts[item], deficit=max(0, total - counts[item]))
        entries.append(entry)
        if counts is not None and counts[item] >= total:
            continue
        if source['route'] == 'carried_only':
            blockers.append({'code': 'unsupported_source', 'item_id': item,
                             'inventory_availability': 'unknown' if counts is None else 'insufficient'})
        if source.get('raw_source_must_be_carried'):
            raw = source['input_alternatives'][0]
            # Account for final raw-food goals; don't spend their protected stock.
            required = total - (counts[item] if counts is not None else 0) + goals.get(raw, 0)
            if counts is None or counts[raw] < required:
                blockers.append({'code': 'unsupported_food_source', 'item_id': raw,
                    'required_carried_raw': required,
                    'inventory_availability': 'unknown' if counts is None else 'insufficient'})
    result.update(status='planned', reason='finite_source_metadata', goals=entries, blockers=blockers,
                  observation_used=counts is not None, nested_acquisition_plan=False,
                  movement_accounting='selected_route_allocations_not_all_nested_physical_displacement')
    return result
