"""Ranged native action binds captured state; owner commands remain immutable."""
import copy
import unittest
from unittest.mock import patch
from watchdog import Watchdog
from test_ranged_tactics import RangedQueue, terrain, witch
from base_watchdog import recovery_context


def mark(o,ready=True,epoch=2):
    o['state']['world'].update(dimension='minecraft:overworld',navigation_guard={
        'schema_version':1,'epoch':epoch,'fresh_binding_required':True,
        'rebind_ready':ready,'stable_ticks':3 if ready else 1,'reason':'position_discontinuity'})
    return o


class WatchdogNavigationBindingTests(unittest.TestCase):
    def prepare(self,ready=True):
        q=RangedQueue();mark(q.obs,ready);d=Watchdog(q,clock=lambda:10)
        d.latest=copy.deepcopy(q.obs);d.observed_at=10
        d.ranged_context={'target_uuid':witch()['uuid'],'identity':recovery_context(q.obs['state'])[0]}
        d.ranged_terrain={'data':terrain(),'received':10}
        q.results['fresh']={'status':'succeeded','result':copy.deepcopy(q.obs)}
        d.rpc={'id':'fresh','kind':'ranged_fresh','started':10}
        return q,d
    def test_ranged_retreat_binds_captured_pose_not_waypoint(self):
        q,d=self.prepare();d.handle_ranged_rpc()
        actions=[c for _,c in q.calls if c['op']=='action'];self.assertEqual(1,len(actions))
        a=actions[0];self.assertEqual(2,a['expected_navigation_epoch'])
        self.assertEqual({'x':.5,'y':64,'z':.5},a['expected_origin'])
        self.assertNotEqual(a['waypoints'][0],a['expected_origin'])
        self.assertEqual('test-action-session',a['expected_action_session'])
    def test_prior_seen_cannot_be_erased_by_a_new_ranged_leg(self):
        q,d=self.prepare();d.observation_received(copy.deepcopy(q.obs),'fresh')
        del q.results['fresh']['result']['state']['world']['navigation_guard']
        d.handle_ranged_rpc()
        self.assertFalse(any(c['op']=='action' for _,c in q.calls))
        self.assertFalse(d.armed)
    def test_malformed_presence_then_missing_still_stops(self):
        for malformed in (None,{},'invalid'):
            q,d=self.prepare();old=copy.deepcopy(q.obs)
            old['state']['world']['navigation_guard']=malformed;d.observation_received(old,'fresh')
            del q.results['fresh']['result']['state']['world']['navigation_guard']
            d.handle_ranged_rpc()
            self.assertFalse(any(c['op']=='action' for _,c in q.calls))
    def test_unready_observation_never_dispatches(self):
        q,d=self.prepare(False);d.handle_ranged_rpc()
        self.assertFalse(any(c['op']=='action' for _,c in q.calls))
    def test_owner_raw_stale_or_half_pairs_are_never_rebound(self):
        for pair in ({'expected_origin':{'x':999,'y':64,'z':999}},
                     {'expected_navigation_epoch':999,'expected_origin':{'x':999,'y':64,'z':999}}):
            q,d=self.prepare();d.rpc=None;d.ranged_context=None;d.ranged_terrain=None
            d.phase='watching';d.latest['state']['nearby']['entities']=[]
            cmd={'op':'action','action':'follow_path','waypoints':[{'x':1,'y':64,'z':0}],
                 '_navigation_defense_epoch':d.defense_epoch,**pair}
            old=copy.deepcopy(cmd)
            self.assertTrue(d.submit_owner('owner-intent',cmd))
            actual=q.calls[-1][1];expected=copy.deepcopy(cmd);expected.pop('_navigation_defense_epoch')
            self.assertEqual(expected,actual);self.assertEqual(old,cmd)
