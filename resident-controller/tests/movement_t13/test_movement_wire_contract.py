"""Production codec contracts using synthetic facts emitted by the real Java codec.

No game acceptance is implied. HTTPConnection is always an in-memory double.
"""
from copy import deepcopy
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from resident_controller.capability_snapshot import exact, validate_snapshot, validate_scoped_witness
from resident_controller.controller import action_rejection_admission
from resident_controller.movement_wire import (MARKER, ENCODING, WITNESS, REFERENCE, load_strict,
                                              retain, validate_retained, validate_delivery,
                                              valid_size_diagnostic)
from resident_controller.transport import Bridge, BridgeError


class Response:
    def __init__(self, raw, status=200):
        self.raw, self.status = raw, status
    def read(self, limit):
        return self.raw[:limit]
    def getheader(self, key):
        return None


def http_read(raw, status=200, method='GET', path='/control/capability-snapshot?radius=8'):
    bridge = Bridge('http://127.0.0.1:12345', 'synthetic-fixture-only')
    with patch('resident_controller.transport.http.client.HTTPConnection') as connect:
        connect.return_value.getresponse.return_value = Response(raw, status)
        value = bridge.request(method, path, {} if method == 'POST' else None)
    return bridge, value


def reference(bundle, name='status'):
    return bundle[name]['client_action']['result'][REFERENCE]


def authority(bundle):
    return bundle['action']['result'][WITNESS]


class MovementWireContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = Path(os.environ['MDC_MOVEMENT_WIRE_FIXTURES'])
        cls.raw = (cls.directory / 'coherent-3.json').read_bytes()
        cls.bundle = load_strict(cls.raw)
        cls.intent = load_strict((cls.directory / 'original-intent.json').read_bytes())
        cls.request = load_strict((cls.directory / 'original-request.json').read_bytes())

    def validate(self, bundle):
        decoded = validate_snapshot(bundle, 8)
        validate_scoped_witness(decoded['action'], self.request, self.intent['action_id'], self.intent)
        return decoded

    def test_actual_native_generated_counts_nulls_and_immutability(self):
        for count in (0, 3, 32, 64, 128, 180):
            raw = (self.directory / f'coherent-{count}.json').read_bytes()
            original = load_strict(raw)
            before = deepcopy(original)
            decoded = self.validate(original)
            self.assertTrue(exact(before, original))
            self.assertIsNot(decoded, original)
            witness = authority(original)
            self.assertTrue(exact(witness, decoded['state']['client_action']['result'][WITNESS]))
            movement = witness['facts']['movement']
            self.assertEqual(150, len(movement['cells']))
            self.assertEqual(count, len(movement['entity_guard']['rows']))
            for row in movement['entity_guard']['rows']:
                if not row['removed']:
                    self.assertIn('mob_target_uuid', row['flags'])
                    self.assertIsNone(row['flags']['mob_target_uuid'])
            if len(raw) <= 262144:
                bridge, parsed = http_read(raw)
                self.assertTrue(exact(parsed, original))
                self.assertEqual(raw, bridge.last_capability_wire['raw_utf8'].encode())
                validate_retained(bridge.last_capability_wire, decoded, 8)

    def test_legacy_complete_inline_retains_identity_and_behavior(self):
        raw = (self.directory / 'legacy-inline-3.json').read_bytes()
        original = load_strict(raw)
        self.assertIs(validate_snapshot(original, 8), original)
        self.validate(original)

    def test_malformed_dangling_cycle_cross_owner_and_changed_frame(self):
        changes = {
            'missing marker': lambda b: b.pop(MARKER),
            'unsupported marker': lambda b: b.update({MARKER: 'single-authority-v2'}),
            'missing authority': lambda b: b['action']['result'].pop(WITNESS),
            'inline and reference': lambda b: b['status']['client_action']['result'].update({WITNESS: deepcopy(authority(b))}),
            'extra key': lambda b: reference(b).update(extra=False),
            'bool version': lambda b: reference(b).update(schema_version=True),
            'bool generation': lambda b: reference(b).update(owner_generation=True),
            'different owner': lambda b: reference(b).update(owner_id='f' * 32),
            'different job': lambda b: reference(b).update(job_id='other-job'),
            'different session': lambda b: reference(b).update(action_session='other-session'),
            'different command': lambda b: reference(b).update(command_sha256='f' * 64),
            'different intent': lambda b: reference(b).update(submitted_intent_sha256='f' * 64),
            'different admission frame': lambda b: reference(b).update(source_nano='999999999'),
            'wrong profile': lambda b: reference(b).update(profile='movement-flat-v1'),
            'external reference': lambda b: reference(b).update(path='https://invalid.example/witness'),
            'dangling reference': lambda b: reference(b).update(path='/missing/result/scoped_native_preflight'),
            'cycle': lambda b: reference(b).update(path='/state/client_action/result/scoped_native_preflight_ref'),
            'authority chain': lambda b: b['action']['result'].update({REFERENCE: deepcopy(reference(b))}),
            'non-witness action mismatch': lambda b: b['state']['client_action'].update(ticks=123),
            'entity frame mismatch': lambda b: authority(b)['facts']['movement']['entity_guard'].update(source_tick=101),
            'entity count mismatch': lambda b: authority(b)['facts']['movement']['entity_guard'].update(enumerated_count=999),
            'cell deletion': lambda b: authority(b)['facts']['movement']['cells'].pop(),
        }
        for label, change in changes.items():
            with self.subTest(label=label):
                modified = deepcopy(self.bundle)
                change(modified)
                with self.assertRaises((ValueError, KeyError, TypeError)):
                    self.validate(modified)

    def test_real_http_parser_rejects_duplicate_keys_before_dictionary_collapse(self):
        duplicated = self.raw.replace(b'"scoped_movement_witness_encoding":',
                                      b'"scoped_movement_witness_encoding":"single-authority-v1","scoped_movement_witness_encoding":', 1)
        self.assertNotEqual(self.raw, duplicated)
        with self.assertRaises(BridgeError):
            http_read(duplicated)
        duplicated = self.raw.replace(b'"owner_generation":1', b'"owner_generation":1,"owner_generation":1', 1)
        self.assertNotEqual(self.raw, duplicated)
        with self.assertRaises(BridgeError):
            http_read(duplicated)

    def test_original_wire_and_decoded_delivery_are_separate(self):
        wire = retain(self.raw)
        decoded = self.validate(self.bundle)
        delivered = {key: deepcopy(decoded[key]) for key in ('status', 'action', 'state', 'screen', 'capability_snapshot_schema_version')}
        delivered['native_capability_wire'] = deepcopy(wire)
        validate_delivery(delivered, 8)
        self.assertEqual(self.raw, delivered['native_capability_wire']['raw_utf8'].encode())
        changed = deepcopy(delivered)
        changed['state']['client_action']['result'][WITNESS]['facts']['movement']['cells'][0]['state'] += 'changed'
        with self.assertRaises(ValueError):
            validate_delivery(changed, 8)
        for key, value in (('bytes', True), ('bytes', 262145), ('sha256', 'f' * 64), ('encoding', 'other')):
            changed = deepcopy(wire)
            changed[key] = value
            with self.assertRaises(ValueError):
                validate_retained(changed, decoded, 8)
        with self.assertRaises(ValueError):
            retain(json.dumps(decoded).encode())  # Expanded data is not original encoded provenance.

    def test_real_known_refusal_diagnostics_transport_and_receipt(self):
        raw = (self.directory / 'size-refusal.json').read_bytes()
        bridge = Bridge('http://127.0.0.1:12345', 'synthetic-fixture-only')
        with patch('resident_controller.transport.http.client.HTTPConnection') as connect:
            connect.return_value.getresponse.return_value = Response(raw, 409)
            with self.assertRaises(BridgeError) as caught:
                bridge.request('POST', '/control/scoped-action', {})
        error = caught.exception
        self.assertFalse(error.uncertain)
        self.assertEqual(409, error.status)
        receipt = action_rejection_admission(error)
        self.assertIs(receipt['admitted'], False)
        self.assertIs(receipt['uncertain'], False)
        self.assertTrue(valid_size_diagnostic(receipt['scoped_movement_response_size']))
        diagnostic = receipt['scoped_movement_response_size']
        for key in diagnostic:
            for invalid in (True, -1, 2147483648, 0.5, '0'):
                changed = deepcopy(diagnostic)
                changed[key] = invalid
                self.assertFalse(valid_size_diagnostic(changed))

    def test_synthetic_definite_refusal_has_no_witness_or_retrospective_diagnostic(self):
        # Entirely synthetic refusal, with no historical receipt or live identity.
        raw = b'{"error":"scoped_movement_response_evidence_too_large"}'
        with self.assertRaises(BridgeError) as caught:
            http_read(raw, status=409, method='POST', path='/control/scoped-action')
        error = caught.exception
        self.assertFalse(error.uncertain)
        self.assertEqual(409, error.status)
        receipt = action_rejection_admission(error)
        self.assertEqual({'schema_version': 1, 'http_status': 409, 'admitted': False,
                          'uncertain': False, 'reason': 'scoped_movement_response_evidence_too_large'}, receipt)
        self.assertNotIn('scoped_movement_response_size', receipt)
        self.assertNotIn(WITNESS, receipt)
        self.assertNotIn(REFERENCE, receipt)


if __name__ == '__main__':
    from offline_guards import offline_python
    with offline_python():
        unittest.main()
