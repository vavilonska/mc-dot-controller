"""Finite current-consumer tests against fabricated wire witnesses, never engine acceptance."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import unittest
from types import SimpleNamespace
from .mining_fixture import mining_fixture, add_entity
from resident_controller.capability_snapshot import validate_scoped_witness
from mdc_skills import scoped_mining
from mdc_skills.core import Outcome,SkillError
from mdc_toolbox.catalog import CapabilityCatalog, DOMAIN_MODULES
from mdc_toolbox.contracts import PROFILES
from mdc_toolbox.runtime_adapter import OwnerRuntimeBackend
from mdc_toolbox.bindings import resources
from mining_collect.bootstrap import JAVA_ROOT
from mining_collect.references import original_resources

class WitnessTests(unittest.TestCase):
    def test_exact_complete_witness(self):self.assertTrue(validate_scoped_witness(*mining_fixture())['coverage_complete'])
    def bad(self,change):
        d=mining_fixture();change(d)
        with self.assertRaises(ValueError):validate_scoped_witness(*d)
    def test_passive_item_observation_is_not_causal_loot(self):
        d=mining_fixture();m=d[0]['result']['scoped_native_preflight']['facts']['mining']
        add_entity(d,'item',(2.,64.,0.))
        d[0]['result']['mining']['observed_passive_items']=4
        validate_scoped_witness(*d)
        for key,value in (('passive_items',True),('passive_items',1024),('other_entities',2),('entity_policy','allow_everything')):
            self.bad(lambda d,key=key,value=value:d[0]['result']['scoped_native_preflight']['facts']['mining'].update({key:value}))
        for value in (True,-1,1024):
            self.bad(lambda d,value=value:d[0]['result']['mining'].update(observed_passive_items=value))
    def test_t13_movement_source_preserved_and_mining_budgeted(self):
        # Collect and the bounded native entity diagnostic extend T13 movement.
        # Pin their exact source; no geometry/type guard is weakened.
        reference=Path(__file__).resolve().parents[1]/'references/accepted_movement_sha256.json'
        expected=json.loads(reference.read_text())
        self.assertEqual(set(expected),{'ScopedFlatMovement.java','ScopedMovementEntities.java','ScopedEntityPolicy.java'})
        for name,digest in expected.items():
            self.assertEqual(hashlib.sha256((JAVA_ROOT/name).read_bytes()).hexdigest(),digest,name)
        java=JAVA_ROOT
        self.assertIn('active.scopedMovement.activate(active.entry)',(java/'ClientActions.java').read_text())
        self.assertIn('if(capture.movement!=null || capture.mining!=null || capture.placement!=null)',(java/'ScopedNativePreflight.java').read_text())
        mining=(java/'ScopedMining.java').read_text()
        self.assertIn('ScopedMiningEntities.capture',mining)
        self.assertIn('actionEntry.ticks',mining)
        self.assertIn('ClientActions.ownsScopedMining(this,actionEntry)',mining)
    def test_distant_passive_allowed_near_projectile_unknown_refused(self):
        d=mining_fixture();add_entity(d);validate_scoped_witness(*d)
        for kind,pos,vel in [('sheep',(2.,64.,0.),(0.,0.,0.)),('sheep',(20.,64.,0.),(-.2,0.,0.)),('arrow',(20.,64.,0.),(0.,0.,0.))]:
            d=mining_fixture();add_entity(d,kind,pos,vel)
            with self.assertRaises(ValueError):validate_scoped_witness(*d)
        d=mining_fixture();row=add_entity(d);row['class']='custom.Sheep'
        with self.assertRaises(ValueError):validate_scoped_witness(*d)
    def test_observed_profile_rejects_old_timeout_and_clock(self):
        self.bad(lambda d:d[3].update(timeout_ms=20000))
        self.bad(lambda d:d[0]['result']['mining'].update(last_entity_check_action_tick=160))
        self.bad(lambda d:d[0]['result']['scoped_native_preflight']['facts']['mining']['entity_guard'].update(remaining_projection_ticks=159))
    def test_final_tick_and_time_fence_retains_original_sample(self):
        j=JAVA_ROOT
        s=(j/'ScopedMining.java').read_text()
        self.assertIn('int actionTick=actionTicks();',s)
        self.assertIn('actionEntry.ticks==actionTick',s)
        self.assertIn('now-checkBegan<=ScopedNativePreflight.MAX_NANOS',s)
        self.assertLess(s.index('rawFence(mc,true,permitAir,hit,reach,checkTick,yaw,pitch,actionTick,began);'),s.index('sampleActionTick=actionTick;'))
        self.assertIn('ACTIONS.active()==entry && entry!=null && entry.running()', (j/'ClientActions.java').read_text())
    def test_missing_extra_duplicate_and_reordered_cells(self):
        for change in (lambda m:m['cells'].pop(),lambda m:m['cells'].append(deepcopy(m['cells'][0])),
                       lambda m:m['cells'].__setitem__(1,deepcopy(m['cells'][0])),lambda m:m['cells'].reverse()):
            self.bad(lambda d:change(d[0]['result']['scoped_native_preflight']['facts']['mining']))
    def test_changed_target_tool_context(self):
        self.bad(lambda d:d[0]['result']['scoped_native_preflight']['facts']['mining']['target'].update(x=3))
        self.bad(lambda d:d[3]['expected_held_item'].update(count=2))
        self.bad(lambda d:d[0]['result']['scoped_native_preflight']['facts']['context'].update(world_generation='different'))
    def test_wrong_state_class_fluid_or_coverage(self):
        for k,v in (('id','minecraft:sand'),('fluid','minecraft:water'),('block_class','custom.ModBlock'),('properties',{'foo':'bar'}),('loaded',False)):
            self.bad(lambda d,k=k,v=v:d[0]['result']['scoped_native_preflight']['facts']['mining']['cells'][0].update({k:v}))
    def test_original_deadline_and_owner_digest(self):
        for k,v in (('owner_generation',2),('command_sha256','a'*64),('clock_domain','client-pre-tick-v1'),('source_tick',True)):
            self.bad(lambda d,k=k,v=v:d[0]['result']['scoped_native_preflight'].update({k:v}))
        self.bad(lambda d:d[0]['result']['scoped_native_preflight']['facts']['mining'].update(deadline_nano='999'))
    def test_removal_needs_independent_neutral_proof(self):
        for k,v in (('block_removed',False),('input_neutral',False),('unknown_outcome',True),('drops_or_pickup_proven',True)):
            self.bad(lambda d,k=k,v=v:d[0]['result']['mining'].update({k:v}))
    def test_cancel_can_be_neutral_without_removal(self):
        d=mining_fixture();d[0]['status']='cancelled';d[0]['result']['mining']['block_removed']=False
        validate_scoped_witness(*d)
    def test_final_ray_has_exact_face_and_ordinary_reach(self):
        for k,v in (('face','east'),('reach',.1)):
            self.bad(lambda d,k=k,v=v:d[0]['result']['mining']['final_ray'].update({k:v}))
        self.bad(lambda d:d[0]['result']['mining']['final_ray']['hit'].update(x=99))
    def test_integer_and_boolean_fields_are_exact(self):
        for k,v in (('expected_cells',True),('other_entities',False),('stationary',1),('callbacks_installed',1)):
            self.bad(lambda d,k=k,v=v:d[0]['result']['scoped_native_preflight']['facts']['mining'].update({k:v}))

class BindingTests(unittest.TestCase):
    def test_public_profile_is_accepted(self):
        definition=CapabilityCatalog().get('mine_local')
        self.assertEqual(definition['observation_profile'],'player')
        self.assertIn(definition['observation_profile'],PROFILES)
    def test_exact_profile_negotiation(self):
        backend=OwnerRuntimeBackend(None)
        self.assertEqual(backend._profile_actions({'scoped_profiles':{'mining-local-observed-v2':['break_block']}}),{'break_block':'mining-local-observed-v2'})
        self.assertNotIn('break_block',backend._profile_actions({'scoped_profiles':{'mining-local-observed-v2':['break_block','place_block']}}))
    def test_catalog_union_preserves_every_original_entry(self):
        module=original_resources
        old={d['capability']:d for d in module.definitions()};new={d['capability']:d for d in resources.definitions()}
        self.assertEqual(set(new)-set(old),{'mine_local','collect_local'})
        for name in old:self.assertEqual(new[name],old[name])
        cat=CapabilityCatalog();self.assertFalse(cat.load_errors);self.assertIn('mine_local',cat._entries)
        original=CapabilityCatalog(modules=[module if name=='mdc_toolbox.bindings.resources' else name for name in DOMAIN_MODULES])
        self.assertEqual(set(cat._entries)-set(original._entries),{'mine_local','collect_local'})
        for name in original._entries:self.assertEqual(cat.get(name),original.get(name))
        # Combat is an independent current tactical binding in both catalogs.
        self.assertIn('engage',cat._entries);self.assertIn('engage',original._entries)
        self.assertEqual(cat.get('engage'),original.get('engage'))
    def test_schema_blocks_switching_search_and_multi_target(self):
        cat=CapabilityCatalog();args={'target':{'x':2,'y':64,'z':0},'expected_block_id':'minecraft:stone','expected_block_properties':{}}
        cat.validate('mine_local',1,args)
        for extra in ({'hotbar_slot':1},{'auto_move':True},{'targets':[]},{'expected_block_properties':{'axis':'x'}},{'expected_block_id':'minecraft:gravel'}):
            with self.assertRaises(Exception):cat.validate('mine_local',1,{**args,**extra})
    def test_state_only_one_action_no_drop_claim(self):
        class Runtime:
            _job_scoped_profiles={'break_block':'mining-local-observed-v2'}
            def observe(self,**kwargs):self.observation_args=kwargs;return SimpleNamespace()
            def execute(self,skill,command,verify,**kwargs):self.command=command;return Outcome('succeeded','synthetic')
        rt=Runtime();result=scoped_mining.mine_local(rt,{'x':2,'y':64,'z':0},'minecraft:stone',{})
        self.assertEqual(rt.observation_args,{'terrain':False});self.assertEqual(rt.command['action'],'break_block')
        self.assertNotIn('hotbar_slot',rt.command);self.assertFalse(result.evidence['item_acquisition_proven'])
    def test_missing_profile_blocks_before_observation(self):
        with self.assertRaises(SkillError):scoped_mining.mine_local(SimpleNamespace(),{'x':2,'y':64,'z':0},'minecraft:stone',{})
    def test_source_fence_order_and_single_native_lane(self):
        root=JAVA_ROOT
        s=(root/'ScopedNativePreflight.java').read_text();start=s.index('if(mining!=null)mining.admissionBeforeFacts(mc);')
        self.assertLess(start,s.index('require(facts.equals(captureFacts(mc))',start))
        self.assertLess(s.index('require(facts.equals(captureFacts(mc))',start),s.index('mining.admissionAfterFacts(mc)',start))
        scoped=(root/'ScopedMining.java').read_text();self.assertNotIn('.setBlock(',scoped);self.assertNotIn('.send(',scoped)
        dispatch=(root/'ScopedMiningDispatch.java').read_text();self.assertIn('finally {CALL.remove();}',dispatch)
        self.assertIn('throw failure;',dispatch)
        actions=(root/'ClientActions.java').read_text()
        self.assertIn('ScopedMiningDispatch.attack(g,mc::startAttack)',actions)
        self.assertIn('event.getInput()!=input || input!=a.player.input || !ScopedMining.neutral(input)',actions)
        self.assertNotIn('current.getDamageValue(',scoped)
        self.assertIn('containers[i].getItem(indices[i])',scoped)
        self.assertIn('rawInventory();rawMenu.check(player);',scoped)
        self.assertIn('originalWitness.equals(result.get("scoped_native_preflight"))',scoped)
        self.assertIn('commandDigest.equals(ScopedNativePreflight.digest(request.original()))',scoped)
        self.assertIn('receiver==expectedTargetState',scoped)
        self.assertIn('return state.onDestroyedByPlayer(level,pos,player,harvest,fluid);',
                      (root/'mixin/ScopedMiningGameModeMixin.java').read_text())

if __name__=='__main__':unittest.main()
