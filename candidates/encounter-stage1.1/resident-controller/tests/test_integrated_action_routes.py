"""Actual resident routing with a fake bridge; no IPC or real game is accessed."""
import copy
import tempfile
import unittest
from resident_controller.controller import Resident
from resident_controller.ipc import QueueClient
from resident_controller.transport import BridgeError
from test_controller import FakeBridge

class IntegratedRoutes(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.bridge=FakeBridge()
        self.resident=Resident(self.bridge,self.tmp.name);self.resident.start();self.client=QueueClient(self.tmp.name)
    def tearDown(self):
        if self.resident.lock:self.resident.lock.close()
        self.tmp.cleanup()
    def post(self,body):
        rid=self.client.submit({'op':'action',**body});self.resident.tick()
        return rid,[b for m,p,b in self.bridge.calls if m=='POST' and p=='/control/action']
    def test_boat_fields_pass_unchanged_and_only_resident_assigns_action_id(self):
        b={'action':'boat_drive','action_id':'caller-id','boat_schema_version':1,'timeout_ms':10000,'expected_world_generation':'w','expected_player_uuid':'p','expected_action_session':'test-session','vehicle_uuid':'v','vehicle_entity_id':1,'vehicle_type':'minecraft:boat','water_surface_y':63,'waypoints':[{'x':0,'z':8}]}
        # This fake bridge omits status.world, so provide the existing launch observation.
        old=self.bridge.request
        def request(m,p,body=None):
            result=old(m,p,body)
            if p=='/control/status':result['world']={'world_generation':'w'}
            return result
        self.bridge.request=request
        _,posts=self.post(b);self.assertEqual(len(posts),1)
        for k,v in b.items():
            if k!='action_id':self.assertEqual(posts[0][k],v)
        self.assertNotEqual(posts[0]['action_id'],'caller-id')
    def test_combat_and_navigation_binding_preserved(self):
        b={'action':'combat_entity','target_uuid':'target','target_entity_id':1,'target_type':'minecraft:zombie','expected_navigation_epoch':4,'expected_origin':{'x':1,'y':64,'z':2},'approach':False,'shield':True}
        _,posts=self.post(b);self.assertEqual(len(posts),1)
        for k,v in b.items():self.assertEqual(posts[0][k],v)
    def test_sprint_false_is_not_lost_by_passthrough(self):
        _,posts=self.post({'action':'follow_path','waypoints':[{'x':1,'y':64,'z':1},{'x':2,'y':64,'z':1}],'sprint':False})
        self.assertIs(posts[0]['sprint'],False) # Does not claim native multi-waypoint sprint bug is fixed.
    def test_boat_then_combat_are_serial_not_two_active_posts(self):
        self.post({'action':'boat_drive'});self.post({'action':'combat_entity'})
        self.assertEqual(sum(m=='POST' and p=='/control/action' for m,p,_ in self.bridge.calls),1)
        self.assertEqual(len(self.resident.pending),1)
    def test_unknown_result_never_replays_boat_with_new_id(self):
        self.bridge.fail_post=True;rid,_=self.post({'action':'boat_drive'})
        for _ in range(4):self.resident.tick()
        self.assertEqual(self.client.result(rid)['status'],'uncertain')
        self.assertEqual(sum(m=='POST' and p=='/control/action' for m,p,_ in self.bridge.calls),1)
    def test_proposal_is_not_an_executable_resident_operation(self):
        rid=self.client.submit({'op':'draft_plan','action':'boat_drive'});self.resident.tick()
        self.assertEqual(self.client.result(rid)['status'],'failed')
        self.assertFalse(any(m=='POST' for m,p,b in self.bridge.calls))
