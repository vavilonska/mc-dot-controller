import copy
import importlib.util
from pathlib import Path
import tempfile
import unittest
p=Path(__file__).with_name('client_tick_combat_trial.py');s=importlib.util.spec_from_file_location('trial',p)
module=importlib.util.module_from_spec(s);s.loader.exec_module(module)
class Queue:
    def __init__(self):self.calls=[];self.results={}
    def submit(self,c):
        self.calls.append(c);rid=str(len(self.calls))
        state={'world':{'world_generation':'w'},'combat_observation_schema_version':1,
               'player':{'uuid':'p','health':20,'using_item':False},'client_action':{'action_session':'s'},
               'nearby':{'entities':[{'uuid':'t','entity_id':9,'type':'minecraft:zombie','alive':True}]}}
        if c['op']=='observe':payload={'state':state,'status':{'held_mappings':[]},'action':{'status':'succeeded'}}
        else:payload={'action':{'status':'succeeded','reason':'target_dead_observed'},'state':state}
        self.results[rid]={'status':'succeeded','result':payload};return rid
    def wait(self,rid,timeout):return copy.deepcopy(self.results[rid])
    def result(self,rid):return copy.deepcopy(self.results.get(rid))
class Checks(unittest.TestCase):
    def test_one_bounded_native_action_with_identity_and_release_observation(self):
        with tempfile.TemporaryDirectory() as t:
            q=Queue();r=module.trial(q,'w','t','iron',Path(t)/'r.json',20000)
            self.assertEqual([x['op'] for x in q.calls],['observe','action','observe'])
            a=q.calls[1];self.assertEqual(a['action'],'combat_entity');self.assertEqual(a['timeout_ms'],20000)
            self.assertEqual(a['expected_action_session'],'s');self.assertEqual(a['expected_player_uuid'],'p')
            self.assertEqual(a['target_entity_id'],9);self.assertTrue(r['input_release_observed'])
    def test_cross_world_does_not_submit_attack(self):
        q=Queue()
        with self.assertRaisesRegex(RuntimeError,'candidate_local_world'):
            module.trial(q,'other','t','iron',Path('/tmp/not-written-native.json'))
        self.assertEqual([x['op'] for x in q.calls],['observe'])
if __name__=='__main__':unittest.main()
