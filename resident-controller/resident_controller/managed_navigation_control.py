"""One exact bounded walking route. Pending native ownership blocks every other operation."""
from copy import deepcopy
from .external_navigation_control import CONTEXT,need,validate as validate_stop,validate_external_proof
from .transport import BridgeError
VERSION='managed-navigation-owner-control/1'
BINDING=('operation_id','control_owner','expected_context','source','timeout_ms','goal','max_distance','min_health')
def validate(command,*,resident=False):
    fields={'op','operation',*BINDING}
    if resident:fields|={'expected_resident_session','request_id','session_id','submitted_at'}
    need(type(command) is dict and set(command)==fields and command['op']=='managed_navigation_control'
        and command['operation'] in ('start','cancel','status'),'managed_navigation_closed_command')
    need(type(command['timeout_ms']) is int and 1000<=command['timeout_ms']<=120000,'managed_navigation_timeout')
    need(type(command['max_distance']) is int and 1<=command['max_distance']<=200
        and type(command['min_health']) is int and 6<=command['min_health']<=20,'managed_navigation_policy')
    goal=command['goal'];need(type(goal) is dict and set(goal)=={'x','y','z'}
        and all(type(goal[k]) is int and -limit<=goal[k]<=limit for k,limit in (('x',29999984),('y',2048),('z',29999984))),
        'managed_navigation_goal')
    # Shared exact identity/context/source contract; the route owns its separate timeout bounds.
    probe={k:v for k,v in command.items() if k not in ('goal','max_distance','min_health')}
    probe.update(op='external_navigation_control',operation='stop',timeout_ms=1000)
    return validate_stop(probe,resident=resident)
def native_body(command):
    owner,context=validate(command,resident=True)
    return {'managed_navigation_schema_version':1,'operation_id':command['operation_id'],**owner,
        **{'expected_'+k:v for k,v in context.items()},**command['source'],'timeout_ms':command['timeout_ms'],
        **{'goal_'+k:v for k,v in command['goal'].items()},'max_distance':command['max_distance'],'min_health':command['min_health']}
def validate_native_request(body):
    keys={'managed_navigation_schema_version','operation_id','owner_id','owner_generation','job_id','timeout_ms','source_tick','source_nano',
        'goal_x','goal_y','goal_z','max_distance','min_health'}|{'expected_'+k for k in CONTEXT}
    need(type(body) is dict and set(body)==keys and type(body['managed_navigation_schema_version']) is int
        and body['managed_navigation_schema_version']==1,'managed_navigation_native_request')
    validate({'op':'managed_navigation_control','operation':'start','operation_id':body['operation_id'],
        'control_owner':{k:body[k] for k in ('owner_id','owner_generation','job_id')},
        'expected_context':{k:body['expected_'+k] for k in CONTEXT},'source':{k:body[k] for k in ('source_tick','source_nano')},
        'goal':{k:body['goal_'+k] for k in ('x','y','z')},**{k:body[k] for k in ('timeout_ms','max_distance','min_health')}})
def validate_status(value,command,previous=None):
    owner,context=validate(command,resident=True)
    need(type(value) is dict,'managed_navigation_status_schema')
    if 'protocol' in value or 'schema_version' in value:
        need(type(value.get('protocol')) is str and value['protocol']=='mineclient-bridge'
            and type(value.get('schema_version')) is int and value['schema_version']==2,'managed_navigation_status_wrapper')
        value={k:v for k,v in value.items() if k not in ('protocol','schema_version')}
    keys={'managed_navigation_schema_version','input_owned','unknown_outcome_quarantined','execution_authority','no_auto_resume',
        'operation_id','owner_id','owner_generation','job_id',*CONTEXT,'state','reason','start_attempted','stop_attempted',
        'cancel_accepted','goal_reached','settings_restored','control_released','idle_samples','admission_tick','source_tick',
        'remaining_ms','unloaded_terrain_certified','goal_x','goal_y','goal_z','external_controller'}
    need(set(value)==keys and type(value['managed_navigation_schema_version']) is int and value['managed_navigation_schema_version']==1,
        'managed_navigation_status_schema')
    identity={'operation_id':command['operation_id'],**owner,**context,**{'goal_'+k:v for k,v in command['goal'].items()}}
    need(all(type(value[k]) is type(v) and value[k]==v for k,v in identity.items()),'managed_navigation_status_identity')
    flags=('input_owned','unknown_outcome_quarantined','start_attempted','stop_attempted','goal_reached','settings_restored','control_released')
    need(value['state'] in ('routing','stopping','settled','unknown') and value['execution_authority'] is False
        and value['no_auto_resume'] is True and value['unloaded_terrain_certified'] is False
        and all(type(value[k]) is bool for k in flags) and (value['cancel_accepted'] is None or type(value['cancel_accepted']) is bool)
        and type(value['reason']) is str and 0<len(value['reason'])<=128,'managed_navigation_status_flags')
    settled=value['state']=='settled';unknown=value['state']=='unknown'
    need(value['input_owned'] is (not settled) and value['control_released'] is settled
        and value['unknown_outcome_quarantined'] is unknown and value['settings_restored'] is settled
        and (not value['goal_reached'] or settled)
        and (value['state']!='routing' or not value['stop_attempted'])
        and (value['stop_attempted'] or value['cancel_accepted'] is None)
        and (unknown or value['start_attempted'])
        and (unknown or not value['stop_attempted'] or type(value['cancel_accepted']) is bool),
        'managed_navigation_status_consistency')
    need(all(type(value[k]) is int and lo<=value[k]<=hi for k,lo,hi in
        (('idle_samples',0,2),('admission_tick',0,2**53-1),('source_tick',0,2**53-1),('remaining_ms',0,command['timeout_ms']))),
        'managed_navigation_status_bounds')
    need(value['admission_tick']>=command['source']['source_tick'] and value['source_tick']>=value['admission_tick']
        and (not settled or value['idle_samples']==2 and value['source_tick']>=value['admission_tick']+2),
        'managed_navigation_sample_order')
    proof=validate_external_proof(value['external_controller'],context,settled=settled)
    need(proof['source_tick']==value['source_tick'] and int(proof['source_nano'])>=int(command['source']['source_nano']),
        'managed_navigation_proof_clock')
    if previous is not None:
        need(value['start_attempted'] is previous['start_attempted'] and (not previous['stop_attempted'] or value['stop_attempted'])
            and (previous['cancel_accepted'] is None or value['cancel_accepted'] is previous['cancel_accepted'])
            and value['admission_tick']==previous['admission_tick'] and value['source_tick']>=previous['source_tick']
            and value['remaining_ms']<=previous['remaining_ms'] and (previous['state']!='settled' or settled)
            and (previous['state']!='stopping' or value['state'] in ('stopping','settled','unknown')),
            'managed_navigation_status_regressed')
    need(not unknown,'managed_navigation_native_quarantined')
    return deepcopy(value)
def execute(resident,command):
    owner,context=validate(command,resident=True)
    need(command['expected_resident_session']==resident.session_id
        and context['action_session']==(resident.bridge_identity or {}).get('action_session'),'managed_navigation_resident_changed')
    policy=resident.observation_policy()
    need(not resident.paused and not policy['requires_handoff'] and not policy['input_release_unconfirmed']
        and resident.active is None and not resident.pending and not resident.combat.active and not resident.combat.held
        and not resident.aim.active and getattr(resident,'_fall_rescue_owner',None) is None
        and getattr(resident,'_external_navigation_owner',None) is None,'managed_navigation_existing_owner')
    binding={k:deepcopy(command[k]) for k in BINDING};operation=command['operation']
    previous=getattr(resident,'_managed_navigation_owner',None)
    need(previous is None if operation=='start' else previous==binding,'managed_navigation_original_owner_required')
    if operation=='start':
        resident._managed_navigation_owner=binding;resident._managed_navigation_last_status=None
        resident._managed_navigation_cancel_submitted=False
    if operation=='cancel':
        need(not resident._managed_navigation_cancel_submitted,'managed_navigation_cancel_not_repeatable')
        resident._managed_navigation_cancel_submitted=True
    try:
        value=resident.bridge.request('GET' if operation=='status' else 'POST','/control/managed-navigation/'+operation,
            None if operation=='status' else native_body(command))
        checked=validate_status(value,command,getattr(resident,'_managed_navigation_last_status',None))
        resident._managed_navigation_last_status=deepcopy(checked)
    except (BridgeError,ValueError,KeyError,TypeError) as exc:
        resident.paused,resident.reason=True,'managed_navigation_original_route_unknown'
        raise BridgeError(str(exc),uncertain=True) from exc
    if checked['state']=='settled':resident._managed_navigation_owner=None
    resident.finish(command,'succeeded',result=checked,control_owner=deepcopy(owner),resident_policy=policy,gameplay_effect_confirmed=False)
