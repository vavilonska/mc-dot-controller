"""Durable owner-bound compact telemetry; it never refreshes an execution preflight."""
from copy import deepcopy
from .core import SkillError, require

def capture(runtime, bounds):
    require(set(bounds)<= {'radius'}, 'compact_observation_bounds')
    radius=bounds.get('radius',1)
    require(type(radius) is int and 1<=radius<=2, 'compact_observation_radius')
    with runtime._mutex:
        runtime._control_checkpoint()
        require(runtime._journal['pending'] is None, 'unknown_or_pending_request_blocks_new_work')
        require(runtime._observation_reacquisition is None, 'compact_observation_reacquisition_forbidden')
        session=runtime._session()
        command={'op':'observe','capability_observation':True,'compact_observation':True,'radius':radius}
        record=runtime._reserve('observation',runtime._owned_command(command,session))
        runtime._preflight_request_id=None
        started=runtime.clock();result=runtime._exchange(record)
        try:
            require(result.get('status')=='succeeded', 'compact_observation_failed')
            require(not runtime._unsafe_flags(result), 'compact_observation_requires_handoff')
            from resident_controller.compact_observation import validate
            value,stamp=validate(result['result']['compact_observation'],result['queue_request_id'],radius,
                context=session['capability_context'],prior=getattr(runtime,'_compact_observation_clock',None))
            require(0<=runtime.clock()-started<=runtime.max_age, 'compact_observation_stale')
            require(runtime._session().get('defense_epoch')==session.get('defense_epoch'), 'compact_observation_owner_changed')
        except (ValueError,KeyError,TypeError,SkillError) as exc:
            reason=exc.reason if isinstance(exc,SkillError) else str(exc) or 'compact_observation_invalid'
            runtime._finish(record,'blocked',reason)
            raise SkillError(reason,request_id=record['request_id']) from None
        runtime._compact_observation_clock=stamp
        runtime._finish(record,'succeeded','compact_observation_completed')
        return {'profile':'compact','request_id':record['request_id'],'compact':deepcopy(value),
            'execution_authority':False,'historical':False,'server_confirmed':False,
            'age_ms':max(0,(runtime.clock()-started)*1000),
            'provenance':{'original_request_id':record['request_id'],'queue_request_id':result['queue_request_id'],
                          'grants_dispatch_authority':False}}
