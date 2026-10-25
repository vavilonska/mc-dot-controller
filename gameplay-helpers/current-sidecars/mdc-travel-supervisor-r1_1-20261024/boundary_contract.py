"""Unmodified existing v2 admission predicate; no I/O or game effects."""
import hashlib,json

def bound_pre_input_rejection(code,obj,body):
    if code not in (400,409) or not isinstance(obj,dict):return False
    p=obj.get('native_admission')
    if not isinstance(p,dict):return False
    digest=hashlib.sha256(json.dumps(body,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()).hexdigest()
    return (p.get('boundary_schema_version')==2 and type(p.get('boundary_schema_version'))is int
        and p.get('ordinary_start_entered') is True and p.get('input_transfer_entered') is False
        and p.get('registration_entered') is False and p.get('reentry_observed') is False
        and p.get('stage') in ('validation','hooks_possible') and p.get('dispatch_authority') is False and p.get('retry_authority') is False
        and isinstance(obj.get('error'),str) and p.get('reason')==obj['error']
        and p.get('action_id')==body['action_id'] and p.get('action')==body['action']
        and p.get('action_session')==body['expected_action_session']
        and p.get('digest_format')=='sorted-json-utf8/1' and p.get('request_payload_sha256')==digest)
