"""An explicit stop-only lease, never ordinary authority under an external owner."""
from copy import deepcopy
from capability_ownership import safe_idle, CONTEXT
VERSION='external-navigation-owner-control/1'

def admission_ready(dog):
    try:
        payload=dog.latest;s=payload['state'];e=s['external_controller'];feature=s['external_navigation'];rescue=s['native_fall_rescue_status']
        if (getattr(dog,'execution_policy',None)!='request_only' or dog.rpc is not None
                or type(feature.get('schema_version')) is not int or feature.get('schema_version')!=1
                or feature.get('version')!=VERSION or feature.get('single_owner_fences') is not True
                or type(e.get('schema_version')) is not int or e.get('schema_version')!=1 or e.get('supported') is not True or e.get('status') not in ('idle','busy')
                or e.get('facts',{}).get('context_matches') is not True
                or type(e.get('facts',{}).get('instances')) is not int or e.get('facts',{}).get('instances')!=1
                or e.get('world_generation')!=s['world']['world_generation'] or e.get('player_uuid')!=s['player']['uuid']
                or e.get('action_session')!=s['client_action']['action_session'] or e.get('source_tick')!=s['world']['game_time']
                or rescue.get('armed') is not False):return False
        # Only Baritone-owned key state may be nonneutral. The normal proof still
        # checks the MDC native action, direct holds, resident task and combat.
        candidate=deepcopy(payload);candidate['state'].pop('external_controller')
        candidate['state']['held_inputs']['neutral']=True
        return safe_idle(candidate)
    except (KeyError,TypeError,AttributeError):return False

def prepare(dog,lease,body,expected_dimension):
    from resident_controller.external_navigation_control import validate
    try:
        owner,context=validate(body)
        valid=(lease.get('owner_mode')=='external_stop' and expected_dimension is None
            and owner['owner_id']==lease['owner_id'] and context==lease['context']
            and getattr(dog,'execution_policy',None)=='request_only' and not lease['post_observation_required'])
        binding={'operation_id':body['operation_id'],'control_owner':deepcopy(owner),'source':deepcopy(body['source']),
                 'timeout_ms':body['timeout_ms']}
        if body['operation']=='stop':
            proof=(dog.latest or {}).get('state',{}).get('external_controller',{})
            valid=(valid and lease.get('external_navigation') is None and admission_ready(dog)
                and dog.observed_at is not None and 0<=dog.clock()-dog.observed_at<=.8
                and body['source']=={k:proof.get(k) for k in ('source_tick','source_nano')}
                and dog.clock()+body['timeout_ms']/1000<=lease['deadline'])
        else:valid=valid and lease.get('external_navigation')==binding
        if valid:body['expected_resident_session']=lease['resident_session']
        return valid,binding
    except (ValueError,KeyError,TypeError):return False,None
