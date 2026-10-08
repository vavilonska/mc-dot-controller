"""Owner-run baseline sampler. Existing resident queue only; no credentials/HTTP.

Run only after the sole game operator confirms the independent local test world,
watchdog stopped/released, an adult test zombie and the requested equipment.
Stationary: never submits movement, down/up keys, commands or inventory changes.
The timer bounds sampling and queues stop at 20 s; it is NOT a JVM input lease.
"""
import argparse
import json
from pathlib import Path
import sys
import threading
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'resident-controller'))
from resident_controller.ipc import QueueClient, atomic_json


def run(q, expected_world, target_uuid, label, output, duration=20.0):
    session = q.session()['session_id']
    calls = []
    samples = []
    stop_id = []
    errors = []
    started = time.monotonic()
    lock = threading.Lock()
    def submit(command):
        if q.session()['session_id'] != session:
            raise RuntimeError('resident_session_changed_no_write')
        rid = q.submit(command)
        with lock: calls.append({'op':command['op'], 'request_id':rid, 'elapsed':time.monotonic()-started})
        return rid
    def stop_once():
        with lock:
            if stop_id: return
            stop_id.append(None)
        try: stop_id[0] = submit({'op':'combat_stop'})
        except Exception as e: errors.append(type(e).__name__+':'+str(e))
    initial_id = submit({'op':'observe'})
    initial = q.wait(initial_id, 8)
    state = initial.get('result',{}).get('state',{})
    if initial.get('status') != 'succeeded' or state.get('world',{}).get('world_generation') != expected_world:
        raise RuntimeError('local_test_world_not_verified')
    if state.get('screen_open') is not False or state.get('paused') is not False:
        raise RuntimeError('close_test_world_screen_first')
    entity=next((e for e in state.get('nearby',{}).get('entities',[]) if e.get('uuid')==target_uuid),None)
    if not entity or entity.get('type') != 'minecraft:zombie' or entity.get('alive') is not True:
        raise RuntimeError('exact_test_zombie_not_observed')
    initial_health=state.get('player',{}).get('health')
    started=time.monotonic()
    timer=threading.Timer(duration, stop_once)
    timer.daemon=True
    reason='deadline'
    try:
        start_id=submit({'op':'combat_start','target_uuid':target_uuid,'approach':False,'shield':True,'radius':8})
        timer.start()
        result=q.wait(start_id,min(8,duration))
        if result.get('status') != 'succeeded':
            reason='combat_start_'+str(result.get('status')); return
        while time.monotonic()-started < duration:
            rid=submit({'op':'observe'})
            result=q.wait(rid,min(3,max(.1,duration-(time.monotonic()-started))))
            if result.get('status') != 'succeeded':
                reason='observation_'+str(result.get('status')); break
            payload=result.get('result',{}); state=payload.get('state',{})
            if state.get('world',{}).get('world_generation') != expected_world:
                reason='world_changed'; break
            p=state.get('player',{}); combat=payload.get('combat',{})
            entity=next((e for e in state.get('nearby',{}).get('entities',[]) if e.get('uuid')==target_uuid),None)
            samples.append({'elapsed':round(time.monotonic()-started,3),
                'tick':state.get('world',{}).get('game_time'),'player_health':p.get('health'),
                'player_alive':p.get('alive'),'on_ground':p.get('on_ground'),'target_health':(entity or {}).get('health'),
                'target_alive':(entity or {}).get('alive'),'phase':combat.get('phase'),
                'reason':combat.get('reason'),'attack_attempts':combat.get('attack_attempts'),
                'attack_dispatches':combat.get('attack_dispatches')})
            if p.get('alive') is not True: reason='player_dead_observed'; break
            if entity and (entity.get('alive') is False or entity.get('health',1)<=0): reason='target_dead_observed'; break
            if combat.get('active') is not True: reason='combat_stopped_'+str(combat.get('reason')); break
            time.sleep(.35)
    finally:
        stop_once(); timer.cancel()
        if timer.ident is not None:
            timer.join(timeout=3)
        stop=q.wait(stop_id[0],8) if stop_id and stop_id[0] else None
        released=bool(stop and stop.get('status')=='succeeded' and stop.get('result',{}).get('input_release_confirmed') is True)
        # Stop failure is reported, never hidden or replaced by more blind keys.
        report={'schema_version':1,'scenario':'stationary_adult_zombie_baseline','equipment':label,
                'duration_seconds':round(time.monotonic()-started,3),'stop_reason':reason,
                'initial_player_health':initial_health,'samples':samples,'calls':calls,
                'stop_result':stop,'input_release_confirmed':released,'errors':errors,
                'approach':False,'server_hits_confirmed':None,'new_java_lease':False}
        atomic_json(output,report)
        print(json.dumps({'report':str(output),'samples':len(samples),'stop_reason':reason,
                          'input_release_confirmed':released},ensure_ascii=False),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--queue',required=True);p.add_argument('--out',type=Path,required=True)
    p.add_argument('--expected-world',required=True);p.add_argument('--target-uuid',required=True)
    p.add_argument('--equipment',choices=('iron','diamond'),required=True)
    p.add_argument('--confirm-local-test-world',action='store_true',required=True)
    a=p.parse_args();run(QueueClient(a.queue),a.expected_world,a.target_uuid,a.equipment,a.out)
