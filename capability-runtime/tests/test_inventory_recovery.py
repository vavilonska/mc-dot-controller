"""Synthetic ordinary-click policy tests. These do not establish game acceptance."""
import copy
import unittest
from mdc_skills import inventory_recovery as recovery, container
from mdc_skills.core import Outcome, SkillError
from mdc_toolbox.bindings import inventory as binding
from mdc_toolbox.catalog import CapabilityCatalog
from mdc_toolbox.contracts import ToolboxError, validate_schema
from test_reach_inventory_resources import observation, stack
from test_toolbox_inventory_container import storage_observation, target_slot, resized, Control

MENU_ID = '11111111-1111-1111-1111-111111111111'
SCREEN_ID = '22222222-2222-2222-2222-222222222222'

def ready(obs):
    obs.player['armor'] = [{**stack(), 'slot': name} for name in ('feet', 'legs', 'chest', 'head')]
    obs.state['menu']['recovery_context'] = {'schema_version': 1, 'menu_instance': MENU_ID,
        'screen_instance': SCREEN_ID if obs.state['screen_open'] else 'none', 'screen_open': obs.state['screen_open']}
    return obs

def inventory_observation(entries=None, offhand=None):
    obs = ready(observation(entries=entries or {0: stack('minecraft:stone', 4)}))
    obs.player['offhand'] = copy.deepcopy(offhand or stack())
    rows = [{'menu_index': i, 'slot_index': i, 'container_slot': i, 'player_inventory': False,
             'active': True, 'item': stack()} for i in range(5)]
    for index in [39, 38, 37, 36, *range(9, 36), *range(9), 40]:
        i = len(rows)
        value = recovery._inventory_item(obs, index)
        rows.append({'menu_index': i, 'slot_index': i, 'container_slot': index,
                     'inventory_index': index, 'player_inventory': True, 'active': True,
                     'item': copy.deepcopy(value)})
    obs.state['menu'].update(menu_class=container.PREFIX+'InventoryMenu', container_id=0, state_id=11,
        slots=rows, slots_total=len(rows), slots_returned=len(rows))
    return obs

class Runtime:
    def __init__(self, obs, *, stop=None, mutate_before=None, mutate_after=None):
        self.current=copy.deepcopy(obs); self.commands=[]; self.stop=stop
        self.mutate_before=mutate_before; self.mutate_after=mutate_after; self.mutations=0
    def observe(self, **_): return copy.deepcopy(self.current)
    def execute(self, skill, command, verify, *, before, **_):
        self.commands.append(copy.deepcopy(command)); n=len(self.commands); rid='recovery-'+str(n)
        if self.stop:
            return Outcome(self.stop, 'synthetic_'+self.stop, (rid,), {}, before)
        if self.mutate_before: self.mutate_before(self.current)
        view=recovery.View(self.current)
        if (view.binding(command['inventory_recovery']['phase'])!=command['inventory_recovery']
            or command['expected_menu_state_id']!=view.menu['state_id']
            or command['expected_carried']!=view.menu['carried']):
            return Outcome('blocked','native_bound_state_changed',(rid,),{},before)
        menu=self.current.state['menu']; row=menu['slots'][command['slot']]
        old=row['item']; carried=menu['carried']; self.mutations+=1
        if carried['empty']:
            row['item'],menu['carried']=stack(),copy.deepcopy(old)
        else:
            amount=min(carried['count'], min(64,carried['max_stack_size'])-old['count'])
            row['item']=resized(carried,old['count']+amount); menu['carried']=resized(carried,carried['count']-amount)
        i=row['inventory_index']
        if i<36: self.current.player['inventory'][i]={**copy.deepcopy(row['item']),'slot':i}
        elif i==40: self.current.player['offhand']=copy.deepcopy(row['item'])
        menu['state_id']=(menu['state_id']+1)%32768
        if self.mutate_after: self.mutate_after(self.current,n)
        valid=verify(before,self.current)
        return Outcome('succeeded' if valid else 'failed','semantic_verified' if valid else 'postcondition_not_observed',
            (rid,),{'native_status':'succeeded','inputs_released':True,'server_confirmed':False},copy.deepcopy(self.current))
    def require_success(self,result):
        if not result.ok: raise SkillError(result.reason,status=result.status)
        return result.last_observation
    def result(self,skill,observations,**evidence): return Outcome('succeeded','goal_observed',(),evidence,observations[-1])

def cursor_args(obs):
    menu=obs.state['menu']; context=menu['recovery_context']
    return dict(container_id=menu['container_id'],menu_state_id=menu['state_id'],
        menu_instance=context['menu_instance'],screen_instance=context['screen_instance'],
        cursor_fingerprint=menu['carried']['item_fingerprint'])

def fill(obs,item='minecraft:bread',count=64):
    for i in range(36):
        value={**stack(item,count),'slot':i};obs.player['inventory'][i]=value
        next(r for r in obs.state['menu']['slots'] if r.get('inventory_index')==i)['item']=copy.deepcopy(value)
    return obs

class RecoveryTests(unittest.TestCase):
    def test_clear_both_exact_vanilla_pickups_and_release(self):
        runtime=Runtime(inventory_observation(offhand=stack('minecraft:torch',8)))
        result=recovery.clear_hand(runtime)
        self.assertTrue(result.ok,result.reason);self.assertEqual(len(runtime.commands),4)
        self.assertTrue(runtime.current.player['inventory'][0]['empty']);self.assertTrue(runtime.current.player['offhand']['empty'])
        self.assertEqual(sum(v['count'] for v in runtime.current.player['inventory']),12)
        self.assertTrue(all(s['evidence']['inputs_released'] for s in result.evidence['stages']))
        self.assertEqual([c['slot'] for c in runtime.commands],[36,37,45,38])
    def test_merges_across_whole_inventory_when_no_empty_slot(self):
        obs=fill(inventory_observation(offhand=stack('minecraft:stone',8)))
        for i,count in [(34,60),(35,60)]:
            value={**stack('minecraft:stone',count),'slot':i};obs.player['inventory'][i]=value
            obs.state['menu']['slots'][target_slot(obs,i)]['item']=copy.deepcopy(value)
        runtime=Runtime(obs);result=recovery.clear_hand(runtime,hand='offhand')
        self.assertTrue(result.ok,result.reason);self.assertEqual(len(runtime.commands),3)
        self.assertEqual(runtime.current.player['inventory'][34]['count'],64)
        self.assertEqual(runtime.current.player['inventory'][35]['count'],64)
    def test_second_hand_capacity_failure_does_not_pick_up_first(self):
        obs=fill(inventory_observation(offhand=stack('minecraft:stone',1)))
        runtime=Runtime(obs)
        with self.assertRaisesRegex(SkillError,'insufficient_storage_capacity'):recovery.clear_hand(runtime)
        self.assertEqual(runtime.commands,[])
    def test_noop_is_observation_only(self):
        runtime=Runtime(inventory_observation(entries={1:stack('minecraft:stone',1)}))
        self.assertTrue(recovery.clear_hand(runtime).ok);self.assertEqual(runtime.commands,[])
    def test_explicit_cursor_recovery_in_all_supported_menus(self):
        for kind in ('ChestMenu','HopperMenu','DispenserMenu','ShulkerBoxMenu','InventoryMenu'):
            obs=inventory_observation() if kind=='InventoryMenu' else ready(storage_observation(kind=kind))
            obs.state['menu']['carried']=stack('minecraft:stone',8)
            runtime=Runtime(obs);result=recovery.recover_cursor(runtime,**cursor_args(obs))
            self.assertTrue(result.ok,(kind,result.reason));self.assertTrue(runtime.current.state['menu']['carried']['empty'])
            self.assertEqual(runtime.current.state['screen_open'],obs.state['screen_open'])
    def test_full_inventory_cursor_fails_before_click(self):
        obs=fill(inventory_observation());obs.state['menu']['carried']=stack('minecraft:stone',1);runtime=Runtime(obs)
        with self.assertRaisesRegex(SkillError,'insufficient_storage_capacity'):recovery.recover_cursor(runtime,**cursor_args(obs))
        self.assertFalse(runtime.commands)
    def test_exact_window_revision_cursor_are_required(self):
        obs=ready(storage_observation());obs.state['menu']['carried']=stack('minecraft:stone',1)
        for key,value in [('container_id',8),('menu_state_id',12),('menu_instance',SCREEN_ID),
                          ('screen_instance',MENU_ID),('cursor_fingerprint','different')]:
            runtime=Runtime(obs)
            with self.subTest(key=key),self.assertRaisesRegex(SkillError,'changed'):
                recovery.recover_cursor(runtime,**{**cursor_args(obs),key:value})
            self.assertFalse(runtime.commands)
    def test_unknown_failure_cancel_never_replay(self):
        for status in ('unknown','failed','cancelled'):
            runtime=Runtime(inventory_observation(),stop=status);result=recovery.clear_hand(runtime)
            self.assertEqual(result.status,status);self.assertEqual(len(runtime.commands),1)
            self.assertFalse(result.evidence['automatic_replay_allowed'])
    def test_cancel_between_clicks_retains_cursor_without_cleanup(self):
        runtime=Runtime(inventory_observation());result=recovery.clear_hand(runtime,control=Control(stop_at=3))
        self.assertEqual(result.status,'cancelled');self.assertEqual(len(runtime.commands),1)
        self.assertEqual(result.evidence['last_observed_carried']['count'],4)
    def test_changed_window_or_cursor_before_native_blocks(self):
        for mutate in (lambda o:o.state['menu'].update(state_id=12),
                       lambda o:o.state['menu']['recovery_context'].update(menu_instance=SCREEN_ID),
                       lambda o:o.state['menu'].update(carried=stack('minecraft:dirt',1))):
            runtime=Runtime(inventory_observation(),mutate_before=mutate)
            result=recovery.clear_hand(runtime);self.assertFalse(result.ok);self.assertEqual(runtime.mutations,0)
    def test_full_conservation_catches_unrelated_item_change(self):
        def corrupt(obs,n):
            obs.player['offhand']=stack('minecraft:diamond',1)
            obs.state['menu']['slots'][45]['item']=copy.deepcopy(obs.player['offhand'])
        runtime=Runtime(inventory_observation(),mutate_after=corrupt);result=recovery.clear_hand(runtime)
        self.assertFalse(result.ok);self.assertEqual(len(runtime.commands),1)
    def test_complete_coverage_and_schema_fail_closed(self):
        for mutate in (lambda o:o.state['menu'].pop('recovery_context'),
                       lambda o:o.player.update(armor=[]),
                       lambda o:o.state['menu'].update(slots_truncated=True)):
            obs=inventory_observation();mutate(obs);runtime=Runtime(obs)
            with self.assertRaises(SkillError):recovery.clear_hand(runtime)
            self.assertFalse(runtime.commands)
    def test_whole_budget_preflight(self):
        runtime=Runtime(inventory_observation(offhand=stack('minecraft:torch',1)))
        with self.assertRaisesRegex(SkillError,'budget_insufficient'):recovery.clear_hand(runtime,max_actions=3)
        self.assertFalse(runtime.commands)
        from mdc_toolbox.budgets import SharedBudget
        for budget in ({'max_actions':2,'max_observations':100},{'max_actions':10,'max_observations':2}):
            control=Control();control.budget=SharedBudget(budget,60,wall_clock=lambda:0,clock=lambda:0)
            with self.assertRaisesRegex(SkillError,'shared_'):recovery.clear_hand(runtime,control=control)
            self.assertFalse(runtime.commands)
    def test_public_schema_and_requirements(self):
        defs={x['capability']:x for x in binding.definitions()}
        for name in ('clear_hand','recover_cursor'):
            self.assertIn(recovery.FEATURE,defs[name]['native_features']);self.assertFalse(defs[name]['normal_fallback']['automatic'])
        for args in ({'hand':'head'},{'max_actions':True},{'raw_action':{}},{'hand':'both','callback':'x'}):
            with self.assertRaises(ToolboxError):validate_schema(args,defs['clear_hand']['input_schema'])
        with self.assertRaises(ToolboxError):validate_schema({},defs['recover_cursor']['input_schema'])
        entry=CapabilityCatalog().entry('clear_hand',{'available':True,'private_singleplayer':True,
            'supported_capabilities':['clear_hand'],'native_features':['capability_guard/1','action:click_slot']})
        self.assertFalse(entry['runtime_available']);self.assertEqual(entry['availability_reason'],'native_feature_unavailable')


class RealRuntimeRecoveryTests(unittest.TestCase):
    """Real durable Runtime and exact receipt checks; the gateway and clicks are synthetic."""
    def run_case(self, *, lag=0, bad_release=False, lost=False):
        import tempfile
        from support_core import Client, Clock
        from mdc_skills.core import Runtime as DurableRuntime
        model=Runtime(inventory_observation(offhand=stack('minecraft:torch',2)))
        clock=Clock()
        class Gateway(Client):
            def __init__(self):
                super().__init__(clock);self.pending_model=None;self.remaining=0
                self.fail_after_submit=lost
                self.patch_state=self.state_patch
            def state_patch(self,state):
                current=copy.deepcopy(model.current.state)
                state['menu']=current['menu'];state['screen_open']=current['screen_open']
                state['player'].update(current['player']);state['player']['uuid']='player-one'
                state['player']['mainhand']=state['player']['inventory'][state['player']['selected_slot']]
                return state
            def wait(self,request_id,timeout):
                command=self.results[request_id]
                if command['op']=='action':
                    old=copy.deepcopy(model.current)
                    result=model.execute('native',command,lambda *_:True,before=old)
                    self.pending_model=copy.deepcopy(model.current);model.current=old;self.remaining=lag
                    if not lag:model.current=self.pending_model;self.pending_model=None
                elif self.pending_model is not None:
                    self.remaining-=1
                    if self.remaining<=0:model.current=self.pending_model;self.pending_model=None
                result=super().wait(request_id,timeout)
                if bad_release and 'action' in result['result']:
                    result['result']['action']['result']['input_release_confirmed']=False
                return result
        gateway=Gateway()
        with tempfile.TemporaryDirectory() as directory:
            runtime=DurableRuntime(gateway,directory,clock=clock,sleeper=clock.sleep)
            try:
                result=recovery.clear_hand(runtime)
                if lost or bad_release:
                    self.assertEqual(result.status,'unknown',result)
                    with self.assertRaises(SkillError):recovery.clear_hand(runtime)
                    self.assertEqual(gateway.action_count,1)
                elif lag>=9:
                    self.assertFalse(result.ok);self.assertEqual(gateway.action_count,1)
                else:
                    self.assertTrue(result.ok,result)
                    self.assertEqual(gateway.action_count,4)
                    self.assertTrue(all(len(stage['evidence']['stable_game_times'])==2 for stage in result.evidence['stages']))
                    for command,_ in gateway.calls:
                        if command['op']=='action':
                            self.assertEqual(command['expected_player_uuid'],'player-one')
                            self.assertEqual(len(command['inventory_recovery']['inventory']),41)
                    self.assertFalse(result.evidence['server_confirmed'])
                return result
            finally:runtime.close()
    def test_actual_runtime_delayed_ack_two_distinct_ticks(self):self.run_case(lag=3)
    def test_actual_runtime_no_effect_timeout_never_replays(self):self.run_case(lag=9)
    def test_actual_runtime_unknown_post_never_replays(self):self.run_case(lost=True)
    def test_actual_runtime_unconfirmed_release_never_recovers_again(self):self.run_case(bad_release=True)


if __name__=='__main__':unittest.main()
