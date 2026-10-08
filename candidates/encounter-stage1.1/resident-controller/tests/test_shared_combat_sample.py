"""Call-count and stale-ray regressions using the actual Resident loop."""
import unittest
import test_native_combat as fixture
from test_entity_aim_lock import OTHER

class SharedSampleChecks(unittest.TestCase):
    # Reuse fixtures without running inherited tests a second time.
    setUp = fixture.CombatChecks.setUp
    tearDown = fixture.CombatChecks.tearDown
    command = fixture.CombatChecks.command
    start = fixture.CombatChecks.start
    step = fixture.CombatChecks.step
    keys = fixture.CombatChecks.keys
    def test_one_state_read_per_due_combat_tick(self):
        self.start(shield=False)
        before = len(self.bridge.calls)
        self.step()
        calls = self.bridge.calls[before:]
        self.assertEqual(sum(m == 'GET' and p.startswith('/control/state?') for m,p,_ in calls), 1)
        self.assertEqual(sum(m == 'POST' and p == '/control/look' for m,p,_ in calls), 1)
    def test_read_decide_then_look_does_not_reuse_post_look_crosshair(self):
        self.start(shield=False)
        self.bridge.state['crosshair']['uuid'] = OTHER
        before = len(self.keys('key.attack'))
        self.step()
        self.assertEqual(len(self.keys('key.attack')), before)
        self.assertTrue(self.resident.combat.active)
    def test_manual_view_change_stops_before_any_combat_input(self):
        self.start(shield=False)
        self.bridge.state['player']['yaw'] += 10
        self.step()
        self.assertFalse(self.resident.combat.active)
        self.assertEqual(self.keys('key.attack'), [])
        self.assertIn('manual_view_changed', self.resident.combat.reason)
    def observed_combat(self, strength=1, using=False, reach=3, shield_cooldown=False):
        self.bridge.state['combat_observation_schema_version'] = 1
        self.bridge.state['player'].update(attack_strength=strength, using_item=using,
                entity_interaction_range=reach, shield_cooldown=shield_cooldown, blocking=False, use_ticks=0)
    def test_observed_low_cooldown_waits_even_after_wall_clock_interval(self):
        self.observed_combat(.3)
        self.start(shield=False)
        self.step(5)
        self.assertEqual(self.keys('key.attack'), [])
        self.assertEqual(self.resident.combat.status()['cadence_source'], 'observed_client_attack_strength')
    def test_observed_ready_cooldown_does_not_wait_old_fixed_weapon_delay(self):
        self.observed_combat(1)
        self.start(shield=False)
        self.resident.combat.next_attack = self.now + 10
        self.step()
        self.assertEqual(len(self.keys('key.attack')), 1)
    def test_observed_item_use_must_end_before_attack(self):
        self.observed_combat(1, using=True)
        self.start(shield=False)
        self.step()
        self.assertEqual(self.keys('key.attack'), [])
        self.assertEqual(self.resident.combat.phase, 'waiting_item_use_end')
    def test_malformed_observed_cooldown_stops_instead_of_falling_back(self):
        self.observed_combat(2)
        self.start(shield=False)
        self.step()
        self.assertFalse(self.resident.combat.active)
        self.assertEqual(self.keys('key.attack'), [])
    def test_reduced_effective_reach_is_respected(self):
        self.observed_combat(1, reach=1)
        self.start(shield=False)
        self.step()
        self.assertEqual(self.keys('key.attack'), [])
    def test_shield_cooldown_never_claims_or_requests_a_block(self):
        self.observed_combat(.2, shield_cooldown=True)
        self.start()
        self.step()
        self.assertEqual(self.keys('key.use'), [])
        self.assertFalse(self.resident.combat.status()['blocking_observed'])
