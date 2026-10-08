"""Single owner-run trial using the bounded client-tick action; no game I/O on import."""
import argparse
import json
from pathlib import Path
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'resident-controller'))
from resident_controller.ipc import QueueClient, atomic_json


def trial(q, expected_world, target_uuid, equipment, output, timeout_ms=20000):
    initial=q.wait(q.submit({'op':'observe'}),8)
    state=initial.get('result',{}).get('state',{})
    if (initial.get('status')!='succeeded' or state.get('world',{}).get('world_generation')!=expected_world
            or state.get('combat_observation_schema_version')!=1):
        raise RuntimeError('candidate_local_world_not_verified')
    entity=next((e for e in state.get('nearby',{}).get('entities',[]) if e.get('uuid')==target_uuid),None)
    if not entity or entity.get('alive') is not True: raise RuntimeError('target_not_observed')
    command={'op':'action','action':'combat_entity','timeout_ms':timeout_ms,
             'expected_world_generation':expected_world,
             'expected_player_uuid':state['player']['uuid'],
             'expected_action_session':state['client_action']['action_session'],
             'target_uuid':target_uuid,'target_entity_id':entity['entity_id'],'target_type':entity['type'],
             'approach':True,'shield':True}
    start=time.monotonic();rid=q.submit(command);result=q.wait(rid,timeout_ms/1000+12)
    cancel=None
    if result.get('status')=='pending':
        cancel=q.wait(q.submit({'op':'cancel'}),8)
        result=q.result(rid) or result
    payload=result.get('result') or {}
    action=payload.get('action') or result.get('resolved_action') or result.get('action') or {}
    observed=q.wait(q.submit({'op':'observe'}),8)
    observation=observed.get('result') or {}
    final=observation.get('state') or {}
    released=(observed.get('status')=='succeeded'
              and final.get('world',{}).get('world_generation')==expected_world
              and observation.get('status',{}).get('held_mappings')==[]
              and final.get('player',{}).get('using_item') is False
              and observation.get('action',{}).get('status')!='running')
    report={'schema_version':1,'scenario':'client_tick_single_target','equipment':equipment,
            'entity_type':entity['type'],'timeout_ms':timeout_ms,'request_id':rid,
            'elapsed_seconds':round(time.monotonic()-start,3),'status':result.get('status'),
            'reason':result.get('reason') or action.get('reason'),'action':action,'cancel':cancel,
            'final_player_health':final.get('player',{}).get('health'),
            'input_release_observed':released,
            'api_intents':3 if cancel is None else 4,'server_hits_confirmed':None,
            'notes':'Health changes are client observations, not exclusive attacker attribution.'}
    atomic_json(output,report)
    print(json.dumps({'report':str(output),'status':report['status'],'reason':report['reason']},ensure_ascii=False))
    return report

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--queue',required=True);p.add_argument('--out',type=Path,required=True)
    p.add_argument('--expected-world',required=True);p.add_argument('--target-uuid',required=True)
    p.add_argument('--equipment',choices=('iron','diamond'),required=True)
    p.add_argument('--timeout-ms',type=int,default=20000);p.add_argument('--confirm-local-test-world',action='store_true',required=True)
    a=p.parse_args()
    if not 50 <= a.timeout_ms <= 30000:p.error('timeout must be 50..30000 ms')
    trial(QueueClient(a.queue),a.expected_world,a.target_uuid,a.equipment,a.out,a.timeout_ms)
