"""Cold geometry is only a negative planning fixture, never native authority."""
from pathlib import Path
import unittest
from interaction_controller.legacy import strict_json,Refused
from interaction_controller.policy import gate
from test_interaction import observation,request,OWNER

COLD=Path('/workspace/scratch/5f333e5a575b/mdc-recovery-interaction-plan-r1/COLD-CURRENT-150-CELLS-FIXTURE.json')

@unittest.skipUnless(COLD.is_file(),'authorized cold planning fixture unavailable')
class ColdPlanTests(unittest.TestCase):
    def test_actual_initial_cold_geometry_cannot_qualify_jump(self):
        cold=strict_json(COLD.read_bytes());self.assertEqual(cold['base_block'],[-636,59,35]);self.assertEqual(len(cold['cells']),150)
        # Construct a planning-only model at the cold base, not an actual observe.
        obs=observation();obs['pose']['z']=35.5;obs['player_bbox'].update(min_z=35.2,max_z=35.8)
        obs['local_blocks']=[dict(dx=c['dx'],dy=c['dy'],dz=c['dz'],loaded=True,id=c['state']['Name'],collision=c['state']['Name']!='minecraft:air',fluid='minecraft:empty') for c in cold['cells']]
        req=request('move');req['jump_first']=True
        with self.assertRaises(Refused):gate(obs,req,OWNER,{})
        self.assertIn('NOT native',cold['provenance'])

if __name__=='__main__':unittest.main()
