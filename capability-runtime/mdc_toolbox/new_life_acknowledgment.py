"""Durable explicit new-life acknowledgment, outside all gameplay owner leases."""
from copy import deepcopy
import threading
import time
import uuid
from .contracts import API_VERSION,ToolboxError
from resident_controller import new_life_acknowledgment as proof


def runtime_binding(runtime):
    """Process-local cache identity; this is not observation or action authority."""
    last=runtime._last
    return {'runtime_identity':id(runtime),'client_identity':id(runtime.client),'owner_context':runtime.owner_context(),'last_identity':None if last is None else id(last),
        'last_request_id':None if last is None else last.request_id,
        'last_payload_sha256':None if last is None else proof.digest(last.raw),
        'last_tick':runtime._last_tick,'preflight_request_id':runtime._preflight_request_id,
        'last_observation_clock':deepcopy(runtime._last_observation_clock)}

def runtime_idle(backend,runtime,client):
    return (backend.runtime is runtime and runtime.client is client and backend._active is None
        and not backend._quarantined and not runtime.has_unresolved_execution and not runtime._lease_active
        and runtime._job_control is None and runtime._lock_fd is not None
        and runtime._observation_reacquisition is None and runtime.observation_clock_contract is None
        and not runtime._observation_clock_failed
        and getattr(client,'_capability_owner',None) is None and getattr(client,'_capability_fault',None) is None)

def adopt_context(backend,context,p,*,backend_locked=False):
    """Adopt a proven destination only into the unchanged, owner-free Runtime.

    Locks never wait, including exact result lookup during shutdown. No journal,
    sticky capability knowledge, unresolved flag or gameplay owner is changed.
    """
    runtime=backend.runtime;client=runtime.client
    marker={'request_id':context['gateway_request_id'],'session_id':context['gateway_session'],
        'command_sha256':proof.digest(context['life_command']),'accepted_proof_sha256':proof.digest(p),
        'defense_epoch':context['life_command']['expected_defense_epoch']+1}
    def result(ok,reason):return {'adopted':ok,'reason':reason,'gateway_request_id':marker['request_id']}
    acquired=False
    if not backend_locked:
        acquired=backend._lock.acquire(blocking=False)
        if not acquired:return result(False,'runtime_backend_busy')
    try:
        if not runtime._mutex.acquire(blocking=False):return result(False,'runtime_mutex_busy')
        try:
            if proof.exact(getattr(runtime,'_new_life_adoption',None),marker):
                return result(True,'exact_original_already_adopted_no_change')
            prior=getattr(runtime,'_new_life_adoption',None)
            if (type(prior) is dict and prior.get('session_id')==marker['session_id']
                    and prior.get('request_id')==marker['request_id']):
                return result(False,'original_receipt_conflict')
            if (type(prior) is dict and prior.get('session_id')==marker['session_id']
                    and type(prior.get('defense_epoch')) is int and prior['defense_epoch']>=marker['defense_epoch']):
                return result(False,'newer_runtime_lifecycle_already_adopted')
            if not runtime_idle(backend,runtime,client):return result(False,'runtime_owner_or_uncertainty')
            if not proof.exact(runtime_binding(runtime),context.get('runtime_binding')):
                return result(False,'runtime_binding_changed')
            if runtime._session_id not in (None,marker['session_id']):return result(False,'runtime_gateway_changed')
            old=runtime._context;new=p['new_context'];origin=p['origin']['context']
            if old is not None and tuple(old[2:])!=(origin['player_uuid'],origin['action_session']):
                return result(False,'runtime_lifecycle_changed')
            destination=tuple(new[k] for k in ('world_generation','dimension','player_uuid','action_session'))
            floor=p['samples'][-1]['tick']
            if old==destination and runtime._last_tick is not None:floor=max(floor,runtime._last_tick)
            # All validation is pure and complete before these local assignments.
            runtime._context=destination;runtime._last_tick=floor
            runtime._last=None;runtime._preflight_request_id=None;runtime._last_observation_clock=None
            runtime._new_life_adoption=marker
            return result(True,'proven_destination_adopted_fresh_read_required')
        finally:runtime._mutex.release()
    finally:
        if acquired:backend._lock.release()

def pin_receipt(backend,context,receipt,p):
    """First validated original receipt wins across worker/shutdown readers.

    The backend-lifetime lock protects only a small in-memory immutable copy.
    No I/O, owner lock or Runtime lock occurs inside it. Keep the first receipt
    even if local adoption is temporarily busy or its binding later changes.
    """
    key=(context['gateway_session'],context['gateway_request_id'])
    entry={'command_sha256':proof.digest(context['life_command']),
        'receipt_sha256':proof.digest(receipt),'receipt':deepcopy(receipt),'proof':deepcopy(p)}
    with backend._new_life_receipts_lock:
        first=backend._new_life_receipts.get(key)
        if first is None:
            backend._new_life_receipts[key]=entry;first=entry
        conflict=(first['command_sha256']!=entry['command_sha256']
            or first['receipt_sha256']!=entry['receipt_sha256'])
        return deepcopy(first['receipt']),deepcopy(first['proof']),conflict


def outcome(backend,context,receipt,*,backend_locked=False):
    command=context['life_command'];request_id=context['gateway_request_id'];session_id=context['gateway_session']
    p=proof.validate(receipt,command,request_id,session_id)
    retained=context.get('accepted_proof_sha256')
    if retained is not None and retained!=proof.digest(p):raise ValueError('new_life_ack_original_receipt_conflict')
    receipt,p,conflict=pin_receipt(backend,context,receipt,p)
    adoption=({'adopted':False,'reason':'original_receipt_conflict','gateway_request_id':request_id} if conflict else
        adopt_context(backend,context,p,backend_locked=backend_locked) if p['rearmed'] else
        {'adopted':False,'reason':'gateway_refused','gateway_request_id':request_id})
    return {'state':'succeeded' if p['rearmed'] and adoption['adopted'] else 'blocked','effect_certainty':'none_proven',
        'cleanup_certainty':'not_needed','reason':receipt['reason'] if adoption['adopted'] or not p['rearmed'] else 'new_life_ack_runtime_adoption_blocked',
        'request_ids':[request_id],
        'result':{'new_life_acknowledgment':deepcopy(p),'runtime_context_adoption':adoption,
            'new_requests_only':p['rearmed'] and adoption['adopted'],'automatic_task_resume':False},
        'evidence':{'gateway_receipt':deepcopy(receipt)}}

def exchange(backend,context,*,read_only=False):
    runtime=backend.runtime;client=runtime.client;command=context['life_command']
    request_id=context['gateway_request_id'];session_id=context['gateway_session']
    # A result lookup does not erase or re-enter any owner. New admission below
    # must prove that this Runtime and client have no unresolved execution.
    if read_only:
        receipt=client.result(request_id)
        if receipt is not None:return outcome(backend,context,receipt)
        return {'state':'unknown','reason':'new_life_ack_original_receipt_pending_no_retry','effect_certainty':'none_proven',
            'cleanup_certainty':'unknown','request_ids':[request_id]}
    if not backend._lock.acquire(blocking=False):
        return {'state':'blocked','reason':'new_life_ack_backend_busy','effect_certainty':'none_proven','cleanup_certainty':'not_needed','request_ids':[]}
    try:
        if not read_only:
            if not runtime_idle(backend,runtime,client):
                raise ValueError('new_life_ack_runtime_owner_or_uncertainty')
            session=client.session()
            if (session.get('session_id')!=session_id or session.get('new_life_acknowledgment',{}).get('death_ref')!=command['death_ref']
                    or session.get('defense_epoch')!=command['expected_defense_epoch']
                    or not runtime_idle(backend,runtime,client)
                    or not proof.exact(runtime_binding(runtime),context.get('runtime_binding'))):
                return {'state':'blocked','reason':'new_life_ack_local_scope_changed','effect_certainty':'none_proven','cleanup_certainty':'not_needed','request_ids':[]}
            client.submit(command,request_id=request_id)
        deadline=time.monotonic()+6.5
        while True:
            receipt=client.result(request_id)
            if receipt is not None:return outcome(backend,context,receipt,backend_locked=True)
            if read_only or time.monotonic()>=deadline:
                return {'state':'unknown','reason':'new_life_ack_original_receipt_pending_no_retry','effect_certainty':'none_proven',
                    'cleanup_certainty':'unknown','request_ids':[request_id]}
            time.sleep(.025)
    finally:
        backend._lock.release()

def acknowledge(service,args):
    digest=service._digest(args)
    with service._lock:
        existing=service.store.get(request_id=args['request_id'])
        if existing:
            if existing['intent_digest']!=digest:raise ToolboxError('request_conflict','Original acknowledgment identity has a different intent',stage='new_life_ack')
            return service._public_job(existing)
        if service._closing:raise ToolboxError('service_stopping','Service is stopping',stage='new_life_ack')
        if service._busy():raise ToolboxError('owner_busy','All original work must have known terminal cleanup',stage='new_life_ack')
        description=service._description();info=description.get('new_life_acknowledgment',{})
        if (args['session_ref']!=description.get('session_ref') or description.get('private_singleplayer') is not True
                or info.get('version')!=proof.VERSION or info.get('eligible') is not True or info.get('death_ref')!=args['death_ref']):
            raise ToolboxError('policy_violation','Exact verified death and new player instance is not eligible',stage='new_life_ack')
        client=service.backend.runtime.client;session=client.session();now=time.time()
        command=proof.command({'op':proof.OP,'schema_version':1,'death_ref':args['death_ref'],
            'expected_defense_epoch':session['defense_epoch'],'acknowledgment':args['acknowledgment'],'created_at':now,'expires_at':now+5})
        gateway_id='life_'+uuid.uuid4().hex;job_id='job_'+uuid.uuid4().hex
        context={'job_id':job_id,'request_id':args['request_id'],'life_command':command,
            'gateway_request_id':gateway_id,'gateway_session':session['session_id'],
            'runtime_binding':runtime_binding(service.backend.runtime)}
        record={'api_version':API_VERSION,'job_id':job_id,'request_id':args['request_id'],'intent_digest':digest,
            'job_kind':'new_life_acknowledgment','session_ref':args['session_ref'],'capability':'acknowledge_new_life','capability_version':1,
            'build_versions':description.get('build_versions',{}),'context':{'context_ref':description.get('context_ref')},
            'owner_generation':None,'state':'running','phase':'new_life_ack_requested','event_cursor':0,'deadline':now+5,'budgets':{},
            'active_action':None,'request_ids':[gateway_id],'effect_certainty':'none_proven','cleanup_certainty':'pending',
            'confirmed_effects':[],'goal_result':None,'result':None,'evidence':{},'input_release':None,'ownership':None,'error':None,
            'continuation':'none','intent':deepcopy(args),'backend_context':deepcopy(context),'dispatch_started':True,
            'cancel_requested':False,'cancel_sent':False}
        service.store.create(record);service._workers[job_id]=threading.current_thread();service._cancel_events[job_id]=threading.Event()
    try:
        result=exchange(service.backend,context)
        with service._lock:
            if not service._closed:service._apply(job_id,result,'new_life_ack_result')
    except Exception:
        with service._lock:
            if not service._closed:service._unknown(job_id,'Original new-life acknowledgment must be read by exact identity','new_life_ack_unconfirmed')
    finally:
        with service._lock:
            result=(deepcopy(service._closed_records[job_id]) if service._closed else service._public_job(service.store.get(job_id=job_id)))
            service._workers.pop(job_id,None);service._condition.notify_all()
    return result
