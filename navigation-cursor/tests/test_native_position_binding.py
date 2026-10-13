"""Native binding, not watchdog defense epochs; synthetic wire observations only."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from test_navigation_cursor import observation, Gateway
from navigation_cursor import Navigator

NODES = [(x, 64, z) for x in range(8) for z in range(3)]
GOAL = (7, 64, 0)


def observed(position=(0,64,0), epoch=3, ready=True):
    o = observation(position, NODES)
    s = o['state']
    s['world'].update(game_time=100, navigation_guard={'schema_version':1, 'epoch':epoch,
        'fresh_binding_required':True, 'rebind_ready':ready, 'stable_ticks':3 if ready else 1,
        'reason':'position_discontinuity'})
    s['player']['uuid']='player-a'
    s['client_action']={'action_session':'native-session'}
    return o


def admission(reason='navigation_origin_changed', status=409, uncertain=False):
    return {'schema_version':1, 'http_status':status, 'admitted':False,
            'uncertain':uncertain, 'reason':reason}


def native_cancel():
    return {'action_schema_version':1,'action_id':'native-cancel-id','action_session':'native-session',
            'status':'cancelled','reason':'position_discontinuity_rebind_required',
            'result':{'input_release_confirmed':True}}


class NativeBindingCursorTests(unittest.TestCase):
    def navigator(self, **kwargs):
        g = Gateway(); n = Navigator(g, **kwargs)
        n.data.update(target=list(GOAL), gateway_session='gateway-a', observation_epoch=0)
        return g,n
    def fresh(self,g,n,o):
        self.assertEqual('observe_submitted', n.tick(GOAL)['reason'])
        g.finish(result=o)
        return n.tick(GOAL)
    def terminal(self,g,n,**fields):
        g.finish(**fields)
        return n.tick(GOAL)
    def test_both_adaptive_and_explicit_prefix_bind_exact_planning_pose(self):
        for size in (None,2):
            g,n=self.navigator(slice_size=size);o=observed()
            o['state']['player']['x']=.613
            self.assertEqual('pending',n.process_observation(o)['status'])
            body=g.commands[-1][1]
            self.assertEqual(3,body['expected_navigation_epoch'])
            self.assertEqual({'x':.613,'y':64,'z':.5},body['expected_origin'])
            self.assertEqual('world-a',body['expected_world_generation'])
            self.assertEqual('player-a',body['expected_player_uuid'])
            self.assertEqual('native-session',body['expected_action_session'])
            self.assertEqual(0,body['_navigation_defense_epoch'])
            self.assertEqual(1,n.route.index)
            self.assertEqual(8,len(n.route.nodes))
    def test_unready_preserves_route_anchor_budget_and_does_not_submit(self):
        g,n=self.navigator();o=observed(ready=False)
        n.data.update(anchor_attempts=1, replans=2, route={'nodes':[(x,64,0) for x in range(8)],'index':2})
        before=copy.deepcopy(n.data)
        for _ in range(5):self.assertEqual('waiting', n.process_observation(o)['status'])
        self.assertEqual([],g.commands)
        for key in ('anchor_attempts','replans','route','pending','forbidden'):
            self.assertEqual(before[key],n.data[key])
    def test_guard_presence_survives_wait_and_checkpoint_reload(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'cursor.json';g,n=self.navigator(checkpoint=p)
            self.assertEqual('waiting',n.process_observation(observed(ready=False))['status'])
            n=Navigator(g,p)
            o=observed();del o['state']['world']['navigation_guard']
            self.assertEqual('blocked', self.fresh(g,n,o)['status'])
            self.assertFalse(any(c['op']=='action' for _,c in g.commands))
    def test_malformed_epoch_readiness_and_origin_fail_without_action(self):
        mutations=[('epoch',True),('epoch',1.5),('epoch',2**53),('epoch','3'),('schema_version',2),
                   ('rebind_ready',1),('fresh_binding_required',None),('stable_ticks',True)]
        for field,value in mutations:
            with self.subTest(field=field,value=value):
                g,n=self.navigator();o=observed();o['state']['world']['navigation_guard'][field]=value
                self.assertEqual('blocked',self.fresh(g,n,o)['status'])
                self.assertFalse(any(c['op']=='action' for _,c in g.commands))
        for v in (float('nan'),True,'0'):
            g,n=self.navigator();o=observed();o['state']['player']['x']=v
            self.assertEqual('blocked',self.fresh(g,n,o)['status'])
    def test_known_no_effect_409_replans_once_without_blacklisting(self):
        g,n=self.navigator(slice_size=2);n.process_observation(observed())
        original=copy.deepcopy(g.commands[-1]);rid=n.data['pending']['id']
        self.assertEqual('progress',self.terminal(g,n,status='failed',reason='navigation_origin_changed',
                         action_admission=admission(),action=None,action_id=None,cancellation=None)['status'])
        self.assertEqual('pending',self.fresh(g,n,observed(epoch=4))['status'])
        self.assertEqual([],n.data['forbidden']);self.assertEqual(1,n.data['replans'])
        self.assertNotEqual(rid,n.data['pending']['id']);self.assertEqual(original,g.commands[0])
        self.assertEqual(4,g.commands[-1][1]['expected_navigation_epoch'])
    def test_native_rejection_marks_capability_before_any_supported_observation(self):
        g,n=self.navigator();o=observed();del o['state']['world']['navigation_guard']
        n.process_observation(o)
        self.terminal(g,n,status='failed',reason='navigation_rebind_required',
                      action_admission=admission('navigation_rebind_required'),action=None,action_id=None,cancellation=None)
        self.assertEqual('blocked',self.fresh(g,n,o)['status'])
        self.assertEqual(1,sum(c['op']=='action' for _,c in g.commands))
    def test_reason_text_400_identity_and_malformed_evidence_do_not_recover(self):
        cases=[{'reason':'navigation_origin_changed'},
               {'reason':'expected_origin_required','action_admission':admission('expected_origin_required',400)},
               {'reason':'world_generation_changed','action_admission':admission('world_generation_changed')},
               {'reason':'navigation_origin_changed','action_admission':admission(uncertain=True)},
               {'reason':'navigation_origin_changed','action_admission':{**admission(),'admitted':0}},
               {'reason':'navigation_origin_changed','action_admission':admission(status=500)}]
        for fields in cases:
            with self.subTest(fields=fields):
                g,n=self.navigator();n.process_observation(observed())
                result=self.terminal(g,n,status='failed',**fields)
                self.assertEqual('blocked',result['status'])
                for _ in range(3):n.tick(GOAL)
                self.assertEqual(1,sum(c['op']=='action' for _,c in g.commands))
    def test_uncertainty_and_release_latch_win_even_with_admission_metadata(self):
        for status,extra in [('uncertain',{}),('failed',{'action':{'reason':'input_release_unconfirmed',
                                                        'result':{'input_release_confirmed':False}}})]:
            g,n=self.navigator();n.process_observation(observed());rid=n.data['pending']['id']
            r=self.terminal(g,n,status=status,reason='navigation_origin_changed',action_admission=admission(),**extra)
            self.assertEqual('blocked',r['status']);self.assertEqual(rid,n.data['pending']['id'])
            self.assertEqual(1,sum(c['op']=='action' for _,c in g.commands))
    def test_discontinuity_consumes_budget_not_free_combat_preemption(self):
        g,n=self.navigator(max_replans=1,slice_size=2)
        n.process_observation(observed())
        self.terminal(g,n,status='cancelled',reason='position_discontinuity_rebind_required',
                      action=native_cancel())
        self.assertEqual('pending',self.fresh(g,n,observed(epoch=4))['status'])
        self.assertEqual(1,n.data['replans']);self.assertEqual([],n.data['forbidden'])
        self.assertEqual('blocked',self.terminal(g,n,status='cancelled',reason='position_discontinuity_rebind_required',action=native_cancel())['status'])
        self.assertEqual('blocked',n.tick(GOAL)['status'])
        self.assertEqual(2,sum(c['op']=='action' for _,c in g.commands))
    def test_guarded_player_or_native_session_change_stops_same_world(self):
        for section,key in [('player','uuid'),('client_action','action_session')]:
            g,n=self.navigator();n.process_observation(observed())
            self.terminal(g,n,status='succeeded')
            o=observed((2,64,0));o['state'][section][key]='changed'
            self.assertEqual('blocked',self.fresh(g,n,o)['status'])
            self.assertEqual(1,sum(c['op']=='action' for _,c in g.commands))
    def test_discontinuity_to_old_leg_endpoint_does_not_reset_budget(self):
        g,n=self.navigator(max_replans=1);n.data['target']=[20,64,0]
        n.process_observation(observed())
        g.finish(status='cancelled',reason='position_discontinuity_rebind_required',action=native_cancel())
        self.assertEqual('progress',n.tick((20,64,0))['status'])
        o=observed((7,64,0),epoch=4)
        # No additional observed terrain can reach the global goal. The old local
        # endpoint may finish, but must not reset the discontinuity charge.
        n.process_observation(o)
        self.assertEqual(1,n.data['replans'])

    def test_ground_anchor_uses_edge_pose_and_unready_does_not_spend_attempt(self):
        from test_ground_anchor import edge_observation
        g,n=self.navigator();o=edge_observation()
        source=observed()['state']
        o['state']['world']['navigation_guard']=source['world']['navigation_guard']
        o['state']['player']['uuid']='player-a';o['state']['client_action']=source['client_action']
        self.assertEqual('pending',n.process_observation(o)['status'])
        body=g.commands[-1][1]
        self.assertEqual({'x':.48,'y':64,'z':-.04},body['expected_origin'])
        self.assertEqual({'x':.5,'y':64,'z':.5,'jump':False},body['waypoints'][0])
        self.assertEqual(1,n.data['anchor_attempts'])
        rid=n.data['pending']['id'];g.finish(status='failed',reason='navigation_origin_changed',action_admission=admission())
        self.assertEqual('progress',n.tick(GOAL)['status'])
        self.assertEqual(0,n.data['anchor_attempts'])
        o['state']['world']['navigation_guard'].update(rebind_ready=False,stable_ticks=1)
        self.assertEqual('waiting',n.process_observation(o)['status'])
        self.assertEqual(0,n.data['anchor_attempts'])
        self.assertEqual(1,sum(c['op']=='action' for _,c in g.commands))

    def test_final_state_running_cannot_be_hidden_by_older_outer_idle(self):
        g,n=self.navigator();o=observed();o['state']['client_action']['status']='running'
        self.assertEqual('waiting',n.process_observation(o)['status'])
        self.assertEqual([],g.commands)

    def test_malformed_result_shapes_stop_with_saved_pending_id(self):
        for response in ([], 2, {'status':{}}, {'status':'failed','reason':[]},
                         {'status':'failed','reason':'navigation_origin_changed','action_admission':{'reason':[]}}):
            g,n=self.navigator();n.process_observation(observed());rid=n.data['pending']['id']
            g.results[rid]=response
            self.assertEqual('blocked',n.tick(GOAL)['status'])
            self.assertEqual(rid,n.data['pending']['id'])
            self.assertEqual(1,len(g.commands))

    def test_top_uncertainty_beats_409_no_effect_metadata(self):
        for key in ('post_uncertain','uncertain','unknown_outcome'):
            for value in (True,None,1,'false'):
                g,n=self.navigator();n.process_observation(observed());rid=n.data['pending']['id']
                r=self.terminal(g,n,status='failed',reason='navigation_origin_changed',action_admission=admission(),**{key:value})
                self.assertEqual('blocked',r['status']);self.assertEqual(rid,n.data['pending']['id'])
                self.assertEqual(1,sum(c['op']=='action' for _,c in g.commands))

    def test_new_discontinuity_requires_original_native_confirmed_release(self):
        partial=native_cancel();partial['result']={}
        contradictory=native_cancel();contradictory['reason']='different'
        for receipt in (None,{},partial,contradictory):
            g,n=self.navigator();n.process_observation(observed());rid=n.data['pending']['id']
            r=self.terminal(g,n,status='cancelled',reason='position_discontinuity_rebind_required',action=receipt)
            self.assertEqual('input_release_unconfirmed_requires_operator',r['reason'])
            self.assertEqual(rid,n.data['pending']['id'])
            for _ in range(3):n.tick(GOAL)
            self.assertEqual(1,sum(c['op']=='action' for _,c in g.commands))
