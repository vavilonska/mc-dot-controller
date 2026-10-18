"""One refused renewal + one exact read; no retry or historical UNKNOWN settlement."""
from copy import deepcopy
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch
import json,threading,unittest
from resident_controller.transport import Bridge,BridgeError
from resident_controller import fall_rescue_control as f
from test_fall_rescue_evidence import COMMAND,ROWS
import test_fall_rescue_owner_chain as chain
from test_paused_owner_cleanup import PausedEndpoint

CANONICAL=json.loads((Path(__file__).parent/'fixtures/fall-renew-refusal-java-http.json').read_text())
REFUSED=next(row for row in CANONICAL if row['name']=='refused')

class Wire:
 def __init__(self):
  self.code=REFUSED['http_status'];self.raw=REFUSED['body'].encode();self.calls=[];self.stopped=None;parent=self
  class Handler(BaseHTTPRequestHandler):
   def log_message(self,*a):pass
   def do_POST(self):self.exchange()
   def do_GET(self):self.exchange()
   def exchange(self):
    raw=self.rfile.read(int(self.headers.get('Content-Length',0)))
    parent.calls.append((self.command,self.path,json.loads(raw) if raw else None))
    if self.command=='GET':code,raw=200,json.dumps(parent.stopped).encode()
    else:code,raw=parent.code,parent.raw
    self.send_response(code);self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
  self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler);self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
  self.bridge=Bridge('http://127.0.0.1:'+str(self.server.server_port),'synthetic-test-only')
 def close(self):self.server.shutdown();self.server.server_close();self.thread.join(2)

def fixture():
 command={**deepcopy(COMMAND),'operation':'renew','ttl_ms':5000,'expected_arm_revision':1,'request_id':'original-renewal','session_id':'resident'}
 prior=deepcopy(ROWS[0]);stopped={**deepcopy(prior),'armed':False,'status':'disarmed','reason':'user_screen_or_pause','remaining_ms':0}
 owner={'owner':command['control_owner'],'context':command['expected_context'],'arm_id':command['arm_id']}
 resident=NS(session_id='resident',running=True,paused=False,reason='ready',active=None,pending=[],combat=NS(active=False,held=False),aim=NS(active=False),
  bridge_identity={'action_session':'session'},_fall_rescue_owner=owner,_fall_rescue_status=prior)
 resident.observation_policy=lambda:{'schema_version':1,'requires_handoff':False,'input_release_unconfirmed':False}
 receipts=[];resident.finish=lambda *a,**kw:receipts.append((a,kw))
 return command,prior,stopped,resident,receipts

class RenewalTests(unittest.TestCase):
 def setUp(self):self.w=Wire();self.addCleanup(self.w.close)
 def test_exact_http_refusal_then_read_stopped_receipt(self):
  cmd,prior,stopped,r,receipts=fixture();r.bridge=self.w.bridge;self.w.stopped=stopped;f.execute(r,cmd)
  self.assertEqual([a[:2] for a in self.w.calls],[('POST','/control/fall-rescue/renew'),('GET','/control/fall-rescue/status')])
  value=receipts[0][1];self.assertEqual(receipts[0][0][1],'succeeded');self.assertEqual(value['reason'],'fall_rescue_renew_refused_stopped')
  self.assertEqual(f.validate_control_receipt(value,cmd,prior),stopped);self.assertFalse(r.paused);self.assertIsNotNone(r._fall_rescue_owner)
  with self.assertRaises(ValueError):f.validate_status(stopped,cmd,prior)
 def test_ambiguous_or_wrong_refusal_never_reads_or_retries(self):
  bad=[(500,self.w.raw),(400,self.w.raw),(409,b'{"ok":false,"error":"fall_rescue_owner_changed"}'),
   (409,b'{"ok":false,"error":"fall_rescue_not_armed","extra":true}'),
   (409,b'{"ok":false,"error":"fall_rescue_not_armed","error":"fall_rescue_not_armed"}'),
   (409,b'{"ok":0,"error":"fall_rescue_not_armed"}'),(409,b'{'),(200,b'{"ok":false,"error":"fall_rescue_not_armed"}')]
  for code,raw in bad:
   cmd,prior,stopped,r,receipts=fixture();r.bridge=self.w.bridge;self.w.code,self.w.raw=code,raw;before=len(self.w.calls)
   with self.subTest(code=code,raw=raw),self.assertRaises(BridgeError):f.execute(r,cmd)
   self.assertEqual(len(self.w.calls)-before,1);self.assertFalse(receipts);self.assertTrue(r.paused)
 def test_other_canonical_native_refusals_never_read(self):
  for row in CANONICAL:
   if row['name']=='refused':continue
   cmd,prior,stopped,r,receipts=fixture();r.bridge=self.w.bridge;self.w.code=row['http_status'];self.w.raw=row['body'].encode();before=len(self.w.calls)
   with self.assertRaises(BridgeError):f.execute(r,cmd)
   self.assertEqual(len(self.w.calls)-before,1);self.assertFalse(receipts)
 def test_transport_error_even_with_matching_text_never_reads(self):
  for error in (BridgeError('fall_rescue_not_armed',uncertain=True,status=409),BridgeError('fall_rescue_not_armed',status=409)):
   cmd,prior,stopped,r,receipts=fixture();calls=[]
   def request(*a):calls.append(a);raise error
   r.bridge=NS(request=request)
   with self.assertRaises(BridgeError):f.execute(r,cmd)
   self.assertEqual(len(calls),1);self.assertFalse(receipts)
 def test_stopped_status_missing_foreign_attempted_or_other_reason_unknown(self):
  edits=[lambda v:v.update(owner_id='foreign'),lambda v:v.update(arm_id='foreign'),lambda v:v.update(action_session='foreign'),
   lambda v:v.update(world_generation='foreign'),lambda v:v.update(player_uuid='foreign'),lambda v:v.update(arm_revision=2),
   lambda v:v.update(unknown_outcome_quarantined=True),lambda v:v.update(automation_blocked=True),
   lambda v:v.update(reason='arm_lease_expired'),lambda v:v.update(armed=True),lambda v:v.update(input_owned=True),
   lambda v:v.pop('episodes_used'),lambda v:v.update(last_episode=None),lambda v:v.update(extra=True)]
  for edit in edits:
   cmd,prior,stopped,r,receipts=fixture();edit(stopped);r.bridge=self.w.bridge;self.w.stopped=stopped;before=len(self.w.calls)
   with self.assertRaises(BridgeError):f.execute(r,cmd)
   self.assertEqual(len(self.w.calls)-before,2);self.assertFalse(receipts);self.assertTrue(r.paused)
  cmd,prior,stopped,r,receipts=fixture();r._fall_rescue_status=deepcopy(ROWS[2]);r.bridge=self.w.bridge;self.w.stopped=stopped
  with self.assertRaises(BridgeError):f.execute(r,cmd)
  self.assertFalse(receipts)
 def test_final_read_callback_replacement_never_inherits_or_pauses(self):
  for stage in ('post','get','policy'):
   cmd,prior,stopped,r,receipts=fixture();replacement={'replacement':True};self.w.stopped=stopped;real=self.w.bridge.request
   def request(method,path,body=None):
    try:return real(method,path,body)
    finally:
     if (stage=='post' and method=='POST') or (stage=='get' and method=='GET'):r._fall_rescue_owner=replacement
   r.bridge=NS(request=request)
   if stage=='policy':
    calls=[0]
    def policy():
     calls[0]+=1
     if calls[0]>=3:r._fall_rescue_owner=replacement
     return {'schema_version':1,'requires_handoff':False,'input_release_unconfirmed':False}
    r.observation_policy=policy
   with self.assertRaises(BridgeError):f.execute(r,cmd)
   self.assertIs(r._fall_rescue_owner,replacement);self.assertFalse(r.paused);self.assertFalse(receipts);self.assertIs(r._fall_rescue_status,prior)
 def test_stop_session_and_busy_during_get_refuse(self):
  for edit in (lambda r:setattr(r,'paused',True),lambda r:setattr(r,'session_id','foreign'),
    lambda r:r.bridge_identity.update(action_session='foreign'),lambda r:setattr(r,'active',object()),
    lambda r:setattr(r,'running',False),
    lambda r:r.pending.append({'op':'stop'})):
   cmd,prior,stopped,r,receipts=fixture();self.w.stopped=stopped;real=self.w.bridge.request
   def request(method,path,body=None):
    value=real(method,path,body)
    if method=='GET':edit(r)
    return value
   r.bridge=NS(request=request)
   with self.assertRaises(BridgeError):f.execute(r,cmd)
   self.assertFalse(receipts);self.assertIs(r._fall_rescue_status,prior)
 def test_in_place_prior_status_mutation_cannot_weaken_evidence(self):
  for stage in ('get','policy'):
   cmd,prior,stopped,r,receipts=fixture();self.w.stopped=stopped;real=self.w.bridge.request
   def request(method,path,body=None):
    value=real(method,path,body)
    if stage=='get' and method=='GET':prior['reason']='mutated_in_place'
    return value
   r.bridge=NS(request=request)
   if stage=='policy':
    calls=[0]
    def policy():
     calls[0]+=1
     if calls[0]>=3:prior['reason']='mutated_in_place'
     return {'schema_version':1,'requires_handoff':False,'input_release_unconfirmed':False}
    r.observation_policy=policy
   with self.assertRaises(BridgeError):f.execute(r,cmd)
   self.assertFalse(receipts);self.assertIs(r._fall_rescue_status,prior);self.assertEqual(prior['reason'],'mutated_in_place')
 def test_runtime_closed_marker_cannot_relax_normal_renew(self):
  cmd,prior,stopped,r,receipts=fixture();proof=f.renewal_stop_proof(cmd)
  for key in list(proof):
   p=deepcopy(proof);p.pop(key)
   with self.assertRaises(ValueError):f.validate_control_receipt({'result':stopped,'fall_rescue_renewal_stop':p},cmd,prior)
  with self.assertRaises(ValueError):f.validate_control_receipt({'result':stopped},cmd,prior)
  p=deepcopy(proof);p['request']['expected_arm_revision']=2
  with self.assertRaises(ValueError):f.validate_control_receipt({'result':stopped,'fall_rescue_renewal_stop':p},cmd,prior)
 def test_native_refusal_is_before_renewal_mutation_source_parity(self):
  p=Path(__file__).resolve().parents[2]/'client-mod/src/main/java/io/github/campione01/mineclientbridge/NativeFallRescue.java'
  text=p.read_text().split('static JsonObject renew(',1)[1].split('static JsonObject disarm',1)[0]
  self.assertIn('thread(mc);long operation=OPERATIONS.stamp();require(authorization!=null,"fall_rescue_not_armed")',text)
  self.assertLess(text.index('fall_rescue_not_armed'),text.index('OPERATIONS.commit'))
  self.assertLess(text.index('fall_rescue_not_armed'),text.index('deadline=System.nanoTime()'))

class Endpoint(PausedEndpoint):
 def __init__(self):super().__init__();self.wire=Wire();self.refusal_edit=None
 def request(self,method,path,body=None):
  if path=='/control/fall-rescue/renew':
   self.fall_calls.append(('renew',deepcopy(body)));self.game_paused=True
   self.fall.update(armed=False,status='disarmed',reason='user_screen_or_pause',remaining_ms=0)
   if self.refusal_edit:self.refusal_edit(self)
   return self.wire.bridge.request(method,path,body)
  if path=='/control/fall-rescue/status' and self.game_paused:
   self.fall_calls.append(('status',None));self.wire.stopped=deepcopy(self.fall)
   return self.wire.bridge.request(method,path,body)
  return super().request(method,path,body)

class OwnerChainTests(unittest.TestCase):
 until=chain.FallOwnerChainTests.until;submit=chain.FallOwnerChainTests.submit;finish=chain.FallOwnerChainTests.finish
 def setUp(self):
  with patch.object(chain,'Endpoint',Endpoint):chain.FallOwnerChainTests.setUp(self)
 def tearDown(self):chain.FallOwnerChainTests.tearDown(self);self.bridge.wire.close()
 def test_original_guard_known_interrupted_and_exact_paused_cleanup(self):
  result=self.finish(self.submit(duration_ms=2200));self.assertEqual(result['state'],'interrupted',result)
  self.assertEqual(result['effect_certainty'],'none_proven');self.assertEqual(result['cleanup_certainty'],'confirmed')
  ops=[op for op,_ in self.bridge.fall_calls];self.assertEqual(ops.count('arm'),1);self.assertEqual(ops.count('renew'),1);self.assertEqual(ops.count('disarm'),1)
  self.assertEqual([x[:2] for x in self.bridge.wire.calls],[('POST','/control/fall-rescue/renew'),('GET','/control/fall-rescue/status')])
  self.assertTrue(self.bridge.game_paused);self.until(lambda:self.client.session()['state']=='paused')
  self.assertIsNone(self.client.session()['capability_lease']);self.assertIn('error',self.submit('no-auto-resume'))
  records=[v for v in self.runtime._journal['records'].values() if v['kind']=='fall_rescue_control']
  self.assertTrue(any(v.get('reason')=='fall_rescue_renew_refused_stopped' for v in records),records)
 def test_wrong_stop_reason_keeps_original_unknown_without_disarm(self):
  self.bridge.refusal_edit=lambda e:e.fall.update(reason='arm_lease_expired')
  result=self.finish(self.submit(duration_ms=2200));self.assertEqual(result['state'],'unknown',result)
  self.assertIsNotNone(self.client.session()['capability_lease']);self.assertNotIn('disarm',[op for op,_ in self.bridge.fall_calls])

if __name__=='__main__':unittest.main()
