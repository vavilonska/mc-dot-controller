"""Offline field-specific T21 encoding regression; never a runtime admission rule."""
from copy import deepcopy
import math
import struct

def need(ok, reason):
    if not ok: raise ValueError(reason)

def exact(a,b):
    if type(a) is not type(b): return False
    if isinstance(a,dict): return a.keys()==b.keys() and all(exact(a[k],b[k]) for k in a)
    if isinstance(a,list): return len(a)==len(b) and all(exact(x,y) for x,y in zip(a,b))
    return a==b

LATCH_PATH=('result','combat','threat_gate','health_diagnostics')
OPTIONAL='latch_trigger'
ENVELOPE_ONLY={'protocol','schema_version'}


def no_latch(action):
    current=action
    for key in LATCH_PATH:
        need(type(current) is dict and key in current,'required_health_diagnostics_path')
        current=current[key]
    need(type(current) is dict and current.get('latched') is False
                  and current.get('latch_triggered_now') is False,'explicit_no_latch_flags_required')
    need(OPTIONAL not in current or current[OPTIONAL] is None,'nonnull_latch_trigger_rejected')
    return current


def exact_terminal_with_optional_null(native,observed):
    """All nested fields/types exact, except this one absent-versus-null path."""
    need(type(native) is dict and type(observed) is dict,'terminal_objects')
    need(native.get('protocol')=='mineclient-bridge' and type(native.get('schema_version')) is int
                  and native['schema_version']==2,'original_native_envelope')
    need(not (ENVELOPE_ONLY & observed.keys()),'client_action_has_unexpected_envelope')
    required={'action','action_id','action_session','status','reason','result','ticks','action_schema_version','input_owner','movement_budget','ok','server_confirmed'}
    need(required<=native.keys() and required<=observed.keys(),'required_terminal_fields')
    left=deepcopy(native);right=deepcopy(observed)
    no_latch(left)[OPTIONAL]=None;no_latch(right)[OPTIONAL]=None
    for key in ENVELOPE_ONLY:del left[key]
    need(exact(left,right),'terminal_difference_outside_optional_null')
    return True


def exact_target_health_float32(native,observed):
    """Only Float JSON versus its exact float-to-double widening, never epsilon."""
    need(all(type(v) in (int,float) and math.isfinite(v) and 0<v<20 for v in (native,observed)),
                  'positive_decreased_finite_health_required')
    native_bits=struct.pack('>f',native);observed_bits=struct.pack('>f',observed)
    widened=struct.unpack('>f',native_bits)[0]
    need(native==widened and native_bits==observed_bits,'same_exact_binary32_health_required')
    return {'native_double_health':native,'nearby_float_json_health':observed,'binary32_hex':native_bits.hex(),
            'native_exact_float32_widening':True,'same_binary32':True}


def same_target_health(native_combat, nearby):
    need(type(native_combat) is dict and type(nearby) is list, 'target_objects')
    rows=[x for x in nearby if type(x) is dict and x.get('uuid')==native_combat.get('target_uuid')]
    need(type(native_combat.get('target_uuid')) is str and bool(native_combat['target_uuid']) and len(rows)==1, 'exact_target_uuid')
    row=rows[0]
    need(type(row.get('entity_id')) is int and type(native_combat.get('target_entity_id')) is int and row['entity_id']==native_combat['target_entity_id'] and row.get('type')==native_combat.get('target_type')=='minecraft:zombie' and row.get('alive') is True, 'exact_target_identity')
    return exact_target_health_float32(native_combat.get('target_health'),row.get('health'))
