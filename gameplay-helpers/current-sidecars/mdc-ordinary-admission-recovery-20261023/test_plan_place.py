import copy,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from test_roundtrip import m,Fake,plan

def placeplan():
    p=plan();p['steps'][1]['action']=dict(action='place_block',target=dict(x=3,y=60,z=0),support=dict(x=3,y=59,z=0),face='up',hotbar_slot=6,timeout_ms=5000,sneak=True,jump=False,expected_block_id='minecraft:cobbled_deepslate');return p
class PlaceFake(Fake):
    def request(self,method,path,body=None):
        if path=='/control/action' and body['action']=='place_block' and body['target']['x']==3:
            assert 'capability_guard' not in body and 'expected_block_id' not in body
            assert body['hotbar_slot']==6 and body['expected_origin']==m.idle.point(self.s['player']) and body['expected_navigation_epoch']==7
            if self.mode=='lost':
                self.calls.append((method,path,copy.deepcopy(body)));self.records[body['action_id']]=copy.deepcopy(body)
                self.note('one_shot_request',method=method,path=path,body=body);raise TimeoutError('lost plain place response')
        if path.startswith('/control/action/status'):
            uid=path.split('=')[1];b=self.records[uid]
            if b['action']=='place_block' and b['target']['x']==3:
                self.polls[uid]=self.polls.get(uid,0)+1
                if self.mode=='lost' and self.polls[uid]==1:return 200,dict(action_id=uid,action_session='session',status='running')
                code,o=super().request(method,path,body);o['result'].pop('input_release_confirmed',None)
                if self.mode=='failed':o['status']='failed';o['reason']='support_face_not_in_reach_or_visible';o['result']={}
                return code,o
        return super().request(method,path,body)
class Tests(unittest.TestCase):
    @patch.object(m.time,'sleep',lambda _:None)
    def test_place_success_then_return_two_doors_actual_payload_and_note(self):
        with tempfile.TemporaryDirectory() as d:
            c=PlaceFake(d,'success');r=m.run(c,placeplan());self.assertEqual(r['phase'],'COVERED_DISARMED');self.assertTrue(r['work_success'])
            self.assertEqual(len([x for x in c.calls if x[1]=='/control/action']),5)
            rows=[json.loads(x) for x in Path(d,'events.jsonl').read_text().splitlines()];self.assertTrue(any(x['event']=='one_shot_request' and x['body'].get('target',{}).get('x')==3 for x in rows))
    @patch.object(m.time,'sleep',lambda _:None)
    def test_place_known_failed_releases_and_returns_without_retry(self):
        with tempfile.TemporaryDirectory() as d:
            c=PlaceFake(d,'failed');r=m.run(c,placeplan());self.assertEqual(r['phase'],'COVERED_DISARMED');self.assertFalse(r['work_success']);self.assertEqual(r['actions'][1]['terminal']['status'],'failed')
            self.assertEqual(len([x for x in c.calls if x[1]=='/control/action' and x[2].get('target',{}).get('x')==3]),1)
    @patch.object(m.time,'sleep',lambda _:None)
    def test_place_lost_response_reads_original_running_terminal_no_repeat_cancel(self):
        with tempfile.TemporaryDirectory() as d:
            c=PlaceFake(d,'lost');r=m.run(c,placeplan());self.assertEqual(r['phase'],'COVERED_DISARMED');self.assertTrue(r['work_success']);self.assertFalse(c.cancelled)
            starts=[x[2] for x in c.calls if x[1]=='/control/action'];self.assertEqual(len(starts),len({b['action_id'] for b in starts}));self.assertEqual(len([b for b in starts if b.get('target',{}).get('x')==3]),1)
if __name__=='__main__':unittest.main(verbosity=2)
