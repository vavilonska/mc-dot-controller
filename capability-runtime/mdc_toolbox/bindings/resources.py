"""Finite resource goals; inventory acquisition and block removal stay distinct."""
from copy import deepcopy
from mdc_skills import resources as skills, supply, planning, production
from mdc_skills import scoped_mining, scoped_collect
from .production import (_object, _integer, _number, _enum, _ITEM, _COORD,
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
_COLLECT_SCHEMA = _object({'target_uuid': {'type':'string', 'pattern':'^' + scoped_collect._UUID + '$'},
    'item_id':_enum(scoped_collect.ITEMS), 'minimum':_integer(1,64), 'min_health':_number(8,20)},
    ('target_uuid','item_id'))
_MOB_SOURCES = ('minecraft:ender_pearl', 'minecraft:blaze_rod', 'minecraft:gunpowder', 'minecraft:string')
_MINE_LOCAL_SCHEMA = _object({'target': _COORD, 'expected_block_id': _enum(scoped_mining.BLOCKS),
    'expected_block_properties': {'type': 'object'}, 'require_correct_tool': {'type': 'boolean'}},
    ('target', 'expected_block_id', 'expected_block_properties'))
_MINE_LOCAL_SCHEMA['allOf'] = [{
    'if': {'properties': {'expected_block_id': _enum(scoped_mining.LOGS)}},
    'then': {'properties': {'expected_block_properties': _object({'axis': _enum(('x','y','z'))}, ('axis',))}},
    'else': {'properties': {'expected_block_properties': _object({})}},
}]



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
    local = _definition('mine_local','resources','local_controller',
        _MINE_LOCAL_SCHEMA,
        (scoped_mining,), prerequisites=('Negotiated mining-local-observed-v2 with exact native callback fences.',
            'Private Overworld survival; stationary supported player and selected ordinary tool.'),
        limits=('Observed-profile v2: at most 8 seconds / 160 native action ticks; longer native requests refused.',
            'Distant supported passives use observed projection; ordinary items allowed; no future-dynamics guarantee.',
            'Exactly one explicit full-cube target, including six plain log species with exact axis and iron ores; no movement, hotbar switch, search or pickup.',
            'Coal/XP-bearing ore extraction, bamboo cells and changed foliage remain unsupported; use carried fuel or charcoal.',
            'Full original catalog is preserved. Legacy mine keeps its separate terrain-limited contract.',
            'Block absence proves removal only; no causal attribution of drops or inventory acquisition.'),
        features=('scoped-native-preflight/1','profile:mining-local-observed-v2','action:break_block'),
        bounds={'target_blocks':1,'timeout_ms':8000,'native_footprint_cells':512})
    local.update(observation_profile='player',adapter_status='implemented',
                 cancel_granularity='exact_native_action',
                 validation={'offline':'not_run','live':'not_run'})
    local['known_limits'] = local['known_limits'][:-1]
    rows.append(local)
    collect = _definition('collect_local','resources','local_controller',_COLLECT_SCHEMA,(scoped_collect,),
        prerequisites=('Negotiated collect-local-observed-v1 and same original runtime owner/context.',
            'One explicit observed plain item UUID in an adjacent cardinal cell; entire stack inventory capacity.'),
        limits=('Exactly one flat one-block movement; no search, replan, retry, jump or sprint.',
            f'Only {len(scoped_collect.ITEMS)} explicitly listed ordinary item IDs with exact default components; native target identity and stack rechecked.',
            'All other corridor entities remain excluded; unsupported entities and projectiles refuse.',
            'Only known target-absence cancellation may proceed to independent inventory verification.',
            'Stable typed inventory gain proves observed acquisition, never causal loot attribution.',
            'Input release and ownership cleanup remain required; no general physical-distance budget.'),
        features=('scoped-native-preflight/1','profile:collect-local-observed-v1','action:follow_path'),
        bounds={'target_entities':1,'route_steps':1,'native_timeout_ms':8000,'maximum_action_ticks':160,
                'pickup_observations':16,'maximum_stack_count':64})
    collect.update(adapter_status='implemented',observation_profile='entities',cancel_granularity='exact_native_action',
        validation={'offline':'not_run','live':'not_run'})
    collect['known_limits'] = collect['known_limits'][:-1]
    rows.append(collect)
    return rows


def invoke(capability, runtime, arguments, control):
    if capability == 'collect_local':
        return _invoke(capability,runtime,arguments,control,{'collect_local':_COLLECT_SCHEMA},
            {'collect_local':scoped_collect.collect_local},skill_kwargs={'control':control})
    if capability == 'mine_local':
        schema = next(row['input_schema'] for row in definitions() if row['capability'] == capability)
        return _invoke(capability, runtime, arguments, control, {capability:schema},
                       {capability:scoped_mining.mine_local})
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
