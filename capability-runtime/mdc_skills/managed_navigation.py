"""One real walking waypoint, one original owner, no automatic task resume."""
from copy import deepcopy
import math
import uuid
from .core import Outcome,SkillError,require
VERSION='managed-navigation-owner-control/1'
def _source(runtime,before,context):
    """Only the original owner-bound authoritative read can authorize start."""
    from resident_controller.external_navigation_control import CONTEXT,validate_external_proof
    runtime._fresh(before)
    require(before.context==tuple(context[k] for k in CONTEXT),'managed_navigation_source_context_changed')
    try:proof=validate_external_proof(before.state.get('external_controller'),context,settled=True)
    except (ValueError,KeyError,TypeError) as exc:
        raise SkillError('managed_navigation_source_proof_invalid') from exc
    require(proof['source_tick']==before.tick,'managed_navigation_source_tick_changed')
    # Conservative local elapsed time starts before the owned read was sent.
    # Java remains authoritative for its original nano clock and five-tick bound.
    require(0<=runtime.clock()-before.captured_at<=.75,'managed_navigation_source_acquisition_stale')
    return {k:proof[k] for k in ('source_tick','source_nano')}

def _start_binding(runtime,control,binding,before,session):
    require(before is not None,'managed_navigation_owned_source_required')
    owner=runtime.owner_context()
    require(binding['control_owner']=={k:owner[k] for k in ('owner_id','owner_generation')}|{'job_id':control.job_id}
        and binding['expected_context']==runtime._lease_info['context']
        and before._gateway_epoch==session['defense_epoch'],'managed_navigation_source_owner_changed')
    require(binding['source']==_source(runtime,before,binding['expected_context']),
        'managed_navigation_source_binding_changed')

def exchange(runtime,control,operation,binding,*,before=None):
    from resident_controller.managed_navigation_control import validate_status
    with runtime._mutex:
        control.checkpoint();require(not runtime.has_unresolved_execution,'managed_navigation_original_request_unknown')
        session=runtime._session();require(session.get('managed_navigation_owner_control')==VERSION,'managed_navigation_transport_unavailable')
        if operation=='start':_start_binding(runtime,control,binding,before,session)
        body={'op':'managed_navigation_control','operation':operation,**deepcopy(binding)}
        control.consume('observations' if operation=='status' else 'actions')
        record=runtime._reserve('managed_navigation_control',runtime._owned_command(deepcopy(body),session),skill='navigate_managed_walk',before=before)
        try:
            control.checkpoint();reason=control.stop_reason() if control.lane!='cleanup' else None
            if reason:raise SkillError(reason,status='cancelled' if reason=='cancel_requested' else 'interrupted')
            if operation=='start':_start_binding(runtime,control,binding,before,session)
        except SkillError as exc:
            runtime._finish(record,exc.status,exc.reason,{'submission_outcome':'stopped_before_dispatch'});raise
        prior=runtime._job_effect_certainty
        if operation!='status':runtime._job_effect_certainty='unknown'
        try:result=runtime._exchange(record,before=before)
        except SkillError:
            # _exchange's pure final age guard can still stop this unsubmitted
            # start. Never clear uncertainty once transport may have started.
            if operation=='start' and record.get('status')=='blocked' and record.get('reason')=='preflight_observation_stale':
                runtime._job_effect_certainty=prior
            raise
        if result.get('status')!='succeeded':runtime._unknown(record,'managed_navigation_control_unconfirmed')
        try:
            require(result.get('control_owner')==binding['control_owner'],'managed_navigation_owner_receipt_changed')
            checked=validate_status(result.get('result'),{**body,'expected_resident_session':runtime._lease_info['resident_session'],
                'request_id':record['request_id'],'session_id':runtime._lease_info['resident_session'],'submitted_at':0},
                getattr(control,'managed_navigation_last_status',None))
            control.managed_navigation_last_status=deepcopy(checked)
        except (ValueError,KeyError,TypeError,SkillError):runtime._unknown(record,'managed_navigation_native_status_unconfirmed')
        runtime._finish(record,'succeeded','managed_navigation_'+operation+'_observed',checked)
        control.emit('managed_navigation_status',{'native':checked,'original_operation_id':binding['operation_id']})
        return checked

def navigate(runtime,control,*,goal,max_distance=200,timeout_ms=60000,min_health=12):
    require(runtime.required_execution_policy=='request_only' and runtime._owner_mode=='ordinary','managed_navigation_ordinary_owner_required')
    require(type(timeout_ms) is int and 1000<=timeout_ms<=120000,'managed_navigation_timeout')
    require(control.budget.remaining_seconds()>=timeout_ms/1000+15,'managed_navigation_deadline_too_short')
    require(control.budget.snapshot()['remaining']['observations']>=math.ceil(timeout_ms/250)+45,'managed_navigation_full_poll_budget_required')
    runtime._session()  # Acquire this ordinary owner once, before the read.
    context=deepcopy(runtime._lease_info['context'])
    before=runtime.observe(entity_radius=8,_context=tuple(context[k] for k in
        ('world_generation','dimension','player_uuid','action_session')))
    source=_source(runtime,before,context);owner=runtime.owner_context()
    binding={'operation_id':uuid.uuid4().hex,'control_owner':{k:owner[k] for k in ('owner_id','owner_generation')},
        'expected_context':context,'source':{k:source.get(k) for k in ('source_tick','source_nano')},
        'goal':deepcopy(goal),'max_distance':max_distance,'timeout_ms':timeout_ms,'min_health':min_health}
    binding['control_owner']['job_id']=control.job_id
    control.emit('managed_navigation_source',{'request_id':before.request_id,'source':deepcopy(source),
        'owner_id':before._owner,'defense_epoch':before._gateway_epoch,'acquisition_age_ms':(runtime.clock()-before.captured_at)*1000})
    control.emit('managed_navigation_reserved',deepcopy(binding));last=exchange(runtime,control,'start',binding,before=before)
    deadline=runtime.clock()+timeout_ms/1000+11;cancelled=False
    # The cleanup lane only polls or cancels this original route. Native deadlines
    # remain unchanged and UNKNOWN exits immediately without replay.
    with control.cleanup():
        while last['state']!='settled' and runtime.clock()<deadline:
            if control.stop_reason() and not cancelled:
                cancelled=True;last=exchange(runtime,control,'cancel',binding)
            else:
                runtime.sleeper(.25);last=exchange(runtime,control,'status',binding)
    if last['state']!='settled':
        runtime._job_effect_certainty='unknown'
        return Outcome('unknown','managed_navigation_actual_idle_unconfirmed',evidence={'native':last})
    runtime._job_effect_certainty='known' if last['start_attempted'] else 'none_proven'
    stopped=control.stop_reason()
    goal_success=last['goal_reached'] and last['reason']=='managed_navigation_goal_observed' and not last['stop_attempted']
    status='cancelled' if stopped=='cancel_requested' else 'succeeded' if not stopped and goal_success else 'interrupted'
    return Outcome(status,stopped or last['reason'],evidence={'native':last,'physical_safe':None,'unloaded_terrain_certified':False,'no_auto_resume':True})
