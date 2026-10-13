"""Original synthetic gate evidence constructor; no request or transport method.

Source: candidate resident-controller/tests/test_gate_off_probe.py, ProbeBridge.
Only its existing W/P/S constants and __init__ are retained for ledger tests.
"""
import copy

W='00000000-0000-0000-0000-000000000001'
P='00000000-0000-0000-0000-000000000002'
S='00000000-0000-0000-0000-000000000003'

class ProbeBridge:
    def __init__(self, outcome='expected'):
        self.outcome=outcome;self.calls=[];self.posted=False;self.last_response_metadata=None
        action={'ok':True,'action_schema_version':1,'action_session':S,'action_id':'old-terminal','status':'failed',
                'result':{'input_release_confirmed':True}}
        self.status={'ok':True,'protocol':'mineclient-bridge','schema_version':2,'run_id':'fake','process_id':1,
            'in_world':True,'client_action':action,'world':{'world_generation':W,'game_time':100},
            'player':{'uuid':P,'x':1.,'y':64.,'z':1.,'health':20.},'held_mappings':[],
            'input_isolation':{'held_keys':0},'mouse':{'left_pressed':False,'right_pressed':False,'middle_pressed':False,'held_world_buttons':[]},
            'guarded_movement':{'held_keys':False,'owner_request_id':None},'guarded_turn':{'held_input':False}}
        self.state={**copy.deepcopy(self.status),'paused':True,'nearby':{'truncated':False,'entities':[]}}
