"""One explicit safe cancellation request, then actual native idle verification."""
from copy import deepcopy
import math
import uuid
from .core import Outcome,SkillError,require
VERSION='external-navigation-owner-control/1'

def exchange(runtime,control,operation,binding):
    from resident_controller.external_navigation_control import validate_status
    with runtime._mutex:
        control.checkpoint()
        require(not runtime.has_unresolved_execution,'external_navigation_original_request_unknown')
        session=runtime._session()
        require(session.get('external_navigation_owner_control')==VERSION,'external_navigation_transport_unavailable')
        body={'op':'external_navigation_control','operation':operation,**deepcopy(binding)}
        control.consume('actions' if operation=='stop' else 'observations')
        record=runtime._reserve('external_navigation_control',runtime._owned_command(deepcopy(body),session),skill='stop_external_navigation')
        try:
            control.checkpoint()
            reason=control.stop_reason() if control.lane!='cleanup' else None
            if reason:raise SkillError(reason,status='cancelled' if reason=='cancel_requested' else 'interrupted')
        except SkillError as exc:
            runtime._finish(record,exc.status,exc.reason,{'submission_outcome':'stopped_before_dispatch'})
            raise
        if operation=='stop':runtime._job_effect_certainty='unknown'
        result=runtime._exchange(record)
        if result.get('status')!='succeeded':runtime._unknown(record,'external_navigation_control_unconfirmed')
        try:
            require(result.get('control_owner')==binding['control_owner'],'external_navigation_owner_receipt_changed')
            checked=validate_status(result.get('result'),{**body,'expected_resident_session':runtime._lease_info['resident_session'],
                'request_id':record['request_id'],'session_id':runtime._lease_info['resident_session'],'submitted_at':0},
                getattr(control,'external_navigation_last_status',None))
            control.external_navigation_last_status=deepcopy(checked)
        except (ValueError,KeyError,TypeError,SkillError):runtime._unknown(record,'external_navigation_native_status_unconfirmed')
        runtime._finish(record,'succeeded','external_navigation_'+operation+'_observed',checked)
        control.emit('external_navigation_status',{'native':checked,'original_operation_id':binding['operation_id']})
        return checked

def stop(runtime,control,*,timeout_ms=5000):
    require(type(timeout_ms) is int and 1000<=timeout_ms<=10000,'external_navigation_timeout')
    require(runtime.required_execution_policy=='request_only' and runtime._owner_mode=='external_stop','external_navigation_stop_only_owner_required')
    require(control.budget.remaining_seconds()>=timeout_ms/1000+3,'external_navigation_deadline_too_short')
    require(control.budget.snapshot()['remaining']['observations']>=math.ceil(timeout_ms/100)+3,'external_navigation_full_poll_budget_required')
    runtime._session()  # Acquire once; the original read may drain before acknowledgement.
    session=runtime._session();source=session.get('external_navigation_source',{})
    context=deepcopy(runtime._lease_info['context']);owner=runtime.owner_context()
    binding={'operation_id':uuid.uuid4().hex,'control_owner':{k:owner[k] for k in ('owner_id','owner_generation')},
        'expected_context':context,'source':{k:source.get(k) for k in ('source_tick','source_nano')},'timeout_ms':timeout_ms}
    binding['control_owner']['job_id']=control.job_id
    control.emit('external_navigation_reserved',deepcopy(binding))
    last=exchange(runtime,control,'stop',binding)
    deadline=runtime.clock()+timeout_ms/1000+.5
    # Cancel requests never send another native stop. The same owner may finish
    # bounded verification of its original cancellation before releasing.
    with control.cleanup():
        while last['state']!='settled' and runtime.clock()<deadline:
            runtime.sleeper(.1)
            last=exchange(runtime,control,'status',binding)
    if last['state']!='settled':
        runtime._job_effect_certainty='unknown'
        return Outcome('unknown','external_navigation_idle_not_confirmed',evidence={'native':last})
    runtime._job_effect_certainty='known' if last['stop_attempted'] else 'none_proven'
    return Outcome('cancelled' if control.stop_reason() else 'succeeded',
        'external_navigation_actual_idle_observed',evidence={'native':last,'physical_safe':None,'no_auto_resume':True})
