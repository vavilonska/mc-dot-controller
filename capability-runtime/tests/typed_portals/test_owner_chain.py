"""Public Toolbox -> Runtime -> IntentClient -> Watchdog -> QueueClient -> Resident.
Only the native HTTP endpoint is fabricated; no game, native physics, or server proof.
"""
from copy import deepcopy
from pathlib import Path
import importlib
import time
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit
import test_capability_ownership as owners
from mdc_skills.core import Runtime
from mdc_toolbox import ToolboxService
from mdc_toolbox.runtime_adapter import OwnerRuntimeBackend
from navigation_controller.fake import FakeWorld
from navigation_controller.terrain import Block
from resident_controller.capability_snapshot import validate_scoped_witness
from resident_controller.transport import BridgeError
from typed_portals.typed_portal_fixture import (typed_fixture, footprint, held_item, EMPTY_FP,
    ITEM_PROFILE, PORTAL_PROFILE, SOURCE_WORLD, DESTINATION_WORLD, SERVER)


class RequestOnlyWatchdog(owners.Watchdog):
    def __init__(self,*args,**kwargs):
        kwargs['execution_policy']='request_only';super().__init__(*args,**kwargs)


class Endpoint(owners.CombatEndpoint):
    def __init__(self):
        super().__init__();self.kind='flint';self.outcome='success';self.last_eye=False
        self.profiles={ITEM_PROFILE:['interact_block'],PORTAL_PROFILE:['follow_path']}
        self.fixture_errors=[];self.effect_applied=False;self.delay_source_pairs=2;self.initial_damage=4
        self.post_snapshot_count=0;self.destination_active=False;self.observed_contexts=[]
        self.permit_samples=[];self.lease_owner_samples=[];self.owner_probe=lambda:None
    def snapshot(self):
        value=super().snapshot()
        value['world']['world_generation']=DESTINATION_WORLD if self.destination_active else SOURCE_WORLD
        value['world']['dimension']=value['player']['dimension']='minecraft:the_nether' if self.destination_active else 'minecraft:overworld'
        if self.outcome=='wrong_server' and self.effect_applied:
            value['world']['integrated_server_instance']='44444444-4444-4444-8444-444444444444'
        for row in value['player']['inventory']:
            row.update(id='minecraft:air',count=0,empty=True,item_fingerprint=EMPTY_FP,
                component_fingerprint=EMPTY_FP,max_stack_size=0,damage=0,max_damage=0)
        value['player']['inventory'][0].update(held_item(self.kind))
        if self.kind=='flint':value['player']['inventory'][0]['damage']=self.initial_damage
        if self.effect_applied and self.kind!='portal':
            selected=value['player']['inventory'][0]
            if self.kind=='flint' and self.outcome!='wrong_damage':
                selected.update(damage=self.initial_damage+1,component_fingerprint='55555555-5555-4555-8555-555555555555')
                if self.outcome=='wrong_damage_bool':selected['damage']=True
            if self.kind=='eye' and self.outcome!='wrong_count':selected['count']=2
            if self.outcome=='wrong_protected_inventory':value['player']['inventory'][1]['component_fingerprint']='99999999-9999-4999-8999-999999999999'
        value['player']['mainhand']=deepcopy(value['player']['inventory'][0])
        value['player'].update(inventory_total=36,offhand={'id':'minecraft:air','empty':True,'count':0},armor=[])
        value['scoped_native_preflight']={'version':'scoped-native-preflight/1','private_singleplayer_only':True,
            'same_callback_capture_validate_admit':True,'capability_guard_schema_version':1,
            'profiles':deepcopy(self.profiles),'guarded_actions':['interact_block','follow_path']}
        return value
    def world(self):
        world=FakeWorld();world.generation=DESTINATION_WORLD if self.destination_active else SOURCE_WORLD
        if self.kind=='portal':
            world.set(Block(1,64,0),'nether_portal',properties={'axis':'x'},collision_empty=True,full_top_support=False)
        else:
            for r in footprint(self.kind,self.last_eye):
                final=self.effect_applied and self.outcome!='wrong_block'
                id=r['block_id'] if final else r['expected_id'];props=r['properties'] if final else r['expected_properties']
                nonsolid=id in ('minecraft:air','minecraft:nether_portal','minecraft:end_portal')
                world.set(Block(**r['position']),id.removeprefix('minecraft:'),properties=deepcopy(props),
                    collision_empty=nonsolid,full_top_support=not nonsolid and id!='minecraft:end_portal_frame')
        return world
    def request(self,method,path,body=None):
        if path=='/control/scoped-action':
            self.posts.append((path,deepcopy(body)))
            self.action,_,_,_=typed_fixture(self.kind,body['intent'],body['preflight'],terminal=False)
            try:validate_scoped_witness(self.action,body['preflight'],body['intent']['action_id'],body['intent'])
            except ValueError as exc:self.fixture_errors.append(str(exc))
            if self.outcome=='lost':raise BridgeError('synthetic_lost_submit',uncertain=True)
            return deepcopy(self.action)
        if path.startswith('/control/action/status') and self.action['status']=='running':
            if self.hold:return deepcopy(self.action)
            self.action.update(status='cancelled' if self.kind=='portal' else 'succeeded',
                reason='world_transition' if self.kind=='portal' else 'synthetic_item_success')
            if self.outcome=='unrelated_cancel':
                self.action.update(status='cancelled',reason='cancel_requested')
                self.action['result']['portal_entry']['transition_eligible']=False
            if self.outcome=='forged':self.action['result']['portal_entry']['original_native_action_id']='0'*32
            if self.outcome=='terminal_unknown':self.action['result']['portal_entry']['unknown_outcome']=True
            if self.outcome=='missing_contact':self.action['result']['portal_entry']['source_portal_contact']=False
            self.effect_applied=True
            return deepcopy(self.action)
        if path.startswith('/control/capability-snapshot?') and self.effect_applied and self.outcome=='post_item_count_bool':
            self.action['result']['item_interaction']['final_count']=True
        if path.startswith('/control/capability-snapshot?') and self.effect_applied and self.kind=='portal':
            self.post_snapshot_count+=1
            if self.outcome=='post_bool_forged':self.action['result']['portal_entry']['transition_eligible']=1
            if self.outcome=='post_forged':self.action['result']['portal_entry']['original_native_action_id']='0'*32
            if self.post_snapshot_count>self.delay_source_pairs*2+2:
                if self.outcome=='arrival_forged':self.action['result']['portal_entry']['original_native_action_id']='0'*32
                if self.outcome=='arrival_bool_forged':self.action['result']['portal_entry']['transition_eligible']=1
            if self.outcome=='disconnect':raise BridgeError('synthetic_disconnect',uncertain=False)
            # Each actual terrain observation has two atomic capability snapshots.
            # Advance only between the source pairs, never in the middle of a pair.
            if self.outcome!='never_arrive' and self.post_snapshot_count>self.delay_source_pairs*2:
                self.destination_active=True
            lease=self.owner_probe()
            if lease and lease.get('transition'):
                self.permit_samples.append(deepcopy(lease['transition']))
                self.lease_owner_samples.append((lease['owner_id'],lease['defense_epoch'],lease['resident_session']))
            self.observed_contexts.append('destination' if self.destination_active else 'source')
        if path.startswith('/control/terrain?'):
            query=parse_qs(urlsplit(path).query)
            if 'radius' in query:
                pages=self.world().pages(radius=int(query['radius'][0]),vertical=int(query['vertical'][0]),
                    tick=self.tick,limit=min(int(query.get('limit',['128'])[0]),512))
                for page in pages:
                    page['dimension']='minecraft:the_nether' if self.destination_active else 'minecraft:overworld'
                    if query.get('capability')==['1']:page.update(capability_page_schema_version=1,page_limit=int(query['limit'][0]))
                self.terrain_pages=iter(pages)
            page=next(self.terrain_pages);self.terrain_responses.append(deepcopy(page));return page
        return super().request(method,path,body)


class PublicTypedOwnerChainTests(unittest.TestCase):
    until=owners.ActualGatewayOwnershipTests.until
    def setUp(self):
        # Detect fixture bootstraps that silently prepend a different checkout.
        source=Path(importlib.import_module('mdc_skills.core').__file__).resolve().parents[2]
        for name in ('mdc_toolbox.service','mdc_toolbox.runtime_adapter','intent_client','base_watchdog','watchdog',
                     'capability_ownership','resident_controller.ipc','resident_controller.controller',
                     'resident_controller.capability_snapshot','resident_controller.item_interaction_snapshot',
                     'resident_controller.portal_entry_snapshot'):
            self.assertTrue(Path(importlib.import_module(name).__file__).resolve().is_relative_to(source),
                            'mixed production source tree: '+name)
        with patch.object(owners,'CombatEndpoint',Endpoint),patch.object(owners,'Watchdog',RequestOnlyWatchdog):
            owners.ActualGatewayOwnershipTests.setUp(self)
        self.runtime=Runtime(self.client,self.root/'typed-runtime',wait_timeout=3)
        self.backend=OwnerRuntimeBackend(self.runtime);self.service=ToolboxService(self.backend,self.root/'toolbox')
        self.bridge.owner_probe=lambda:self.dog.capability_lease
    def tearDown(self):
        self.service.close();self.runtime.close();owners.ActualGatewayOwnershipTests.tearDown(self)
    def submit(self,kind='flint',deadline=12):
        self.bridge.kind=kind
        capability={'flint':'ignite_portal_local','eye':'insert_end_eye_local','portal':'enter_portal_local'}[kind]
        args={'flint':{'interior_base':{'x':2,'y':64,'z':0}},
              'eye':{'interior_corner':{'x':3,'y':63,'z':0},'target':{'x':3,'y':63,'z':-1}},
              'portal':{'portal_cell':{'x':1,'y':64,'z':0},'destination':'minecraft:the_nether','timeout_ms':5000}}[kind]
        description=self.backend.describe()
        return self.service.call('mdc_job',{'api_version':'mdc.toolbox/1','operation':'submit','request_id':'typed_one',
            'session_ref':description['session_ref'],'expected_context_ref':description['context_ref'],
            'capability':capability,'capability_version':1,'arguments':args,
            'policy':{'version':1,'execution_mode':'request_only','reactions':'stop'},
            'budgets':{'max_actions':3,'max_observations':128,'deadline_seconds':deadline},'wait_ms':0})
    def finish(self,result,timeout=15):
        self.assertIn('job_id',result,result)
        def terminal():
            self.result=self.service.call('mdc_job',{'api_version':'mdc.toolbox/1','operation':'status',
                'job_id':result['job_id'],'session_ref':result['session_ref']})
            return self.result['state'] not in ('accepted','running','stopping')
        self.until(terminal,timeout=timeout);return self.result
    def posts(self):return [b for p,b in self.bridge.posts if p=='/control/scoped-action']
    def assert_one_exact_request(self,profile):
        posts=self.posts();self.assertEqual(len(posts),1,(self.bridge.fixture_errors,self.result));self.assertFalse(self.bridge.fixture_errors)
        self.assertEqual(posts[0]['preflight']['profile'],profile)
        self.assertFalse([p for p,b in self.bridge.posts if p=='/control/action'])
        self.assertEqual(posts[0]['intent']['action_id'],self.bridge.action['action_id'])
        return posts[0]
    def assert_no_transition_permit(self):
        self.assertFalse(self.bridge.permit_samples)
        self.assertIsNone((self.dog.capability_lease or {}).get('transition'))
    def test_flint_public_one_request_exact_damage_and_block_success(self):
        result=self.finish(self.submit('flint'));self.assertEqual(result['state'],'succeeded',result)
        post=self.assert_one_exact_request(ITEM_PROFILE)
        self.assertEqual(post['intent']['typed_item_interaction']['kind'],'ignite_nether_portal')
        self.assertEqual(self.bridge.snapshot()['player']['inventory'][0]['damage'],5)
        self.assertEqual(sum(r['block_id']=='minecraft:nether_portal' for r in post['intent']['item_footprint']),6)
        self.assertIsNone(self.client.session()['capability_lease'])
    def test_eye_public_one_request_exact_one_consumption_and_frame_change(self):
        result=self.finish(self.submit('eye'));self.assertEqual(result['state'],'succeeded',result)
        post=self.assert_one_exact_request(ITEM_PROFILE)
        self.assertEqual(self.bridge.snapshot()['player']['inventory'][0]['count'],2)
        self.assertEqual(sum(r['expected_properties']!=r['properties'] for r in post['intent']['item_footprint']),1)
        self.assertIsNone(self.client.session()['capability_lease'])
    def test_last_eye_public_one_use_all_nine_portal_cells(self):
        self.bridge.last_eye=True;result=self.finish(self.submit('eye'));self.assertEqual(result['state'],'succeeded',result)
        post=self.assert_one_exact_request(ITEM_PROFILE)
        self.assertEqual(sum(r['block_id']=='minecraft:end_portal' for r in post['intent']['item_footprint']),9)
    def test_flint_exact_durability_is_independent_of_success_receipt(self):
        self.bridge.outcome='wrong_damage';result=self.finish(self.submit('flint'))
        self.assertNotEqual(result['state'],'succeeded',result);self.assert_one_exact_request(ITEM_PROFILE)
    def test_flint_bool_is_not_exact_observed_damage(self):
        self.bridge.initial_damage=0;self.bridge.outcome='wrong_damage_bool';result=self.finish(self.submit('flint'))
        self.assertNotEqual(result['state'],'succeeded',result);self.assert_one_exact_request(ITEM_PROFILE)
    def test_flint_bool_is_not_exact_post_observation_count_proof(self):
        self.bridge.outcome='post_item_count_bool';result=self.finish(self.submit('flint'))
        self.assertNotEqual(result['state'],'succeeded',result);self.assert_one_exact_request(ITEM_PROFILE)
    def test_eye_exact_consumption_is_independent_of_success_receipt(self):
        self.bridge.outcome='wrong_count';result=self.finish(self.submit('eye'))
        self.assertNotEqual(result['state'],'succeeded',result);self.assert_one_exact_request(ITEM_PROFILE)
    def test_item_exact_block_outcome_is_independent_of_success_receipt(self):
        self.bridge.outcome='wrong_block';result=self.finish(self.submit('flint'))
        self.assertNotEqual(result['state'],'succeeded',result);self.assert_one_exact_request(ITEM_PROFILE)
    def test_item_protected_inventory_change_is_independently_refused(self):
        self.bridge.outcome='wrong_protected_inventory';result=self.finish(self.submit('flint'))
        self.assertNotEqual(result['state'],'succeeded',result);self.assert_one_exact_request(ITEM_PROFILE)
    def test_unknown_item_submit_has_no_replay_or_extra_cancel(self):
        self.bridge.outcome='lost';result=self.finish(self.submit('flint'))
        self.assertEqual(result['state'],'unknown',result);self.assert_one_exact_request(ITEM_PROFILE)
        self.assertFalse([p for p,b in self.bridge.posts if p=='/control/action/cancel'])
        self.assertTrue(self.dog.handoff_latched)
    def test_portal_delayed_source_then_destination_same_owner_original_deadline(self):
        result=self.finish(self.submit('portal'));self.assertEqual(result['state'],'succeeded',result)
        self.assert_one_exact_request(PORTAL_PROFILE)
        self.assertEqual(self.bridge.action['status'],'cancelled');self.assertEqual(self.bridge.action['reason'],'world_transition')
        self.assertIs(self.bridge.action['result']['portal_entry']['transition_eligible'],True)
        self.assertIs(self.bridge.action['result']['portal_entry']['source_portal_contact'],True)
        self.assertEqual(self.bridge.observed_contexts[:4],['source']*4)
        self.assertIn('destination',self.bridge.observed_contexts)
        self.assertTrue(self.bridge.permit_samples)
        self.assertEqual(len({p['deadline'] for p in self.bridge.permit_samples}),1)
        self.assertEqual(len({p['action_id'] for p in self.bridge.permit_samples}),1)
        self.assertEqual(len(set(self.bridge.lease_owner_samples)),1)
        self.assertEqual(self.bridge.lease_owner_samples[0][0],self.posts()[0]['preflight']['owner_id'])
        self.assertEqual(self.bridge.permit_samples[0]['action_id'],self.bridge.action['action_id'])
        self.assertIsNone(self.client.session()['capability_lease'])
    def test_portal_unrelated_cancel_cannot_issue_transition_permit(self):
        self.bridge.outcome='unrelated_cancel';result=self.finish(self.submit('portal'))
        self.assertNotEqual(result['state'],'succeeded',result);self.assert_one_exact_request(PORTAL_PROFILE);self.assert_no_transition_permit()
    def test_portal_forged_original_action_cannot_issue_transition_permit(self):
        self.bridge.outcome='forged';result=self.finish(self.submit('portal'))
        self.assertNotEqual(result['state'],'succeeded',result);self.assert_one_exact_request(PORTAL_PROFILE);self.assert_no_transition_permit()
    def test_portal_unknown_terminal_cannot_issue_transition_permit(self):
        self.bridge.outcome='terminal_unknown';result=self.finish(self.submit('portal'))
        self.assertNotEqual(result['state'],'succeeded',result);self.assert_one_exact_request(PORTAL_PROFILE);self.assert_no_transition_permit()
    def test_portal_without_exact_source_contact_cannot_issue_transition_permit(self):
        self.bridge.outcome='missing_contact';result=self.finish(self.submit('portal'))
        self.assertNotEqual(result['state'],'succeeded',result);self.assert_one_exact_request(PORTAL_PROFILE);self.assert_no_transition_permit()
    def test_portal_post_terminal_proof_forgery_refuses_rebinding(self):
        self.bridge.outcome='post_forged';result=self.finish(self.submit('portal'))
        self.assertNotEqual(result['state'],'succeeded',result);self.assert_one_exact_request(PORTAL_PROFILE)
        self.assertEqual((self.dog.capability_lease or {}).get('context',{}).get('dimension'),'minecraft:overworld')
    def test_portal_post_terminal_bool_integer_forgery_refuses_rebinding(self):
        self.bridge.outcome='post_bool_forged';result=self.finish(self.submit('portal'))
        self.assertNotEqual(result['state'],'succeeded',result);self.assert_one_exact_request(PORTAL_PROFILE)
        self.assertEqual((self.dog.capability_lease or {}).get('context',{}).get('dimension'),'minecraft:overworld')
    def test_portal_proof_forgery_after_first_arrival_cannot_complete_stability(self):
        self.bridge.outcome='arrival_forged';result=self.finish(self.submit('portal',deadline=8))
        self.assertNotEqual(result['state'],'succeeded',result);self.assert_one_exact_request(PORTAL_PROFILE)
        self.assertIn('destination',self.bridge.observed_contexts)
        self.assertEqual(self.bridge.action['result']['portal_entry']['original_native_action_id'],'0'*32)
    def test_portal_bool_forgery_after_first_arrival_cannot_complete_stability(self):
        self.bridge.outcome='arrival_bool_forged';result=self.finish(self.submit('portal',deadline=8))
        self.assertNotEqual(result['state'],'succeeded',result);self.assert_one_exact_request(PORTAL_PROFILE)
        self.assertIn('destination',self.bridge.observed_contexts)
        self.assertIs(type(self.bridge.action['result']['portal_entry']['transition_eligible']),int)
    def test_portal_wrong_server_refuses_rebinding(self):
        self.bridge.outcome='wrong_server';result=self.finish(self.submit('portal'))
        self.assertNotEqual(result['state'],'succeeded',result);self.assert_one_exact_request(PORTAL_PROFILE)
        self.assertEqual((self.dog.capability_lease or {}).get('context',{}).get('dimension'),'minecraft:overworld')
    def test_portal_disconnect_never_replays_or_rebinds(self):
        self.bridge.outcome='disconnect';result=self.finish(self.submit('portal'))
        self.assertNotEqual(result['state'],'succeeded',result);self.assert_one_exact_request(PORTAL_PROFILE)
        self.assertEqual((self.dog.capability_lease or {}).get('context',{}).get('dimension'),'minecraft:overworld')
    def test_portal_original_timeout_expires_without_destination_or_deadline_renewal(self):
        self.bridge.outcome='never_arrive';start=time.monotonic();result=self.finish(self.submit('portal'))
        self.assertNotEqual(result['state'],'succeeded',result);self.assert_one_exact_request(PORTAL_PROFILE)
        self.assertLess(time.monotonic()-start,10)
        self.assertTrue(self.bridge.permit_samples)
        self.assertEqual(len({p['deadline'] for p in self.bridge.permit_samples}),1)
        self.assertEqual(self.dog.reason,'capability_transition_deadline_expired')
    def test_unknown_portal_submit_has_no_replay_cancel_or_permit(self):
        self.bridge.outcome='lost';result=self.finish(self.submit('portal'))
        self.assertEqual(result['state'],'unknown',result);self.assert_one_exact_request(PORTAL_PROFILE);self.assert_no_transition_permit()
        self.assertFalse([p for p,b in self.bridge.posts if p=='/control/action/cancel'])
        self.assertTrue(self.dog.handoff_latched)
    def test_missing_profiles_do_not_advertise_typed_capabilities(self):
        self.bridge.profiles={}
        self.until(lambda:'ignite_portal_local' not in self.backend.describe()['supported_capabilities'])
        self.assertTrue({'ignite_portal_local','insert_end_eye_local','enter_portal_local'}.isdisjoint(self.backend.describe()['supported_capabilities']))
        for kind in ('flint','eye','portal'):
            result=self.submit(kind);self.assertEqual(result['error']['code'],'capability_unavailable',result)
        self.assertFalse(self.posts())
    def test_legacy_profiles_and_mismatched_action_lists_do_not_advertise(self):
        self.bridge.profiles={'block-menu-v1':['interact_block'],'movement-flat-observed-v2':['follow_path'],
            ITEM_PROFILE:['use_item'],PORTAL_PROFILE:['interact_block']}
        self.until(lambda:'ignite_portal_local' not in self.backend.describe()['supported_capabilities'])
        self.assertTrue({'ignite_portal_local','insert_end_eye_local','enter_portal_local'}.isdisjoint(self.backend.describe()['supported_capabilities']))
        for kind in ('flint','eye','portal'):
            result=self.submit(kind);self.assertEqual(result['error']['code'],'capability_unavailable',result)
        self.assertFalse(self.posts())

if __name__=='__main__':unittest.main()
