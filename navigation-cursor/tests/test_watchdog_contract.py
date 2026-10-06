"""Optional real-source contract test, with a fake resident and temporary inbox.

WATCHDOG_CANDIDATE=/path/to/verified/watchdog/source python -m unittest discover -s tests -v
No live mailbox, service, socket or game action is used.
"""
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from navigation_cursor import Navigator
from test_navigation_cursor import observation

CANDIDATE = os.environ.get('WATCHDOG_CANDIDATE')
if CANDIDATE:
    sys.path.insert(0, CANDIDATE)
    from intent_client import IntentClient
    from watchdog import Watchdog, write_json


class FakeResident:
    def __init__(self):
        self.commands, self.results = [], {}
    def submit(self, command):
        rid='resident-'+str(len(self.commands))
        self.commands.append((rid,dict(command)))
        return rid
    def result(self, rid): return self.results.get(rid)


@unittest.skipUnless(CANDIDATE, 'set WATCHDOG_CANDIDATE for the real v5.1-compatible source contract')
class RealGatewayContractTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        for name in ('inbox','working','results'):(self.root/name).mkdir()
        self.queue=FakeResident()
        self.dog=Watchdog(self.queue,clock=lambda:100)
        self.nodes=[(x,92,0) for x in range(6)]
        self.obs=observation(self.nodes[0],self.nodes)
        self.dog.latest=self.obs
        self.dog.observed_at=100
        self.dog.next_observe=200
        self.client=IntentClient(self.root)
        self.nav=Navigator(self.client,self.root/'route.json')
        self.publish_status()

    def tearDown(self):self.temp.cleanup()

    def publish_status(self):
        # Match base_watchdog.run(), not Watchdog.status() in isolation.
        write_json(self.root/'state.json',{**self.dog.status(),
                   'pending': len(list((self.root/'inbox').glob('*.json'))),
                   'updated_at':time.time()})

    def flush(self):
        for done in self.dog.completed:
            write_json(self.root/'results'/(done['intent_id']+'.json'),done)
            (self.root/'working'/(done['intent_id']+'.json')).unlink(missing_ok=True)
        self.dog.completed.clear()
        self.publish_status()

    def admit(self):
        path=next((self.root/'inbox').glob('*.json'))
        command=json.loads(path.read_text())
        self.assertEqual(command.pop('_watchdog_session_id'),self.dog.session_id)
        accepted=self.dog.submit_owner(path.stem,command)
        if accepted:path.rename(self.root/'working'/path.name)
        self.flush()
        return accepted,command

    def finish_owner(self,result):
        rid=self.dog.owner['request_id']
        self.queue.results[rid]={'status':'succeeded','session_id':'resident-session','result':result}
        self.dog.tick()
        self.flush()

    def prepare_action(self):
        self.assertEqual(self.nav.tick((5,0))['reason'],'observe_submitted')
        self.assertTrue(self.admit()[0])
        self.finish_owner(self.obs)
        self.assertEqual(self.nav.tick((5,0))['reason'],'action_submitted')

    def test_matching_epoch_is_stripped_before_real_watchdog_dispatch(self):
        self.prepare_action()
        accepted,command=self.admit()
        self.assertTrue(accepted)
        self.assertEqual(command['_navigation_defense_epoch'],0)
        self.assertEqual(self.queue.commands[-1][1]['action'],'follow_path')
        self.assertNotIn('_navigation_defense_epoch',self.queue.commands[-1][1])

    def test_race_cancels_locally_then_navigator_observes_and_replans(self):
        self.prepare_action()
        rid=self.nav.data['pending']['id']
        count=len(self.queue.commands)
        # Combat starts after navigator submit but before gateway admission.
        self.dog.defense_epoch += 1
        self.dog.phase='combat'
        self.publish_status()
        accepted,_=self.admit()
        self.assertTrue(accepted)
        self.assertEqual(len(self.queue.commands),count)
        result=self.client.result(rid)
        self.assertEqual(result['status'],'cancelled')
        self.assertEqual(result['reason'],'navigation_defense_epoch_changed')
        self.assertIsNone(result['queue_request_id'])
        self.assertEqual(self.nav.tick((5,0))['status'],'progress')
        self.assertEqual(self.nav.tick((5,0))['status'],'waiting')
        self.dog.phase='watching'
        self.publish_status()
        self.assertEqual(self.nav.tick((5,0))['reason'],'observe_submitted')
        self.admit()
        self.finish_owner(self.obs)
        self.assertEqual(self.nav.tick((5,0))['reason'],'action_submitted')
        accepted,command=self.admit()
        self.assertTrue(accepted)
        self.assertEqual(command['_navigation_defense_epoch'],1)
        self.assertEqual(self.nav.data['forbidden'],[])
        self.assertNotIn('_navigation_defense_epoch',self.queue.commands[-1][1])

if __name__=='__main__':unittest.main()
