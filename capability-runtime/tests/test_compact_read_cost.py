"""Bounded compact failed-read evidence through actual loopback HTTP; no game."""
from copy import deepcopy
from http.server import BaseHTTPRequestHandler,HTTPServer
import json,os,threading,unittest
from pathlib import Path
from types import SimpleNamespace
from resident_controller.compact_observation import valid_diagnostic
from resident_controller.transport import Bridge,BridgeError
from resident_controller.controller import Resident


def diagnostic():
    return {'schema_version':1,'request_id':'compact-cost-one','read_only':True,'execution_authority':False,
        'stage':'terrain_ids','radius':1,'terrain_returned':4,'terrain_total':45,
        'terrain_elapsed_nanos':'8000000','terrain_budget_nanos':'8000000',
        'callback_elapsed_nanos':'9000000','callback_budget_nanos':'100000000',
        'stage_elapsed_nanos':{'context':'0','terrain_ids':'9000000','state':'0','final_context':'0','projection':'0'},
        'external_controller_elapsed_nanos':'0','external_controller_samples':0}

class CompactCostTests(unittest.TestCase):
    def test_closed_diagnostic_negative_matrix(self):
        self.assertTrue(valid_diagnostic(diagnostic(),'compact-cost-one',1))
        for key,value in [('schema_version',True),('request_id','other'),('read_only',False),('execution_authority',True),
                ('stage','dispatch'),('radius',True),('terrain_returned',46),('terrain_total',44),('terrain_elapsed_nanos','-1'),
                ('callback_elapsed_nanos','1e5'),('external_controller_samples',True),('external_controller_elapsed_nanos','1'),
                ('stage_elapsed_nanos',{'context':'9000000'}),('callback_budget_nanos','20000000'),('terrain_budget_nanos','20000000'),('extra',1)]:
            with self.subTest(key=key):self.assertFalse(valid_diagnostic({**diagnostic(),key:value},'compact-cost-one',1))
    def http_error(self,raw,request_id='compact-cost-one'):
        calls=[]
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                calls.append(self.path);self.send_response(409);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(raw)
            def log_message(self,*args):pass
        server=HTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            bridge=Bridge('http://127.0.0.1:'+str(server.server_port),'offline-test-token')
            with self.assertRaises(BridgeError) as caught:bridge.request('GET',f'/control/compact-observation?request_id={request_id}&radius=1')
            return caught.exception,calls
        finally:server.shutdown();server.server_close();thread.join(2)
    def test_actual_http_bounded_error_retained_one_get(self):
        raw=json.dumps({'ok':False,'error':'compact_observation_terrain_budget_exhausted','compact_observation_diagnostic':diagnostic()}).encode()
        error,calls=self.http_error(raw);self.assertEqual(len(calls),1);self.assertFalse(error.uncertain)
        self.assertEqual(error.compact_observation_diagnostic,diagnostic());self.assertEqual(error.compact_observation_diagnostic_status,'reported')
    def test_actual_http_invalid_or_duplicate_proof_is_not_retained(self):
        body={'ok':False,'error':'compact_observation_terrain_budget_exhausted','compact_observation_diagnostic':{**diagnostic(),'terrain_returned':True}}
        error,calls=self.http_error(json.dumps(body).encode());self.assertIsNone(error.compact_observation_diagnostic)
        self.assertEqual(error.compact_observation_diagnostic_status,'invalid');self.assertEqual(len(calls),1)
        raw=json.dumps(body).replace('"schema_version": 1','"schema_version":1,"schema_version":1').encode()
        error,calls=self.http_error(raw);self.assertIsNone(error.compact_observation_diagnostic);self.assertEqual(len(calls),1)
    def test_read_failure_preserves_original_owner_and_failure_evidence(self):
        result=[];resident=object.__new__(Resident);resident.paused=True;resident.reason='original_unknown'
        resident.observation_policy=lambda:{'requires_handoff':True,'input_release_unconfirmed':True}
        resident.finish=lambda *a,**k:result.append((a,k))
        resident.combat=SimpleNamespace(stop=lambda *a:(_ for _ in ()).throw(AssertionError('must not stop original owner')))
        error=BridgeError('compact_observation_terrain_budget_exhausted',uncertain=True,compact_observation_diagnostic=diagnostic(),compact_observation_diagnostic_status='reported')
        command={'op':'observe','compact_observation':True,'request_id':'compact-cost-one'}
        resident.command_error(command,error)
        self.assertEqual(result[0][0],(command,'uncertain'));self.assertEqual(result[0][1]['compact_observation_diagnostic'],diagnostic())
        self.assertEqual(resident.reason,'original_unknown');self.assertTrue(resident.paused)
    def test_actual_java_failure_codec_when_supplied(self):
        wire=os.environ.get('MDC_COMPACT_COST_WIRE')
        if not wire:self.skipTest('explicit production Java diagnostic HTTP codec fixture required')
        body=json.loads(Path(wire).read_text());self.assertEqual(body['error'],'compact_observation_terrain_budget_exhausted')
        self.assertTrue(valid_diagnostic(body['compact_observation_diagnostic'],'compact-cost-one',1))
    def test_actual_whole_callback_overbudget_retains_stage_evidence(self):
        path=os.environ.get('MDC_COMPACT_BUDGET_WIRE')
        if not path:self.skipTest('explicit production overbudget fixture required')
        body=json.loads(Path(path).read_text());self.assertEqual(body['error'],'compact_observation_budget_exhausted')
        d=body['compact_observation_diagnostic'];self.assertTrue(valid_diagnostic(d,'compact-one',1))
        self.assertEqual(d['stage'],'final_context');self.assertEqual(d['callback_elapsed_nanos'],'100000001')
        self.assertEqual(d['external_controller_samples'],1);self.assertEqual(d['external_controller_elapsed_nanos'],'79000000')
        error,calls=self.http_error(Path(path).read_bytes(),'compact-one')
        self.assertEqual(error.compact_observation_diagnostic,d);self.assertFalse(error.uncertain);self.assertEqual(len(calls),1)
    def test_stage_accounting_and_external_subspan_faults(self):
        for key,value in [('state','1'),('context','-1'),('terrain_ids',True)]:
            bad=diagnostic();bad['stage_elapsed_nanos'][key]=value
            self.assertFalse(valid_diagnostic(bad,'compact-cost-one',1))
        bad=diagnostic();bad['external_controller_samples']=2;self.assertFalse(valid_diagnostic(bad,'compact-cost-one',1))
    def test_timing_nested_terrain_and_future_phase_contradictions(self):
        bad=diagnostic();bad['terrain_elapsed_nanos']='9000001'
        self.assertFalse(valid_diagnostic(bad,'compact-cost-one',1))
        for stage in ('state','final_context','projection'):
            with self.subTest(stage=stage):
                bad=diagnostic();bad['stage_elapsed_nanos']['terrain_ids']='8999999'
                bad['stage_elapsed_nanos'][stage]='1'
                self.assertFalse(valid_diagnostic(bad,'compact-cost-one',1))
        good=diagnostic();good['terrain_elapsed_nanos']='9000000'
        self.assertTrue(valid_diagnostic(good,'compact-cost-one',1))
    def test_id_only_adapter_does_not_invoke_physics_or_mutation(self):
        root=Path(__file__).resolve().parents[2]
        source=(root/'client-mod/src/main/java/io/github/campione01/mineclientbridge/TerrainReader.java').read_text()
        section=source[source.index('static JsonObject compact('):source.index('static JsonObject clockPage(')]
        for forbidden in ('new LoadedSource','CollisionContext','getCollisionShape','getFluidState','getBrightness','getValues','getBlockEntity','setBlock','getChunk(x,z)'):
            self.assertNotIn(forbidden,section)
        self.assertIn('ChunkStatus.FULL,false',section);self.assertIn('scan.complete()&&!scan.budgetExhausted()',section)

if __name__=='__main__':unittest.main()
