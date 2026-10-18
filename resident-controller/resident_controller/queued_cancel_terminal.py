"""Proof for a queued cancel consumed after its original completed, before native POST.
No native calls, release, rollback or replay. This proof is not semantic completion.
"""
from copy import deepcopy
import math
import re
import uuid
from .cancel_terminal import digest, identifier, valid_command, native_of, unsafe, normalized, CONTEXT
from .ipc import read_json

REASON = 'exact_queued_cancel_original_terminal_no_native_dispatch'
BASE = {'op','expected_request_id','expected_resident_session','expected_action_session','expected_action_id'}
BINDING = {'schema_version','request_id','gateway_session','command','context'}
NATIVE_PROOF = {'schema_version','stage','cancel_queue_request_id','resident_session','resident_command',
    'resident_command_sha256','original_queue_request_id','original_result_sha256','original_command_sha256',
    'native_action_id','native_status','native_cancel_dispatched','input_release_confirmed','semantic_postcondition_confirmed'}
PUBLIC_PROOF = {'schema_version','stage','request_id','gateway_session','command','command_sha256','context',
    'resident_session','cancel_queue_request_id','original_queue_request_id','original_result_sha256',
    'resident_proof','native_cancel_dispatched','input_release_confirmed','semantic_postcondition_confirmed'}
ACK = {'status','reason','gameplay_effect_confirmed','exact_queued_cancel_terminal','request_id','session_id',
       'queue_request_id','queue_session_id'}

def hexhash(v):return type(v) is str and re.fullmatch('[0-9a-f]{64}',v) is not None

def valid_body(body):
    try:
        if type(body) is not dict or set(body)!=BASE|{'terminal_proof_binding'}:return False
        b=body['terminal_proof_binding'];c=b['command']
        return (body['op']=='capability_cancel_exact' and type(b) is dict and set(b)==BINDING
            and type(b['schema_version']) is int and b['schema_version']==1 and identifier(b['request_id'])
            and identifier(b['gateway_session']) and valid_command(c) and type(b['context']) is dict
            and set(b['context'])==CONTEXT and all(type(x) is str and 0<len(x)<=256 for x in b['context'].values())
            and body['expected_action_session']==c['expected_action_session']==b['context']['action_session']
            and identifier(body['expected_request_id']) and type(body['expected_resident_session']) is str
            and body['expected_action_id']==uuid.uuid5(uuid.UUID(body['expected_resident_session']),body['expected_request_id']+':1').hex)
    except (KeyError,TypeError,ValueError,AttributeError):return False

def valid_original(original,body):
    try:
        n=native_of(original);b=body['terminal_proof_binding'];ctx=b['context'];w=n['result']['scoped_native_preflight']
        return (type(original) is dict and original.get('request_id')==body['expected_request_id']
            and original.get('session_id')==body['expected_resident_session'] and original.get('status')=='succeeded'
            and not any(k in original for k in ('exact_cancel','cancellation','resolved_action','fall_rescue_cleanup'))
            and type(n) is dict and not any(unsafe(v) for v in (original,original.get('result'),n,n.get('result')))
            and type(n.get('action_schema_version')) is int and n['action_schema_version']==1
            and n.get('action_id')==body['expected_action_id'] and n.get('action_session')==ctx['action_session']
            and n.get('status')=='succeeded' and n.get('result',{}).get('input_release_confirmed') is True
            and type(w) is dict and w.get('version')=='scoped-native-preflight/1'
            and w.get('owner_id')==b['command']['owner_id'] and type(w.get('defense_epoch')) is int
            and w['defense_epoch']==b['command']['expected_defense_epoch']
            and all(w.get('context',{}).get(k)==v for k,v in ctx.items())
            and w.get('action_id')==body['expected_action_id'] and w.get('action_session')==ctx['action_session'])
    except (KeyError,TypeError,AttributeError):return False

def remember(resident,task,status):
    """Bounded process-local provenance, never recovered from an arbitrary cached result."""
    resident._capability_terminal_candidate=None
    command=task.command
    if (status=='succeeded' and command.get('op')=='action' and type(command.get('capability_guard')) is dict
            and type(command.get('scoped_native_preflight')) is dict and task.step_number==1
            and not task.capability_cancel_attempted and not task.capability_unknown
            and task.fall_rescue is None and task.encounter_request is None):
        resident._capability_terminal_candidate={'task':task,'command':deepcopy(command),
            'session':resident.session_id,'bridge_identity':deepcopy(resident.bridge_identity),
            'native':deepcopy(task.last_action_result),'cancel_request_id':None}

def attempt(resident,command):
    """Only called at the target-not-active branch, before any cancel attempt flag/POST."""
    body={k:deepcopy(v) for k,v in command.items() if k not in ('request_id','session_id','submitted_at')}
    if not valid_body(body):return False
    token=getattr(resident,'_capability_terminal_candidate',None)
    if type(token) is not dict or token.get('cancel_request_id') is not None:return False
    captured=deepcopy(command);original_command=deepcopy(token['command']);identity=deepcopy(token['bridge_identity'])
    target=body['expected_request_id'];rid=command.get('request_id');task=token['task'];native=deepcopy(token['native'])
    def bound():
        return (resident._capability_terminal_candidate is token and resident.active is None and not resident.pending
            and resident.running and resident.initialized and not resident.paused
            and resident.session_id==token['session']==body['expected_resident_session']==command.get('session_id')
            and resident.bridge_identity==identity and (identity or {}).get('action_session')==body['expected_action_session']
            and command==captured and token['command']==original_command and task.command==original_command
            and token['native']==native and task.last_action_result==native
            and task.step_number==1 and not task.capability_cancel_attempted and not task.capability_unknown
            and task.fall_rescue is None and task.encounter_request is None
            and not resident.combat.active and not resident.combat.held and not resident.aim.active
            and getattr(resident,'_fall_rescue_owner',None) is None and getattr(resident,'_managed_navigation_owner',None) is None
            and getattr(resident,'_external_navigation_owner',None) is None and getattr(resident,'_terrain_acquisition_unknown',None) is None
            and original_command.get('request_id')==target and original_command.get('session_id')==resident.session_id)
    if not identifier(rid) or not bound():return False
    # A second control identity cannot retry even a failed/lost proof construction.
    token['cancel_request_id']=rid
    try:
        original=read_json(resident.root/'results'/(target+'.json'),2*1024*1024)
        if not valid_original(original,body) or native_of(original)!=token['native']:return False
        scope=original_command['scoped_native_preflight'];b=body['terminal_proof_binding']
        if (scope.get('owner_id')!=b['command']['owner_id'] or scope.get('defense_epoch')!=b['command']['expected_defense_epoch']
                or any(original_command.get('expected_'+k)!=v for k,v in b['context'].items())):return False
        p={'schema_version':1,'stage':'original_terminal_before_native_cancel_dispatch',
            'cancel_queue_request_id':rid,'resident_session':resident.session_id,'resident_command':body,
            'resident_command_sha256':digest(body),'original_queue_request_id':target,'original_result_sha256':digest(original),
            'original_command_sha256':digest(original_command),'native_action_id':body['expected_action_id'],
            'native_status':'succeeded','native_cancel_dispatched':False,'input_release_confirmed':True,
            'semantic_postcondition_confirmed':False}
        # All receipt I/O and validation precede this exact current process-owner fence.
        if not bound() or token['cancel_request_id']!=rid:return False
        resident.finish(command,'succeeded',reason=REASON,gameplay_effect_confirmed=False,exact_cancel_no_native_dispatch=p)
        return True
    except (OSError,ValueError,KeyError,TypeError,AttributeError):return False

def validate_resident(receipt,body,queue_id,*,original=None):
    try:
        if (not valid_body(body) or not identifier(queue_id) or type(receipt) is not dict
                or set(receipt)!={'request_id','session_id','status','finished_at','reason','gameplay_effect_confirmed','exact_cancel_no_native_dispatch'}
                or receipt['request_id']!=queue_id or receipt['session_id']!=body['expected_resident_session']
                or receipt['status']!='succeeded' or receipt['reason']!=REASON or receipt['gameplay_effect_confirmed'] is not False
                or type(receipt['finished_at']) not in (int,float) or not math.isfinite(receipt['finished_at'])):return False
        p=receipt['exact_cancel_no_native_dispatch']
        if (type(p) is not dict or set(p)!=NATIVE_PROOF or type(p['schema_version']) is not int or p['schema_version']!=1
                or p['stage']!='original_terminal_before_native_cancel_dispatch' or p['cancel_queue_request_id']!=queue_id
                or p['resident_session']!=body['expected_resident_session'] or p['resident_command']!=body
                or not valid_body(p['resident_command']) or digest(p['resident_command'])!=digest(body)
                or not valid_body(p['resident_command']) or p['resident_command_sha256']!=digest(body)
                or p['original_queue_request_id']!=body['expected_request_id'] or not hexhash(p['original_result_sha256'])
                or not hexhash(p['original_command_sha256']) or p['native_action_id']!=body['expected_action_id']
                or p['native_status']!='succeeded' or p['native_cancel_dispatched'] is not False
                or p['input_release_confirmed'] is not True or p['semantic_postcondition_confirmed'] is not False):return False
        return original is None or valid_original(original,body) and digest(original)==p['original_result_sha256']
    except (KeyError,TypeError,ValueError,AttributeError):return False

def public_proof(receipt,original):
    p=receipt['exact_cancel_no_native_dispatch'];b=p['resident_command']['terminal_proof_binding'];c=b['command']
    value=normalized(original,c['expected_intent_id'],b['gateway_session'],p['original_queue_request_id'])
    return {'schema_version':1,'stage':'resident_terminal_before_native_cancel_dispatch','request_id':b['request_id'],
        'gateway_session':b['gateway_session'],'command':deepcopy(c),'command_sha256':digest(c),'context':deepcopy(b['context']),
        'resident_session':p['resident_session'],'cancel_queue_request_id':p['cancel_queue_request_id'],
        'original_queue_request_id':p['original_queue_request_id'],'original_result_sha256':digest(value),
        'resident_proof':deepcopy(receipt),'native_cancel_dispatched':False,'input_release_confirmed':True,
        'semantic_postcondition_confirmed':False}

def validate(receipt,command,request_id,gateway_session,*,original=None,context=None):
    try:
        if (not valid_command(command) or type(receipt) is not dict or set(receipt)!=ACK
                or receipt['status']!='succeeded' or receipt['reason']!=REASON or receipt['gameplay_effect_confirmed'] is not False
                or receipt['request_id']!=request_id or receipt['session_id']!=gateway_session):return False
        p=receipt['exact_queued_cancel_terminal'];r=p['resident_proof'];body=r['exact_cancel_no_native_dispatch']['resident_command'];b=body['terminal_proof_binding']
        if (type(p) is not dict or set(p)!=PUBLIC_PROOF or type(p['schema_version']) is not int or p['schema_version']!=1
                or p['stage']!='resident_terminal_before_native_cancel_dispatch' or p['command']!=command
                or not valid_command(p['command']) or p['command_sha256']!=digest(command)
                or p['request_id']!=request_id or p['gateway_session']!=gateway_session
                or b!={'schema_version':1,'request_id':request_id,'gateway_session':gateway_session,'command':command,'context':p['context']}
                or p['resident_session']!=receipt['queue_session_id'] or p['resident_session']!=body['expected_resident_session']
                or p['cancel_queue_request_id']!=receipt['queue_request_id'] or not hexhash(p['original_result_sha256'])
                or p['original_queue_request_id']!=body['expected_request_id']
                or p['native_cancel_dispatched'] is not False or p['input_release_confirmed'] is not True
                or p['semantic_postcondition_confirmed'] is not False
                or not validate_resident(r,body,p['cancel_queue_request_id'])):return False
        if context is not None and p['context']!=context:return False
        if original is not None:
            raw=deepcopy(original);raw.pop('queue_request_id',None);raw.pop('queue_session_id',None)
            raw.update(request_id=p['original_queue_request_id'],session_id=p['resident_session'])
            return (original.get('request_id')==command['expected_intent_id'] and original.get('session_id')==gateway_session
                and original.get('queue_request_id')==p['original_queue_request_id'] and original.get('queue_session_id')==p['resident_session']
                and digest(original)==p['original_result_sha256'] and validate_resident(r,body,p['cancel_queue_request_id'],original=raw))
        return True
    except (KeyError,TypeError,ValueError,AttributeError):return False
