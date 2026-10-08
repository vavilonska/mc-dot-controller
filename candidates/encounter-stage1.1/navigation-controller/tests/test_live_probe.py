from copy import deepcopy
from dataclasses import replace
import io
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from navigation_controller.fake import FakeClock
from navigation_controller.live_probe import (ProbeError, cleanup_summary, main, one_action_test,
                                              read_only_probe, session_fingerprint, safe_failure)
from navigation_controller.sample_adapter import GuardedSampleAdapter, SampleConfig, SampleError
from navigation_controller.sample_fake import FakeSampleTransport
from navigation_controller.terrain import WorldStamp


class MockLiveTransport(FakeSampleTransport):
    """Non-simulation marker exercises live gates but inherits NO networking."""
    simulation_only=False
    def __init__(self,clock,enabled=False,accepted=False):
        super().__init__(clock)
        self.config=SimpleNamespace(enabled=enabled,acceptance_verified=accepted)
        self.closed=False

    def request(self,*args,**kwargs):
        if self.closed:raise RuntimeError('mock transport closed')
        return super().request(*args,**kwargs)

    def close(self):self.closed=True


class ProbeTests(unittest.TestCase):
    def setUp(self):
        self.clock=FakeClock()
        self.transport=MockLiveTransport(self.clock)

    def arm(self):
        self.transport.config=SimpleNamespace(enabled=True,acceptance_verified=True)
        return session_fingerprint(self.transport._status())

    def act(self,**kwargs):
        args=dict(action='forward-sample',expected_session=self.arm(),accept_local_test=True,
                  accept_installed_guard_build=True,accept_unpublished_survival=True)
        args.update(kwargs)
        return one_action_test(self.transport,self.clock,**args)

    def test_default_probe_sends_get_only(self):
        report=read_only_probe(self.transport,self.clock)
        self.assertEqual(report['mode'],'read_only')
        self.assertEqual(report['result'],'read_only_observations_verified')
        self.assertFalse(report['input_sent'])
        self.assertEqual(report['terrain']['cells'],27)
        self.assertTrue(all(method=='GET' for method,_,_ in self.transport.calls))
        self.assertFalse(self.transport.actions)

    def test_report_has_no_raw_identity_or_private_payload(self):
        def hook(method,path,body,result):
            result['desktop_name']='PRIVATE-DESKTOP'
            result['runtime_root']='/private/runtime'
            if 'player' in result:result['player']['name']='PRIVATE-OWNER'
            return result
        self.transport.response_hook=hook
        report=json.dumps(read_only_probe(self.transport,self.clock))
        for private in ('PRIVATE-DESKTOP','/private/runtime','PRIVATE-OWNER',*map(str,self.transport.identity[:1]),
                        self.transport.identity[2],self.transport.identity[3],self.transport.session):
            self.assertNotIn(private,report)
        self.assertEqual(len(json.loads(report)['session_fingerprint']),64)

    def test_probe_tolerates_default_disabled_capabilities(self):
        def hook(method,path,body,result):
            if path=='/control/capabilities':
                result['guarded_movement']['enabled']=False
                result['guarded_turn']['enabled']=False
            return result
        self.transport.response_hook=hook
        result=read_only_probe(self.transport,self.clock)
        self.assertFalse(result['movement_enabled'])
        self.assertFalse(result['turn_enabled'])
        self.assertFalse(self.transport.actions)

    def test_no_world_report_does_not_read_terrain_or_state(self):
        def hook(method,path,body,result):
            if path=='/control/status':result['in_world']=False
            return result
        self.transport.response_hook=hook
        result=read_only_probe(self.transport,self.clock)
        self.assertEqual(result['result'],'local_world_required_for_terrain')
        self.assertEqual(len(self.transport.calls),2)

    def test_probe_supports_real_budget_pagination(self):
        transport=self.transport
        original=transport.request
        pages=transport.world.pages(radius=1,vertical=1,limit=4,tick_per_page=1)
        def paged(method,path,body=None):
            if path.startswith('/control/terrain?'):
                transport.calls.append((method,path,body))
                return deepcopy(pages.pop(0))
            return original(method,path,body)
        transport.request=paged
        result=read_only_probe(transport,self.clock)
        self.assertEqual(result['terrain']['cells'],27)
        paths=[p for m,p,_ in transport.calls if p.startswith('/control/terrain?')]
        self.assertEqual(len(paths),7)
        self.assertTrue(all(p.startswith('/control/terrain?cursor=') for p in paths[1:]))

    def test_probe_changed_session_rejected(self):
        count=0
        def hook(method,path,body,result):
            nonlocal count
            if path=='/control/status':
                count+=1
                if count==2:result['guarded_movement']['session']='00000000-0000-4000-8000-000000000999'
            return result
        self.transport.response_hook=hook
        with self.assertRaises(ProbeError):read_only_probe(self.transport,self.clock)
        self.assertFalse(self.transport.actions)

    def test_probe_future_state_rejected(self):
        def hook(method,path,body,result):
            if path=='/control/state?radius=4':result['world']['game_time']=1000
            return result
        self.transport.response_hook=hook
        with self.assertRaises(ProbeError):read_only_probe(self.transport,self.clock)

    def test_no_acceptance_never_reads_or_posts(self):
        with self.assertRaisesRegex(ProbeError,'explicit_acceptance_flags_required'):
            one_action_test(self.transport,self.clock,action='forward-sample',expected_session='a'*64)
        self.assertEqual(self.transport.calls,[])

    def test_missing_individual_acceptance_flag(self):
        for flag in ('accept_local_test','accept_installed_guard_build','accept_unpublished_survival'):
            self.setUp()
            with self.assertRaises(ProbeError):self.act(**{flag:False})
            self.assertFalse(self.transport.calls)

    def test_invalid_fingerprint_fails_before_any_call(self):
        with self.assertRaises(ProbeError):self.act(expected_session='bad')
        self.assertFalse(self.transport.calls)

    def test_wrong_fingerprint_no_action(self):
        with self.assertRaisesRegex(ProbeError,'session_fingerprint_mismatch'):self.act(expected_session='a'*64)
        self.assertFalse(self.transport.actions)

    def test_exactly_one_forward_sample(self):
        result=self.act()
        self.assertEqual(result['result'],'readback_verified')
        self.assertEqual(result['actions'],1)
        self.assertEqual(result['samples'],1)
        self.assertTrue(result['cleanup_verified'])
        self.assertTrue(self.transport.closed)
        self.assertFalse(result['live_navigation_accepted'])

    def test_exactly_one_turn(self):
        result=self.act(action='turn',turn_degrees=15)
        self.assertEqual(result['result'],'readback_verified')
        self.assertEqual(result['actions'],1)
        self.assertEqual(result['samples'],0)
        self.assertEqual(result['yaw_change_degrees'],15)
        self.assertTrue(self.transport.closed)

    def test_illegal_turn_degrees_no_actions(self):
        for changes in ({'action':'turn','turn_degrees':30},{'action':'turn','turn_degrees':0},
                        {'action':'forward-sample','turn_degrees':10},{'max_seconds':10}):
            self.setUp()
            with self.assertRaises(ProbeError):self.act(**changes)
            self.assertFalse(self.transport.calls)

    def test_ambiguous_post_no_retry_and_local_close(self):
        def hook(method,path,body,result):
            if method=='POST':raise RuntimeError('mock lost response')
            return result
        self.transport.response_hook=hook
        result=self.act()
        self.assertEqual(result['result'],'stopped')
        self.assertEqual(result['actions'],1)
        self.assertFalse(result['cleanup_verified'])
        self.assertFalse(result['further_actions_allowed'])
        self.assertEqual(len(self.transport.actions),1)
        self.assertTrue(self.transport.closed)

    def test_owned_or_incomplete_cleanup_metadata_is_not_success(self):
        raw=self.transport._status()
        raw['guarded_movement']['owner_request_id']='pending'
        self.assertFalse(cleanup_summary(raw)['guard_cleanup_quiescent'])
        del raw['guarded_movement']['owner_request_id']
        self.assertFalse(cleanup_summary(raw)['ownership_metadata_complete'])
        self.assertFalse(cleanup_summary(raw)['guard_cleanup_quiescent'])

    def test_live_adapter_missing_each_gate(self):
        identity=self.transport.identity
        for config,session,accepted in ((SampleConfig(enabled=True),self.transport.session,True),
                                       (SampleConfig(enabled=True,acceptance_verified=True),None,True),
                                       (SampleConfig(enabled=True,acceptance_verified=True),self.transport.session,False)):
            self.transport.config=SimpleNamespace(enabled=True,acceptance_verified=accepted)
            adapter=GuardedSampleAdapter(self.transport,self.clock,identity,config,expected_movement_session=session)
            with self.assertRaisesRegex(SampleError,'live_acceptance_required'):adapter.prepare()
        self.assertFalse(self.transport.calls)

    def test_pinned_movement_session_must_match_capabilities(self):
        self.arm()
        adapter=GuardedSampleAdapter(self.transport,self.clock,self.transport.identity,
            SampleConfig(enabled=True,acceptance_verified=True),
            expected_movement_session='00000000-0000-4000-8000-000000000999')
        with self.assertRaises(SampleError):adapter.prepare()
        self.assertFalse(self.transport.actions)

    def test_explicit_stop_prevents_future_requests(self):
        self.arm()
        adapter=GuardedSampleAdapter(self.transport,self.clock,self.transport.identity,
            SampleConfig(enabled=True,acceptance_verified=True),expected_movement_session=self.transport.session)
        adapter.prepare();adapter.stop()
        calls=len(self.transport.calls)
        with self.assertRaises(SampleError):adapter.prepare()
        self.assertEqual(len(self.transport.calls),calls)
        self.assertTrue(self.transport.closed)

    def test_cli_missing_approval_stops_before_secret_prompt(self):
        with patch('navigation_controller.live_probe.getpass.getpass') as secret,patch('sys.stdout',new_callable=io.StringIO):
            self.assertEqual(main(['--url','http://127.0.0.1:1234','--action','forward-sample']),1)
            secret.assert_not_called()

    def test_cli_noninteractive_prompt_forbidden(self):
        with patch('sys.stdin.isatty',return_value=False),patch('navigation_controller.live_probe.getpass.getpass') as secret,patch('sys.stdout',new_callable=io.StringIO):
            self.assertEqual(main(['--url','http://127.0.0.1:1234']),1)
            secret.assert_not_called()

    def test_cli_unknown_arguments_do_not_echo_secret(self):
        with patch('sys.stdout',new_callable=io.StringIO) as output:
            self.assertEqual(main(['--url','http://127.0.0.1:1234','--token','NOT-TO-LOG']),1)
            self.assertNotIn('NOT-TO-LOG',output.getvalue())

    def test_invalid_start_delay_rejected_before_prompt_or_transport(self):
        for delay in ('-0.01','15.01','nan','inf','-inf'):
            with self.subTest(delay=delay),\
                 patch('navigation_controller.live_probe.getpass.getpass') as secret,\
                 patch('navigation_controller.http_transport.LoopbackHttpTransport') as client,\
                 patch('navigation_controller.live_probe.time.sleep') as sleep,\
                 patch('sys.stdout',new_callable=io.StringIO):
                self.assertEqual(main(['--url','http://127.0.0.1:1234','--start-delay='+delay]),1)
                secret.assert_not_called();client.assert_not_called();sleep.assert_not_called()

    def test_start_delay_occurs_after_hidden_prompt_before_any_reads(self):
        order=[]
        def prompt(*args,**kwargs):
            order.append('prompt');return 'FAKE-ONLY'
        def sleep(seconds):
            self.assertEqual(seconds,5)
            self.assertEqual(order,['prompt'])
            self.assertFalse(self.transport.calls)
            order.append('delay')
        with patch('sys.stdin.isatty',return_value=True),\
             patch('navigation_controller.live_probe.getpass.getpass',side_effect=prompt),\
             patch('navigation_controller.http_transport.LoopbackHttpTransport',return_value=self.transport),\
             patch('navigation_controller.live_probe.RealClock',return_value=self.clock),\
             patch('navigation_controller.live_probe.time.sleep',side_effect=sleep),\
             patch('sys.stdout',new_callable=io.StringIO) as output,\
             patch('sys.stderr',new_callable=io.StringIO) as notice:
            self.assertEqual(main(['--url','http://127.0.0.1:1234','--start-delay','5']),0)
            result=json.loads(output.getvalue())
            self.assertEqual(result['result'],'read_only_observations_verified')
            self.assertFalse(result['input_sent'])
            self.assertTrue(all(m=='GET' for m,p,b in self.transport.calls))
            self.assertEqual(order,['prompt','delay'])
            self.assertIn('return focus to Minecraft yourself',notice.getvalue())
            self.assertNotIn('FAKE-ONLY',output.getvalue()+notice.getvalue())

    def test_default_or_zero_start_delay_does_not_sleep(self):
        for arguments in ([],['--start-delay','0']):
            self.setUp()
            with patch('sys.stdin.isatty',return_value=True),\
                 patch('navigation_controller.live_probe.getpass.getpass',return_value='FAKE-ONLY'),\
                 patch('navigation_controller.http_transport.LoopbackHttpTransport',return_value=self.transport),\
                 patch('navigation_controller.live_probe.RealClock',return_value=self.clock),\
                 patch('navigation_controller.live_probe.time.sleep') as sleep,\
                 patch('sys.stdout',new_callable=io.StringIO):
                self.assertEqual(main(['--url','http://127.0.0.1:1234',*arguments]),0)
                sleep.assert_not_called()

    def test_interrupted_start_delay_makes_no_requests(self):
        with patch('sys.stdin.isatty',return_value=True),\
             patch('navigation_controller.live_probe.getpass.getpass',return_value='FAKE-ONLY'),\
             patch('navigation_controller.http_transport.LoopbackHttpTransport',return_value=self.transport),\
             patch('navigation_controller.live_probe.time.sleep',side_effect=KeyboardInterrupt),\
             patch('sys.stdout',new_callable=io.StringIO) as output,\
             patch('sys.stderr',new_callable=io.StringIO):
            self.assertEqual(main(['--url','http://127.0.0.1:1234','--start-delay','5']),130)
            self.assertEqual(json.loads(output.getvalue())['result'],'interrupted')
            self.assertFalse(self.transport.calls)
            self.assertTrue(self.transport.closed)

    def test_maximum_start_delay_precedes_unchanged_one_action_budget(self):
        expected=self.arm()
        def sleep(seconds):
            self.assertEqual(seconds,15)
            self.assertFalse(self.transport.calls)
            self.clock.sleep(seconds)
        args=['--url','http://127.0.0.1:1234','--start-delay','15',
              '--action','turn','--turn-degrees','15','--expected-session',expected,
              '--accept-local-test','--accept-installed-guard-build','--accept-unpublished-survival']
        with patch('sys.stdin.isatty',return_value=True),\
             patch('navigation_controller.live_probe.getpass.getpass',return_value='FAKE-ONLY'),\
             patch('navigation_controller.http_transport.LoopbackHttpTransport',return_value=self.transport),\
             patch('navigation_controller.live_probe.RealClock',return_value=self.clock),\
             patch('navigation_controller.live_probe.time.sleep',side_effect=sleep),\
             patch('sys.stdout',new_callable=io.StringIO) as output,\
             patch('sys.stderr',new_callable=io.StringIO):
            self.assertEqual(main(args),0)
            result=json.loads(output.getvalue())
            self.assertEqual(result['result'],'readback_verified')
            self.assertEqual(result['actions'],1)
            self.assertEqual(result['samples'],0)
            self.assertLess(result['elapsed_seconds'],2)
            self.assertEqual(len(self.transport.actions),1)

    def test_start_delay_does_not_relax_acceptance_flags(self):
        with patch('navigation_controller.live_probe.getpass.getpass') as secret,\
             patch('navigation_controller.live_probe.time.sleep') as sleep,\
             patch('sys.stdout',new_callable=io.StringIO):
            self.assertEqual(main(['--url','http://127.0.0.1:1234','--start-delay','5',
                                  '--action','forward-sample']),1)
            secret.assert_not_called();sleep.assert_not_called()

    def test_configuration_failure_saved_without_secret_or_requests(self):
        from pathlib import Path
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory)/'failure.json'
            with patch('sys.stdin.isatty',return_value=True),\
                 patch('navigation_controller.live_probe.getpass.getpass',return_value='FAKE SECRET WITH SPACE'),\
                 patch('navigation_controller.http_transport.LoopbackHttpTransport') as client,\
                 patch('sys.stdout',new_callable=io.StringIO) as output:
                self.assertEqual(main(['--url','http://127.0.0.1:1234','--report',str(target)]),1)
                result=json.loads(target.read_text())
                self.assertEqual(result['code'],'invalid_caller_token')
                self.assertEqual(result['stage'],'configure_transport')
                self.assertFalse(result['input_sent'])
                self.assertEqual(json.loads(output.getvalue()),result)
                self.assertNotIn('FAKE SECRET',target.read_text()+output.getvalue())
                client.assert_not_called()

    def test_http_failure_has_only_fixed_code_stage_and_status(self):
        from navigation_controller.http_transport import TransportError
        from pathlib import Path
        import tempfile
        error=TransportError('unexpected_http_status');error.http_status=401
        self.transport.request=lambda *a,**kw: (_ for _ in ()).throw(error)
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory)/'failure.json'
            with patch('sys.stdin.isatty',return_value=True),\
                 patch('navigation_controller.live_probe.getpass.getpass',return_value='FAKE-ONLY'),\
                 patch('navigation_controller.http_transport.LoopbackHttpTransport',return_value=self.transport),\
                 patch('sys.stdout',new_callable=io.StringIO) as output:
                self.assertEqual(main(['--url','http://127.0.0.1:1234','--report',str(target)]),1)
                result=json.loads(target.read_text())
                self.assertEqual(result['code'],'unexpected_http_status')
                self.assertEqual(result['http_status'],401)
                self.assertEqual(result['stage'],'capabilities')
                self.assertFalse(result['input_sent'])
                self.assertNotIn('FAKE-ONLY',target.read_text()+output.getvalue())
                self.assertTrue(self.transport.closed)

    def test_missing_field_name_is_never_exposed(self):
        self.transport.request=lambda *a,**kw: (_ for _ in ()).throw(KeyError('PRIVATE-KEY-OR-TOKEN'))
        with patch('sys.stdin.isatty',return_value=True),\
             patch('navigation_controller.live_probe.getpass.getpass',return_value='FAKE-ONLY'),\
             patch('navigation_controller.http_transport.LoopbackHttpTransport',return_value=self.transport),\
             patch('sys.stdout',new_callable=io.StringIO) as output:
            self.assertEqual(main(['--url','http://127.0.0.1:1234']),1)
            result=json.loads(output.getvalue())
            self.assertEqual(result['code'],'missing_response_field')
            self.assertEqual(result['stage'],'capabilities')
            self.assertNotIn('PRIVATE-KEY',output.getvalue())

    def test_unrecognized_error_payloads_remain_private(self):
        from navigation_controller.http_transport import TransportError
        from navigation_controller.terrain import TerrainError
        for error in (ProbeError('PRIVATE-TOKEN'),TransportError('PRIVATE-TOKEN'),
                      TerrainError('PRIVATE-TOKEN'),RuntimeError('PRIVATE-TOKEN')):
            result=safe_failure(error,{'stage':'capabilities'})
            self.assertNotIn('PRIVATE-TOKEN',json.dumps(result))
            self.assertFalse(result['input_sent'])

    def test_status_diagnostic_excludes_bool_strings_and_out_of_range(self):
        from navigation_controller.http_transport import TransportError
        for status in (True,'401',99,600,None):
            error=TransportError('unexpected_http_status');error.http_status=status
            self.assertNotIn('http_status',safe_failure(error,{'stage':'capabilities'}))

    def test_action_failure_does_not_claim_no_input_or_safe_retry(self):
        result=safe_failure(RuntimeError('PRIVATE'),{'stage':'one_action_acceptance'},action=True)
        self.assertNotIn('input_sent',result)
        self.assertFalse(result['cleanup_verified'])
        self.assertFalse(result['further_actions_allowed'])
        self.assertFalse(result['input_retried'])

    def test_interruption_is_saved_to_reserved_report(self):
        from pathlib import Path
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory)/'interrupted.json'
            with patch('sys.stdin.isatty',return_value=True),\
                 patch('navigation_controller.live_probe.getpass.getpass',side_effect=KeyboardInterrupt),\
                 patch('sys.stdout',new_callable=io.StringIO):
                self.assertEqual(main(['--url','http://127.0.0.1:1234','--report',str(target)]),130)
                result=json.loads(target.read_text())
                self.assertEqual(result['result'],'interrupted')
                self.assertEqual(result['stage'],'hidden_token_prompt')
                self.assertFalse(result['input_sent'])

    def test_closed_stdout_does_not_append_second_report(self):
        from pathlib import Path
        from unittest.mock import MagicMock
        import tempfile
        broken=MagicMock();broken.write.side_effect=BrokenPipeError('PRIVATE')
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory)/'closed-stdout.json'
            with patch('sys.stdin.isatty',return_value=True),\
                 patch('navigation_controller.live_probe.getpass.getpass',return_value='FAKE-ONLY'),\
                 patch('navigation_controller.http_transport.LoopbackHttpTransport',return_value=self.transport),\
                 patch('navigation_controller.live_probe.RealClock',return_value=self.clock),\
                 patch('sys.stdout',broken):
                self.assertEqual(main(['--url','http://127.0.0.1:1234','--report',str(target)]),1)
                result=json.loads(target.read_text())
                self.assertEqual(result['result'],'read_only_observations_verified')
                self.assertNotIn('PRIVATE',target.read_text())

    def test_ctrl_c_after_saved_action_keeps_one_json_and_action_count(self):
        from pathlib import Path
        from unittest.mock import MagicMock
        import tempfile
        expected=self.arm()
        interrupted=MagicMock();interrupted.write.side_effect=KeyboardInterrupt
        args=['--url','http://127.0.0.1:1234','--action','turn','--turn-degrees','15',
              '--expected-session',expected,'--accept-local-test',
              '--accept-installed-guard-build','--accept-unpublished-survival']
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory)/'saved-action.json'
            with patch('sys.stdin.isatty',return_value=True),\
                 patch('navigation_controller.live_probe.getpass.getpass',return_value='FAKE-ONLY'),\
                 patch('navigation_controller.http_transport.LoopbackHttpTransport',return_value=self.transport),\
                 patch('navigation_controller.live_probe.RealClock',return_value=self.clock),\
                 patch('sys.stdout',interrupted):
                self.assertEqual(main([*args,'--report',str(target)]),130)
                result=json.loads(target.read_text())
                self.assertEqual(result['result'],'readback_verified')
                self.assertEqual(result['actions'],1)
                self.assertEqual(result['samples'],0)
                self.assertTrue(result['cleanup_verified'])
                self.assertNotIn('input_sent',result)
                self.assertEqual(len(self.transport.actions),1)
                self.assertTrue(self.transport.closed)
                interrupted.write.assert_called_once()

    def test_ctrl_c_during_report_write_is_not_followed_by_second_append(self):
        from unittest.mock import MagicMock
        handle=MagicMock();handle.write.side_effect=KeyboardInterrupt
        with patch('pathlib.Path.open',return_value=handle),\
             patch('sys.stdin.isatty',return_value=True),\
             patch('navigation_controller.live_probe.getpass.getpass',return_value='FAKE-ONLY'),\
             patch('navigation_controller.http_transport.LoopbackHttpTransport',return_value=self.transport),\
             patch('navigation_controller.live_probe.RealClock',return_value=self.clock),\
             patch('sys.stdout',new_callable=io.StringIO) as output:
            self.assertEqual(main(['--url','http://127.0.0.1:1234','--report','mocked-only.json']),130)
            result=json.loads(output.getvalue())
            self.assertEqual(result['result'],'read_only_observations_verified')
            self.assertFalse(result['report_saved'])
            self.assertEqual(result['report_error'],'report_write_failed')
            handle.write.assert_called_once()
            self.assertTrue(self.transport.closed)

    def test_action_observation_accepts_fast_two_page_scan(self):
        self.arm()
        original=self.transport.request
        pages=self.transport.world.pages(radius=1,vertical=1,limit=14,tick_per_page=1)
        def paged(method,path,body=None):
            if path.startswith('/control/terrain?'):
                self.transport.calls.append((method,path,body))
                return deepcopy(pages.pop(0))
            return original(method,path,body)
        self.transport.request=paged
        adapter=GuardedSampleAdapter(self.transport,self.clock,self.transport.identity,
            SampleConfig(enabled=True,acceptance_verified=True),expected_movement_session=self.transport.session)
        adapter.prepare()
        context=adapter.observe()
        self.assertEqual(len(context.observation.terrain.cells),27)
        self.assertEqual(len([p for m,p,_ in self.transport.calls if 'terrain' in p]),2)
        self.assertFalse(self.transport.actions)

    def test_action_observation_slow_paging_still_failclosed(self):
        self.arm()
        original=self.transport.request
        pages=self.transport.world.pages(radius=1,vertical=1,limit=4,tick_per_page=1)
        def paged(method,path,body=None):
            if path.startswith('/control/terrain?'):
                self.transport.calls.append((method,path,body))
                return deepcopy(pages.pop(0))
            return original(method,path,body)
        self.transport.request=paged
        adapter=GuardedSampleAdapter(self.transport,self.clock,self.transport.identity,
            SampleConfig(enabled=True,acceptance_verified=True),expected_movement_session=self.transport.session)
        adapter.prepare()
        with self.assertRaises(SampleError):adapter.observe()
        self.assertTrue(adapter._faulted)
        self.assertFalse(self.transport.actions)

    def test_getpass_warning_is_fatal_before_echo_fallback_or_transport(self):
        import getpass
        import warnings
        def unsafe_prompt(*args,**kwargs):
            warnings.warn('would echo token',getpass.GetPassWarning)
            raise AssertionError('fallback must never be reached')
        with patch('sys.stdin.isatty',return_value=True),\
             patch('navigation_controller.live_probe.getpass.getpass',side_effect=unsafe_prompt),\
             patch('navigation_controller.http_transport.LoopbackHttpTransport') as client,\
             patch('sys.stdout',new_callable=io.StringIO) as output:
            self.assertEqual(main(['--url','http://127.0.0.1:1234']),1)
            client.assert_not_called()
            self.assertIn('secure_token_prompt_unavailable',output.getvalue())
            self.assertNotIn('would echo token',output.getvalue())

    def test_contradictory_cleanup_readback_clears_ack_claim(self):
        def hook(method,path,body,result):
            if path=='/control/status' and self.transport.actions:
                result['guarded_movement']['released']=False
                result['guarded_movement']['owner_request_id']='00000000-0000-4000-8000-000000000999'
            return result
        self.transport.response_hook=hook
        report=self.act(action='turn',turn_degrees=10)
        self.assertEqual(report['result'],'stopped')
        self.assertEqual(report['actions'],1)
        self.assertFalse(report['cleanup_verified'])
        self.assertTrue(self.transport.closed)

    def test_existing_report_refused_before_prompt_or_any_action(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory)/'existing.json';target.write_text('keep')
            with patch('navigation_controller.live_probe.getpass.getpass') as secret,patch('sys.stdout',new_callable=io.StringIO) as output:
                code=main(['--url','http://127.0.0.1:1234','--report',str(target)])
                self.assertEqual(code,1)
                secret.assert_not_called()
                self.assertIn('report_destination_unavailable',output.getvalue())
                self.assertEqual(target.read_text(),'keep')

    def test_report_write_failure_preserves_successful_action_result(self):
        from unittest.mock import MagicMock
        handle=MagicMock();handle.write.side_effect=OSError('disk full')
        expected=self.arm()
        args=['--url','http://127.0.0.1:1234','--action','turn','--turn-degrees','15',
              '--expected-session',expected,'--accept-local-test','--accept-installed-guard-build',
              '--accept-unpublished-survival','--report','unused-mocked-path.json']
        with patch('pathlib.Path.open',return_value=handle),patch('sys.stdin.isatty',return_value=True),\
             patch('navigation_controller.live_probe.getpass.getpass',return_value='FAKE-ONLY'),\
             patch('navigation_controller.http_transport.LoopbackHttpTransport',return_value=self.transport),\
             patch('navigation_controller.live_probe.RealClock',return_value=self.clock),\
             patch('sys.stdout',new_callable=io.StringIO) as output:
            self.assertEqual(main(args),1)
            result=json.loads(output.getvalue())
            self.assertEqual(result['result'],'readback_verified')
            self.assertEqual(result['actions'],1)
            self.assertTrue(result['cleanup_verified'])
            self.assertFalse(result['report_saved'])
            self.assertNotIn('disk full',output.getvalue())
            self.assertNotIn('FAKE-ONLY',output.getvalue())
            self.assertEqual(len(self.transport.actions),1)

    def test_live_route_runner_remains_forbidden_even_with_acceptance_flags(self):
        from navigation_controller.planner import plan
        from navigation_controller.sample_adapter import SampleNavigator
        from navigation_controller.terrain import Block
        self.arm()
        adapter=GuardedSampleAdapter(self.transport,self.clock,self.transport.identity,
            SampleConfig(enabled=True,acceptance_verified=True,max_actions=1,max_samples=1,max_seconds=2),
            expected_movement_session=self.transport.session)
        world=WorldStamp(self.transport.world.generation,'minecraft:overworld',100)
        route=plan(self.transport.world.grid(),Block(0,64,0),Block(1,64,0),world,100).route
        result=SampleNavigator(adapter).run(route)
        self.assertEqual(result.reason,'live_route_following_not_accepted')
        self.assertFalse(self.transport.calls)

    def test_live_adapter_rejects_multi_action_configuration_before_post(self):
        self.arm()
        adapter=GuardedSampleAdapter(self.transport,self.clock,self.transport.identity,
            SampleConfig(enabled=True,acceptance_verified=True),expected_movement_session=self.transport.session)
        adapter.prepare();context=adapter.observe()
        with self.assertRaisesRegex(SampleError,'live_single_action_scope_required'):
            adapter.turn(context,15,102)
        self.assertFalse(self.transport.actions)
        self.assertTrue(all(m=='GET' for m,p,b in self.transport.calls))
