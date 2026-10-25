"""One stationary exact block through native admission; no terrain-age authority."""
from copy import deepcopy
from . import reach
from .core import Outcome, require

PROFILE = 'mining-local-observed-v2'
# Original placement support vocabulary is deliberately frozen independently of mining.
LEGACY_BLOCKS = ('minecraft:stone', 'minecraft:cobblestone', 'minecraft:dirt', 'minecraft:andesite',
          'minecraft:granite', 'minecraft:diorite', 'minecraft:smooth_stone', 'minecraft:stone_bricks',
          'minecraft:bricks', 'minecraft:oak_planks', 'minecraft:spruce_planks', 'minecraft:birch_planks')
LOGS = tuple('minecraft:' + name + '_log' for name in
             ('oak', 'spruce', 'birch', 'jungle', 'acacia', 'dark_oak', 'mangrove'))
ORES = ('minecraft:iron_ore', 'minecraft:deepslate_iron_ore')
BLOCKS = LEGACY_BLOCKS + LOGS + ORES


def valid_target_properties(block_id, properties):
    """Exact public target state; native registry, class and shape are still authoritative."""
    if type(properties) is not dict or block_id not in BLOCKS:
        return False
    if block_id in LOGS:
        return set(properties) == {'axis'} and type(properties['axis']) is str and properties['axis'] in ('x', 'y', 'z')
    return properties == {}



def _removed(observation, target):
    native = observation.state.get('client_action', {})
    result = native.get('result', {})
    mining = result.get('mining', {})
    return (native.get('action') == 'break_block' and native.get('status') == 'succeeded'
            and result.get('input_release_confirmed') is True
            and mining.get('profile') == PROFILE and mining.get('target') == target
            and mining.get('block_removed') is True and mining.get('input_neutral') is True
            and mining.get('unknown_outcome') is False and result.get('observed_block') == 'minecraft:air')


def mine_local(runtime, target, expected_block_id, expected_block_properties, *, require_correct_tool=True):
    """Single removal only. Tool selection, movement, drops and pickup are separate capabilities."""
    require(getattr(runtime, '_job_scoped_profiles', {}).get('break_block') == PROFILE,
            'scoped_mining_profile_not_negotiated')
    target = reach.coordinate(target)
    require(valid_target_properties(expected_block_id, expected_block_properties), 'scoped_mining_static_block_required')
    require(type(require_correct_tool) is bool, 'scoped_mining_tool_policy_invalid')
    before = runtime.observe(terrain=False)
    command = {'op':'action', 'action':'break_block', 'target':target, 'expected_block_id':expected_block_id,
               'expected_block_properties':deepcopy(expected_block_properties),
               'require_correct_tool':require_correct_tool, 'timeout_ms':8000}
    result = runtime.execute('resources.mine_local', command, lambda old,new:_removed(new,target),
                             before=before, stable_samples=2, max_samples=8)
    return Outcome(result.status,result.reason,result.request_ids,{**result.evidence,
                   'profile':PROFILE,'target':target,'scope':'one_stationary_block_removal',
                   'item_acquisition_proven':False,'causal_drop_attribution':False},result.last_observation)
