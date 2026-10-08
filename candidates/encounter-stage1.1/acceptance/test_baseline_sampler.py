import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
p=Path(__file__).with_name('baseline_stationary_combat.py')
s=importlib.util.spec_from_file_location('sampler',p);module=importlib.util.module_from_spec(s);s.loader.exec_module(module)
class Queue:
    def __init__(self): self.calls=[]; self.results={}; self.changed=False
    def session(self): return {'session_id':'different' if self.changed else 'test'}
    def submit(self,c):
        self.calls.append(c); k=str(len(self.calls))
        state={'world':{'world_generation':'w','game_time':10},'screen_open':False,'paused':False,
               'player':{'alive':True,'health':20},'nearby':{'entities':[{'uuid':'z','type':'minecraft:zombie','alive':True,'health':20}]}}
        if c['op']=='observe': r={'state':state,'combat':{'active':False,'reason':'target_dead'}}
        elif c['op']=='combat_stop':r={'input_release_confirmed':True}
        else:r={}
        self.results[k]={'status':'succeeded','result':r};return k
    def wait(self,k,timeout):return copy.deepcopy(self.results[k])
class Checks(unittest.TestCase):
    def test_no_motion_commands_and_exactly_one_stop_on_completion(self):
        with tempfile.TemporaryDirectory() as tmp:
            q=Queue();out=Path(tmp)/'r.json';module.run(q,'w','z','iron',out,duration=.05)
            r=json.loads(out.read_text());self.assertTrue(r['input_release_confirmed'])
            self.assertEqual(sum(c['op']=='combat_stop' for c in q.calls),1)
            self.assertFalse(next(c for c in q.calls if c['op']=='combat_start')['approach'])
            self.assertFalse(any(c['op'] in ('direct','action','walk_to') for c in q.calls))
    def test_wrong_world_never_starts_combat(self):
        q=Queue()
        with self.assertRaisesRegex(RuntimeError,'local_test_world_not_verified'):
            module.run(q,'other','z','iron',Path('/tmp/not-written-baseline.json'))
        self.assertEqual([c['op'] for c in q.calls],['observe'])
    def test_wrong_target_never_starts_combat(self):
        q=Queue()
        with self.assertRaisesRegex(RuntimeError,'exact_test_zombie'):
            module.run(q,'w','other','iron',Path('/tmp/not-written-baseline.json'))
        self.assertEqual([c['op'] for c in q.calls],['observe'])
if __name__=='__main__':unittest.main()
