"""Offline fake clocks/HTTP only: no server, socket, IPC, sleep, or game."""
import copy
import hashlib
import json
from pathlib import Path
import random
from types import ModuleType
import unittest
from unittest.mock import patch

from resident_controller import world, transport
from resident_controller.terrain_diagnostics import ScanDiagnostics

W = '11111111-1111-4111-8111-111111111111'
G = '22222222-2222-4222-8222-222222222222'
G2 = '33333333-3333-4333-8333-333333333333'


def frozen(name, digest):
    path = Path(__file__).parent / 'fixtures' / (name + '_pre_latency.py.txt')
    source = path.read_bytes()
    assert hashlib.sha256(source).hexdigest() == digest
    module = ModuleType('resident_controller.' + name + '_pre_latency')
    module.__file__ = world.__file__
    module.__package__ = 'resident_controller'
    exec(compile(source, str(path), 'exec'), module.__dict__)
    return module


OLD_WORLD = frozen('world', '4fdc749b7912fbb0b2b63eaee061a96708387de09140ac513592dbce3f5ed15d')
OLD_TRANSPORT = frozen('transport', 'b1ec6486efaac8218ba4d06103b2b134aa960ceec20e36fb5206cbf4463cfb87')


class Clock:
    def __init__(self):
        self.now = 100.0
        self.sleeps = []
    def monotonic(self):
        return self.now
    def sleep(self, value):
        self.sleeps.append(value)
        self.now += value


class FakeBridge:
    def __init__(self, clock, *, page_delay=0, first_delay=0, last_delay=0,
                 frozen_tick=True, faults=None, page_size=128):
        self.clock = clock
        self.page_delay, self.first_delay, self.last_delay = page_delay, first_delay, last_delay
        self.frozen_tick, self.faults, self.page_size = frozen_tick, faults or {}, page_size
        self.calls, self.pages, self.states, self.offset, self.attempt = [], 0, 0, 0, 0
    def request(self, method, path):
        assert method == 'GET'
        self.calls.append((method, path))
        if path == '/control/state?radius=8':
            self.states += 1
            self.clock.now += self.first_delay if self.states == 1 else self.last_delay
            value = {'world': {'world_generation': W, 'dimension': 'minecraft:overworld',
                              'game_time': 100 if self.frozen_tick else 100 + self.pages},
                     'player': {'uuid': 'test-player'}, 'client_action': {'action_session': 'test-session'},
                     'paused': self.frozen_tick, 'screen_open': self.frozen_tick}
            fault = self.faults.get(('state', self.states))
        else:
            assert path.startswith('/control/terrain?')
            if 'radius=' in path:
                self.offset = 0
                self.attempt += 1
            self.pages += 1
            self.clock.now += self.page_delay
            start, end = self.offset, min(567, self.offset + self.page_size)
            self.offset = end
            cells = [{'x': -4+i % 9, 'z': -4+(i//9) % 9, 'y': 61+i//81,
                      'status': 'unloaded', 'known': False} for i in range(start, end)]
            generation = G if self.attempt == 1 else G2
            tick = 100 if self.frozen_tick else 100 + self.pages
            value = {'ok': True, 'protocol': 'mineclient-bridge', 'schema_version': 2,
                     'terrain_schema_version': 1, 'consistency': 'live_pages', 'order': 'x_then_z_then_y',
                     'read_only': True, 'loaded_chunks_only': True, 'world_generation': W,
                     'dimension': 'minecraft:overworld', 'game_time': tick, 'response_game_time': tick,
                     'generation': generation, 'origin': {'x': 0, 'y': 64, 'z': 0}, 'radius': 4, 'vertical': 3,
                     'total_cells': 567, 'offset': start, 'next_offset': end, 'returned': len(cells),
                     'cells': cells, 'complete': end == 567,
                     'next_cursor': None if end == 567 else f'{generation}:{end}',
                     'budget_exhausted': False, 'read_elapsed_micros': 17, 'unknown_cells': len(cells)}
            fault = self.faults.get(('page', self.pages))
        if isinstance(fault, BaseException):
            raise fault
        if callable(fault):
            fault(value, self)
        return value


def run_scan(module, **kwargs):
    clock = Clock()
    bridge = FakeBridge(clock, **kwargs)
    cache = module.WorldCache()
    cache.grid, cache.cells, cache.terrain_received_at = object(), {('old',): 'old'}, 10
    with patch.object(module, 'time', clock):
        try:
            result = ('ok', cache.scan(bridge, radius=4, vertical=3))
        except Exception as exc:
            result = ('error', type(exc).__name__, str(exc))
    legacy = {key: value for key, value in cache.terrain_read.items() if key != 'diagnostics'}
    evidence = (result, legacy, cache.grid is not None, cache.cells, cache.terrain_received_at,
                cache.state, cache.received_at, bridge.calls, clock.sleeps)
    return evidence, cache, bridge


class TerrainDiagnosticsChecks(unittest.TestCase):
    def equivalent(self, **kwargs):
        old = run_scan(OLD_WORLD, **kwargs)
        new = run_scan(world, **kwargs)
        self.assertEqual(old[0], new[0])
        json.dumps(new[1].terrain_read, allow_nan=False)
        return new

    def test_frozen_and_advancing_ticks_with_fast_and_slow_stages(self):
        for frozen_tick in (True, False):
            for args in ({}, {'page_delay': .75}, {'first_delay': 3.1}, {'last_delay': 3.1}):
                with self.subTest(frozen_tick=frozen_tick, **args):
                    _, cache, bridge = self.equivalent(frozen_tick=frozen_tick, **args)
                    self.assertEqual(cache.terrain_read['diagnostics']['actual_attempts'], 1)
                    if not args:
                        self.assertEqual(cache.terrain_read['outcome'], 'complete')
                        self.assertEqual(bridge.pages, 5)
                        self.assertEqual(len(cache.grid.cells), 567)
                        self.assertEqual(cache.cells, {})  # unknown cells stay unknown

    def test_request_timings_and_unknown_bytes_are_measured_without_reencoding(self):
        _, cache, _ = self.equivalent(first_delay=.1, last_delay=.2, page_delay=.03)
        d = cache.terrain_read['diagnostics']
        stages = d['attempts'][0]['stages']
        requests = [s for s in stages if 'roundtrip_ms' in s]
        self.assertEqual([s['roundtrip_ms'] for s in requests], [100,30,30,30,30,30,200])
        self.assertEqual(d['total_elapsed_ms'], 650)
        self.assertEqual(d['remaining_total_ms'], 2350)
        self.assertEqual(d['attempts'][0]['assembler_budget_ms'], 2900)
        pages = [s for s in requests if s['phase'] == 'terrain_page']
        self.assertEqual([s['page_reported']['returned'] for s in pages], [128,128,128,128,55])
        self.assertEqual([s['page_reported']['complete'] for s in pages], [False]*4+[True])
        self.assertTrue(all(s['response_bytes_read'] is None and s['response_bytes_status']=='unknown' for s in requests))
        self.assertTrue(all(s['java_read_elapsed_micros']==17 for s in pages))
        self.assertEqual(sum(s['elapsed_ms'] for s in stages if s['phase']=='page_interval'), 200)
        self.assertEqual([s['phase'] for s in stages][-2:], ['final_state', 'assembler_finish'])
        self.assertIsNone(d['network_elapsed_ms'])
        self.assertIsNone(d['http_queue_elapsed_ms'])
        self.assertIsNone(d['python_cpu_elapsed_ms'])

    def test_original_rejection_and_failed_request_roundtrip_preserved(self):
        failure = transport.BridgeError('minecraft_thread_timeout', status=504)
        _, cache, _ = self.equivalent(page_delay=.5, faults={('page',1):failure})
        d = cache.terrain_read['diagnostics']['attempts'][0]
        request = [s for s in d['stages'] if s['phase']=='terrain_page'][0]
        self.assertEqual(request['roundtrip_ms'], 500)
        self.assertEqual(request['outcome'], 'raised')
        self.assertEqual(d['original_rejection']['code'], 'minecraft_thread_timeout')
        self.assertEqual(d['original_rejection']['http_status'], 504)
        self.assertEqual(d['rejection_phase'], 'terrain_page')
        self.assertIsNone(cache.grid)
        self.assertEqual(cache.cells, {})

    def test_slow_five_page_scan_can_fail_before_final_state(self):
        _, cache, bridge = self.equivalent(page_delay=.5972856)
        self.assertEqual(bridge.pages, 5)
        self.assertEqual(bridge.states, 1)
        self.assertEqual(cache.terrain_read['elapsed_ms'], 3186.428)
        d = cache.terrain_read['diagnostics']['attempts'][0]
        self.assertEqual(d['rejection_phase'], 'assembler_add_and_collect')
        self.assertEqual(d['original_rejection']['detail'], 'stale_terrain_clock')
        self.assertEqual(cache.terrain_read['diagnostics']['actual_attempts'], 1)

    def test_retry_uses_fresh_get_shared_budget_and_retains_first_rejection(self):
        for code, status in (('stale_terrain_cursor',409), ('terrain_rate_limited',429)):
            _, cache, bridge = self.equivalent(faults={('page',2):transport.BridgeError(code,status=status)})
            d = cache.terrain_read['diagnostics']
            self.assertEqual(d['actual_attempts'], 2)
            self.assertEqual(d['attempts'][0]['last_rejection'], code)
            self.assertEqual(cache.terrain_read['outcome'], 'recovered')
            self.assertEqual(sum('limit=128' in p for _,p in bridge.calls), 2)
            self.assertLess(d['attempts'][1]['budget_at_entry_ms'], 3000)

    def test_malformed_identity_coverage_tick_and_page_limit_differential(self):
        changes = [
            ('state',1,lambda v,b:v.update(world=None)),
            ('state',1,lambda v,b:v['player'].update(uuid='')),
            ('state',2,lambda v,b:v['player'].update(uuid='changed')),
            ('state',2,lambda v,b:v['client_action'].update(action_session='changed')),
            ('state',2,lambda v,b:v['world'].update(world_generation=G2)),
            ('state',2,lambda v,b:v['world'].update(game_time=99)),
            ('page',1,lambda v,b:v.update(returned=129)),
            ('page',1,lambda v,b:v.update(complete=True)),
            ('page',2,lambda v,b:v.update(offset=0)),
            ('page',2,lambda v,b:v.update(generation=G2)),
            ('page',1,lambda v,b:v.update(game_time=99)),
            ('page',1,lambda v,b:v.update(response_game_time=141)),
            ('page',1,lambda v,b:v.update(read_elapsed_micros=None)),
            ('page',1,lambda v,b:v.update(unknown_cells=0)),
            ('page',1,lambda v,b:v['cells'][0].update(known=True)),
            ('page',1,lambda v,b:v['cells'][0].update(x=9)),
            ('page',1,lambda v,b:setattr(b.clock,'now',99)),
            ('page',1,transport.BridgeError('transport_failed',uncertain=True)),
            ('page',1,ValueError('synthetic_value_error')),
            ('page',1,KeyError('synthetic_key_error')),
            ('page',1,TypeError('synthetic_type_error')),
        ]
        for phase, number, fault in changes:
            with self.subTest(phase=phase, number=number, fault=str(fault)):
                self.equivalent(faults={(phase,number):fault})
        self.equivalent(page_size=1)

    def test_seeded_delay_boundary_matrix(self):
        r = random.Random(62107)
        for i in range(200):
            args = {'first_delay':r.choice([0,.01,.2,.5,2.8,2.99,3,3.01]),
                    'last_delay':r.choice([0,.01,.2,2.8,3]),
                    'page_delay':r.choice([0,.01,.2,.5,.55,.559999,.56,.560001,.75]),
                    'frozen_tick':bool(i%2)}
            with self.subTest(i=i, **args):
                self.equivalent(**args)

    def test_observer_clock_failures_are_unknown_and_cannot_change_admission(self):
        def broken():
            raise RuntimeError('sensor unavailable')
        for clock in (broken, lambda:float('nan'), lambda:float('inf')):
            class DiagnosticClock(ScanDiagnostics):
                def __init__(self, original, started, deadline):
                    super().__init__(clock, started, deadline)
            with patch.object(world, 'ScanDiagnostics', DiagnosticClock):
                _, cache, _ = self.equivalent()
            d = cache.terrain_read['diagnostics']
            self.assertGreater(d['clock_observation_errors'], 0)
            self.assertEqual(d['attempts'][0]['stages'][0]['timing_status'], 'unknown_clock_error')

    def test_clock_reverse_in_observer_is_labeled_not_clamped(self):
        values = iter([100,100.2,100.1])
        d = ScanDiagnostics(lambda:next(values), 100, 103)
        d.enter_attempt(1)
        with d.stage('synthetic'):
            pass
        s=d.data['attempts'][0]['stages'][0]
        self.assertIsNone(s['elapsed_ms'])
        self.assertEqual(s['timing_status'], 'clock_reversed')

    def test_unprintable_exception_is_not_masked_by_diagnostics(self):
        class UnprintableError(RuntimeError):
            def __str__(self):
                raise ValueError('formatter failed')
        clock=Clock();d=ScanDiagnostics(clock.monotonic,100,103);d.enter_attempt(1)
        failure=UnprintableError()
        with self.assertRaises(UnprintableError) as caught:
            with d.stage('synthetic'):
                raise failure
        self.assertIs(caught.exception,failure)
        self.assertEqual(d.attempt['stages'][0]['original_rejection']['message_status'],'unknown_format_error')

    def test_attempt_guard_does_not_count_an_unrequested_attempt(self):
        class DelayedDiagnostic(ScanDiagnostics):
            def enter_attempt(self, number):
                super().enter_attempt(number)
                self.clock.__self__.now += 3.1
        clock=Clock(); bridge=FakeBridge(clock); cache=world.WorldCache()
        with patch.object(world,'time',clock), patch.object(world,'ScanDiagnostics',DelayedDiagnostic):
            with self.assertRaisesRegex(world.TerrainError,'terrain_refresh_exhausted_stale_terrain_clock'):
                cache.scan(bridge,radius=4,vertical=3)
        d=cache.terrain_read['diagnostics']
        self.assertEqual(cache.terrain_read['attempts'],1)
        self.assertEqual(d['attempts_entered'],1)
        self.assertEqual(d['actual_attempts'],0)
        self.assertEqual(bridge.calls,[])


class FailurePublicationChecks(unittest.TestCase):
    def resident(self):
        # Pure in-memory protocol stubs; no Resident.start(), queue, or filesystem.
        from resident_controller.controller import Resident
        resident = object.__new__(Resident)
        resident.cache = world.WorldCache()
        resident.bridge = ModuleType('fake_bridge')
        resident.bridge.request = lambda method,path: {'in_world': False}
        resident.check_identity = lambda status: None
        resident.aim = ModuleType('fake_aim');resident.aim.status = lambda: {}
        resident.combat = ModuleType('fake_combat');resident.combat.status = lambda: {}
        resident.combat.held = False;resident.combat.active = False
        resident.prospecting = ModuleType('fake_prospecting');resident.prospecting.summary = lambda: {}
        resident.finish = lambda command,status,**fields: self.published.append((command,status,fields))
        self.published = []
        return resident

    def test_failed_snapshot_carries_only_the_matching_new_scan_diagnostic(self):
        resident = self.resident()
        command = {'op':'observe','terrain':True,'request_id':'test-request'}
        failure = world.TerrainError('terrain_refresh_exhausted_stale_terrain_clock')
        def fail_scan(*args):
            resident.cache.terrain_read = {'outcome':'failed','diagnostics':{'schema_version':1}}
            raise failure
        resident.cache.scan = fail_scan
        with self.assertRaises(world.TerrainError) as caught:
            resident.snapshot(command)
        self.assertIs(caught.exception, failure)
        resident.command_error(command, caught.exception)
        self.assertEqual(self.published,[(command,'failed',{
            'reason':'terrain_refresh_exhausted_stale_terrain_clock',
            'terrain_read':resident.cache.terrain_read})])

    def test_bad_bounds_do_not_attach_old_diagnostic(self):
        resident = self.resident()
        resident.cache.terrain_read = {'outcome':'failed','diagnostics':{'old':True}}
        command = {'op':'observe','terrain':True,'radius':99,'request_id':'other-request'}
        with self.assertRaises(ValueError) as caught:
            resident.snapshot(command)
        resident.command_error(command,caught.exception)
        self.assertNotIn('terrain_read',self.published[0][2])


class Response:
    def __init__(self, raw=b'{"ok":true}', status=200, error=None):
        self.raw,self.status,self.error=raw,status,error
        self.read_limits=[]
    def read(self, limit):
        self.read_limits.append(limit)
        if self.error: raise self.error
        return self.raw[:limit]


class Connection:
    def __init__(self, response, request_error=None):
        self.response,self.request_error=response,request_error
        self.calls=[];self.closed=False
    def request(self,*args,**kwargs):
        self.calls.append((args,kwargs))
        if self.request_error: raise self.request_error
    def getresponse(self):return self.response
    def close(self):self.closed=True


def transport_result(module, raw, status=200, read_error=None, request_error=None, method='GET', path='/control/terrain?limit=128',body=None):
    response=Response(raw,status,read_error);connection=Connection(response,request_error)
    bridge=module.Bridge('http://127.0.0.1:12345','synthetic-test-token')
    with patch('http.client.HTTPConnection',return_value=connection):
        try:result=('ok',bridge.request(method,path,body))
        except module.BridgeError as exc:result=('error',exc.code,exc.status,exc.uncertain)
    return (result,response.read_limits,connection.calls,connection.closed),bridge


class TransportDiagnosticsChecks(unittest.TestCase):
    def test_exact_observed_bytes_no_json_reserialization(self):
        raw=b'{ "ok" : true, "space" : "  " }\n'
        old,_=transport_result(OLD_TRANSPORT,raw)
        new,bridge=transport_result(transport,raw)
        self.assertEqual(old,new)
        self.assertEqual(bridge.last_response_metadata,{'response_bytes_read':len(raw),
            'response_bytes_status':'observed_read_length','http_status':200})
        self.assertEqual(new[1],[256*1024+1])

    def test_error_bounds_and_uncertainty_differential(self):
        cases=[dict(raw=b'{}'),dict(raw=b'[]'),dict(raw=b'NaN'),dict(raw=b'bad json'),
               dict(raw=b'\xff'),dict(raw=b'x'*(256*1024)),dict(raw=b'x'*(256*1024+1)),
               dict(raw=b'{"error":"stale_terrain_cursor"}',status=409),
               dict(raw=b'{"error":"minecraft_thread_timeout"}',status=504),
               dict(raw=b'ignored',read_error=OSError('read fail')),
               dict(raw=b'ignored',request_error=TimeoutError('request fail')),
               dict(raw=b'{"error":"minecraft_thread_timeout"}',status=504,
                    method='POST',path='/control/action',body={'action':'x'})]
        for kwargs in cases:
            with self.subTest(kwargs={k:v for k,v in kwargs.items() if k!='raw'}):
                old,_=transport_result(OLD_TRANSPORT,**kwargs)
                new,bridge=transport_result(transport,**kwargs)
                self.assertEqual(old,new)
                expected=None if kwargs.get('read_error') or kwargs.get('request_error') else min(len(kwargs['raw']),256*1024+1)
                self.assertEqual(bridge.last_response_metadata['response_bytes_read'],expected)

    def test_stale_metadata_resets_before_failed_request(self):
        _,bridge=transport_result(transport,b'{"ok":true}')
        connection=Connection(Response(),request_error=TimeoutError())
        with patch('http.client.HTTPConnection',return_value=connection):
            with self.assertRaises(transport.BridgeError):bridge.request('GET','/control/state')
        self.assertEqual(bridge.last_response_metadata,{'response_bytes_read':None,
            'response_bytes_status':'unknown','http_status':None})

    def test_scan_records_real_transport_bytes_including_failure(self):
        clock=Clock();d=ScanDiagnostics(clock.monotonic,100,103);d.enter_attempt(1)
        bridge=transport.Bridge('http://127.0.0.1:12345','synthetic-test-token')
        for raw,status in [(b'{ "ok": true }',200),(b'{"error":"stale_terrain_cursor"}',409)]:
            connection=Connection(Response(raw,status))
            with patch('http.client.HTTPConnection',return_value=connection):
                if status==200:d.request(bridge,'terrain_page','/control/terrain?limit=128',1)
                else:
                    with self.assertRaises(transport.BridgeError):d.request(bridge,'terrain_page','/control/terrain?limit=128',1)
            record=d.attempt['stages'][-1]
            self.assertEqual(record['response_bytes_read'],len(raw))
            self.assertEqual(record['http_status'],status)
            self.assertEqual(record['roundtrip_ms'],0)


if __name__=='__main__':unittest.main()
