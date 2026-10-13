import copy
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from mdc_skills.core import Observation, Outcome, SkillError
from mdc_skills import threats, dimensions


def observation(*, tick=1, mobs=(), dimension=dimensions.END, terrain=None, health=20):
    if isinstance(terrain, dict):
        terrain.setdefault('world_generation', 'world')
        terrain.setdefault('dimension', dimension)
    player = dict(x=.5, y=64, z=.5, health=health, alive=True, on_ground=True,
                  selected_slot=0, inventory_truncated=False, inventory_total=0, inventory=[],
                  environment_schema_version=1, frozen_ticks=0,
                  **{key: False for key in threats.ENVIRONMENT_FLAGS})
    state = {'player': player, 'world': {'dimension': dimension, 'world_generation': 'world', 'game_time': tick},
             'nearby': {'entities': list(mobs), 'truncated': False, 'total': len(mobs), 'returned': len(mobs),
                        'loaded_chunks':[{'x':x,'z':z,'loaded':True} for x in range(-3,4) for z in range(-3,4)]}}
    return Observation(state, terrain, {}, tick, ('world', dimension, 'player', 'session'), 0, 'obs-' + str(tick))


def mob(uuid='target', kind='minecraft:zombie', health=20, **extra):
    return dict(uuid=uuid, entity_id=1, type=kind, alive=health > 0, health=health,
                x=.5, y=64, z=2.5, **extra)


def cell(x, y, z, kind='minecraft:air', *, full=False, props=None):
    return dict(x=x, y=y, z=z, id=kind, status='loaded', known=True,
                collision_known=True, collision_empty=not full, full_top_support=full,
                fluid='minecraft:empty', hazards=[], id_truncated=False, fluid_truncated=False,
                properties_truncated=False, properties=props or {}, air=not full)


class FakeRuntime:
    def __init__(self, observations, after=(), status='succeeded'):
        self.observations = list(observations)
        self.after = list(after)
        self.commands = []
        self.status = status
        self.sleeps = []
        self.sleeper = self.sleeps.append
    def observe(self, **kw):
        if not self.observations:
            raise AssertionError('unexpected observe: ' + repr(kw))
        return self.observations.pop(0)
    def execute(self, skill, command, verify, **kw):
        self.commands.append((skill, command, kw))
        before = kw['before']
        last = self.after.pop(0) if self.after else before
        passed = self.status == 'succeeded' and verify(before, last)
        return Outcome('succeeded' if passed else self.status if self.status != 'succeeded' else 'failed',
                       'verified' if passed else 'postcondition_not_observed', ('action-1',), {}, last)
    def require_success(self, outcome):
        if not outcome.ok:
            raise SkillError(outcome.reason, status=outcome.status)
        return outcome.last_observation
    def result(self, skill, observations=(), **evidence):
        observations = list(observations)
        return Outcome('succeeded', skill, (), evidence, observations[-1] if observations else None)


class CombatTests(unittest.TestCase):
    def test_actual_health_decrease_required(self):
        before = observation(mobs=[mob()])
        for hp, expected in [(20, False), (16, True), (0, True)]:
            with self.subTest(hp=hp):
                rt = FakeRuntime([before], [observation(tick=2, mobs=[mob(health=hp)])])
                result = threats.strike(rt, 'target')
                self.assertEqual(result.ok, expected)
                self.assertEqual(rt.commands[0][1]['action'], 'attack_entity')
    def test_missing_living_target_is_not_death(self):
        rt = FakeRuntime([observation(mobs=[mob()])], [observation(tick=2)])
        self.assertFalse(threats.strike(rt, 'target').ok)
    def test_reused_id_or_uuid_stops(self):
        before = observation(mobs=[mob()]); changed = mob(); changed['entity_id'] = 99
        rt = FakeRuntime([before], [observation(tick=2, mobs=[changed])])
        with self.assertRaisesRegex(SkillError, 'target_identity_changed'):
            threats.strike(rt, 'target')
    def test_unknown_never_issues_another_strike(self):
        before = observation(mobs=[mob()])
        rt = FakeRuntime([before, before], status='unknown')
        result = threats.defeat(rt, 'target', max_actions=9)
        self.assertEqual(result.status, 'unknown')
        self.assertEqual(len(rt.commands), 1)
    def test_budget_exhaustion_is_not_victory(self):
        before = observation(mobs=[mob()]); after = observation(tick=2, mobs=[mob(health=19)])
        rt = FakeRuntime([before, before], [after])
        result = threats.defeat(rt, 'target', max_actions=1)
        self.assertEqual(result.reason, 'combat_action_budget_exhausted')
    def test_truncation_low_health_and_hazard_block_before_action(self):
        variants = []
        value = observation(mobs=[mob()]); value.state['nearby']['truncated'] = True; variants.append(value)
        variants.append(observation(mobs=[mob()], health=8))
        value = observation(mobs=[mob()]); value.player['on_fire'] = True; variants.append(value)
        for value in variants:
            rt = FakeRuntime([value])
            with self.assertRaises(SkillError): threats.strike(rt, 'target')
            self.assertFalse(rt.commands)
    def test_phase_five_flame_refused_seven_allowed(self):
        for phase, allow in [(5, False), (7, True), (9, False)]:
            before = observation(mobs=[mob(kind='minecraft:ender_dragon', phase_id=phase)])
            after = observation(tick=2, mobs=[mob(kind='minecraft:ender_dragon', health=19, phase_id=phase)])
            rt = FakeRuntime([before], [after])
            if allow:
                self.assertTrue(threats.strike(rt, 'target', expected_dragon_phase=phase).ok)
                self.assertEqual(rt.commands[0][1]['expected_dragon_phase'], phase)
            else:
                with self.assertRaisesRegex(SkillError, 'safe_perched'): threats.strike(rt, 'target', expected_dragon_phase=phase)
                self.assertFalse(rt.commands)
    def test_native_combat_requires_explicit_death_evidence(self):
        before = observation(mobs=[mob()]); after = observation(tick=2)
        rt = FakeRuntime([before], [after]); self.assertFalse(threats.engage(rt, 'target').ok)
        after.state['client_action'] = {'status':'succeeded','action_id':'new-action','action_session':'session', 'result':{'combat':{'target_uuid':'target',
            'target_entity_id':1, 'target_dead_observed':True}}}
        rt = FakeRuntime([before], [after]); self.assertTrue(threats.engage(rt, 'target').ok)
    def test_real_environment_planner_and_action(self):
        cells = []
        for x in range(-1, 4):
            for z in range(-1, 3):
                for y in range(63, 66):
                    cells.append(cell(x,y,z,'minecraft:stone' if y==63 else 'minecraft:air',full=y==63))
        terrain = {'complete':True,'world_generation':'world','cells':cells}
        before = observation(terrain=terrain); before.player['on_fire'] = True
        # Real planner sees source fire and loaded dry escape. No pretend planner stub.
        for c in cells:
            if (c['x'],c['y'],c['z']) == (0,64,0):
                c['id']='minecraft:fire';c['hazards']=['contact_damage']
        after = observation(tick=2, terrain=terrain)
        rt=FakeRuntime([before],[after]); result=threats.recover_hazard(rt)
        self.assertTrue(result.ok); self.assertEqual(rt.commands[0][1]['action'],'recover_environment')
        self.assertLessEqual(len(rt.commands[0][1]['waypoints']),64)
        self.assertEqual(rt.commands[0][1]['timeout_ms'],10000)
    def test_environment_missing_route_never_flails(self):
        before=observation(terrain={'complete':False});before.player['in_lava']=True
        rt=FakeRuntime([before])
        with self.assertRaisesRegex(SkillError,'no_bounded_observed_egress'):threats.recover_hazard(rt)
        self.assertFalse(rt.commands)


class DimensionTests(unittest.TestCase):
    def test_end_frames_all_inward_and_unique(self):
        rows=dimensions.end_portal_frames({'x':0,'y':64,'z':0})
        self.assertEqual(len(rows),12);self.assertEqual(len({tuple(c.values()) for c,_ in rows}),12)
        self.assertIn(({'x':0,'y':64,'z':-1},'south'),rows)
        self.assertIn(({'x':3,'y':64,'z':0},'west'),rows)
    def test_portal_requires_observed_geometry_then_expected_destination(self):
        cells=[cell(x,y,z,'minecraft:stone' if y==63 else 'minecraft:air',full=y==63)
            for x in range(-1,3) for z in range(-1,3) for y in range(63,66)]
        for c in cells:
            if (c['x'],c['y'],c['z'])==(1,64,0):c['id']='minecraft:nether_portal'
        before=observation(dimension=dimensions.OVERWORLD,terrain={'complete':True,'cells':cells})
        after=observation(tick=2,dimension=dimensions.NETHER)
        rt=FakeRuntime([before],[after]);r=dimensions.enter_portal(rt,{'x':1,'y':64,'z':0},dimensions.NETHER)
        self.assertTrue(r.ok)
        self.assertEqual(rt.commands[0][2]['allowed_dimension'],dimensions.NETHER)
        self.assertEqual(rt.commands[0][2]['max_samples'],128)
        self.assertEqual(rt.commands[0][1]['action'],'follow_path')
        cells[0]['fluid']='minecraft:lava'  # unknown unrelated cell does not alter corridor
        for c in cells:
            if (c['x'],c['y'],c['z'])==(1,63,0):c['full_top_support']=False
        rt=FakeRuntime([before])
        with self.assertRaisesRegex(SkillError,'support_or_collision'):
            dimensions.enter_portal(rt,{'x':1,'y':64,'z':0},dimensions.NETHER)
        self.assertFalse(rt.commands)
    def test_wrong_portal_dimension_cannot_succeed(self):
        rt=FakeRuntime([observation()])
        with self.assertRaisesRegex(SkillError,'pair_unsupported'):
            dimensions.enter_portal(rt,{'x':1,'y':64,'z':0},dimensions.NETHER)
    def test_crystal_receipt_without_removal_is_not_success(self):
        crystal=mob(kind='minecraft:end_crystal');crystal.update(x=13.5,z=.5)
        terrain={'complete':True,'cells':[cell(13,64,0)]}
        before=observation(mobs=[crystal],terrain=terrain)
        for missing in (False,True):
            after=observation(tick=2,mobs=[] if missing else [crystal],terrain=terrain)
            rt=FakeRuntime([before,before],[after])
            with patch.object(dimensions,'_select',return_value=before):r=dimensions.remove_crystal(rt,'target')
            self.assertEqual(r.ok,missing)
            if missing:
                self.assertFalse(r.evidence['all_world_crystals_absent'])
                self.assertFalse(r.evidence['destruction_attributed_to_action'])
    def test_crystal_too_close_stops_before_shot(self):
        crystal=mob(kind='minecraft:end_crystal')
        before=observation(mobs=[crystal]);rt=FakeRuntime([before])
        with patch.object(dimensions,'_select',return_value=before):
            with self.assertRaisesRegex(SkillError,'12_to_32'):dimensions.remove_crystal(rt,'target')
        self.assertFalse(rt.commands)
    def test_crystal_truncated_disappearance_cannot_pass(self):
        crystal=mob(kind='minecraft:end_crystal');crystal.update(x=13.5,z=.5)
        terrain={'complete':True,'cells':[cell(13,64,0)]}
        before=observation(mobs=[crystal],terrain=terrain);after=observation(tick=2,terrain=terrain)
        after.state['nearby']['truncated']=True
        rt=FakeRuntime([before,before],[after])
        with patch.object(dimensions,'_select',return_value=before):
            with self.assertRaisesRegex(SkillError,'complete_entity'):dimensions.remove_crystal(rt,'target')
    def test_phase_wait_bounded_no_actions_and_no_missing_dragon_victory(self):
        rt=FakeRuntime([observation(tick=1),observation(tick=2)])
        r=dimensions.wait_dragon_phase(rt,'dragon',max_samples=2)
        self.assertEqual(r.status,'blocked');self.assertFalse(rt.commands);self.assertEqual(len(rt.sleeps),2)
    def test_phase_wait_context_change_stops(self):
        a=observation(tick=1);b=observation(tick=2);b.state['world']['dimension']=dimensions.OVERWORLD
        rt=FakeRuntime([a,b])
        with self.assertRaises(SkillError):dimensions.wait_dragon_phase(rt,'dragon',max_samples=2)
    def test_crystal_unloaded_original_chunk_is_not_removal(self):
        crystal=mob(kind='minecraft:end_crystal');crystal.update(x=13.5,z=.5)
        before=observation(mobs=[crystal]);after=observation(tick=2)
        after.state['nearby']['loaded_chunks']=[{'x':0,'z':0,'loaded':False}]
        rt=FakeRuntime([before,before],[after])
        with patch.object(dimensions,'_select',return_value=before):
            with self.assertRaisesRegex(SkillError,'target_chunk_not_observed_loaded'):
                dimensions.remove_crystal(rt,'target')
    def test_ignition_uses_actual_existing_hotbar_item(self):
        cells=[]
        for x in range(-1,3):
            for y in range(63,68):
                edge=x in (-1,2) or y in (63,67)
                cells.append(cell(x,y,0,'minecraft:obsidian' if edge else 'minecraft:air',full=edge))
        before=observation(dimension=dimensions.OVERWORLD,terrain={'complete':True,'cells':cells})
        before.player['selected_slot']=3
        after=copy.deepcopy(before)
        for c in after.terrain['cells']:
            if c['x'] in (0,1) and c['y'] in (64,65,66):
                c['id']='minecraft:nether_portal';c['properties']={'axis':'x'}
        rt=FakeRuntime([before,before],[after])
        with patch.object(dimensions,'_select',return_value=before):
            result=dimensions.ignite_nether_portal(rt,{'x':0,'y':64,'z':0},hotbar_slot=0)
        self.assertTrue(result.ok);self.assertEqual(rt.commands[0][1]['hotbar_slot'],3)
        self.assertEqual(rt.commands[0][1]['action'],'interact_block')
    def test_activation_preserves_actual_eye_hotbar_slot(self):
        base={'x':0,'y':64,'z':0}
        rows=dimensions.end_portal_frames(base)
        cells=[cell(c['x'],c['y'],c['z'],'minecraft:end_portal_frame',full=True,
               props={'facing':face,'eye':'false' if i==0 else 'true'}) for i,(c,face) in enumerate(rows)]
        before=observation(dimension=dimensions.OVERWORLD,terrain={'complete':True,'cells':cells})
        before.player.update(x=-2,selected_slot=3,inventory=[{'id':'minecraft:ender_eye','count':1}])
        after=copy.deepcopy(before)
        after.terrain['cells'][0]['properties']['eye']='true'
        after.terrain['cells'].extend(cell(x,64,z,'minecraft:end_portal') for x in range(3) for z in range(3))
        rt=FakeRuntime([before,after])
        with patch.object(dimensions,'_select',return_value=before), patch.object(dimensions,'interact',return_value=Outcome('succeeded','verified',('eye',),{},after)) as interact:
            result=dimensions.activate_end_portal(rt,base,hotbar_slot=0)
        self.assertTrue(result.ok);self.assertEqual(interact.call_args.kwargs['hotbar_slot'],3)
    def test_discovery_selects_real_ready_uuid_and_records_range_blockers(self):
        near=mob('ready','minecraft:end_crystal');near.update(x=13.5,z=.5)
        far=mob('too_far','minecraft:end_crystal');far.update(x=40.5,z=.5,entity_id=2)
        before=observation(mobs=[far,near],terrain={'complete':True,'cells':[]})
        before.player['inventory']=[{'id':'minecraft:bow','count':1},{'id':'minecraft:arrow','count':6}]
        rt=FakeRuntime([before]);result=dimensions.discover_end_goals(rt)
        self.assertEqual(result.evidence['selected_crystal_uuids'],['ready'])
        self.assertFalse(result.evidence['all_world_crystals_absent'])
        self.assertIn('crystal_observation_station_12_to_32_blocks',result.evidence['crystals'][1]['blockers'])
        self.assertFalse(rt.commands)
    def test_discovery_enderman_gaze_blocks_auto_crystal_selection(self):
        crystal=mob('crystal','minecraft:end_crystal');crystal.update(x=13.5,z=.5)
        enderman=mob('neutral','minecraft:enderman');enderman['entity_id']=2
        before=observation(mobs=[crystal,enderman],terrain={'complete':True,'cells':[]})
        before.player['inventory']=[{'id':'minecraft:bow','count':1},{'id':'minecraft:arrow','count':6}]
        result=dimensions.discover_end_goals(FakeRuntime([before]))
        self.assertFalse(result.evidence['selected_crystal_uuids'])
        self.assertIn('enderman_gaze_unplanned',result.evidence['global_blockers'])
    def test_auto_crystal_sequence_stops_on_unknown(self):
        before=observation()
        discovered=Outcome('succeeded','found',(),{'selected_crystal_uuids':['one','two']},before)
        unknown=Outcome('unknown','receipt_missing',('exact-pending',),{},before)
        with patch.object(dimensions,'discover_end_goals',return_value=discovered), patch.object(dimensions,'remove_crystal',return_value=unknown) as remove:
            result=dimensions.clear_observed_crystals(FakeRuntime([]))
        self.assertEqual(result.status,'unknown');self.assertEqual(remove.call_count,1)
    def test_end_state_machine_requires_real_health_and_death(self):
        before=observation(mobs=[mob('dragon','minecraft:ender_dragon',phase_id=6)])
        dead=observation(tick=3,mobs=[mob('dragon','minecraft:ender_dragon',health=0,phase_id=9)])
        phase=Outcome('succeeded','ready',(),{'phase_id':6},before)
        equipment=Outcome('succeeded','selected',('select',),{},before)
        hit=Outcome('succeeded','health_decreased',('hit',),{},dead)
        with patch('mdc_skills.inventory.select_hotbar',return_value=equipment), patch.object(dimensions,'wait_dragon_phase',return_value=phase), patch.object(threats,'strike',return_value=hit) as strike:
            result=dimensions.end_battle(FakeRuntime([before]),'dragon',max_strikes=1)
        self.assertTrue(result.ok);self.assertEqual(result.evidence['outcome'],'dragon_dead_observed')
        self.assertFalse(result.evidence['all_world_crystals_absent'])
        self.assertEqual(strike.call_args.kwargs['expected_dragon_phase'],6)
        missing=Outcome('failed','target_missing_not_death',('hit',),{},observation(tick=3))
        with patch('mdc_skills.inventory.select_hotbar',return_value=equipment), patch.object(dimensions,'wait_dragon_phase',return_value=phase), patch.object(threats,'strike',return_value=missing):
            result=dimensions.end_battle(FakeRuntime([before]),'dragon',max_strikes=1)
        self.assertFalse(result.ok)
    def test_pure_native_target_math_compiles_and_executes(self):
        source=Path(__file__).resolve().parents[2]/'client-mod/src/main/java/io/github/campione01/mineclientbridge/CapabilityTargetPolicy.java'
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'CapabilityTargetPolicy.java').write_text(source.read_text())
            (root/'Check.java').write_text('''package io.github.campione01.mineclientbridge;
public class Check {public static void main(String[] args) {
if(CapabilityTargetPolicy.crystalClear(11.99))throw new AssertionError();
if(!CapabilityTargetPolicy.crystalClear(12))throw new AssertionError();
if(CapabilityTargetPolicy.crystalClear(Double.NaN))throw new AssertionError();
if(CapabilityTargetPolicy.stationaryDragonPhase(5))throw new AssertionError();
if(!CapabilityTargetPolicy.stationaryDragonPhase(6))throw new AssertionError();
if(CapabilityTargetPolicy.meleeReach(3.01,6))throw new AssertionError();
if(!Double.isFinite(CapabilityTargetPolicy.bowElevation(13,0)))throw new AssertionError();
if(!Double.isNaN(CapabilityTargetPolicy.bowElevation(33,0)))throw new AssertionError();
System.out.println("native-target-policy-ok");}}
''')
            compile=subprocess.run(['java','com.sun.tools.javac.Main','-source','21','-target','21','-d',tmp,str(root/'CapabilityTargetPolicy.java'),str(root/'Check.java')],capture_output=True,text=True,timeout=30)
            self.assertEqual(compile.returncode,0,compile.stderr)
            run=subprocess.run(['java','-cp',tmp,'io.github.campione01.mineclientbridge.Check'],capture_output=True,text=True,timeout=15)
            self.assertEqual(run.returncode,0,run.stderr);self.assertIn('native-target-policy-ok',run.stdout)

if __name__=='__main__':unittest.main()

class SpeciesAndRetainedDeathTests(unittest.TestCase):
    def test_exact_retained_native_death_is_distinct_from_disappearance(self):
        before=observation(mobs=[mob()]);after=observation(tick=4)
        witness={'target_uuid':'target','target_entity_id':1,'target_type':'minecraft:zombie',
                 'target_initial_health':20,'target_min_observed_health':0,'target_dead_observed':True,'observation_tick':3}
        after.state['client_action']={'status':'succeeded','action':'attack_entity','action_id':'new','action_session':'session',
                                     'result':{'target_action':witness}}
        result=threats.strike(FakeRuntime([before],[after]),'target')
        self.assertTrue(result.ok);self.assertTrue(result.evidence['target_dead_observed'])
        for key,bad in [('target_uuid','other'),('target_dead_observed',False),('observation_tick',99),('target_type','minecraft:cow')]:
            changed=copy.deepcopy(after);changed.state['client_action']['result']['target_action'][key]=bad
            self.assertFalse(threats.strike(FakeRuntime([before],[changed]),'target').ok)
    def test_enderman_melee_requires_exact_observed_shelter(self):
        target=mob(kind='minecraft:enderman');before=observation(mobs=[target])
        with self.assertRaisesRegex(SkillError,'two_block_shelter'):threats._species_policy(before,target,False)
        before.player['enderman_shelter']={'schema_version':1,'safe':True,'roof_y':66}
        self.assertEqual(threats._species_policy(before,target,False),{'enderman_shelter_required':True})
        with self.assertRaises(SkillError):threats._species_policy(before,target,True)
    def test_creeper_active_fuse_and_close_charged_target_rejected(self):
        target=mob(kind='minecraft:creeper');target['z']=14
        target['creeper']={'powered':False,'ignited':False,'swell_ticks':0,'swell_direction':-1,'fuse_ticks':30}
        before=observation(mobs=[target]);self.assertTrue(threats._species_policy(before,target,True)['creeper_safety_required'])
        for key,value in [('ignited',True),('swell_ticks',1),('swell_direction',1),('powered',True)]:
            bad=copy.deepcopy(target);bad['creeper'][key]=value
            with self.assertRaises(SkillError):threats._species_policy(before,bad,True)
    def test_blaze_bootstrap_shield_binding_and_full_cycle_timeout(self):
        target=mob(kind='minecraft:blaze');target.update(z=20,blaze={'charged':True})
        before=observation(mobs=[target]);before.player.update(effects=[],effects_truncated=False,
            offhand={'id':'minecraft:shield','count':1,'item_fingerprint':'shield','damage':0,'max_damage':336})
        policy=threats._species_policy(before,target,True)
        self.assertEqual(policy['blaze_safety_mode'],'shield_window')
        with self.assertRaisesRegex(SkillError,'complete_cycle_deadline'):threats.strike(FakeRuntime([before]),'target',ranged=True,timeout_ms=5000)
        for remaining,allowed in ((63,False),(64,True)):
            before.player['offhand']['damage']=336-remaining
            if allowed:self.assertEqual(threats._species_policy(before,target,True)['blaze_safety_mode'],'shield_window')
            else:
                with self.assertRaisesRegex(SkillError,'durability'):threats._species_policy(before,target,True)
        before.player['offhand']['damage']=0
        after=observation(tick=3,mobs=[dict(target,health=10)])
        after.state['client_action']={'status':'succeeded','action':'shoot_entity','action_id':'new',
            'action_session':'session','result':{'target_action':{'target_uuid':'target','target_entity_id':1,
            'target_type':'minecraft:blaze','observation_tick':2,'shield_window':True,
            'pre_cover_saw_charge':True,'pre_cover_complete':True,'shield_raised':True,'shield_released':True,
            'shield_blocking_observed':True,'cover_ticks':20,'risk_remaining':False}}}
        rt=FakeRuntime([before],[after]);self.assertTrue(threats.strike(rt,'target',ranged=True,timeout_ms=20000).ok)
        self.assertEqual(rt.commands[0][1]['min_health'],18)
        self.assertEqual(rt.commands[0][1]['expected_offhand_item'],before.player['offhand'])
