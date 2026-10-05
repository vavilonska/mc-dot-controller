from copy import deepcopy
from dataclasses import replace
import unittest
from navigation_controller.fake import FakeClock, FakeWorld
from navigation_controller.observation import Position
from navigation_controller.planner import plan
from navigation_controller.sample_adapter import GuardedSampleAdapter, SampleConfig, SampleError, SampleNavigator, swept_corridor
from navigation_controller.sample_fake import FakeSampleTransport
from navigation_controller.terrain import Block, TerrainError, WorldStamp


class SampleAdapterTests(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.transport = FakeSampleTransport(self.clock)
        self.adapter = GuardedSampleAdapter(self.transport, self.clock, self.transport.identity, SampleConfig(enabled=True))

    def observe(self):
        self.adapter.prepare()
        return self.adapter.observe()

    def route(self, target=Block(1,64,0)):
        grid = self.transport.world.grid()
        return plan(grid, Block(0,64,0), target,
                    WorldStamp(self.transport.world.generation,'minecraft:overworld',100),100).route

    def hook(self, path, mutate):
        self.transport.response_hook = lambda method,p,body,result: mutate(result) if path == p else result

    def test_defaults_disabled_without_any_transport_calls(self):
        adapter = GuardedSampleAdapter(self.transport,self.clock,self.transport.identity)
        self.assertEqual(SampleNavigator(adapter).run(self.route()).reason,'sample_adapter_disabled')
        self.assertEqual(self.transport.calls,[])

    def test_no_live_transport_route(self):
        self.transport.simulation_only=False
        with self.assertRaisesRegex(SampleError,'live_acceptance_required'):
            self.adapter.prepare()
        self.assertEqual(self.transport.calls,[])

    def test_prepare_and_actual_shape_observation(self):
        context=self.observe()
        self.assertEqual(context.observation.identity,self.transport.identity)
        self.assertEqual(context.observation.horizontal_speed,0)
        self.assertTrue(swept_corridor(context))

    def test_status_does_not_invalidate_state_challenge(self):
        context=self.observe()
        state=self.transport._observation[0]
        self.assertEqual(context.observation_id,state['guarded_movement']['observation_id'])
        self.assertEqual(self.transport.calls[-1][1],'/control/status')

    def test_forward_one_sample_then_observed_settling(self):
        context=self.observe()
        fresh=self.adapter.forward_sample(context,110)
        self.assertAlmostEqual(fresh.observation.position.z-.5,.103)
        self.assertLessEqual(fresh.observation.horizontal_speed,.001)
        self.assertEqual(self.adapter.samples,1)
        self.assertEqual(len(self.transport.actions),1)
        self.assertTrue(self.adapter.cleanup_verified)
        self.assertGreaterEqual(self.clock.now,100.19)
        self.assertNotEqual(context.observation_id,fresh.observation_id)

    def test_request_is_one_sample_not_duration_travel(self):
        context=self.observe()
        self.adapter.forward_sample(context,110)
        body=self.transport.actions[0]
        self.assertEqual(body['action'],'forward_sample')
        self.assertEqual(body['duration_ms'],100)
        self.assertEqual(body['ttl_ms'],100)
        self.assertNotIn('speed',body)
        self.assertNotIn('key',body)
        self.assertNotAlmostEqual(self.transport.position.z-.5,.4)

    def test_bounded_turn_then_fresh_readback(self):
        context=self.observe()
        fresh=self.adapter.turn(context,-30,110)
        self.assertEqual(fresh.canonical_yaw,-30)
        self.assertEqual(self.adapter.actions,1)
        self.assertEqual(self.adapter.samples,0)
        self.assertNotEqual(context.observation_id,fresh.observation_id)

    def test_turn_maximum_and_no_duration_field(self):
        context=self.observe()
        with self.assertRaisesRegex(SampleError,'turn_step_out_of_bounds'):
            self.adapter.turn(context,31,110)
        self.assertFalse(self.transport.actions)
        self.adapter.turn(context,30,110)
        self.assertNotIn('duration_ms',self.transport.actions[0])

    def test_full_route_turns_and_samples(self):
        result=SampleNavigator(self.adapter).run(self.route())
        self.assertEqual(result.reason,'arrived')
        self.assertTrue(result.cleanup_verified)
        self.assertEqual(result.samples,9)
        self.assertGreaterEqual(result.actions,12)
        self.assertLessEqual(result.actions,16)
        self.assertTrue(all(a['duration_ms']==100 for a in self.transport.actions if a['action']=='forward_sample'))
        self.assertTrue(all(p in self.adapter.WRITE_PATHS for m,p,_ in self.transport.calls if m=='POST'))

    def test_no_legacy_release_or_input_calls(self):
        SampleNavigator(self.adapter).run(self.route())
        prohibited={'/control/key','/control/raw-key','/control/look','/control/release-all','/control/command'}
        self.assertFalse(any(p in prohibited for _,p,_ in self.transport.calls))

    def test_missing_turn_capability_failclosed(self):
        self.hook('/control/capabilities',lambda r: dict(r,guarded_turn={}))
        with self.assertRaises(SampleError):self.adapter.prepare()
        self.assertFalse(self.transport.actions)

    def test_movement_capability_mutations_failclosed(self):
        for key,value in {'enabled':False,'max_input_samples':2,'forward_impulse':1.0,'held_keys':True,
                          'turn_supported':False,'max_duration_ms':101,'schema_version':True,
                          'owner_request_id':'busy','released':False,'admission_open':False}.items():
            with self.subTest(key=key):
                self.setUp()
                def mutate(r):r['guarded_movement'][key]=value;return r
                self.hook('/control/capabilities',mutate)
                with self.assertRaises(SampleError):self.adapter.prepare()
                self.assertFalse(self.transport.actions)

    def test_world_generation_change_rejected(self):
        self.observe()
        self.transport.world.generation='00000000-0000-4000-8000-000000000999'
        with self.assertRaises(TerrainError):self.adapter.observe()

    def test_session_restart_rejected(self):
        self.observe()
        self.transport.session='00000000-0000-4000-8000-000000000999'
        with self.assertRaises(TerrainError):self.adapter.observe()

    def test_foreign_context_rejected(self):
        context=self.observe()
        with self.assertRaisesRegex(SampleError,'consumed_or_unrecognized_observation'):
            self.adapter.forward_sample(replace(context),110)
        self.assertFalse(self.transport.actions)

    def test_context_single_use(self):
        context=self.observe()
        self.adapter.forward_sample(context,110)
        with self.assertRaisesRegex(SampleError,'consumed_or_unrecognized_observation'):
            self.adapter.forward_sample(context,110)
        self.assertEqual(len(self.transport.actions),1)

    def test_new_observation_supersedes_previous(self):
        context=self.observe()
        self.adapter.observe()
        with self.assertRaises(SampleError):self.adapter.forward_sample(context,110)
        self.assertFalse(self.transport.actions)

    def test_local_observation_age_blocks_post(self):
        context=self.observe();self.clock.sleep(.11)
        with self.assertRaisesRegex(SampleError,'action_context_stale'):
            self.adapter.forward_sample(context,110)
        self.assertFalse(self.transport.actions)

    def test_remaining_deadline_blocks_post(self):
        context=self.observe()
        with self.assertRaisesRegex(SampleError,'action_deadline_exhausted'):
            self.adapter.forward_sample(context,100.05)
        self.assertFalse(self.transport.actions)

    def test_duplicate_nonce_not_retried(self):
        self.adapter.nonce_factory=lambda:'00000000-0000-4000-8000-000000000777'
        context=self.observe()
        context=self.adapter.turn(context,30,110)
        with self.assertRaisesRegex(SampleError,'request_id_reused'):self.adapter.turn(context,60,110)
        self.assertEqual(len(self.transport.actions),1)

    def test_unknown_terrain_blocks_movement(self):
        self.transport.world.unknown(Block(0,63,1))
        context=self.observe()
        with self.assertRaisesRegex(SampleError,'forward_corridor_unsafe'):self.adapter.forward_sample(context,110)
        self.assertFalse(self.transport.actions)

    def test_wider_planner_floor_not_assumed_movement_supported(self):
        self.transport.world.set(Block(0,63,1),'bricks')
        context=self.observe()
        self.assertTrue(context.observation.terrain.standable(Block(0,64,1)))
        with self.assertRaisesRegex(SampleError,'forward_corridor_unsafe'):self.adapter.forward_sample(context,110)

    def test_truncated_terrain_blocks(self):
        self.hook('/control/terrain?radius=1&vertical=1&limit=128',lambda r:dict(r,complete=False,next_cursor=r['generation']+':27'))
        with self.assertRaises(SampleError):self.observe()

    def test_stale_terrain_blocks(self):
        def mutate(r):r['game_time']=90;r['response_game_time']=90;return r
        self.hook('/control/terrain?radius=1&vertical=1&limit=128',mutate)
        with self.assertRaises(SampleError):self.observe()

    def test_empty_radius_capture_not_weakened(self):
        def mutate(r):r['nearby']['radius']=0;return r
        self.hook('/control/state?radius=4',mutate)
        with self.assertRaises(SampleError):self.observe()

    def test_entity_or_truncated_observation_blocks(self):
        for nearby in ({'radius':4,'total':1,'returned':1,'truncated':False,'entities':[{'type':'minecraft:cow'}]},
                       {'radius':4,'total':0,'returned':0,'truncated':True,'entities':[]}):
            self.setUp()
            self.hook('/control/state?radius=4',lambda r:dict(r,nearby=nearby))
            with self.assertRaises(SampleError):self.observe()
            self.assertFalse(self.transport.actions)

    def test_full_health_required(self):
        self.transport.health=19
        with self.assertRaises(SampleError):self.observe()

    def test_active_effects_required_empty(self):
        self.transport.state_changes=dict(effects=[{'id':'minecraft:speed'}],effects_total=1,effects_returned=1)
        with self.assertRaises(SampleError):self.observe()

    def test_near_rest_stricter_than_old_fake_controller(self):
        self.transport.velocity=Position(.002,-.0784,0)
        with self.assertRaises(SampleError):self.observe()

    def test_status_after_state_pose_change_rejected(self):
        count=0
        def mutate(r):
            nonlocal count
            count+=1
            if count==2:r['player']['x']+=.2
            return r
        self.hook('/control/status',mutate)
        with self.assertRaises(SampleError):self.observe()

    def test_slow_post_state_bracket_rejected(self):
        def mutate(r):self.clock.sleep(.11);return r
        self.hook('/control/state?radius=4',mutate)
        with self.assertRaises(SampleError):self.observe()

    def test_canonical_yaw_from_guard_observation(self):
        self.transport.yaw=720
        context=self.observe()
        self.assertEqual(context.canonical_yaw,0)
        self.adapter.forward_sample(context,110)
        self.assertEqual(self.transport.actions[0]['expected_yaw'],0)

    def test_nonfinite_guard_yaw_rejected(self):
        def mutate(r):r['guarded_movement']['observation_yaw']=float('nan');return r
        self.hook('/control/state?radius=4',mutate)
        with self.assertRaises(SampleError):self.observe()

    def test_ambiguous_post_fault_latched_no_retry(self):
        context=self.observe()
        def fail(r):raise RuntimeError('fake lost reply')
        self.hook('/control/guarded-movement',fail)
        with self.assertRaisesRegex(SampleError,'ambiguous_action_response'):self.adapter.forward_sample(context,110)
        self.assertFalse(self.adapter.cleanup_verified)
        count=len(self.transport.calls)
        with self.assertRaises(SampleError):self.adapter.prepare()
        self.assertEqual(len(self.transport.calls),count)
        self.assertEqual(len(self.transport.actions),1)

    def test_mismatched_or_unreleased_response_faults(self):
        for changes in ({'released':False},{'sampled':False},{'movement_confirmed':True},{'request_id':'wrong'}):
            self.setUp();context=self.observe()
            self.hook('/control/guarded-movement',lambda r:dict(r,**changes))
            with self.assertRaisesRegex(SampleError,'action_result_mismatch'):self.adapter.forward_sample(context,110)
            self.assertFalse(self.adapter.cleanup_verified)
            self.assertTrue(self.adapter._faulted)

    def test_damage_during_settling_stops(self):
        context=self.observe()
        def hurt(r):self.transport.health=19;return r
        self.hook('/control/guarded-movement',hurt)
        with self.assertRaises(SampleError):self.adapter.forward_sample(context,110)
        self.assertEqual(len(self.transport.actions),1)

    def test_excess_settling_displacement_stops(self):
        context=self.observe()
        def shift(r):self.transport.position=Position(1.5,64,.5);return r
        self.hook('/control/guarded-movement',shift)
        with self.assertRaisesRegex(SampleError,'unexpected_settling_displacement'):self.adapter.forward_sample(context,110)

    def test_never_settles_finite_read_budget(self):
        self.adapter.config=replace(self.adapter.config,settle_reads=3)
        context=self.observe()
        def moving(r):self.transport.never_settles=True;return r
        self.hook('/control/guarded-movement',moving)
        with self.assertRaisesRegex(SampleError,'settling_read_budget_exhausted'):self.adapter.forward_sample(context,110)
        self.assertEqual(len(self.transport.actions),1)

    def test_settling_time_budget(self):
        self.adapter.config=replace(self.adapter.config,settle_seconds=.1)
        context=self.observe()
        with self.assertRaisesRegex(SampleError,'settling_deadline_exhausted'):self.adapter.forward_sample(context,110)
        self.assertEqual(len(self.transport.actions),1)

    def test_two_distinct_rest_ticks_required(self):
        self.transport.stalled=True
        context=self.observe()
        started=self.clock.now
        self.adapter.forward_sample(context,110)
        self.assertGreaterEqual(self.clock.now-started,.099)

    def test_action_budget_stops_before_extra_turn(self):
        self.adapter.config=replace(self.adapter.config,max_actions=1)
        result=SampleNavigator(self.adapter).run(self.route())
        self.assertEqual(result.reason,'action_budget_exhausted')
        self.assertEqual(result.actions,1)
        self.assertEqual(result.samples,0)

    def test_sample_budget_stops(self):
        self.adapter.config=replace(self.adapter.config,max_samples=1)
        result=SampleNavigator(self.adapter).run(self.route())
        self.assertEqual(result.reason,'sample_budget_exhausted')
        self.assertEqual(result.samples,1)

    def test_stall_progress_stops(self):
        self.transport.stalled=True
        result=SampleNavigator(self.adapter).run(self.route())
        self.assertEqual(result.reason,'sample_progress_stalled')
        self.assertEqual(result.samples,3)

    def test_noncentered_capture_not_weakened(self):
        self.transport.position=Position(.5,64,.92689)
        result=SampleNavigator(self.adapter).run(self.route())
        self.assertEqual(result.reason,'left_route_corridor')
        self.assertFalse(self.transport.actions)

    def test_nonflat_route_deferred(self):
        self.transport.world.set(Block(1,63,0),'air')
        route=self.route(Block(1,63,0))
        result=SampleNavigator(self.adapter).run(route)
        self.assertEqual(result.reason,'flat_bounded_route_required')
        self.assertFalse(self.transport.actions)

    def test_config_budget_validation(self):
        for changes in ({'enabled':1},{'max_actions':0},{'max_samples':257},{'settle_reads':1},{'settle_seconds':10},{'max_seconds':100}):
            with self.assertRaises(ValueError):SampleConfig(**changes)

    def test_unsafe_turn_readback_latches_at_adapter_boundary(self):
        context=self.observe()
        def shift(r):self.transport.position=Position(.54,64,.5);return r
        self.hook('/control/guarded-turn',shift)
        with self.assertRaisesRegex(SampleError,'unsafe_action_readback'):self.adapter.turn(context,30,110)
        self.assertTrue(self.adapter._faulted)
        self.assertIsNone(self.adapter._latest)
        with self.assertRaises(SampleError):self.adapter.prepare()
        self.assertEqual(len(self.transport.actions),1)

    def test_unsafe_settle_readback_latches_at_adapter_boundary(self):
        context=self.observe()
        def hurt(r):self.transport.health=19;return r
        self.hook('/control/guarded-movement',hurt)
        with self.assertRaises(SampleError):self.adapter.forward_sample(context,110)
        self.assertTrue(self.adapter._faulted)
        self.assertIsNone(self.adapter._latest)

    def test_turn_readback_respects_total_deadline(self):
        context=self.observe()
        def slow(r):self.clock.sleep(.2);return r
        self.hook('/control/guarded-turn',slow)
        with self.assertRaisesRegex(SampleError,'turn_readback_deadline_exhausted'):self.adapter.turn(context,30,100.15)
        self.assertTrue(self.adapter._faulted)
        self.assertIsNone(self.adapter._latest)

    def test_expired_fake_challenge_consumes_nonce(self):
        context=self.observe()
        body=self.adapter._envelope(context,110)
        body.update(turn_schema_version=1,action='yaw',target_yaw=30)
        self.clock.sleep(.16)
        with self.assertRaises(ValueError):self.transport.request('POST','/control/guarded-turn',body)
        self.assertIn(body['request_id'],self.transport._used)
        self.assertIsNone(self.transport._observation)

    def test_fake_rejects_malformed_wire_types(self):
        for key,value in (('request_id','NOT-A-UUID'),('turn_schema_version',True),('expected_tick',True),('ttl_ms',True),('target_yaw',float('nan'))):
            self.setUp();context=self.observe()
            body=self.adapter._envelope(context,110)
            body.update(turn_schema_version=1,action='yaw',target_yaw=30)
            body[key]=value
            with self.assertRaises(ValueError):self.transport.request('POST','/control/guarded-turn',body)
            self.assertFalse(self.transport.actions)

    def test_float32_turn_target_sent_exactly(self):
        import struct
        context=self.observe()
        target=29.123456789
        result=self.adapter.turn(context,target,110)
        expected=struct.unpack('!f',struct.pack('!f',target))[0]
        self.assertEqual(self.transport.actions[0]['target_yaw'],expected)
        self.assertEqual(result.canonical_yaw,expected)

    def test_float32_rounding_wraps_positive_180(self):
        self.transport.yaw=179
        context=self.observe()
        result=self.adapter.turn(context,179.999999,110)
        self.assertEqual(self.transport.actions[0]['target_yaw'],-180)
        self.assertEqual(result.canonical_yaw,-180)

    def test_shared_observation_and_no_pitch_capabilities_required(self):
        for key,value in (('shared_movement_observation',False),('pitch_supported',True)):
            self.setUp()
            def mutate(r):r['guarded_turn'][key]=value;return r
            self.hook('/control/capabilities',mutate)
            with self.assertRaises(SampleError):self.adapter.prepare()

    def test_missing_nullable_ownership_fields_rejected(self):
        for missing in ('owner_request_id','owner_action'):
            self.setUp()
            def mutate(r):del r['guarded_movement'][missing];return r
            self.hook('/control/capabilities',mutate)
            with self.assertRaises(SampleError):self.adapter.prepare()
            self.assertFalse(self.transport.actions)

    def test_fractional_float32_initial_yaw_route(self):
        import struct
        self.transport.yaw=struct.unpack('!f',struct.pack('!f',45.3))[0]
        result=SampleNavigator(self.adapter).run(self.route())
        self.assertEqual(result.reason,'arrived')
        for action in self.transport.actions:
            if action['action']=='yaw':
                delta=(action['target_yaw']-action['expected_yaw']+180)%360-180
                self.assertLessEqual(abs(delta),30)

    def test_exact_thirty_rounded_over_bound_fails_before_post(self):
        import struct
        self.transport.yaw=struct.unpack('!f',struct.pack('!f',45.3))[0]
        context=self.observe()
        with self.assertRaisesRegex(SampleError,'rounded_turn_step_out_of_bounds'):
            self.adapter.turn(context,context.canonical_yaw+30,110)
        self.assertFalse(self.transport.actions)

    def test_standalone_unsafe_observe_cannot_resume_same_adapter(self):
        context=self.observe()
        context=self.adapter.turn(context,30,110)
        self.transport.health=19
        with self.assertRaises(SampleError):self.adapter.observe()
        self.assertTrue(self.adapter._faulted)
        self.assertIsNone(self.adapter._latest)
        self.transport.health=20
        calls=len(self.transport.calls)
        with self.assertRaises(SampleError):self.adapter.observe()
        self.assertEqual(len(self.transport.calls),calls)
        self.assertEqual(len(self.transport.actions),1)

    def test_session_change_during_post_readback_latches(self):
        context=self.observe()
        def changed(r):self.transport.session='00000000-0000-4000-8000-000000000999';return r
        self.hook('/control/guarded-movement',changed)
        with self.assertRaises(SampleError):self.adapter.forward_sample(context,110)
        self.assertTrue(self.adapter._faulted)
        self.assertIsNone(self.adapter._latest)
        self.assertEqual(len(self.transport.actions),1)
