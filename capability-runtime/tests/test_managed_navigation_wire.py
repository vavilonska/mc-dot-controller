"""Actual Java route model/wrapper/codec bytes through HTTP, Resident and Runtime."""
from copy import deepcopy
import json,os,threading,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from test_external_navigation_wire import http_rows,resident
from resident_controller.managed_navigation_control import execute,validate_status,validate_native_request,native_body,BINDING
from resident_controller.transport import BridgeError
from mdc_skills.managed_navigation import exchange

def command(operation='start'):
    return {'op':'managed_navigation_control','operation':operation,'operation_id':'a'*32,
        'control_owner':{'owner_id':'b'*32,'owner_generation':1,'job_id':'job_original'},
        'expected_context':{'action_session':'session','world_generation':'world','player_uuid':'player','dimension':'minecraft:overworld'},
        'source':{'source_tick':9,'source_nano':'1234'},'goal':{'x':100,'y':64,'z':100},'max_distance':200,'min_health':12,'timeout_ms':1000,
        'expected_resident_session':'resident','request_id':'route_request_original','session_id':'resident','submitted_at':0}
def run_exchange(r,receipts,operation='start',control=None):
    c=command(operation);binding={k:c[k] for k in BINDING};finished=[]
    def perform(record,**kwargs):execute(r,c);return receipts[-1]
    def unknown(*args):raise RuntimeError('retained_unknown')
    runtime=SimpleNamespace(_mutex=threading.RLock(),has_unresolved_execution=False,
        _session=lambda:{'managed_navigation_owner_control':'managed-navigation-owner-control/1','defense_epoch':0},
        _lease_info={'resident_session':'resident','context':c['expected_context']},
        _job_effect_certainty='none_proven',owner_context=lambda:c['control_owner'],_owned_command=lambda body,session:body,
        _reserve=lambda *a,**kw:{'request_id':c['request_id']},_exchange=perform,_unknown=unknown,
        _finish=lambda *a:finished.append(a))
    if control is None:control=SimpleNamespace(lane='ordinary',checkpoint=lambda:None,consume=lambda *a:None,stop_reason=lambda:None,emit=lambda *a:None)
    # This codec harness supplies a modeled upstream observation boundary; the
    # separate owner-chain tests exercise the real fresh observation acquisition.
    from resident_controller.external_navigation_control import CONTEXT
    from test_external_navigation_owner import Endpoint
    endpoint=Endpoint();endpoint.busy=False;state=endpoint.snapshot()
    proof=state['external_controller'];proof.update(c['source'],**{k:c['expected_context'][k] for k in
        ('action_session','world_generation','player_uuid')})
    before=SimpleNamespace(context=tuple(c['expected_context'][k] for k in CONTEXT),state={'external_controller':proof},
        tick=c['source']['source_tick'],captured_at=0,_gateway_epoch=0)
    runtime._fresh=lambda value:None;runtime.clock=lambda:0;control.job_id=c['control_owner']['job_id']
    return exchange(runtime,control,operation,binding,before=before if operation=='start' else None),control

class ManagedWireTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path=os.environ.get('MDC_MANAGED_NAVIGATION_WIRE_FIXTURE')
        if not path:raise unittest.SkipTest('generate actual Java fixture and set MDC_MANAGED_NAVIGATION_WIRE_FIXTURE')
        cls.rows={r['name']:r for r in json.loads(Path(path).read_text())}
        assert set(cls.rows)=={'routing','one_idle_sample','settled_goal','stopping','settled_cancel','unknown','unowned_idle','rejected'}
    def test_native_command_closed(self):
        body=native_body(command());self.assertEqual(body,json.loads(self.rows['routing']['request_wire']));validate_native_request(body)
        for key,value in [('timeout_ms',120001),('max_distance',201),('min_health',5),('source_tick',True),('goal_x',True),('extra',0)]:
            with self.subTest(key=key),self.assertRaises(ValueError):validate_native_request({**body,key:value})
    def test_canonical_start_pending_and_goal_settlement(self):
        with http_rows([self.rows[k] for k in ('routing','one_idle_sample','settled_goal')]) as (bridge,calls):
            r,receipts=resident(bridge);first,control=run_exchange(r,receipts)
            self.assertIsNone(first['cancel_accepted']);self.assertFalse(first['control_released'])
            sample,_=run_exchange(r,receipts,'status',control);self.assertEqual(sample['idle_samples'],1)
            result,_=run_exchange(r,receipts,'status',control)
            self.assertTrue(result['goal_reached']);self.assertTrue(result['settings_restored']);self.assertTrue(result['control_released'])
            self.assertIsNone(r._managed_navigation_owner);self.assertEqual([c[0] for c in calls],['POST','GET','GET'])
            self.assertEqual(receipts[-1]['request_id'],'route_request_original')
    def test_canonical_cancel_ack_does_not_release(self):
        with http_rows([self.rows[k] for k in ('routing','stopping','settled_cancel')]) as (bridge,calls):
            r,receipts=resident(bridge);_,control=run_exchange(r,receipts)
            pending,_=run_exchange(r,receipts,'cancel',control);self.assertTrue(pending['cancel_accepted']);self.assertFalse(pending['control_released'])
            with self.assertRaises(ValueError):execute(r,command('cancel'))
            self.assertEqual(len(calls),2)
            final,_=run_exchange(r,receipts,'status',control);self.assertTrue(final['control_released']);self.assertFalse(final['goal_reached'])
            self.assertEqual([c[1] for c in calls],['/control/managed-navigation/start','/control/managed-navigation/cancel','/control/managed-navigation/status'])
    def test_exact_raw_embedded_model_and_nullable_scope(self):
        for name,row in self.rows.items():
            if 'embedded_wire' not in row:continue
            raw=json.loads(row['embedded_wire']);state=json.loads(row['state_wire'])
            self.assertEqual(state['managed_navigation_status'],raw)
            if raw.get('cancel_accepted','missing') is None:self.assertNotIn('cancel_accepted',state['unrelated'])
            if name not in ('unknown','unowned_idle'):
                self.assertEqual(validate_status(raw,command()),validate_status(json.loads(row['wire']),command()))
    def test_closed_settled_proof_rejects_false_release(self):
        good=json.loads(self.rows['settled_goal']['wire'])
        for key,value in [('schema_version',True),('schema_version',2.0),('protocol','foreign'),('goal_x',101),('settings_restored',False),
            ('start_attempted',False),('source_tick',True),('idle_samples',1),('unloaded_terrain_certified',True),('extra',0)]:
            with self.subTest(key=key),self.assertRaises(ValueError):validate_status({**good,key:value},command())
        for key in ('protocol','schema_version','cancel_accepted'):
            bad=deepcopy(good);bad.pop(key)
            with self.assertRaises(ValueError):validate_status(bad,command())
        for fact in ('planning','goal_present','is_pathing','current_path','next_path'):
            bad=deepcopy(good);bad['external_controller']['facts'][fact]=True
            with self.assertRaises(ValueError):validate_status(bad,command())
        running=json.loads(self.rows['routing']['wire'])
        for key,value in [('settings_restored',True),('goal_reached',True),('stop_attempted',True)]:
            with self.subTest(key=key),self.assertRaises(ValueError):validate_status({**running,key:value},command())
        stopped=validate_status(json.loads(self.rows['stopping']['wire']),command())
        regressed={**running,'stop_attempted':True,'cancel_accepted':True}
        with self.assertRaises(ValueError):validate_status(regressed,command(),stopped)
    def test_unknown_error_or_unowned_status_preserves_owner(self):
        for name in ('unknown','rejected','unowned_idle'):
            with self.subTest(name=name),http_rows([self.rows[name]]) as (bridge,calls):
                r,receipts=resident(bridge)
                with self.assertRaises(BridgeError) as caught:run_exchange(r,receipts)
                self.assertTrue(caught.exception.uncertain);self.assertTrue(r.paused);self.assertIsNotNone(r._managed_navigation_owner)
                self.assertEqual(len(calls),1);self.assertEqual(receipts,[])
    def test_runtime_revalidates_corrupt_ipc_status(self):
        forged=json.loads(self.rows['settled_goal']['wire']);forged['settings_restored']=False;r,receipts=resident(None)
        with patch(__name__+'.execute',lambda r,c:receipts.append({'status':'succeeded','result':forged,'control_owner':c['control_owner']})):
            with self.assertRaisesRegex(RuntimeError,'retained_unknown'):run_exchange(r,receipts)

if __name__=='__main__':unittest.main()
