"""Closed data bindings over the existing guarded production runtime.

The early craft/smelt lane only uses an already-open supported menu (or the
ordinary inventory crafting grid). Opening/discovering stations is separate and
remains legacy-limited. No endpoint, callback or alternate writer is exposed.
"""
from collections import Counter
from copy import deepcopy
import hashlib
import math
from pathlib import Path

from mdc_skills import production as skills, planning
from mdc_toolbox.contracts import ToolboxError, validate_schema


def _object(properties, required=()):
    return {'type': 'object', 'properties': properties, 'required': list(required), 'additionalProperties': False}


def _integer(low, high):
    return {'type': 'integer', 'minimum': low, 'maximum': high}


def _number(low, high):
    return {'type': 'number', 'minimum': low, 'maximum': high}


def _enum(values):
    return {'type': 'string', 'enum': sorted(values)}


_ITEM = {'type': 'string', 'pattern': '^minecraft:[a-z0-9_./-]+$', 'minLength': 11, 'maxLength': 128}
_COORD = _object({'x': _integer(-30000000, 30000000), 'y': _integer(-2048, 2048),
                  'z': _integer(-30000000, 30000000)}, ('x', 'y', 'z'))
_FACE = _enum(('up', 'down', 'north', 'south', 'east', 'west'))
_RESULT = _object({
    'status': _enum(('succeeded', 'blocked', 'failed', 'cancelled', 'interrupted', 'unknown')),
    'reason': {'type': 'string', 'maxLength': 2048},
    'request_ids': {'type': 'array', 'maxItems': 32768, 'items': {'type': 'string', 'maxLength': 256}},
    'evidence': {'type': 'object'}, 'server_confirmed': {'const': False},
    'last_observation': {'type': 'object'},
}, ('status', 'reason', 'request_ids', 'evidence', 'server_confirmed'))


def _fingerprints(*modules):
    result = []
    for module in modules:
        path = Path(module.__file__)
        result.append({'path': 'capability-runtime/mdc_skills/' + path.name,
                       'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
    return result


def _definition(capability, group, level, schema, source, *, menu=False, query=False,
                prerequisites=(), limits=(), bounds=None, features=()):
    return {
        'capability': capability, 'capability_version': 1, 'group': group, 'level': level,
        'input_schema': deepcopy(schema), 'result_schema': deepcopy(_RESULT),
        'observation_profile': 'menu' if menu else 'local_terrain',
        'native_features': ['capability_guard/1', *features], 'bounds': bounds or {},
        'prerequisites': list(prerequisites), 'cancel_granularity': 'read_boundary' if query else 'native_action_boundary',
        'resume_supported': False, 'planner_available': False, 'implementation_status': 'implemented',
        'adapter_status': 'implemented' if menu else 'legacy_limited',
        'known_limits': list(limits) + ([] if menu else [
            'Current path requests legacy terrain; no scoped-native-preflight/1 acceptance is claimed.']),
        'source_fingerprints': _fingerprints(*source),
        'validation': {'offline': 'domain_contract_tests', 'live': 'not_validated_for_toolbox_v1'},
    }


_SCHEMAS = {
    'discover_workstations': _object({'station_ids': {'type': 'array', 'minItems': 1, 'maxItems': 4,
        'uniqueItems': True, 'items': _enum(skills.STATIONS)}}),
    'open_workstation': _object({'position': _COORD, 'block_id': _enum(skills.STATIONS), 'face': _FACE},
                                 ('position', 'block_id')),
    'craft': _object({'recipe_name': _enum(skills.CRAFT_RECIPES), 'batches': _integer(1, 32),
        'max_actions': _integer(1, 4096),
        'ingredients': {'type': 'object', 'minProperties': 1, 'maxProperties': 9,
            'patternProperties': {'^[A-Za-z]$': _ITEM}, 'additionalProperties': False}}, ('recipe_name',)),
    'smelt': _object({'input_id': _enum(skills.SMELTING_RECIPES), 'count': _integer(1, 32),
        'fuel_id': _enum(skills.FUELS), 'max_actions': _integer(1, 4096),
        'wait_seconds': {'type': 'number', 'exclusiveMinimum': 0, 'maximum': 600},
        'max_samples': _integer(2, 6000)}, ('input_id',)),
    'craft_nearby': _object({'recipe_name': _enum(skills.CRAFT_RECIPES), 'batches': _integer(1, 32),
        'max_actions': _integer(1, 4096)}, ('recipe_name',)),
    'smelt_nearby': _object({'input_id': _enum(skills.SMELTING_RECIPES), 'count': _integer(1, 32),
        'fuel_id': _enum(skills.FUELS), 'max_actions': _integer(1, 4096),
        'wait_seconds': {'type': 'number', 'exclusiveMinimum': 0, 'maximum': 600}}, ('input_id',)),
}
_DISPATCH = {'discover_workstations': planning.discover_workstations, 'open_workstation': skills.open_workstation,
             'craft': skills.craft, 'smelt': skills.smelt, 'craft_nearby': planning.craft_nearby,
             'smelt_nearby': planning.smelt_nearby}


def definitions():
    result = []
    for name, schema in _SCHEMAS.items():
        menu = name in ('craft', 'smelt')
        result.append(_definition(name, 'production', 'query' if name == 'discover_workstations'
            else 'bounded_composite' if name.endswith('_nearby') else 'primitive', schema,
            (skills, planning), menu=menu, query=name == 'discover_workstations',
            prerequisites=('Complete exact menu/stack fingerprints and empty cursor.',
                'Carried ingredients, output capacity and sufficient original shared action budget.'),
            limits=('Craft/smelt leave the menu open; occupied partial grid/machine state is refused, never cleaned or replayed.',
                'Recipe support does not imply an acquisition route for every ingredient.',
                'Menu-only craft/smelt do not open or search for a workstation.'),
            features=(() if name == 'discover_workstations' else ('action:interact_block',) if name == 'open_workstation' else ('action:click_slot',)),
            bounds={'batches_or_inputs': 32, 'actions_per_skill': 4096,
                    'smelting_wait_seconds': 600, 'smelting_samples': 6000}))
    for row in result:
        row['planner_available'] = row['capability'] in ('craft', 'craft_nearby', 'smelt', 'smelt_nearby')
    return result


def _validate(capability, arguments, schemas):
    if capability not in schemas:
        raise ToolboxError('unsupported_capability', 'No binding for ' + str(capability))
    validate_schema(arguments, schemas[capability])


def _invoke(capability, runtime, arguments, control, schemas, dispatch, *, skill_kwargs=None):
    _validate(capability, arguments, schemas)
    control.checkpoint()
    control.emit('capability_started', {'capability': capability})
    outcome = dispatch[capability](runtime, **deepcopy(arguments), **(skill_kwargs or {}))
    # Preserve the known result even if a stop arrives just after final semantic
    # verification. Every later semantic step is checkpointed at its admission.
    control.emit('capability_result', {'capability': capability, 'status': outcome.status,
        'reason': outcome.reason, 'request_ids': list(outcome.request_ids)})
    return outcome


def invoke(capability, runtime, arguments, control):
    return _invoke(capability, runtime, arguments, control, _SCHEMAS, _DISPATCH)


def _inventory_counts(observation):
    """Historical/planning data only; never validates dispatch freshness."""
    if observation is None:
        return None
    if hasattr(observation, 'player'):
        player = observation.player
    elif isinstance(observation, dict):
        player = observation.get('player', observation.get('state', {}).get('player', {}))
    else:
        return None
    rows = player.get('inventory')
    if not isinstance(rows, list) or player.get('inventory_truncated') is not False:
        return None
    if player.get('inventory_total') != len(rows) or len(rows) > 128:
        return None
    slots = [row.get('slot') for row in rows if isinstance(row, dict)]
    if len(slots) != len(rows) or any(type(slot) is not int for slot in slots) or len(set(slots)) != len(slots):
        return None
    totals = Counter()
    for row in rows:
        if not isinstance(row, dict) or type(row.get('count')) is not int or row['count'] < 0:
            return None
        if row['count']:
            if not isinstance(row.get('id'), str):
                return None
            totals[row['id']] += row['count']
    return totals


def plan(capability, arguments, observation=None):
    _validate(capability, arguments, _SCHEMAS)
    result = {'capability': capability, 'status': 'unavailable', 'execution_authority': False,
              'reason': 'no_read_only_planner_for_capability', 'observation_used': False}
    counts = _inventory_counts(observation)
    if capability in ('craft', 'craft_nearby'):
        name = arguments['recipe_name']; recipe = skills.CRAFT_RECIPES[name]
        batches = arguments.get('batches', 1)
        amounts = Counter(ch for row in recipe.pattern for ch in row if ch != ' ')
        selected = arguments.get('ingredients')
        if selected is not None and (set(selected) != set(recipe.ingredients)
                or any(item not in recipe.ingredients[key] for key, item in selected.items())):
            raise ToolboxError('invalid_request', 'invalid_recipe_ingredient_binding')
        needs = [{'symbol': symbol, 'count': amount * batches,
            'alternatives': list(recipe.ingredients[symbol]) if selected is None else [selected[symbol]]}
            for symbol, amount in sorted(amounts.items())]
        result.update(status='planned', reason='static_recipe_requirements', ingredients=needs,
            output={'item_id': 'minecraft:' + name, 'count': recipe.count * batches},
            requires_crafting_table=len(recipe.pattern) > 2 or max(map(len, recipe.pattern)) > 2
                or name in skills.BASE_RECIPES and name not in ('stick', 'torch', 'crafting_table'))
    elif capability in ('smelt', 'smelt_nearby'):
        recipe = skills.SMELTING_RECIPES[arguments['input_id']]; count = arguments.get('count', 1)
        fuel = arguments.get('fuel_id', 'minecraft:coal' if capability == 'smelt' else None)
        fuels = [fuel] if fuel is not None else sorted(skills.FUELS)
        result.update(status='planned', reason='static_smelting_requirements',
            ingredients=[{'item_id': recipe.input_id, 'count': count}],
            output={'item_id': recipe.output_id, 'count': count}, stations=list(recipe.stations),
            fuel_options=[{'item_id': item, 'count': math.ceil(count * recipe.furnace_ticks / skills.FUELS[item])}
                          for item in fuels])
        if counts is not None:
            result.update(observation_used=True, missing_input=max(0, count - counts[recipe.input_id]))
    return result
