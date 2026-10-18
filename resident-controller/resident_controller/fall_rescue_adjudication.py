"""Explicit original-owner authority release on the existing Resident thread."""
from copy import deepcopy
import time
from .ipc import atomic_json,read_json
from .transport import BridgeError
from . import fall_rescue_adjudication_wire as wire
from .fall_rescue_attached import exact,digest

MAX_RECORDS=128

def validate(command):
    fields={'op','operation','adjudication_id','selector','acknowledgment'}
    metadata={'request_id','session_id','submitted_at'}
    wire.require(type(command) is dict and set(command)-metadata==fields
        and command.get('op')=='fall_rescue_adjudicate' and command.get('operation') in ('commit','status')
        and wire.identifier(command.get('adjudication_id')) and command.get('acknowledgment')==wire.ACK)
    return wire.selector(command['selector'])

def ledger(resident):
    value=getattr(resident,'_fall_adjudications',None)
    if value is None:
        path=resident.root/'fall-adjudications.json'
        value=read_json(path,2*1024*1024) if path.exists() else {}
        wire.require(type(value) is dict and len(value)<=MAX_RECORDS)
        resident._fall_adjudications=value
    return value

def save(resident):atomic_json(resident.root/'fall-adjudications.json',ledger(resident))

def scope_current(resident,selected,entry):
    return (resident.session_id==selected['resident_session'] and resident.active is None and not resident.pending
        and not resident.combat.active and not resident.combat.held and not resident.aim.active
        and getattr(resident,'_fall_rescue_owner',None) is None
        and getattr(resident,'_external_navigation_owner',None) is None
        and getattr(resident,'_managed_navigation_owner',None) is None
        and (resident.bridge_identity or {}).get('action_session')==selected['expected_context']['action_session']
        and ((resident.paused and resident.reason=='fall_rescue_original_outcome_unknown')
             or entry is not None and entry.get('state')=='authority_released' and not resident.paused and resident.reason is None))

def execute(resident,command):
    selected=validate(command);identity=command['adjudication_id'];entries=ledger(resident);entry=entries.get(identity)
    wire.require(scope_current(resident,selected,entry),'fall_adjudication_resident_original_scope_changed')
    original_path=resident.root/'results'/(selected['original_request_id']+'.json')
    receipt=read_json(original_path,2*1024*1024);sealed=wire.original(receipt,selected);original_digest=digest(receipt)
    if entry is not None:
        wire.require(type(entry.get('native_write_attempted')) is bool,'fall_adjudication_attempt_state_invalid')
        wire.require(exact(entry['selector'],selected) and entry['original_digest']==original_digest
            and entry['acknowledgment']==wire.ACK,'fall_adjudication_original_attempt_changed')
    elif command['operation']=='status':
        raise ValueError('fall_adjudication_original_attempt_not_found')
    else:
        wire.require(len(entries)<MAX_RECORDS,'fall_adjudication_identity_capacity_exhausted')
        entry={'selector':deepcopy(selected),'original_digest':original_digest,'acknowledgment':wire.ACK,
               'native_request':None,'state':'preparing','native_write_attempted':False}
        entries[identity]=entry;save(resident)
    if not entry['native_write_attempted']:
        if command['operation']=='status':
            resident.finish(command,'failed',reason='fall_adjudication_native_write_never_attempted',
                fall_adjudication_attempt=attempt_evidence(resident,command),resident_policy=resident.observation_policy())
            return
        started=time.monotonic();view=resident.bridge.request('GET',wire.ROOT+'/prepare')
        body=wire.request_for(identity,sealed,view)
        wire.require(scope_current(resident,selected,entry) and time.monotonic()-started<=1,
            'fall_adjudication_preparation_stale_or_owner_changed')
        entry['native_request']=body;entry['state']='reserved';save(resident)
    if command['operation']=='commit' and not entry['native_write_attempted']:
        # Persist once before POST. Every subsequent request reads this exact native ID.
        entry['native_write_attempted']=True;entry['state']='native_write_attempted';save(resident)
        wire.require(scope_current(resident,selected,entry),'fall_adjudication_owner_changed_before_write')
        started=time.monotonic()
        response=resident.bridge.request('POST',wire.ROOT,entry['native_request'])
    else:
        wire.require(entry['native_write_attempted'],'fall_adjudication_native_write_not_attempted')
        started=time.monotonic()
        response=resident.bridge.request('GET',wire.ROOT+'/status?adjudication_id='+identity)
    proof=wire.native_result(response,entry['native_request'],sealed)
    wire.require(scope_current(resident,selected,entry) and time.monotonic()-started<=1
        and digest(read_json(original_path,2*1024*1024))==original_digest,
        'fall_adjudication_after_read_scope_or_receipt_changed')
    entry['state']='authority_released';entry['native_result']=deepcopy(proof);save(resident)
    wire.require(scope_current(resident,selected,entry) and time.monotonic()-started<=1,
        'fall_adjudication_final_original_scope_changed')
    # Pure local authority release only. Old receipt/task is immutable and never resumed.
    resident.paused,resident.reason=False,None
    resident.publish()
    resident.finish(command,'succeeded',reason='fall_adjudication_authority_released_original_unknown',
        adjudication={'schema_version':1,'adjudication_id':identity,'selector':deepcopy(selected),
            'native_request':deepcopy(entry['native_request']),'native_result':proof,
            'original_effects':'unknown','no_auto_resume':True,'authority_released':True},
        resident_policy=resident.observation_policy(),gameplay_effect_confirmed=False,
        proof_received_monotonic=time.monotonic())

def attempt_evidence(resident,command):
    """Positive local pre-POST evidence; no missing record is treated as no effects."""
    try:
        selected=validate(command);entry=ledger(resident).get(command['adjudication_id'])
        if entry is None or not exact(entry['selector'],selected):return None
        return {'schema_version':1,'adjudication_id':command['adjudication_id'],'selector':deepcopy(selected),
            'native_write_attempted':entry['native_write_attempted'],'original_effects':'unknown','authority_released':False}
    except (ValueError,KeyError,TypeError,OSError):return None
