"""Offline exhaustive taxonomy contracts; synthetic data proves no live safety."""
from copy import deepcopy
from dataclasses import FrozenInstanceError
import unittest

from building_controller.ambient_entities import (
    Box, classify_ambient_entities, reacquirable_entity_absence)
from building_controller.ambient_taxonomy import PASSIVE_LIVING_TYPES
from building_controller.model import Pos
from building_controller.terrain import state_blockers
from tests.helpers import terrain
from tests.test_ambient_entities import CONTEXT, entity, policy, sample


# Independent expected registry IDs, exact classes and adult dimensions, checked
# against the pinned EntityType constructor bootstraps, not copied at runtime
# from the production taxonomy. The observed AABB remains authoritative.
EXPECTED = {
    "pig": ("animal.Pig", .9, .9),
    "cow": ("animal.Cow", .9, 1.4),
    "mooshroom": ("animal.MushroomCow", .9, 1.4),
    "chicken": ("animal.Chicken", .4, .7),
    "sheep": ("animal.Sheep", .9, 1.3),
    "horse": ("animal.horse.Horse", 1.3964844, 1.6),
    "donkey": ("animal.horse.Donkey", 1.3964844, 1.5),
    "mule": ("animal.horse.Mule", 1.3964844, 1.6),
    "zombie_horse": ("animal.horse.ZombieHorse", 1.3964844, 1.6),
    "camel": ("animal.camel.Camel", 1.7, 2.375),
    "bat": ("ambient.Bat", .5, .9),
    "parrot": ("animal.Parrot", .5, .9),
    "turtle": ("animal.Turtle", 1.2, .4),
    "sniffer": ("animal.sniffer.Sniffer", 1.9, 1.75),
    "armadillo": ("animal.armadillo.Armadillo", .7, .65),
    "allay": ("animal.allay.Allay", .35, .6),
    "strider": ("monster.Strider", .9, 1.7),
    "cod": ("animal.Cod", .5, .3),
    "salmon": ("animal.Salmon", .7, .4),
    "tropical_fish": ("animal.TropicalFish", .5, .4),
    "squid": ("animal.Squid", .8, .8),
    "glow_squid": ("GlowSquid", .8, .8),
    "tadpole": ("animal.frog.Tadpole", .4, .3),
    "cat": ("animal.Cat", .6, .7),
    "ocelot": ("animal.Ocelot", .6, .7),
    "bee": ("animal.Bee", .7, .6),
    "rabbit": ("animal.Rabbit", .4, .5),
}


def living(kind, *, x=24., ident=11, scale=1.):
    row = entity("sheep", x=x, ident=ident)
    java_class, width, height = EXPECTED[kind]
    width *= scale; height *= scale
    row.update(type="minecraft:" + kind, **{"class": "net.minecraft.world.entity." + java_class},
               bounding_box={"min": {"x": x-width/2, "y": 64., "z": -width/2},
                             "max": {"x": x+width/2, "y": 64.+height, "z": width/2}})
    facts = row["native_living"]
    facts["entity_type"] = row["type"]
    if kind == "bee":
        facts["bee"] = dict(angry=False, remaining_anger_ticks=0, persistent_anger_target_uuid=None)
    if kind == "rabbit":
        facts["rabbit"] = dict(variant_id=0, killer_bunny=False, passive_goals_verified=True)
    return row


def missing_source(row):
    row = deepcopy(row)
    keys = ("schema_version", "entity_uuid", "entity_id", "entity_type", "dimension",
            "world_generation", "player_uuid", "coverage_complete", "inspected")
    facts = {key: row["native_living"][key] for key in keys}
    facts.update(known=False, source="unavailable", reason="entity_not_observed", current_target_known=False)
    row["native_living"] = facts
    return row


class PassiveAmbientTaxonomyTests(unittest.TestCase):
    def report(self, row):
        state = sample([row]); state["nearby"]["radius"] = 48.
        return classify_ambient_entities(state, policy())

    def test_every_registry_id_and_exact_class_is_independently_enumerated(self):
        self.assertEqual(set(PASSIVE_LIVING_TYPES), {"minecraft:"+kind for kind in EXPECTED})
        for kind, (java_class, _, _) in EXPECTED.items():
            with self.subTest(kind=kind):
                self.assertEqual(PASSIVE_LIVING_TYPES["minecraft:"+kind].exact_class,
                                 "net.minecraft.world.entity."+java_class)
                row = living(kind); before = deepcopy(row); report = self.report(row)
                self.assertTrue(report.ok, report.blockers)
                self.assertIs(report.raw_entities[0], row)
                self.assertEqual(row, before)

    def test_table_and_entries_are_immutable_not_caller_options(self):
        with self.assertRaises(TypeError): PASSIVE_LIVING_TYPES["minecraft:wolf"] = None
        with self.assertRaises(FrozenInstanceError):
            PASSIVE_LIVING_TYPES["minecraft:pig"].exact_class = "mod.Pig"

    def test_every_species_rejects_class_spoof_mod_namespace_and_unknown_type(self):
        for kind in EXPECTED:
            for change in (lambda r:r.update(**{"class":"mod.CustomPassive"}),
                           lambda r:r.update(**{"class":"net.minecraft.world.entity.animal.Animal"}),
                           lambda r:r.update(type="mod:"+kind),
                           lambda r:r.update(type="minecraft:unreviewed_passive")):
                row = living(kind); change(row)
                with self.subTest(kind=kind, row_type=row["type"], java_class=row["class"]):
                    self.assertFalse(self.report(row).ok)
                    self.assertIsNone(reacquirable_entity_absence(sample([row]), policy()))

    def test_every_species_requires_native_identity_health_freshness_and_calm(self):
        mutations = {
            "no_native": lambda r:r.pop("native_living"),
            "unknown": lambda r:r["native_living"].update(known=False),
            "source": lambda r:r["native_living"].update(source="client_guess"),
            "identity": lambda r:r["native_living"].update(entity_uuid=CONTEXT[2]),
            "type_binding": lambda r:r["native_living"].update(entity_type="minecraft:zombie"),
            "world_binding": lambda r:r["native_living"].update(world_generation=CONTEXT[2]),
            "stale": lambda r:r["native_living"].update(sample_age_ms=251.),
            "clock": lambda r:r["native_living"].update(source_nano="1000000001"),
            "tick": lambda r:r["native_living"].update(sample_tick=101),
            "coverage": lambda r:r["native_living"].update(coverage_complete=False),
            "aggressive": lambda r:r["native_living"].update(aggressive=True),
            "aggressive_unknown": lambda r:r["native_living"].pop("aggressive"),
            "target_unknown": lambda r:r["native_living"].update(current_target_known=False),
            "target_missing": lambda r:r["native_living"].pop("current_target"),
            "target_player": lambda r:r["native_living"].update(current_target={"uuid":CONTEXT[2]}),
            "target_prey": lambda r:r["native_living"].update(current_target={"type":"minecraft:chicken"}),
            "dead": lambda r:r.update(health=0),
            "hurt": lambda r:r.update(hurt_time=1),
            "using_item": lambda r:r.update(using_item=True),
        }
        for kind in EXPECTED:
            for name, change in mutations.items():
                row = living(kind); change(row)
                with self.subTest(kind=kind, mutation=name):
                    self.assertFalse(self.report(row).ok)
                    self.assertIsNone(reacquirable_entity_absence(sample([row]), policy()))

    def test_every_species_retains_body_motion_full_envelope_and_48_scan_checks(self):
        for kind in EXPECTED:
            with self.subTest(kind=kind):
                row = living(kind)
                row["velocity"]["x"] = .350001
                self.assertFalse(self.report(row).ok)
                row = living(kind); row.pop("bounding_box")
                self.assertFalse(self.report(row).ok)
                row = living(kind); row["bounding_box"]["max"]["x"] += 1
                self.assertFalse(self.report(row).ok)
                self.assertFalse(self.report(living(kind, x=6.)).ok)
                state = sample([living(kind)])
                full_work = Box((20, 63, -2), (30, 68, 2))
                self.assertFalse(classify_ambient_entities(state, policy(full_work)).ok)
                self.assertFalse(classify_ambient_entities(state, policy(), additional_boxes=(full_work,)).ok)
                state["nearby"]["radius"] = 48.
                self.assertTrue(classify_ambient_entities(state, policy()).ok)
                state["nearby"]["truncated"] = True
                self.assertFalse(classify_ambient_entities(state, policy()).ok)
                state["nearby"].update(truncated=False, radius=20.)
                self.assertFalse(classify_ambient_entities(state, policy()).ok)

    def test_baby_geometry_is_observed_and_near_body_cannot_use_center_only(self):
        for kind in ("pig", "cow", "mooshroom", "chicken", "sheep", "horse", "donkey", "mule",
                     "camel", "turtle", "sniffer", "armadillo", "strider", "cat", "ocelot", "bee", "rabbit"):
            with self.subTest(kind=kind):
                self.assertTrue(self.report(living(kind, scale=.5)).ok)
        # Both origins are >8 from the work box. Only the smaller AABB clears it.
        self.assertFalse(self.report(living("pig", x=12.3)).ok)
        self.assertTrue(self.report(living("pig", x=12.3, scale=.5)).ok)

    def test_all_six_normal_rabbit_variants_need_complete_independent_goal_proof(self):
        for variant in range(6):
            row = living("rabbit"); row["native_living"]["rabbit"]["variant_id"] = variant
            self.assertTrue(self.report(row).ok)
        changes = [dict(variant_id=v) for v in (-1, 6, 99, 100, True, 0., "0", None)]
        changes += [dict(killer_bunny=v) for v in (True, 0, None)]
        changes += [dict(passive_goals_verified=v) for v in (False, 1, None)]
        for change in changes:
            row = living("rabbit"); row["native_living"]["rabbit"].update(change)
            with self.subTest(change=change): self.assertFalse(self.report(row).ok)
        for field in ("variant_id", "killer_bunny", "passive_goals_verified"):
            row = living("rabbit"); row["native_living"]["rabbit"].pop(field)
            self.assertFalse(self.report(row).ok)
        row = living("rabbit"); row["native_living"].pop("rabbit")
        self.assertFalse(self.report(row).ok)
        # EVIL -> normal can retain melee/retaliation goals; normal ID alone is insufficient.
        row = living("rabbit"); row["native_living"]["rabbit"]["passive_goals_verified"] = False
        self.assertFalse(self.report(row).ok)

    def test_exact_source_absence_uses_same_table_but_never_accepts_unknown_rabbit(self):
        for kind in EXPECTED:
            row = missing_source(living(kind)); state = sample([row]); before = deepcopy(state)
            with self.subTest(kind=kind):
                report = classify_ambient_entities(state, policy())
                self.assertFalse(report.ok)
                evidence = reacquirable_entity_absence(state, policy())
                if kind == "rabbit":
                    self.assertIsNone(evidence)
                else:
                    self.assertIsNotNone(evidence)
                    self.assertIs(evidence["observation_accepted"], False)
                    self.assertEqual(evidence["missing_entities"][0]["type"], "minecraft:"+kind)
                self.assertEqual(state, before)
                row = missing_source(living(kind, x=6.))
                self.assertIsNone(reacquirable_entity_absence(sample([row]), policy()))

    def test_known_neutral_hostile_projectile_and_tag_dependent_predators_stay_blocked(self):
        excluded = {"wolf":"animal.Wolf", "polar_bear":"animal.PolarBear", "llama":"animal.horse.Llama",
            "trader_llama":"animal.horse.TraderLlama", "goat":"animal.goat.Goat", "panda":"animal.Panda",
            "dolphin":"animal.Dolphin", "fox":"animal.Fox", "pufferfish":"animal.Pufferfish",
            "skeleton_horse":"animal.horse.SkeletonHorse", "frog":"animal.frog.Frog",
            "axolotl":"animal.axolotl.Axolotl", "iron_golem":"animal.IronGolem",
            "snow_golem":"animal.SnowGolem", "villager":"npc.Villager", "wandering_trader":"npc.WanderingTrader",
            "zombie":"monster.Zombie", "creeper":"monster.Creeper", "enderman":"monster.EnderMan",
            "arrow":"projectile.Arrow", "fireball":"projectile.LargeFireball"}
        for kind, java_class in excluded.items():
            row = living("pig", x=47.)
            row.update(type="minecraft:"+kind, **{"class":"net.minecraft.world.entity."+java_class})
            row["native_living"]["entity_type"] = row["type"]
            with self.subTest(kind=kind):
                self.assertEqual(self.report(row).classifications[0].reason, "unsupported_entity_type_or_class")
                self.assertIsNone(reacquirable_entity_absence(sample([missing_source(row)]), policy()))

    def test_generic_builder_default_is_still_strict_for_every_admitted_species(self):
        for kind in EXPECTED:
            state = sample([living(kind)])
            with self.subTest(kind=kind):
                self.assertIn("entities_present_or_scan_incomplete", state_blockers(state, terrain(), [Pos(2,64,2)]))
                self.assertEqual(state_blockers(state, terrain(), [Pos(2,64,2)], ambient_policy=policy()), [])

    def test_passive_mount_does_not_hide_a_threat_passenger_or_any_raw_row(self):
        mount = living("chicken"); mount["passenger_count"] = 1
        rider = living("pig", ident=12)
        rider.update(type="minecraft:zombie", **{"class":"net.minecraft.world.entity.monster.Zombie"})
        rider["native_living"]["entity_type"] = rider["type"]
        rows = [mount, rider]; state = sample(rows); before = deepcopy(state)
        report = classify_ambient_entities(state, policy())
        self.assertFalse(report.ok)
        self.assertEqual(report.raw_entities, tuple(rows))
        self.assertIs(report.raw_entities[0], mount)
        self.assertIs(report.raw_entities[1], rider)
        self.assertEqual(report.classifications[1].reason, "unsupported_entity_type_or_class")
        self.assertEqual(state, before)
        mount["native_living"] = missing_source(mount)["native_living"]
        self.assertIsNone(reacquirable_entity_absence(state, policy()))


if __name__ == "__main__":
    unittest.main()
