import copy
import json
from pathlib import Path
import tempfile
import unittest

from resident_controller.ipc import QueueClient, MAX_COMMAND_BYTES, MAX_SESSION_BYTES, atomic_json, read_json
from resident_controller.native_admission import validate, no_effect, digest, entity_diagnostic
from resident_controller.session_diagnostics import compact_session, read_diagnostic


def request():
    return {'preflight': {'version': 'scoped-native-preflight/1', 'profile': 'placement-local-observed-v1',
        'owner_id': 'a' * 32, 'owner_generation': 1, 'job_id': 'job-one', 'defense_epoch': 7},
        'intent': {'action': 'place_block', 'action_id': 'action-one', 'expected_action_session': 'session-one'}}


def proof(body=None, stage='validation'):
    body = body or request()
    return {'schema_version': 1, 'action_session': body['intent']['expected_action_session'],
        'request_payload_sha256': digest(body), 'digest_format': 'sorted-json-utf8/1',
        'action_id': body['intent']['action_id'], 'action': body['intent']['action'], 'scope': copy.deepcopy(body['preflight']),
        'stage': stage, 'reason': 'unsupported_scoped_version', 'effects_none_proven': stage == 'validation',
        'dispatch_authority': False, 'retry_authority': False}


class AdmissionProofTests(unittest.TestCase):
    def test_only_bound_validation_proves_no_effect(self):
        body = request()
        for stage in ('validation', 'hooks_possible', 'input_transfer', 'registered'):
            value = proof(body, stage)
            self.assertTrue(validate(value, body, value['reason']))
            self.assertEqual(no_effect(value), stage == 'validation')

    def test_wire_faults_never_prove_no_effect(self):
        body = request()
        edits = [('action_id', 'other'), ('action_session', 'other'), ('request_payload_sha256', '0' * 64),
            ('schema_version', True), ('effects_none_proven', 1), ('retry_authority', True),
            ('dispatch_authority', True), ('stage', 'hooks_possible'), ('reason', 'other'),
            ('scope', {**body['preflight'], 'owner_generation': True}),
            ('scope', {**body['preflight'], 'owner_id': 'b' * 32}),
            ('scope', {**body['preflight'], 'job_id': 'other'}),
            ('scope', {**body['preflight'], 'defense_epoch': 8})]
        for key, value in edits:
            with self.subTest(key=key, value=value):
                forged = proof(body); forged[key] = value
                self.assertFalse(validate(forged, body, 'unsupported_scoped_version'))
        forged = proof(body); forged['extra'] = 'untrusted'
        self.assertFalse(validate(forged, body, forged['reason']))
        changed = copy.deepcopy(body); changed['intent']['timeout_ms'] = 999
        self.assertFalse(validate(proof(body), changed, 'unsupported_scoped_version'))

    def test_entity_diagnostic_explains_global_scope_without_geometry_claim(self):
        d = {'schema_version': 1, 'profile': 'mining-local-observed-v2',
            'enumeration_scope': 'all_rendered_entities_before_spatial_filter', 'spatial_filter_applied': False,
            'spatial_relation': 'not_evaluated', 'entity_class': 'example.UnknownEntity',
            'entity_class_complete': True, 'reason': 'scoped_movement_entity_unsupported',
            'diagnostic_only': True, 'dispatch_authority': False}
        self.assertTrue(entity_diagnostic(d, d['reason']))
        for key, value in [('spatial_relation', 'outside'), ('entity_class', 'x' * 257), ('dispatch_authority', True)]:
            self.assertFalse(entity_diagnostic({**d, key: value}, d['reason']))


class SessionTelemetryTests(unittest.TestCase):
    def test_session_read_70k_command_limit_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = {'session_id': 'session-one', 'state': 'ready', 'diagnostics': 'x' * 70000}
            atomic_json(Path(tmp) / 'session.json', data)
            self.assertEqual(QueueClient(tmp).session(), data)
            with self.assertRaisesRegex(ValueError, 'mailbox_file_too_large'):
                read_json(Path(tmp) / 'session.json')
            with self.assertRaisesRegex(ValueError, 'command_too_large'):
                QueueClient(tmp).submit({'op': 'observe', 'padding': 'x' * MAX_COMMAND_BYTES})
            (Path(tmp) / 'session.json').write_bytes(b' ' * (MAX_SESSION_BYTES + 1))
            with self.assertRaisesRegex(ValueError, 'mailbox_file_too_large'):
                QueueClient(tmp).session()

    def test_complete_diagnostic_retained_summary_bounded_and_immutable(self):
        with tempfile.TemporaryDirectory() as tmp:
            failure = {'type': 'BridgeError', 'message': 'original_failure', 'message_truncated': False}
            diagnostics = {'schema_version': 1, 'clock': 'python_monotonic', 'attempts': [
                {'attempt': 1, 'outcome': 'failed', 'last_rejection': 'original_failure',
                 'original_rejection': failure, 'stages': [{'evidence': 'x' * 70000}]}]}
            data = {'session_id': 'session-one', 'terrain_read': {'outcome': 'failed', 'diagnostics': diagnostics}}
            original = copy.deepcopy(data)
            projected = compact_session(tmp, data)
            self.assertEqual(data, original)
            self.assertLess(len(json.dumps(projected)), 8192)
            ref = projected['terrain_read']['diagnostics_ref']
            self.assertEqual(read_diagnostic(tmp, 'session-one', ref)['diagnostics'], diagnostics)
            self.assertEqual(projected['terrain_read']['diagnostics_summary']['attempts'][0]['original_rejection'], failure)
            path = Path(tmp) / ref['path']; before = path.read_bytes()
            self.assertEqual(compact_session(tmp, data), projected)
            self.assertEqual(path.read_bytes(), before)
            bad = {**ref, 'path': '../session.json'}
            with self.assertRaises(ValueError): read_diagnostic(tmp, 'session-one', bad)
            with self.assertRaises(ValueError): read_diagnostic(tmp, 'other', ref)
            path.write_text('{}')
            with self.assertRaisesRegex(ValueError, 'digest_mismatch'): read_diagnostic(tmp, 'session-one', ref)
            with self.assertRaisesRegex(ValueError, 'existing_digest_mismatch'): compact_session(tmp, data)

    def test_capacity_never_silently_evicts_failure(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            data = {'session_id': 'session-one', 'terrain_read': {'diagnostics': {'failure': 'x' * 70000}}}
            with patch('resident_controller.session_diagnostics.MAX_DIAGNOSTIC_FILES', 0):
                result = compact_session(tmp, data)
            self.assertEqual(result['terrain_read']['diagnostics'], data['terrain_read']['diagnostics'])
            self.assertEqual(result['terrain_read']['diagnostics_storage_status'], 'reference_capacity_full_full_evidence_inline')

class ImmutableReceiptTests(unittest.TestCase):
    def test_stop_does_not_rewrite_original_uncertainty(self):
        from resident_controller.controller import Resident, Running
        class Bridge: base_url = 'http://127.0.0.1:12345'
        with tempfile.TemporaryDirectory() as tmp:
            resident = Resident(Bridge(), tmp)
            command = {'request_id': 'original', 'session_id': resident.session_id, 'op': 'action', 'action': 'place_block'}
            resident.active = Running(command, iter(()), action_id='original-native', capability_unknown=True)
            resident.finish(command, 'uncertain', reason='post_hook_failure', action_id='original-native', unknown_outcome=True)
            path = Path(tmp) / 'results' / 'original.json'; original = path.read_bytes()
            resident.interrupt_local('cancel_requested')
            resident.finish({'request_id': 'stop'}, 'succeeded', result={'input_release_confirmed': True})
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(read_json(Path(tmp) / 'results' / 'stop.json')['status'], 'succeeded')
            self.assertEqual(read_json(path)['status'], 'uncertain')


    def test_result_retention_does_not_evict_unknown_evidence(self):
        from unittest.mock import patch
        from resident_controller.controller import Resident
        class Bridge: base_url = 'http://127.0.0.1:12345'
        with tempfile.TemporaryDirectory() as tmp:
            resident = Resident(Bridge(), tmp)
            with patch('resident_controller.controller.MAX_RESULTS', 1):
                resident.finish({'request_id':'original'}, 'uncertain', reason='unresolved')
                resident.finish({'request_id':'stop'}, 'succeeded', result={'ok':True})
                resident.finish({'request_id':'later'}, 'succeeded')
            self.assertEqual(read_json(Path(tmp) / 'results' / 'original.json')['status'], 'uncertain')
            self.assertFalse((Path(tmp) / 'results' / 'stop.json').exists())


class ResidentAdmissionTests(unittest.TestCase):
    def run_case(self, stage, tamper=False):
        from resident_controller.controller import Resident, Running
        from resident_controller.transport import BridgeError
        class Bridge:
            base_url = 'http://127.0.0.1:12345'
            posts = []
            def request(inner, method, path, body=None):
                self.assertEqual((method,path), ('POST','/control/scoped-action'))
                inner.posts.append(copy.deepcopy(body))
                p = proof(body, stage)
                if tamper: p['scope']['owner_id'] = 'b' * 32
                raise BridgeError(p['reason'], status=409, native_admission=p, native_admission_status='reported')
        with tempfile.TemporaryDirectory() as tmp:
            bridge = Bridge(); resident = Resident(bridge, tmp)
            resident.bridge_identity = {'action_session': 'session-one'}
            envelope = request()
            intent = {k:v for k,v in envelope['intent'].items() if k != 'action_id'}
            command = {'op':'action', 'request_id':'original', 'session_id':resident.session_id,
                'scoped_native_preflight':envelope['preflight'], **intent}
            def recipe(): yield {'step':'action', 'body':intent}
            resident.active = Running(command, recipe())
            resident.advance()
            receipt = read_json(Path(tmp) / 'results' / 'original.json')
            if stage == 'validation' and not tamper:
                self.assertEqual(receipt['status'], 'failed')
                self.assertEqual(receipt['action_admission']['schema_version'], 2)
                self.assertIsNone(receipt['action_id'])
                self.assertIsNone(resident.active)
            else:
                self.assertEqual(receipt['status'], 'uncertain')
                self.assertTrue(resident.active.capability_unknown)
                self.assertEqual(receipt['action_id'], bridge.posts[0]['intent']['action_id'])
                for _ in range(3): resident.advance()
                self.assertEqual(len(bridge.posts), 1)
                original = (Path(tmp) / 'results' / 'original.json').read_bytes()
                resident.interrupt_local('cancel_requested')
                self.assertEqual((Path(tmp) / 'results' / 'original.json').read_bytes(), original)

    def test_pre_hook_proof_is_known_refusal(self): self.run_case('validation')
    def test_post_hook_proof_stays_unknown_without_cancel_or_retry(self): self.run_case('hooks_possible')
    def test_owner_tamper_stays_unknown(self): self.run_case('validation', tamper=True)


class CoreAdmissionTests(unittest.TestCase):
    def test_scoped_receipt_requires_independently_bound_native_proof(self):
        import uuid
        from mdc_skills.core import Runtime
        body = request()
        record = {'gateway_session': str(uuid.UUID(int=123)), 'request_id': 'queue-one',
            'command': {'op': 'action', 'scoped_native_preflight': copy.deepcopy(body['preflight']),
                **{k: v for k, v in body['intent'].items() if k != 'action_id'}}}
        body['intent']['action_id'] = uuid.uuid5(uuid.UUID(record['gateway_session']), 'queue-one:1').hex
        result = {'status': 'failed', 'reason': 'unsupported_scoped_version', 'action': None,
            'action_id': None, 'cancellation': None,
            'action_admission': {'schema_version': 2, 'http_status': 409, 'admitted': False,
                'uncertain': False, 'reason': 'unsupported_scoped_version', 'native_admission': proof(body)}}
        self.assertTrue(Runtime._no_effect(result, record))
        original = copy.deepcopy(result)
        for stage in ('hooks_possible','input_transfer','registered'):
            bad = copy.deepcopy(result); bad['action_admission']['native_admission'] = proof(body, stage)
            self.assertFalse(Runtime._no_effect(bad, record))
        legacy = copy.deepcopy(result); legacy['action_admission'].pop('native_admission')
        legacy['action_admission']['schema_version'] = 1
        self.assertFalse(Runtime._no_effect(legacy, record))
        for key, value in [('queue_request_id','other'), ('queue_session_id',str(uuid.UUID(int=124)))]:
            self.assertFalse(Runtime._no_effect({**result,key:value}, record))
        bad = copy.deepcopy(result); bad['action_admission']['native_admission']['scope']['job_id'] = 'other'
        self.assertFalse(Runtime._no_effect(bad, record))
        self.assertEqual(result, original)


class ProductionWireTests(unittest.TestCase):
    def exchange(self, raw, body):
        from unittest.mock import patch
        from resident_controller.transport import Bridge, BridgeError
        class Response:
            status = 409
            def read(self, limit): return raw[:limit]
            def getheader(self, name): return None
        class Connection:
            calls = []
            def __init__(self, *args, **kwargs): pass
            def request(self, *args, **kwargs): self.calls.append((args, kwargs))
            def getresponse(self): return Response()
            def close(self): pass
        bridge = Bridge('http://127.0.0.1:12345', 'offline-fixture')
        with patch('resident_controller.transport.http.client.HTTPConnection', Connection):
            try: bridge.request('POST', '/control/scoped-action', body)
            except BridgeError as exc:
                self.assertEqual(len(Connection.calls), 1)
                return exc
        self.fail('expected rejection')

    def wire(self):
        import os
        path = os.environ.get('MDC_NATIVE_OUTCOME_WIRE')
        if not path: self.skipTest('production Java fixture not selected')
        return Path(path)

    def test_actual_java_http_envelopes_through_transport(self):
        from resident_controller.controller import action_rejection_admission, scoped_uncertain_diagnostics
        wire = self.wire(); body = json.loads((wire / 'request.json').read_text())
        for stage in ('validation', 'hooks_possible', 'input_transfer', 'registered'):
            exc = self.exchange((wire / (stage + '.json')).read_bytes(), body)
            self.assertEqual(exc.native_admission_status, 'reported')
            self.assertEqual(no_effect(exc.native_admission), stage == 'validation')
            self.assertEqual(action_rejection_admission(exc)['schema_version'], 2)
        exc = self.exchange((wire / 'entity.json').read_bytes(), body)
        self.assertEqual(exc.native_entity_rejection_status, 'reported')
        retained = scoped_uncertain_diagnostics(exc)
        self.assertEqual(retained['native_entity_rejection']['entity_class'], 'java.lang.Object')
        self.assertFalse(retained['effect_free_proven'])

    def test_actual_java_proof_wire_faults_remain_unproven(self):
        wire = self.wire(); body = json.loads((wire / 'request.json').read_text())
        valid = json.loads((wire / 'validation.json').read_text())
        for key, value in [('action_session','other'), ('action_id','other'),
            ('request_payload_sha256','0' * 64), ('effects_none_proven',1), ('schema_version',True),
            ('stage','hooks_possible'), ('scope',{**body['preflight'], 'owner_generation':2})]:
            bad = copy.deepcopy(valid); bad['native_admission'][key] = value
            exc = self.exchange(json.dumps(bad).encode(), body)
            self.assertEqual(exc.native_admission_status, 'invalid')
            self.assertIsNone(exc.native_admission)
        # Duplicate JSON fields fail strict parsing, and never acquire proof authority.
        raw = (wire / 'validation.json').read_text().replace('"effects_none_proven":true', '"effects_none_proven":false,"effects_none_proven":true')
        self.assertIsNone(self.exchange(raw.encode(), body).native_admission)

if __name__ == '__main__': unittest.main()
