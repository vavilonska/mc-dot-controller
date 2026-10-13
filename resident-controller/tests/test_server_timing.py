import unittest
from resident_controller.transport import read_server_timing

class Response:
    def __init__(self, values): self.values = values
    def getheader(self, name): return self.values.get(name)

class ServerTimingTests(unittest.TestCase):
    def headers(self):
        h = {'X-MDC-Read-Timing-Version':'1', 'X-MDC-Read-Timing-Status':'complete'}
        for name, value in zip(('Dispatch','Client-Start','Client-End','Encode-Start','Encode-End'),
                               (1000, 500001000, 502001000, 510001000, 520001000)):
            h['X-MDC-'+name+'-Offset-Nanos'] = str(value)
        return h
    def test_queue_operation_and_encoding_are_separate_reported_intervals(self):
        h = self.headers(); h.update({'X-MDC-Client-Fps':'2','X-MDC-Client-Focused':'true','X-MDC-Client-Paused':'true'})
        t = read_server_timing(Response(h))
        self.assertEqual('reported_complete',t['status'])
        self.assertEqual(500,t['dispatch_to_client_operation_ms'])
        self.assertEqual(2,t['client_operation_ms']); self.assertEqual(10,t['json_encoding_ms'])
        self.assertEqual(8,t['client_end_to_encoding_ms']); self.assertEqual(2,t['client_reported_fps'])
        self.assertTrue(t['client_focused']);self.assertTrue(t['client_paused'])
        self.assertFalse(t['includes_socket_write_or_transport'])
    def test_missing_and_partial_do_not_invent_zero_durations(self):
        self.assertIsNone(read_server_timing(Response({})))
        t=read_server_timing(Response({'X-MDC-Read-Timing-Version':'1','X-MDC-Read-Timing-Status':'partial'}))
        self.assertEqual('reported_partial',t['status']);self.assertIsNone(t['json_encoding_ms'])
        self.assertIsNone(t['client_operation_ms'])
    def test_malformed_and_reversed_headers_are_not_trusted(self):
        for value in ('-1','NaN','1, 2',str(2**63)):
            h=self.headers();h['X-MDC-Client-End-Offset-Nanos']=value
            self.assertEqual('invalid_offset',read_server_timing(Response(h))['status'])
        h=self.headers();h['X-MDC-Client-End-Offset-Nanos']='1'
        self.assertEqual('invalid_order',read_server_timing(Response(h))['status'])
        h=self.headers();del h['X-MDC-Client-End-Offset-Nanos']
        self.assertEqual('invalid_completeness',read_server_timing(Response(h))['status'])
    def test_header_errors_cannot_mask_the_original_transport_flow(self):
        class Broken:
            def getheader(self, name): raise RuntimeError('private unused text')
        self.assertEqual({'status':'header_read_failed'},read_server_timing(Broken()))


class TransportTimingIntegrationTests(unittest.TestCase):
    def test_known_transport_forwards_headers_to_scan_record_without_changing_payload(self):
        import json
        from unittest.mock import patch
        from resident_controller.transport import Bridge
        from resident_controller.terrain_diagnostics import ScanDiagnostics
        raw = b'{"read_elapsed_micros":2000,"offset":0}'
        class NativeResponse(Response):
            status = 200
            def read(self, limit): return raw
        class Connection:
            def __init__(self, *args, **kwargs): pass
            def request(self, *args, **kwargs): pass
            def getresponse(self): return NativeResponse(ServerTimingTests().headers())
            def close(self): pass
        bridge = Bridge('http://127.0.0.1:12345', 'synthetic-test-token')
        diagnostics = ScanDiagnostics(lambda: 1.0, 1.0, 4.0); diagnostics.enter_attempt(1)
        with patch('resident_controller.transport.http.client.HTTPConnection', Connection):
            result = diagnostics.request(bridge, 'terrain_page', '/control/terrain')
        self.assertEqual(json.loads(raw), result)
        record = diagnostics.data['attempts'][0]['stages'][0]
        self.assertEqual(len(raw), record['response_bytes_read'])
        self.assertEqual(2000, record['java_read_elapsed_micros'])
        self.assertEqual(500, record['server_timing']['dispatch_to_client_operation_ms'])
        self.assertIsNone(diagnostics.data['http_queue_elapsed_ms'])
        self.assertIsNone(diagnostics.data['network_elapsed_ms'])
    def test_next_legacy_response_cannot_inherit_previous_server_timing(self):
        from unittest.mock import patch
        from resident_controller.transport import Bridge
        headers = [ServerTimingTests().headers(), {}]
        class NativeResponse(Response):
            status = 200
            def read(self, limit): return b'{}'
        class Connection:
            def __init__(self, *args, **kwargs): pass
            def request(self, *args, **kwargs): pass
            def getresponse(self): return NativeResponse(headers.pop(0))
            def close(self): pass
        bridge = Bridge('http://127.0.0.1:12345', 'synthetic-test-token')
        with patch('resident_controller.transport.http.client.HTTPConnection', Connection):
            bridge.request('GET','/control/state')
            self.assertIn('server_timing',bridge.last_response_metadata)
            bridge.request('GET','/control/state')
            self.assertNotIn('server_timing',bridge.last_response_metadata)

if __name__=='__main__': unittest.main()
