"""Validate the actual optional HTTP wrapper before validating a closed native payload.

State snapshots embed the raw native status; ActionResponses adds these two fields
only at the HTTP boundary. Neither shape changes owner or evidence semantics.
"""
from copy import deepcopy

def payload(value):
    if type(value) is not dict:raise ValueError('fall_rescue_wire_object_required')
    value=deepcopy(value)
    if 'protocol' in value or 'schema_version' in value:
        if (value.get('protocol')!='mineclient-bridge' or type(value.get('schema_version')) is not int
                or value.get('schema_version')!=2):
            raise ValueError('fall_rescue_http_protocol_unconfirmed')
        del value['protocol'];del value['schema_version']
    return value
