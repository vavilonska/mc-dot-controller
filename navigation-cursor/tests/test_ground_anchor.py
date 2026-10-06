"""Synthetic geometry only; no real server/player coordinates are fixtures."""
import copy
import tempfile
from pathlib import Path
import unittest
from navigation_cursor import LocalTerrain, Navigator
from test_navigation_cursor import Gateway


def edge_observation(*, x=.48, y=64, z=-.04, support=(0,63,0), eye=True):
    cells=[]
    for bx in range(-2,4):
        for by in range(62,67):
            for bz in range(-2,4):
                solid=(bx,by,bz)==support
                cells.append({'x':bx,'y':by,'z':bz,'status':'loaded','known':True,
                              'collision_known':True,'id_truncated':False,'fluid_truncated':False,
                              'properties_truncated':False,'fluid':'minecraft:empty','hazards':[],
                              'collision_empty':not solid,'full_top_support':solid,
                              'collision_bounds':[0,0,0,1,1,1] if solid else None})
    p={'x':x,'y':y,'z':z,'on_ground':True,'alive':True,'health':20,'food':20}
    if eye:p['eye_position']={'x':x,'y':y+1.62,'z':z}
    return {'state':{'world':{'world_generation':'synthetic','dimension':'overworld'},'player':p},
            'terrain':{'complete':True,'world_generation':'synthetic','cells':cells},
            'action':{'status':'idle'},'combat':{'active':False}}


def cell(o,point):
    return next(c for c in o['terrain']['cells'] if (c['x'],c['y'],c['z'])==point)


class GroundAnchorGeometryTests(unittest.TestCase):
    def test_center_over_air_but_footprint_over_known_support(self):
        o=edge_observation()
        t=LocalTerrain(o)
        self.assertFalse(t.stand((0,64,-1)))
        self.assertEqual(t.ground_anchor(o['state']['player']),(0,64,0))

    def test_east_west_and_corner_edges(self):
        cases=[(.96,.48,(1,63,0),(1,64,0)),(-.03,.48,(0,63,0),(0,64,0)),
               (-.04,-.04,(0,63,0),(0,64,0))]
        for x,z,support,expected in cases:
            o=edge_observation(x=x,z=z,support=support)
            self.assertEqual(LocalTerrain(o).ground_anchor(o['state']['player']),expected)

    def test_narrow_positive_overlap_is_valid_not_exact_touch(self):
        o=edge_observation(z=-.2999)
        self.assertEqual(LocalTerrain(o).ground_anchor(o['state']['player']),(0,64,0))
        o=edge_observation(z=-.3)
        self.assertIsNone(LocalTerrain(o).ground_anchor(o['state']['player']))

    def test_support_at_wrong_height_is_not_current_support(self):
        for support in ((0,62,0),(0,64,0)):
            o=edge_observation(support=support)
            self.assertIsNone(LocalTerrain(o).ground_anchor(o['state']['player']))

    def test_multilevel_neighbor_does_not_hide_correct_height_support(self):
        o=edge_observation()
        low=cell(o,(0,62,-1));low.update(collision_empty=False,full_top_support=True)
        self.assertEqual(LocalTerrain(o).ground_anchor(o['state']['player']),(0,64,0))

    def test_unknown_or_hazard_support_is_not_created(self):
        for change in ({'known':False},{'hazards':['damage']},{'fluid':'minecraft:water'}):
            o=edge_observation();cell(o,(0,63,0)).update(change)
            self.assertIsNone(LocalTerrain(o).ground_anchor(o['state']['player']))

    def test_union_collision_bounds_are_not_solid_top_evidence(self):
        o=edge_observation();cell(o,(0,63,0))['full_top_support']=False
        self.assertIsNone(LocalTerrain(o).ground_anchor(o['state']['player']))

    def test_full_top_at_partial_collision_height_is_not_integer_anchor(self):
        o=edge_observation();cell(o,(0,63,0))['collision_bounds']=[0,0,0,1,.5,1]
        self.assertIsNone(LocalTerrain(o).ground_anchor(o['state']['player']))

    def test_unknown_or_blocked_swept_headroom_rejects_normalization(self):
        for change in ({'known':False},{'collision_empty':False}):
            o=edge_observation();cell(o,(0,65,-1)).update(change)
            self.assertIsNone(LocalTerrain(o).ground_anchor(o['state']['player']))

    def test_actual_bounding_box_precedes_vanilla_width_assumption(self):
        o=edge_observation(z=-.4,eye=False);p=o['state']['player']
        p['bounding_box']={'min':{'x':-.02,'y':64,'z':-.9},
                           'max':{'x':.98,'y':65.8,'z':.1}}
        self.assertEqual(LocalTerrain(o).ground_anchor(p),(0,64,0))

    def test_unknown_pose_or_airborne_or_fractional_stand_is_not_guessed(self):
        for field,value in (('on_ground',False),('y',64.5),('eye_position',{'y':64.4})):
            o=edge_observation();o['state']['player'][field]=value
            self.assertIsNone(LocalTerrain(o).ground_anchor(o['state']['player']))
        o=edge_observation(eye=False)
        self.assertIsNone(LocalTerrain(o).ground_anchor(o['state']['player']))

    def test_actual_bbox_upper_extent_is_included_in_sweep(self):
        o=edge_observation(y=64.03,eye=False);p=o['state']['player']
        p['bounding_box']={'min':{'x':.18,'y':64.03,'z':-.34},
                           'max':{'x':.78,'y':66.02,'z':.26}}
        cell(o,(0,66,-1))['known']=False
        self.assertIsNone(LocalTerrain(o).ground_anchor(p))

    def test_null_eye_position_fails_closed_without_exception(self):
        o=edge_observation();o['state']['player']['eye_position']=None
        self.assertIsNone(LocalTerrain(o).ground_anchor(o['state']['player']))

    def test_crouching_pose_retains_observed_horizontal_footprint(self):
        o=edge_observation();o['state']['player']['eye_position']['y']=65.27
        self.assertEqual(LocalTerrain(o).ground_anchor(o['state']['player']),(0,64,0))


class GroundAnchorNavigatorTests(unittest.TestCase):
    def setUp(self):
        self.gateway=Gateway();self.gateway.state['implementation']='native-defense-watchdog-v5'
        self.nav=Navigator(self.gateway)
        self.goal=(0,0)

    def observe(self,o):
        self.assertEqual(self.nav.tick(self.goal)['reason'],'observe_submitted')
        self.gateway.finish(result=o)
        return self.nav.tick(self.goal)

    def terminal(self,status='succeeded'):
        self.gateway.finish(status)
        return self.nav.tick(self.goal)

    def test_small_guarded_centering_then_actual_arrival(self):
        r=self.observe(edge_observation())
        self.assertEqual(r['status'],'pending')
        command=self.gateway.commands[-1][1]
        self.assertEqual(command['waypoints'],[{'x':.5,'y':64,'z':.5,'jump':False}])
        self.assertEqual(command['_navigation_defense_epoch'],0)
        self.assertEqual(self.nav.data['pending']['purpose'],'ground_anchor')
        self.terminal()
        r=self.observe(edge_observation(z=.2))
        self.assertEqual(r['status'],'complete')

    def test_three_unknown_support_observations_stop_infinite_read_loop(self):
        o=edge_observation();cell(o,(0,63,0))['known']=False
        for i in range(3):r=self.observe(o)
        self.assertEqual(r['reason'],'grounded_support_unresolved_after_3_observations')
        self.assertEqual([c['op'] for _,c in self.gateway.commands],['observe']*3)
        count=len(self.gateway.commands)
        self.nav.tick(self.goal)
        self.assertEqual(len(self.gateway.commands),count)

    def test_two_centering_attempts_without_observed_movement_stop(self):
        o=edge_observation()
        for i in range(2):
            self.assertEqual(self.observe(o)['status'],'pending')
            self.terminal()
        r=self.observe(o)
        self.assertEqual(r['reason'],'ground_anchor_no_progress_after_2_attempts')
        self.assertEqual(sum(c['op']=='action' for _,c in self.gateway.commands),2)

    def test_normalization_preserves_pending_id_across_helper_reload(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'route.json'
            self.nav=Navigator(self.gateway,path)
            self.observe(edge_observation())
            rid=self.nav.data['pending']['id'];count=len(self.gateway.commands)
            self.nav=Navigator(self.gateway,path)
            self.assertEqual(self.nav.tick(self.goal)['request_id'],rid)
            self.assertEqual(len(self.gateway.commands),count)
            self.assertEqual(self.nav.data['anchor_attempts'],1)

    def test_combat_cancel_requires_observation_and_does_not_exhaust_centering(self):
        self.observe(edge_observation())
        self.gateway.state.update(state='busy',phase='combat',defense_epoch=1)
        self.terminal('cancelled')
        self.assertEqual(self.nav.tick(self.goal)['status'],'waiting')
        self.gateway.state.update(state='ready',phase='watching')
        self.observe(edge_observation())
        self.assertEqual(self.nav.data['anchor_attempts'],1)
        self.assertEqual(self.gateway.commands[-1][1]['_navigation_defense_epoch'],1)

    def test_centering_cannot_erase_failed_or_stalled_navigation_edge(self):
        for status in ('failed','succeeded'):
            self.setUp()
            self.goal=(2,0)
            self.nav.data['route']={'nodes':[(0,64,0),(1,64,0),(2,64,0)],'index':1}
            self.nav.data['last_action']={'status':status,'end_index':2,'purpose':'navigation'}
            self.observe(edge_observation())
            self.terminal()
            o=edge_observation(z=.25)
            for x in (1,2):cell(o,(x,63,0)).update(collision_empty=False,full_top_support=True)
            r=self.observe(o)
            self.assertEqual(r['status'],'blocked')
            self.assertEqual(self.nav.data['forbidden'],[[[0,64,0],[1,64,0]]])
            self.assertEqual(self.nav.data['replans'],1)

    def test_relocalization_retains_tail_goal_without_blacklisting_next_edge(self):
        self.goal=(2,0)
        self.nav.data['route']={'nodes':[(0,64,0),(1,64,0),(2,64,0)],'index':1}
        self.observe(edge_observation())
        self.terminal()
        o=edge_observation(z=.25)
        for x in (1,2):cell(o,(x,63,0)).update(collision_empty=False,full_top_support=True)
        r=self.observe(o)
        self.assertEqual(r['status'],'pending')
        self.assertEqual(self.nav.route.nodes[-1],(2,64,0))
        self.assertEqual(self.nav.data['forbidden'],[])
        self.assertEqual(self.nav.data['replans'],0)

if __name__=='__main__':unittest.main()
