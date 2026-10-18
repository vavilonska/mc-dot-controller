"""Explicit retained-original authority release. UNKNOWN semantic history stays immutable."""
from copy import deepcopy
import time
import uuid
from resident_controller import fall_rescue_adjudication_wire as wire
from resident_controller.fall_rescue_attached import exact,digest


def prepare(runtime,context):
    owner=context.get('owner_context',{})
    wire.require(runtime._job_control is not None and runtime._job_control.job_id==context['job_id']
        and runtime._owner==owner.get('owner_id') and runtime._job_generation==owner.get('owner_generation'),
        'fall_adjudication_runtime_original_owner_changed')
    rid=runtime.pending_request_id
    wire.require(rid is not None and runtime._journal.get('semantic_pending') in (None,rid))
    record=runtime._journal['records'][rid]
    wire.require(record.get('job_id')==context['job_id'] and record.get('status')=='unknown'
        and record.get('kind')=='mutation' and 'fall_rescue_policy' in record['command'])
    raw=runtime._read_evidence(record['receipt_ref'],'receipt')
    wire.require(raw.get('request_id')==rid and raw.get('session_id')==record['gateway_session']==runtime._session_id)
    receipt={**raw,'request_id':raw.get('queue_request_id'),'session_id':raw.get('queue_session_id')}
    seal=receipt.get('fall_rescue',{});b=seal.get('binding',{})
    selected={'original_intent_id':rid,'original_request_id':receipt['request_id'],'resident_session':receipt['session_id'],
        'owner_id':runtime._owner,'owner_generation':runtime._job_generation,'job_id':context['job_id'],
        'original_defense_epoch':b.get('defense_epoch'),'expected_context':b.get('context'),
        'original_receipt_sha256':seal.get('sha256')}
    checked=wire.original(receipt,selected)
    wire.require(record['command'].get('_capability_owner_id')==runtime._owner)
    return record,selected,checked


def execute(runtime,context,args):
    with runtime._mutex:
        runtime._open();items=runtime._journal.setdefault('fall_adjudications',{})
        identity=args.get('adjudication_request_id');entry=items.get(identity)
        if entry and entry.get('state')=='authority_released':
            wire.require(entry['job_id']==context['job_id'] and args.get('original_receipt_sha256')==entry['selector']['original_receipt_sha256']
                and args.get('acknowledgment')==wire.ACK)
            return deepcopy(entry['public_proof'])
        record,selected,sealed=prepare(runtime,context)
        if args['operation']=='adjudication_prepare':
            return {'schema_version':1,'eligible':True,'selector':selected,'acknowledgment_required':wire.ACK,
                'original_effects':'unknown','no_auto_resume':True,'current_release_proof_observed':False,'scope':'ended_confirmed_attached_rescue'}
        wire.require(wire.identifier(identity) and args.get('acknowledgment')==wire.ACK
            and args.get('original_receipt_sha256')==selected['original_receipt_sha256'])
        if entry:
            wire.require(exact(entry['selector'],selected) and entry['job_id']==context['job_id'])
        else:
            wire.require(args['operation']=='adjudicate' and len(items)<128
                and not any(v.get('state')!='authority_released' for v in items.values()),
                'fall_adjudication_original_id_required')
            entry={'job_id':context['job_id'],'selector':deepcopy(selected),'state':'reserved','controls':[]}
            items[identity]=entry;runtime._save()
        previous=entry['controls'][-1] if entry['controls'] else None
        result=runtime.client.result(previous['id']) if previous else None
        if previous and result is None:
            result=runtime.client.wait(previous['id'],timeout=min(3,runtime.wait_timeout))
        if previous is not None:
            wire.require(type(result) is dict and result.get('request_id')==previous['id']
                and result.get('session_id')==runtime._session_id,'fall_adjudication_original_control_identity_unconfirmed')
        continuing_first_write=(previous is not None and args['operation']=='adjudicate' and wire.no_write_result(result,identity,selected))
        if (not previous or continuing_first_write or args['operation']=='adjudication_status'
                and result is not None and result.get('status') not in ('succeeded','pending')):
            wire.require(len(entry['controls'])<64,'fall_adjudication_read_capacity')
            control={'id':uuid.uuid4().hex,'operation':'capability_fall_adjudicate' if not previous or continuing_first_write else 'capability_fall_adjudication_status'}
            entry['controls'].append(control);entry['state']='control_attempted';runtime._save()
            command={'op':control['operation'],'adjudication_id':identity,'selector':deepcopy(selected),'acknowledgment':wire.ACK}
            wire.require(runtime.client.submit(command,request_id=control['id'])==control['id'])
            result=runtime.client.wait(control['id'],timeout=min(3,runtime.wait_timeout));previous=control
        wire.require(type(result) is dict and result.get('request_id')==previous['id']
            and result.get('session_id')==runtime._session_id,'fall_adjudication_gateway_receipt_identity')
        entry['last_control_result']=deepcopy(result);runtime._save()
        if wire.no_write_result(result,identity,selected):
            raise wire.NativeWriteNotAttempted('fall_adjudication_native_write_never_attempted_explicit_same_id_commit_allowed')
        wire.require(result.get('status')=='succeeded' and result.get('gateway_authority_released') is True
            and result.get('explicit_new_job_only') is True,'fall_adjudication_pending_or_unconfirmed_use_original_id_status')
        a=result.get('adjudication',{})
        wire.require(exact(a.get('selector'),selected) and a.get('adjudication_id')==identity
            and a.get('authority_released') is True and a.get('original_effects')=='unknown' and a.get('no_auto_resume') is True)
        wire.native_result(a['native_result'],a['native_request'],sealed)
        wire.require(a['native_request']['adjudication_id']==identity)
        # The gateway proof binds its release to a fresh native read. This local
        # settlement cannot replay gameplay; a later job still requires fresh admission.
        current=runtime.client._read_session()
        wire.require(current.get('session_id')==runtime._session_id and current.get('capability_lease') is None
            and current.get('active_request_id') is None and current.get('handoff_latched') is False
            and current.get('input_release_latched') is False and current.get('explicit_new_job_only') is True
            and current.get('state')=='ready' and current.get('stopped') is False)
        again,sel2,_=prepare(runtime,context);wire.require(again is record and exact(sel2,selected))
        proof={'schema_version':1,'adjudication_request_id':identity,'original_receipt_sha256':selected['original_receipt_sha256'],
            'original_job_id':context['job_id'],'authority_released':True,'original_effects':'unknown','no_auto_resume':True,
            'explicit_new_job_only':True,'native_proof':deepcopy(a['native_result']['receipt'])}
        # Archive acknowledgment separately; original UNKNOWN receipt/status remains unchanged.
        entry.update(state='release_proven',public_proof=proof);runtime._save()
        runtime.client.adjudication_release_local(runtime._owner,runtime._session_id)
        record['authority_adjudication']=deepcopy(proof)
        runtime._journal['pending']=None;runtime._journal['semantic_pending']=None
        runtime._lease_active=False;runtime._job_control=None;runtime._job_scoped_profiles={}
        entry['state']='authority_released';runtime._save()
        return deepcopy(proof)
