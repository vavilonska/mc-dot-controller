"""Small session projection with immutable content-addressed diagnostic evidence."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re

from .ipc import MAX_SESSION_BYTES, atomic_json, read_json
from .transport import json_bytes

INLINE_DIAGNOSTIC_BYTES = 8192
MAX_DIAGNOSTIC_BYTES = 2 * 1024 * 1024
MAX_DIAGNOSTIC_FILES = 256


def compact_session(root, data):
    result = deepcopy(data)
    terrain = result.get('terrain_read')
    if isinstance(terrain, dict) and isinstance(terrain.get('diagnostics'), dict):
        diagnostics = terrain['diagnostics']
        if len(json_bytes(diagnostics)) > INLINE_DIAGNOSTIC_BYTES:
            document = {'schema_version': 1, 'session_id': data['session_id'], 'diagnostics': diagnostics}
            encoded = json_bytes(document)
            if len(encoded) > MAX_DIAGNOSTIC_BYTES:
                raise ValueError('session_diagnostic_too_large_evidence_not_dropped')
            sha = hashlib.sha256(encoded).hexdigest()
            directory = Path(root) / 'diagnostics'
            directory.mkdir(mode=0o700, exist_ok=True)
            path = directory / (sha + '.json')
            if path.exists():
                # A digest-named file is immutable. Never overwrite mismatched evidence.
                with path.open('rb') as stream:
                    retained = stream.read(MAX_DIAGNOSTIC_BYTES + 1)
                if retained != encoded:
                    raise ValueError('session_diagnostic_existing_digest_mismatch')
            elif sum(1 for _ in directory.glob('*.json')) >= MAX_DIAGNOSTIC_FILES:
                # Keep the full data inline while bounded session space permits; never evict failures.
                terrain['diagnostics_storage_status'] = 'reference_capacity_full_full_evidence_inline'
                if len(json_bytes(result)) > MAX_SESSION_BYTES:
                    raise ValueError('session_diagnostic_capacity_full_evidence_not_dropped')
                return result
            else:
                atomic_json(path, document)
            terrain.pop('diagnostics')
            terrain['diagnostics_ref'] = {'schema_version': 1, 'session_id': data['session_id'],
                'sha256': sha, 'bytes': len(encoded), 'path': 'diagnostics/' + sha + '.json'}
            terrain['diagnostics_summary'] = {key: deepcopy(diagnostics[key]) for key in
                ('schema_version','clock','time_origin','total_budget_ms','actual_attempts','attempts_entered',
                 'total_elapsed_ms','remaining_total_ms','network_elapsed_ms','http_queue_elapsed_ms',
                 'python_cpu_elapsed_ms','attribution_status','clock_observation_errors') if key in diagnostics}
            terrain['diagnostics_summary']['attempts'] = [{key: deepcopy(attempt[key]) for key in
                ('attempt','outcome','last_rejection','original_rejection','rejection_phase') if key in attempt}
                for attempt in diagnostics.get('attempts', [])]
            if len(json_bytes(terrain['diagnostics_summary'])) > INLINE_DIAGNOSTIC_BYTES:
                # Exact evidence is retained above. Explicitly say a larger summary was omitted.
                terrain['diagnostics_summary'] = {'status': 'summary_exceeds_bound_use_complete_reference'}
            terrain['diagnostics_storage_status'] = 'complete_reference'
    if len(json_bytes(result)) > MAX_SESSION_BYTES:
        raise ValueError('session_too_large_evidence_not_dropped')
    return result


def read_diagnostic(root, session_id, reference):
    if (type(reference) is not dict or set(reference) != {'schema_version','session_id','sha256','bytes','path'}
            or type(reference.get('schema_version')) is not int or reference['schema_version'] != 1
            or reference.get('session_id') != session_id
            or type(reference.get('sha256')) is not str or re.fullmatch(r'[0-9a-f]{64}', reference['sha256']) is None
            or type(reference.get('bytes')) is not int or not 0 < reference['bytes'] <= MAX_DIAGNOSTIC_BYTES
            or reference.get('path') != 'diagnostics/' + reference['sha256'] + '.json'):
        raise ValueError('invalid_session_diagnostic_reference')
    path = Path(root) / reference['path']
    if path.is_symlink():
        raise ValueError('invalid_session_diagnostic_file')
    with path.open('rb') as stream:
        raw = stream.read(MAX_DIAGNOSTIC_BYTES + 1)
    if len(raw) != reference['bytes'] or hashlib.sha256(raw).hexdigest() != reference['sha256']:
        raise ValueError('session_diagnostic_digest_mismatch')
    document = json.loads(raw, parse_constant=lambda _: (_ for _ in ()).throw(ValueError('invalid_session_diagnostic_json')))
    if not isinstance(document, dict):
        raise ValueError('invalid_session_diagnostic_json')
    if document.get('session_id') != session_id or document.get('schema_version') != 1:
        raise ValueError('session_diagnostic_identity_mismatch')
    return document
