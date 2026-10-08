"""HTTP transport unit tests. All socket/HTTP/timer operations are mocked.

These tests never start a listener, resolve a host, connect a socket, read a
credential, or contact the game. They establish source behavior only.
"""
from dataclasses import replace
import json
import io
import socket
import unittest
from unittest.mock import Mock, patch

from navigation_controller.http_transport import (
    MAX_JSON_BYTES, LoopbackConfig, LoopbackHttpTransport, TransportError,
    _NumericLoopbackConnection,
)


PREFIX = 'navigation_controller.http_transport.'
# Deliberately fabricated, public unit-test data; not an actual credential.
TEST_TOKEN = 'unit-test-token-not-a-secret'
UUIDS = [f'00000000-0000-0000-0000-{n:012d}' for n in range(1, 6)]


def movement_body():
    return dict(zip(('session', 'request_id', 'observation_id',
                     'expected_world_generation', 'expected_player_uuid'), UUIDS),
                movement_schema_version=1, action='forward_sample',
                expected_tick=100, expected_x=.5, expected_y=64, expected_z=.5,
                expected_yaw=0, ttl_ms=100, duration_ms=100)


def turn_body():
    body = movement_body()
    del body['movement_schema_version'], body['duration_ms']
    body.update(turn_schema_version=1, action='yaw', target_yaw=29.99)
    return body


class MockedNetworkCase(unittest.TestCase):
    def setUp(self):
        # Fail rather than ever opening a real socket if a mock is incomplete.
        self.socket_factory = self.enterContext(patch(PREFIX + 'socket.socket',
                                      side_effect=AssertionError('real socket forbidden')))
        self.dns = self.enterContext(patch(PREFIX + 'socket.getaddrinfo',
                                      side_effect=AssertionError('DNS forbidden')))
        self.timer_factory = self.enterContext(patch(PREFIX + 'threading.Timer'))
        self.timer = self.timer_factory.return_value

    def tearDown(self):
        self.dns.assert_not_called()

    def config(self, **changes):
        return LoopbackConfig('http://127.0.0.1:8765', TEST_TOKEN, **changes)


class ConfigTests(MockedNetworkCase):
    def test_explicit_endpoint_and_token_required(self):
        with self.assertRaises(TypeError):
            LoopbackConfig()
        with self.assertRaises(TypeError):
            LoopbackConfig('http://127.0.0.1:8765')

    def test_numeric_loopback_only_and_no_construction_network(self):
        for url, host in [('http://127.0.0.1:1', '127.0.0.1'),
                          ('http://[::1]:65535', '::1')]:
            with self.subTest(url=url):
                config = replace(self.config(), base_url=url)
                transport = LoopbackHttpTransport(config)
                self.assertEqual(config._host, host)
                self.assertIs(transport.config, config)
                self.assertFalse(transport.simulation_only)
                self.assertFalse(config.enabled)
                self.assertFalse(config.acceptance_verified)
                self.assertEqual(config.timeout_s, .5)
        self.socket_factory.assert_not_called()
        self.timer_factory.assert_not_called()

    def test_invalid_endpoints(self):
        urls = ['https://127.0.0.1:8765', 'http://localhost:8765',
                'http://127.0.0.2:8765', 'http://0.0.0.0:8765',
                'http://192.168.1.1:8765', 'http://2130706433:8765',
                'http://127.1:8765', 'http://127.0.0.1',
                'http://127.0.0.1:0', 'http://127.0.0.1:65536',
                'http://127.0.0.1:08765', 'http://127.0.0.1:+8765',
                'http://[::ffff:127.0.0.1]:8765', 'http://[::01]:8765',
                'http://[::1%lo]:8765', 'http://::1:8765',
                'http://user@127.0.0.1:8765', 'http://127.0.0.1:8765/',
                'http://127.0.0.1:8765/control', 'http://127.0.0.1:8765?',
                'http://127.0.0.1:8765#', 'http://127.0.0.1:8765\n',
                ' http://127.0.0.1:8765', None, 123, True]
        for url in urls:
            with self.subTest(url=url), self.assertRaisesRegex(TransportError, 'base_url'):
                replace(self.config(), base_url=url)

    def test_token_redacted_and_header_injection_rejected(self):
        self.assertNotIn(TEST_TOKEN, repr(self.config()))
        for token in ['', None, True, 'hello world', 'x\r\nInjected: yes',
                      '\x00', 'é', 'x' * 4097]:
            with self.subTest(token_type=type(token).__name__):
                with self.assertRaisesRegex(TransportError, '^invalid_caller_token$'):
                    replace(self.config(), token=token)

    def test_flags_and_bounded_finite_timeout(self):
        for key in ('enabled', 'acceptance_verified'):
            for value in (0, 1, 'true', None):
                with self.subTest(key=key, value=value), self.assertRaises(TransportError):
                    replace(self.config(), **{key: value})
        for timeout in (0, .049, 2.001, -1, float('inf'), float('nan'), True, '0.5', None):
            with self.subTest(timeout=timeout), self.assertRaises(TransportError):
                replace(self.config(), timeout_s=timeout)
        for timeout in (.05, .5, 2):
            self.assertEqual(replace(self.config(), timeout_s=timeout).timeout_s, timeout)


class RequestTests(MockedNetworkCase):
    def setUp(self):
        super().setUp()
        self.connection_factory = self.enterContext(patch(PREFIX + '_NumericLoopbackConnection'))
        self.connection = self.connection_factory.return_value
        self.response = self.connection.getresponse.return_value
        self.response.status = 200
        self.response.getheaders.return_value = [('Content-Type', 'application/json; charset=utf-8')]
        self.response.read.return_value = b'{"ok":true}'
        self.transport = LoopbackHttpTransport(self.config())

    def test_canonical_read_paths_and_bounds(self):
        paths = ['/control/capabilities', '/control/status', '/control/state?radius=0',
                 '/control/state?radius=4', '/control/terrain?radius=0&vertical=0&limit=1',
                 '/control/terrain?radius=16&vertical=8&limit=128',
                 '/control/terrain?cursor=' + UUIDS[0] + ':1',
                 '/control/terrain?cursor=' + UUIDS[0] + ':18513']
        for path in paths:
            with self.subTest(path=path):
                self.assertEqual(self.transport.request('GET', path), {'ok': True})
                self.connection.request.assert_called_with('GET', path, body=None,
                    headers={'Authorization': 'Bearer ' + TEST_TOKEN,
                             'Accept': 'application/json', 'Connection': 'close'})
        self.assertEqual(self.connection_factory.call_count, len(paths))
        self.connection_factory.assert_called_with('127.0.0.1', 8765, .5)
        self.socket_factory.assert_not_called()

    def test_forbidden_reads_never_create_connection(self):
        paths = ['/control/state', '/control/state?radius=1', '/control/status?',
                 '/control/terrain', '/control/terrain?radius=17&vertical=1&limit=128',
                 '/control/terrain?radius=1&vertical=9&limit=128',
                 '/control/terrain?radius=1&vertical=1&limit=129',
                 '/control/terrain?radius=1&vertical=1&limit=0',
                 '/control/terrain?radius=01&vertical=1&limit=128',
                 '/control/terrain?vertical=1&radius=1&limit=128',
                 '/control/terrain?radius=1&vertical=1&limit=128&radius=1',
                 '/control/terrain?cursor=' + UUIDS[0] + ':0',
                 '/control/terrain?cursor=' + UUIDS[0] + ':01',
                 '/control/terrain?cursor=' + UUIDS[0] + ':18514',
                 '/control/terrain?cursor=' + UUIDS[0] + '%3A1',
                 '/control/terrain?cursor=' + UUIDS[0] + ':1&limit=1',
                 '/control/status#fragment', '/control/status\r\n',
                 'http://127.0.0.1:8765/control/status', '/control/release-all',
                 '/control/look', '/control/input', '/control/guarded-movement', None, {}]
        for path in paths:
            with self.subTest(path=path), self.assertRaises(TransportError):
                self.transport.request('GET', path)
        self.connection_factory.assert_not_called()

    def test_only_exact_get_and_post_and_no_get_body(self):
        for method in ('get', 'post', 'PUT', 'DELETE', 'HEAD', None, {}):
            with self.subTest(method=method), self.assertRaises(TransportError):
                self.transport.request(method, '/control/status')
        with self.assertRaisesRegex(TransportError, 'get_body'):
            self.transport.request('GET', '/control/status', {})
        self.connection_factory.assert_not_called()

    def test_post_requires_both_independent_opt_ins(self):
        for enabled, accepted in [(False, False), (True, False), (False, True)]:
            transport = LoopbackHttpTransport(self.config(enabled=enabled, acceptance_verified=accepted))
            with self.subTest(enabled=enabled, accepted=accepted):
                with self.assertRaisesRegex(TransportError, 'mutation_not_accepted'):
                    transport.request('POST', '/control/guarded-movement', movement_body())
                self.assertEqual(transport.request('GET', '/control/status'), {'ok': True})
        self.assertEqual(self.connection.request.call_count, 3)

    def enabled(self):
        return LoopbackHttpTransport(self.config(enabled=True, acceptance_verified=True))

    def test_exact_guarded_writes_json_and_one_sample(self):
        transport = self.enabled()
        for path, body in [('/control/guarded-movement', movement_body()),
                           ('/control/guarded-turn', turn_body())]:
            with self.subTest(path=path):
                transport = self.enabled()
                self.assertEqual(transport.request('POST', path, body), {'ok': True})
                args, kwargs = self.connection.request.call_args
                self.assertEqual(args, ('POST', path))
                self.assertEqual(json.loads(kwargs['body']), body)
                self.assertEqual(kwargs['headers']['Content-Type'], 'application/json')
                self.assertNotIn('key', kwargs['body'].decode())
        self.assertEqual(self.connection.request.call_count, 2)

    def test_single_post_budget_never_resets_and_readback_remains_allowed(self):
        transport = self.enabled()
        transport.request('POST', '/control/guarded-movement', movement_body())
        for path, body in [('/control/guarded-movement', movement_body()),
                           ('/control/guarded-turn', turn_body())]:
            with self.subTest(path=path):
                with self.assertRaisesRegex(TransportError, '^single_action_budget_exhausted$'):
                    transport.request('POST', path, body)
        self.connection_factory.assert_called_once()
        self.assertEqual(transport.request('GET', '/control/status'), {'ok': True})
        self.assertEqual(self.connection_factory.call_count, 2)
        with self.assertRaisesRegex(TransportError, '^single_action_budget_exhausted$'):
            transport.request('POST', '/control/guarded-movement', movement_body())
        self.assertEqual(self.connection_factory.call_count, 2)

    def test_first_http_error_consumes_single_post_budget(self):
        transport = self.enabled()
        self.response.status = 409
        with self.assertRaisesRegex(TransportError, '^unexpected_http_status$'):
            transport.request('POST', '/control/guarded-turn', turn_body())
        self.response.read.assert_not_called()
        self.response.status = 200
        with self.assertRaisesRegex(TransportError, '^single_action_budget_exhausted$'):
            transport.request('POST', '/control/guarded-movement', movement_body())
        self.connection_factory.assert_called_once()
        self.assertEqual(transport.request('GET', '/control/state?radius=4'), {'ok': True})

    def test_ambiguous_dispatch_failure_consumes_single_post_budget(self):
        transport = self.enabled()
        self.connection.request.side_effect = OSError('ambiguous exchange')
        with self.assertRaisesRegex(TransportError, '^request_failed$'):
            transport.request('POST', '/control/guarded-movement', movement_body())
        self.connection.request.side_effect = None
        with self.assertRaisesRegex(TransportError, '^single_action_budget_exhausted$'):
            transport.request('POST', '/control/guarded-turn', turn_body())
        self.connection_factory.assert_called_once()
        self.assertEqual(transport.request('GET', '/control/status'), {'ok': True})

    def test_connection_construction_failure_does_not_refund_post_admission(self):
        transport = self.enabled()
        self.connection_factory.side_effect = OSError('creation failure')
        with self.assertRaisesRegex(TransportError, '^request_failed$'):
            transport.request('POST', '/control/guarded-movement', movement_body())
        self.connection_factory.side_effect = None
        with self.assertRaisesRegex(TransportError, '^single_action_budget_exhausted$'):
            transport.request('POST', '/control/guarded-movement', movement_body())
        self.connection_factory.assert_called_once()

    def test_invalid_request_can_be_corrected_before_post_admission(self):
        transport = self.enabled()
        with self.assertRaisesRegex(TransportError, '^invalid_request_fields$'):
            transport.request('POST', '/control/guarded-movement',
                              {**movement_body(), 'key': 'w'})
        self.connection_factory.assert_not_called()
        transport.request('POST', '/control/guarded-movement', movement_body())
        self.connection_factory.assert_called_once()
        with self.assertRaisesRegex(TransportError, '^single_action_budget_exhausted$'):
            transport.request('POST', '/control/guarded-turn', turn_body())
        self.connection_factory.assert_called_once()

    def test_concurrent_second_post_fails_without_second_connection(self):
        transport = self.enabled()
        def while_first_dispatches(*args, **kwargs):
            with self.assertRaisesRegex(TransportError, '^transport_busy$'):
                transport.request('POST', '/control/guarded-turn', turn_body())
            self.connection_factory.assert_called_once()
        self.connection.request.side_effect = while_first_dispatches
        transport.request('POST', '/control/guarded-movement', movement_body())
        self.connection_factory.assert_called_once()
        self.assertEqual(self.connection.request.call_count, 1)
        self.connection.request.side_effect = None
        with self.assertRaisesRegex(TransportError, '^single_action_budget_exhausted$'):
            transport.request('POST', '/control/guarded-turn', turn_body())
        self.connection_factory.assert_called_once()

    def test_no_legacy_query_or_unknown_post(self):
        transport = self.enabled()
        for path in ('/control/release-all', '/control/look', '/control/input',
                     '/control/guarded-turn?', '/control/guarded-movement?x=1',
                     '/control/guarded-movement/', '/control/status'):
            with self.subTest(path=path), self.assertRaises(TransportError):
                transport.request('POST', path, movement_body())
        self.connection_factory.assert_not_called()

    def test_exact_body_fields_and_actions(self):
        transport = self.enabled()
        bodies = [None, [], '{}', {}, {**movement_body(), 'key': 'w'},
                  {**movement_body(), 'action': 'forward'},
                  {**movement_body(), 'movement_schema_version': True},
                  {**movement_body(), 'movement_schema_version': 1.0},
                  {**movement_body(), 'movement_schema_version': 2}, turn_body()]
        for key in movement_body():
            body = movement_body()
            del body[key]
            bodies.append(body)
        for body in bodies:
            with self.subTest(body=body), self.assertRaises(TransportError):
                transport.request('POST', '/control/guarded-movement', body)
        self.connection_factory.assert_not_called()

    def test_all_identities_are_canonical_uuid(self):
        transport = self.enabled()
        for key in ('session', 'request_id', 'observation_id', 'expected_world_generation', 'expected_player_uuid'):
            for invalid in ('not-a-uuid', 'ABCDEFAB-0000-0000-0000-000000000001',
                            '00000000000000000000000000000001', '{' + UUIDS[0] + '}', None, 1):
                body = movement_body()
                body[key] = invalid
                with self.subTest(key=key, invalid=invalid), self.assertRaises(TransportError):
                    transport.request('POST', '/control/guarded-movement', body)
        self.connection_factory.assert_not_called()

    def test_exact_tick_position_yaw_and_lease_bounds(self):
        transport = self.enabled()
        invalid_fields = {
            'expected_tick': [-1, 2**53, 1.0, True, '100'],
            'expected_x': [-30_000_001, 30_000_001, float('nan'), float('inf'), True, '0', 10**400],
            'expected_y': [float('-inf'), -30_000_001],
            'expected_z': [float('nan'), 30_000_001],
            'expected_yaw': [-181, 180, float('nan'), True],
            'ttl_ms': [0, 251, 100.0, True, '100'],
            'duration_ms': [0, 101, 1.0, True, '100'],
        }
        for key, values in invalid_fields.items():
            for value in values:
                body = movement_body()
                body[key] = value
                with self.subTest(key=key, value=value), self.assertRaises(TransportError):
                    transport.request('POST', '/control/guarded-movement', body)
        body = movement_body()
        body.update(ttl_ms=10, duration_ms=11)
        with self.assertRaises(TransportError):
            transport.request('POST', '/control/guarded-movement', body)
        self.connection_factory.assert_not_called()

    def test_valid_request_boundaries(self):
        transport = self.enabled()
        body = movement_body()
        body.update(expected_tick=2**53 - 1, expected_x=30_000_000, expected_y=-30_000_000,
                    expected_z=30_000_000, expected_yaw=-180, ttl_ms=250, duration_ms=100)
        transport.request('POST', '/control/guarded-movement', body)
        body.update(expected_tick=0, ttl_ms=1, duration_ms=1)
        transport = self.enabled()
        transport.request('POST', '/control/guarded-movement', body)
        self.assertEqual(self.connection.request.call_count, 2)

    def test_turn_schema_lease_and_float32_bound(self):
        transport = self.enabled()
        for changes in ({'ttl_ms': 101}, {'ttl_ms': 0}, {'ttl_ms': True},
                        {'duration_ms': 100}, {'action': 'forward_sample'},
                        {'turn_schema_version': True}, {'target_yaw': float('nan')},
                        {'target_yaw': 180}, {'target_yaw': -181}, {'target_yaw': 30.01},
                        {'expected_yaw': .1, 'target_yaw': 30.1}):
            body = turn_body()
            body.update(changes)
            with self.subTest(changes=changes), self.assertRaises(TransportError):
                transport.request('POST', '/control/guarded-turn', body)
        self.connection_factory.assert_not_called()
        for yaw, target in ((0, 30), (0, -30), (179, -179), (-179, 179), (179, 179.999999)):
            body = turn_body()
            body.update(expected_yaw=yaw, target_yaw=target)
            transport = self.enabled()
            transport.request('POST', '/control/guarded-turn', body)
        self.assertEqual(self.connection.request.call_count, 5)

    def test_close_stop_are_idempotent_local_only(self):
        for name in ('stop', 'close'):
            with self.subTest(name=name):
                transport = self.enabled()
                getattr(transport, name)()
                getattr(transport, name)()
                with self.assertRaisesRegex(TransportError, 'transport_closed'):
                    transport.request('GET', '/control/status')
                with self.assertRaisesRegex(TransportError, 'transport_closed'):
                    transport.request('POST', '/control/guarded-movement', movement_body())
        self.connection_factory.assert_not_called()

    def test_concurrent_admission_rejected_without_wait(self):
        self.transport._inflight.acquire()
        try:
            with self.assertRaisesRegex(TransportError, 'transport_busy'):
                self.transport.request('GET', '/control/status')
        finally:
            self.transport._inflight.release()
        self.connection_factory.assert_not_called()

    def test_timer_and_per_operation_timeouts_cleaned_up(self):
        self.transport.request('GET', '/control/status')
        interval, callback = self.timer_factory.call_args.args
        self.assertGreater(interval, 0)
        self.assertLessEqual(interval, .5)
        self.assertTrue(self.timer.daemon)
        self.timer.start.assert_called_once_with()
        self.timer.cancel.assert_called_once_with()
        self.timer.join.assert_called_once_with()
        self.assertEqual(self.connection.set_remaining_timeout.call_count, 3)
        for call in self.connection.set_remaining_timeout.call_args_list:
            self.assertGreater(call.args[0], 0)
            self.assertLessEqual(call.args[0], .5)
        self.response.read.assert_called_once_with(MAX_JSON_BYTES + 1)
        self.response.close.assert_called_once_with()
        self.connection.close.assert_called_once_with()

    def fire_timer(self):
        self.timer_factory.call_args.args[1]()

    def test_timer_expiry_aborts_during_each_io_stage(self):
        for stage in ('request', 'getresponse', 'read'):
            self.connection.reset_mock(side_effect=True)
            self.connection.getresponse.return_value = self.response
            self.response.reset_mock(side_effect=True)
            self.response.status = 200
            self.response.getheaders.return_value = [('Content-Type', 'application/json')]
            self.response.read.return_value = b'{}'
            operation = self.response.read if stage == 'read' else getattr(self.connection, stage)
            return_value = b'{}' if stage == 'read' else self.response if stage == 'getresponse' else None
            operation.side_effect = lambda *a, result=return_value, **k: (self.fire_timer(), result)[1]
            with self.subTest(stage=stage), self.assertRaisesRegex(TransportError, 'operation_deadline'):
                self.transport.request('GET', '/control/status')
            self.connection.abort.assert_called_once_with()
            self.connection.close.assert_called_once_with()
            self.assertEqual(self.connection.request.call_count, 1)
            self.assertFalse(self.transport._inflight.locked())

    def test_timeout_before_connect_prevents_request(self):
        self.timer.start.side_effect = self.fire_timer
        with self.assertRaisesRegex(TransportError, 'operation_deadline'):
            self.transport.request('GET', '/control/status')
        self.connection.request.assert_not_called()
        self.connection.abort.assert_called_once_with()

    def test_elapsed_total_deadline_even_if_timer_not_scheduled(self):
        with patch(PREFIX + 'time.monotonic', side_effect=[10, 10, 10, 10.2, 10.51]):
            with self.assertRaisesRegex(TransportError, 'operation_deadline'):
                self.transport.request('GET', '/control/status')
        self.response.read.assert_not_called()
        self.connection.close.assert_called_once_with()

    def test_stop_during_exchange_closes_socket_without_cancel_request(self):
        self.connection.request.side_effect = lambda *a, **kw: self.transport.stop()
        with self.assertRaisesRegex(TransportError, 'transport_closed'):
            self.transport.request('GET', '/control/status')
        self.connection.abort.assert_called_once_with()
        self.assertEqual(self.connection.request.call_count, 1)
        self.connection.getresponse.assert_not_called()

    def test_non_200_errors_never_read_body_or_follow_redirect(self):
        for status in (201, 204, 301, 302, 307, 308, 400, 401, 403, 408, 409, 429, 500, 503, True):
            self.response.status = status
            with self.subTest(status=status), self.assertRaisesRegex(TransportError, '^unexpected_http_status$') as raised:
                self.transport.request('GET', '/control/status')
            if type(status) is int and 100 <= status <= 599:
                self.assertEqual(raised.exception.http_status,status)
            else:
                self.assertFalse(hasattr(raised.exception,'http_status'))
        self.response.read.assert_not_called()
        self.assertEqual(self.connection.request.call_count, 15)

    def test_response_headers_and_limit(self):
        invalid = [[], [('Content-Type', 'text/html')],
                   [('Content-Type', 'application/json'), ('Content-Encoding', 'gzip')],
                   [('Content-Type', 'application/json'), ('Content-Type', 'application/json')],
                   [('Content-Type', 'application/json'), ('Content-Length', '-1')],
                   [('Content-Type', 'application/json'), ('Content-Length', str(MAX_JSON_BYTES + 1))],
                   [('Content-Type', 'application/json'), ('Content-Length', '1'), ('Content-Length', '1')],
                   [('Content-Type', 'application/json'), ('Transfer-Encoding', 'gzip')],
                   [('Content-Type', 'application/json'), ('Transfer-Encoding', 'chunked'), ('Content-Length', '1')]]
        for headers in invalid:
            self.response.getheaders.return_value = headers
            with self.subTest(headers=headers), self.assertRaises(TransportError):
                self.transport.request('GET', '/control/status')
        self.response.read.assert_not_called()

    def test_content_length_must_match_complete_body(self):
        self.response.getheaders.return_value = [('Content-Type', 'application/json'),
                                                  ('Content-Length', '10')]
        self.response.read.return_value = b'{}'
        with self.assertRaisesRegex(TransportError, '^truncated_response$'):
            self.transport.request('GET', '/control/status')
        self.response.getheaders.return_value[-1] = ('Content-Length', '1')
        with self.assertRaisesRegex(TransportError, '^truncated_response$'):
            self.transport.request('GET', '/control/status')
        self.response.getheaders.return_value[-1] = ('Content-Length', '2')
        self.assertEqual(self.transport.request('GET', '/control/status'), {})

    def test_bounded_body_and_exact_limit(self):
        self.response.read.return_value = b'{}' + b' ' * (MAX_JSON_BYTES - 2)
        self.assertEqual(self.transport.request('GET', '/control/status'), {})
        self.response.read.return_value += b' '
        with self.assertRaisesRegex(TransportError, 'response_too_large'):
            self.transport.request('GET', '/control/status')

    def test_json_rejects_nonobject_duplicates_nonfinite_and_bad_types(self):
        for raw in (b'[]', b'null', b'true', b'123', b'"hi"', b'{}{}', b'', b'\xff',
                    b'{"x":NaN}', b'{"x":Infinity}', b'{"x":-Infinity}', b'{"x":1e999}',
                    b'{"x":1,"x":2}', b'{"nested":{"x":1,"x":2}}',
                    b'{"x":1,"\\u0078":2}', b'{"x":[' + b'[' * 2000 + b']]}' ,
                    '{}', None, bytearray(b'{}')):
            self.response.read.return_value = raw
            with self.subTest(raw_type=type(raw).__name__), self.assertRaises(TransportError) as raised:
                self.transport.request('GET', '/control/status')
            self.assertNotIn(TEST_TOKEN, str(raised.exception))
        self.assertFalse(self.transport._inflight.locked())

    def test_network_failures_are_sanitized_no_retry_and_cleanup(self):
        for stage in ('request', 'getresponse', 'read'):
            self.connection.reset_mock(side_effect=True)
            self.connection.getresponse.return_value = self.response
            self.response.reset_mock(side_effect=True)
            self.response.status = 200
            self.response.getheaders.return_value = [('Content-Type', 'application/json')]
            operation = self.response.read if stage == 'read' else getattr(self.connection, stage)
            operation.side_effect = OSError('server body ' + TEST_TOKEN)
            with self.subTest(stage=stage), self.assertRaisesRegex(TransportError, '^request_failed$') as raised:
                self.transport.request('GET', '/control/status')
            self.assertNotIn(TEST_TOKEN, str(raised.exception))
            self.assertTrue(raised.exception.__suppress_context__)
            self.assertEqual(self.connection.request.call_count, 1)
            self.connection.close.assert_called_once_with()
            self.assertFalse(self.transport._inflight.locked())

    def test_cleanup_errors_cannot_expose_details_or_strand_admission(self):
        self.response.close.side_effect = OSError(TEST_TOKEN)
        self.connection.close.side_effect = OSError(TEST_TOKEN)
        self.assertEqual(self.transport.request('GET', '/control/status'), {'ok': True})
        self.assertFalse(self.transport._inflight.locked())

    def test_timer_start_failure_closes_and_does_not_join_unstarted_timer(self):
        self.timer.start.side_effect = RuntimeError(TEST_TOKEN)
        with self.assertRaisesRegex(TransportError, '^request_failed$'):
            self.transport.request('GET', '/control/status')
        self.timer.join.assert_not_called()
        self.connection.close.assert_called_once_with()
        self.assertFalse(self.transport._inflight.locked())


class NumericConnectionTests(MockedNetworkCase):
    def setUp(self):
        super().setUp()
        self.socket_factory.side_effect = None
        self.sock = self.socket_factory.return_value

    def test_numeric_ipv4_and_ipv6_connect_without_dns(self):
        for host, family, address in [('127.0.0.1', socket.AF_INET, ('127.0.0.1', 8765)),
                                     ('::1', socket.AF_INET6, ('::1', 8765, 0, 0))]:
            with self.subTest(host=host):
                connection = _NumericLoopbackConnection(host, 8765, .5)
                connection.connect()
                self.socket_factory.assert_called_with(family, socket.SOCK_STREAM)
                self.sock.connect.assert_called_with(address)
                self.sock.settimeout.assert_called_with(.5)
                connection.close()

    def test_deadline_socket_retained_when_http_connection_relinquishes_it(self):
        connection = _NumericLoopbackConnection('127.0.0.1', 8765, .5)
        connection.connect()
        connection.sock = None  # Mirrors HTTPConnection after Connection: close.
        connection.set_remaining_timeout(.1)
        self.sock.settimeout.assert_called_with(.1)
        connection.abort()
        self.sock.shutdown.assert_called_once_with(socket.SHUT_RDWR)
        self.sock.close.assert_called_once_with()

    def test_expired_before_connect_never_connects(self):
        connection = _NumericLoopbackConnection('127.0.0.1', 8765, .5)
        connection.abort()
        with self.assertRaisesRegex(TransportError, 'operation_deadline'):
            connection.connect()
        self.sock.connect.assert_not_called()
        self.sock.close.assert_called_once_with()

    def test_shutdown_failure_still_closes_socket(self):
        connection = _NumericLoopbackConnection('127.0.0.1', 8765, .5)
        connection.connect()
        self.sock.shutdown.side_effect = OSError('already closed')
        connection.abort()
        self.sock.close.assert_called_once_with()


class HttpFramingTests(MockedNetworkCase):
    """Exercise stdlib HTTP parsing with a mocked socket and in-memory bytes."""

    def setUp(self):
        super().setUp()
        self.socket_factory.side_effect = None
        self.sock = self.socket_factory.return_value
        self.locally_closed = False
        self.sock.close.side_effect = self.mark_closed
        self.sock.settimeout.side_effect = self.set_timeout
        self.transport = LoopbackHttpTransport(self.config())

    def mark_closed(self):
        self.locally_closed = True

    def set_timeout(self, _):
        if self.locally_closed and self.input.closed:
            raise OSError('descriptor closed')

    def response(self, wire_bytes):
        self.input = io.BytesIO(wire_bytes)
        self.sock.makefile.return_value = self.input

    def test_connection_close_success_never_sets_closed_descriptor_timeout(self):
        self.response(b'HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n'
                      b'Content-Length: 2\r\nConnection: close\r\n\r\n{}')
        self.assertEqual(self.transport.request('GET', '/control/status'), {})
        self.assertTrue(self.input.closed)
        self.assertTrue(self.locally_closed)
        self.sock.connect.assert_called_once_with(('127.0.0.1', 8765))
        self.timer.cancel.assert_called_once_with()

    def test_stdlib_short_read_with_complete_json_still_rejected(self):
        self.response(b'HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n'
                      b'Content-Length: 10\r\nConnection: close\r\n\r\n{}')
        with self.assertRaisesRegex(TransportError, '^truncated_response$'):
            self.transport.request('GET', '/control/status')
        self.assertTrue(self.input.closed)

    def test_valid_chunked_body_is_bounded_and_decoded(self):
        self.response(b'HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n'
                      b'Transfer-Encoding: chunked\r\nConnection: close\r\n\r\n'
                      b'1\r\n{\r\n1\r\n}\r\n0\r\n\r\n')
        self.assertEqual(self.transport.request('GET', '/control/status'), {})
        self.assertTrue(self.input.closed)

    def test_incomplete_chunked_body_sanitized(self):
        self.response(b'HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n'
                      b'Transfer-Encoding: chunked\r\nConnection: close\r\n\r\n'
                      b'a\r\n{}')
        with self.assertRaisesRegex(TransportError, '^request_failed$'):
            self.transport.request('GET', '/control/status')
        self.assertTrue(self.input.closed)


if __name__ == '__main__':
    unittest.main()
