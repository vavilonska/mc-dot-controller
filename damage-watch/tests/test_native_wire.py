"""Actual production Recorder+Codec output from explicitly synthetic Java inputs."""
from pathlib import Path
import tempfile
import unittest
from damage_watch.schema import validate,MAX_RESPONSE
from damage_watch.strict import strict_json
from damage_watch.watcher import Reply,watch
from test_watch import Clock

FIXTURES=Path(__file__).parent/'fixtures'

class WireTests(unittest.TestCase):
    def test_every_production_payload_closed_and_bounded(self):
        for p in FIXTURES.glob('*.json'):
            if p.name=='ORIGIN.json':continue
            raw=p.read_bytes();self.assertLessEqual(len(raw),MAX_RESPONSE);validate(strict_json(raw))
    def test_native_early_damage_stops_before_client_ready_raw_exact(self):
        raw=(FIXTURES/'damage-before-client.json').read_bytes();v=validate(strict_json(raw));self.assertIsNone(v['client_first']);self.assertGreater(v['damage_total'],0)
        owner='11111111-1111-4111-8111-111111111111';player=v['damage_events'][0]['player_uuid'];pose=v['damage_events'][0]['position']
        class Transport:
            calls=0
            def get(self,path,*,timeout_s):self.calls+=1;return Reply(200,raw,True)
        t=Transport();clock=Clock()
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'capture';r=watch(t,out,expected_pose=pose,expected_owner=owner,expected_player=player,expected_next_generation=95,expected_entry_count=94,clock=clock.clock,sleep=clock.sleep)
            self.assertEqual(r['reason'],'damage_detected');self.assertEqual(t.calls,1);self.assertEqual((out/'0000.raw').read_bytes(),raw)
    def test_large_native_fixture_reports_overflow_not_noevent(self):
        v=validate(strict_json((FIXTURES/'window-closed.json').read_bytes()))
        self.assertTrue(v['window_closed']);self.assertGreater(v['damage_dropped'],0);self.assertEqual(v['capture_errors'],0) # overflow is independently explicit, never invented as a capture exception

if __name__=='__main__':unittest.main()
