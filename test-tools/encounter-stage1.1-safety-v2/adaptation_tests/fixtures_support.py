"""Frozen Java-produced payloads in explicitly synthetic resident envelopes.

No fixture identities may be used for live requests. Original JSON is unchanged;
only in-memory copies substitute the expected UUID5 ID for attribution tests.
"""
import copy,json
from pathlib import Path
from receipt_binding import CONTRACT
from encounter_binding import EncounterBinding

ROOT=Path(__file__).resolve().parents[1]
NATIVE=json.loads((ROOT/'fixtures/native-emitted-receipts.json').read_text())['cases']
CASES={x['name']:x for x in NATIVE}
RESIDENT='aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
RISK={'risk_remaining':True,'requires_handoff':True,'safety_assured':False}


def setup(case='succeeded',request_id='synthetic_encounter_1'):
    data=copy.deepcopy(CASES[case]);req=data['request'];req.pop('action_id')
    binding=EncounterBinding(request_id,RESIDENT,req['expected_action_session'],req['expected_world_generation'],req['expected_player_uuid'],'combat_entity',encounter_request=req)
    native=data['receipt'];native['action_id']=binding.expected_action_id
    return binding,native


def observation(binding,native=None):
    old={'action_schema_version':1,'action_id':'unrelated_old_action','action_session':binding.action_session,
         'action':'combat_entity','status':'succeeded','reason':'old','ticks':0,'result':{'world_generation':binding.world_generation}}
    return {'action':copy.deepcopy(native or old),'state':{'world':{'world_generation':binding.world_generation,
         'navigation_guard':{'rebind_ready':True,'epoch':3}},'player':{'uuid':binding.player_uuid,
         'x':0,'y':64,'z':0,'health':20,'using_item':False,'sprinting':False,'yaw':0,'pitch':0},
         'client_action':{'action_session':binding.action_session},'screen_open':False,'paused':False},
         'status':{'held_mappings':[],'mouse':{'held_world_buttons':[]}}}


def receipt(binding,native=None,status=None,**extra):
    return {'request_id':binding.request_id,'session_id':binding.resident_session,
            'finished_at':1791380000.125,'status':status or (native or {}).get('status','failed'),
            **copy.deepcopy(RISK),**({'result':{'action':copy.deepcopy(native)}} if native else {}),**extra}


def rejection(binding):
    return receipt(binding,status='failed',reason='encounter_stage1_disabled',original_error='encounter_stage1_disabled',
                   action_id=None,action=None,resolved_action=None,cancellation=None,
                   task_completed=False,action_step=1,postcondition_observed=False)


def context(binding):
    return {'resident_session':binding.resident_session,'action_session':binding.action_session,
            'world_generation':binding.world_generation,'player_uuid':binding.player_uuid,'action_id_contract':CONTRACT}


def user_body(binding):
    return {k:copy.deepcopy(v) for k,v in binding.encounter_request.items()
            if k not in ('action_id','timeout_ms') and not k.startswith('expected_')}
