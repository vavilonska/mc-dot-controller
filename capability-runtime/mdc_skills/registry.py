"""Discoverable reusable goal vocabulary. Registration never runs a game action."""
from copy import deepcopy
import inspect
import json
from .core import Outcome, require
from .scheduler import Registry, SkillSpec


def _signature(function):
    def validate(arguments):
        # JSON goals cannot smuggle arbitrary callbacks, objects or code. Each
        # actual skill adds its domain constraints before its first mutation.
        json.dumps(arguments, allow_nan=False)
        inspect.signature(function).bind(None, **arguments)
        return True
    return validate


def _unmet(observation):
    return Outcome('blocked', 'goal_not_yet_observed', (),
        {'goal_unmet': True, 'safe_to_replan': True, 'server_confirmed': False}, observation)


def default_registry():
    from . import reach, inventory, resources, production, building, threats, dimensions, planning, supply, mobility, expedition, combat_goals, construction
    registry = Registry()
    def register(name, function, description, satisfied=None):
        registry.register(SkillSpec(name, function, _signature(function), satisfied, description))
    def navigation_satisfied(runtime, goal, **_):
        p = reach.coordinate(goal)
        observation = runtime.observe(terrain=True)
        target = {'x': p['x'] + .5, 'y': p['y'], 'z': p['z'] + .5}
        if reach._arrived(observation.player, target):
            return runtime.result('navigate', (observation,), target=target)
        return _unmet(observation)
    def equipment_satisfied(runtime, item_id, *, slot):
        require(slot in inventory.EQUIPMENT, 'invalid_equipment_slot')
        observation = runtime.observe(allow_menu=True)
        if inventory._inventory_item(observation, inventory.EQUIPMENT[slot]).get('id') == item_id:
            return runtime.result('equip', (observation,), item_id=item_id, slot=slot)
        return _unmet(observation)
    register('build_with_materials', construction.build_with_materials, 'Derive blueprint materials, procure outside protected worksite, return and execute verified construction')
    register('discover_mobs', combat_goals.discover_mobs, 'Discover observed species and explicit risk prerequisites')
    register('defeat_nearby', combat_goals.defeat_nearby, 'Choose observed targets and execute species-specific bounded encounters')
    register('hunt_resource', combat_goals.hunt_resource, 'Acquire actual inventory totals from observed mob drops with bounded search')
    register('ensure_items', supply.ensure_items, 'Meet inventory totals through observed resources, tool/station prerequisites, crafting and smelting')
    register('place_workstation', supply.place_workstation, 'Place one owned workstation at an observed clear supported site')
    register('navigate_loaded', mobility.navigate_loaded, 'Replan bounded fresh loaded movement with ordinary one-block elevation changes')
    register('boat_mount', mobility.boat_mount, 'Mount the exact observed boat and verify vehicle identity')
    register('boat_dismount', mobility.boat_dismount, 'Dismount only onto verified dry supported ground')
    register('boat_travel', mobility.boat_travel, 'Continue bounded observed water segments and verify arrival')
    register('pillar_up', mobility.pillar_up, 'Place one owned full cube beneath a guarded jump')
    register('pillar_down', mobility.pillar_down, 'Mine one exact owned pillar step above observed support')
    register('bridge_step', mobility.bridge_step, 'Sneak-place one verified edge block then move onto it')
    register('gateway_pearl', mobility.gateway_pearl, 'One ordinary pearl throw with expected loaded End-gateway landing proof')
    register('end_expedition', expedition.end_expedition, 'Discover and execute bounded dragon, gateway, outer-End and shulker-box phases')
    register('deflect_shulker_bullet', expedition.deflect_shulker_bullet, 'One observed bullet interception with later removal proof')
    register('discover_workstations', planning.discover_workstations, 'Select observed local stations and safe approach stands')
    register('craft_nearby', planning.craft_nearby, 'Discover a station and carry out an explicit recipe')
    register('smelt_nearby', planning.smelt_nearby, 'Choose observed station/fuel and carry out smelting')
    register('acquire_nearby', planning.acquire_nearby, 'Select local resource blocks/tools and prove inventory goal')
    register('discover_end_goals', dimensions.discover_end_goals, 'Read-only discovery of loaded End goals and blockers')
    register('clear_observed_crystals', dimensions.clear_observed_crystals, 'Select and remove only safely actionable observed crystals')
    register('navigate', reach.navigate, 'Reach a bounded observed local goal', navigation_satisfied)
    register('interact', reach.interact, 'Interact once with an observed visible block face')
    register('close_menu', reach.close_menu, 'Close the exact current menu with empty cursor')
    register('select_hotbar', inventory.select_hotbar, 'Select and verify an existing hotbar stack')
    register('ensure_hotbar', inventory.ensure_hotbar, 'Move/select the observed required stack')
    register('equip', inventory.equip, 'Equip through verified vanilla inventory slots', equipment_satisfied)
    register('consume', inventory.consume, 'Use food/potion/milk and verify semantic effect')
    register('find_resources', resources.find, 'Find resources in a complete local terrain scan')
    register('mine', resources.mine, 'Mine the exact observed block')
    register('collect', resources.collect, 'Approach actual drops and verify inventory gain')
    register('mine_and_collect', resources.mine_and_collect, 'Mine and prove subsequent item acquisition')
    register('open_workstation', production.open_workstation, 'Open the observed vanilla station')
    register('craft', production.craft, 'Craft a supported shaped recipe with exact inventory evidence')
    register('smelt', production.smelt, 'Load fuel/input, wait for actual smelting and collect output')
    register('build', building.build, 'Execute imported exact full-cube or oriented blueprint with durable progress')
    register('engage', threats.engage, 'Bounded native combat against a supported observed hostile')
    register('strike', threats.strike, 'One guarded attack with later health loss proof')
    register('defeat', threats.defeat, 'Bounded semantic attacks against an explicit hostile')
    register('recover_hazard', threats.recover_hazard, 'Follow an observed environmental escape route')
    register('retreat', threats.retreat, 'Execute a checked short retreat from an explicit threat')
    register('ignite_nether_portal', dimensions.ignite_nether_portal, 'Ignite an observed valid portal frame')
    register('activate_end_portal', dimensions.activate_end_portal, 'Fill observed oriented frames and verify portal')
    register('enter_portal', dimensions.enter_portal, 'Enter an observed portal and prove expected dimension')
    register('remove_crystal', dimensions.remove_crystal, 'Fire one guarded crystal shot and verify loaded-area removal')
    register('open_crystal_cage', dimensions.open_crystal_cage, 'Mine selected observed cage bars within reach')
    register('wait_dragon_phase', dimensions.wait_dragon_phase, 'Read-only bounded safe dragon phase observation')
    # EndBattle accepts typed CrystalGoal inputs. A JSON-facing wrapper constructs
    # only that bounded data type rather than accepting arbitrary executable objects.
    def end_battle(runtime, dragon_uuid, *, crystals=(), **kwargs):
        require(isinstance(crystals, (list, tuple)) and len(crystals) <= 10, 'bounded_crystal_goals_required')
        goals = [dimensions.CrystalGoal(**deepcopy(c)) for c in crystals]
        return dimensions.end_battle(runtime, dragon_uuid, crystals=goals, **kwargs)
    register('end_battle', end_battle, 'Bounded crystal/cage/perched-dragon sequence with actual evidence')
    return registry
