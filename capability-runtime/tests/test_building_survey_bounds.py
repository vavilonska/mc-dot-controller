"""Complete synthetic terrain bounds/provenance tests; no game or physics claim."""
from copy import deepcopy
import unittest
from mdc_skills import building_v3 as b
from mdc_skills.core import SkillError
from building_controller.model import Pos
from test_building_v3 import OrientedRuntime, blueprint, stair, door


def fixture():
    return blueprint([((13,64,27),'minecraft:oak_stairs',stair()),
        ((14,64,27),'minecraft:oak_slab',dict(type='bottom',waterlogged='false')),
        ((15,64,27),'minecraft:oak_log',dict(axis='y')),
        ((16,64,27),'minecraft:oak_door',door(hinge='right')),
        ((16,65,27),'minecraft:oak_door',door('upper',hinge='right'))])


class SizedRuntime(OrientedRuntime):
    def __init__(self):
        super().__init__()
        p=self.state['player'];p.update(x=12.536393768,y=64.,z=25.5)
        p['eye_position']=dict(x=p['x'],y=65.62,z=p['z'])
        self.requests=[]; self.patch=lambda s:s
    def survey(self, **kwargs):
        self.requests.append(kwargs)
        return self.patch(super().survey(**kwargs))


class BuildingSurveyBoundsTests(unittest.TestCase):
    def runtime(self):
        r=SizedRuntime(); self.addCleanup(r.close); return r
    def test_initial_and_work_minimum_real_requested_bounds(self):
        r=self.runtime(); s=b.planning_survey(r,fixture())
        self.assertEqual(r.requests,[dict(radius=5,vertical=3,entity_radius=48)])
        self.assertEqual(len(s.terrain['cells']),847)
        self.assertEqual(s.terrain['origin'],dict(x=12,y=64,z=25))
        r.state['player'].update(x=14.5);r.state['player']['eye_position']['x']=14.5
        s=b.planning_survey(r,fixture())
        self.assertEqual(r.requests[-1],dict(radius=3,vertical=3,entity_radius=48))
        self.assertEqual(len(s.terrain['cells']),343)
        self.assertEqual(r.actions,[])
    def test_access_and_cavity_shell_extend_actual_request(self):
        r=self.runtime(); spec=blueprint([((13,64,27),'minecraft:oak_planks',{})],
            clearance=[dict(position=dict(x=18,y=64,z=27),purpose='cavity')],
            light_checks=[dict(position=dict(x=17,y=65,z=27),min_block_light=0)],
            access_points=[dict(x=20,y=64,z=25)])
        s=b.planning_survey(r,spec)
        self.assertEqual(s.terrain['radius'],9)
        self.assertEqual(s.terrain['vertical'],3)
    def test_region_shell_not_only_declared_sparse_targets(self):
        r=self.runtime(); spec=fixture(); spec['region']['max']['x']=22
        spec=b.seal_blueprint(spec);s=b.planning_survey(r,spec)
        self.assertEqual(s.terrain['radius'],11)
    def test_outside_bounds_rejects_before_survey_or_effects(self):
        r=self.runtime(); spec=blueprint([((31,64,27),'minecraft:oak_planks',{})])
        with self.assertRaisesRegex(SkillError,'outside_bounded_survey'):b.planning_survey(r,spec)
        self.assertEqual(r.requests,[]);self.assertEqual(r.actions,[])
    def test_same_tick_subcell_drift_rejects_without_second_survey(self):
        r=self.runtime()
        def changed(s):
            s.player['x']+=.01; s.tick=101; s.state['world']['game_time']=101; return s
        r.patch=changed
        with self.assertRaisesRegex(SkillError,'context_epoch_or_position'):b.planning_survey(r,fixture())
        self.assertEqual(len(r.requests),1);self.assertEqual(r.actions,[])
    def test_context_epoch_origin_and_bounds_changes_reject(self):
        for kind in ('context','epoch','origin','radius','vertical','tick'):
            with self.subTest(kind=kind):
                r=self.runtime()
                def changed(s):
                    if kind=='context': s.context=('changed',)+s.context[1:]
                    elif kind=='epoch':s.state['world']['navigation_guard']['epoch']+=1
                    elif kind=='origin':s.terrain['origin']['x']+=1
                    elif kind in ('radius','vertical'):s.terrain[kind]+=1
                    else:s.tick=-1
                    return s
                r.patch=changed
                with self.assertRaises(SkillError):b.planning_survey(r,fixture())
                self.assertEqual(r.actions,[])
    def test_missing_or_unknown_boundary_support_rejects(self):
        for remove in (True,False):
            r=self.runtime()
            def changed(s):
                cells=s.terrain['cells'];cell=next(c for c in cells if (c['x'],c['y'],c['z'])==(17,63,28))
                if remove:cells.remove(cell)
                else:cell['known']=False
                return s
            r.patch=changed
            with self.assertRaisesRegex(SkillError,'incomplete|required_cell_unknown'):b.planning_survey(r,fixture())
            self.assertEqual(r.actions,[])
    def test_unknown_collision_and_duplicate_rows_reject(self):
        for duplicate in (True,False):
            r=self.runtime()
            def changed(s):
                if duplicate:s.terrain['cells'][-1]=deepcopy(s.terrain['cells'][0])
                else:
                    next(c for c in s.terrain['cells'] if (c['x'],c['y'],c['z'])==(16,66,27))['collision_known']=False
                return s
            r.patch=changed
            with self.assertRaises(SkillError):b.planning_survey(r,fixture())
            self.assertEqual(r.actions,[])
    def test_survey_does_not_gain_freshness_or_filter_payload(self):
        r=self.runtime();captured=[]
        r.patch=lambda s:(captured.append(s) or s)
        s=b.planning_survey(r,fixture())
        self.assertIs(s,captured[0]);self.assertEqual(s.request_id,'survey-1')
        self.assertGreater(s.terrain['capture_finished_mono']-s.terrain['capture_started_mono'],.8)
        with self.assertRaises(SkillError):b._terrain(s)
    def test_same_position_enlarged_or_malformed_returned_body_rejects(self):
        for mode in ('enlarged','malformed','airborne'):
            r=self.runtime()
            def changed(s):
                if mode=='enlarged':s.player['bounding_box']['min']['x']-=8
                elif mode=='malformed':s.player['bounding_box']['max']['y']=None
                else:s.player['on_ground']=False
                return s
            r.patch=changed
            with self.assertRaises(SkillError):b.planning_survey(r,fixture())
            self.assertEqual(len(r.requests),1);self.assertEqual(r.actions,[])

    def test_malformed_body_and_guard_reject_before_survey(self):
        r=self.runtime();r.state['world']['navigation_guard']['epoch']=True
        with self.assertRaises(SkillError):b.planning_survey(r,fixture())
        self.assertEqual(r.requests,[])

if __name__=='__main__':unittest.main()
