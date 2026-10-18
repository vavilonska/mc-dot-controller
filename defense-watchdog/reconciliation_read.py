"""Bounded diagnostic mailbox; never enters or settles an execution owner lane."""
from copy import deepcopy
import hashlib
import fcntl
import json
import os
from pathlib import Path
import re
import time
import uuid
from resident_controller.ipc import read_json, atomic_json
from resident_controller.reconciliation_read import failure_fields

VERSION='lease-free-reconciliation/1'
MAX_RECORDS=256
MAX_BYTES=128*1024
ID=re.compile(r'[A-Za-z0-9_-]{1,80}')
FIELDS={'schema_version','op','request_id','watchdog_session','created_at','expires_at','radius','original_job_id'}

def require(ok, reason):
    if not ok: raise ValueError(reason)

def encode(v): return json.dumps(v,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
def digest(v): return hashlib.sha256(encode(v)).hexdigest()
def folders(root):
    root=Path(root)/'reconciliation'
    require(not root.is_symlink(),'reconciliation_symlink')
    for name in ('inbox','working','results'):
        p=root/name;require(not p.is_symlink(),'reconciliation_symlink');p.mkdir(parents=True,exist_ok=True,mode=0o700)
    return root

def validate(v):
    require(type(v) is dict and set(v)==FIELDS,'reconciliation_closed_request')
    require(type(v['schema_version']) is int and v['schema_version']==1 and v['op']=='reconciliation_observe','reconciliation_schema')
    require(all(type(v[k]) is str and ID.fullmatch(v[k]) for k in ('request_id','watchdog_session','original_job_id')),'reconciliation_identity')
    require(type(v['radius']) is int and v['radius']==1,'reconciliation_radius')
    require(all(type(v[k]) in (int,float) and 0<v[k]<2**53 for k in ('created_at','expires_at'))
        and 0<v['expires_at']-v['created_at']<=5,'reconciliation_deadline')
    return v

def session(client):
    # A latched capability heartbeat fault remains untouched. This explicit read
    # inspects the gateway, rather than calling session() to clear/bypass a lease.
    v=read_json(client.root/'state.json',1024*1024)
    require(v.get('implementation')=='native-defense-watchdog-v5' and v.get('reconciliation_read_profile')==VERSION
        and type(v.get('session_id')) is str
        and ID.fullmatch(v['session_id']) is not None,'reconciliation_gateway_identity')
    require(type(v.get('updated_at')) in (int,float) and 0<=time.time()-v['updated_at']<=3,'reconciliation_gateway_stale')
    return v

def _submit(client, request_id, watchdog_session, original_job_id):
    require(type(request_id) is str and ID.fullmatch(request_id),'reconciliation_request_id')
    current=session(client);require(current['session_id']==watchdog_session,'reconciliation_gateway_changed')
    root=folders(client.root);name=request_id+'.json'
    for folder in ('inbox','working','results'):
        p=root/folder/name
        if p.exists():
            prior=read_json(p,MAX_BYTES);request=prior.get('request',prior)
            validate(request);require(request['request_id']==request_id and request['watchdog_session']==watchdog_session and request['original_job_id']==original_job_id,'reconciliation_id_conflict')
            return request
    require(sum(len(list((root/f).glob('*.json'))) for f in ('inbox','working','results'))<MAX_RECORDS,'reconciliation_history_full')
    require(len(list((root/'inbox').glob('*.json')))+len(list((root/'working').glob('*.json')))<1,'reconciliation_read_busy')
    now=time.time();body=validate({'schema_version':1,'op':'reconciliation_observe','request_id':request_id,
        'watchdog_session':watchdog_session,'created_at':now,'expires_at':now+5,'radius':1,'original_job_id':original_job_id})
    # Publish without replacing an existing identity, including concurrent callers.
    tmp=root/'inbox'/('.'+uuid.uuid4().hex+'.tmp');atomic_json(tmp,body)
    try:os.link(tmp,root/'inbox'/name)
    except FileExistsError:
        prior=read_json(root/'inbox'/name);require(digest(prior)==digest(body),'reconciliation_id_conflict')
    finally:tmp.unlink(missing_ok=True)
    return body

def submit(client, request_id, watchdog_session, original_job_id):
    root=folders(client.root)
    fd=os.open(root/'admission.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    try:
        fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        return _submit(client,request_id,watchdog_session,original_job_id)
    finally:
        os.close(fd)


def result(client, request):
    p=folders(client.root)/'results'/(request['request_id']+'.json')
    if not p.exists():return None
    v=read_json(p,MAX_BYTES)
    require(v.get('request')==request and v.get('request_digest')==digest(request),'reconciliation_result_identity')
    require(v.get('read_only') is True and v.get('execution_authority') is False and v.get('settles_original') is False,'reconciliation_result_authority')
    if any(key in v for key in ('compact_observation_diagnostic','compact_observation_diagnostic_status','read_failure_reason')):
        expected='reconcile_'+uuid.uuid5(uuid.NAMESPACE_OID,request['watchdog_session']+':reconciliation:'+request['request_id']).hex
        fields=failure_fields(v,expected) if v.get('queue_request_id')==expected and v.get('state')=='unknown' else {'compact_observation_diagnostic_status':'invalid'}
        for key in ('compact_observation_diagnostic','compact_observation_diagnostic_status','read_failure_reason'):v.pop(key,None)
        v.update(fields)
    return v

def _finish(root, request, state, reason, **data):
    value={'schema_version':1,'request':request,'request_digest':digest(request),'state':state,'reason':reason,
        'read_only':True,'execution_authority':False,'settles_original':False,'completed_at':time.time(),**data}
    require(len(encode(value))<=MAX_BYTES,'reconciliation_result_too_large')
    p=root/'results'/(request['request_id']+'.json')
    if not p.exists():atomic_json(p,value)
    (root/'working'/p.name).unlink(missing_ok=True)

def tick(dog,directory):
    """One independent GET-in-flight, on the existing watchdog thread only."""
    root=folders(directory);pending=getattr(dog,'_reconciliation_read',None)
    if pending is not None:
        request=pending['request']
        try:reply=dog.q.reconciliation_result(pending['queue_request_id'])
        except (ValueError,OSError,KeyError,TypeError):
            _finish(root,request,'unknown','diagnostic_mailbox_reply_unconfirmed',queue_request_id=pending['queue_request_id'])
            dog._reconciliation_read=None;return
        if reply is None and time.time()<request['expires_at']:return
        evidence={}
        try:
            if reply is None:
                _finish(root,request,'unknown','diagnostic_read_timeout_no_replay',queue_request_id=pending['queue_request_id'])
            else:
                require(reply.get('request_id')==pending['queue_request_id'] and reply.get('session_id')==pending['resident_session'],'reconciliation_resident_identity')
                require(reply.get('diagnostic_request_digest')==digest(request),'reconciliation_resident_request_digest')
                if reply.get('status')!='succeeded':
                    require(reply.get('read_only') is True and reply.get('execution_authority') is False
                        and reply.get('settles_original') is False,'reconciliation_failed_reply_authority')
                    evidence=failure_fields(reply,pending['queue_request_id'])
                require(reply.get('status')=='succeeded','reconciliation_native_read_unconfirmed')
                payload=reply.get('result');require(type(payload) is dict and payload.get('read_only') is True
                    and payload.get('execution_authority') is False and payload.get('settles_original') is False,'reconciliation_native_authority')
                _finish(root,request,'succeeded','diagnostic_read_only',queue_request_id=pending['queue_request_id'],resident_session=pending['resident_session'],result=payload)
        except (ValueError,KeyError,TypeError):
            _finish(root,request,'unknown','diagnostic_reply_unconfirmed_no_replay',queue_request_id=pending['queue_request_id'],**evidence)
        dog._reconciliation_read=None
        return
    # Restart never resubmits a claimed query, and never reads/writes an old action.
    for path in sorted((root/'working').glob('*.json'))[:1]:
        retained=read_json(path,MAX_BYTES);request=validate(retained.get('request',retained))
        _finish(root,request,'unknown','diagnostic_previous_run_not_replayed')
        return
    for path in sorted((root/'inbox').glob('*.json'))[:1]:
        request=read_json(path,4096)
        # Claim before transport. Any exception after this point becomes a
        # retained unknown on the next pass, never a second GET.
        os.replace(path,root/'working'/path.name)
        request=validate(request)
        if request['request_id']!=path.stem or request['watchdog_session']!=dog.session_id or not 0<=time.time()-request['created_at']<=5 or time.time()>=request['expires_at']:
            _finish(root,request,'blocked','diagnostic_stale_identity_or_deadline');return
        current=dog.q.session();resident=current.get('session_id')
        require(type(resident) is str and ID.fullmatch(resident),'reconciliation_resident_session')
        queue_id='reconcile_'+uuid.uuid5(uuid.NAMESPACE_OID,dog.session_id+':reconciliation:'+request['request_id']).hex
        pending={'request':request,'queue_request_id':queue_id,'resident_session':resident}
        atomic_json(root/'working'/path.name,pending)
        # q.submit is the existing resident mailbox; this exact closed operation
        # is intercepted before every takeover/mutator/error-cleanup branch.
        try:
            returned=dog.q.submit({'op':'reconciliation_observe','radius':1,'expected_resident_session':resident,
                'diagnostic_request':request,'diagnostic_request_digest':digest(request)},request_id=queue_id)
        except ValueError as exc:
            if str(exc)!='reconciliation_resident_history_full':raise
            _finish(root,request,'blocked','reconciliation_resident_history_full',queue_request_id=queue_id)
            return
        require(returned==queue_id,'reconciliation_queue_identity')
        dog._reconciliation_read=pending
        return
