"""Explicit GUI-close escape from automatic observation recovery only."""
import copy
import json
from pathlib import Path
import tempfile
import time
import unittest
from base_watchdog import cancel_waiting_intents, write_json
from watchdog import Watchdog
from intent_client import IntentClient
from test_watchdog import Queue

CLOSE = {'op': 'recovery_close_menu'}

class MenuRecoveryChecks(unittest.TestCase):
    def setUp(self):
        self.now = 0.0
        self.q = Queue()
        self.d = Watchdog(self.q, clock=lambda:self.now)
    def tick(self, n=1):
        for _ in range(n): self.d.tick(); self.now += .1
    def recover(self):
        self.tick(3)
        self.q.hold_observe = True; self.tick(5); self.now += 3; self.tick(2)
        self.q.hold_observe = False
        self.q.obs['state']['screen_open'] = True
        self.tick(15)
        self.assertTrue(self.d.menu_close_ready())
    def test_gui_block_is_reproduced_and_explicit_escape_is_single_dispatch(self):
        self.recover()
        self.assertFalse(self.d.armed)
        self.assertEqual(self.d.recovery_samples, 0)
        self.assertFalse(self.d.submit_owner('movement', {'op': 'action'}))
        while self.d.rpc: self.tick()
        self.assertTrue(self.d.submit_owner('close', CLOSE))
        writes = [c for _,c in self.q.calls if c['op'] == 'direct']
        self.assertEqual(writes, [{'op':'direct','endpoint':'raw-key','body':{'key':'key.keyboard.escape','action':'click'}}])
        self.assertFalse(self.d.armed)
        self.q.obs['state']['screen_open'] = False
        self.tick(20)
        self.assertTrue(self.d.armed)
        self.assertEqual(len([c for _,c in self.q.calls if c['op'] == 'direct']), 1)
    def test_hard_pauses_never_offer_recovery_control(self):
        for reason in ('operator_took_control','owner_action_uncertain','player_dead_or_unavailable'):
            self.recover()
            self.d.attention(reason)
            self.assertFalse(self.d.menu_close_ready())
            self.assertFalse(self.d.submit_owner('close', CLOSE))
            self.setUp()
    def test_stop_changed_context_stale_open_world_or_holds_reject(self):
        for mode in ('stop','world','session','player','stale','closed','holds','action','combat','dead'):
            with self.subTest(mode=mode):
                self.recover(); state = self.d.latest['state']
                if mode == 'stop': self.d.stop()
                elif mode == 'world': state['world']['world_generation'] = 'other'
                elif mode == 'session': state['client_action']['action_session'] = 'other'
                elif mode == 'player': state['player']['uuid'] = 'other'
                elif mode == 'stale': self.now += 1
                elif mode == 'closed': state['screen_open'] = False
                elif mode == 'holds': self.d.latest['status']['held_mappings'] = ['key.forward']
                elif mode == 'action': self.d.latest['action']['status'] = 'running'
                elif mode == 'combat': self.d.latest['combat']['active'] = True
                elif mode == 'dead': state['player']['alive'] = False
                self.assertFalse(self.d.menu_close_ready())
                self.assertFalse(self.d.submit_owner('close', CLOSE))
                self.setUp()
    def test_no_arbitrary_payload_or_direct_input_through_exception(self):
        self.recover()
        while self.d.rpc: self.tick()
        with self.assertRaisesRegex(ValueError, 'invalid_recovery_close_menu'):
            self.d.submit_owner('bad', {**CLOSE, 'body':{'key':'w','action':'down'}})
        self.assertFalse(self.d.submit_owner('direct', {'op':'direct','endpoint':'key','body':{'mapping':'key.attack','action':'click'}}))
    def test_adapter_and_inbox_keep_only_explicit_new_close_in_recovery(self):
        self.recover()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for folder in ('inbox','working','results'): (root/folder).mkdir()
            write_json(root/'state.json', {**self.d.status(),'updated_at':time.time()})
            client = IntentClient(root)
            with self.assertRaisesRegex(ValueError,'not_accepting'):
                client.submit({'op':'action'}, 'bad')
            client.submit(CLOSE, 'close')
            write_json(root/'inbox/old.json', {'op':'action','_watchdog_session_id':self.d.session_id})
            cancel_waiting_intents(root, self.d)
            self.assertTrue((root/'inbox/close.json').is_file())
            self.assertFalse((root/'inbox/old.json').exists())
            self.d.stop(); cancel_waiting_intents(root,self.d)
            self.assertFalse((root/'inbox/close.json').exists())
    def test_recovery_control_uncertainty_stays_paused_and_is_not_replayed(self):
        self.recover()
        while self.d.rpc: self.tick()
        self.d.submit_owner('close', CLOSE)
        self.q.results[self.d.owner['request_id']] = {'status':'uncertain','reason':'transport_failed'}
        self.tick(20)
        self.assertFalse(self.d.armed)
        self.assertFalse(self.d.recover_observation)
        self.assertEqual(len([c for _,c in self.q.calls if c['op']=='direct']),1)

if __name__ == '__main__': unittest.main()
