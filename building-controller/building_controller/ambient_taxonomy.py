"""Pinned vanilla 1.21.1 distant-living taxonomy, never a general mob allowlist.

Each entry is an exact registry ID AND concrete Java class, with a reviewed
goal/brain inheritance chain. See validation/passive-ambient-taxonomy for the
pinned bytecode, registry constructor bindings, prey tags, and exclusions.
"Passive" means no vanilla player attack path under the stated server guard;
predators still require a known null current target. Neither Animal inheritance
nor the minecraft namespace is an admission rule. Unknown types fail closed.

This table supplies only the species proof. The caller must retain every native
living, timing, identity, health, velocity, raw-scan and whole-envelope gate.
"""
from dataclasses import dataclass
from types import MappingProxyType


@dataclass(frozen=True)
class PassiveLivingKind:
    exact_class: str
    family: str
    evidence: str
    server_guard: str = "none"
    clearance: int = 8
    # Absence never accepts a row. It may justify bounded NEW reads while idle.
    # Rabbit's dangerous variant and persistent attack goals cannot be proved
    # absent when its source row is missing, so it deliberately cannot wait.
    source_absence_reacquirable: bool = True


def _kind(java_class, family, evidence, **kwargs):
    return PassiveLivingKind("net.minecraft.world.entity." + java_class,
                             family, evidence, **kwargs)


PASSIVE_LIVING_TYPES = MappingProxyType({
    "minecraft:pig": _kind("animal.Pig", "farm", "farm_goals"),
    "minecraft:cow": _kind("animal.Cow", "farm", "farm_goals"),
    "minecraft:mooshroom": _kind("animal.MushroomCow", "farm", "cow_inheritance"),
    "minecraft:chicken": _kind("animal.Chicken", "farm", "farm_goals"),
    "minecraft:sheep": _kind("animal.Sheep", "farm", "farm_goals"),
    "minecraft:horse": _kind("animal.horse.Horse", "equine", "horse_inheritance"),
    "minecraft:donkey": _kind("animal.horse.Donkey", "equine", "horse_inheritance"),
    "minecraft:mule": _kind("animal.horse.Mule", "equine", "horse_inheritance"),
    "minecraft:zombie_horse": _kind("animal.horse.ZombieHorse", "equine", "horse_inheritance"),
    "minecraft:camel": _kind("animal.camel.Camel", "equine", "camel_brain"),
    "minecraft:bat": _kind("ambient.Bat", "ambient", "bat_inheritance"),
    "minecraft:parrot": _kind("animal.Parrot", "ambient", "parrot_goals"),
    "minecraft:turtle": _kind("animal.Turtle", "land_water", "turtle_goals"),
    "minecraft:sniffer": _kind("animal.sniffer.Sniffer", "land", "sniffer_brain"),
    "minecraft:armadillo": _kind("animal.armadillo.Armadillo", "land", "armadillo_brain"),
    "minecraft:allay": _kind("animal.allay.Allay", "ambient", "allay_brain"),
    "minecraft:strider": _kind("monster.Strider", "land", "strider_goals"),
    "minecraft:cod": _kind("animal.Cod", "aquatic", "schooling_fish_inheritance"),
    "minecraft:salmon": _kind("animal.Salmon", "aquatic", "schooling_fish_inheritance"),
    "minecraft:tropical_fish": _kind("animal.TropicalFish", "aquatic", "schooling_fish_inheritance"),
    "minecraft:squid": _kind("animal.Squid", "aquatic", "squid_goals"),
    "minecraft:glow_squid": _kind("GlowSquid", "aquatic", "squid_inheritance"),
    "minecraft:tadpole": _kind("animal.frog.Tadpole", "aquatic", "tadpole_brain"),
    "minecraft:cat": _kind("animal.Cat", "nonplayer_predator", "cat_targets"),
    "minecraft:ocelot": _kind("animal.Ocelot", "nonplayer_predator", "ocelot_targets"),
    "minecraft:bee": _kind("animal.Bee", "guarded_neutral", "bee_anger",
                           server_guard="bee", clearance=12),
    "minecraft:rabbit": _kind("animal.Rabbit", "guarded_variant", "rabbit_variant_and_goals",
                              server_guard="rabbit", source_absence_reacquirable=False),
})
