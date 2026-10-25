import copy
import hashlib
from pathlib import Path
import tempfile
import unittest
from damage_watch.schema import validate,PATH
from damage_watch.strict import Invalid,encode,strict_json
from damage_watch.watcher import Reply,watch

BOOT='aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';PLAYER='bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';OWNER='cccccccc-cccc-4ccc-8ccc-cccccccccccc'
POSE={'x':-634.5243,'y':60.,'z':18.94168}

def snapshot(world=True):
    native=dict(enabled=True,owner_id=OWNER,active_id=None,profile=None,state=None,applied_count=0,next_generation=95,entry_count=94,unknown_lock=False)
    sample=dict(nano_time=1000000000,client_tick=1,player_uuid=PLAYER,health=20.,position=copy.deepcopy(POSE),input=dict(forward=0.,strafe=0.,jump=False),native=native)
    return dict(schema_version=1,profile='recovery_damage_diagnostics_v1',enabled=True,boot_id=BOOT,window_ms=15000,window_started=world,window_closed=False,window_start_nanos=1000000000 if world else None,query_nanos=1000000000,server_first=None,client_first=copy.deepcopy(sample) if world else None,client_latest=copy.deepcopy(sample) if world else None,client_total=1 if world else 0,client_nonzero_count=0,first_nonzero_tick=None,client_dropped=0,client_samples=[copy.deepcopy(sample)] if world else [],damage_total=0,damage_dropped=0,damage_events=[],capture_errors=0)

def event():return dict(sequence=1,nano_time=1000000001,server_tick=10,game_time=200,player_uuid=PLAYER,health_after=19.,position=copy.deepcopy(POSE),original_damage=1.,new_damage=1.,blocked_damage=0.,source_key='minecraft:in_fire',direct=None,causing=None,client_snapshot_nanos=None,native_snapshot=None)

class Clock:
    def __init__(self):self.now=0.
    def clock(self):return self.now
    def sleep(self,s):self.now+=s

class Transport:
    def __init__(self,items):self.items=items;self.calls=[];self.i=0
    def get(self,path,*,timeout_s):
        assert path==PATH and 0<timeout_s<=.75
        self.calls.append((path,timeout_s));value=self.items[min(self.i,len(self.items)-1)];self.i+=1
        if isinstance(value,Exception):raise value
        return value if isinstance(value,Reply) else Reply(200,encode(value),True)
    def post(self,*_):raise AssertionError('watcher must not POST')

class WatchTests(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)/'capture';self.clock=Clock()
    def tearDown(self):self.tmp.cleanup()
    def run_watch(self,items,**kw):
        self.transport=Transport(items)
        return watch(self.transport,self.root,expected_pose=POSE,expected_owner=OWNER,expected_player=PLAYER,expected_next_generation=95,expected_entry_count=94,clock=self.clock.clock,sleep=self.clock.sleep,utc=lambda:'offline-fixture',**kw)
    def test_first_damage_stops_without_extra_get_and_saves_raw_first(self):
        s=snapshot();s['damage_total']=1;s['damage_events']=[event()]
        result=self.run_watch([s]);self.assertEqual(result['reason'],'damage_detected');self.assertEqual(len(self.transport.calls),1)
        self.assertEqual((self.root/'0000.raw').read_bytes(),encode(s));self.assertTrue(strict_json((self.root/'stop-trigger.json').read_bytes())['close_required'])
        m=strict_json((self.root/'0000.json').read_bytes());self.assertEqual(m['raw_sha256'],hashlib.sha256(encode(s)).hexdigest());self.assertTrue(m['complete'])
    def test_other_player_damage_closes_without_false_target_reproduction(self):
        s=snapshot();e=event();e['player_uuid']=OWNER;s.update(damage_total=1,damage_events=[e])
        r=self.run_watch([s]);self.assertEqual(r['reason'],'player_identity_changed');self.assertFalse(r['damage_reproduced']);self.assertEqual(len(self.transport.calls),1)
    def test_server_damage_before_client_window_is_immediate(self):
        s=snapshot(False);s.update(window_started=True,window_start_nanos=1000000000,damage_total=1,damage_events=[event()])
        result=self.run_watch([s]);self.assertEqual(result['reason'],'damage_detected');self.assertTrue(result['damage_reproduced']);self.assertEqual(len(self.transport.calls),1)
    def test_client_health_pose_nonzero_active_and_generation_trigger(self):
        changes=[('health',19.,'health_below20'),('position',dict(POSE,y=60.051),'pose_deviation'),('input',dict(forward=.1,strafe=0.,jump=False),'nonzero_input_detected')]
        for key,value,reason in changes:
            with self.subTest(key=key):
                self.root=Path(self.tmp.name)/key;s=snapshot();s['client_latest'][key]=value;self.assertEqual(self.run_watch([s])['reason'],reason)
        for key,value,reason in [('active_id',BOOT,'native_action_detected'),('next_generation',96,'native_identity_or_generation_changed'),('owner_id',BOOT,'native_identity_or_generation_changed')]:
            self.root=Path(self.tmp.name)/key;s=snapshot();s['client_latest']['native'][key]=value;self.assertEqual(self.run_watch([s])['reason'],reason)
    def test_nonzero_cumulative_catches_omitted_middle_sample(self):
        s=snapshot();s.update(client_total=100,client_nonzero_count=1,first_nonzero_tick=42)
        self.assertEqual(self.run_watch([s])['reason'],'nonzero_input_detected')
    def test_expected_prelaunch_refusal_waits_but_never_resets_startup60(self):
        r=self.run_watch([Reply(None,b'',False,'connection_unavailable')],startup_s=1)
        self.assertEqual(r['reason'],'startup_not_in_world');self.assertAlmostEqual(r['elapsed_seconds'],1);self.assertFalse(r['world_seen']);self.assertGreater(r['incomplete_transport_responses'],0)
    def test_prelaunch_refusal_then_world_transport_loss_closes(self):
        r=self.run_watch([Reply(None,b'',False,'connection_unavailable'),snapshot(),Reply(None,b'',False,'connection_unavailable')])
        self.assertEqual(r['reason'],'transport_incomplete');self.assertTrue(r['world_seen']);self.assertEqual(len(self.transport.calls),3)
    def test_world12_limit_even_if_native_query_does_not_advance(self):
        r=self.run_watch([snapshot()]);self.assertEqual(r['reason'],'window_not_reproduced');self.assertAlmostEqual(r['elapsed_seconds'],12);self.assertFalse(r['damage_reproduced']);self.assertFalse(r['native_window_closed'])
    def test_native_elapsed_prevents_late_watcher_extending_window(self):
        s=snapshot();s['query_nanos']+=11900000000
        r=self.run_watch([s]);self.assertLessEqual(r['elapsed_seconds'],.100001);self.assertEqual(len(self.transport.calls),1)
    def test_http_latency_cannot_extend_world_budget(self):
        base=Transport([snapshot()]);clock=self.clock
        class Delayed:
            def get(self,path,*,timeout_s):clock.sleep(min(.5,timeout_s));return base.get(path,timeout_s=timeout_s)
        r=watch(Delayed(),self.root,expected_pose=POSE,expected_owner=OWNER,expected_player=PLAYER,expected_next_generation=95,expected_entry_count=94,clock=clock.clock,sleep=clock.sleep,utc=lambda:'offline')
        self.assertLessEqual(r['elapsed_seconds'],12.00001)
    def test_no_world_and_explicit_capture_errors_are_not_safety_claims(self):
        r=self.run_watch([snapshot(False)],startup_s=.4);self.assertEqual(r['reason'],'startup_not_in_world');self.assertFalse(r['damage_reproduced'])
        self.root=Path(self.tmp.name)/'errors';s=snapshot();s['capture_errors']=1;self.assertEqual(self.run_watch([s])['reason'],'native_capture_error')
    def test_invalid_duplicate_nonfinite_schema_stops_preserving_raw(self):
        for i,raw in enumerate((b'{"x":1,"x":2}',b'{"x":NaN}',encode(dict(snapshot(),extra=1)))):
            self.root=Path(self.tmp.name)/str(i);r=self.run_watch([Reply(200,raw,True)]);self.assertEqual(r['reason'],'invalid_diagnostic_response');self.assertEqual((self.root/'0000.raw').read_bytes(),raw)
    def test_overflow_prefix_not_full_response_and_exception_sanitized(self):
        raw=b'x'*140000;r=self.run_watch([Reply(200,raw,True)]);self.assertEqual(r['reason'],'transport_incomplete');m=strict_json((self.root/'0000.json').read_bytes());self.assertFalse(m['complete']);self.assertTrue(m['raw_is_prefix']);self.assertEqual(m['raw_bytes'],131073)
        self.root=Path(self.tmp.name)/'exception';self.run_watch([RuntimeError('SECRET_MUST_NOT_LOG')]);self.assertNotIn(b'SECRET',b''.join(p.read_bytes() for p in self.root.iterdir()))
    def test_boot_change_and_evidence_regression_close(self):
        for key,value,reason in [('boot_id',OWNER,'boot_identity_changed'),('client_total',0,'invalid_diagnostic_response'),('query_nanos',999999999,'invalid_diagnostic_response')]:
            self.root=Path(self.tmp.name)/key;s=snapshot();s[key]=value;self.assertEqual(self.run_watch([snapshot(),s])['reason'],reason)
    def test_cannot_adopt_output_or_extend_bounds(self):
        self.root.mkdir()
        with self.assertRaises(FileExistsError):self.run_watch([snapshot()])
        self.root=Path(self.tmp.name)/'bounds'
        with self.assertRaises(Invalid):self.run_watch([snapshot()],world_s=13)
    def test_schema_nulls_counts_and_sampling_not_fake_full_continuity(self):
        validate(snapshot(False));s=snapshot();s.update(client_total=100,client_dropped=0);validate(s)
        for changed in (dict(s,window_ms=30000),dict(s,enabled=1),dict(s,client_samples=s['client_samples']*33),dict(s,first_nonzero_tick=1)):
            with self.assertRaises(Invalid):validate(changed)

if __name__=='__main__':unittest.main()
