"""Bounded same-envelope wire decoding. Never captures, repairs, caches, or grants action authority."""
from copy import deepcopy
import hashlib
import json
import re

MARKER = 'scoped_movement_witness_encoding'
ENCODING = 'single-authority-v1'
WITNESS = 'scoped_native_preflight'
REFERENCE = 'scoped_native_preflight_ref'
TARGET = '/action/result/scoped_native_preflight'
WIRE_LIMIT = 256 * 1024
BINDINGS = ('profile', 'action_id', 'action_session', 'owner_id', 'owner_generation', 'job_id',
            'defense_epoch', 'submitted_intent_sha256', 'command_sha256', 'source_tick',
            'source_nano', 'admitted_nano')
REFERENCE_KEYS = {'schema_version', 'path', *BINDINGS}
REFERENCE_PATHS = {('status', 'client_action', 'result', REFERENCE),
                   ('state', 'client_action', 'result', REFERENCE)}


def require(condition, detail):
    if not condition:
        raise ValueError('invalid_capability_snapshot_movement_wire_' + detail)


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'duplicate_json_key')
        result[key] = value
    return result


def load_strict(raw):
    return json.loads(raw, object_pairs_hook=unique_object,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite_json')))


def _reference_paths(value, path=()):
    found = set()
    if type(value) is dict:
        for key, child in value.items():
            if key == REFERENCE:
                found.add(path + (key,))
            found.update(_reference_paths(child, path + (key,)))
    elif type(value) is list:
        for index, child in enumerate(value):
            found.update(_reference_paths(child, path + (index,)))
    return found


def decode(bundle):
    """Return legacy input unchanged, or a separate semantic copy of the declared new format."""
    from .capability_snapshot import exact, _integer, signed_long_string
    require(type(bundle) is dict, 'envelope')
    refs = _reference_paths(bundle)
    if MARKER not in bundle:
        require(not refs, 'marker_missing')
        return bundle
    require(bundle[MARKER] == ENCODING and type(bundle[MARKER]) is str, 'encoding')
    require(refs == REFERENCE_PATHS, 'reference_locations')
    action = bundle.get('action')
    require(type(action) is dict and type(action.get('result')) is dict, 'authority_action')
    result = action['result']
    authority = result.get(WITNESS)
    require(REFERENCE not in result and type(authority) is dict, 'authority_missing_or_chained')
    require(authority.get('profile') in ('movement-flat-observed-v2','mining-local-observed-v2','collect-local-observed-v1')
            and authority.get('version') == 'scoped-native-preflight/1'
            and type(authority.get('schema_version')) is int and authority['schema_version'] == 1
            and authority.get('coverage_complete') is True and authority.get('admitted') is True
            and authority.get('clock_domain') == 'native-system-nanotime', 'authority_profile')
    require(all(key in authority for key in BINDINGS)
            and type(authority['action_id']) is str and bool(authority['action_id'])
            and type(authority['action_session']) is str and bool(authority['action_session'])
            and authority['action_id'] == action.get('action_id')
            and authority['action_session'] == action.get('action_session')
            and type(authority['owner_id']) is str and re.fullmatch(r'[0-9a-f]{32}', authority['owner_id'])
            and _integer(authority['owner_generation'], 1)
            and type(authority['job_id']) is str and re.fullmatch(r'[A-Za-z0-9_-]{1,80}', authority['job_id'])
            and _integer(authority['defense_epoch']) and _integer(authority['source_tick'])
            and all(type(authority[key]) is str and re.fullmatch(r'[0-9a-f]{64}', authority[key])
                    for key in ('submitted_intent_sha256', 'command_sha256'))
            and signed_long_string(authority['source_nano']) and signed_long_string(authority['admitted_nano'])
            and 0 <= int(authority['admitted_nano']) - int(authority['source_nano']) <= 250000000,
            'authority_identity_or_clock')
    semantic = deepcopy(bundle)
    del semantic[MARKER]
    for name in ('status', 'state'):
        sibling = semantic.get(name)
        require(type(sibling) is dict and type(sibling.get('client_action')) is dict,
                'sibling_action')
        receipt = sibling['client_action'].get('result')
        require(type(receipt) is dict and WITNESS not in receipt, 'inline_reference_conflict')
        ref = receipt.get(REFERENCE)
        require(type(ref) is dict and set(ref) == REFERENCE_KEYS
                and type(ref['schema_version']) is int and ref['schema_version'] == 1
                and ref['path'] == TARGET
                and all(exact(ref[key], authority[key]) for key in BINDINGS), 'reference_binding')
        del receipt[REFERENCE]
        receipt[WITNESS] = deepcopy(authority)
    # validate_snapshot checks exact complete sibling equality after this declared decoding.
    return semantic


def retain(raw):
    """Only original received UTF-8 bytes may enter this provenance record."""
    require(type(raw) is bytes and 0 < len(raw) <= WIRE_LIMIT, 'raw_bound')
    parsed = load_strict(raw)
    require(type(parsed) is dict and parsed.get(MARKER) == ENCODING, 'raw_encoding')
    return {'schema_version': 1, 'encoding': ENCODING, 'raw_utf8': raw.decode('utf-8'),
            'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}


def validate_retained(provenance, semantic, radius, *, observation_clock=None, delivered=False):
    """Reparse original bytes and compare decoded native fields; keep the raw record untouched."""
    from .capability_snapshot import exact, validate_snapshot
    require(type(provenance) is dict and set(provenance) ==
            {'schema_version', 'encoding', 'raw_utf8', 'bytes', 'sha256'}, 'provenance_schema')
    require(type(provenance['schema_version']) is int and provenance['schema_version'] == 1
            and provenance['encoding'] == ENCODING and type(provenance['raw_utf8']) is str
            and type(provenance['bytes']) is int and 0 < provenance['bytes'] <= WIRE_LIMIT
            and type(provenance['sha256']) is str
            and re.fullmatch(r'[0-9a-f]{64}', provenance['sha256']), 'provenance_fields')
    raw = provenance['raw_utf8'].encode('utf-8')
    require(len(raw) == provenance['bytes']
            and hashlib.sha256(raw).hexdigest() == provenance['sha256'], 'provenance_bytes')
    encoded = load_strict(raw)
    require(type(encoded) is dict and encoded.get(MARKER) == ENCODING, 'provenance_encoding')
    decoded = validate_snapshot(encoded, radius, observation_clock=observation_clock)
    keys = ('status', 'action', 'state', 'screen', 'capability_snapshot_schema_version')
    if observation_clock is not None:
        keys += ('ok', 'protocol', 'schema_version', 'observation_clock_profile', 'observation_clock')
    require(all(key in semantic and exact(decoded.get(key), semantic[key]) for key in keys),
            'decoded_delivery_mismatch')
    if not delivered:
        require(exact(decoded, semantic), 'decoded_envelope_mismatch')
    return decoded


def validate_delivery(payload, radius, *, observation_clock=None):
    """Resident payload is semantic data; encoded markers/references may not leak into it."""
    require(type(payload) is dict and MARKER not in payload, 'delivery_representation')
    provenance = payload.get('native_capability_wire')
    if provenance is None:
        # Preserve legacy payload contracts; malformed reference objects still fail closed.
        require(not _reference_paths(payload), 'delivery_provenance_missing')
        return
    require(not _reference_paths({k: payload.get(k) for k in ('status', 'action', 'state', 'screen')}),
            'delivery_reference')
    validate_retained(provenance, payload, radius, observation_clock=observation_clock, delivered=True)


def valid_size_diagnostic(value):
    keys = {'schema_version', 'standalone_bytes', 'capability_bytes', 'response_limit',
            'standalone_reserve_bytes', 'capability_reserve_bytes', 'witness_bytes',
            'entity_frame_bytes', 'enumerated_count', 'cell_count'}
    if type(value) is not dict:
        return False
    mining = value.get('schema_version') == 2 and value.get('profile') == 'mining-local-observed-v2'
    if set(value) != (keys | {'profile'} if mining else keys):
        return False
    if not all(type(value[k]) is int and 0 <= value[k] <= 2147483647 for k in keys):
        return False
    return (value['schema_version'] == (2 if mining else 1) and value['response_limit'] == WIRE_LIMIT
            and value['standalone_reserve_bytes'] == 8192 and value['capability_reserve_bytes'] == 24576
            and (1 <= value['cell_count'] <= 512 if mining else value['cell_count'] == 150)
            and 1 <= value['enumerated_count'] <= 1024
            and value['entity_frame_bytes'] <= 192 * 1024
            and value['entity_frame_bytes'] <= value['witness_bytes'] <= value['standalone_bytes']
            and (value['standalone_bytes'] > WIRE_LIMIT - 8192
                 or value['capability_bytes'] > WIRE_LIMIT - 24576))
