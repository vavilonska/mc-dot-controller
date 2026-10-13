"""One explicit fixture-free gate-off probe using the existing resident mailbox."""
from pathlib import Path
import json
import os
import time

from resident_controller.ipc import ID, atomic_json
from gate_probe_contract import probe_body


def run_gate_off_case(client, request_id, binding, *, authorization_ref):
    """No live transport construction, fixtures, cleanup, retries or cancellation."""
    if not isinstance(authorization_ref, str) or not authorization_ref.strip():
        raise ValueError('gate_probe_authorization_required')
    if not isinstance(request_id, str) or not ID.fullmatch(request_id):
        raise ValueError('gate_probe_request_id_invalid')
    if set(binding) != {'resident_session', 'action_session', 'world_generation', 'player_uuid'}:
        raise ValueError('gate_probe_binding_fields')
    session = client.session()
    if (session.get('session_id') != binding['resident_session'] or session.get('state') != 'ready'
            or session.get('active_request_id') is not None or session.get('active_action_id') is not None
            or session.get('pending') != 0
            or session.get('bridge_identity', {}).get('action_session') != binding['action_session']):
        raise ValueError('gate_probe_requires_bound_idle_resident')
    command = {'op':'encounter_gate_off_probe', 'probe_schema_version':1,
        'expected_resident_session':binding['resident_session'],
        'expected_action_session':binding['action_session'],
        'expected_world_generation':binding['world_generation'],
        'expected_player_uuid':binding['player_uuid']}
    expected_body = probe_body(dict(command, request_id=request_id), binding['resident_session'])
    root = Path(client.root) / 'gate-off-case-evidence'
    root.mkdir(exist_ok=True)
    record = {'request_id':request_id,'command':command,'authorization_ref':authorization_ref,
              'targets_are_unspawned_test_identifiers':True,'fixture_registration':False,
              'automatic_retry':False,'submitted':False,'result':None,'probe_passed':False}
    # Fixed queue-scoped exclusive intent; changing output cannot renew this ID.
    with (root / (request_id + '.intent.json')).open('x') as stream:
        json.dump(record,stream,allow_nan=False);stream.flush();os.fsync(stream.fileno())
    try:
        record['submit_started_monotonic']=time.monotonic()
        record['submitted']=True  # Attempted, not a claim that the write arrived.
        returned=client.submit(command,request_id=request_id)
        if returned != request_id:
            raise ValueError('gate_probe_submit_identity_changed')
        receipt=client.wait(request_id,20)
        record['result']=receipt
        proof=receipt.get('result',{}) if isinstance(receipt,dict) else {}
        record['probe_passed']=(isinstance(receipt,dict) and receipt.get('request_id')==request_id
            and receipt.get('session_id')==binding['resident_session'] and receipt.get('status')=='succeeded'
            and proof.get('request_id') == request_id and proof.get('body') == expected_body
            and proof.get('probe_passed') is True and proof.get('http_status')==409
            and proof.get('native_error')=='encounter_stage1_disabled'
            and proof.get('expected_rejection') is True
            and proof.get('ownership_and_inputs_unchanged') is True
            and proof.get('targets_declared_unspawned_test_identifiers') is True)
    except Exception as exc:
        record['stop_reason']=type(exc).__name__
    record['finished_monotonic']=time.monotonic()
    atomic_json(root / (request_id + '.result.json'),record)
    return record
