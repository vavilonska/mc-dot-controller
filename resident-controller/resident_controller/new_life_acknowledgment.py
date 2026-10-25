"""Closed, owner-free acknowledgement of an observed death and new player object."""
import math
import uuid
from .pause_acknowledgment import encode,digest,exact,ID,SHA

VERSION='explicit-new-life-ack/1'
ACK='allow_new_life_requests_only_no_task_resume'
OP='acknowledge_new_life'
REASON='player_dead_or_unavailable'
SUCCESS='explicit_new_life_acknowledged_new_requests_only'
CONTEXT={'world_generation','dimension','player_uuid','action_session'}

def require(ok,reason):
    if not ok:raise ValueError('new_life_ack_'+reason)

def generation(player):
    if type(player) is not dict or type(player.get('generation_schema_version')) is not int or player['generation_schema_version']!=1:return None
    value=player.get('generation')
    try:return value if type(value) is str and value==str(uuid.UUID(value)) else None
    except (ValueError,AttributeError):return None

def valid_context(v):
    return type(v) is dict and set(v)==CONTEXT and all(type(x) is str and x for x in v.values())

def same_lifecycle(context,origin):
    return (valid_context(context) and valid_context(origin) and context['player_uuid']==origin['player_uuid']
            and context['action_session']==origin['action_session'])

def command(v):
    require(type(v) is dict and set(v)=={'op','schema_version','death_ref','expected_defense_epoch','acknowledgment','created_at','expires_at'},'closed_command')
    require(v['op']==OP and type(v['schema_version']) is int and v['schema_version']==1 and v['acknowledgment']==ACK,'contract')
    require(type(v['death_ref']) is str and SHA.fullmatch(v['death_ref']) and type(v['expected_defense_epoch']) is int and v['expected_defense_epoch']>=1,'binding')
    require(all(type(v[k]) in (int,float) and math.isfinite(v[k]) and v[k]>0 for k in ('created_at','expires_at')) and 0<v['expires_at']-v['created_at']<=5,'deadline')
    return v

def validate(result,cmd,request_id,session_id):
    command(cmd)
    require(type(result) is dict and result.get('request_id')==request_id and result.get('session_id')==session_id and result.get('queue_request_id') is None,'receipt_identity')
    p=result.get('new_life_acknowledgment')
    require(type(p) is dict and set(p)=={'schema_version','command','request_sha256','rearmed','origin','samples','new_context','new_generation','no_task_resume','no_native_mutation'},'closed_proof')
    require(type(p['schema_version']) is int and p['schema_version']==1 and exact(p['command'],cmd) and p['request_sha256']==digest(cmd),'command_proof')
    require(type(p['rearmed']) is bool and p['no_task_resume'] is True and p['no_native_mutation'] is True,'authority')
    if p['rearmed']:
        o=p['origin'];samples=p['samples']
        require(type(o) is dict and set(o)=={'watchdog_session','death_epoch','reason','context','integrated_server_instance','resident_session','bridge_identity','death_request_id','death_tick','dead_generation','death_health'},'origin')
        require(digest(o)==cmd['death_ref'] and o['watchdog_session']==session_id and type(o['death_epoch']) is int
            and 1<=o['death_epoch']<=cmd['expected_defense_epoch'] and o['reason']==REASON,'origin_binding')
        require(valid_context(o['context']) and type(o['death_request_id']) is str and ID.fullmatch(o['death_request_id'])
            and type(o['death_tick']) is int and o['death_tick']>=0
            and type(o['death_health']) in (int,float) and math.isfinite(o['death_health']) and o['death_health']<=0,'death_fact')
        require(generation({'generation_schema_version':1,'generation':o['dead_generation']}) is not None
            and generation({'generation_schema_version':1,'generation':p['new_generation']}) is not None
            and p['new_generation']!=o['dead_generation'] and same_lifecycle(p['new_context'],o['context']),'new_instance')
        require(type(samples) is list and len(samples)==2 and all(type(s) is dict and set(s)=={'request_id','tick'}
            and type(s['request_id']) is str and ID.fullmatch(s['request_id']) and type(s['tick']) is int and s['tick']>=0 for s in samples),'samples')
        require(samples[0]['tick']<samples[1]['tick'] and len({o['death_request_id'],samples[0]['request_id'],samples[1]['request_id']})==3,'sample_order')
        require(p['new_context']['world_generation']!=o['context']['world_generation'] or o['death_tick']<samples[0]['tick'],'source_tick')
        require(result.get('status')=='succeeded' and result.get('reason')==SUCCESS,'success')
    else:
        require(result.get('status')=='failed' and p['origin'] is None and p['samples']==[] and p['new_context'] is None and p['new_generation'] is None,'refusal')
    return p
