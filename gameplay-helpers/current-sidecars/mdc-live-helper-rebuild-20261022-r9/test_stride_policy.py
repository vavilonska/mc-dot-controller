"""Focused pure stride/geometry tests; exact original C8 gate, no native I/O."""
import copy,math,unittest
from test_terrain_planner import observation,cell,solid,production_gate
from terrain_planner import TerrainPlanner,manual_target
from stride_policy import redirected,arrived,stride
class Tests(unittest.TestCase):
 def test_original_input_and_sample_limits(self):
  for distance in (.2,.3,.4,.6,1.,1.5,2.):
   speed,samples=stride(distance)
   self.assertLessEqual(speed,1);self.assertLessEqual(samples,8)
  self.assertEqual(stride(2),(1.,8));self.assertEqual(stride(1),(1.,6))
 def test_observed_flat_two_cell_stage_original_gate(self):
  o=observation();p=TerrainPlanner(stop_x=-100);s=p.choose(o,'flat.1')
  self.assertEqual(s['target']['x'],-1.5);self.assertEqual(s['max_samples'],8)
  self.assertAlmostEqual(s['forward'],1);production_gate(o,s)
  restored=TerrainPlanner.restore(p.snapshot());self.assertEqual(restored.snapshot(),p.snapshot())
 def test_blocked_long_target_falls_back_to_observed_one_cell(self):
  o=observation();solid(cell(o,-2,0,0));solid(cell(o,-2,1,0))
  s=TerrainPlanner(stop_x=-100).choose(o,'flat.2')
  self.assertEqual(s['target']['x'],-.5);production_gate(o,s)
 def test_long_target_never_exceeds_two_meters(self):
  o=observation(x=.8);s=TerrainPlanner(stop_x=-100).choose(o,'flat.3')
  self.assertLessEqual(abs(s['target']['x']-o['pose']['x']),2)
 def test_redirect_retains_pending_budget_and_target(self):
  o=observation();s=manual_target(o,'old.stage',dict(x=-.5,y=48.,z=.5))
  s['max_samples']=4;s['max_moves']=8;before=copy.deepcopy(s)
  new,samples=redirected(o,s)
  self.assertEqual(s,before);self.assertEqual(new['id'],s['id']);self.assertEqual(new['target'],s['target'])
  self.assertEqual(new['max_moves'],8);self.assertLessEqual(samples,4)
  self.assertEqual(new['max_samples'],4);self.assertAlmostEqual(new['forward'],1.)
 def test_ordinary_settled_landing_not_center_convergence(self):
  o=observation();s=manual_target(o,'arrival',dict(x=-.5,y=48.,z=.5))
  actual=observation(x=-.28)
  self.assertTrue(arrived(actual,s));self.assertFalse(arrived(observation(x=-.24),s))
  self.assertFalse(arrived(observation(x=-.5,y=47.),s))
 def test_jump_keeps_original_half_input_eight_and_strict_arrival(self):
  o=observation(heights={(x,z):(49. if x<0 else 48.) for x in range(-2,3) for z in range(-2,3)})
  s=manual_target(o,'jump',dict(x=-.5,y=49.,z=.5),jump=True)
  new,n=redirected(o,s);self.assertAlmostEqual(new['forward'],.5)
  self.assertEqual(s['max_samples'],8);self.assertEqual(s['max_moves'],1)
  self.assertFalse(arrived(observation(x=-.28,y=49.),s))
 def test_two_cell_blocked_state_roundtrip(self):
  p=TerrainPlanner(stop_x=-100);s=p.choose(observation(),'blocked.long');p.blocked(s)
  self.assertEqual(TerrainPlanner.restore(p.snapshot()).snapshot(),p.snapshot())
if __name__=='__main__':unittest.main(verbosity=2)
