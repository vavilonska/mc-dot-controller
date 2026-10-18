"""Production Java response bytes through real HTTP, Resident and Runtime validators.

Generate with ExternalNavigationWireFixtures and set MDC_EXTERNAL_NAVIGATION_WIRE_FIXTURE.
The Java producer calls the same status model, ActionResponses, and BridgeJson as HTTP.
"""
from contextlib import contextmanager
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import threading
from types import SimpleNamespace
import unittest

from mdc_skills.external_navigation import exchange
from resident_controller.external_navigation_control import execute, native_body, validate_status
from resident_controller.transport import Bridge, BridgeError


def command(operation='stop'):
    return {'op':'external_navigation_control','operation':operation,'operation_id':'a'*32,
        'control_owner':{'owner_id':'b'*32,'owner_generation':1,'job_id':'job_original'},
        'expected_context':{'action_session':'session','world_generation':'world','player_uuid':'player','dimension':'minecraft:overworld'},
        'source':{'source_tick':9,'source_nano':'1234'},'timeout_ms':1000,
        'expected_resident_session':'resident','request_id':'transport_original','session_id':'resident','submitted_at':0}


@contextmanager
def http_rows(rows):
    calls=[];queue=list(rows)
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def respond(self):
            body=self.rfile.read(int(self.headers.get('Content-Length','0')))
            calls.append((self.command,self.path,body))
            row=queue.pop(0);data=row['wire'].encode()
            self.send_response(row['http_status']);self.send_header('Content-Type','application/json')
            self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
        do_GET=respond;do_POST=respond
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:yield Bridge(f'http://127.0.0.1:{server.server_port}','offline-fixture-only'),calls
    finally:server.shutdown();server.server_close();thread.join(2)


def resident(bridge):
    receipts=[]
    r=SimpleNamespace(session_id='resident',bridge_identity={'action_session':'session'},bridge=bridge,
        paused=False,reason=None,active=None,pending=[],combat=SimpleNamespace(active=False,held=False),
        aim=SimpleNamespace(active=False),observation_policy=lambda:{'requires_handoff':False,'input_release_unconfirmed':False})
    r.finish=lambda c,status,**kw:receipts.append({'request_id':c['request_id'],'status':status,**kw})
    return r,receipts


def runtime_exchange(r,receipts,operation='stop',control=None):
    c=command(operation);binding={k:c[k] for k in ('operation_id','control_owner','expected_context','source','timeout_ms')}
    finished=[]
    def perform(record):
        execute(r,c);return receipts[-1]
    def unknown(*args):raise RuntimeError('retained_unknown')
    runtime=SimpleNamespace(_mutex=threading.RLock(),has_unresolved_execution=False,
        _session=lambda:{'external_navigation_owner_control':'external-navigation-owner-control/1'},
        _lease_info={'resident_session':'resident'},_owned_command=lambda body,session:body,
        _reserve=lambda *a,**kw:{'request_id':c['request_id']},_exchange=perform,_unknown=unknown,
        _finish=lambda *a:finished.append(a))
    if control is None:control=SimpleNamespace(lane='ordinary',checkpoint=lambda:None,consume=lambda *a:None,
        stop_reason=lambda:None,emit=lambda *a:None)
    return exchange(runtime,control,operation,binding),control,finished


class ExternalNavigationWire(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path=os.environ.get('MDC_EXTERNAL_NAVIGATION_WIRE_FIXTURE')
        if not path:raise unittest.SkipTest('actual Java fixture required; set MDC_EXTERNAL_NAVIGATION_WIRE_FIXTURE')
        cls.rows={r['name']:r for r in json.loads(Path(path).read_text())}
        assert set(cls.rows)=={'busy_attempted','one_idle_sample','settled_attempted','already_idle_pending',
            'already_idle_settled','attempted_unknown_null','unowned_idle','rejected'}

    def test_actual_pending_to_settled_through_http_resident_and_runtime(self):
        rows=[self.rows[n] for n in ('busy_attempted','one_idle_sample','settled_attempted')]
        with http_rows(rows) as (bridge,calls):
            r,receipts=resident(bridge);pending,control,_=runtime_exchange(r,receipts)
            self.assertTrue(pending['input_owned']);self.assertFalse(pending['control_released'])
            sample,_,_=runtime_exchange(r,receipts,'status',control)
            self.assertEqual(sample['idle_samples'],1);self.assertFalse(sample['control_released'])
            settled,_,finished=runtime_exchange(r,receipts,'status',control)
            self.assertTrue(settled['control_released']);self.assertIsNone(r._external_navigation_owner)
            self.assertEqual([c[0] for c in calls],['POST','GET','GET'])
            self.assertEqual(json.loads(calls[0][2])['operation_id'],'a'*32)
            self.assertEqual(receipts[-1]['request_id'],'transport_original')
            self.assertEqual(finished[-1][3]['job_id'],'job_original')
            self.assertNotIn('protocol',settled)

    def test_actual_already_idle_null_through_entire_chain(self):
        with http_rows([self.rows[n] for n in ('already_idle_pending','already_idle_settled')]) as (bridge,calls):
            r,receipts=resident(bridge);value,control,_=runtime_exchange(r,receipts)
            self.assertFalse(value['stop_attempted']);self.assertIsNone(value['cancel_accepted'])
            value,_,_=runtime_exchange(r,receipts,'status',control)
            self.assertTrue(value['control_released']);self.assertFalse(value['stop_attempted'])
            self.assertIsNone(value['cancel_accepted']);self.assertEqual(len(calls),2)

    def test_actual_raw_embedded_state_and_nullable_scope(self):
        for name,row in self.rows.items():
            if 'embedded_wire' not in row:continue
            value=json.loads(row['embedded_wire']);state=json.loads(row['state_wire'])
            self.assertEqual(state['external_navigation_status'],value)
            self.assertNotIn('unrelated_null',state);self.assertEqual(state['unrelated'],{'external_navigation_schema_version':1})
            self.assertNotIn('cancel_accepted',json.loads(row['boolean_schema_wire']))
            self.assertNotIn('cancel_accepted',json.loads(row['floating_schema_wire']))
            if name in ('attempted_unknown_null','unowned_idle'):continue
            self.assertEqual(validate_status(value,command()),validate_status(json.loads(row['wire']),command()))
            if name.startswith('already_idle'):self.assertIn('cancel_accepted',value);self.assertIsNone(value['cancel_accepted'])

    def test_exact_wrapper_and_required_null_negative_shapes(self):
        good=json.loads(self.rows['already_idle_settled']['wire'])
        bads=[]
        for key,val in [('protocol','other'),('protocol',True),('schema_version',True),('schema_version',2.0),('schema_version',1),('extra',False)]:
            bad=deepcopy(good);bad[key]=val;bads.append(bad)
        for key in ('protocol','schema_version','cancel_accepted'):
            bad=deepcopy(good);bad.pop(key);bads.append(bad)
        for bad in bads:
            with self.subTest(bad=bad),self.assertRaises(ValueError):validate_status(bad,command())
        # A malformed wrapper reaching HTTP still cannot release Resident ownership.
        row={'http_status':200,'wire':json.dumps({**good,'schema_version':True})}
        with http_rows([row]) as (bridge,calls):
            r,receipts=resident(bridge)
            with self.assertRaises(BridgeError):runtime_exchange(r,receipts)
            self.assertTrue(r.paused);self.assertIsNotNone(r._external_navigation_owner);self.assertEqual(receipts,[])
            self.assertEqual(len(calls),1)

    def test_actual_unknown_and_http_error_never_settle_or_retry(self):
        for name in ('attempted_unknown_null','unowned_idle','rejected'):
            with self.subTest(name=name),http_rows([self.rows[name]]) as (bridge,calls):
                r,receipts=resident(bridge)
                with self.assertRaises(BridgeError) as caught:runtime_exchange(r,receipts)
                self.assertTrue(caught.exception.uncertain);self.assertTrue(r.paused)
                self.assertIsNotNone(r._external_navigation_owner);self.assertEqual(receipts,[])
                self.assertEqual(len(calls),1);self.assertEqual(calls[0][0],'POST')
                self.assertEqual(r._external_navigation_owner['operation_id'],'a'*32)

    def test_runtime_independently_rejects_forged_receipt_wrapper(self):
        good=json.loads(self.rows['settled_attempted']['wire']);good['protocol']='foreign'
        r,receipts=resident(None)
        # Resident is intentionally replaced only to inject a corrupt IPC receipt;
        # the public Runtime exchange must independently retain UNKNOWN.
        from unittest.mock import patch
        with patch(__name__+'.execute',lambda r,c:receipts.append({'status':'succeeded','result':good,'control_owner':c['control_owner']})):
            with self.assertRaisesRegex(RuntimeError,'retained_unknown'):runtime_exchange(r,receipts)

if __name__=='__main__':unittest.main()
