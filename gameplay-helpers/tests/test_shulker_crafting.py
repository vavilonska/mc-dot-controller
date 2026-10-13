"""New recipe through the retained main stable-result algorithm; synthetic queue only."""
import unittest
from unittest.mock import patch

import crafting_helper  # Existing portability tests deliberately reload this module.
from test_crafting_helper import FakeQueueClient, item


class ShulkerCrafting(unittest.TestCase):
    def client(self):
        return FakeQueueClient(stock={2: ('shulker_shell', 2), 19: ('chest', 1)})

    def craft(self, client):
        with patch('crafting_helper.time.sleep'):
            return crafting_helper.craft_once(client, 'shulker_box', settle_timeout=0.02)

    def outputs(self, client):
        return [c for c in client.commands if c.get('click_type') == 'quick_move']

    def test_one_box_requires_two_distinct_later_matching_ticks(self):
        client = self.client()
        result = self.craft(client)
        self.assertEqual('minecraft:shulker_box', result['item_id'])
        self.assertEqual(1, result['added'])
        self.assertEqual({'minecraft:shulker_shell': 2, 'minecraft:chest': 1}, result['consumed'])
        first, second = result['stable_game_times']
        self.assertLess(result['output_action_game_time'], first)
        self.assertLess(first, second)
        self.assertEqual('client_observed_stable', result['evidence'])
        self.assertFalse(result['server_confirmed'])
        self.assertTrue(result['grid_empty'] and result['cursor_empty'])
        self.assertEqual(1, client.quick_moves)
        self.assertEqual(1, len(self.outputs(client)))
        self.assertEqual([{'op': 'observe'}, {'op': 'observe'}], client.commands[-2:])

    def test_duplicate_final_game_tick_never_becomes_stable_or_replays_output(self):
        client = self.client()
        def freeze(queue, command, result):
            if command.get('click_type') == 'quick_move':
                queue.advance_game_time = False
        client.hook = freeze
        with self.assertRaisesRegex(crafting_helper.CraftStopped, 'not_stable_across_fresh_game_times'):
            self.craft(client)
        self.assertEqual(1, client.quick_moves)
        self.assertEqual(1, len(self.outputs(client)))
        after = client.commands.index(self.outputs(client)[0]) + 1
        self.assertTrue(all(c == {'op': 'observe'} for c in client.commands[after:]))

    def test_matching_tick_then_inventory_rollback_prevents_success(self):
        client = self.client()
        later = []
        def rollback(queue, command, result):
            if queue.quick_moves and command['op'] == 'observe':
                later.append(queue.game_time)
                if len(later) == 2:
                    for slot in queue.storage.values():
                        if queue.slots[slot]['id'] == 'minecraft:shulker_box':
                            queue.slots[slot] = item()
        client.hook = rollback
        with self.assertRaisesRegex(crafting_helper.CraftStopped, 'not_stable_across_fresh_game_times'):
            self.craft(client)
        self.assertGreaterEqual(len(later), 2)
        self.assertEqual(1, client.quick_moves)
        self.assertEqual(1, len(self.outputs(client)))

    def test_uncertain_output_preserves_original_request_and_never_retries(self):
        client = self.client()
        def uncertain(queue, command, result):
            if command.get('click_type') == 'quick_move':
                result['status'] = 'uncertain'
                result['reason'] = 'synthetic_transport_timeout'
                # The operation may already have taken effect; keep that uncertainty.
        client.hook = uncertain
        with self.assertRaisesRegex(crafting_helper.CraftStopped, 'request_uncertain') as caught:
            self.craft(client)
        self.assertEqual(1, client.quick_moves)
        self.assertEqual(1, len(self.outputs(client)))
        self.assertEqual('quick_move', client.commands[-1]['click_type'])
        self.assertEqual(caught.exception.request_ids[-1], caught.exception.request_id)
        self.assertEqual('uncertain', client.results[caught.exception.request_id]['status'])

    def test_time_regression_after_output_stops_without_another_action(self):
        client = self.client()
        def regress(queue, command, result):
            if queue.quick_moves and command['op'] == 'observe':
                queue.game_time = 0
        client.hook = regress
        with self.assertRaisesRegex(crafting_helper.CraftStopped, 'game_time_regressed'):
            self.craft(client)
        self.assertEqual(1, client.quick_moves)
        self.assertEqual([{'op': 'observe'}], client.commands[-1:])

    def test_missing_pending_count_cannot_authorize_the_new_recipe(self):
        client = self.client()
        session = client.session
        def missing():
            value = session()
            value.pop('pending')
            return value
        client.session = missing
        with self.assertRaisesRegex(crafting_helper.CraftStopped, 'session_pending_count_missing'):
            self.craft(client)
        self.assertEqual([], client.commands)

    def test_insufficient_shells_stop_before_the_first_inventory_click(self):
        client = FakeQueueClient(stock={2: ('shulker_shell', 1), 19: ('chest', 1)})
        with self.assertRaisesRegex(crafting_helper.CraftStopped, 'missing_ingredient'):
            self.craft(client)
        self.assertEqual([{'op': 'observe'}], client.commands)
        self.assertEqual(0, client.quick_moves)


if __name__ == '__main__':
    unittest.main()
