"""Exact display-only read branch and isolated immutable diagnostic receipts."""
import hashlib
import json
import math
import os
import time
import uuid
from .compact_observation import validate, valid_diagnostic
from copy import deepcopy
import re
from .ipc import ID, RECONCILIATION_PREFIX, atomic_json, read_json

MAX_RESULTS=256
MAX_BYTES=128*1024
REQUEST_FIELDS={'schema_version','op','request_id','watchdog_session','created_at','expires_at','radius','original_job_id'}

def encode(value):return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
def digest(value):return hashlib.sha256(encode(value)).hexdigest()

def request_proof(command):
    request=command.get('diagnostic_request')
    if (type(request) is not dict or set(request)!=REQUEST_FIELDS
            or type(request['schema_version']) is not int or request['schema_version']!=1
            or request['op']!='reconciliation_observe' or type(request['radius']) is not int or request['radius']!=1
            or not all(type(request[k]) is str and ID.fullmatch(request[k]) for k in ('request_id','watchdog_session','original_job_id'))
            or not all(type(request[k]) in (int,float) and math.isfinite(request[k]) and 0<request[k]<2**53 for k in ('created_at','expires_at'))
            or not 0<request['expires_at']-request['created_at']<=5
            or command.get('diagnostic_request_digest')!=digest(request)):
        raise ValueError('invalid_reconciliation_request_proof')
    expected=RECONCILIATION_PREFIX+uuid.uuid5(uuid.NAMESPACE_OID,request['watchdog_session']+':reconciliation:'+request['request_id']).hex
    if command.get('request_id')!=expected:raise ValueError('invalid_reconciliation_queue_binding')
    return request

def failure_fields(value, request_id):
    """Bounded same-read cost evidence only; never an outcome/settlement proof."""
    diagnostic=value.get('compact_observation_diagnostic')
    reported=value.get('compact_observation_diagnostic_status')
    fields={}
    try: valid=reported=='reported' and valid_diagnostic(diagnostic,request_id,1)
    except (ValueError,KeyError,TypeError):valid=False
    if valid:
        fields['compact_observation_diagnostic']=deepcopy(diagnostic)
        fields['compact_observation_diagnostic_status']='reported'
    else:
        fields['compact_observation_diagnostic_status']='invalid' if diagnostic is not None or reported not in (None,'missing') else 'missing'
    reason=value.get('read_failure_reason')
    if type(reason) is str and re.fullmatch(r'[a-zA-Z0-9_]{1,100}',reason):fields['read_failure_reason']=reason
    return fields

def receipt_root(resident):
    root=resident.root/'reconciliation-results'
    if root.is_symlink():raise ValueError('reconciliation_receipt_symlink')
    root.mkdir(parents=True,exist_ok=True,mode=0o700)
    return root

def finish(resident,command,status,**fields):
    """Never enters generic execution receipt retention/pruning, including errors."""
    rid=command.get('request_id')
    if type(rid) is not str or not ID.fullmatch(rid):return
    root=receipt_root(resident);path=root/(rid+'.json');working=resident.root/'working'/(rid+'.json')
    if path.exists():
        working.unlink(missing_ok=True);return
    if len(list(root.glob('*.json')))>=MAX_RESULTS:
        # Keep claimed evidence at saturation; never evict any prior receipt.
        return
    value={'request_id':rid,'session_id':command.get('session_id',resident.session_id),
        'status':status,'finished_at':time.time(),**fields,
        'read_only':True,'execution_authority':False,'settles_original':False}
    proof=command.get('diagnostic_request_digest')
    if type(proof) is str and len(proof)==64 and all(c in '0123456789abcdef' for c in proof):value['diagnostic_request_digest']=proof
    if len(encode(value))>MAX_BYTES:
        value={k:v for k,v in value.items() if k in ('request_id','session_id','finished_at','read_only','execution_authority','settles_original','diagnostic_request_digest')}
        value.update(status='unknown',reason='reconciliation_response_too_large')
    temporary=root/('.'+uuid.uuid4().hex+'.tmp')
    atomic_json(temporary,value)
    try:os.link(temporary,path)  # First result is immutable, even across a duplicate writer.
    except FileExistsError:pass
    finally:temporary.unlink(missing_ok=True)
    working.unlink(missing_ok=True)

def execute(resident,command):
    required={'op','radius','expected_resident_session','request_id','session_id','submitted_at',
        'diagnostic_request','diagnostic_request_digest'}
    if (type(command) is not dict or set(command)!=required or command['op']!='reconciliation_observe'
            or type(command['radius']) is not int or command['radius']!=1
            or command['session_id']!=resident.session_id
            or command['expected_resident_session']!=resident.session_id):
        raise ValueError('invalid_reconciliation_read')
    request=request_proof(command);rid=command['request_id'];root=receipt_root(resident)
    if (root/(rid+'.json')).exists():return
    if len(list(root.glob('*.json')))>=MAX_RESULTS:raise ValueError('reconciliation_resident_history_full')
    # Original immutable gateway deadline is checked at the final dispatch boundary.
    # Queue delay never grants a new time budget; no late GET after a timed-out read.
    if not request['created_at']<=time.time()<request['expires_at']:
        raise ValueError('reconciliation_read_expired_before_get')
    raw=resident.bridge.request('GET',f'/control/compact-observation?request_id={rid}&radius=1')
    if time.time()>=request['expires_at']:
        raise ValueError('reconciliation_read_expired_after_get')
    value,_=validate(raw,rid,1,identity=resident.bridge_identity)
    if value['control'].get('private_singleplayer') is not True:
        raise ValueError('reconciliation_private_singleplayer_unconfirmed')
    policy=resident.observation_policy()
    finish(resident,command,'succeeded',result={'compact':value,'resident_policy':policy,
        'read_only':True,'execution_authority':False,'settles_original':False,
        'original_resident_owner':{'active_request_id':resident.active.command.get('request_id') if resident.active else None,
            'active_action_id':resident.active.action_id if resident.active else None,
            'pending_count':len(resident.pending),'paused':resident.paused,'reason':resident.reason}},
        gameplay_effect_confirmed=False)
