import tempfile,unittest
from unittest.mock import patch
from test_roundtrip import m,Fake,plan
class Tests(unittest.TestCase):
    @patch.object(m.time,'sleep',lambda _:None)
    def test_explicit_previously_walked_follow_is_plain_bound_break_remains_schema2(self):
        with tempfile.TemporaryDirectory() as d:
            p=plan();p['steps'][0]['known_tunnel']=True;c=Fake(d,'success');r=m.run(c,p)
            self.assertEqual(r['phase'],'COVERED_DISARMED');self.assertTrue(r['work_success'])
            bodies=[x[2] for x in c.calls if x[1]=='/control/action'];walk,cut=bodies[:2]
            self.assertNotIn('capability_guard',walk);self.assertNotIn('known_tunnel',walk)
            for k in ('expected_world_generation','expected_player_uuid','expected_action_session','expected_navigation_epoch','expected_origin'):self.assertIn(k,walk)
            self.assertEqual(cut['capability_guard']['schema_version'],2)
            p=plan();p['steps'][1]['known_tunnel']=True
            with self.assertRaises(m.idle.Refused):m.validate(p)
            s=c.state();normal=m.bind_step(plan()['steps'][0]['action'],s);self.assertIn('capability_guard',normal)
if __name__=='__main__':unittest.main(verbosity=2)
