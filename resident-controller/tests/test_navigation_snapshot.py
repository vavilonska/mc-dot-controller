"""Scan final state and capability cannot be hidden behind a pre-scan envelope."""
import copy
import tempfile
import unittest
from unittest.mock import patch
from resident_controller.controller import Resident
from resident_controller.world import WorldCache
from test_controller import FakeBridge
from test_navigation_binding_producers import state, MemoryBridge, ACTION_SESSION


class SnapshotBridge(FakeBridge):
    def __init__(self,states):
        super().__init__();self.action['action_session']=ACTION_SESSION
        self.reads=MemoryBridge(states)
    def request(self,method,path,body=None):
        if path.startswith('/control/state?') or path.startswith('/control/terrain?'):
            self.calls.append((method,path,copy.deepcopy(body)))
            return self.reads.request(method,path,body)
        return super().request(method,path,body)


class NavigationSnapshotTests(unittest.TestCase):
    def resident(self,states):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        bridge=SnapshotBridge(states);resident=Resident(bridge,temp.name);resident.start()
        self.addCleanup(resident.lock.close)
        return resident,bridge
    @patch('time.sleep',return_value=None)
    def test_initial_legacy_final_schema_is_published_from_final_plan_state(self,_):
        a=state(missing=True);b=state(epoch=5);c=state(epoch=6,x=.671, tick=101)
        resident,bridge=self.resident([a,b,c])
        with patch.object(resident.prospecting,'observe_world',wraps=resident.prospecting.observe_world) as watched:
            result=resident.snapshot({'terrain':True,'radius':1,'vertical':2})
            self.assertEqual(c,result['state'])
            self.assertEqual(c['world'],watched.call_args.args[0])
        self.assertEqual(3,sum('/state?' in p for _,p,_ in bridge.calls))
    @patch('time.sleep',return_value=None)
    def test_initial_to_scan_context_change_does_not_publish_mixed_envelope(self,_):
        for section,key in [('world','world_generation'),('world','dimension'),('player','uuid'),('client_action','action_session')]:
            a=state();a[section][key]='old-context'
            if section=='world' and key=='dimension':a['player']['dimension']='old-context'
            resident,_bridge=self.resident([a,state(),state()])
            with self.assertRaisesRegex(ValueError,'terrain_snapshot_context_changed'):
                resident.snapshot({'terrain':True,'radius':1,'vertical':2})
    @patch('time.sleep',return_value=None)
    def test_final_running_owner_is_retained_even_when_outer_action_was_idle(self,_):
        c=state();c['client_action']['status']='running'
        resident,_bridge=self.resident([state(),state(),c])
        result=resident.snapshot({'terrain':True,'radius':1,'vertical':2})
        self.assertEqual('idle',result['action']['status'])
        self.assertEqual('running',result['state']['client_action']['status'])
    @patch('time.sleep',return_value=None)
    def test_final_missing_cannot_fall_back_to_initial_valid_state(self,_):
        resident,_bridge=self.resident([state(),state(),state(missing=True)])
        with self.assertRaisesRegex(ValueError,'navigation_guard_missing_after_seen'):
            resident.snapshot({'terrain':True,'radius':1,'vertical':2})
        self.assertIsNone(resident.cache.grid)
        self.assertEqual('failed',resident.cache.terrain_read['outcome'])
