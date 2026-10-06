import copy
import unittest
from environment_recovery import egress_plan, hazards, dry
from watchdog import Watchdog
from test_watchdog import Queue


def state():
    return {'world':{'world_generation':'test-world','game_time':100},
        'client_action':{'action_session':'test-action-session'},'screen_open':False,'paused':False,
        'player':{'uuid':'test-player','alive':True,'health':5,'on_ground':False,
          'x':.5,'y':64,'z':.5,'environment_schema_version':1,
          'in_water':True,'eye_in_water':True,'in_lava':False,'in_powder_snow':False,
          'on_fire':False,'frozen_ticks':0,'inventory':[]},'nearby':{'entities':[]}}


def terrain(water=True):
    cells=[]
    for x in range(-2,4):
      for z in range(-2,3):
       for y in range(63,68):
        solid=y==63
        wet=water and x<=0 and y in (63,64)
        cells.append({'x':x,'y':y,'z':z,'status':'loaded','known':True,'collision_known':True,
          'id_truncated':False,'fluid_truncated':False,'properties_truncated':False,
          'fluid':'minecraft:water' if wet else 'minecraft:empty','hazards':['water'] if wet else [],
          'id':'minecraft:water' if wet else 'minecraft:stone' if solid else 'minecraft:air',
          'collision_empty':not solid or wet,'full_top_support':solid and not wet})
    return {'complete':True,'world_generation':'test-world','cells':cells}


class EnvQueue(Queue):
    def __init__(self):
        super().__init__();self.obs['state']=state();self.obs['terrain']=terrain();self.moves=[]
    def submit(self,cmd):
        key=super().submit(cmd)
        if cmd['op']=='action' and cmd.get('action')=='recover_environment':
            self.moves.append(key)
            self.obs['action']={'status':'running','result':{'environment_waiting_for_route':not cmd['waypoints']}}
        return key
    def finish_dry(self):
        p=self.obs['state']['player'];p.update(in_water=False,eye_in_water=False,on_ground=True,x=1.5)
        if self.moves:self.results[self.moves[-1]]={'status':'succeeded','result':{}}
        self.obs['action']={'status':'succeeded','result':{}}


class EnvironmentTests(unittest.TestCase):
    def test_old_mod_never_silently_assumes_fields(self):
        s=state();del s['player']['environment_schema_version'];self.assertEqual(hazards(s),())
    def test_air_at_surface_is_not_dry_land(self):
        s=state();s['player']['eye_in_water']=False;s['player']['on_ground']=True
        self.assertFalse(dry(s))
    def test_low_health_dry_recovery_does_not_wait_full_health_or_frozen_zero(self):
        s=state();s['player'].update(in_water=False,eye_in_water=False,on_ground=True,health=1,frozen_ticks=60)
        self.assertTrue(dry(s))
    def test_observed_water_to_dry_exit(self):
        plan=egress_plan(state(),terrain());self.assertTrue(plan)
        self.assertGreater(plan[-1]['x'],.5)
    def test_missing_terrain_or_lava_destination_not_invented(self):
        t=terrain();t['cells']=[];self.assertIsNone(egress_plan(state(),t))
        t=terrain()
        for c in t['cells']:
            if c['x']>0:c['fluid']='minecraft:lava';c['hazards']=['lava']
        self.assertIsNone(egress_plan(state(),t))
    def test_powder_uses_observed_supported_exit(self):
        s=state();s['player'].update(in_water=False,eye_in_water=False,in_powder_snow=True)
        t=terrain(False)
        for c in t['cells']:
            if c['x']==0 and c['z']==0 and c['y']==64:c.update(id='minecraft:powder_snow',hazards=['powder_snow'])
        self.assertTrue(egress_plan(s,t))
    def setup_dog(self):
        self.now=0;self.q=EnvQueue();self.d=Watchdog(self.q,clock=lambda:self.now)
    def tick(self,n):
        for _ in range(n):self.d.tick();self.now+=.1
    def test_single_writer_float_then_verified_route_no_model_involvement(self):
        self.setup_dog();self.tick(15)
        moves=[c for _,c in self.q.calls if c.get('action')=='recover_environment']
        self.assertEqual(len(moves),2);self.assertEqual(moves[0]['waypoints'],[])
        self.assertTrue(moves[1]['waypoints']);self.assertTrue(self.d.environment.active)
        self.assertFalse(self.d.submit_owner('ordinary',{'op':'direct','endpoint':'key','body':{}}))
    def test_dry_requires_later_observations_after_action_completion(self):
        self.setup_dog();self.tick(15);self.q.finish_dry();self.tick(12)
        self.assertFalse(self.d.environment.active);self.assertTrue(self.d.environment.final_observed)
    def test_manual_stop_releases_and_never_resumes_environment(self):
        self.setup_dog();self.tick(12);self.d.stop();self.tick(6)
        self.assertTrue(self.d.stopped);self.assertTrue(self.d.cancel_confirmed)
        self.assertFalse(self.d.environment.active)
    def test_unknown_exit_keeps_one_float_request_not_replay(self):
        self.setup_dog();self.q.obs['terrain']['cells']=[];self.tick(60)
        self.assertEqual(len(self.q.moves),1);self.assertTrue(self.d.environment.active)
    def test_menu_interrupt_never_autocloses_menu(self):
        self.setup_dog();self.tick(10);self.q.obs['state']['screen_open']=True;self.tick(12)
        self.assertFalse(self.d.armed);self.assertFalse(self.d.environment.active)
        self.assertFalse(any(c.get('endpoint')=='raw-key' for _,c in self.q.calls))
    def test_uncertain_request_is_not_replayed(self):
        self.setup_dog();self.tick(12)
        self.q.results[self.q.moves[-1]]={'status':'uncertain'};self.tick(8)
        self.assertFalse(self.d.armed);self.assertEqual(len(self.q.moves),2)

    def test_delayed_read_does_not_cancel_native_flotation(self):
        self.setup_dog();self.q.obs['terrain']['cells']=[];self.tick(8)
        self.q.hold_observe=True
        before=sum(c['op']=='cancel' for _,c in self.q.calls)
        self.tick(60)
        self.assertTrue(self.d.environment.active)
        self.assertEqual(sum(c['op']=='cancel' for _,c in self.q.calls),before)
        self.assertEqual(len(self.q.moves),1)
        self.assertIn('delayed',self.d.environment.reason)
    def test_burning_on_clear_dry_land_does_not_choose_random_direction(self):
        s=state();s['player'].update(in_water=False,eye_in_water=False,on_fire=True,on_ground=True)
        self.assertIsNone(egress_plan(s,terrain(False)))
    def test_burning_in_fire_cell_can_leave_to_observed_dry_land(self):
        s=state();s['player'].update(in_water=False,eye_in_water=False,on_fire=True,on_ground=True)
        t=terrain(False)
        for c in t['cells']:
            if (c['x'],c['y'],c['z'])==(0,64,0):c.update(id='minecraft:fire',hazards=['fire'])
        self.assertTrue(egress_plan(s,t))
    def test_burning_prefers_observed_water_when_reachable(self):
        s=state();s['player'].update(in_water=False,eye_in_water=False,on_fire=True,on_ground=True)
        t=terrain(False)
        for c in t['cells']:
            if c['x']==2 and c['y'] in (63,64):c.update(id='minecraft:water',fluid='minecraft:water',hazards=['water'],collision_empty=True,full_top_support=False)
        route=egress_plan(s,t);self.assertTrue(route);self.assertEqual(route[-1]['x'],2.5)
    def test_world_change_stops_without_reconnecting(self):
        self.setup_dog();self.tick(8);self.q.obs['state']['world']['world_generation']='other'
        self.tick(10);self.assertFalse(self.d.armed);self.assertFalse(self.d.environment.active)

    def test_hazard_reentry_after_terminal_is_new_observed_recovery_not_false_success(self):
        self.setup_dog();self.tick(12)
        old=self.q.moves[-1]
        self.q.results[old]={'status':'succeeded','result':{}}
        # Still actually underwater on the next fresh observation.
        self.tick(10)
        self.assertTrue(self.d.environment.active);self.assertFalse(self.d.environment.final_observed)
        self.assertNotEqual(self.q.moves[-1],old)

    def test_actual_terrain_water_hazard_and_flowing_water_contract(self):
        t=terrain()
        for c in t['cells']:
            if c['fluid']=='minecraft:water':c['fluid']='minecraft:flowing_water'
        self.assertTrue(egress_plan(state(),t))

if __name__=='__main__':unittest.main()
