"""Closed refusal evidence through the real consumer; no connection or gameplay."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from resident_controller.capability_snapshot import exact
from resident_controller.controller import action_rejection_admission
from resident_controller.route_threat_diagnostic import (
    MAX_BYTES, PHASES, REASONS, REJECTION_CODES, valid_rejection_diagnostic)
from resident_controller.transport import Bridge, BridgeError
from route_threat_diagnostic_fixture import diagnostic_fixture, request_fixture


def encode(value, code=None):
    return json.dumps({'error':code or value['rejection_code'], 'route_threat_rejection':value},
                      separators=(',', ':'), allow_nan=False).encode()


def exchange(raw, body, *, status=409, method='POST', path='/control/scoped-action'):
    """Exercise production HTTP consumption with bytes, without opening a socket."""
    class Response:
        def read(self, limit): return raw[:limit]
        def getheader(self, name): return None
    response = Response(); response.status = status
    class Connection:
        calls = []
        def __init__(self, *args, **kwargs): pass
        def request(self, *args, **kwargs): self.calls.append((args, kwargs))
        def getresponse(self): return response
        def close(self): pass
    bridge = Bridge('http://127.0.0.1:12345', 'synthetic-offline-test-token')
    with patch('resident_controller.transport.http.client.HTTPConnection', Connection):
        try: bridge.request(method, path, body)
        except BridgeError as exc: return exc, bridge, Connection.calls
    raise AssertionError('expected HTTP refusal')


class RouteThreatDiagnosticSchemaTests(unittest.TestCase):
    def test_each_object_is_closed_and_every_field_required(self):
        d = diagnostic_fixture(); self.assertTrue(valid_rejection_diagnostic(d))
        for path in ((), ('entity',), ('context',), ('native',), ('source',)):
            original = d if not path else d[path[0]]
            for key in tuple(original) + ('extra',):
                bad = deepcopy(d); target = bad if not path else bad[path[0]]
                if key == 'extra': target[key] = False
                else: del target[key]
                with self.subTest(path=path, key=key): self.assertFalse(valid_rejection_diagnostic(bad))
            for replacement in (None, [], True, 'unknown'):
                bad = deepcopy(d)
                if path: bad[path[0]] = replacement
                else: bad = replacement
                self.assertFalse(valid_rejection_diagnostic(bad))

    def test_exact_profile_policy_version_type_and_closed_enums(self):
        d = diagnostic_fixture()
        for key, value in (('schema_version',True), ('schema_version',2), ('schema_version',1.),
                ('profile','movement-local-segment-spatial-stop-v2'), ('policy','route-spatial-stop-v2'),
                ('rejection_code','arbitrary'), ('phase','admission')):
            self.assertFalse(valid_rejection_diagnostic({**d, key:value}))
        for key, allowed in (('rejection_code',REJECTION_CODES), ('phase',PHASES)):
            for value in allowed:
                valid = deepcopy(d); valid[key] = value
                if value == 'final_fence': valid['context']['final_check_nano'] = '1000000001'
                self.assertTrue(valid_rejection_diagnostic(valid))
            for value in (None, True, [], {}, '', 'private error text'):
                self.assertFalse(valid_rejection_diagnostic({**d, key:value}))
        for obj, key in (('native','reason'), ('source','batch_reason')):
            for value in REASONS:
                bad = deepcopy(d); bad[obj][key] = value; self.assertTrue(valid_rejection_diagnostic(bad))
            for value in (None, True, [], {}, '', 'private error text', 'x'*4097):
                bad = deepcopy(d); bad[obj][key] = value; self.assertFalse(valid_rejection_diagnostic(bad))
        for value in ('minecraft:bee', 'minecraft:Zombie', True, None):
            bad = deepcopy(d); bad['entity']['type'] = value; self.assertFalse(valid_rejection_diagnostic(bad))

    def test_signed_integer_bounds_canonical_nanos_and_boolean_types(self):
        d = diagnostic_fixture()
        fields = [('entity','id',-(2**31),2**31-1), ('context','frame_tick',0,2**63-1),
                  ('native','inspected',0,4097), ('native','sample_tick',-(2**63),2**63-1),
                  ('native','source_tick',-(2**63),2**63-1), ('source','row_tick',-(2**63),2**63-1)]
        for obj, key, lo, hi in fields:
            for value in (lo, hi):
                bad = deepcopy(d)
                if obj == 'source': bad['source'].update(row_present=True,row_nano='0')
                bad[obj][key] = value; self.assertTrue(valid_rejection_diagnostic(bad))
            for value in (lo-1, hi+1, True, 1., '1', [], {}):
                bad = deepcopy(d); bad[obj][key] = value
                with self.subTest(obj=obj,key=key,value=value): self.assertFalse(valid_rejection_diagnostic(bad))
        for obj, key in (('context','frame_nano'), ('context','final_check_nano'),
                         ('native','sample_nano'), ('native','source_nano'), ('source','row_nano')):
            for value in (str(-(2**63)), '0', str(2**63-1)):
                bad = deepcopy(d)
                if obj == 'source': bad['source'].update(row_present=True,row_tick=0)
                if key == 'final_check_nano': bad['phase'] = 'final_fence'
                bad[obj][key] = value; self.assertTrue(valid_rejection_diagnostic(bad))
            for value in (str(-(2**63)-1), str(2**63), '-0', '+1', '01', '1.0', '', 1, True, [], {}):
                bad = deepcopy(d)
                if key == 'final_check_nano': bad['phase'] = 'final_fence'
                bad[obj][key] = value; self.assertFalse(valid_rejection_diagnostic(bad))
        for obj, keys in (('entity',('selected',)), ('native',('present','known','coverage_complete','alive','current_target_known')),
                ('source',('batch_present','batch_context_matches','row_present','row_identity_matches','batch_complete'))):
            for key in keys:
                for value in (0, 1, 'true', [], {}):
                    bad = deepcopy(d); bad[obj][key] = value; self.assertFalse(valid_rejection_diagnostic(bad))

    def test_uuids_registry_and_selected_identity_are_strict(self):
        for obj, key in (('entity','uuid'), ('context','world_generation'), ('context','player_uuid'), ('context','selected_target_uuid')):
            for value in ('', 'world-one', 'AAAAAAAA-1111-4111-8111-111111111111', '1'*36, True, None):
                d = diagnostic_fixture(); d[obj][key] = value; self.assertFalse(valid_rejection_diagnostic(d))
        for value in ('', 'overworld', 'minecraft:Overworld', 'a:'+'b'*127, True, None):
            d = diagnostic_fixture(); d['context']['dimension'] = value; self.assertFalse(valid_rejection_diagnostic(d))
        d = diagnostic_fixture(); d['entity']['selected'] = False; self.assertFalse(valid_rejection_diagnostic(d))
        d['entity']['uuid'] = '55555555-5555-4555-8555-555555555555'; self.assertTrue(valid_rejection_diagnostic(d))
        d['entity']['selected'] = True; self.assertFalse(valid_rejection_diagnostic(d))

    def test_nullable_unknowns_and_stale_facts_are_preserved_without_reclocking(self):
        d = diagnostic_fixture()
        d['native'] = {k:False if k == 'present' else 'unavailable' if k == 'reason' else None for k in d['native']}
        self.assertTrue(valid_rejection_diagnostic(d))
        d['source'].update(row_present=True, row_tick=189, row_nano='999999000')
        self.assertTrue(valid_rejection_diagnostic(d)); self.assertIsNone(d['native']['sample_nano'])
        d['native'].update(present=True, sample_tick=-1, source_tick=2, sample_nano='99', source_nano='100', sample_age_ms=-.000001)
        self.assertTrue(valid_rejection_diagnostic(d))
        for value in (True, float('nan'), float('inf'), float('-inf'), 10**400, '1', [], {}):
            bad = deepcopy(d); bad['native']['sample_age_ms'] = value; self.assertFalse(valid_rejection_diagnostic(bad))

    def test_encoded_whole_diagnostic_is_bounded_without_truncating_or_mutating(self):
        d = diagnostic_fixture(); before = deepcopy(d)
        self.assertLess(len(json.dumps(d, separators=(',', ':')).encode()), MAX_BYTES)
        with patch('resident_controller.route_threat_diagnostic.MAX_BYTES', 1):
            self.assertFalse(valid_rejection_diagnostic(d))
        self.assertTrue(exact(d, before))

    def test_source_presence_consistency_and_final_fence_clock_scope(self):
        for changes in ({'row_present':True}, {'row_identity_matches':True}, {'row_tick':1}, {'row_nano':'1'},
                {'batch_present':False,'row_present':True,'row_tick':1,'row_nano':'1'}):
            d = diagnostic_fixture(); d['source'].update(changes); self.assertFalse(valid_rejection_diagnostic(d))
        for phase in ('capture','recheck'):
            d = diagnostic_fixture(); d['phase'] = phase; d['context']['final_check_nano'] = '1000000001'
            self.assertFalse(valid_rejection_diagnostic(d))
        d['phase'] = 'final_fence'; self.assertTrue(valid_rejection_diagnostic(d))
        d['context']['final_check_nano'] = None; self.assertFalse(valid_rejection_diagnostic(d))

    def test_absent_native_and_batch_cannot_claim_captured_facts(self):
        d = diagnostic_fixture()
        absent = {k:False if k == 'present' else 'unavailable' if k == 'reason' else None for k in d['native']}
        d['native'] = deepcopy(absent); self.assertTrue(valid_rejection_diagnostic(d))
        populated = diagnostic_fixture()['native']
        populated.update(sample_tick=1,source_tick=1,sample_nano='1',source_nano='1',sample_age_ms=0.,alive=False,current_target_known=False)
        for key,value in populated.items():
            if key == 'present': continue
            bad = deepcopy(d); bad['native'][key] = value
            with self.subTest(key=key): self.assertFalse(valid_rejection_diagnostic(bad))
        d['source'].update(batch_present=False,batch_context_matches=False,batch_complete=None,batch_reason='unavailable')
        self.assertTrue(valid_rejection_diagnostic(d))
        for key,value in (('batch_context_matches',True),('batch_complete',False),('batch_reason','observed')):
            bad = deepcopy(d); bad['source'][key] = value; self.assertFalse(valid_rejection_diagnostic(bad))


class RouteThreatDiagnosticTransportTests(unittest.TestCase):
    def test_valid_409_preserves_original_code_status_and_copies_nested_data(self):
        d = diagnostic_fixture(); raw = encode(d)
        exc, bridge, calls = exchange(raw, request_fixture(d))
        self.assertEqual((exc.code, exc.status, exc.uncertain), (d['rejection_code'],409,False))
        self.assertEqual(exc.route_threat_rejection_status, 'reported')
        self.assertEqual(bridge.last_response_metadata['route_threat_rejection_status'], 'reported')
        self.assertTrue(exact(exc.route_threat_rejection, d)); self.assertEqual(len(calls), 1)
        admission = action_rejection_admission(exc)
        self.assertFalse(admission['admitted']); self.assertFalse(admission['uncertain'])
        self.assertEqual(admission['route_threat_rejection'], d)
        admission['route_threat_rejection']['native']['reason'] = 'changed'
        self.assertEqual(exc.route_threat_rejection, d); self.assertEqual(encode(d), raw)
        independent = BridgeError(d['rejection_code'],status=409,route_threat_rejection=d)
        d['native']['reason'] = 'changed'; self.assertNotEqual(independent.route_threat_rejection,d)

    def test_missing_foreign_or_malformed_context_drops_only_diagnostic(self):
        d = diagnostic_fixture()
        for mutation in ('intent','action','world_generation','dimension','player_uuid','target_uuid',
                'guard','guard_version','code','schema','selected','oversized','profile'):
            request = request_fixture(d); bad = deepcopy(d); code = d['rejection_code']
            if mutation == 'intent': del request['intent']
            elif mutation == 'action': request['intent']['action'] = 'combat_entity'
            elif mutation == 'guard': request['intent']['route_threat_guard'] = None
            elif mutation == 'guard_version': request['intent']['route_threat_guard']['schema_version'] = True
            elif mutation == 'target_uuid': request['intent']['route_threat_guard']['target_uuid'] = '55555555-5555-4555-8555-555555555555'
            elif mutation == 'code': code = 'route_spatial_native_target_stale'
            elif mutation == 'schema': bad['native']['reason'] = 'private text'
            elif mutation == 'selected': bad['entity']['selected'] = False
            elif mutation == 'oversized': bad['context']['dimension'] = 'a:'+'b'*4096
            elif mutation == 'profile': bad['profile'] = 'movement-local-segment-spatial-stop-v2'
            else: request['intent']['expected_' + mutation] = 'foreign'
            exc, bridge, calls = exchange(encode(bad,code), request)
            with self.subTest(mutation=mutation):
                self.assertEqual((exc.code,exc.status,exc.uncertain),(code,409,False))
                self.assertIsNone(exc.route_threat_rejection); self.assertEqual(len(calls),1)
                self.assertEqual(action_rejection_admission(exc)['route_threat_rejection_status'],'invalid')

    def test_only_409_scoped_post_spatial_profile_can_carry_diagnostic(self):
        d = diagnostic_fixture()
        for status, method, path, profile in ((400,'POST','/control/scoped-action',d['profile']),
                (500,'POST','/control/scoped-action',d['profile']), (503,'POST','/control/scoped-action',d['profile']),
                (409,'POST','/control/action',d['profile']), (409,'GET','/control/action/status',d['profile']),
                (409,'POST','/control/scoped-action','movement-local-segment-spatial-stop-v2')):
            request = request_fixture(d); request['preflight']['profile'] = profile
            exc, bridge, calls = exchange(encode(d),request if method == 'POST' else None,status=status,method=method,path=path)
            with self.subTest(status=status,method=method,path=path,profile=profile):
                self.assertEqual(exc.code,d['rejection_code']); self.assertIsNone(exc.route_threat_rejection)
                self.assertIsNone(exc.route_threat_rejection_status); self.assertEqual(len(calls),1)
                self.assertEqual(exc.uncertain,method == 'POST' and status >= 500)

    def test_absent_and_invalid_diagnostics_leave_existing_known_rejection_unchanged(self):
        d = diagnostic_fixture(); expected = {'schema_version':1,'http_status':409,'admitted':False,
            'uncertain':False,'reason':d['rejection_code']}
        for raw in (json.dumps({'error':d['rejection_code']}).encode(),
                json.dumps({'error':d['rejection_code'],'route_threat_rejection':None}).encode()):
            exc, bridge, calls = exchange(raw,request_fixture(d)); admission = action_rejection_admission(exc)
            self.assertEqual({k:admission[k] for k in expected},expected); self.assertEqual(len(calls),1)
            self.assertNotIn('route_threat_rejection',admission)
        # Invalid duplicate-key JSON keeps the original strict-parse fallback.
        raw = encode(d); duplicate = raw.replace(b'"known":false',b'"known":true,"known":false')
        self.assertNotEqual(raw,duplicate)
        for status in (409,500):
            exc, bridge, calls = exchange(duplicate,request_fixture(d),status=status)
            self.assertEqual(exc.code,'bridge_http_'+str(status)); self.assertEqual(exc.uncertain,status >= 500)
            self.assertIsNone(exc.route_threat_rejection); self.assertEqual(len(calls),1)

    def test_controller_revalidates_without_turning_invalid_diagnostic_into_proof(self):
        d = diagnostic_fixture()
        for status, uncertain, code, diagnostic in ((500,True,d['rejection_code'],d),
                (409,False,'other',d), (409,False,d['rejection_code'],{**d,'extra':False}),
                (409,True,d['rejection_code'],d)):
            exc = BridgeError(code,status=status,uncertain=uncertain,route_threat_rejection=diagnostic)
            result = action_rejection_admission(exc)
            self.assertNotIn('route_threat_rejection',result)
            self.assertEqual(result['route_threat_rejection_status'],'invalid')

    def test_deep_malformed_refusal_keeps_known_409_and_never_retries(self):
        d = diagnostic_fixture()
        raw = ('{"error":"'+d['rejection_code']+'","route_threat_rejection":'+'['*10000+'null'+']'*10000+'}').encode()
        for status in (409,500):
            exc, bridge, calls = exchange(raw,request_fixture(d),status=status)
            self.assertEqual((exc.code,exc.status,exc.uncertain),('bridge_http_'+str(status),status,status >= 500))
            self.assertIsNone(exc.route_threat_rejection); self.assertEqual(len(calls),1)


@unittest.skipUnless(os.environ.get('MDC_ROUTE_THREAT_DIAGNOSTIC_NATIVE'), 'explicit original Java HTTP serializer directory required')
class RouteThreatDiagnosticNativeWireTests(unittest.TestCase):
    def original_paths(self):
        root = Path(os.environ['MDC_ROUTE_THREAT_DIAGNOSTIC_NATIVE'])
        paths = [p for p in sorted(root.glob('*.json'))
                 if 'route_threat_rejection' in json.loads(p.read_bytes())]
        self.assertTrue(paths,'no original route threat refusal response files')
        return paths

    def test_original_java_http_bytes_survive_transport_once_unchanged(self):
        for path in self.original_paths():
            raw = path.read_bytes(); sha = hashlib.sha256(raw).hexdigest(); value = json.loads(raw); d = value['route_threat_rejection']
            with self.subTest(path=path.name):
                self.assertTrue(valid_rejection_diagnostic(d)); self.assertEqual(value['error'],d['rejection_code'])
                exc, bridge, calls = exchange(raw,request_fixture(d))
                self.assertEqual((exc.code,exc.status,exc.uncertain),(value['error'],409,False))
                self.assertTrue(exact(action_rejection_admission(exc)['route_threat_rejection'],d)); self.assertEqual(len(calls),1)
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),sha)

    def test_original_wire_never_binds_foreign_request_or_downgrades_5xx(self):
        for path in self.original_paths():
            raw = path.read_bytes(); d = json.loads(raw)['route_threat_rejection']
            for mutation in ('world_generation','player_uuid','dimension','target_uuid','5xx'):
                request = request_fixture(d)
                if mutation == 'target_uuid': request['intent']['route_threat_guard']['target_uuid'] = '55555555-5555-4555-8555-555555555555'
                elif mutation != '5xx': request['intent']['expected_'+mutation] = 'foreign'
                exc, bridge, calls = exchange(raw,request,status=500 if mutation == '5xx' else 409)
                self.assertEqual(exc.code,d['rejection_code']); self.assertEqual(exc.uncertain,mutation == '5xx')
                self.assertIsNone(exc.route_threat_rejection); self.assertEqual(len(calls),1)
            self.assertEqual(path.read_bytes(),raw)


if __name__ == '__main__': unittest.main()
