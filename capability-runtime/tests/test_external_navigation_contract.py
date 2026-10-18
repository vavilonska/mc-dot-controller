"""Stop-only proof, transport, monotonic status and final unsent-cancel boundaries."""
from copy import deepcopy
from types import SimpleNamespace
import unittest
from urllib.parse import urlsplit
from unittest.mock import patch
from resident_controller.external_navigation_control import validate,validate_native_request,validate_status,native_body
from resident_controller.transport import _external_request
from mdc_skills.external_navigation import exchange
from mdc_skills.core import SkillError

class StopContracts(unittest.TestCase):
    def command(self):
        return {'op':'external_navigation_control','operation':'stop','operation_id':'a'*32,
            'control_owner':{'owner_id':'b'*32,'owner_generation':1,'job_id':'job_original'},
            'expected_context':{'action_session':'session','world_generation':'world','player_uuid':'player','dimension':'minecraft:overworld'},
            'source':{'source_tick':9,'source_nano':'1234'},'timeout_ms':1000,
            'expected_resident_session':'resident','request_id':'transport','session_id':'resident','submitted_at':0}
    def status(self):
        c=self.command();return {'external_navigation_schema_version':1,'operation_id':c['operation_id'],**c['control_owner'],**c['expected_context'],
            'input_owned':True,'unknown_outcome_quarantined':False,'no_auto_resume':True,'execution_authority':False,
            'state':'stopping','reason':'awaiting_actual_idle','stop_attempted':True,'cancel_accepted':True,
            'control_released':False,'admission_tick':9,'idle_samples':0,'source_tick':9,'remaining_ms':900,
            'external_controller':{'schema_version':1,'execution_authority':False,'world_generation':'world','player_uuid':'player','action_session':'session',
                'source_tick':9,'source_nano':'1234','controller':'baritone','adapter':'baritone-api-neoforge/1.11.3',
                'reason':'version_pinned_actual_api_sample','supported':True,'idle_proven':False,'status':'busy',
                'facts':{'context_matches':True,'instances':1,'is_pathing':True,'current_path':True,'next_path':False,'planning':False,
                    'goal_present':True,'active_process_count':1,'registered_process_count':12,'forced_input_count':1}}}
    def test_closed_native_wire_transport(self):
        body=native_body(self.command());validate_native_request(body)
        _external_request('POST',urlsplit('/control/external-navigation/stop'),body)
        _external_request('GET',urlsplit('/control/external-navigation/status'),None)
        for field,value in [('source_tick',True),('owner_generation',False),('timeout_ms',10001),('source_nano','1e4'),('job_id','../escape'),('extra',1)]:
            bad={**body,field:value}
            with self.subTest(field=field),self.assertRaises(ValueError):validate_native_request(bad)
        for method,url,b in [('POST','/control/external-navigation/forceCancel',body),('GET','/control/external-navigation/status?owner=anything',None),('GET','/control/external-navigation/stop',None),('POST','/control/external-navigation/stop',None)]:
            with self.assertRaises(ValueError):_external_request(method,urlsplit(url),b)
    def test_cancel_ack_is_not_settlement(self):
        value=validate_status(self.status(),self.command());self.assertFalse(value['control_released'])
        bad=self.status();bad['control_released']=True
        with self.assertRaises(ValueError):validate_status(bad,self.command())
    def test_foreign_identity_and_unknown_cannot_settle(self):
        for field,value in [('operation_id','c'*32),('owner_id','c'*32),('owner_generation',2),('job_id','job_other'),('source_tick',True),('execution_authority',True)]:
            bad=self.status();bad[field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):validate_status(bad,self.command())
        bad=self.status();bad.update(state='unknown',unknown_outcome_quarantined=True)
        with self.assertRaises(ValueError):validate_status(bad,self.command())
    def test_settled_requires_exact_idle_proof_and_two_ticks(self):
        good=self.status();good.update(state='settled',input_owned=False,control_released=True,idle_samples=2,source_tick=11)
        good['external_controller'].update(status='idle',idle_proven=True,source_tick=11)
        good['external_controller']['facts'].update(is_pathing=False,current_path=False,goal_present=False,active_process_count=0,forced_input_count=0)
        self.assertTrue(validate_status(good,self.command(),self.status())['control_released'])
        for mutate in (lambda v:v.update(admission_tick=10),lambda v:v.update(idle_samples=1),lambda v:v['external_controller'].update(idle_proven=False),lambda v:v['external_controller'].update(source_tick=10)):
            bad=deepcopy(good);mutate(bad)
            with self.assertRaises(ValueError):validate_status(bad,self.command())
    def test_closed_actual_proof_rejects_contradiction_boolean_types_and_missing_fields(self):
        good=self.status();good.update(state='settled',input_owned=False,control_released=True,idle_samples=2,source_tick=11)
        good['external_controller'].update(status='idle',idle_proven=True,source_tick=11)
        good['external_controller']['facts'].update(is_pathing=False,current_path=False,goal_present=False,active_process_count=0,forced_input_count=0)
        for field,value in [('schema_version',True),('source_tick',True),('controller','other'),('adapter','unverified')]:
            bad=deepcopy(good);bad['external_controller'][field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):validate_status(bad,self.command())
        for field in good['external_controller']:
            bad=deepcopy(good);bad['external_controller'].pop(field)
            with self.subTest(missing=field),self.assertRaises(ValueError):validate_status(bad,self.command())
        for field,value in [('is_pathing',True),('current_path',True),('next_path',True),('planning',True),('goal_present',True),
                            ('active_process_count',1),('forced_input_count',1),('instances',True),('registered_process_count',True),('context_matches',False)]:
            bad=deepcopy(good);bad['external_controller']['facts'][field]=value
            with self.subTest(fact=field),self.assertRaises(ValueError):validate_status(bad,self.command())
    def test_status_cannot_erase_attempt_or_change_ack(self):
        previous=self.status()
        for field,value in [('stop_attempted',False),('cancel_accepted',False),('source_tick',8)]:
            bad=deepcopy(previous);bad[field]=value
            with self.assertRaises(ValueError):validate_status(bad,self.command(),previous)
    def test_final_local_stop_after_reservation_sends_nothing(self):
        import threading
        sent=[];finished=[];control=SimpleNamespace(lane='ordinary',checkpoint=lambda:None,consume=lambda *a:None,stop_reason=lambda:'cancel_requested')
        runtime=SimpleNamespace(_mutex=threading.RLock(),has_unresolved_execution=False,
            _session=lambda:{'external_navigation_owner_control':'external-navigation-owner-control/1'},
            _owned_command=lambda body,session:body,_reserve=lambda *a,**k:{'request_id':'reserved'},
            _finish=lambda *a:finished.append(a),_exchange=lambda *a:sent.append(a))
        c=self.command();binding={k:c[k] for k in ('operation_id','control_owner','expected_context','source','timeout_ms')}
        with self.assertRaises(SkillError):exchange(runtime,control,'stop',binding)
        self.assertEqual(sent,[]);self.assertEqual(finished[0][2],'cancel_requested')

if __name__=='__main__':unittest.main()
