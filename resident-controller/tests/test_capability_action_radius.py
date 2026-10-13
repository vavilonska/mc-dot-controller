"""Explicit capability post-action radius reaches both Resident recipe loops."""
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from resident_controller.controller import Resident, Running
from resident_controller.tasks import basic, observe


class CapabilityActionRadiusTests(unittest.TestCase):
    def recipe(self, **fields):
        return basic({'op': 'action', 'action': 'select_hotbar', 'hotbar_slot': 1, **fields})

    def test_opt_in_step_preserves_radius(self):
        recipe = self.recipe(capability_guard={'schema_version': 1}, entity_radius=48)
        self.assertEqual(next(recipe)['step'], 'action')
        self.assertEqual(recipe.send({'status': 'succeeded'}), {'step': 'observe', 'entity_radius': 48})

    def test_legacy_step_keeps_original_default(self):
        for fields in ({}, {'entity_radius': 48}, {'capability_guard': {'schema_version': 1}}):
            recipe = self.recipe(**fields)
            next(recipe)
            self.assertEqual(recipe.send({'status': 'succeeded'}), {'step': 'observe'})

    def test_invalid_opt_in_radius_rejected_before_action_yield(self):
        for radius in (None, True, 0, 129, 48., '48'):
            with self.subTest(radius=radius), self.assertRaisesRegex(ValueError, 'entity_radius_1_to_128'):
                next(self.recipe(capability_guard={'schema_version': 1}, entity_radius=radius))

    def test_step_observation_validates_before_bridge_read(self):
        resident = Resident.__new__(Resident)
        resident.bridge, resident.cache = object(), SimpleNamespace(observe=Mock(return_value={'state': 'ok'}))
        for radius in (None, True, 0, 129, 48., '48'):
            with self.subTest(radius=radius), self.assertRaisesRegex(ValueError, 'entity_radius_1_to_128'):
                resident.observe_recipe_step({'step': 'observe', 'entity_radius': radius})
        resident.cache.observe.assert_not_called()
        resident.observe_recipe_step(observe())
        resident.cache.observe.assert_called_once_with(resident.bridge)
        resident.observe_recipe_step(observe(entity_radius=48))
        resident.cache.observe.assert_called_with(resident.bridge, entity_radius=48)

    def test_coordinated_loop_uses_same_bounded_observation_step(self):
        resident = Resident.__new__(Resident)
        resident.bridge = object()
        resident.cache = SimpleNamespace(observe=Mock(return_value={'observation': 'wide'}))
        resident.coordination_context = Mock(return_value=('same-context',))
        recipe = iter([{'step': 'observe', 'entity_radius': 48}])
        class Recipe:
            def send(self, response):
                return next(recipe)
        task = Running({}, Recipe())
        resident.advance_coordination(task)
        resident.cache.observe.assert_called_once_with(resident.bridge, entity_radius=48)
        self.assertEqual(task.response, {'observation': 'wide'})


if __name__ == '__main__':
    unittest.main()
