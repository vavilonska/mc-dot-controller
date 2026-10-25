"""Durable explicit pause acknowledgment, outside all gameplay owner leases."""
from copy import deepcopy
import threading
import time
import uuid
from .contracts import API_VERSION,ToolboxError
from resident_controller import pause_acknowledgment as proof


def outcome(receipt,command,request_id,session_id):
    p=proof.validate(receipt,command,request_id,session_id)
    return {'state':'succeeded' if p['rearmed'] else 'blocked','effect_certainty':'none_proven',
        'cleanup_certainty':'not_needed','reason':receipt['reason'],'request_ids':[request_id],
        'result':{'pause_acknowledgment':deepcopy(p),'new_requests_only':True,'automatic_task_resume':False},
        'evidence':{'gateway_receipt':deepcopy(receipt)}}

def exchange(backend,context,*,read_only=False):
    runtime=backend.runtime;client=runtime.client;command=context['pause_command']
    request_id=context['gateway_request_id'];session_id=context['gateway_session']
    # A result lookup does not erase or re-enter any owner. New admission below
    # must prove that this Runtime and client have no unresolved execution.
    if read_only:
        receipt=client.result(request_id)
        if receipt is not None:return outcome(receipt,command,request_id,session_id)
        return {'state':'unknown','reason':'pause_ack_original_receipt_pending_no_retry','effect_certainty':'none_proven',
            'cleanup_certainty':'unknown','request_ids':[request_id]}
    if not backend._lock.acquire(blocking=False):
        return {'state':'blocked','reason':'pause_ack_backend_busy','effect_certainty':'none_proven','cleanup_certainty':'not_needed','request_ids':[]}
    try:
        if not read_only:
            if (backend._active is not None or backend._quarantined or runtime.has_unresolved_execution or runtime._lease_active
                    or getattr(runtime,'_job_control',None) is not None
                    or getattr(client,'_capability_owner',None) is not None or getattr(client,'_capability_fault',None)):
                raise ValueError('pause_ack_runtime_owner_or_uncertainty')
            session=client.session()
            if (session.get('session_id')!=session_id or session.get('pause_acknowledgment',{}).get('pause_ref')!=command['pause_ref']
                    or session.get('defense_epoch')!=command['expected_defense_epoch']):
                return {'state':'blocked','reason':'pause_ack_local_scope_changed','effect_certainty':'none_proven','cleanup_certainty':'not_needed','request_ids':[]}
            client.submit(command,request_id=request_id)
        deadline=time.monotonic()+6.5
        while True:
            receipt=client.result(request_id)
            if receipt is not None:return outcome(receipt,command,request_id,session_id)
            if read_only or time.monotonic()>=deadline:
                return {'state':'unknown','reason':'pause_ack_original_receipt_pending_no_retry','effect_certainty':'none_proven',
                    'cleanup_certainty':'unknown','request_ids':[request_id]}
            time.sleep(.025)
    finally:
        backend._lock.release()

def acknowledge(service,args):
    digest=service._digest(args)
    with service._lock:
        existing=service.store.get(request_id=args['request_id'])
        if existing:
            if existing['intent_digest']!=digest:raise ToolboxError('request_conflict','Original acknowledgment identity has a different intent',stage='pause_ack')
            return service._public_job(existing)
        if service._closing:raise ToolboxError('service_stopping','Service is stopping',stage='pause_ack')
        if service._busy():raise ToolboxError('owner_busy','All original work must have known terminal cleanup',stage='pause_ack')
        description=service._description();info=description.get('pause_acknowledgment',{})
        if (args['session_ref']!=description.get('session_ref') or description.get('private_singleplayer') is not True
                or info.get('version')!=proof.VERSION or info.get('eligible') is not True or info.get('pause_ref')!=args['pause_ref']):
            raise ToolboxError('policy_violation','Exact clean idle pause is not eligible',stage='pause_ack')
        client=service.backend.runtime.client;session=client.session();now=time.time()
        command=proof.command({'op':proof.OP,'schema_version':1,'pause_ref':args['pause_ref'],
            'expected_defense_epoch':session['defense_epoch'],'acknowledgment':args['acknowledgment'],'created_at':now,'expires_at':now+5})
        gateway_id='pause_'+uuid.uuid4().hex;job_id='job_'+uuid.uuid4().hex
        context={'job_id':job_id,'request_id':args['request_id'],'pause_command':command,
            'gateway_request_id':gateway_id,'gateway_session':session['session_id']}
        record={'api_version':API_VERSION,'job_id':job_id,'request_id':args['request_id'],'intent_digest':digest,
            'job_kind':'pause_acknowledgment','session_ref':args['session_ref'],'capability':'acknowledge_pause','capability_version':1,
            'build_versions':description.get('build_versions',{}),'context':{'context_ref':description.get('context_ref')},
            'owner_generation':None,'state':'running','phase':'pause_ack_requested','event_cursor':0,'deadline':now+5,'budgets':{},
            'active_action':None,'request_ids':[gateway_id],'effect_certainty':'none_proven','cleanup_certainty':'pending',
            'confirmed_effects':[],'goal_result':None,'result':None,'evidence':{},'input_release':None,'ownership':None,'error':None,
            'continuation':'none','intent':deepcopy(args),'backend_context':deepcopy(context),'dispatch_started':True,
            'cancel_requested':False,'cancel_sent':False}
        service.store.create(record);service._workers[job_id]=threading.current_thread();service._cancel_events[job_id]=threading.Event()
    try:
        result=exchange(service.backend,context)
        with service._lock:
            if not service._closed:service._apply(job_id,result,'pause_ack_result')
    except Exception:
        with service._lock:
            if not service._closed:service._unknown(job_id,'Original pause acknowledgment must be read by exact identity','pause_ack_unconfirmed')
    finally:
        with service._lock:
            result=(deepcopy(service._closed_records[job_id]) if service._closed else service._public_job(service.store.get(job_id=job_id)))
            service._workers.pop(job_id,None);service._condition.notify_all()
    return result
