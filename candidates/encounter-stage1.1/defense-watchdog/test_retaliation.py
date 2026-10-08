import copy
import tempfile
from pathlib import Path
import unittest
from watchdog import Watchdog, cancel_waiting_intents
from targeting import TargetPolicy
from resident_controller.native_combat import HOSTILES
from test_watchdog import Queue, observation, TARGET
OTHER='33333333-3333-4333-8333-333333333333'

def enemy(identity=TARGET,distance=2,kind='minecraft:zombie'):
    return {'uuid':identity,'type':kind,'alive':True,'health':20,'distance':distance}

class RetaliationChecks(unittest.TestCase):
    def setUp(self):
        self.now=0;self.q=Queue();self.d=Watchdog(self.q,clock=lambda:self.now)
    def tick(self,n=1,step=.1):
        for _ in range(n):self.d.tick();self.now+=step
    def ops(self,op):return [c for _,c in self.q.calls if c['op']==op]
    def set_entities(self,*entities):self.q.obs['state']['nearby']['entities']=list(entities)
    def inherit(self,phase='shielding'):
        self.q.obs['combat']={'active':True,'target_uuid':TARGET,'reason':'tracking_hostile','phase':phase,'attack_dispatches':0}
        self.tick(3)
    def test_health_drop_admits_visible_hostile_outside_default_six_blocks(self):
        self.set_entities(enemy(distance=7));self.tick(7)
        self.assertEqual(self.ops('combat_start'),[])
        self.q.obs['state']['player']['health']=18
        self.tick(10)
        self.assertEqual(self.ops('combat_start')[0]['target_uuid'],TARGET)
        event=self.d.status()['targeting']['last_health_drop']
        self.assertEqual(event['source'],'unknown');self.assertIsNone(event['attacker_uuid'])
    def test_repeated_damage_and_closer_enemy_keep_attackable_uuid(self):
        self.set_entities(enemy(distance=2.4),enemy(OTHER,1))
        self.inherit()
        for health in (19,18,17,16,15):
            self.q.obs['state']['player']['health']=health;self.tick(6)
        self.assertEqual(self.d.started_target,TARGET)
        self.assertEqual(self.ops('combat_start'),[]);self.assertEqual(self.ops('cancel'),[])
    def test_projectile_or_fall_damage_does_not_invent_attacker(self):
        self.tick(3);self.q.obs['state']['player']['health']=16;self.tick(10)
        self.assertEqual(self.ops('combat_start'),[])
        self.assertEqual(self.d.targeting.last_damage['source'],'unknown')
    def test_player_or_neutral_is_never_retaliation_target(self):
        self.tick(3)
        for kind in ('minecraft:player','minecraft:wolf','minecraft:piglin','minecraft:spider'):
            self.set_entities(enemy(kind=kind));self.q.obs['state']['player']['health']-=1;self.tick(8)
        self.assertEqual(self.ops('combat_start'),[])
    def test_unsupported_claimed_attacker_field_is_not_trusted(self):
        self.tick(3);self.q.obs['state']['damage_source']={'attacker_uuid':OTHER}
        self.set_entities(enemy(OTHER,1,'minecraft:player'))
        self.q.obs['state']['player']['health']=18;self.tick(8)
        self.assertEqual(self.ops('combat_start'),[])
    def test_persistent_unreachable_target_switches_only_after_grace(self):
        self.set_entities(enemy(distance=5.5),enemy(OTHER,2))
        self.inherit('waiting_in_range');self.tick(20)
        self.assertEqual(self.ops('combat_start'),[])
        self.assertEqual(self.d.started_target,TARGET)
        self.tick(23)
        self.assertEqual(len(self.ops('combat_start')),1)
        self.assertEqual(self.ops('combat_start')[0]['target_uuid'],OTHER)
    def test_damage_does_not_shorten_unreachable_grace(self):
        self.set_entities(enemy(distance=5.5),enemy(OTHER,2));self.inherit('waiting_in_range')
        self.q.obs['state']['player']['health']=15;self.tick(15)
        self.assertEqual(self.ops('cancel'),[]);self.assertEqual(self.d.started_target,TARGET)
    def test_attack_dispatch_progress_resets_unreachable_timer(self):
        self.set_entities(enemy(distance=5.5),enemy(OTHER,2));self.inherit('waiting_in_range')
        self.tick(20);self.q.obs['combat']['attack_dispatches']=1;self.tick(22)
        self.assertEqual(self.ops('combat_start'),[])
    def test_brief_target_loss_does_not_instantly_switch(self):
        self.set_entities(enemy(),enemy(OTHER,1));self.inherit()
        self.q.obs['combat']={'active':False,'reason':'combat_aim_released_target_missing'}
        self.set_entities(enemy(OTHER,1));self.tick(5)
        self.assertEqual(self.ops('combat_start'),[])
        self.assertEqual(self.d.phase,'retaining_target')
        self.tick(15)
        self.assertEqual(self.ops('combat_start')[0]['target_uuid'],OTHER)
    def test_brief_loss_reacquires_same_uuid_even_if_other_is_closer(self):
        self.set_entities(enemy(),enemy(OTHER,1));self.inherit();self.tick(10)
        self.q.obs['combat']={'active':False,'reason':'combat_aim_released_target_missing'}
        self.set_entities(enemy(distance=7),enemy(OTHER,1));self.tick(10)
        self.assertEqual(self.ops('combat_start')[0]['target_uuid'],TARGET)
    def test_target_death_permits_selecting_remaining_enemy(self):
        self.set_entities(enemy(),enemy(OTHER,1));self.inherit()
        self.q.obs['combat']={'active':False,'reason':'combat_aim_released_target_dead'}
        self.set_entities(enemy(OTHER,1));self.tick(10)
        self.assertEqual(self.ops('combat_start')[0]['target_uuid'],OTHER)
    def test_no_alternative_does_not_restart_same_blocked_target_forever(self):
        self.set_entities(enemy(distance=6));self.inherit('waiting_in_range');self.tick(100)
        self.assertEqual(self.ops('combat_start'),[]);self.assertEqual(len(self.ops('cancel')),1)
        self.assertEqual(self.d.phase,'watching');self.assertIsNone(self.d.started_target)
    def test_manual_takeover_still_requires_operator_not_retal_restart(self):
        self.set_entities(enemy());self.inherit()
        self.q.obs['combat']={'active':False,'reason':'explicit_direct'};self.tick(10)
        self.assertFalse(self.d.armed);self.assertEqual(self.ops('combat_start'),[])
    def test_stop_wins_during_target_loss_hysteresis(self):
        self.set_entities(enemy());self.inherit()
        self.q.obs['combat']={'active':False,'reason':'combat_aim_released_target_missing'}
        self.set_entities();self.tick(5);self.d.stop();self.tick(3)
        self.assertTrue(self.d.stopped);self.assertTrue(self.d.cancel_confirmed)
    def test_delay_recovery_rearms_after_confirmed_cancel_and_two_fresh_reads(self):
        self.tick(3);self.d.submit_owner('walk',{'op':'action'})
        self.q.hold_observe=True;self.tick(4);self.now+=3;self.tick(2)
        self.assertFalse(self.d.armed);self.assertTrue(self.d.recover_observation)
        self.q.hold_observe=False;self.tick(20)
        self.assertTrue(self.d.armed);self.assertEqual(len(self.ops('action')),1)
        self.assertEqual(self.d.completed[0]['result']['status'],'cancelled')
    def test_delay_recovery_does_not_cross_player_or_world_change(self):
        self.tick(3);self.q.hold_observe=True;self.tick(4);self.now+=3;self.tick(2)
        self.q.hold_observe=False;self.q.obs['state']['world']={'world_generation':'new-world','game_time':100};self.tick(15)
        self.assertFalse(self.d.armed);self.assertFalse(self.d.recover_observation)
    def test_interruption_cancels_waiting_intents_not_replays_them(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'inbox').mkdir();(root/'results').mkdir()
            (root/'inbox/queued.json').write_text('{"op":"action"}')
            self.d.attention('observation_delayed_cancel_requested')
            cancel_waiting_intents(root,self.d)
            self.assertFalse((root/'inbox/queued.json').exists())
            self.assertIn('replan_required',(root/'results/queued.json').read_text())
        self.assertEqual(self.ops('action'),[])

    def test_manual_hard_pause_is_not_erased_by_later_observation_delay(self):
        self.set_entities(enemy());self.inherit()
        self.q.obs['combat']={'active':False,'reason':'explicit_direct'};self.tick(8)
        self.assertFalse(self.d.armed)
        self.q.hold_observe=True;self.tick(6);self.now+=3;self.tick(2)
        self.q.hold_observe=False;self.tick(20)
        self.assertFalse(self.d.armed);self.assertFalse(self.d.recover_observation)
        self.assertEqual(self.ops('combat_start'),[]);self.assertEqual(self.ops('cancel'),[])
    def test_owner_uncertainty_is_not_auto_recovered_after_sensor_delay(self):
        self.tick(3);self.d.submit_owner('walk',{'op':'action'})
        self.q.results[self.d.owner['request_id']]={'status':'uncertain','reason':'transport_failed'}
        self.tick(3);count=len(self.ops('cancel'))
        self.q.hold_observe=True;self.tick(6);self.now+=3;self.tick(2)
        self.q.hold_observe=False;self.tick(20)
        self.assertFalse(self.d.armed);self.assertEqual(len(self.ops('cancel')),count)
    def test_missing_recovery_identity_cannot_rearm(self):
        del self.q.obs['state']['player']['uuid'];self.tick(3)
        self.q.hold_observe=True;self.tick(5);self.now+=3;self.tick(2)
        self.q.hold_observe=False;self.tick(20)
        self.assertFalse(self.d.armed);self.assertEqual(self.d.reason,'observation_recovery_context_changed')
    def test_recovery_requires_advancing_game_ticks(self):
        self.tick(3);self.q.hold_observe=True;self.tick(5);self.now+=3;self.tick(2)
        self.q.hold_observe=False;original=self.q.submit
        def submit(command):
            request_id=original(command)
            if command['op']=='observe':self.q.results[request_id]['result']['state']['world']['game_time']=100
            return request_id
        self.q.submit=submit;self.tick(20)
        self.assertFalse(self.d.armed);self.assertEqual(self.d.recovery_samples,0)
    def test_recovery_waits_until_menu_is_closed(self):
        self.tick(3);self.q.hold_observe=True;self.tick(5);self.now+=3;self.tick(2)
        self.q.hold_observe=False;self.q.obs['state']['screen_open']=True;self.tick(15)
        self.assertFalse(self.d.armed)
        self.q.obs['state']['screen_open']=False;self.tick(15);self.assertTrue(self.d.armed)
    def test_navigation_epoch_is_incremented_by_defense_takeover(self):
        self.tick(3);epoch=self.d.status()['defense_epoch']
        self.set_entities(enemy());self.tick(10)
        self.assertGreater(self.d.status()['defense_epoch'],epoch)
    def test_stale_navigation_epoch_is_cancelled_without_resident_dispatch(self):
        self.tick(3);epoch=self.d.defense_epoch
        self.set_entities(enemy());self.tick(10)
        before=len(self.q.calls)
        self.assertTrue(self.d.submit_owner('stale-route',{'op':'action','action':'follow_path',
                                                         '_navigation_defense_epoch':epoch}))
        self.assertEqual(len(self.q.calls),before)
        self.assertEqual(self.d.completed[-1]['result']['reason'],'navigation_defense_epoch_changed')
    def test_matching_navigation_epoch_is_stripped_before_dispatch(self):
        self.tick(3)
        self.assertTrue(self.d.submit_owner('route',{'op':'action','action':'follow_path',
                                                    '_navigation_defense_epoch':self.d.defense_epoch}))
        self.assertNotIn('_navigation_defense_epoch',self.ops('action')[0])

    def test_read_failure_after_manual_hard_pause_does_not_cancel_manual_input(self):
        self.set_entities(enemy());self.inherit()
        self.q.obs['combat']={'active':False,'reason':'explicit_direct'};self.tick(8)
        self.assertFalse(self.d.armed);old_reason=self.d.reason
        self.q.hold_observe=True;self.tick(6)
        self.q.results[self.d.rpc['id']]={'status':'failed','reason':'transport_failed'}
        self.tick(2)
        self.assertEqual(self.ops('cancel'),[]);self.assertEqual(self.d.reason,old_reason)
    def test_read_uncertainty_after_hard_pause_does_not_rearm_or_cancel(self):
        self.tick(3);self.d.attention('operator_took_control');self.q.hold_observe=True;self.tick(6)
        self.q.results[self.d.rpc['id']]={'status':'uncertain','reason':'transport_failed'}
        self.tick(2)
        self.assertFalse(self.d.armed);self.assertEqual(self.ops('cancel'),[])

class PolicyChecks(unittest.TestCase):
    def test_health_increase_is_not_damage(self):
        p=TargetPolicy(HOSTILES);s=observation()['state'];p.observe_health(s,0)
        s['player']['health']=21;self.assertFalse(p.observe_health(s,1))
    def test_new_world_resets_damage_baseline(self):
        p=TargetPolicy(HOSTILES);s=observation()['state'];p.observe_health(s,0)
        s['world']={'world_generation':'new'};s['player']['health']=10
        self.assertFalse(p.observe_health(s,1));self.assertIsNone(p.last_damage)
    def test_health_drop_window_expires_instead_of_permanent_expanded_targeting(self):
        p=TargetPolicy(HOSTILES);s=observation()['state'];p.observe_health(s,0)
        s['player']['health']=18;p.observe_health(s,1);s['nearby']['entities']=[enemy(distance=7)]
        self.assertIsNotNone(p.choose(s,2));self.assertIsNone(p.choose(s,4))
    def test_old_unreachable_target_temporarily_excluded_to_prevent_ping_pong(self):
        p=TargetPolicy(HOSTILES);s=observation()['state'];s['nearby']['entities']=[enemy(),enemy(OTHER,3)]
        p.lock(TARGET,0);p.prepare_retarget(s['nearby']['entities'][1],4);p.lock(OTHER,4.5)
        self.assertIsNone(p.choose(s,6,exclude=(OTHER,)))
        self.assertEqual(p.choose(s,9,exclude=(OTHER,))['uuid'],TARGET)
    def test_damage_event_never_assigns_nearby_entity_as_attacker(self):
        p=TargetPolicy(HOSTILES);s=observation()['state'];s['nearby']['entities']=[enemy()]
        p.observe_health(s,0);s['player']['health']=19;p.observe_health(s,1)
        self.assertIsNone(p.status(1)['last_health_drop']['attacker_uuid'])
    def test_stopped_blocked_target_missing_releases_after_hysteresis(self):
        p=TargetPolicy(HOSTILES);s=observation()['state'];p.lock(TARGET,0)
        combat={'active':False,'reason':'combat_flat_approach_blocked'}
        self.assertEqual(p.assess(s,combat,1)[0],'wait')
        self.assertEqual(p.assess(s,combat,2)[0],'released');self.assertIsNone(p.locked_uuid)
    def test_stopped_blocked_dead_target_releases_immediately(self):
        p=TargetPolicy(HOSTILES);s=observation()['state'];s['nearby']['entities']=[{**enemy(),'alive':False,'health':0}]
        p.lock(TARGET,0)
        self.assertEqual(p.assess(s,{'active':False,'reason':'combat_flat_approach_blocked'},1)[0],'released')
    def test_stopped_blocked_target_now_reachable_is_reacquired_not_replaced(self):
        p=TargetPolicy(HOSTILES);s=observation()['state'];s['nearby']['entities']=[enemy(),enemy(OTHER,1)]
        s['crosshair']={'type':'entity','uuid':TARGET,'distance_euclidean':2};p.lock(TARGET,0)
        decision,target=p.assess(s,{'active':False,'reason':'combat_flat_approach_blocked'},1)
        self.assertEqual((decision,target['uuid']),('reacquire',TARGET));self.assertEqual(p.choose(s,1)['uuid'],TARGET)
    def test_stopped_unreachable_without_alternative_has_bounded_release(self):
        p=TargetPolicy(HOSTILES);s=observation()['state'];s['nearby']['entities']=[enemy(distance=6)];p.lock(TARGET,0)
        combat={'active':False,'reason':'combat_flat_approach_blocked'}
        self.assertEqual(p.assess(s,combat,1)[0],'wait')
        self.assertEqual(p.assess(s,combat,5)[0],'released');self.assertIsNone(p.choose(s,5))
if __name__=='__main__':unittest.main()
