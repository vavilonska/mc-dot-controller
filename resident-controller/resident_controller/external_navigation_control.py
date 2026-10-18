"""Closed, exact-owner external cancellation. A cancel acknowledgement is not idle."""
from copy import deepcopy
import re
from .transport import BridgeError
VERSION='external-navigation-owner-control/1'
CONTEXT=('world_generation','dimension','player_uuid','action_session')
def need(ok,reason):
    if not ok:raise ValueError(reason)
def validate(command,*,resident=False):
    fields={'op','operation','operation_id','control_owner','expected_context','source','timeout_ms'}
    if resident:fields|={'expected_resident_session','request_id','session_id','submitted_at'}
    need(type(command) is dict and set(command)==fields and command['op']=='external_navigation_control'
        and command['operation'] in ('stop','status'),'external_navigation_closed_command')
    need(type(command['operation_id']) is str and re.fullmatch('[0-9a-f]{32}',command['operation_id']), 'external_navigation_id')
    owner=command['control_owner'];context=command['expected_context'];source=command['source']
    need(type(owner) is dict and set(owner)=={'owner_id','owner_generation','job_id'}
        and type(owner['owner_id']) is str and re.fullmatch('[0-9a-f]{32}',owner['owner_id'])
        and type(owner['owner_generation']) is int and 1<=owner['owner_generation']<=2**53-1
        and type(owner['job_id']) is str and re.fullmatch('[A-Za-z0-9_-]{1,80}',owner['job_id']), 'external_navigation_owner')
    need(type(context) is dict and set(context)==set(CONTEXT)
        and all(type(v) is str and 0<len(v)<=128 for v in context.values()),'external_navigation_context')
    need(type(source) is dict and set(source)=={'source_tick','source_nano'}
        and type(source['source_tick']) is int and 0<=source['source_tick']<=2**53-1
        and type(source['source_nano']) is str and re.fullmatch('-?(0|[1-9][0-9]{0,18})',source['source_nano'])
        and -2**63<=int(source['source_nano'])<2**63,'external_navigation_source')
    need(type(command['timeout_ms']) is int and 1000<=command['timeout_ms']<=10000,'external_navigation_timeout')
    return owner,context

def native_body(command):
    owner,context=validate(command,resident=True)
    return {'external_navigation_schema_version':1,'operation_id':command['operation_id'],**owner,
        **{'expected_'+k:v for k,v in context.items()},**command['source'],'timeout_ms':command['timeout_ms']}

def validate_native_request(body):
    fields={'external_navigation_schema_version','operation_id','owner_id','owner_generation','job_id','timeout_ms',
        'source_tick','source_nano'}|{'expected_'+k for k in CONTEXT}
    need(type(body) is dict and set(body)==fields and type(body['external_navigation_schema_version']) is int
        and body['external_navigation_schema_version']==1,'external_navigation_native_request')
    validate({'op':'external_navigation_control','operation':'stop','operation_id':body['operation_id'],
        'control_owner':{k:body[k] for k in ('owner_id','owner_generation','job_id')},
        'expected_context':{k:body['expected_'+k] for k in CONTEXT},
        'source':{k:body[k] for k in ('source_tick','source_nano')},'timeout_ms':body['timeout_ms']})

def validate_external_proof(proof,context,*,settled=False):
    keys={'schema_version','controller','adapter','source_tick','source_nano','action_session','world_generation',
          'player_uuid','execution_authority','status','supported','idle_proven','reason','facts'}
    need(type(proof) is dict and set(proof)==keys and type(proof['schema_version']) is int
        and proof['schema_version']==1 and proof['controller']=='baritone'
        and proof['adapter']=='baritone-api-neoforge/1.11.3' and proof['execution_authority'] is False
        and proof['supported'] is True and type(proof['idle_proven']) is bool
        and proof['status'] in ('idle','busy') and type(proof['reason']) is str and 0<len(proof['reason'])<=128
        and all(type(proof[k]) is str and proof[k]==context[k] for k in ('world_generation','player_uuid','action_session')),
        'external_navigation_proof_identity')
    need(type(proof['source_tick']) is int and 0<=proof['source_tick']<=2**53-1
        and type(proof['source_nano']) is str and re.fullmatch('-?(0|[1-9][0-9]{0,18})',proof['source_nano'])
        and -2**63<=int(proof['source_nano'])<2**63,'external_navigation_proof_clock')
    facts=proof['facts'];flags=('is_pathing','current_path','next_path','planning','goal_present')
    need(type(facts) is dict and set(facts)=={'instances','context_matches',*flags,'active_process_count','registered_process_count','forced_input_count'}
        and type(facts['instances']) is int and facts['instances']==1 and facts['context_matches'] is True
        and all(type(facts[k]) is bool for k in flags)
        and all(type(facts[k]) is int for k in ('active_process_count','registered_process_count','forced_input_count'))
        and 1<=facts['registered_process_count']<=64 and 0<=facts['active_process_count']<=facts['registered_process_count']
        and 0<=facts['forced_input_count']<=32,'external_navigation_proof_facts')
    idle=not any(facts[k] for k in flags) and facts['active_process_count']==0 and facts['forced_input_count']==0
    need(proof['idle_proven'] is idle and proof['status']==('idle' if idle else 'busy')
        and (not settled or idle),'external_navigation_proof_contradiction')
    return proof

def validate_status(value,command,previous=None):
    owner,context=validate(command,resident=True)
    # The endpoint carries the exact ActionResponses envelope. Embedded state
    # carries the raw model. No partial/malformed wrapper or extra field is accepted.
    need(type(value) is dict,'external_navigation_status_schema')
    if 'protocol' in value or 'schema_version' in value:
        need(type(value.get('protocol')) is str and value['protocol']=='mineclient-bridge'
            and type(value.get('schema_version')) is int and value['schema_version']==2,
            'external_navigation_status_wrapper')
        value={k:v for k,v in value.items() if k not in ('protocol','schema_version')}
    keys={'external_navigation_schema_version','input_owned','unknown_outcome_quarantined','no_auto_resume','execution_authority',
        'operation_id','owner_id','owner_generation','job_id',*CONTEXT,'state','reason','stop_attempted','cancel_accepted',
        'control_released','admission_tick','idle_samples','source_tick','remaining_ms','external_controller'}
    need(type(value) is dict and set(value)==keys,'external_navigation_status_schema')
    need(type(value['external_navigation_schema_version']) is int and value['external_navigation_schema_version']==1
        and value['operation_id']==command['operation_id'] and all(type(value[k]) is type(v) and value[k]==v for k,v in {**owner,**context}.items()),'external_navigation_status_identity')
    need(value['state'] in ('stopping','settled','unknown') and value['execution_authority'] is False and value['no_auto_resume'] is True
        and all(type(value[k]) is bool for k in ('input_owned','unknown_outcome_quarantined','stop_attempted','control_released'))
        and (value['cancel_accepted'] is None or type(value['cancel_accepted']) is bool)
        and type(value['reason']) is str and 0<len(value['reason'])<=128,'external_navigation_status_flags')
    need(all(type(value[k]) is int and lo<=value[k]<=hi for k,lo,hi in
        (('idle_samples',0,2),('admission_tick',0,2**53-1),('source_tick',0,2**53-1),('remaining_ms',0,command['timeout_ms']))),'external_navigation_status_bounds')
    settled=value['state']=='settled';unknown=value['state']=='unknown'
    need(value['input_owned'] is (not settled) and value['control_released'] is settled
        and value['unknown_outcome_quarantined'] is unknown and (not settled or value['idle_samples']==2),'external_navigation_status_consistency')
    need(value['admission_tick']>=command['source']['source_tick'] and value['source_tick']>=value['admission_tick']
        and (not settled or value['source_tick']>=value['admission_tick']+2)
        and (value['stop_attempted'] or value['cancel_accepted'] is None),'external_navigation_sample_order')
    proof=validate_external_proof(value['external_controller'],context,settled=settled)
    need(proof['source_tick']>=command['source']['source_tick']
        and int(proof['source_nano'])>=int(command['source']['source_nano'])
        and (not settled or proof['source_tick']==value['source_tick']),'external_navigation_idle_not_proven')
    if previous is not None:
        need(value['stop_attempted'] is previous['stop_attempted'] and value['cancel_accepted'] is previous['cancel_accepted']
            and value['admission_tick']==previous['admission_tick'] and value['remaining_ms']<=previous['remaining_ms']
            and value['source_tick']>=previous['source_tick'] and (previous['state']!='settled' or settled),
            'external_navigation_status_regressed')
    need(not unknown,'external_navigation_native_quarantined')
    return deepcopy(value)

def execute(resident,command):
    owner,context=validate(command,resident=True)
    need(command['expected_resident_session']==resident.session_id and context['action_session']==(resident.bridge_identity or {}).get('action_session'),'external_navigation_resident_changed')
    policy=resident.observation_policy()
    need(not resident.paused and not policy['requires_handoff'] and not policy['input_release_unconfirmed']
        and resident.active is None and not resident.pending and not resident.combat.active and not resident.combat.held
        and not resident.aim.active and getattr(resident,'_fall_rescue_owner',None) is None,'external_navigation_existing_owner')
    binding={k:deepcopy(command[k]) for k in ('operation_id','control_owner','expected_context','source','timeout_ms')}
    previous=getattr(resident,'_external_navigation_owner',None);operation=command['operation']
    need(previous is None if operation=='stop' else previous==binding,'external_navigation_original_owner_required')
    if operation=='stop':
        resident._external_navigation_owner=binding
        resident._external_navigation_last_status=None
    try:
        value=resident.bridge.request('POST' if operation=='stop' else 'GET','/control/external-navigation/'+operation,
            native_body(command) if operation=='stop' else None)
        checked=validate_status(value,command,getattr(resident,'_external_navigation_last_status',None))
        resident._external_navigation_last_status=deepcopy(checked)
    except (BridgeError,ValueError,KeyError,TypeError) as exc:
        resident.paused,resident.reason=True,'external_navigation_original_stop_unknown'
        raise BridgeError(str(exc),uncertain=True) from exc
    if checked['state']=='settled':resident._external_navigation_owner=None
    resident.finish(command,'succeeded',result=checked,control_owner=deepcopy(owner),resident_policy=policy,gameplay_effect_confirmed=False)
