"""Bounded public projections; private Runtime objects never cross the API."""
from dataclasses import fields, is_dataclass
from enum import Enum
from .contracts import json_data, ToolboxError

_PRIVATE_KEYS = frozenset({'token','password','secret','authorization','api_key','access_token','control_directory',
                          'journal_directory','runtime_journal_directory','base_url','endpoint','cancel_event','emit'})

def public_data(value, *, _depth=0):
    if _depth > 32: raise ToolboxError('outcome_unknown','Backend result exceeds structural bounds',stage='serialization',effect_certainty='unknown')
    if value is None or type(value) in (str,bool,int,float): return value
    if isinstance(value,Enum): return public_data(value.value,_depth=_depth+1)
    if is_dataclass(value):
        value = {f.name:getattr(value,f.name) for f in fields(value) if not f.name.startswith('_')}
    if isinstance(value,dict):
        return {str(k):public_data(v,_depth=_depth+1) for k,v in value.items()
                if not str(k).startswith('_') and str(k).lower() not in _PRIVATE_KEYS}
    if isinstance(value,(tuple,list,set,frozenset)):
        return [public_data(v,_depth=_depth+1) for v in value]
    raise ToolboxError('outcome_unknown','Backend returned a non-data object',stage='serialization',effect_certainty='unknown')

def serialize_outcome(value):
    if hasattr(value, 'status') and hasattr(value, 'request_ids') and hasattr(value, 'evidence'):
        value = {key:getattr(value,key) for key in ('status','reason','request_ids','evidence')}
    result = public_data(value)
    if isinstance(result,dict): result['server_confirmed'] = False
    json_data(result)
    return result
