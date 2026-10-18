"""Managed route binds an ordinary lease acquired while the external API is idle."""
from copy import deepcopy
from capability_ownership import safe_idle
VERSION='managed-navigation-owner-control/1'
def prepare(dog,lease,body,expected_dimension):
    from resident_controller.managed_navigation_control import validate,BINDING
    try:
        owner,context=validate(body)
        valid=(lease.get('owner_mode','ordinary')=='ordinary' and expected_dimension is None
            and owner['owner_id']==lease['owner_id'] and context==lease['context']
            and getattr(dog,'execution_policy',None)=='request_only' and not lease['post_observation_required'])
        binding={k:deepcopy(body[k]) for k in BINDING}
        if body['operation']=='start':
            state=(dog.latest or {}).get('state',{});feature=state.get('managed_navigation',{});proof=state.get('external_controller',{})
            valid=(valid and lease.get('managed_navigation') is None and safe_idle(dog.latest)
                and feature.get('version')==VERSION and feature.get('input_fence_ready') is True
                and state.get('native_fall_rescue_status',{}).get('armed') is False
                and dog.observed_at is not None and 0<=dog.clock()-dog.observed_at<=.8
                and body['source']=={k:proof.get(k) for k in ('source_tick','source_nano')}
                and dog.clock()+body['timeout_ms']/1000+10<=lease['deadline'])
        else:
            valid=valid and lease.get('managed_navigation')==binding
            if body['operation']=='cancel':valid=valid and not lease.get('managed_navigation_cancel_submitted',False)
        if valid:body['expected_resident_session']=lease['resident_session']
        return valid,binding
    except (ValueError,KeyError,TypeError):return False,None
