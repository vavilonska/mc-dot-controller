"""Exact original-owner release through the single gateway loop; no action replay."""
from copy import deepcopy
import time
import uuid
from resident_controller import fall_rescue_adjudication_wire as wire
from resident_controller.fall_rescue_attached import exact,digest
from resident_controller.ipc import atomic_json,read_json

OPS=frozenset({'capability_fall_adjudicate','capability_fall_adjudication_status'})

def validate(command):
    wire.require(type(command) is dict and set(command)=={'op','adjudication_id','selector','acknowledgment'}
        and command['op'] in OPS and wire.identifier(command['adjudication_id']) and command['acknowledgment']==wire.ACK)
    return wire.selector(command['selector'])

def entries(dog):
    if not hasattr(dog,'_fall_adjudications'):
        path=dog.capability_directory/'fall-adjudications.json'
        dog._fall_adjudications=read_json(path,2*1024*1024) if path.exists() else {}
        wire.require(type(dog._fall_adjudications) is dict and len(dog._fall_adjudications)<=128)
    return dog._fall_adjudications

def save(dog):atomic_json(dog.capability_directory/'fall-adjudications.json',entries(dog))

def scope(dog,s,entry):
    if (dog.stop_requested or dog.stopped or dog.input_release_latched or dog.rpc
        or getattr(dog,'_coordination_owner',None) is not None or dog.started_target
        or getattr(dog,'ranged_move',None) or getattr(getattr(dog,'environment',None),'active',False)):
        return False
    if entry and entry.get('state') in ('release_prepared','authority_released') and dog.capability_lease is None:
        return (dog.capability_lease is None and dog.owner is None and not dog.handoff_latched
            and dog.armed and dog.defense_epoch==entry['released_defense_epoch']
            and getattr(dog,'explicit_after_adjudication',False))
    lease=dog.capability_lease;owner=dog.owner
    return (lease is not None and owner is not None and lease.get('state')=='paused'
        and lease.get('reason')=='capability_owner_outcome_unconfirmed' and dog.handoff_latched
        and not dog.armed and dog.phase=='needs_operator' and dog.reason=='capability_owner_outcome_unconfirmed'
        and lease['owner_id']==s['owner_id'] and lease['resident_session']==s['resident_session']
        and lease['defense_epoch']==s['original_defense_epoch'] and dog.defense_epoch==s['original_defense_epoch']+1
        and exact(lease['context'],s['expected_context']) and owner.get('reported') is True
        and owner.get('id')==s['original_intent_id'] and owner.get('request_id')==s['original_request_id']
        and owner.get('capability_owner')==s['owner_id'] and owner.get('resident_session')==s['resident_session'])

def submit(dog,intent_id,command):
    try:
        s=validate(command);identity=command['adjudication_id'];items=entries(dog);entry=items.get(identity)
        wire.require(scope(dog,s,entry),'fall_adjudication_gateway_original_scope_changed')
        receipt=dog.q.result(s['original_request_id']);sealed=wire.original(receipt,s)
        if entry is not None:
            wire.require(exact(entry['selector'],s) and entry['original_digest']==digest(receipt),
                'fall_adjudication_original_attempt_changed')
            wire.require(entry.get('pending') is None,'fall_adjudication_read_already_pending')
            wire.require(command['op']=='capability_fall_adjudication_status' or entry.get('native_write_never_attempted_proven') is True,
                'fall_adjudication_use_original_id_status')
        else:
            wire.require(command['op']=='capability_fall_adjudicate','fall_adjudication_original_attempt_not_found')
            wire.require(len(items)<128 and not any(x.get('state')!='authority_released' for x in items.values()),
                'fall_adjudication_other_attempt_or_capacity')
            entry={'selector':deepcopy(s),'original_digest':digest(receipt),'state':'reserved'};items[identity]=entry
        session=dog.q.session()
        wire.require(session.get('session_id')==s['resident_session'] and session.get('active_request_id') is None
            and session.get('pending')==0,'fall_adjudication_resident_not_same_idle_owner')
        qid=uuid.uuid4().hex
        body={'op':'fall_rescue_adjudicate','operation':'commit' if command['op']=='capability_fall_adjudicate' else 'status',
            'adjudication_id':identity,'selector':deepcopy(s),'acknowledgment':wire.ACK}
        entry['pending']={'intent_id':intent_id,'queue_request_id':qid};entry['native_write_never_attempted_proven']=False;save(dog)
        wire.require(scope(dog,s,entry),'fall_adjudication_gateway_scope_changed_before_queue')
        # The queue identity is durable before its single write. Failure never resubmits it.
        wire.require(dog.q.submit(body,request_id=qid)==qid,'fall_adjudication_queue_identity_changed')
        return True
    except (ValueError,KeyError,TypeError,OSError) as exc:
        return dog.capability_complete(intent_id,'uncertain','fall_adjudication_unconfirmed:'+str(exc)[:160])

def tick(dog):
    items=getattr(dog,'_fall_adjudications',{})
    for identity,entry in items.items():
        pending=entry.get('pending')
        if not pending:continue
        result=dog.q.result(pending['queue_request_id'])
        if result is None:return True
        good=False
        try:
            s=entry['selector'];original_lease=dog.capability_lease;original_owner=dog.owner
            wire.require(scope(dog,s,entry),'fall_adjudication_gateway_scope_changed_after_read')
            original=dog.q.result(s['original_request_id']);wire.require(digest(original)==entry['original_digest'])
            sealed=wire.original(original,s);a=result.get('adjudication',{})
            if (result.get('request_id')==pending['queue_request_id'] and result.get('session_id')==s['resident_session']
                    and wire.no_write_result(result,identity,s)):
                entry['native_write_never_attempted_proven']=True
            wire.require(result.get('request_id')==pending['queue_request_id'] and result.get('session_id')==s['resident_session']
                and result.get('status')=='succeeded' and exact(a.get('selector'),s)
                and a.get('adjudication_id')==identity and a.get('original_effects')=='unknown'
                and a.get('no_auto_resume') is True and a.get('authority_released') is True)
            wire.native_result(a['native_result'],a['native_request'],sealed)
            wire.require(a['native_request']['adjudication_id']==identity)
            received=result.get('proof_received_monotonic')
            wire.require(type(received) in (int,float) and 0<=time.monotonic()-received<=1)
            session=dog.q.session();policy=session.get('resident_policy',{})
            wire.require(session.get('session_id')==s['resident_session'] and session.get('state')=='ready'
                and session.get('pending')==0 and session.get('active_request_id') is None
                and policy.get('requires_handoff') is False and policy.get('input_release_unconfirmed') is False)
            wire.require(scope(dog,s,entry) and time.monotonic()-received<=1)
            # Checkpoint before releasing exactly this owner. No old receipt is overwritten.
            entry['state']='release_prepared';entry['released_defense_epoch']=dog.defense_epoch
            entry['proof']=deepcopy(a);save(dog)
            atomic_json(dog.capability_directory/'explicit-after-adjudication.json',{'schema_version':1,'explicit_new_job_only':True})
            # Durable writes may block. Re-sample the Resident after them, then fence
            # exact local owner objects and proof age immediately before release.
            final_session=dog.q.session();final_policy=final_session.get('resident_policy',{})
            wire.require(final_session.get('session_id')==s['resident_session'] and final_session.get('state')=='ready'
                and final_session.get('pending')==0 and final_session.get('active_request_id') is None
                and final_policy.get('requires_handoff') is False and final_policy.get('input_release_unconfirmed') is False)
            wire.require(entries(dog).get(identity) is entry and entry.get('pending') is pending
                and dog.capability_lease is original_lease and dog.owner is original_owner
                and scope(dog,s,entry) and 0<=time.monotonic()-received<=1,
                'fall_adjudication_final_gateway_scope_or_proof_changed')
            dog.capability_lease=None;dog.owner=None;dog.handoff_latched=False
            dog.armed=True;dog.explicit_after_adjudication=True;dog.recover_observation=False
            dog.phase='watching';dog.reason='fall_adjudication_explicit_new_job_only'
            dog.latest=None;dog.observed_at=None;dog.next_observe=0
            # A checkpoint failure retains the durable old owner and the immutable
            # original UNKNOWN. Same-ID reads can finish this release later.
            dog.capability_checkpoint(None)
            entry['state']='authority_released'
            good=True
        except (ValueError,KeyError,TypeError,OSError):pass
        entry['pending']=None;save(dog)
        dog.completed.append({'intent_id':pending['intent_id'],'session_id':dog.session_id,
            'queue_request_id':pending['queue_request_id'],'result':{**result,
                'status':'succeeded' if good else 'uncertain',
                'reason':'fall_adjudication_authority_released_original_unknown' if good else 'fall_adjudication_release_unconfirmed',
                'gateway_authority_released':good,'explicit_new_job_only':good}})
        return True
    return False
