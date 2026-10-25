"""Explicit, one-original-ID maintenance resolution; no gameplay transport.

This is an extension to C8's intentionally sticky public UNKNOWN, not an existing
C8 API.  It only recognizes the independently observed, released, zero-input
terminal of the specified original action. All uncertain evidence is retained.
"""
from __future__ import annotations
import argparse
import base64
import copy
import hashlib
import os
from pathlib import Path
import sys
from urllib.parse import urlencode

ORIGINAL_ID = '168600cd-1eda-4e4c-83ef-b93231525f34'
KIND = 'explicit_original_zero_input_resolution_v1'

class ResolutionRefused(ValueError): pass

def require(value, reason):
    if not value: raise ResolutionRefused(reason)

def sha(raw): return hashlib.sha256(raw).hexdigest()

def private_read(path, limit=128*1024*1024):
    from run_recovery import safe_read
    return safe_read(path, limit, True)

def write_new(path, raw):
    from run_recovery import write_new as write
    write(path, raw)

def status_path(controller, request):
    return controller.route(request)+'status?'+urlencode({k:request[k] for k in ('id','session','owner_id','owner_generation')})

def proposed_resolution(controller, *, original_id, before_raw, independent_raw,
                        fresh_reply, observation, code_sha256):
    from survival6_controller.legacy import encode, strict_json
    require(original_id == ORIGINAL_ID, 'only_explicit_original_id_allowed')
    data = controller.ledger.data
    require(encode(data) == before_raw, 'exact_locked_before_history_required')
    rec = data['actions'].get(original_id)
    require(type(rec) is dict and rec.get('state') == 'UNKNOWN'
            and rec.get('terminal_native') is None and data['unknown_lock'] is True,
            'original_unresolved_record_required')
    require(len(data['actions']) == 1276 and all(k == original_id or r['state'] == 'CLOSED'
            for k,r in data['actions'].items()), 'sole_original_unknown_complete_1276_history_required')
    require(rec.get('unknown_reasons') == ['start_receipt_uncertain']
            and rec.get('stop_attempted') is True, 'specific_retained_uncertain_start_required')
    req = rec['request']
    require(req['id'] == original_id and req['owner_id'] == controller.owner_id
            and req['profile'] == 'recovery_survival_v6' and req['kind'] == 'move',
            'exact_original_owner_move_required')
    require(fresh_reply.complete is True and fresh_reply.status == 200
            and len(fresh_reply.body) <= 65536, 'fresh_complete_original_status_required')
    independent = strict_json(independent_raw)
    fresh = strict_json(fresh_reply.body)
    for receipt in (independent, fresh, rec.get('latest_native')):
        controller._validate_receipt(receipt, req)
        require(receipt['state'] == 'SETTLED' and receipt['protocol_state'] == 'SETTLED'
                and receipt['protocol_terminal'] is True and receipt['settled'] is True
                and receipt['applied_calls'] == 0 and receipt['effect_state'] == 'not_started'
                and receipt['input_invalidated'] is True and receipt['release_proven'] is True
                and receipt['release_state'] == 'not_needed' and receipt['unknown_lock'] is False,
                'complete_zero_input_released_terminal_required')
    require(independent == fresh == rec['latest_native'], 'independent_and_fresh_terminal_must_match')
    retained = []
    for evidence in rec['evidence']:
        if evidence['kind'] in ('stop','status') and evidence['complete'] is True and evidence['http_status'] == 200:
            receipt = strict_json(base64.b64decode(evidence['raw_base64'], validate=True))
            controller._validate_receipt(receipt, req)
            require(receipt == fresh, 'retained_native_terminal_conflict')
            retained.append(evidence['kind'])
    require('stop' in retained and 'status' in retained and any(e['kind']=='start'
            and e['complete'] is False for e in rec['evidence']), 'original_uncertain_and_terminal_evidence_required')
    require(type(observation) is dict and observation.get('profile') == req['profile']
            and observation.get('bound_owner_id') == req['owner_id']
            and all(observation.get(k)==req[k] for k in ('session','world_generation','player_uuid'))
            and observation.get('active_id') is None and observation.get('unknown_lock') is False
            and observation.get('owner_generation') == len(data['actions'])+1,
            'fresh_idle_same_native_context_required')
    require('resolution' not in rec, 'resolution_cannot_be_reapplied')
    resolution = dict(schema_version=1, kind=KIND, original_id=original_id,
        original_public_state='UNKNOWN', original_record_sha256=sha(encode(rec)),
        original_ledger_sha256=sha(before_raw), independent_status_sha256=sha(independent_raw),
        fresh_status_sha256=sha(fresh_reply.body), fresh_observation_sha256=sha(encode(observation)),
        source_sha256=code_sha256, original_unknown_reasons=list(rec['unknown_reasons']),
        resolved=True, no_effect_retried=True, applied_calls=0,
        context={k:req[k] for k in ('session','world_generation','player_uuid','owner_id')},
        stage_id=req['stage_id'], retained_stage_uses=sum(r['request'].get('stage_id')==req['stage_id']
            for r in data['actions'].values()))
    replacement = copy.deepcopy(rec)
    replacement['evidence'].append(dict(kind='status', complete=True, http_status=200,
        raw_base64=base64.b64encode(fresh_reply.body).decode('ascii')))
    replacement.update(state='CLOSED', terminal_native=copy.deepcopy(fresh),
        latest_native=copy.deepcopy(fresh), resolution=resolution)
    proposed = dict(data, actions=dict(data['actions']), unknown_lock=False)
    proposed['actions'][original_id] = replacement
    require(all(proposed['actions'][k] is r for k,r in data['actions'].items() if k!=original_id),
            'unrelated_history_must_be_untouched')
    return proposed, resolution

def cli(argv=None):
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--source-root',required=True);ap.add_argument('--recovery-root',required=True)
    ap.add_argument('--original-id',required=True);ap.add_argument('--before-ledger-sha256',required=True)
    ap.add_argument('--independent-status',required=True);ap.add_argument('--independent-status-sha256',required=True)
    ap.add_argument('--evidence-dir',required=True);ap.add_argument('--endpoint',required=True)
    args=ap.parse_args(argv)
    require(args.original_id==ORIGINAL_ID,'only_explicit_original_id_allowed')
    source=Path(args.source_root).resolve();root=Path(args.recovery_root).resolve()
    sys.path.insert(0,str(source/'survival6-controller'))
    from survival6_controller import Controller
    from survival6_controller.legacy import encode,ROOT
    from maintenance5_controller.transport import HttpTransport
    ledger=root/'controller-state';before_raw=private_read(ledger/'ledger.json')
    require(sha(before_raw)==args.before_ledger_sha256,'explicit_before_ledger_pin_required')
    independent_raw=private_read(args.independent_status,65536)
    require(sha(independent_raw)==args.independent_status_sha256,'independent_terminal_pin_required')
    out=Path(args.evidence_dir).absolute()
    require(not out.exists() and not any(p.is_symlink() for p in (out,*out.parents)), 'new_private_evidence_directory_required')
    game=root/'polymc-data/instances/MDC-RECOVERY-F1220-20261022/minecraft'
    token=private_read(game/'config/mineclient-bridge.token',512).decode('ascii').strip()
    class ReadOnlyTransport(HttpTransport):
        allowed_status=None
        def request(self,method,path,body=None):
            require(method=='GET' and body is None and path in (ROOT+'observe',self.allowed_status),
                    'resolution_transport_only_exact_get_no_post')
            return super().request(method,path,body)
    transport=ReadOnlyTransport(args.endpoint,token,2.)
    with Controller(ledger,transport) as controller:
        require(sha(private_read(ledger/'ledger.json'))==args.before_ledger_sha256,
                'history_changed_before_original_resolution')
        rec=controller.ledger.data['actions'].get(ORIGINAL_ID)
        require(type(rec) is dict,'original_record_required')
        transport.allowed_status=status_path(controller,rec['request'])
        fresh=transport.request('GET',transport.allowed_status)
        observation=controller.observe()
        proposed,resolution=proposed_resolution(controller,original_id=ORIGINAL_ID,
            before_raw=before_raw,independent_raw=independent_raw,fresh_reply=fresh,
            observation=observation,code_sha256=sha(Path(__file__).read_bytes()))
        out.mkdir(parents=True,mode=0o700)
        write_new(out/'BEFORE-LEDGER.json',before_raw)
        write_new(out/'ORIGINAL-ACTION.json',encode(rec))
        write_new(out/'INDEPENDENT-STATUS.json',independent_raw)
        write_new(out/'FRESH-STATUS.json',fresh.body)
        write_new(out/'FRESH-OBSERVATION.json',encode(observation))
        write_new(out/'INTENT.json',encode(resolution))
        for directory in (out,out.parent):
            fd=os.open(directory,os.O_RDONLY|os.O_DIRECTORY)
            try:os.fsync(fd)
            finally:os.close(fd)
        # Original atomic complete-ledger save: no manual file edit or new epoch.
        controller.ledger.data=proposed
        try: controller.ledger.save()
        except BaseException:
            write_new(out/'COMMIT-UNCERTAIN.json',encode(dict(kind=KIND,state='inspect_original_file_no_retry')))
            raise
        after_raw=private_read(ledger/'ledger.json')
        require(after_raw==encode(proposed),'committed_complete_history_verification_required')
        result=dict(resolution, state='CLOSED', unknown_lock=False, final_count=1276,
            after_ledger_sha256=sha(after_raw), after_record_sha256=sha(encode(proposed['actions'][ORIGINAL_ID])),
            evidence_dir=str(out), original_request_unchanged=True, unrelated_1275_records_unchanged=True)
        write_new(out/'RESULT.json',encode(result))
        print(encode(result).decode())
    return 0

if __name__=='__main__': raise SystemExit(cli())
