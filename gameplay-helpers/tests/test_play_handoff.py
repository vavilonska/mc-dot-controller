"""Only synthetic queue replies: bounded success is still an operator handoff."""
import contextlib
import copy
import io
import unittest

import play


class Client:
    def __init__(self, response):
        self.response = copy.deepcopy(response)
        self.commands = []
    def submit(self, command):
        self.commands.append(copy.deepcopy(command))
        return 'queue-one'
    def wait(self, identity, timeout):
        assert identity == 'queue-one'
        return self.response


class HandoffChecks(unittest.TestCase):
    def setUp(self):
        self.output = contextlib.redirect_stdout(io.StringIO())
        self.output.__enter__()
        self.addCleanup(self.output.__exit__, None, None, None)
        self.addCleanup(play.configure, None)

    def test_explicit_handoff_never_returns_recipe_success(self):
        for status in ('succeeded', 'failed', 'cancelled', 'uncertain'):
            for flag in (True, None, 0, 'true'):
                with self.subTest(status=status, flag=flag):
                    response = {'status': status, 'reason': 'bounded_end',
                                'requires_handoff': flag, 'risk_remaining': True,
                                'result': {'action': {'status': status}}}
                    client = Client(response); play.configure(client)
                    with self.assertRaisesRegex(RuntimeError, 'requires_handoff'):
                        play.run({'op': 'action', 'action': 'combat_entity'})
                    self.assertEqual(response, client.response)
                    self.assertEqual(1, len(client.commands))

    def test_observe_historical_encounter_does_not_become_new_handoff(self):
        response = {'status': 'succeeded', 'result': {'action': {'status': 'succeeded',
                    'result': {'combat': {'encounter': {'requires_handoff': True}}}}}}
        client = Client(response); play.configure(client)
        self.assertEqual(response['result'], play.run({'op': 'observe'}))
        self.assertEqual(1, len(client.commands))

    def test_legacy_success_and_error_still_have_their_original_meaning(self):
        client = Client({'status': 'succeeded', 'result': {'old': True}}); play.configure(client)
        self.assertEqual(client.response['result'], play.run({'op': 'action', 'action': 'follow_path'}))
        client = Client({'status': 'failed', 'reason': 'stuck'}); play.configure(client)
        with self.assertRaisesRegex(RuntimeError, 'stuck'):
            play.run({'op': 'action', 'action': 'follow_path'})
        self.assertEqual(1, len(client.commands))
