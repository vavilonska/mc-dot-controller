"""Strict bounded native admission provenance. Diagnostic stages never authorize replay."""
from copy import deepcopy
import hashlib
import json
import re

STAGES = frozenset(('validation', 'hooks_possible', 'input_transfer', 'registered'))
KEYS = frozenset(('schema_version','action_session','request_payload_sha256','digest_format',
    'action_id','action','scope','stage','reason','effects_none_proven','dispatch_authority','retry_authority'))


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
        allow_nan=False, separators=(',', ':')).encode('utf-8')).hexdigest()


def validate(proof, body, reason):
    try:
        scope, intent = body['preflight'], body['intent']
        from .capability_snapshot import exact
        return (type(proof) is dict and set(proof) == KEYS
            and len(json.dumps(proof, ensure_ascii=False).encode('utf-8')) <= 8192
            and type(proof['schema_version']) is int and proof['schema_version'] == 1
            and proof['digest_format'] == 'sorted-json-utf8/1'
            and type(proof['action_id']) is str and re.fullmatch(r'[A-Za-z0-9_-]{1,64}', proof['action_id']) is not None
            and proof['action_id'] == intent['action_id'] and proof['action'] == intent['action']
            and type(proof['action_session']) is str and bool(proof['action_session'])
            and proof['action_session'] == intent['expected_action_session']
            and exact(proof['scope'], scope)
            and type(scope.get('owner_id')) is str and re.fullmatch(r'[0-9a-f]{32}', scope['owner_id']) is not None
            and type(scope.get('owner_generation')) is int and scope['owner_generation'] > 0
            and type(scope.get('job_id')) is str and re.fullmatch(r'[A-Za-z0-9_-]{1,80}', scope['job_id']) is not None
            and type(scope.get('defense_epoch')) is int and scope['defense_epoch'] >= 0
            and proof['request_payload_sha256'] == digest(body)
            and proof['stage'] in STAGES and proof['reason'] == reason
            and type(proof['effects_none_proven']) is bool
            and proof['effects_none_proven'] == (proof['stage'] == 'validation')
            and proof['dispatch_authority'] is False and proof['retry_authority'] is False)
    except (ValueError, TypeError, KeyError, RecursionError):
        return False


def entity_diagnostic(value, reason):
    keys = {'schema_version','profile','enumeration_scope','spatial_filter_applied',
        'spatial_relation','entity_class','entity_class_complete','reason','diagnostic_only','dispatch_authority'}
    return (type(value) is dict and set(value) == keys
        and type(value.get('schema_version')) is int and value['schema_version'] == 1
        and type(value.get('profile')) is str and 0 < len(value['profile']) <= 100
        and value.get('enumeration_scope') == 'all_rendered_entities_before_spatial_filter'
        and value.get('spatial_filter_applied') is False and value.get('spatial_relation') == 'not_evaluated'
        and type(value.get('entity_class')) is str and 0 < len(value['entity_class']) <= 256
        and type(value.get('entity_class_complete')) is bool
        and value.get('reason') == reason == 'scoped_movement_entity_unsupported'
        and value.get('diagnostic_only') is True and value.get('dispatch_authority') is False)


def no_effect(proof):
    # Only valid transport-bound proofs can enter this helper; core revalidates independently.
    return type(proof) is dict and proof.get('stage') == 'validation' and proof.get('effects_none_proven') is True
