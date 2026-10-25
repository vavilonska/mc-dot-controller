#!/usr/bin/env python3
"""One explicit known-room excursion: known route, existing stationary fight, return and seal."""
import argparse, copy, datetime, hashlib, importlib.util, json, sys, time, uuid
from pathlib import Path
from damage_policy import DamagePolicy

HERE=Path(__file__).resolve().parent
B=HERE.parent
N=B/'MDC-RECOVERY-LIVE-F1220-20261022'

def load_core():
    dep=json.loads((HERE/'CORE-PIN.json').read_text())
    core=B/dep['directory']
    for name,sha in dep['files'].items():
        if hashlib.sha256((core/name).read_bytes()).hexdigest()!=sha:
            raise RuntimeError('frozen_core_hash_mismatch:'+name)
    sys.path.insert(0,str(core))
    def load(name,file):
        spec=importlib.util.spec_from_file_location(name,core/file)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module
    return load('room_trip_core','exposure-roundtrip.py'),load('room_fight_core','shield-axe.py')

trip,combat=load_core()
idle=trip.idle

class Client(trip.Client):
    entities=False
    def state(self):
        # Same frozen transport/logger/token; only combat needs the entity-bearing read.
        return idle.Client.state(self) if self.entities else super().state()

def report(c,phase,**values):return trip.publish(c,phase,**values)

def finish_return(c,w,s,reason,actions,clicks=0):
    """Drive the existing Watch/resolver to closed doors or explicit unresolved handoff."""
    c.entities=False;observed_id=None;action_deadline=0
    while True:
        try:s=c.state();status=w.step(s,(c.out/'DISARM').exists())
        except Exception as e:
            report(c,'RESOLVING_ORIGINAL_ONLY' if w.pending else 'NEEDS_OPERATOR',reason='return_observation_unavailable',error=type(e).__name__)
            if not w.pending:return report(c,'NEEDS_OPERATOR',reason='return_fresh_state_unavailable_no_new_input',actions=actions)
            outcome=trip.execute_one(c,w.body,s,original_only=True,cancel_already_sent=w.cancel_sent,admission_response=w.admission_response,admission_deadline=w.admission_deadline)
            w.cancel_sent=w.cancel_sent or outcome.get('cancel_sent',False)
            if not outcome['released']:return report(c,'NEEDS_OPERATOR',reason=outcome['reason'],actions=actions,return_resolution=outcome)
            s=c.state()
            if outcome.get('no_dispatch'):w.confirm_unregistered(s,outcome['original_status'])
            else:w.finish_if_terminal(outcome['terminal'],s)
            status=w.summary(s)
        if w.body and w.body['action_id']!=observed_id:
            observed_id=w.body['action_id'];action_deadline=time.monotonic()+w.body.get('timeout_ms',15000)/1000+5
        if w.pending and (w.phase=='NEEDS_OPERATOR' or time.monotonic()>action_deadline or 'start_response_unknown' in w.reason):
            outcome=trip.execute_one(c,w.body,s,original_only=True,cancel_already_sent=w.cancel_sent,admission_response=w.admission_response,admission_deadline=w.admission_deadline)
            w.cancel_sent=w.cancel_sent or outcome.get('cancel_sent',False)
            if not outcome['released']:return report(c,'NEEDS_OPERATOR',reason=outcome['reason'],actions=actions,return_resolution=outcome)
            s=c.state()
            if outcome.get('no_dispatch'):w.confirm_unregistered(s,outcome['original_status'])
            else:w.finish_if_terminal(outcome['terminal'],s)
            status=w.summary(s)
        report(c,'RETURNING',reason=reason,actions=actions,known_attack_clicks=clicks,retreat=status)
        if w.done:return report(c,'DISARMED',reason=w.reason,actions=actions,known_attack_clicks=clicks,retreat=status,exclusive_owner=False)
        if w.closure_confirmed:
            w.disarm(s)
            if w.done:return report(c,'COVERED_DISARMED',reason=reason,actions=actions,known_attack_clicks=clicks,retreat=w.summary(s),exclusive_owner=False)
        elif w.phase=='NEEDS_OPERATOR':
            return report(c,'NEEDS_OPERATOR',reason=w.reason,actions=actions,known_attack_clicks=clicks,retreat=status,exclusive_owner=True)
        time.sleep(.1)

def retreat(c,cfg,s,reason,actions):
    if not trip.fresh_released(s,cfg['expected_context']):
        return report(c,'NEEDS_OPERATOR',reason='release_or_context_unproven_no_retreat',actions=actions,exclusive_owner=True)
    cfg=copy.deepcopy(cfg);cfg['exposure_origin']=idle.point(s['player'])
    w=idle.Watch(c,cfg,s);w.start_retreat(s,reason)
    return finish_return(c,w,s,reason,actions)

def rod_count(s):
    return sum(i.get('count',0) for i in s['player'].get('inventory',[]) if i.get('id')=='minecraft:blaze_rod' and not i.get('empty'))

def pickup_once(c,plan,cfg,policy,previous_health,actions,s,initial_rods):
    """Explicit finite local collection actions, not another controller or an implicit search."""
    ctx=cfg['expected_context'];observed_rods=rod_count(s);reason='pickup_plan_completed'
    danger=lambda frame:policy.observe(frame,time.monotonic()) if policy is not None else trip.guard.danger(frame,previous_health)
    for step in plan['pickup_actions']:
        submitted=False;body=None
        try:
            s=c.state()
            if not trip.fresh_released(s,ctx):raise idle.Refused('pickup_context_or_input_changed')
            harm=danger(s)
            if harm:reason=harm;break
            if (c.out/'STOP_FIGHT').exists():reason='operator_stop_pickup_return';break
            if (c.out/'DISARM').exists():return report(c,'DISARMED',reason='explicit_pickup_handoff',actions=actions,exclusive_owner=False)
            spec=step['action'];cells=None;cell=None
            if spec['action']=='break_block':cells=trip.guard.read_neighbours(c,s,spec['target'])
            fresh=c.state()
            if not trip.fresh_released(fresh,ctx):raise idle.Refused('pickup_fresh_context_or_input_changed')
            harm=danger(fresh)
            if harm:reason=harm;break
            if not idle.native_ready(fresh):reason='pickup_native_not_ready_no_work_post';break
            if cells is not None:
                trip.guard.check_cells(cells,trip.guard.needed_cells(fresh,spec['target']))
                cell=cells[tuple(spec['target'][k] for k in ('x','y','z'))]
            body=trip.bind_step(spec,fresh,cell,known_tunnel=step.get('known_tunnel') is True)
            submitted=True;outcome=trip.execute_one(c,body,fresh,danger_check=danger if policy is not None else None)
            if spec['action']=='place_block' and outcome.get('success'):
                result=outcome['terminal']['result'];item=next(i for i in fresh['player']['inventory'] if i.get('slot')==spec['hotbar_slot'])
                if result.get('target')!=spec['target'] or result.get('observed_block')!=spec.get('expected_block_id',item['id']) or result.get('placement_effect_verification')!='observed':
                    outcome.update(success=False,reason='pickup_restore_actual_block_unconfirmed')
            actions.append(outcome)
            if not outcome['released']:return report(c,'NEEDS_OPERATOR',reason=outcome['reason'],actions=actions,exclusive_owner=True)
            s=c.state();observed_rods=max(observed_rods,rod_count(s));c.note('pickup_inventory_observed',blaze_rods=rod_count(s),initial_blaze_rods=initial_rods)
            if not outcome['success']:reason=outcome['reason'];break
            harm=danger(s)
            if harm:reason=harm;break
            previous_health=idle.health(s)
        except Exception as e:
            reason=type(e).__name__+':'+str(e)
            if submitted:return report(c,'NEEDS_OPERATOR',reason='pickup_original_resolution_interrupted:'+reason,original_action_id=body['action_id'],actions=actions,exclusive_owner=True)
            break
    # Known restoration failure also returns immediately; it is not an invitation to inspect while exposed.
    s=c.state();observed_rods=max(observed_rods,rod_count(s))
    r=retreat(c,cfg,s,reason,actions)
    r['pickup']=dict(initial_blaze_rods=initial_rods,max_observed_blaze_rods=observed_rods,observed_gain=max(0,observed_rods-initial_rods))
    return r

def shield_approach(c,spec,first,ctx,policy,previous_health):
    """Existing g304 ordinary keys, once each; never a native follow that clears the shield."""
    attempted=set();uncertain=[];reason=None;last=first;success=False
    def send(path,body,label):
        attempted.add(label)
        try:
            code,obj=c.request('POST',path,body)
            if code==200 and isinstance(obj,dict) and obj.get('ok') is True:return True
        except Exception:pass
        uncertain.append(label);return False
    def key(mapping,action):return send('/control/key',dict(mapping=mapping,action=action),mapping+':'+action)
    def danger(s):return policy.observe(s,time.monotonic()) if policy is not None else trip.guard.danger(s,previous_health)
    if idle.distance(first['player'],spec['origin'])>.5 or not trip.fresh_released(first,ctx):
        return dict(released=True,effect_known=True,success=False,reason='shield_approach_origin_not_observed_no_input',state=first)
    try:
        if not send('/control/look',dict(yaw=spec['yaw'],pitch=0,relative=False),'look'):reason='approach_look_unknown'
        elif not key('key.use','down'):reason='approach_shield_down_unknown'
        else:
            until=time.monotonic()+1
            while True:
                last=c.state()
                if idle.context(last)!=ctx or not idle.valid_world(last) or idle.active(last):reason='approach_context_or_owner_changed';break
                reason=danger(last)
                if reason or last['player'].get('blocking') is True:break
                if time.monotonic()>=until:reason='shield_not_observed_before_forward';break
                time.sleep(.05)
            if not reason:
                if not key('key.forward','down'):reason='approach_forward_down_unknown'
                else:
                    until=time.monotonic()+spec['timeout_seconds']
                    while time.monotonic()<until:
                        last=c.state();p=last['player']
                        if idle.context(last)!=ctx or not idle.valid_world(last) or idle.active(last):reason='approach_context_or_owner_changed';break
                        reason=danger(last)
                        if (c.out/'DISARM').exists() or (c.out/'STOP_FIGHT').exists():reason='operator_stop_approach'
                        if reason:break
                        if abs(p['x']-spec['target']['x'])>.4 or p['z']>spec['target']['z']+.3:reason='approach_outside_verified_strip';break
                        if p['z']>=spec['target']['z'] and abs(p['y']-spec['target']['y'])<.12:
                            success=True;break
                        time.sleep(.05)
                    if not success and not reason:reason='bounded_shield_approach_not_arrived'
    except Exception as e:reason='approach_read_gap:'+type(e).__name__
    finally:
        # Release attempts are distinct from a replay of any uncertain down. Each up is sent at most once.
        if 'key.forward:down' in attempted:key('key.forward','up')
        if 'key.use:down' in attempted:key('key.use','up')
    try:last=c.state();released=trip.fresh_released(last,ctx)
    except Exception:released=False
    result=dict(released=released,effect_known=not uncertain,success=success and released and not uncertain,
                reason=reason or ('shield_approach_arrived_released' if success else 'shield_approach_incomplete'),
                key_attempts=sorted(attempted),uncertain_key_responses=uncertain,state=last)
    c.note('shield_approach_result',**result)
    return result

def validate(plan):
    cfg,steps=trip.validate(plan)
    cfg['require_target_los']=True
    for step in steps:
        action=step['action']
        if step.get('known_tunnel') is not True or action['action']!='follow_path' or len(action['waypoints'])!=1:
            raise idle.Refused('runtime_entry_only_explicit_single_segment_walked_route')
        if action.get('sneak') is not False:raise idle.Refused('actual_descending_route_requires_explicit_sneak_false')
    if idle.distance(steps[-1]['action']['waypoints'][0],cfg['exposure_origin'])>.05:
        raise idle.Refused('final_known_waypoint_must_be_explicit_battle_origin')
    if cfg.get('target_mode')!='closest_blaze_within_3m' or cfg.get('max_seconds')!=15:
        raise idle.Refused('existing_stationary_15s_blaze_mode_required')
    if 'combat_risk_budget' in cfg:raise idle.Refused('use_only_damage_policy_field')
    if 'shield_approach' in plan:
        a=plan['shield_approach']
        if set(a)!={'origin','target','yaw','timeout_seconds'} or a['yaw']!=0 or not 0<a['timeout_seconds']<=5:
            raise idle.Refused('explicit_bounded_south_approach_required')
        if len(steps)<2 or idle.distance(a['origin'],steps[-2]['action']['waypoints'][0])>.05 or idle.distance(a['target'],cfg['exposure_origin'])>.05:
            raise idle.Refused('approach_must_replace_only_final_known_segment')
    if 'pickup_actions' in plan:
        work=plan['pickup_actions']
        if not isinstance(work,list) or not 1<=len(work)<=4:raise idle.Refused('one_to_four_explicit_pickup_actions_required')
        for step in work:
            if not step.get('route_evidence'):raise idle.Refused('pickup_requires_actual_local_route_evidence')
            action=step['action'];trip.validate_step(action)
            if action['action']=='follow_path' and (step.get('known_tunnel') is not True or len(action['waypoints'])!=1):
                raise idle.Refused('pickup_follow_only_single_known_floor_segment')
            if action['action'] not in ('follow_path','break_block','place_block'):raise idle.Refused('pickup_only_existing_ordinary_actions')
    return cfg,steps

def run(c,plan):
    cfg,steps=validate(plan);s=c.state();ctx=cfg['expected_context'];actions=[]
    if not trip.fresh_released(s,ctx) or idle.distance(s['player'],plan['start_anchor'])>.8:
        raise idle.Refused('start_at_actual_room_idle_neutral_current_context')
    if not combat.equipped(s):raise idle.Refused('select_actual_axe_and_offhand_shield_in_room_before_start')
    return_cfg=copy.deepcopy(cfg);return_cfg['waypoints']=[plan['start_anchor']]
    previous_health=idle.health(s);reason=None;initial_rods=rod_count(s)
    policy=DamagePolicy(cfg['damage_policy'],s) if 'damage_policy' in cfg else None
    if policy is not None:c.note('damage_policy_armed',initial_health=previous_health,policy=policy.snapshot())
    danger=lambda frame:policy.observe(frame,time.monotonic()) if policy is not None else trip.guard.danger(frame,previous_health)
    for index,step in enumerate(steps):
        return_cfg['waypoints']=copy.deepcopy(step['return_waypoints'])
        # Wait the existing native readiness, never create or resend an ID while unsettled.
        deadline=time.monotonic()+3
        while True:
            s=c.state()
            if not trip.fresh_released(s,ctx):return report(c,'NEEDS_OPERATOR',reason='outbound_context_or_input_changed',actions=actions)
            reason=danger(s)
            if (c.out/'DISARM').exists():return report(c,'DISARMED',reason='explicit_operator_handoff_idle_neutral',actions=actions,exclusive_owner=False)
            if (c.out/'STOP_FIGHT').exists():reason='operator_stop_outbound_return'
            if reason or idle.native_ready(s):break
            if time.monotonic()>=deadline:reason='outbound_native_wait_bounded_no_post';break
            time.sleep(.1)
        if reason:return retreat(c,return_cfg,s,reason,actions)
        if index==len(steps)-1 and 'shield_approach' in plan:
            outcome=shield_approach(c,plan['shield_approach'],s,ctx,policy,previous_health)
        else:
            body=trip.bind_step(step['action'],s,known_tunnel=True)
            outcome=trip.execute_one(c,body,s,danger_check=danger if policy is not None else None)
        actions.append(outcome)
        if not outcome['released']:return report(c,'NEEDS_OPERATOR',reason=outcome['reason'],actions=actions,exclusive_owner=True)
        if outcome.get('uncertain_key_responses'):return report(c,'NEEDS_OPERATOR',reason='approach_key_response_uncertain_no_reissue',actions=actions,exclusive_owner=True)
        s=c.state()
        if (c.out/'DISARM').exists():
            return report(c,'DISARMED' if trip.fresh_released(s,ctx) else 'NEEDS_OPERATOR',reason='explicit_operator_handoff_after_original_resolution',actions=actions,exclusive_owner=not trip.fresh_released(s,ctx))
        if not outcome['success']:return retreat(c,return_cfg,s,outcome['reason'],actions)
        harm=danger(s)
        if harm:return retreat(c,return_cfg,s,harm,actions)
        previous_health=idle.health(s)
    # No shell/process/import handoff at the firing position. All code was loaded in the room.
    if 'pickup_actions' in plan:
        return pickup_once(c,plan,cfg,policy,previous_health,actions,s,initial_rods)
    c.entities=True
    try:
        fresh=c.state()
        if not trip.fresh_released(fresh,ctx):return report(c,'NEEDS_OPERATOR',reason='combat_handoff_context_or_input_unproven',actions=actions)
        harm=danger(fresh)
        if harm:return retreat(c,cfg,fresh,harm,actions)
        f=combat.Fight(c,copy.deepcopy(cfg),fresh,time.monotonic(),risk_policy=policy)
    except Exception as e:
        # Read-only setup failure may return using a fresh radius0 frame; no fight input was sent.
        c.entities=False;s=c.state();return retreat(c,cfg,s,'combat_preflight:'+type(e).__name__,actions)
    while True:
        try:
            s=c.state();status=f.step(s,time.monotonic(),(c.out/'DISARM').exists(),(c.out/'STOP_FIGHT').exists())
        except Exception as e:
            report(c,'OBSERVATION_UNAVAILABLE',reason=type(e).__name__,exclusive_owner=True)
            if f.uncertain:return report(c,'NEEDS_OPERATOR',reason='combat_input_uncertain_no_reissue',actions=actions)
            # Entities are only needed for fighting, not a fresh bound release/known return.
            # Stop fighting after a read gap; radius0 still requires real current context/input.
            c.entities=False;f.begin_retreat('combat_observation_gap_return')
            try:s=c.state()
            except Exception:return report(c,'NEEDS_OPERATOR',reason='all_fresh_state_unavailable_no_new_input',actions=actions)
            time.sleep(.1);continue
        report(c,'COMBAT',combat=status)
        if f.done:return report(c,'DISARMED',reason='explicit_operator_handoff',actions=actions,combat=status,exclusive_owner=False)
        if f.phase=='RETREATING':return finish_return(c,f.escape,s,f.reason,actions,f.attack_attempts)
        if f.phase=='NEEDS_OPERATOR':return report(c,'NEEDS_OPERATOR',reason=f.reason,actions=actions,combat=status,exclusive_owner=True)
        time.sleep(.1)

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--arm',action='store_true',required=True);p.add_argument('--plan',type=Path,required=True);a=p.parse_args()
    out=N/('room-combat-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+str(uuid.uuid4())[:8]);out.mkdir(mode=0o700)
    c=Client(out);plan=json.loads(a.plan.read_text())
    try:
        s=c.state()
        if not trip.fresh_released(s,idle.context(s)) or s['world'].get('dimension')!='minecraft:the_nether' or idle.distance(s['player'],plan['start_anchor'])>.8:
            raise idle.Refused('fresh_room_neutral_alive_nether_required')
        plan['retreat']['arm']=True;plan['retreat']['expected_context']=idle.context(s)
        validate(plan);c.note('explicit_fresh_bound_plan',plan=plan)
        (out/'PLAN.json').write_text(json.dumps(plan,indent=2)+'\n')
        pointer=N/'ordinary-room-combat-current-run.txt';tmp=pointer.with_suffix('.tmp');tmp.write_text(str(out)+'\n');tmp.replace(pointer)
        print('ROOM_COMBAT_RUN='+str(out),flush=True)
        result=run(c,plan)
    except Exception as e:result=report(c,'NEEDS_OPERATOR',reason=type(e).__name__+':'+str(e),exclusive_owner=True)
    (out/'RESULT.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result),flush=True)
    return 0 if result['phase']=='COVERED_DISARMED' else 2
if __name__=='__main__':raise SystemExit(main())
