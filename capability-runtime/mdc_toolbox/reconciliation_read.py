"""Public explicit lease-free diagnostics; this module never calls Runtime work."""
from copy import deepcopy
import time
from .contracts import ToolboxError,API_VERSION
from .serialization import public_data

def original_summary(record):
    ids=record.get('request_ids',[])
    owner=record.get('context',{}).get('owner_context') or {}
    # A bounded tail is labeled as incomplete, with exact job/request identity
    # retained for the existing full original-status/reconcile APIs.
    return {k:deepcopy(record.get(k)) for k in ('job_id','request_id','session_ref','state','phase','effect_certainty','cleanup_certainty','owner_generation','continuation')} | {
        'owner_id':owner.get('owner_id'),'owner_gateway_session':owner.get('gateway_session'),
        'original_world_context':deepcopy(owner.get('world_context')),
        'request_ids':deepcopy(ids[-32:]),'request_ids_total':len(ids),'request_ids_omitted':max(0,len(ids)-32),
        'request_ids_complete':len(ids)<=32,'status_lookup':{'job_id':record['job_id'],'session_ref':record['session_ref']}}

def observe(service,args):
    if (type(args.get('original_job_id')) is not str or args.get('selectors') or args.get('bounds') not in (None,{}, {'radius':1})
            or 'acquisition_profile' in args or args.get('wait_ms',0)!=0):
        raise ToolboxError('invalid_request','Reconciliation requires original_job_id and fixed radius1; no selectors, acquisition or wait override',stage='observation')
    with service._lock:
        if service._closing:raise ToolboxError('service_stopping','Service is stopping',stage='observation')
        record=service.store.get(job_id=args['original_job_id'])
        if record is None or record['session_ref']!=args['session_ref']:
            raise ToolboxError('context_changed','Original job/session identity is not retained',stage='observation')
        if service.store.get(request_id=args['request_id']) is not None:
            raise ToolboxError('request_conflict','Diagnostic request ID is already an execution identity',stage='observation')
        before=original_summary(record)
    method=getattr(service.backend,'reconciliation_read',None)
    if not callable(method):raise ToolboxError('observation_unavailable','Explicit reconciliation reader unavailable',stage='observation')
    result=public_data(method(args['request_id'],args['session_ref'],args['original_job_id']))
    with service._lock:
        after=(service._closed_records.get(args['original_job_id']) if service._closed else service.store.get(job_id=args['original_job_id']))
        after=original_summary(after) if after else None
    return {'api_version':API_VERSION,'profile':'reconciliation','request_id':args['request_id'],
        'session_ref':args['session_ref'],'original_job_id':args['original_job_id'],'lease_free':True,
        'read_only':True,'execution_authority':False,'executable_authority':False,'server_confirmed':False,
        'settles_original':False,'original_before':before,'original_after':after,'diagnostic':result,
        'warnings':['Read-only current context cannot settle, retry, resume or release the original unknown owner.']}

def _capture(backend,request_id,session_ref,original_job_id):
    from .runtime_adapter import _ref
    from resident_controller.compact_observation import validate
    client=backend.runtime.client
    session=client.reconciliation_session()
    # The original retained job may belong to an older gateway/world. A new
    # diagnostic may show current context, but never reconciles those epochs.
    current_session_ref=_ref(session['session_id'])
    request=client.reconciliation_submit(request_id,session['session_id'],original_job_id)
    deadline=time.monotonic()+5.5
    while True:
        result=client.reconciliation_result(request)
        if result is not None:break
        if time.monotonic()>=deadline:
            return {'state':'unknown','reason':'diagnostic_read_wait_expired_no_replay','request':request,
                'execution_authority':False,'settles_original':False}
        time.sleep(.025)
    if result.get('state')=='succeeded':
        try:
            value=result['result']['compact']
            validate(value,result['queue_request_id'],1)
        except (ValueError,KeyError,TypeError):
            return {'state':'unknown','reason':'diagnostic_wire_unconfirmed','request':request,
                'execution_authority':False,'settles_original':False}
    result['current_session_ref']=current_session_ref
    result['original_session_ref']=session_ref
    result['session_changed']=current_session_ref!=session_ref
    result['age_ms']=max(0,(time.time()-result['completed_at'])*1000)
    result['historical']=result['age_ms']>1000
    return result


def capture(backend,request_id,session_ref,original_job_id):
    try:return _capture(backend,request_id,session_ref,original_job_id)
    except (ValueError,OSError,KeyError,TypeError,AttributeError) as exc:
        import re
        code=str(exc)
        reason=code if re.fullmatch(r'reconciliation_[a-z_]{1,100}',code) else 'reconciliation_read_unconfirmed_'+type(exc).__name__
        return {'state':'unknown','reason':reason,'request_id':request_id,
            'read_only':True,'execution_authority':False,'settles_original':False}
