#!/usr/bin/env python3
"""One explicitly planned ordinary work excursion; known completion/refusal always returns."""
import argparse, copy, hashlib, http.client, json, time
from pathlib import Path
import idle_guard as idle
import guard_core as guard

class Client(idle.Client):
    def state(self):
        # Work/return/closure need player/context/inventory, not the radius32 entity list.
        path='/control/state?radius=0';conn=http.client.HTTPConnection('127.0.0.1',38121,timeout=2)
        try:
            conn.request('GET',path,headers={'Authorization':'Bearer '+self.token})
            response=conn.getresponse();obj=json.loads(response.read())
            if response.status!=200:raise idle.Refused('state_unavailable')
            return obj
        except Exception as e:
            self.note('read_failed',path=path,error=type(e).__name__);raise
        finally:conn.close()
    def exchange(self, method, path, payload=None):
        return self.request(method, path, payload)

def publish(c, phase, **values):
    row=dict(phase=phase,**values);c.note('roundtrip_status',**row)
    p=c.out/'STATUS.tmp';p.write_text(json.dumps(row,indent=2)+'\n');p.replace(c.out/'STATUS.json')
    return row

def digest(body):
    return hashlib.sha256(json.dumps(body,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()).hexdigest()

def bound_admission(obj,b):
    p=obj.get('native_admission') if isinstance(obj,dict) else None
    return isinstance(p,dict) and p.get('action_id')==b['action_id'] and p.get('action_session')==b['expected_action_session'] and p.get('action')==b['action'] and p.get('digest_format')=='sorted-json-utf8/1' and p.get('request_payload_sha256')==digest(b)

def guard_start_rejected(code,obj,b):
    if code!=409 or not bound_admission(obj,b):return False
    p=obj['native_admission'];f=obj.get('capability_source_freshness')
    return (obj.get('error')=='capability_source_expired' and p.get('reason')=='capability_source_expired'
        and p.get('stage')=='hooks_possible' and p.get('dispatch_authority') is False
        and isinstance(f,dict) and f.get('phase')=='guard_start')

def fresh_released(s,ctx):
    return idle.context(s)==ctx and idle.valid_world(s) and s['player'].get('alive') and idle.health(s)>0 and not idle.active(s) and idle.neutral(s)

def execute_one(c,b,before,original_only=False,cancel_already_sent=False,admission_response=None,admission_deadline=None):
    """One start only; original-ID queries and at most one bound cancellation."""
    code=None;obj=None;uncertain=False;cancelled=cancel_already_sent;stop=None
    if original_only:
        uncertain=True
        if isinstance(admission_response,dict):code,obj=admission_response.get('http_status'),copy.deepcopy(admission_response.get('body'))
    else:
        try:code,obj=c.request('POST','/control/action',b)
        except Exception:uncertain=True
    pre_rejection=idle.bound_pre_input_rejection(code,obj,b)
    original_response=copy.deepcopy(obj);ctx=idle.context(before)
    deadline=(admission_deadline if admission_deadline is not None else time.monotonic()+3) if pre_rejection else time.monotonic()+b.get('timeout_ms',15000)/1000+5
    grace=False
    while True:
        if time.monotonic()>=deadline:
            if pre_rejection or grace or cancelled:break
            cancelled=True;grace=True;deadline=time.monotonic()+5
            try:c.request('POST','/control/action/cancel',dict(action_id=b['action_id'],expected_action_session=b['expected_action_session']))
            except Exception:pass
        matching=isinstance(obj,dict) and obj.get('action_id')==b['action_id'] and obj.get('action_session')==b['expected_action_session']
        if pre_rejection and code==200:
            return dict(released=False,effect_known=False,success=False,action_id=b['action_id'],reason='pre_input_rejection_original_id_exists_no_replacement',cancel_sent=cancelled,original_response=original_response,original_status=obj)
        r=obj.get('result') if matching else None
        if matching and obj.get('status') in idle.TERMINAL and isinstance(r,dict):
            try:s=c.state()
            except Exception:s=None
            if s is not None and fresh_released(s,ctx):
                ca=s.get('client_action',{});g=ca.get('reactive_guard',{});pr=g.get('last_local_physical_release',{})
                fallback=('input_release_confirmed' not in r and b.get('action')=='break_block' and obj['status']=='succeeded'
                    and obj.get('reason')=='block_broken_observed' and ca.get('action_id')==b['action_id']
                    and ca.get('action_session')==b['expected_action_session'] and ca.get('status')=='succeeded'
                    and ca.get('result',{}).get('world_generation')==b['expected_world_generation']
                    and ca.get('result',{}).get('input_release_confirmed') is not False
                    and not ca.get('result',{}).get('unknown_outcome') and not ca.get('result',{}).get('requires_handoff')
                    and not r.get('unknown_outcome') and not r.get('requires_handoff')
                    and pr.get('original_action_id')==b['action_id'] and pr.get('physical_release_observed') is True
                    and pr.get('current_context_basis')=='same_player' and g.get('direct_input_release_state')=='clear')
                release_ok=(r.get('input_release_confirmed') is True or (b.get('action')=='place_block' and r.get('input_release_confirmed') is not False) or fallback)
                if release_ok:
                    effect_known=not r.get('unknown_outcome') and not r.get('requires_handoff')
                    return dict(released=True,effect_known=effect_known,success=effect_known and obj['status']=='succeeded' and not stop,
                        action_id=b['action_id'],terminal=obj,reason=stop or obj.get('reason'),cancel_sent=cancelled,
                        release_evidence=copy.deepcopy(pr) if fallback else None)
        if pre_rejection and code==404 and isinstance(obj,dict) and obj.get('error')=='action_not_found':
            try:s=c.state()
            except Exception:s=None
            if s is not None and fresh_released(s,ctx):
                result=dict(released=True,effect_known=True,success=False,no_dispatch=True,action_id=b['action_id'],
                    reason='pre_input_rejected_original_404_neutral_not_global_no_effect',
                    original_response=original_response,original_status=obj)
                c.note('known_unregistered_no_reissue',**result);return result
        if matching and obj.get('status')=='running':
            try:
                s=c.state()
                stop=('context_changed' if idle.context(s)!=ctx else 'player_dead' if not s['player'].get('alive') else 'world_unavailable' if not idle.valid_world(s) else None) or stop
                if not original_only:stop=guard.danger(s,before['player']['health']) or stop
                if (c.out/'DISARM').exists():stop='explicit_disarm'
            except Exception:pass  # Lost observation is not a reason to stop a known bounded escape.
            # Same-ID running proves acceptance: continue reading it, never replay/cancel merely for a lost start response.
            if stop and not cancelled:
                cancelled=True
                try:c.request('POST','/control/action/cancel',dict(action_id=b['action_id'],expected_action_session=b['expected_action_session']))
                except Exception:pass
        if uncertain or code not in (200,202):
            publish(c,'RESOLVING_ORIGINAL_ONLY',original_action_id=b['action_id'],cancel_sent=cancelled,exclusive_owner=True)
        time.sleep(.1)
        try:code,obj=c.request('GET','/control/action/status?action_id='+b['action_id'])
        except Exception:code,obj=None,None
    return dict(released=False,effect_known=False,success=False,action_id=b['action_id'],reason='pre_input_absence_or_release_unproven_bounded' if pre_rejection else 'original_unresolved_no_reissue',cancel_sent=cancelled,original_response=original_response)

def validate_step(spec):
    if spec.get('action')!='place_block':return guard.validate_plan(spec)
    allowed={'action','target','support','face','hotbar_slot','timeout_ms','sneak','jump','expected_block_id'}
    if set(spec)-allowed:raise guard.Stop('ordinary_place_unknown_fields')
    offsets={'up':(0,1,0),'down':(0,-1,0),'north':(0,0,-1),'south':(0,0,1),'east':(1,0,0),'west':(-1,0,0)}
    for key in ('target','support'):
        if not isinstance(spec.get(key),dict) or set(spec[key])!={'x','y','z'} or any(type(v)is not int for v in spec[key].values()):raise guard.Stop('place_integer_target_support_required')
    if spec.get('face') not in offsets or spec['target']!={k:spec['support'][k]+d for k,d in zip(('x','y','z'),offsets[spec['face']])}:raise guard.Stop('place_target_support_face_mismatch')
    if type(spec.get('hotbar_slot'))is not int or not 0<=spec['hotbar_slot']<=8:raise guard.Stop('place_explicit_slot_required')
    if spec.get('jump',False) is not False:raise guard.Stop('planned_place_nonjump_only')
    if type(spec.get('sneak',False))is not bool:raise guard.Stop('place_sneak_boolean_required')
    if type(spec.get('timeout_ms',5000))is not int or not 50<=spec.get('timeout_ms',5000)<=60000:raise guard.Stop('place_finite_timeout_required')
    if 'expected_block_id' in spec and (not isinstance(spec['expected_block_id'],str) or not spec['expected_block_id'].startswith('minecraft:')):raise guard.Stop('place_expected_material_id_required')

def bind_step(spec,fresh,cell=None,known_tunnel=False):
    if spec['action']!='place_block':return guard.bind_action(spec,fresh,cell,guarded=not (spec['action']=='follow_path' and known_tunnel is True))
    # Reuse the already exercised ordinary door-placement contract, not the different capability-placement schema.
    item=next((i for i in fresh['player'].get('inventory',[]) if i.get('slot')==spec['hotbar_slot']),{})
    if item.get('empty') or item.get('count',0)<1 or not item.get('id'):raise guard.Stop('place_actual_slot_empty')
    if spec.get('expected_block_id',item['id'])!=item['id']:raise guard.Stop('place_actual_material_mismatch')
    body={k:v for k,v in spec.items() if k!='expected_block_id'}
    return guard.bind_action(body,fresh,guarded=False)

def validate(plan):
    cfg=idle.validate(copy.deepcopy(plan['retreat']))
    if not cfg.get('closure_actions'):raise idle.Refused('explicit_two_door_closure_required')
    start=plan['start_anchor']
    if not idle.position_ok(start) or idle.distance(start,cfg['cover_anchor'])>.05:raise idle.Refused('start_must_be_actual_room_anchor')
    steps=plan.get('steps')
    if not isinstance(steps,list) or not steps:raise idle.Refused('finite_explicit_steps_required')
    for step in steps:
        validate_step(step['action']);guard.validate_points(step['return_waypoints'])
        if 'known_tunnel' in step and (type(step['known_tunnel'])is not bool or (step['known_tunnel'] and step['action']['action']!='follow_path')):raise idle.Refused('known_tunnel_only_explicit_previously_walked_follow_path')
        if idle.distance(step['return_waypoints'][-1],cfg['cover_anchor'])>.05:raise idle.Refused('every_step_return_must_end_at_room')
        if not step.get('return_evidence'):raise idle.Refused('each_possible_stop_requires_known_return_route')
    return cfg,steps

def run(c,plan):
    cfg,steps=validate(plan);initial=c.state();ctx=cfg['expected_context']
    if not fresh_released(initial,ctx) or idle.distance(initial['player'],plan['start_anchor'])>.8:
        raise idle.Refused('start_at_known_room_idle_neutral_current_context')
    cfg['exposure_origin']=idle.point(initial['player']);cfg['waypoints']=[plan['start_anchor']]
    escape=idle.Watch(c,cfg,initial);previous_health=idle.health(initial);results=[];reason='plan_completed'
    for index,step in enumerate(steps):
        cfg['waypoints']=copy.deepcopy(step['return_waypoints']);submitted=False;body=None
        try:
            s=c.state()
            if not fresh_released(s,ctx):raise guard.Stop('context_or_input_changed')
            harm=guard.danger(s,previous_health)
            if harm:raise guard.Stop(harm)
            spec=step['action'];cells=None
            if spec['action']=='break_block':cells=guard.read_neighbours(c,s,spec['target'])
            fresh=c.state()
            if not fresh_released(fresh,ctx):raise guard.Stop('context_or_input_changed')
            if not idle.native_ready(fresh):raise guard.Stop('native_navigation_not_ready_before_work_no_post')
            harm=guard.danger(fresh,previous_health)
            if harm:raise guard.Stop(harm)
            cell=None
            if cells is not None:
                guard.check_cells(cells,guard.needed_cells(fresh,spec['target']))
                cell=cells[tuple(spec['target'][k] for k in ('x','y','z'))]
            # Final source read is above: no further GET or disk write before the actual once POST.
            body=bind_step(spec,fresh,cell,known_tunnel=step.get('known_tunnel') is True)
            submitted=True
            outcome=execute_one(c,body,fresh)
            if spec['action']=='place_block' and outcome.get('success'):
                r=outcome['terminal']['result'];item=next(i for i in fresh['player']['inventory'] if i.get('slot')==spec['hotbar_slot'])
                if r.get('target')!=spec['target'] or r.get('observed_block')!=spec.get('expected_block_id',item['id']) or r.get('placement_effect_verification')!='observed':
                    outcome.update(success=False,reason='place_target_material_observation_unconfirmed')
            results.append(outcome)
            if not outcome['released']:
                return publish(c,'NEEDS_OPERATOR',reason=outcome['reason'],original_action_id=body['action_id'],exclusive_owner=True,actions=results,retreat_started=False)
            if not outcome['success']:
                reason=outcome['reason'];break
            previous_health=idle.health(fresh)
        except Exception as e:
            reason=str(e) if isinstance(e,(guard.Stop,idle.Refused)) else type(e).__name__
            if submitted:
                return publish(c,'NEEDS_OPERATOR',reason='post_start_resolution_interrupted:'+reason,original_action_id=body['action_id'],exclusive_owner=True,actions=results)
            c.note('preflight_or_read_stop',step=index,reason=reason);break
    # No successful/known-rejected exposed result is returned to the model before this escape.
    s=c.state()
    if not fresh_released(s,ctx):
        return publish(c,'NEEDS_OPERATOR',reason='fresh_release_or_context_unproven_no_retreat',exclusive_owner=True,actions=results)
    work_success=reason=='plan_completed' and len(results)==len(steps) and all(x['success'] for x in results)
    escape.start_retreat(s,reason);observed_id=None;action_deadline=0
    while True:
        try:s=c.state();status=escape.step(s)
        except Exception as e:
            publish(c,'RESOLVING_ORIGINAL_ONLY' if escape.pending else 'NEEDS_OPERATOR',reason='return_observation_unavailable',error=type(e).__name__,exclusive_owner=True,original_action_id=None if escape.body is None else escape.body['action_id'])
            if not escape.pending:
                return publish(c,'NEEDS_OPERATOR',reason='return_fresh_state_unavailable_no_new_input',exclusive_owner=True,actions=results)
            outcome=execute_one(c,escape.body,s,original_only=True,cancel_already_sent=escape.cancel_sent,admission_response=escape.admission_response,admission_deadline=escape.admission_deadline)
            escape.cancel_sent=escape.cancel_sent or outcome.get('cancel_sent',False)
            if not outcome['released']:
                return publish(c,'NEEDS_OPERATOR',reason=outcome['reason'],exclusive_owner=True,actions=results,return_resolution=outcome)
            s=c.state()
            if outcome.get('no_dispatch'):escape.confirm_unregistered(s,outcome['original_status'])
            else:escape.finish_if_terminal(outcome['terminal'],s)
            status=escape.summary(s)
        if escape.body and escape.body['action_id']!=observed_id:
            observed_id=escape.body['action_id'];action_deadline=time.monotonic()+escape.body.get('timeout_ms',15000)/1000+5
        if escape.pending and (escape.phase=='NEEDS_OPERATOR' or time.monotonic()>action_deadline or 'start_response_unknown' in escape.reason):
            outcome=execute_one(c,escape.body,s,original_only=True,cancel_already_sent=escape.cancel_sent,admission_response=escape.admission_response,admission_deadline=escape.admission_deadline)
            escape.cancel_sent=escape.cancel_sent or outcome.get('cancel_sent',False)
            if not outcome['released']:
                return publish(c,'NEEDS_OPERATOR',reason=outcome['reason'],exclusive_owner=True,actions=results,return_resolution=outcome)
            s=c.state()
            if outcome.get('no_dispatch'):escape.confirm_unregistered(s,outcome['original_status'])
            else:escape.finish_if_terminal(outcome['terminal'],s)
            status=escape.summary(s)
        publish(c,'RETURNING',work_reason=reason,actions=results,retreat=status)
        if escape.closure_confirmed:
            escape.disarm(s)
            if escape.done:
                return publish(c,'COVERED_DISARMED',work_reason=reason,work_success=work_success,actions=results,retreat=escape.summary(s),exclusive_owner=False)
        elif escape.phase=='NEEDS_OPERATOR':
            return publish(c,'NEEDS_OPERATOR',reason=escape.reason,actions=results,retreat=status,exclusive_owner=True)
        time.sleep(.1)

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--plan',type=Path,required=True);p.add_argument('--run-dir',type=Path,required=True);a=p.parse_args()
    plan=json.loads(a.plan.read_text());a.run_dir.mkdir(parents=True,exist_ok=False,mode=0o700);c=Client(a.run_dir)
    c.note('explicit_plan',plan=plan)
    try:r=run(c,plan)
    except Exception as e:r=publish(c,'NEEDS_OPERATOR',reason=type(e).__name__+':'+str(e),exclusive_owner=True)
    (a.run_dir/'RESULT.json').write_text(json.dumps(r,indent=2)+'\n');print(json.dumps(r),flush=True)
    return 0 if r['phase']=='COVERED_DISARMED' else 2
if __name__=='__main__':raise SystemExit(main())
