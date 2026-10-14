"""Real Java codec bytes with declared synthetic facts, not live-game evidence."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import unittest

from resident_controller.capability_snapshot import exact, validate_scoped_witness, validate_snapshot
from resident_controller.movement_wire import (
    MARKER, REFERENCE, WITNESS, WIRE_LIMIT, decode, load_strict, retain, validate_retained,
)


class NativeCombinedWireTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        location = os.environ.get('MDC_NATIVE_WIRE_DIR')
        if not location:
            raise unittest.SkipTest('Supply actual Java-emitted combined-wire files via the bounded runner')
        cls.directory = Path(location).resolve()
        cls.raw = {}
        for profile in ('collect', 'combat'):
            for suffix in ('standalone', 'coherent', 'request', 'intent'):
                name = f'{profile}-{suffix}.json'
                raw = (cls.directory / name).read_bytes()
                if not 0 < len(raw) <= WIRE_LIMIT:
                    raise ValueError('Native input exceeds the original wire bound: ' + name)
                cls.raw[name] = raw
        cls.hashes = {name: hashlib.sha256(raw).hexdigest() for name, raw in cls.raw.items()}
        print(json.dumps({'original_java_inputs': cls.hashes,
                          'scope': 'Actual production Java serialization with synthetic captured facts'}), flush=True)

    @classmethod
    def tearDownClass(cls):
        for name, original in cls.raw.items():
            if (cls.directory / name).read_bytes() != original:
                raise AssertionError('Native input file changed during validation: ' + name)

    def parsed(self, profile, suffix):
        return load_strict(self.raw[f'{profile}-{suffix}.json'])

    def validated(self, profile, action):
        scope, intent = self.parsed(profile, 'request'), self.parsed(profile, 'intent')
        before = deepcopy(action)
        witness = validate_scoped_witness(action, scope, intent['action_id'], intent)
        self.assertTrue(exact(action, before), 'Production validation must not repair original wire facts')
        self.assertEqual(witness['profile'], scope['profile'])
        self.assertTrue(witness['coverage_complete'])
        return witness

    def test_collect_original_standalone_consumes_exact_native_bytes(self):
        native = self.parsed('collect', 'standalone')
        witness = self.validated('collect', native)
        self.assertEqual(witness['profile'], 'collect-local-observed-v1')
        self.assertEqual(native['action'], 'follow_path')
        self.assertNotIn(MARKER, native)

    def test_collect_coherent_decodes_and_retains_original_bytes(self):
        raw = self.raw['collect-coherent.json']
        encoded = self.parsed('collect', 'coherent')
        before = deepcopy(encoded)
        self.assertIn(MARKER, encoded)
        for name in ('state', 'status'):
            result = encoded[name]['client_action']['result']
            self.assertIn(REFERENCE, result)
            self.assertNotIn(WITNESS, result)
        semantic = validate_snapshot(encoded, 8)
        self.assertTrue(exact(encoded, before))
        self.assertTrue(exact(semantic, decode(before)))
        native = self.parsed('collect', 'standalone')
        self.assertTrue(exact(self.validated('collect', semantic['action']), self.validated('collect', native)))
        provenance = retain(raw)
        self.assertEqual(provenance['sha256'], self.hashes['collect-coherent.json'])
        self.assertEqual(provenance['raw_utf8'].encode('utf-8'), raw)
        self.assertTrue(exact(validate_retained(provenance, semantic, 8), semantic))

    def test_combat_original_standalone_consumes_exact_native_bytes(self):
        native = self.parsed('combat', 'standalone')
        witness = self.validated('combat', native)
        self.assertEqual(witness['profile'], 'combat-local-observed-v1')
        self.assertEqual(native['action'], 'combat_entity')
        self.assertNotIn(MARKER, native)

    def test_combat_coherent_preserves_current_inline_contract(self):
        encoded = self.parsed('combat', 'coherent')
        before = deepcopy(encoded)
        self.assertNotIn(MARKER, encoded)
        self.assertIs(decode(encoded), encoded)
        semantic = validate_snapshot(encoded, 8)
        witness = self.validated('combat', semantic['action'])
        self.assertTrue(exact(witness, self.validated('combat', self.parsed('combat', 'standalone'))))
        for name in ('state', 'status'):
            self.assertTrue(exact(witness, semantic[name]['client_action']['result'][WITNESS]))
            self.assertNotIn(REFERENCE, semantic[name]['client_action']['result'])
        self.assertTrue(exact(encoded, before))

    def test_collect_explicit_null_and_projection_negatives(self):
        native = self.parsed('collect', 'standalone')
        rows = native['result'][WITNESS]['facts']['movement']['entity_guard']['rows']
        self.assertTrue(rows)
        for row in rows:
            self.assertIn('mob_target_uuid', row['flags'])
            self.assertIsNone(row['flags']['mob_target_uuid'])
        for mutation in ('missing_null', 'moving_target', 'bad_projection'):
            invalid = deepcopy(native)
            row = invalid['result'][WITNESS]['facts']['movement']['entity_guard']['rows'][0]
            if mutation == 'missing_null':
                del row['flags']['mob_target_uuid']
            elif mutation == 'moving_target':
                row['velocity'][0] = .1
            else:
                row['projected_aabb'][0] += 1
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                self.validated('collect', invalid)

    def test_collect_malformed_reference_negatives(self):
        original = self.parsed('collect', 'coherent')
        for mutation in ('missing_marker', 'wrong_owner', 'wrong_path', 'inline_duplicate'):
            invalid = deepcopy(original)
            result = invalid['state']['client_action']['result']
            if mutation == 'missing_marker':
                del invalid[MARKER]
            elif mutation == 'wrong_owner':
                result[REFERENCE]['owner_generation'] += 1
            elif mutation == 'wrong_path':
                result[REFERENCE]['path'] = '/state/other'
            else:
                result[WITNESS] = deepcopy(invalid['action']['result'][WITNESS])
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                validate_snapshot(invalid, 8)

    def test_profiles_and_combat_target_cannot_be_cross_bound(self):
        for profile, other in (('collect', 'combat'), ('combat', 'collect')):
            native = self.parsed(profile, 'standalone')
            intent = self.parsed(profile, 'intent')
            with self.subTest(profile=profile), self.assertRaises(ValueError):
                validate_scoped_witness(native, self.parsed(other, 'request'), intent['action_id'], intent)
        invalid = self.parsed('combat', 'standalone')
        invalid['result'][WITNESS]['facts']['combat']['target_uuid'] = '55555555-5555-4555-8555-555555555555'
        with self.assertRaises(ValueError):
            self.validated('combat', invalid)
        invalid = self.parsed('combat', 'coherent')
        invalid['state']['client_action']['action_id'] = 'different-action'
        with self.assertRaises(ValueError):
            validate_snapshot(invalid, 8)

    def test_strict_raw_parser_rejects_duplicate_keys_and_nonfinite_numbers(self):
        # Only negative copies are changed; acceptance always reads original bytes.
        raw = self.raw['collect-standalone.json']
        start = raw.index(b'{')
        for extra in (b'"negative":1,"negative":2,', b'"negative":NaN,'):
            with self.assertRaises(ValueError):
                load_strict(raw[:start + 1] + extra + raw[start + 1:])
