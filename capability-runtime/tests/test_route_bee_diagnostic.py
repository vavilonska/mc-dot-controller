"""Refusal facts remain bounded, profile-bound, non-authoritative and unreplayed."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest

from mdc_skills.core import Runtime
from resident_controller.capability_snapshot import validate_scoped_witness, validate_snapshot, exact
from resident_controller.movement_wire import retain, validate_retained
from resident_controller.controller import action_rejection_admission
from resident_controller.route_spatial_stop_snapshot import valid_rejection_diagnostic, PROFILE as V1_PROFILE, POLICY as V1_POLICY
from resident_controller.route_bee_diagnostic import REASONS, READ_STATUSES, valid_native_bee_diagnostic
from resident_controller.transport import BridgeError
from bee_diagnostic_fixture import diagnostic_fixture, canonical_fixture, request_fixture
from spatial_stop_v2_fixture import terminal, witness
from support_core import Clock, Client, move, arrived
import test_route_spatial_stop_contract as transport_fixture


def encode(diagnostic, code=None):
    return json.dumps({'error':code or diagnostic['rejection_code'], 'route_entity_rejection':diagnostic},
                      separators=(',', ':'), allow_nan=False).encode()


class BeeDiagnosticSchemaTests(unittest.TestCase):
    def test_each_object_is_exact_and_every_field_required(self):
        d = diagnostic_fixture()
        self.assertTrue(valid_rejection_diagnostic(d))
        self.assertTrue(valid_native_bee_diagnostic(d['native_bee_diagnostic']))
        paths = [(), ('native_bee_diagnostic',)] + [('native_bee_diagnostic', k) for k in ('entity', 'native', 'route', 'source', 'context')]
        for path in paths:
            original = d
            for k in path: original = original[k]
            for missing in tuple(original) + ('extra',):
                bad = deepcopy(d); target = bad
                for k in path: target = target[k]
                if missing == 'extra': target[missing] = False
                else: del target[missing]
                with self.subTest(path=path, missing=missing): self.assertFalse(valid_rejection_diagnostic(bad))
            for replacement in (None, [], True, 'unknown'):
                bad = deepcopy(d)
                if not path: bad = replacement
                else:
                    target = bad
                    for k in path[:-1]: target = target[k]
                    target[path[-1]] = replacement
                with self.subTest(path=path, replacement=replacement): self.assertFalse(valid_rejection_diagnostic(bad))

    def test_legacy_shapes_unchanged_and_extension_requires_exact_v2(self):
        d = diagnostic_fixture(); old = {k:v for k,v in d.items() if k != 'native_bee_diagnostic'}
        old['schema_version'] = 1
        self.assertTrue(valid_rejection_diagnostic(old))
        for changes in ({'schema_version':1}, {'schema_version':True}, {'schema_version':3},
                {'profile':V1_PROFILE}, {'profile':V1_PROFILE, 'policy':V1_POLICY}, {'entity_type':'minecraft:cow'},
                {'phase':'unknown'}, {'phase':'state'}, {'phase':'enumeration'},
                {'rejection_code':'arbitrary'}, {'exception_type':'error text'}):
            with self.subTest(changes=changes): self.assertFalse(valid_rejection_diagnostic({**d, **changes}))
        self.assertFalse(valid_rejection_diagnostic({**old, 'schema_version':2}))
        old.update(profile=V1_PROFILE, policy=V1_POLICY, rejection_code='route_stop_entity_state_unknown')
        self.assertTrue(valid_rejection_diagnostic(old))

    def test_native_reason_and_route_status_are_closed_untruncated_enums(self):
        for key, allowed, obj in (('reason', REASONS, 'native'), ('read_status', READ_STATUSES, 'route')):
            for value in allowed:
                d = diagnostic_fixture(); d['native_bee_diagnostic'][obj][key] = value
                self.assertTrue(valid_rejection_diagnostic(d))
            for value in ('', 'arbitrary error with private fields', 'x'*8192, True, None, [], {}):
                d = diagnostic_fixture(); d['native_bee_diagnostic'][obj][key] = value
                with self.subTest(obj=obj, value=repr(value)[:80]): self.assertFalse(valid_rejection_diagnostic(d))

    def test_typed_signed_bounds_without_bool_integer_coercion(self):
        fields = [('entity', 'id', -(2**31), 2**31-1), ('native', 'inspected', 0, 4097),
                  ('native', 'sample_tick', -(2**63), 2**63-1), ('native', 'source_tick', -(2**63), 2**63-1),
                  ('context', 'client_tick', -(2**63), 2**63-1)]
        for obj, key, lo, hi in fields:
            for value in (lo, hi):
                d = diagnostic_fixture(); d['native_bee_diagnostic'][obj][key] = value
                self.assertTrue(valid_rejection_diagnostic(d))
            for value in (lo-1, hi+1, True, 1., '1', [], {}):
                d = diagnostic_fixture(); d['native_bee_diagnostic'][obj][key] = value
                with self.subTest(obj=obj, key=key, value=value): self.assertFalse(valid_rejection_diagnostic(d))
        for obj, keys in (('native', ('present', 'known', 'coverage_complete')), ('route', ('present', 'captured')),
                ('source', ('context_current', 'batch_present', 'batch_context_matches', 'row_present', 'row_identity_matches'))):
            for key in keys:
                for value in (0, 1, 'true'):
                    d = diagnostic_fixture(); d['native_bee_diagnostic'][obj][key] = value
                    self.assertFalse(valid_rejection_diagnostic(d))
        for value in (True, 128., 127, 129, None):
            d = diagnostic_fixture(); d['native_bee_diagnostic']['source']['source_radius_blocks'] = value
            self.assertFalse(valid_rejection_diagnostic(d))

    def test_canonical_signed_nanos_and_explicit_nullable_unknowns(self):
        for obj, key in (('native', 'sample_nano'), ('native', 'source_nano'), ('context', 'frame_nano')):
            for value in (str(-(2**63)), '0', str(2**63-1)):
                d = diagnostic_fixture(); d['native_bee_diagnostic'][obj][key] = value
                self.assertTrue(valid_rejection_diagnostic(d))
            for value in (str(-(2**63)-1), str(2**63), '-0', '+1', '01', '1.0', '', 1, True, [], {}):
                d = diagnostic_fixture(); d['native_bee_diagnostic'][obj][key] = value
                with self.subTest(obj=obj, key=key, value=value): self.assertFalse(valid_rejection_diagnostic(d))
        d = diagnostic_fixture(); n = d['native_bee_diagnostic']['native']
        for key in ('known', 'coverage_complete', 'inspected', 'sample_tick', 'sample_nano', 'source_tick', 'source_nano', 'sample_age_ms'):
            n[key] = None
        n.update(present=False, reason='unavailable')
        self.assertTrue(valid_rejection_diagnostic(d))

    def test_uuid_registry_and_native_only_type_are_strict(self):
        for obj, key in (('entity', 'uuid'), ('context', 'world_generation'), ('context', 'player_uuid')):
            for value in ('', 'world-one', 'AAAAAAAA-1111-4111-8111-111111111111', '1'*36, True, None):
                d = diagnostic_fixture(); d['native_bee_diagnostic'][obj][key] = value
                self.assertFalse(valid_rejection_diagnostic(d))
        for value in ('', 'overworld', 'minecraft:Overworld', 'a:'+'b'*127, True, None):
            d = diagnostic_fixture(); d['native_bee_diagnostic']['context']['dimension'] = value
            self.assertFalse(valid_rejection_diagnostic(d))
        for value in ('minecraft:cow', 'minecraft:Bee', None, True):
            d = diagnostic_fixture(); d['native_bee_diagnostic']['entity']['type'] = value
            self.assertFalse(valid_rejection_diagnostic(d))

    def test_geometry_is_all_present_or_all_null_and_finite_exact_vectors(self):
        geometry = ('position', 'aabb', 'velocity', 'lerp_target')
        d = diagnostic_fixture()
        for key in geometry: d['native_bee_diagnostic']['entity'][key] = None
        self.assertTrue(valid_rejection_diagnostic(d))
        for obj, keys in (('entity', geometry), ('context', ('player_position', 'prism', 'swept_aabb'))):
            for key in keys:
                for value in (None, [], [1.]*7, True, '0,0,0'):
                    d = diagnostic_fixture(); d['native_bee_diagnostic'][obj][key] = value
                    self.assertFalse(valid_rejection_diagnostic(d))
                for value in (True, float('nan'), float('inf'), float('-inf'), 10**400, '1'):
                    d = diagnostic_fixture(); d['native_bee_diagnostic'][obj][key][0] = value
                    self.assertFalse(valid_rejection_diagnostic(d))
        for value in (True, float('nan'), float('inf'), 10**400, '1', []):
            d = diagnostic_fixture(); d['native_bee_diagnostic']['native']['sample_age_ms'] = value
            self.assertFalse(valid_rejection_diagnostic(d))
        # Finite but stale/reversed/invalid facts explain refusal; never fix them.
        d = diagnostic_fixture(); n = d['native_bee_diagnostic']['native']
        n.update(source_tick=-1, source_nano='100', sample_nano='99', sample_age_ms=-.000001)
        self.assertTrue(valid_rejection_diagnostic(d))

    def test_complete_encoded_detail_is_bounded_without_truncation(self):
        d = diagnostic_fixture(); detail = d['native_bee_diagnostic']
        for obj, keys in (('entity', ('position', 'aabb', 'velocity', 'lerp_target')),
                          ('context', ('player_position', 'prism', 'swept_aabb'))):
            for key in keys: detail[obj][key] = [10**308] * len(detail[obj][key])
        original = deepcopy(d)
        self.assertGreater(len(json.dumps(detail, separators=(',', ':')).encode()), 8192)
        self.assertFalse(valid_rejection_diagnostic(d))
        self.assertTrue(exact(d, original))

    def test_terminal_evidence_requires_unsuccessful_original_context_and_geometry(self):
        data = canonical_fixture(); d = diagnostic_fixture(data); native = data[0]
        native.update(status='cancelled', reason=d['rejection_code'])
        native['result'].update(input_release_confirmed=True, local_segment=terminal(native, landed=False), route_entity_rejection=d)
        before = deepcopy(witness(data)); validate_scoped_witness(*data)
        self.assertEqual(before, witness(data))
        for obj, key, value in (('native', 'status', 'succeeded'), ('native', 'reason', 'other'),
                ('context', 'world_generation', '33333333-3333-4333-8333-333333333333'),
                ('context', 'player_uuid', '33333333-3333-4333-8333-333333333333'),
                ('context', 'dimension', 'minecraft:the_nether'), ('context', 'prism', [0.]*6),
                ('context', 'swept_aabb', [0.]*6)):
            bad = deepcopy(data)
            if obj == 'native': bad[0][key] = value
            else: bad[0]['result']['route_entity_rejection']['native_bee_diagnostic']['context'][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError): validate_scoped_witness(*bad)
        native['result'].update(unknown_outcome=True, motion_gate_rejected=True)
        validate_scoped_witness(*data)
        self.assertTrue(native['result']['unknown_outcome'])


class BeeDiagnosticTransportTests(unittest.TestCase):
    bridge = transport_fixture.SpatialStopDiagnosticTests.bridge

    def test_valid_409_preserved_exactly_once_and_deepcopied(self):
        d = diagnostic_fixture(); raw = encode(d); bridge, calls = self.bridge([(409, raw)])
        with self.assertRaises(BridgeError) as caught: bridge.request('POST', '/control/scoped-action', request_fixture(d))
        exc = caught.exception; self.assertFalse(exc.uncertain); self.assertEqual(exc.code, d['rejection_code'])
        self.assertTrue(exact(exc.route_entity_rejection, d)); self.assertEqual(len(calls), 1)
        admission = action_rejection_admission(exc)
        self.assertFalse(admission['admitted']); self.assertFalse(admission['uncertain'])
        self.assertTrue(exact(admission['route_entity_rejection'], d))
        admission['route_entity_rejection']['native_bee_diagnostic']['entity']['position'][0] = 99.
        self.assertTrue(exact(exc.route_entity_rejection, d)); self.assertEqual(encode(d), raw)

    def test_context_missing_changed_or_foreign_profile_drops_only_diagnostic(self):
        d = diagnostic_fixture()
        for mutation in ('missing', 'world_generation', 'dimension', 'player_uuid', 'profile', 'code', 'schema'):
            request = request_fixture(d); bad = deepcopy(d); code = d['rejection_code']
            if mutation == 'missing': request['intent'] = {}
            elif mutation == 'profile': request['preflight']['profile'] = V1_PROFILE
            elif mutation == 'code': code = 'route_bee_native_stale'
            elif mutation == 'schema': bad['native_bee_diagnostic']['native']['reason'] = 'private arbitrary text'
            else: request['intent']['expected_' + mutation] = 'foreign'
            bridge, calls = self.bridge([(409, encode(bad, code))])
            with self.assertRaises(BridgeError) as caught: bridge.request('POST', '/control/scoped-action', request)
            with self.subTest(mutation=mutation):
                self.assertFalse(caught.exception.uncertain); self.assertEqual(caught.exception.code, code)
                self.assertIsNone(caught.exception.route_entity_rejection); self.assertEqual(len(calls), 1)
                self.assertNotIn('route_entity_rejection', action_rejection_admission(caught.exception))

    def test_5xx_and_duplicate_keys_never_become_known_or_replayed(self):
        d = diagnostic_fixture(); raw = encode(d)
        duplicate = raw.replace(b'"reason":"entity_not_observed"', b'"reason":"observed","reason":"entity_not_observed"')
        self.assertNotEqual(raw, duplicate)
        for status, payload in ((500, raw), (503, raw), (409, duplicate), (500, duplicate)):
            bridge, calls = self.bridge([(status, payload)])
            with self.assertRaises(BridgeError) as caught: bridge.request('POST', '/control/scoped-action', request_fixture(d))
            self.assertIsNone(caught.exception.route_entity_rejection)
            self.assertEqual(caught.exception.uncertain, status >= 500); self.assertEqual(len(calls), 1)

    def test_runtime_retains_nested_refusal_without_retry_or_invented_action(self):
        d = diagnostic_fixture(); bridge, calls = self.bridge([(409, encode(d))])
        with self.assertRaises(BridgeError) as caught: bridge.request('POST', '/control/scoped-action', request_fixture(d))
        admission = action_rejection_admission(caught.exception)
        class RejectingClient(Client):
            def wait(self, request_id, timeout):
                if self.results[request_id]['op'] != 'action': return super().wait(request_id, timeout)
                return {'request_id':request_id, 'session_id':self.session_id, 'status':'failed', 'reason':d['rejection_code'],
                    'result':{}, 'action':None, 'action_id':None, 'cancellation':None, 'action_admission':deepcopy(admission)}
        with tempfile.TemporaryDirectory() as directory:
            clock = Clock(); client = RejectingClient(clock); runtime = Runtime(client, directory, clock=clock, sleeper=clock.sleep)
            try:
                before_x = client.x; outcome = runtime.execute('bee_refusal', move(), arrived)
                self.assertEqual(outcome.status, 'blocked'); self.assertEqual(outcome.reason, d['rejection_code'])
                self.assertEqual(outcome.evidence['submission_outcome'], 'known_no_effect_rejection')
                self.assertTrue(exact(outcome.evidence['action_admission'], admission))
                record = runtime._journal['records'][outcome.request_ids[0]]
                self.assertTrue(exact(record['evidence']['action_admission'], admission))
                self.assertEqual(client.action_count, 1); self.assertEqual(client.x, before_x)
                self.assertIsNone(client.native); self.assertIsNone(runtime.pending_request_id)
                self.assertFalse(outcome.evidence['server_confirmed']); self.assertFalse(outcome.evidence['gameplay_effect_confirmed'])
                outcome.evidence['action_admission']['route_entity_rejection']['native_bee_diagnostic']['native']['reason'] = 'changed'
                self.assertTrue(exact(record['evidence']['action_admission'], admission))
                runtime.close(); self.assertEqual(client.action_count, 1); self.assertEqual(len(calls), 1)
            finally: runtime.close()


@unittest.skipUnless(os.environ.get('MDC_BEE_DIAGNOSTIC_NATIVE'), 'explicit original native HTTP serializer directory required')
class BeeDiagnosticNativeWireTests(unittest.TestCase):
    bridge = transport_fixture.SpatialStopDiagnosticTests.bridge

    def original_paths(self):
        root = Path(os.environ['MDC_BEE_DIAGNOSTIC_NATIVE'])
        metadata = {'bee-diagnostic-result.json', 'bee-diagnostic-engine-start.json', 'bee-diagnostic-engine-terminal.json'}
        paths = sorted(p for p in root.glob('bee-diagnostic-*.json') if p.name not in metadata)
        self.assertTrue(paths, 'no original bee-diagnostic-*.json files')
        return paths

    def test_all_original_http_error_bytes_survive_real_transport_once(self):
        for path in self.original_paths():
            raw = path.read_bytes(); digest = hashlib.sha256(raw).hexdigest(); body = json.loads(raw)
            d = body['route_entity_rejection']
            with self.subTest(path=path.name):
                self.assertEqual(d['schema_version'], 2); self.assertTrue(valid_rejection_diagnostic(d))
                self.assertEqual(body['error'], d['rejection_code'])
                bridge, calls = self.bridge([(409, raw)])
                with self.assertRaises(BridgeError) as caught: bridge.request('POST', '/control/scoped-action', request_fixture(d))
                self.assertFalse(caught.exception.uncertain); self.assertEqual(caught.exception.code, body['error'])
                self.assertTrue(exact(action_rejection_admission(caught.exception)['route_entity_rejection'], d))
                self.assertEqual(len(calls), 1); self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), digest)

    def test_original_bytes_do_not_authorize_foreign_context_or_downgrade_5xx(self):
        for path in self.original_paths():
            raw = path.read_bytes(); body = json.loads(raw); d = body['route_entity_rejection']
            for status in (409, 500):
                request = request_fixture(d)
                if status == 409: request['intent']['expected_world_generation'] = '99999999-9999-4999-8999-999999999999'
                bridge, calls = self.bridge([(status, raw)])
                with self.subTest(path=path.name, status=status), self.assertRaises(BridgeError) as caught:
                    bridge.request('POST', '/control/scoped-action', request)
                self.assertEqual(caught.exception.code, body['error'])
                self.assertEqual(caught.exception.uncertain, status == 500)
                self.assertIsNone(caught.exception.route_entity_rejection); self.assertEqual(len(calls), 1)
            self.assertEqual(path.read_bytes(), raw)


@unittest.skipUnless(os.environ.get('MDC_BEE_MUTABLE_NATIVE_WIRE') and os.environ.get('MDC_BEE_MUTABLE_ENGINE_EVIDENCE'),
                     'explicit original mutable-position native wire and engine directories required')
class BeeMutableNativeWireTests(unittest.TestCase):
    def test_original_immutable_copied_destinations_pass_unchanged_full_witness_validator(self):
        root = Path(os.environ['MDC_BEE_MUTABLE_NATIVE_WIRE'])
        engine = Path(os.environ['MDC_BEE_MUTABLE_ENGINE_EVIDENCE'])
        raw = {k:(root / ('generated-' + k + '.json')).read_bytes()
               for k in ('standalone', 'coherent', 'intent', 'request')}
        values = {k:json.loads(v) for k,v in raw.items()}
        native = values['standalone']; before = deepcopy(native)
        w = validate_scoped_witness(native, values['request'], native['action_id'], values['intent'])
        self.assertEqual(native['status'], 'succeeded'); self.assertTrue(native['result']['input_release_confirmed'])
        footprint = json.loads((engine / 'actual-footprint.json').read_bytes())
        self.assertTrue(exact(w['facts']['local_segment'], footprint))
        bees = [row for row in footprint['entity_guard']['rows'] if row['type'] == 'minecraft:bee' and not row['removed']]
        self.assertTrue(bees)
        for row in bees:
            route = row['native_living']['bee_route']
            self.assertEqual(route['hive_pos'], {'x':1, 'y':2, 'z':3})
            self.assertEqual(route['flower_pos'], {'x':4, 'y':5, 'z':6})
            self.assertEqual(route['server_class'], 'net.minecraft.world.entity.animal.Bee')
            self.assertFalse(route['has_stung'])
        # The producer mutates its exact MutableBlockPos sources after capture;
        # original immutable admission coordinates remain 1/2/3 and 4/5/6.
        radius = values['coherent']['state']['nearby']['radius']
        semantic = validate_snapshot(values['coherent'], radius)
        record = retain(raw['coherent'])
        self.assertEqual(record['sha256'], hashlib.sha256(raw['coherent']).hexdigest())
        self.assertTrue(exact(validate_retained(record, semantic, radius), semantic))
        validate_scoped_witness(semantic['action'], values['request'], native['action_id'], values['intent'])
        self.assertTrue(exact(before, native))
        for key, content in raw.items(): self.assertEqual((root / ('generated-' + key + '.json')).read_bytes(), content)


if __name__ == '__main__': unittest.main()
