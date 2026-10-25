"""Closed proof for explicit idle-menu acknowledgment; never gameplay recovery."""
import hashlib
import json
import math
import re

VERSION='explicit-idle-pause-ack/1'
ACK='allow_new_requests_only_no_task_resume'
OP='acknowledge_idle_pause'
REASON='request_only_observation_not_safe_idle'
ID=re.compile(r'^[A-Za-z0-9_-]{1,80}$')
SHA=re.compile(r'^[0-9a-f]{64}$')

def encode(v):return json.dumps(v,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
def digest(v):return hashlib.sha256(encode(v)).hexdigest()
def exact(a,b):return encode(a)==encode(b)
def require(ok,reason):
    if not ok:raise ValueError('pause_ack_'+reason)

def command(v):
    require(type(v) is dict and set(v)=={'op','schema_version','pause_ref','expected_defense_epoch','acknowledgment','created_at','expires_at'},'closed_command')
    require(v['op']==OP and type(v['schema_version']) is int and v['schema_version']==1 and v['acknowledgment']==ACK,'contract')
    require(type(v['pause_ref']) is str and SHA.fullmatch(v['pause_ref']) and type(v['expected_defense_epoch']) is int and v['expected_defense_epoch']>=1,'binding')
    require(all(type(v[k]) in (int,float) and math.isfinite(v[k]) and v[k]>0 for k in ('created_at','expires_at')) and 0<v['expires_at']-v['created_at']<=5,'deadline')
    return v

def validate(result,cmd,request_id,session_id):
    command(cmd)
    require(type(result) is dict and result.get('request_id')==request_id and result.get('session_id')==session_id and result.get('queue_request_id') is None,'receipt_identity')
    p=result.get('pause_acknowledgment')
    require(type(p) is dict and set(p)=={'schema_version','command','request_sha256','rearmed','origin','samples','no_task_resume','no_native_mutation'},'closed_proof')
    require(type(p['schema_version']) is int and p['schema_version']==1 and exact(p['command'],cmd) and p['request_sha256']==digest(cmd),'command_proof')
    require(type(p['rearmed']) is bool and p['no_task_resume'] is True and p['no_native_mutation'] is True,'authority')
    if p['rearmed']:
        o=p['origin'];samples=p['samples']
        require(type(o) is dict and set(o)=={'watchdog_session','defense_epoch','reason','context','integrated_server_instance','resident_session','bridge_identity','pause_tick'},'origin')
        require(digest(o)==cmd['pause_ref'] and o['watchdog_session']==session_id and type(o['defense_epoch']) is int and o['defense_epoch']==cmd['expected_defense_epoch'] and o['reason']==REASON,'origin_binding')
        require(type(samples) is list and len(samples)==2 and all(type(s) is dict and set(s)=={'request_id','tick'} and type(s['request_id']) is str and ID.fullmatch(s['request_id']) and type(s['tick']) is int for s in samples),'samples')
        require(type(o['pause_tick']) is int and o['pause_tick']<samples[0]['tick']<samples[1]['tick'] and samples[0]['request_id']!=samples[1]['request_id'],'sample_order')
        require(result.get('status')=='succeeded' and result.get('reason')=='explicit_pause_acknowledged_new_requests_only','success')
    else:
        require(result.get('status')=='failed' and p['origin'] is None and p['samples']==[],'refusal')
    return p
