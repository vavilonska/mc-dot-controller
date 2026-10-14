"""Offline production consumer chain with synthetic native facts.

HTTPConnection is an in-memory response double. The queue is driven synchronously
in this process. No service, socket, game process, credentials or live acceptance.
"""
from copy import deepcopy
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import patch

from resident_controller.capability_snapshot import exact, validate_snapshot, validate_scoped_witness
from resident_controller.controller import Resident, action_rejection_admission
from resident_controller.ipc import QueueClient, atomic_json
from resident_controller.movement_wire import MARKER, REFERENCE, WITNESS, load_strict, valid_size_diagnostic
from resident_controller.transport import Bridge, BridgeError, json_bytes
from mdc_skills.core import Runtime, SkillError, _json
from mdc_toolbox.__main__ import MAX_LINE, serve
from mdc_toolbox.contracts import API_VERSION, json_data
from mdc_toolbox.runtime_adapter import OwnerRuntimeBackend
from mdc_toolbox.service import ToolboxService

MIB = 1024 * 1024
COUNTS = (0, 3, 32, 64, 128, 180)
OUT = Path(os.environ['MDC_MOVEMENT_WIRE_E2E_OUTPUT']).resolve()
FIXTURES = Path(os.environ['MDC_MOVEMENT_WIRE_FIXTURES']).resolve()
ROWS = []
NODE_CASES = []


def check(condition, reason):
    if not condition:
        raise AssertionError(reason)


def save(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as stream:
        stream.write(raw)


def store_json(path, value):
    save(path, json.dumps(value, ensure_ascii=False, allow_nan=False,
                          sort_keys=True, separators=(',', ':')).encode('utf-8'))


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def count_key(value, key):
    if isinstance(value, dict):
        return int(key in value) + sum(count_key(v, key) for v in value.values())
    if isinstance(value, list):
        return sum(count_key(v, key) for v in value)
    return 0


class Response:
    def __init__(self, raw, status=200):
        self.raw, self.status = raw, status
        self.limits = []

    def read(self, limit):
        self.limits.append(limit)
        return self.raw[:limit]

    def getheader(self, _name):
        return None


class HTTPFixture:
    def __init__(self, raw, status=200, allowed_route='/control/capability-snapshot?radius=8'):
        self.response = Response(raw, status)
        self.allowed_route = allowed_route
        self.calls = []
        self.closed = 0

    def connection(self, host, port, timeout):
        check(host == '127.0.0.1' and port == 12345, 'HTTP fixture destination changed')
        return self

    def request(self, method, path, body=None, headers=None):
        check(path == self.allowed_route, 'unexpected native endpoint')
        check(method == ('POST' if path == '/control/scoped-action' else 'GET'),
              'unexpected native method')
        self.calls.append((method, path))

    def getresponse(self):
        return self.response

    def close(self):
        self.closed += 1


class InlineQueue(QueueClient):
    """Real file mailbox + real Resident.snapshot, without running its service loop."""
    def __init__(self, resident):
        super().__init__(resident.root)
        self.resident = resident
        self.submissions = []
        self.snapshot_errors = []

    def submit(self, command, request_id=None):
        check(command.get('op') == 'observe', 'only read observation may enter fixture queue')
        check(not self.submissions, 'test must not submit or replay a second operation')
        rid = super().submit(command, request_id=request_id)
        self.submissions.append(rid)
        inbox = self.root / 'inbox' / (rid + '.json')
        working = self.root / 'working' / (rid + '.json')
        inbox.rename(working)
        queued = load_strict(working.read_bytes())
        try:
            payload = self.resident.snapshot(queued)
        except (ValueError, BridgeError) as exc:
            self.snapshot_errors.append(type(exc).__name__)
            self.resident.finish(queued, 'failed', reason='invalid_native_fixture_observation')
        else:
            self.resident.finish(queued, 'succeeded', result=payload)
        return rid


class OneRequestSource:
    """EOF follows the response, avoiding an artificial immediate-EOF shutdown race."""
    def __init__(self, request, written):
        self.request, self.written, self.used = request, written, False

    def readline(self, bound):
        if not self.used:
            self.used = True
            check(len(self.request) <= bound, 'test request exceeds read size')
            return self.request
        check(self.written.wait(20), 'production serve did not produce its one reply')
        return b''


class CaptureSink(io.BytesIO):
    def __init__(self):
        super().__init__()
        self.written = threading.Event()

    def write(self, data):
        count = super().write(data)
        self.written.set()
        return count


def serve_one(service, arguments, *, tool='mdc_observe', identity='tb_1'):
    request = json_data({'id': identity, 'tool': tool, 'arguments': arguments}) + b'\n'
    sink = CaptureSink()
    terminal = serve(service, OneRequestSource(request, sink.written), sink)
    reply = sink.getvalue()
    check(reply.endswith(b'\n') and reply.count(b'\n') == 1, 'expected one complete reply line')
    return request, reply, terminal


def chain(raw, label, *, success=True):
    parsed = load_strict(raw)
    case = OUT / 'cases' / label
    case.mkdir(parents=True, exist_ok=False)
    queue_root = case / 'queue'
    queue_root.mkdir()
    for name in ('inbox', 'working', 'results'):
        (queue_root / name).mkdir()
    bridge = Bridge('http://127.0.0.1:12345', 'synthetic-fixture-only')
    resident = Resident(bridge, queue_root)
    status = parsed['status']
    resident.bridge_identity = {'run_id': status['run_id'], 'process_id': status['process_id'],
                               'action_session': parsed['action']['action_session']}
    # No Resident.start(), no live daemon: these are explicitly fixture-only session facts.
    state = parsed['state']
    context = {'world_generation': state['world']['world_generation'],
               'dimension': state['world']['dimension'], 'player_uuid': state['player']['uuid'],
               'action_session': parsed['action']['action_session']}
    atomic_json(queue_root / 'session.json', {
        'session_id': resident.session_id, 'state': 'ready', 'pending': 0,
        'private_singleplayer': True, 'capability_context': context,
        'capability_lease_schema_version': 1, 'execution_policy': 'noncombat',
        'execution_policy_schema_version': 1})
    client = InlineQueue(resident)
    runtime = Runtime(client, case / 'runtime', clock=lambda: 100.0,
                      sleeper=lambda _: (_ for _ in ()).throw(AssertionError('unexpected wait')))
    backend = OwnerRuntimeBackend(runtime, bindings={})
    service = ToolboxService(backend, case / 'toolbox', start_workers=False)
    arguments = {'api_version': API_VERSION, 'session_ref': backend.describe()['session_ref'],
                 'profile': 'player'}
    http = HTTPFixture(raw)
    try:
        with patch('resident_controller.transport.http.client.HTTPConnection', http.connection):
            request, reply, terminal = serve_one(service, arguments)
        save(case / 'request.ndjson', request)
        save(case / 'reply.ndjson', reply)
        envelope = load_strict(reply)
        check(envelope.get('id') == 'tb_1', 'correlation ID changed')
        check(terminal == {'cleanup_confirmed': True, 'unresolved_job_ids': []}, 'shutdown not clean')
        check(len(client.submissions) == 1 and len(http.calls) == 1 and http.closed == 1,
              'chain retried or added a native request')
        check(http.response.limits == [262145], 'native response cap changed')
        rid = client.submissions[0]
        queued = client.result(rid)
        queue_raw = (queue_root / 'results' / (rid + '.json')).read_bytes()
        check(len(queue_raw) <= 2 * MIB, 'whole real queue result exceeds existing cap')
        record = runtime._journal['records'][rid]
        archive = runtime._read_evidence(record['receipt_ref'], 'receipt')
        check(exact(queued, archive), 'receipt archive changed complete queue result')
        archive_raw = gzip.decompress((runtime.journal_directory / record['receipt_ref']['file']).read_bytes())
        check(len(archive_raw) <= 32 * MIB, 'whole real archive result exceeds existing cap')
        check(digest(archive_raw) == record['receipt_ref']['sha256'], 'archive hash mismatch')
        public = envelope.get('result')
        check(type(public) is dict, 'serve substituted envelope-level transport error')
        if success:
            check(not client.snapshot_errors and 'error' not in public, 'full chain did not succeed')
            semantic = validate_snapshot(parsed, 8)
            observation = runtime._last
            check(observation is not None and observation.request_id == rid, 'actual Runtime observation missing')
            for key in ('status', 'action', 'state', 'screen'):
                check(exact(observation.raw[key], semantic[key]), 'decoded semantic sibling changed: ' + key)
            check(exact(public['state'], semantic['state']), 'public state changed or was narrowed')
            check(exact(observation.raw, queued['result']), 'Runtime raw is not the exact delivered semantic payload')
            check(len(reply) <= MAX_LINE == MIB, 'complete public reply exceeds Python bound')
            check(count_key(public, 'raw_utf8') == 0 and count_key(public, REFERENCE) == 0,
                  'public reply contains raw bytes or unresolved reference')
            check(public['execution_authority'] is False and public['executable_authority'] is False
                  and public['server_confirmed'] is False, 'read-only scope changed')
            provenance = public['provenance']
            if MARKER in parsed:
                wire = observation.raw['native_capability_wire']
                check(wire['raw_utf8'].encode('utf-8') == raw, 'original UTF8 wire was changed')
                check(wire['bytes'] == len(raw) and wire['sha256'] == digest(raw), 'raw metadata mismatch')
                check(count_key(observation.raw, 'raw_utf8') == 1 and count_key(archive, 'raw_utf8') == 1,
                      'raw UTF8 evidence is missing or duplicated within receipt')
                check(set(provenance) == {'original_request_id', 'world_context', 'historical_pages',
                    'grants_dispatch_authority', 'state_representation', 'native_wire_encoding',
                    'native_wire_bytes', 'native_wire_sha256'}, 'public provenance schema changed')
                check(provenance['native_wire_encoding'] == wire['encoding']
                      and provenance['native_wire_bytes'] == len(raw)
                      and provenance['native_wire_sha256'] == digest(raw)
                      and provenance['state_representation'] == 'decoded-semantic-native-siblings',
                      'compact public provenance lost binding')
                check(MARKER not in observation.raw and count_key(observation.raw, REFERENCE) == 0,
                      'raw envelope was substituted for decoded Runtime payload')
                check(MARKER in load_strict(wire['raw_utf8'])
                      and count_key(load_strict(wire['raw_utf8']), REFERENCE) == 2,
                      'retained wire was substituted with decoded semantic siblings')
            else:
                check('native_capability_wire' not in observation.raw
                      and count_key(archive, 'raw_utf8') == 0, 'legacy reply invented encoded provenance')
                check(not any(k.startswith('native_wire_') for k in provenance), 'legacy public provenance changed')
        else:
            check(bool(client.snapshot_errors), 'invalid reference unexpectedly admitted')
            check(runtime._last is None and public.get('error', {}).get('code') == 'observation_unavailable',
                  'invalid reference did not fail closed through public service')
            check(public['error']['effect_certainty'] == 'none_proven', 'known failed read became uncertain')
        check(record['status'] in ('succeeded', 'failed') and not runtime.has_unresolved_execution,
              'terminal original queue result lost')
        check(runtime._job_control is None and not backend._lock.locked(), 'owner cleanup incomplete')
        NODE_CASES.append({'label': label, 'reply': str((case / 'reply.ndjson').relative_to(OUT)),
                           'request': str((case / 'request.ndjson').relative_to(OUT)),
                           'reply_bytes': len(reply), 'reply_sha256': digest(reply)})
        ROWS.append({'case': label, 'native_bytes': len(raw), 'queue_bytes': len(queue_raw),
                     'archive_bytes': len(archive_raw), 'python_reply_bytes': len(reply),
                     'reply_sha256': digest(reply), 'expected_success': success,
                     'native_calls': len(http.calls), 'queue_submissions': len(client.submissions)})
    finally:
        service.shutdown()
        runtime.close()


class ValueService:
    def __init__(self, result):
        self.value = result
        self.calls = 0
        self.shutdown_result = None

    def call(self, tool, arguments):
        self.calls += 1
        return deepcopy(self.value)

    def shutdown(self):
        self.shutdown_result = {'cleanup_confirmed': True, 'unresolved_job_ids': []}
        return self.shutdown_result


class FullReplyTests(unittest.TestCase):
    def test_01_generated_coherent_and_legacy_full_chain(self):
        sizes = load_strict((FIXTURES / 'producer-case-sizes.json').read_bytes())
        by_count = {row['nonself_rows']: row for row in sizes['representative_cases']}
        check(set(by_count) == set(COUNTS), 'producer case set changed')
        intent = load_strict((FIXTURES / 'original-intent.json').read_bytes())
        scoped_request = load_strict((FIXTURES / 'original-request.json').read_bytes())
        for count in COUNTS:
            for prefix, key in (('coherent', 'single_authority_bytes'), ('legacy-inline', 'legacy_three_copy_bytes')):
                label = f'{prefix}-{count}'
                raw = (FIXTURES / (label + '.json')).read_bytes()
                check(len(raw) == by_count[count][key], 'actual producer size report mismatch')
                semantic = validate_snapshot(load_strict(raw), 8)
                validate_scoped_witness(semantic['action'], scoped_request, intent['action_id'], intent)
                check(len(semantic['action']['result'][WITNESS]['facts']['movement']['entity_guard']['rows']) == count,
                      'actual generated entity frame count changed')
                if len(raw) <= 262144:
                    chain(raw, label)
                else:
                    fixture = HTTPFixture(raw)
                    with patch('resident_controller.transport.http.client.HTTPConnection', fixture.connection):
                        with self.assertRaises(BridgeError) as caught:
                            Bridge('http://127.0.0.1:12345', 'synthetic-fixture-only').request(
                                'GET', '/control/capability-snapshot?radius=8')
                    check(caught.exception.code == 'response_too_large' and not caught.exception.uncertain,
                          'oversized producer body did not retain existing native refusal')
                    ROWS.append({'case': label, 'native_bytes': len(raw),
                                 'expected_native_refusal': 'response_too_large', 'no_downstream_success_claim': True})
            raw = (FIXTURES / f'standalone-{count}.json').read_bytes()
            check(len(raw) == by_count[count]['standalone_bytes'], 'standalone actual producer size mismatch')
            fixture = HTTPFixture(raw, allowed_route='/control/action/status')
            with patch('resident_controller.transport.http.client.HTTPConnection', fixture.connection):
                bridge = Bridge('http://127.0.0.1:12345', 'synthetic-fixture-only')
                if len(raw) <= 262144:
                    action = bridge.request('GET', '/control/action/status')
                    check(exact(action, load_strict(raw)), 'standalone wire semantic changed')
                    validate_scoped_witness(action, scoped_request, intent['action_id'], intent)
                    check(bridge.last_capability_wire is None, 'standalone invented coherent-wire provenance')
                else:
                    with self.assertRaises(BridgeError) as caught:
                        bridge.request('GET', '/control/action/status')
                    check(caught.exception.code == 'response_too_large', 'standalone limit changed')
        chain((FIXTURES / 'coherent-at-reserved-limit.json').read_bytes(), 'coherent-at-reserved-limit')

    def test_02_invalid_reference_full_chain_and_original_bytes_binding(self):
        raw = (FIXTURES / 'coherent-3.json').read_bytes()
        original = load_strict(raw)
        for label, change in (
            ('cross-owner', lambda b: b['state']['client_action']['result'][REFERENCE].update(owner_id='f' * 32)),
            ('external-target', lambda b: b['status']['client_action']['result'][REFERENCE].update(path='https://invalid.example/witness')),
            ('missing-authority', lambda b: b['action']['result'].pop(WITNESS)),
        ):
            changed = deepcopy(original)
            change(changed)
            chain(json_bytes(changed), 'invalid-' + label, success=False)
        # Real Runtime must reject a semantic body edited after a valid Resident decode.
        valid = OUT / 'cases' / 'coherent-3'
        queued_files = list((valid / 'queue' / 'results').glob('*.json'))
        check(len(queued_files) == 1, 'missing prior retained full result')
        result = load_strict(queued_files[0].read_bytes())
        runtime = Runtime(object(), OUT / 'tamper-runtime', clock=lambda: 100.0)
        try:
            for label in ('semantic', 'raw', 'hash', 'missing-provenance'):
                changed = deepcopy(result)
                payload = changed['result']
                if label == 'semantic':
                    payload['state']['client_action']['result'][WITNESS]['facts']['movement']['cells'][0]['state'] += '-edited'
                elif label == 'raw':
                    payload['native_capability_wire']['raw_utf8'] += ' '
                elif label == 'hash':
                    payload['native_capability_wire']['sha256'] = 'f' * 64
                else:
                    # An unresolved encoded reference without provenance must not pass as legacy.
                    payload.pop('native_capability_wire')
                    payload['state']['client_action']['result'][REFERENCE] = deepcopy(
                        original['state']['client_action']['result'][REFERENCE])
                with self.assertRaises(SkillError) as caught:
                    runtime._make_observation(changed, 100.0, allow_menu=True)
                check(caught.exception.reason == 'invalid_native_capability_wire_provenance',
                      'tampered representation failed for an unrelated reason')
                check(runtime._last is None, 'tampered raw/decoded data became a Runtime observation')
        finally:
            runtime.close()
        ROWS.append({'case': 'raw-vs-decoded-negative-bindings', 'negative_cases': 4})

    def test_03_existing_queue_exact_limit_plus_one(self):
        root = OUT / 'queue-boundary'
        (root / 'results').mkdir(parents=True)
        client = QueueClient(root)
        for size in (2 * MIB, 2 * MIB + 1):
            label = 'at' if size == 2 * MIB else 'over'
            value = {'request_id': label, 'status': 'succeeded', 'synthetic_size_padding': ''}
            value['synthetic_size_padding'] = 'x' * (size - len(json_bytes(value)))
            encoded = json_bytes(value)
            check(len(encoded) == size, 'queue exact-size construction failed')
            save(root / 'results' / (label + '.json'), encoded)
            if size == 2 * MIB:
                check(exact(client.result(label), value), 'queue rejected/changed exact limit')
            else:
                with self.assertRaisesRegex(ValueError, '^mailbox_file_too_large$'):
                    client.result(label)
        ROWS.append({'case': 'queue-limit', 'accepted_bytes': 2 * MIB, 'rejected_bytes': 2 * MIB + 1})

    def test_04_existing_archive_exact_limit_plus_one(self):
        runtime = Runtime(object(), OUT / 'archive-boundary')
        try:
            for size in (32 * MIB, 32 * MIB + 1):
                rid = ('a' if size == 32 * MIB else 'b') * 32
                record = {'request_id': rid}
                value = {'request_id': rid, 'status': 'succeeded', 'synthetic_size_padding': ''}
                value['synthetic_size_padding'] = 'x' * (size - len(_json(value)))
                check(len(_json(value)) == size, 'archive exact-size construction failed')
                before = set(runtime.journal_directory.glob('receipt-*'))
                if size == 32 * MIB:
                    runtime._receipt(record, value)
                    check(record['receipt_ref']['bytes'] == size, 'archive exact limit metadata changed')
                    check(exact(runtime._read_evidence(record['receipt_ref'], 'receipt'), value),
                          'archive exact-limit readback changed result')
                    store_json(OUT / 'archive-boundary-ref.json', record)
                else:
                    with self.assertRaises(SkillError) as caught:
                        runtime._receipt(record, value)
                    check(caught.exception.reason == 'receipt_evidence_capacity_exhausted', 'archive cap changed')
                    check('receipt_ref' not in record and before == set(runtime.journal_directory.glob('receipt-*')),
                          'over-limit archive left a success artifact')
        finally:
            runtime.close()
        ROWS.append({'case': 'archive-limit', 'accepted_bytes': 32 * MIB, 'rejected_bytes': 32 * MIB + 1})

    def test_05_python_full_reply_exact_limit_plus_one(self):
        check(MAX_LINE == MIB, 'Python transport line limit changed')
        for size in (MIB, MIB + 1):
            label = 'python-line-at' if size == MIB else 'python-line-over'
            result = {'synthetic_boundary_only': True, 'padding': ''}
            base = len(json_data({'id': 'tb_1', 'result': result}) + b'\n')
            padding = size - base
            result['padding'] = '界' * (padding // 3) + 'x' * (padding % 3)
            original = json_data({'id': 'tb_1', 'result': result}) + b'\n'
            check(len(original) == size, 'Python UTF8 exact-size construction failed')
            service = ValueService(result)
            request, reply, terminal = serve_one(service, {})
            case = OUT / 'cases' / label
            save(case / 'original-result.ndjson', original)
            save(case / 'request.ndjson', request)
            save(case / 'reply.ndjson', reply)
            check(service.calls == 1 and terminal['cleanup_confirmed'], 'serve replayed boundary call')
            parsed = load_strict(reply)
            if size == MIB:
                check(reply == original, 'Python rejected/changed exact full-line bound')
            else:
                check(parsed.get('id') == 'tb_1' and parsed.get('error', {}).get('code') == 'response_too_large'
                      and 'result' not in parsed, 'Python +1 did not produce explicit correlated refusal')
            NODE_CASES.append({'label': label, 'reply': str((case / 'reply.ndjson').relative_to(OUT)),
                'request': str((case / 'request.ndjson').relative_to(OUT)),
                'reply_bytes': len(reply), 'reply_sha256': digest(reply)})
            ROWS.append({'case': label, 'original_full_reply_bytes': size, 'actual_full_reply_bytes': len(reply),
                         'correlated_transport_error': size > MIB})

    def test_06_known_size_refusal_and_synthetic_undiagnosed_refusal(self):
        raw = (FIXTURES / 'size-refusal.json').read_bytes()
        fixture = HTTPFixture(raw, status=409, allowed_route='/control/scoped-action')
        with patch('resident_controller.transport.http.client.HTTPConnection', fixture.connection):
            with self.assertRaises(BridgeError) as caught:
                Bridge('http://127.0.0.1:12345', 'synthetic-fixture-only').request('POST', '/control/scoped-action', {})
        error = caught.exception
        check(error.status == 409 and not error.uncertain, 'known native refusal became uncertain')
        admission = action_rejection_admission(error)
        check(admission['admitted'] is False and admission['uncertain'] is False
              and valid_size_diagnostic(admission['scoped_movement_response_size']), 'known native size diagnostic lost')
        store_json(OUT / 'known-size-refusal-admission.json', admission)
        # Synthetic negative without diagnostics. No historical/live receipt is used.
        raw = b'{"error":"scoped_movement_response_evidence_too_large"}'
        undiagnosed = HTTPFixture(raw, status=409, allowed_route='/control/scoped-action')
        with patch('resident_controller.transport.http.client.HTTPConnection', undiagnosed.connection):
            with self.assertRaises(BridgeError) as refused:
                Bridge('http://127.0.0.1:12345', 'synthetic-fixture-only').request('POST', '/control/scoped-action', {})
        negative = action_rejection_admission(refused.exception)
        check(negative == {'schema_version': 1, 'http_status': 409, 'admitted': False,
                           'uncertain': False, 'reason': 'scoped_movement_response_evidence_too_large'},
              'synthetic known refusal gained an admission, witness or retrospective diagnostic')
        check(len(fixture.calls) == len(undiagnosed.calls) == 1
              and fixture.closed == undiagnosed.closed == 1, 'definite refusal was retried')
        store_json(OUT / 'synthetic-undiagnosed-refusal-admission.json', negative)
        ROWS.append({'case': 'synthetic-definite-refusals', 'synthetic_witness_available': False,
                     'native_http_calls': len(fixture.calls) + len(undiagnosed.calls),
                     'native_dispatch_performed': False})



def main():
    # Test code may not spawn a service or accidentally connect a network socket.
    from offline_guards import offline_python
    with offline_python():
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(FullReplyTests)
        result = unittest.TextTestRunner(verbosity=2).run(suite)
    report = {'schema': 'mdc.full-reply-python-report/1', 'scope': 'offline synthetic native facts; actual production consumers',
              'tests_run': result.testsRun, 'failures': len(result.failures), 'errors': len(result.errors),
              'success': result.wasSuccessful(), 'cases': ROWS, 'game_or_service_started': False}
    store_json(OUT / 'python-report.json', report)
    if result.wasSuccessful():
        store_json(OUT / 'node-cases.json', {'schema': 'mdc.full-reply-node-input/1', 'cases': NODE_CASES})
    print(json.dumps({'success': result.wasSuccessful(), 'tests_run': result.testsRun, 'case_count': len(ROWS)}))
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    sys.exit(main())
