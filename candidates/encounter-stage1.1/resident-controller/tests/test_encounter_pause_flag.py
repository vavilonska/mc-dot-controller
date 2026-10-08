"""Pure codecs and fake resident only: no sockets, native game or pause inputs."""
import copy
import importlib.util
from pathlib import Path
import tempfile
import unittest

from resident_controller import encounter_contract as resident_contract
from resident_controller.controller import Resident
from resident_controller.ipc import QueueClient
from resident_controller.tasks import basic
from test_encounter_contract import EncounterBridge, body, receipt

FLAG = 'encounter_pause_on_terminal'
SOURCE = Path(__file__).resolve().parents[4]
HARNESS_PATH = SOURCE / 'test-tools/encounter-stage1.1-safety-v2/encounter_contract.py'
spec = importlib.util.spec_from_file_location('pause_flag_harness_contract', HARNESS_PATH)
harness_contract = importlib.util.module_from_spec(spec)
spec.loader.exec_module(harness_contract)


def terminal_hook(r, outcome='screen_installed'):
    return dict(hook_schema_version=1, requested=True, attempted=True,
                pause_call_attempted=outcome != 'rejected', outcome=outcome,
                pause_screen_installed=True if outcome == 'screen_installed' else None,
                already_pause_screen=False if outcome == 'screen_installed' else None,
                client_paused_observed=False if outcome == 'screen_installed' else None,
                pause_effect_confirmed=False, server_confirmed=False,
                input_release_confirmed=r['result']['input_release_confirmed'])


class PauseFlagCodec(unittest.TestCase):
    def contracts(self):
        return (resident_contract, harness_contract)

    def test_copies_have_identical_contract_source(self):
        self.assertEqual(Path(resident_contract.__file__).read_bytes(), HARNESS_PATH.read_bytes())

    def test_opt_in_or_explicit_false_preserves_entire_request_and_copy(self):
        for contract in self.contracts():
            for value in (True, False):
                with self.subTest(contract=contract.__name__, value=value):
                    b = dict(body(), **{FLAG: value})
                    validated = contract.validate_encounter_request(b)
                    self.assertEqual(validated, b)
                    self.assertIs(validated[FLAG], value)
                    validated['encounter_scope'][0]['entity_id'] = 8
                    self.assertEqual(b['encounter_scope'][0]['entity_id'], 1)
                    self.assertEqual(contract.validate_encounter_command(dict(b, op='action')), b)

    def test_default_omission_does_not_inject_flag_or_change_legacy_request(self):
        for contract in self.contracts():
            b = body()
            self.assertEqual(contract.validate_encounter_request(b), b)
            self.assertNotIn(FLAG, contract.validate_encounter_request(b))
            self.assertIsNone(contract.validate_encounter_request({'action': 'combat_entity'}))
            self.assertIsNone(contract.validate_encounter_command({'op': 'observe'}))

    def test_flag_requires_real_boolean_and_exact_mode_even_when_false(self):
        for contract in self.contracts():
            for value in (0, 1, None, 'true', 'false', [], {}, 1.0):
                with self.subTest(contract=contract.__name__, value=value), self.assertRaises(ValueError):
                    contract.validate_encounter_request(dict(body(), **{FLAG: value}))
            for value in (False, True):
                for action in ('combat_entity', 'follow_path', 'boat_drive'):
                    b = {'action': action, FLAG: value}
                    with self.subTest(contract=contract.__name__, value=value, action=action):
                        with self.assertRaises(ValueError): contract.validate_encounter_request(b)
                        with self.assertRaises(ValueError): contract.validate_encounter_command(dict(b, op='action'))
                        with self.assertRaises(ValueError): contract.validate_encounter_command(dict(b, op='observe'))

    def test_true_flag_never_relaxes_original_encounter_constraints(self):
        for contract in self.contracts():
            for change in ({'timeout_ms': 30001}, {'shield': True}, {'approach': True},
                           {'hotbar_slot': 0}, {'encounter_scope': []}, {'target_type': 'minecraft:husk'},
                           {'action': 'follow_path'}, {'encounter_mode': 'other'}):
                with self.subTest(contract=contract.__name__, change=change), self.assertRaises(ValueError):
                    contract.validate_encounter_request(dict(body(), **{FLAG: True}, **change))

    def test_true_requires_true_native_echo_for_all_statuses_but_no_pause_effect_claim(self):
        for contract in self.contracts():
            b = dict(body(), **{FLAG: True})
            for status in ('running', 'succeeded', 'failed', 'cancelled'):
                r = receipt(b, status)
                if status != 'running': r['result']['encounter_terminal_pause'] = terminal_hook(r)
                with self.subTest(contract=contract.__name__, status=status):
                    with self.assertRaises(ValueError): contract.validate_encounter_receipt(r, b)
                    for value in (False, 0, 1, None, 'true', [], {}):
                        invalid = copy.deepcopy(r)
                        invalid['result']['combat']['encounter'][FLAG] = value
                        with self.assertRaises(ValueError): contract.validate_encounter_receipt(invalid, b)
                    r['result']['combat']['encounter'][FLAG] = True
                    contract.validate_encounter_receipt(r, b)
                    self.assertNotIn('pause_effect_confirmed', r['result']['combat']['encounter'])

    def test_terminal_hook_is_mandatory_only_for_true_terminal_and_all_fields_are_typed(self):
        b = dict(body(), **{FLAG: True})
        for contract in self.contracts():
            for status in ('succeeded', 'failed', 'cancelled'):
                r = receipt(b, status)
                r['result']['combat']['encounter'][FLAG] = True
                with self.assertRaises(ValueError): contract.validate_encounter_receipt(r, b)
                hook = terminal_hook(r)
                for key in hook:
                    invalid = copy.deepcopy(r)
                    invalid['result']['encounter_terminal_pause'] = dict(hook)
                    del invalid['result']['encounter_terminal_pause'][key]
                    with self.subTest(contract=contract.__name__, status=status, missing=key), self.assertRaises(ValueError):
                        contract.validate_encounter_receipt(invalid, b)
                patches = [('hook_schema_version', True), ('hook_schema_version', 1.0), ('hook_schema_version', 2),
                           ('requested', False), ('attempted', 1), ('pause_call_attempted', 1),
                           ('outcome', 'paused'), ('pause_effect_confirmed', True), ('server_confirmed', True),
                           ('pause_screen_installed', 'true'), ('already_pause_screen', 0), ('client_paused_observed', []),
                           ('input_release_confirmed', False), ('input_release_confirmed', 1),
                           ('error_type', None), ('reason', 7)]
                for key, value in patches:
                    invalid = copy.deepcopy(r)
                    invalid['result']['encounter_terminal_pause'] = dict(hook, **{key: value})
                    with self.subTest(contract=contract.__name__, status=status, key=key, value=value), self.assertRaises(ValueError):
                        contract.validate_encounter_receipt(invalid, b)
                for key in ('pause_call_attempted', 'pause_screen_installed'):
                    invalid = copy.deepcopy(r)
                    invalid['result']['encounter_terminal_pause'] = dict(hook, **{key: False})
                    with self.assertRaises(ValueError): contract.validate_encounter_receipt(invalid, b)

    def test_hook_outcome_does_not_rewrite_original_terminal_outcome_or_claim_pause(self):
        b = dict(body(), **{FLAG: True})
        for contract in self.contracts():
            for status in ('succeeded', 'failed', 'cancelled'):
                for outcome in ('screen_installed', 'rejected', 'unconfirmed'):
                    r = receipt(b, status)
                    r['result']['combat']['encounter'][FLAG] = True
                    r['result']['encounter_terminal_pause'] = terminal_hook(r, outcome)
                    r['result']['encounter_terminal_pause'].update(reason='diagnostic', error_type='SyntheticFailure')
                    saved = copy.deepcopy(r)
                    contract.validate_encounter_receipt(r, b)
                    self.assertEqual(r, saved)
                    self.assertEqual(r['status'], status)
                    self.assertIs(r['result']['encounter_terminal_pause']['pause_effect_confirmed'], False)
            r = receipt(b, 'failed', 'input_release_unconfirmed')
            r['result']['input_release_confirmed'] = False
            r['result']['combat']['encounter'][FLAG] = True
            r['result']['encounter_terminal_pause'] = terminal_hook(r, 'unconfirmed')
            contract.validate_encounter_receipt(r, b)

    def test_old_receipts_remain_valid_and_cannot_claim_unrequested_hook(self):
        for contract in self.contracts():
            for b in (body(), dict(body(), **{FLAG: False})):
                for status in ('running', 'succeeded', 'failed', 'cancelled'):
                    r = receipt(b, status)
                    contract.validate_encounter_receipt(r, b)
                    r['result']['combat']['encounter'][FLAG] = False
                    contract.validate_encounter_receipt(r, b)
                    r['result']['combat']['encounter'][FLAG] = True
                    with self.assertRaises(ValueError): contract.validate_encounter_receipt(r, b)

    def test_resident_recipe_propagates_flag_with_original_budgets(self):
        b = dict(body(), **{FLAG: True})
        step = next(basic(dict(b, op='action', request_id='existing-id', session_id='existing-session')))
        self.assertEqual(step['body'], b)
        self.assertEqual(step['body']['timeout_ms'], 15000)


class PauseEchoBridge(EncounterBridge):
    def request(self, method, path, payload=None):
        result = super().request(method, path, payload)
        if path == '/control/action' and self.accepted.get(FLAG) is True:
            self.action['result']['combat']['encounter'][FLAG] = True
            result['result']['combat']['encounter'][FLAG] = True
        return result


class PauseFlagResident(unittest.TestCase):
    def test_fake_resident_sends_opt_in_once_and_preserves_action_id(self):
        with tempfile.TemporaryDirectory() as root:
            bridge = PauseEchoBridge()
            resident = Resident(bridge, root)
            try:
                resident.start()
                client = QueueClient(root)
                command = dict(body(), op='action', **{FLAG: True})
                request_id = client.submit(command, request_id='pause-flag-request')
                resident.tick()
                posts = [b for m, p, b in bridge.calls if m == 'POST' and p == '/control/action']
                self.assertEqual(len(posts), 1)
                self.assertIs(posts[0][FLAG], True)
                original_id = posts[0]['action_id']
                bridge.action = receipt(bridge.accepted, 'succeeded')
                bridge.action['result']['combat']['encounter'][FLAG] = True
                bridge.action['result']['encounter_terminal_pause'] = terminal_hook(bridge.action)
                for _ in range(3):
                    if resident.active: resident.active.wake_at = 0
                    resident.tick()
                self.assertEqual(client.result(request_id)['status'], 'succeeded')
                posts = [b for m, p, b in bridge.calls if m == 'POST' and p == '/control/action']
                self.assertEqual(len(posts), 1)
                self.assertEqual(posts[0]['action_id'], original_id)
                self.assertEqual(posts[0]['timeout_ms'], command['timeout_ms'])
            finally:
                resident.lock.close()

    def test_hidden_flag_is_rejected_before_any_bridge_activity(self):
        with tempfile.TemporaryDirectory() as root:
            bridge = PauseEchoBridge()
            resident = Resident(bridge, root)
            try:
                resident.start()
                client = QueueClient(root)
                before = len(bridge.calls)
                request_id = client.submit({'op': 'observe', FLAG: False})
                resident.tick()
                self.assertEqual(client.result(request_id)['status'], 'failed')
                self.assertEqual(len(bridge.calls), before)
            finally:
                resident.lock.close()


if __name__ == '__main__':
    unittest.main()
