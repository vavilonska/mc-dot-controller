"""Closed attached policy compiled inside the existing ordinary owner thread."""
from copy import deepcopy
from .core import require

def attach(runtime, body, before, original_timeout):
    control=runtime._job_control
    policy=getattr(control,'fall_rescue_policy',None) if control else None
    if policy is None:return body
    from resident_controller.fall_rescue_attached import VERSION,RESERVE_MS,PROFILES,POLICY,validate_envelope,exact
    require(exact(policy,POLICY),'fall_rescue_closed_policy_required')
    action=body['action']
    # Explicitly disclosed setup steps are not guarded. No general hazard takeover.
    if action in ('select_hotbar','click_slot','close_menu'):return body
    require(action in ('follow_path','combat_entity'),'fall_rescue_action_not_supported')
    scope=body.get('scoped_native_preflight',{})
    require(scope.get('profile') in PROFILES,'fall_rescue_scoped_profile_not_supported')
    require(control.budget.remaining_seconds()*1000 >= original_timeout+RESERVE_MS+2000,
            'fall_rescue_full_action_and_rescue_deadline_required')
    require(body['timeout_ms']==original_timeout,'fall_rescue_action_timeout_must_not_be_shortened')
    feature=before.state.get('native_fall_rescue',{});status=before.state.get('native_fall_rescue_status',{})
    require(feature.get('schema_version')==1 and feature.get('native_fences_ready') is True
            and feature.get('external_controller_unknown') is False,'fall_rescue_native_fences_or_external_idle_unavailable')
    require(status.get('armed') is False and status.get('input_owned') is False
            and status.get('unknown_outcome_quarantined') is False and status.get('automation_blocked') is False,
            'fall_rescue_existing_authorization_or_owner')
    require(any(type(row) is dict and type(row.get('slot')) is int and 0<=row['slot']<=8
        and row.get('id')=='minecraft:water_bucket' and type(row.get('count')) is int and row['count']==1
        for row in before.player.get('inventory',[])),'fall_rescue_water_bucket_required_in_hotbar')
    body=deepcopy(body)
    body['fall_rescue_policy']={'version':VERSION,**{k:scope[k] for k in ('owner_id','owner_generation','job_id','defense_epoch')},
        'ttl_ms':original_timeout+RESERVE_MS,'rescue_reserve_ms':RESERVE_MS,
        'authorization_deadline_monotonic_ms':int(control.budget.deadline*1000)-1000}
    validate_envelope(body)
    # Prepay arm and its one eventual disarm. Original action and explicit cancel
    # retain their normal existing charges; no new budget or second controller.
    control.consume('actions',2)
    return body


def retain(runtime,record,result):
    if 'fall_rescue_cleanup' in result:
        control=runtime._job_control
        runtime._receipt(record,result)  # First preserve the original evidence.
        try:
            from resident_controller.fall_rescue_attached import binding_for,verify_cleanup
            expected=binding_for(record['command'],result.get('queue_request_id',record['request_id']),
                                 result.get('queue_session_id',record['gateway_session']))
            proof=verify_cleanup(result['fall_rescue_cleanup'],expected,record['command']['action'],result)
            require(runtime._job_control is control and control is not None and control.job_id==expected['job_id']
                and runtime._owner==expected['owner_id'] and runtime._job_generation==expected['owner_generation']
                and record.get('job_id')==control.job_id,'fall_rescue_cleanup_current_job_changed')
            control.fall_rescue_last_status=deepcopy(proof['native_status'])
        except Exception:
            runtime._unknown(record,'fall_rescue_cleanup_proof_unconfirmed')
    evidence=result.get('fall_rescue')
    if evidence is None:return
    runtime._receipt(record,result)  # Preserve malformed/unknown original evidence before validation.
    from resident_controller.fall_rescue_attached import verify_seal
    try:
        checked=verify_seal(evidence,record['command'],result.get('queue_request_id',record['request_id']),
                            result.get('queue_session_id',record['gateway_session']))
    except Exception:
        runtime._unknown(record,'fall_rescue_sealed_evidence_unconfirmed')
    if runtime._job_control is not None:
        runtime._job_control.emit('fall_rescue_original_interrupted',{'evidence':checked,'original_outcome':'unknown',
            'same_owner_job':True,'auto_resume':False})
