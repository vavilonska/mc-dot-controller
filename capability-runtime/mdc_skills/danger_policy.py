"""Conservative observed danger taxonomy, deliberately not an attack allowlist.

These vanilla types include native Enemy/NeutralMob/Projectile classification
and potential attackers such as goats, killer rabbits and pufferfish. Encounter
movement conservatively treats all observed rabbits as potential attackers.
Native independently inspects live entity classes, including modded subclasses.
Adding a danger here never authorizes targeting or attacking it.
"""
import math
import re

DANGER_TYPES = frozenset('minecraft:' + name for name in (
    'zombie', 'husk', 'zombie_villager', 'skeleton', 'stray', 'bogged', 'shulker',
    'creeper', 'spider', 'cave_spider', 'enderman', 'witch', 'drowned', 'phantom',
    'slime', 'magma_cube', 'blaze', 'ghast', 'guardian', 'elder_guardian',
    'silverfish', 'endermite', 'pillager', 'vindicator', 'evoker', 'vex',
    'ravager', 'piglin', 'piglin_brute', 'zombified_piglin', 'hoglin', 'zoglin',
    'wither_skeleton', 'breeze', 'warden', 'wither', 'ender_dragon',
    'bee', 'dolphin', 'iron_golem', 'llama', 'trader_llama', 'panda',
    'polar_bear', 'wolf', 'goat', 'rabbit', 'pufferfish'))

PROJECTILE_TYPES = frozenset('minecraft:' + name for name in (
    'arrow', 'spectral_arrow', 'small_fireball', 'fireball', 'dragon_fireball',
    'shulker_bullet', 'trident', 'wither_skull', 'potion', 'snowball', 'egg',
    'ender_pearl', 'experience_bottle', 'llama_spit', 'fishing_bobber',
    'wind_charge', 'breeze_wind_charge', 'firework_rocket'))


def _nano(value):
    if (type(value) is not str or re.fullmatch(r'-?[0-9]{1,20}', value) is None
            or not -(2**63) <= int(value) < 2**63):
        raise ValueError('invalid_native_living_nano')
    return int(value)


def observed_calm_enderman(observation, row, *, pumpkin):
    """A synced client hint alone cannot establish a server mob's target state."""
    if (not pumpkin or row.get('type') != 'minecraft:enderman' or row.get('alive') is not True
            or row.get('aggressive') is not False):
        return False
    facts = row.get('native_living')
    if (not isinstance(facts, dict) or type(facts.get('schema_version')) is not int
            or facts['schema_version'] != 1 or facts.get('known') is not True
            or facts.get('source') != 'integrated_server_tick' or facts.get('reason') != 'observed'
            or facts.get('alive') is not True or facts.get('coverage_complete') is not True
            or type(facts.get('inspected')) is not int or not 1 <= facts['inspected'] <= 4096
            or type(facts.get('entity_id')) is not int
            or any(facts.get(key) != expected for key, expected in (
                ('entity_uuid', row.get('uuid')), ('entity_id', row.get('entity_id')),
                ('entity_type', row.get('type')), ('world_generation', observation.context[0]),
                ('dimension', observation.context[1]), ('player_uuid', observation.context[2])))
            or observation.player.get('uuid') != observation.context[2]
            or facts.get('aggressive') is not False or facts.get('current_target_known') is not True
            or 'current_target' not in facts or facts['current_target'] is not None):
        return False
    tick = observation.tick
    age_ms = facts.get('sample_age_ms')
    if (type(tick) is not int or tick < 0 or type(facts.get('sample_tick')) is not int
            or facts['sample_tick'] != tick or type(facts.get('source_tick')) is not int
            or facts['source_tick'] < 0 or abs(tick - facts['source_tick']) > 5
            or type(age_ms) not in (int, float) or not math.isfinite(age_ms) or not 0 <= age_ms <= 250):
        return False
    guard = observation.state.get('capability_guard')
    if (not isinstance(guard, dict) or type(guard.get('schema_version')) is not int
            or guard['schema_version'] != 1 or type(guard.get('source_tick')) is not int
            or guard['source_tick'] != tick):
        return False
    try:
        source = _nano(facts.get('source_nano'))
        sample = _nano(facts.get('sample_nano'))
        state_sample = _nano(guard.get('source_nano'))
    except ValueError:
        return False
    return (0 <= sample - source <= 250_000_000 and 0 <= sample - state_sample <= 250_000_000
            and abs(age_ms - (sample - source) / 1_000_000) <= .000001)


def danger_clearance(row, *, calm_enderman=False):
    """Return distance, exclusive boundary and reason, or no known danger.

    Missing creeper risk evidence takes the larger possible blast clearance.
    Calm endermen need both an observed calm state and worn pumpkin from caller.
    """
    kind = row['type']
    if kind == 'minecraft:enderman':
        return None if calm_enderman else (48, True, 'mob_non_target_enderman_gaze_guard')
    if kind in PROJECTILE_TYPES:
        return 5, False, 'mob_nearby_projectile'
    if kind == 'minecraft:area_effect_cloud':
        return 10, False, 'mob_nearby_effect_cloud'
    if kind == 'minecraft:creeper':
        state = row.get('creeper')
        if not isinstance(state, dict):
            return 18, False, 'mob_non_target_creeper_fuse_guard'
        known = (type(state.get('powered')) is bool and type(state.get('ignited')) is bool
                 and type(state.get('swell_ticks')) is int
                 and type(state.get('swell_direction')) is int)
        if not known:
            return 18, False, 'mob_non_target_creeper_fuse_guard'
        if state['ignited'] or state['swell_ticks'] > 0 or state['swell_direction'] > 0:
            return 18 if state['powered'] else 14, False, 'mob_non_target_creeper_fuse_guard'
    if kind in DANGER_TYPES:
        return 8, False, 'mob_non_target_threat_near'
    return None
