"""Small same-Session manifests and strict finalized-trace deltas.

No constructor, game effects, action retry, baseline promotion, or world rollback.
The r6 bootstrap alone reads its immutable 1276-record snapshot once; subsequent
manifests pin only nonbaseline record hashes plus the immutable original baseline.
"""
import copy
import hashlib
import os
from pathlib import Path
import tempfile
import time

import rebuilt_session as r
import live_session_runner as original
import session_state as ss
from terrain_planner import TerrainPlanner
import resolved_handoff as old

sha=old.sha
same=old.same
file_pin=old.file_pin
_context=old._context
KIND='same_session_small_manifest_v1'
STATE_KEYS={'serial','ctx','spec','batch','batch_number','stage','stage_number','last_id','finish_called',
 'attempted','completed','consume_state','checkpoint','jump_parent','alignment_parent','decision_serial',
 'decision_token','recovery_note','batch_expired','last_clock','reserved','accepted_decisions','pending',
 'planner','stage_uses'}
MANIFEST_KEYS={'schema_version','kind','baseline','history','header','record_hashes','trace','state','sources','reason'}
R6_KEYS={'schema_version','kind','baseline','history','state','sources','evidence','resolution_evidence',
 'restore_observation','no_action_retried','original_results_unchanged'}
ALLOWED={'resolved_same_session_restored','manifest_same_session_restored','maintenance_batch_restored',
 'gameplay_checkpoint','decision_available','decision_accepted','decision_applied','batch_checkpoint',
 'batch_open','navigation_target','stage_arrived','plan_bound','pre_start','action_finished','observation',
 'observation_wait','session_result','transport_response_timing'}


def require(condition,reason):
    if not condition:raise r.Maintenance('resume_manifest_'+reason)


def pin_raw(raw,path,expected):
    require(type(raw) is bytes and sha(raw)==expected,'explicit_bytes_pin_required')
    pin=file_pin(path);require(pin['sha256']==expected,'retained_file_pin_changed');return pin


def current_sources():
    root=Path(__file__).parent
    return {name:file_pin(root/name) for name in ('resume_manifest.py','rebuilt_session.py',
        'live_session_runner.py','terrain_planner.py','stride_policy.py','fast_pending.py',
        'run_recovery.py','terminal_resolution.py','resolved_handoff.py','session_state.py',
        'trace_handoff.py','reconcile_original.py','edge_support.py','grounded_contact.py','local_corridor.py')}


def _build(controller,state,baseline,monotonic):
    require(isinstance(state,dict) and set(state)==STATE_KEYS and state['pending']==[],
            'closed_complete_runtime_state_required')
    s=object.__new__(r.RebuiltSession)
    for key,value in state.items():
        if key not in ('planner','stage_uses'):setattr(s,key,copy.deepcopy(value))
    s.reserved=set(state['reserved']);s.accepted_decisions=set(state['accepted_decisions'])
    require(len(s.reserved)==len(state['reserved']) and len(s.accepted_decisions)==len(state['accepted_decisions'])
            and len(set(s.attempted))==len(s.attempted) and (s.finish_called is True or not s.attempted),
            'unique_reserved_and_attempted_closed_boundary_required')
    require(set(baseline['actions'])<=s.reserved and set(s.attempted)<=s.reserved
            and not set(s.attempted)&set(baseline['actions']),'all_original_reserved_ids_required')
    require(s.last_id==(s.attempted[-1] if s.attempted else None),'last_original_id_mismatch')
    s.c=controller;s.baseline=baseline;s.clock=monotonic;s.timeout=getattr(controller.transport,'scheduling_quantum',getattr(controller.transport,'timeout',None))
    return s


def _replay(s,events,result,planner,arrival,*,resolution,manifest_sha,prefix_bytes):
    controller=s.c;history=controller.ledger.data;baseline=s.baseline;ctx=s.ctx;serial=s.serial
    finished=list(s.attempted);pending_action=None;pending_decision=None;plan=None
    awaiting_batch=False;unknown_seen=0;allow_token_republish=prefix_bytes==0
    def uses(stage):return sum(history['actions'][aid]['request']['stage_id']==stage['id'] for aid in finished) if stage else 0
    def count():return len(baseline['actions'])+len(finished)
    for event_index, event in enumerate(events):
        kind = event['event']
        if kind in ('resolved_same_session_restored','manifest_same_session_restored'):
            require(event_index==0 and prefix_bytes==0 and event.get('manifest',{}).get('sha256')==manifest_sha
                    and same(event.get('context'),s.ctx) and event.get('history_count')==count()
                    and same(event.get('unfinished_stage'),s.stage) and event.get('used')==uses(s.stage),
                    'initial_manifest_trace_binding_required')
        elif kind == 'maintenance_batch_restored':
            require(same(event.get('batch'),s.batch) and same(event.get('carried_stage'),s.stage)
                    and event.get('carried_uses')==uses(s.stage) and event.get('history_count')==count(),
                    'restored_original_pool_mismatch')
        elif kind == 'batch_checkpoint':
            require(s.batch is not None and not awaiting_batch and pending_action is None,
                    'unpaired_batch_checkpoint')
            require(event.get('batch_id') == s.batch['id']
                    and event.get('original_deadline') == s.batch['deadline']
                    and same(event.get('unfinished_stage'), s.stage) and event.get('used') == uses(s.stage),
                    'batch_checkpoint_state_mismatch')
            awaiting_batch = True
        elif kind == 'batch_open':
            b = copy.deepcopy(event.get('batch'))
            require(isinstance(b, dict) and set(b) == {'id','start','deadline','ids','cursor','new_stages'},
                    'closed_batch_required')
            require((s.batch is None or awaiting_batch) and pending_action is None,
                    'unexpected_batch_allocation')
            require(b['id'] == f'{serial}:b{s.batch_number + 1}' and b['cursor'] == 0 and b['new_stages'] == 0
                    and r.finite(b['start']) and r.finite(b['deadline']) and b['deadline'] == b['start'] + 300,
                    'original_batch_deadline_and_budget_required')
            require(s.batch is not None and b['start']>=s.batch['start'],'batch_time_regression')
            ids = b['ids']
            require(isinstance(ids, list) and len(ids) == min(128, 4096 - count())
                    and len(ids) == len(set(ids)) and all(r._uuid(aid) and aid not in s.reserved for aid in ids),
                    'all_original_reserved_pools_required')
            require(event.get('history_count') == count() and same(event.get('carried_stage'), s.stage)
                    and event.get('carried_uses') == uses(s.stage), 'carried_stage_budget_mismatch')
            s.reserved.update(ids); s.batch = b; s.batch_number += 1; awaiting_batch = False
        elif kind == 'navigation_target':
            stage = event.get('stage')
            require(s.batch is not None and s.stage is None and s.checkpoint is None
                    and pending_decision is None and not awaiting_batch and event.get('source') is None,
                    'only_ordinary_planner_targets_supported')
            require(isinstance(stage, dict) and stage.get('jump_first') is False
                    and stage.get('id') == f"ls.{serial.replace('-', '_')}.nav.{s.stage_number + 1}",
                    'original_sequential_nonjump_stage_required')
            _context(event.get('observation'), ctx)
            proposed = planner.choose(event['observation'], stage['id'])
            require(same(proposed, stage), 'frozen_r4_planner_replay_mismatch')
            s.stage = copy.deepcopy(stage); s.stage_number += 1; s.batch['new_stages'] += 1
            require(s.batch['new_stages'] <= 16, 'stage_pool_exhausted')
        elif kind == 'plan_bound':
            plan = event.get('plan')
            require(s.stage is not None and isinstance(plan, dict) and set(plan) == {'parsed','raw_utf8','sha256'},
                    'ordinary_bound_plan_required')
            raw = plan['raw_utf8'].encode('utf-8')
            require(sha(raw) == plan['sha256'] and same(r.strict_json(raw), plan['parsed']), 'plan_pin_mismatch')
            parsed = plan['parsed']
            require(set(parsed) == {'version','kind','context','navigation','survival'}
                    and parsed['version'] == 4 and parsed['kind'] == 'survival'
                    and same(parsed['context'], ctx) and parsed['survival'] == []
                    and isinstance(parsed['navigation'], list) and len(parsed['navigation']) == 1,
                    'only_navigation_plan_supported')
            bound = parsed['navigation'][0]
            require(all(same(bound.get(k), s.stage[k]) for k in ('id','target','max_moves','max_looks','max_samples','jump_first')),
                    'original_target_or_budget_changed')
        elif kind == 'pre_start':
            q = event.get('request')
            require(pending_action is None and s.stage is not None and s.checkpoint is None
                    and plan is not None and not awaiting_batch, 'unpaired_or_checkpoint_action')
            require(isinstance(q, dict) and q.get('kind') == 'move' and q.get('jump_first') is False
                    and q.get('ttl_ms') == 1000 and q.get('profile') == r.PROFILE
                    and q.get('stage_id') == s.stage['id'] and q.get('plan_sha256') == plan['sha256']
                    and q.get('plan_version') == 4 and q.get('schema_version') == 1
                    and all(q.get(k) == v for k, v in ctx.items())
                    and type(q.get('samples')) is int and 1 <= q['samples'] <= s.stage['max_samples'],
                    'only_original_ordinary_move_supported')
            cursor = s.batch['cursor']
            require(cursor < len(s.batch['ids']) and q.get('id') == s.batch['ids'][cursor]
                    and event.get('batch_id') == s.batch['id'] and q['id'] not in s.attempted
                    and q.get('owner_generation') == count() + 1, 'original_batch_cursor_or_generation_mismatch')
            require(uses(s.stage) < s.stage['max_moves'], 'stage_budget_exhausted')
            s.batch['cursor'] += 1; s.attempted.append(q['id']); s.last_id = q['id']
            pending_action = copy.deepcopy(q)
        elif kind == 'action_finished':
            q = pending_action
            require(q is not None and event.get('action_id') == q['id']
                    and same(event.get('request'), q),
                    'missing_original_action_pair')
            rec = history['actions'].get(q['id']); term = event.get('terminal')
            if event.get('public_state') == 'UNKNOWN':
                require(resolution is not None and q['id'] == resolution['action_id']
                        and event.get('terminal') is None and q['id'] == result['attempted_ids'][-1]
                        and unknown_seen == 0, 'only_exact_resolved_final_unknown_allowed')
                term = resolution['terminal']
                unknown_seen += 1
            else:
                require(event.get('public_state') == 'CLOSED', 'original_public_closed_required')
            require(isinstance(rec, dict) and rec.get('state') == 'CLOSED'
                    and same(rec.get('request'), q) and same(rec.get('terminal_native'), term),
                    'retained_closed_receipt_mismatch')
            require(isinstance(term, dict) and term.get('release_proven') is True
                    and term.get('protocol_terminal') is True and term.get('unknown_lock') is False,
                    'unknown_or_unreleased_action_no_retry')
            controller._validate_receipt(term, q)
            finished.append(q['id']); s.finish_called = True; pending_action = None
        elif kind == 'stage_arrived':
            require(s.stage is not None and same(event.get('stage'), s.stage)
                    and event.get('parent_jump') is None and pending_action is None,
                    'exact_original_arrival_required')
            _context(event.get('observation'), ctx)
            original.actual_geometry(event['observation'])
            require(arrival(event['observation'], s.stage), 'actual_r4_arrival_not_established')
            planner.arrived(s.stage); s.completed.append(s.stage['id']); s.stage = None; plan = None
        elif kind == 'gameplay_checkpoint':
            require(event.get('state') == 'GAMEPLAY_CHECKPOINT'
                    and event.get('reason') == 'known_zero_or_partial_no_reissue'
                    and event.get('close_required') is False and pending_action is None
                    and same(event.get('unfinished_stage'), s.stage) and event.get('used') == uses(s.stage),
                    'unsupported_checkpoint_or_unlogged_planner_mutation')
            _context(event.get('observation'), ctx)
            s.checkpoint = dict(state=event['state'], reason=event['reason'],
                                signature=s.material(event['observation']))
        elif kind == 'decision_available':
            token = event.get('decision')
            if allow_token_republish and same(token, s.decision_token):
                require(same(event.get('checkpoint'), s.checkpoint)
                        and event.get('jump_parent') is None and event.get('alignment_parent') is None,
                        'republished_original_token_mismatch')
                allow_token_republish = False
                continue
            require(s.checkpoint is not None and same(event.get('checkpoint'), s.checkpoint)
                    and event.get('jump_parent') is None and event.get('alignment_parent') is None
                    and isinstance(token, dict) and set(token) == {'token','session_id','context','history_count','decision_serial'}
                    and r._uuid(token['token']) and token['session_id'] == serial and same(token['context'], ctx)
                    and token['history_count'] == count() and token['decision_serial'] == s.decision_serial + 1,
                    'original_checkpoint_token_required')
            s.decision_serial += 1; s.decision_token = copy.deepcopy(token)
        elif kind == 'decision_accepted':
            command = event.get('command'); token = s.decision_token
            require(pending_decision is None and s.checkpoint is not None and token is not None
                    and isinstance(command, dict) and set(command) == r.COMMAND_KEYS
                    and command['schema_version'] == 1 and command['kind'] == 'continue_local' and command['args'] == {}
                    and all(same(command[k], token[k]) for k in ('token','session_id','context','history_count'))
                    and command['history_count'] == count() and r._uuid(command['decision_id'])
                    and command['decision_id'] not in s.accepted_decisions
                    and event.get('proposal') == {'kind':'continue_local'}, 'only_original_unused_continue_decision_supported')
            _context(event.get('observation'), ctx)
            pending_decision = command['decision_id']; s.accepted_decisions.add(pending_decision); s.decision_token = None
        elif kind == 'decision_applied':
            require(pending_decision is not None and event.get('decision_id') == pending_decision
                    and event.get('kind') == 'continue_local' and same(event.get('stage'), s.stage),
                    'decision_acceptance_not_fully_applied')
            pending_decision = None; s.checkpoint = None
        elif kind == 'transport_response_timing':
            # Diagnostics only: never authorize/allocate/retry any action.
            continue
        elif kind == 'observation':
            _context(event.get('observation'), ctx)
        elif kind == 'observation_wait':
            require(same(event.get('unfinished_stage'), s.stage) and event.get('used') == uses(s.stage),
                    'read_wait_changed_stage_or_budget')
        elif kind == 'session_result':
            require(same(result.get('attempted_ids'), s.attempted)
                    and same(result.get('completed_stages'), s.completed)
                    and same(result.get('unfinished_stage'), s.stage)
                    and result.get('unfinished_uses') == uses(s.stage)
                    and result.get('batches') == s.batch_number and result.get('final_count') == count(),
                    'final_state_not_fully_reconstructed')
    require(not awaiting_batch and pending_action is None and pending_decision is None
            and s.attempted==finished,'finalized_pairs_required')
    _result_matches(s,result)
    return s,planner


def _result_matches(s,result):
    require(result.get('session_id')==s.serial and same(result.get('attempted_ids'),s.attempted)
            and same(result.get('completed_stages'),s.completed) and same(result.get('unfinished_stage'),s.stage)
            and result.get('unfinished_uses')==(s.stage_uses(s.stage['id']) if s.stage else 0)
            and result.get('batches')==s.batch_number
            and result.get('final_count')==len(s.baseline['actions'])+len(s.attempted),
            'final_result_state_not_preserved')


def validate_resolution(controller,raw,path,expected):
    """Re-run the generic pure proof checker on a shallow original-record view."""
    from types import SimpleNamespace
    from maintenance5_controller.transport import RawReply
    import terminal_resolution as tr
    pin=pin_raw(raw,path,expected);result=r.strict_json(raw)
    base_keys=(old.RESOLUTION_BASE_KEYS|{'requested_calls'})
    result_keys=base_keys|{'state','unknown_lock','final_count','after_ledger_sha256',
        'after_record_sha256','evidence_dir','original_request_unchanged','unrelated_records_unchanged'}
    require(isinstance(result,dict) and set(result)==result_keys and result.get('kind')==tr.KIND
            and result.get('schema_version')==1 and result.get('resolved') is True
            and result.get('no_effect_retried') is True and result.get('state')=='CLOSED'
            and result.get('unknown_lock') is False and result.get('original_request_unchanged') is True
            and result.get('unrelated_records_unchanged') is True,'generic_committed_resolution_required')
    directory=ss._safe_path(result['evidence_dir'],existing=True,directory=True)
    require(Path(pin['path']).parent==directory,'resolution_directory_mismatch')
    files={}
    def read(name,digest):
        data=ss._read(directory/name);files[name]=pin_raw(data,directory/name,digest);return data
    original_raw=read('ORIGINAL-ACTION.json',result['original_record_sha256']);record=r.strict_json(original_raw)
    fresh=read('FRESH-STATUS.json',result['fresh_status_sha256'])
    observation=r.strict_json(read('FRESH-OBSERVATION.json',result['fresh_observation_sha256']))
    independent=None
    if result['independent_status_sha256'] is not None:
        independent=read('INDEPENDENT-STATUS.json',result['independent_status_sha256'])
    history=r.idle(controller);aid=result['original_id'];current=history['actions'].get(aid)
    require(r._uuid(aid) and record.get('request',{}).get('id')==aid and isinstance(current,dict)
            and result['final_count']==len(history['actions'])
            and sha(r.encode(current))==result['after_record_sha256'],'committed_original_record_pin_required')
    before=dict(history,actions=dict(history['actions']),unknown_lock=True);before['actions'][aid]=record
    proxy=SimpleNamespace(ledger=SimpleNamespace(data=before),owner_id=controller.owner_id,
        _validate_receipt=controller._validate_receipt,validate_request=controller.validate_request,
        MAX_EVIDENCE=controller.MAX_EVIDENCE)
    proposed,proof=tr.proposal(proxy,aid,RawReply(200,fresh,True),observation,
        before_sha256=result['original_ledger_sha256'],independent_raw=independent)
    require(same(proof,{key:result[key] for key in base_keys})
            and same(proposed['actions'][aid],current),'exact_retained_evidence_resolution_delta_required')
    history_pin=file_pin(controller.ledger.path)
    require(history_pin['sha256']==result['after_ledger_sha256'],'committed_history_pin_required')
    return dict(action_id=aid,terminal=current['terminal_native'],proof=result),history_pin,dict(result=pin,**files)


def _atomic(path,value):
    path=ss._safe_path(path,existing=False);require(not path.exists(),'new_state_evidence_required')
    raw=ss.encode(value);require(len(raw)<2*1024*1024,'small_manifest_required')
    fd,temp=tempfile.mkstemp(prefix='.manifest-',dir=path.parent)
    try:
        os.fchmod(fd,0o600)
        with os.fdopen(fd,'wb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
        os.replace(temp,path)
        for directory in (path.parent,path.parent.parent):
            fd=os.open(directory,os.O_RDONLY|os.O_DIRECTORY)
            try:os.fsync(fd)
            finally:os.close(fd)
    finally:
        if os.path.exists(temp):os.unlink(temp)
    return file_pin(path)


def save_state(s,*,baseline_path=None,reason='terminal',path=None):
    """Save a terminal/read-only state, including sticky UNKNOWN, never retry.

    Invoke after Session.result has flushed trace and written RESULT. This
    writer does not require idle when recording an unresolved original action.
    No baseline record is serialized; only this Session's added record hashes.
    """
    require(s.pending==[] and (s.finish_called is True or not s.attempted),'no_inflight_runtime_snapshot')
    data=s.c.ledger.data;actions=data['actions']
    unknown=[aid for aid,rec in actions.items() if rec.get('state')!='CLOSED']
    require(not unknown or (unknown==[s.last_id] and actions[s.last_id].get('state')=='UNKNOWN'
            and data.get('unknown_lock') is True),'only_last_sticky_unknown_may_be_recorded')
    require(unknown or data.get('unknown_lock') is False,'known_header_required')
    require(set(actions)==set(s.baseline['actions'])|set(s.attempted)
            and all(actions.get(aid)==rec for aid,rec in s.baseline['actions'].items()),
            'complete_original_baseline_and_session_history_required')
    base=getattr(s,'_resume_baseline_pin',None)
    if baseline_path is not None:
        pin=file_pin(baseline_path)
        require(pin['sha256']==s.spec['baseline_sha256'],'original_baseline_pin_required')
        base=dict(**pin,count=len(s.baseline['actions']))
    require(isinstance(base,dict) and base['count']==s.spec['baseline_count'],'immutable_baseline_reference_required')
    trace=file_pin(s.trace) if Path(s.trace).exists() else dict(path=str(s.trace),bytes=0,sha256=sha(b''))
    history=file_pin(s.c.ledger.path)
    value=dict(schema_version=1,kind=KIND,baseline=base,history=dict(**history,count=len(actions)),
        header={key:copy.deepcopy(value) for key,value in data.items() if key!='actions'},
        record_hashes={aid:sha(r.encode(actions[aid])) for aid in s.attempted},trace=trace,
        state=old._state(s),sources=current_sources(),reason=reason)
    output=Path(path) if path else s.out/f'STATE-{len(actions)}-{trace["bytes"]}.json'
    pin=_atomic(output,value);s._resume_baseline_pin=base
    return pin


def reconstruct(controller,*,manifest_raw,manifest_path,expected_manifest_sha256,
        trace_raw,trace_path,expected_trace_sha256,result_raw,result_path,expected_result_sha256,
        baseline_path,expected_baseline_sha256,session_spec_raw,expected_session_spec_sha256,
        resolution_raw=None,resolution_path=None,expected_resolution_sha256=None,
        source_history_path=None,baseline=None,baseline_raw=None,monotonic=time.monotonic):
    """Pure reconstruction from a small state plus its finalized trace delta."""
    source_pin=pin_raw(manifest_raw,manifest_path,expected_manifest_sha256)
    manifest=r.strict_json(manifest_raw)
    require(isinstance(manifest,dict) and manifest.get('schema_version')==1,'versioned_manifest_required')
    modern=manifest.get('kind')==KIND
    require((modern and set(manifest)==MANIFEST_KEYS) or (not modern and set(manifest)==R6_KEYS
            and manifest.get('kind')=='explicit_resolved_same_session_handoff_v1'),'closed_manifest_schema_required')
    trace_pin=pin_raw(trace_raw,trace_path,expected_trace_sha256)
    result_pin=pin_raw(result_raw,result_path,expected_result_sha256)
    require(trace_raw.endswith(b'\n'),'complete_final_trace_required')
    events=[r.strict_json(line) for line in trace_raw.splitlines()];result=r.strict_json(result_raw)
    require(events and events[-1].get('event')=='session_result'
            and sum(e.get('event')=='session_result' for e in events)==1
            and same(events[-1].get('result'),result) and result.get('close_required') is True
            and result.get('historical_prefix_exact') is True,'unchanged_finalized_result_required')
    require(result.get('state') in ('STOPPED','MAINTENANCE_REQUIRED'),'terminal_maintenance_or_stop_required')
    spec=original.validate_spec(session_spec_raw,expected_session_spec_sha256)
    basepin=file_pin(baseline_path)
    require(basepin['sha256']==expected_baseline_sha256==spec['baseline_sha256']
            and all(manifest['baseline'].get(k)==basepin[k] for k in ('sha256','bytes'))
            and manifest['baseline'].get('count')==spec['baseline_count'],'original_immutable_baseline_required')
    if baseline_raw is not None:require(sha(baseline_raw)==expected_baseline_sha256,'baseline_raw_pin_changed')
    if baseline is None:baseline=r.strict_json(baseline_raw if baseline_raw is not None else ss._read(baseline_path))
    history=r.idle(controller)
    require(isinstance(baseline,dict) and len(baseline.get('actions',{}))==spec['baseline_count']
            and all(history['actions'].get(aid)==rec for aid,rec in baseline['actions'].items()),'baseline_prefix_changed')
    s=_build(controller,manifest['state'],baseline,monotonic)
    require(same(s.spec,spec) and s.ctx.get('owner_id')==controller.owner_id==r.OWNER
            and s.ctx.get('player_uuid')==r.PLAYER and r._uuid(s.serial)
            and all(e.get('session_id')==s.serial for e in events),'same_original_session_required')
    resolution=None;proof_pins=None
    if resolution_raw is not None:
        resolution,history_pin,proof_pins=validate_resolution(controller,resolution_raw,resolution_path,expected_resolution_sha256)
        require(result.get('unknown_lock') is True and result.get('state')=='MAINTENANCE_REQUIRED'
                and result.get('reason')=='original_action_unresolved_no_reissue'
                and result.get('attempted_ids',[])[-1]==resolution['action_id']
                and same(resolution['proof']['context'],s.ctx),'resolved_exact_original_maintenance_required')
    else:
        require(result.get('unknown_lock') is False,'unknown_requires_explicit_resolution')
        history_pin=file_pin(controller.ledger.path)
    source_actions=set(baseline['actions'])|set(s.attempted)
    require(len(source_actions)==manifest['history']['count'],'source_manifest_count_mismatch')
    if modern:
        hashes=manifest['record_hashes'];require(set(hashes)==set(s.attempted),'all_session_record_hashes_required')
        expected_header={key:copy.deepcopy(value) for key,value in manifest['header'].items()}
        expected_header['unknown_lock']=False
        require(same(expected_header,{key:value for key,value in history.items() if key!='actions'}),'history_header_changed')
        for aid,digest in hashes.items():
            rec=history['actions'].get(aid)
            require(isinstance(rec,dict),'retained_original_record_missing')
            if resolution and aid==resolution['action_id']:
                require(digest==resolution['proof']['original_record_sha256'],'unknown_manifest_record_pin_changed')
            else:require(sha(r.encode(rec))==digest,'retained_session_record_changed')
        prefix=manifest['trace'];prefix_bytes=prefix['bytes']
        require(type(prefix_bytes) is int and 0<=prefix_bytes<=len(trace_raw)
                and sha(trace_raw[:prefix_bytes])==prefix['sha256']
                and (prefix_bytes==0 or trace_raw[:prefix_bytes].endswith(b'\n')),'source_trace_prefix_changed')
        delta=[r.strict_json(line) for line in trace_raw[prefix_bytes:].splitlines()]
    else:
        require(source_history_path is not None,'r6_immutable_complete_source_history_required')
        pin=file_pin(source_history_path)
        require(all(pin[k]==manifest['history'][k] for k in ('sha256','bytes')),'r6_source_history_pin_changed')
        source_history=r.strict_json(ss._read(source_history_path))
        require(set(source_history['actions'])==source_actions and source_history.get('unknown_lock') is False
                and same({k:v for k,v in source_history.items() if k!='actions'},
                         {k:v for k,v in history.items() if k!='actions'})
                and all(history['actions'].get(aid)==rec for aid,rec in source_history['actions'].items()),
                'all_original_r6_records_must_be_unchanged')
        del source_history
        prefix_bytes=0;delta=events
    require(all(e.get('event') in ALLOWED for e in delta),'unsupported_unlogged_state_transition')
    # Frozen predecessor policy, not a new choose implementation, interprets any delta.
    def frozen(name):
        pin=manifest['sources'].get(name) if modern else manifest['sources'].get('current_'+name)
        require(isinstance(pin,dict),'frozen_source_pin_required')
        return old.frozen_module(pin['path'],pin['sha256'],'manifest_'+name.replace('.','_'))
    planner=frozen('terrain_planner.py').TerrainPlanner.restore(manifest['state']['planner'])
    require(same(planner.snapshot(),manifest['state']['planner']),'frozen_planner_state_changed')
    arrival=frozen('stride_policy.py').arrived
    require(manifest['state']['stage_uses']==sum(history['actions'][aid]['request'].get('stage_id')==s.stage['id']
            for aid in s.attempted) if s.stage else manifest['state']['stage_uses']==0,'original_stage_budget_mismatch')
    s,planner=_replay(s,delta,result,planner,arrival,resolution=resolution,
        manifest_sha=expected_manifest_sha256,prefix_bytes=prefix_bytes)
    require(set(history['actions'])==set(baseline['actions'])|set(s.attempted),'unowned_new_history_records')
    if resolution:
        require(s.last_id==resolution['action_id'] and s.finish_called and s.pending==[]
                and resolution['proof']['retained_stage_uses']==s.stage_uses(resolution['proof']['stage_id']),
                'resolved_original_stage_budget_mismatch')
    state=planner.snapshot();s.planner=TerrainPlanner.restore(state)
    require(same(state,s.planner.snapshot()),'new_policy_lost_planner_state')
    s.batch_expired=True;s.last_clock=monotonic();require(r.finite(s.last_clock),'valid_clock_required')
    s._resume_baseline_pin=dict(**basepin,count=len(baseline['actions']))
    s._resume_provenance=dict(manifest=source_pin,trace=trace_pin,result=result_pin,resolution=proof_pins)
    require(file_pin(controller.ledger.path)==history_pin,'history_changed_during_restore')
    return s,history_pin


def restore(controller,*,initial_observation,outdir,confirm_world,stop_requested=lambda:False,
            on_event=lambda event:None,decision_reader=lambda checkpoint:None,sleep=time.sleep,
            session_started_at=None,**kwargs):
    s,history_pin=reconstruct(controller,**kwargs)
    output=ss._safe_path(outdir,existing=False);require(not output.exists(),'new_evidence_directory_required')
    s.stop_requested=stop_requested;s.sleep=sleep;s.on_event=on_event;s.decision_reader=decision_reader
    s.check_context(initial_observation)
    fresh=r.observe_wait(controller,stop_requested=stop_requested,sleep=sleep);s.now();s.check_context(fresh)
    require(confirm_world(fresh) is True and file_pin(controller.ledger.path)==history_pin,
            'fresh_same_world_and_history_confirmation_required')
    if s.checkpoint is None:
        require(s.decision_token is None,'consumed_token_must_not_return')
        s.checkpoint=dict(state='GAMEPLAY_CHECKPOINT',reason='known_zero_or_partial_no_reissue',signature=s.material(fresh))
        s._checkpoint_token()
    else:require(s.decision_token is not None,'checkpoint_original_token_required')
    output.mkdir(parents=True,mode=0o700);s.out=output;s.trace=output/'trace.jsonl'
    pin=save_state(s,reason='restored_explicit_original_same_session',path=output/'RESUME-MANIFEST.json')
    s.emit('manifest_same_session_restored',manifest=pin,context=s.ctx,history_count=len(s.c.ledger.data['actions']),
        original_batch_deadline=s.batch['deadline'],batch_expired=True,unfinished_stage=s.stage,
        used=s.stage_uses(s.stage['id']) if s.stage else 0,no_action_retried=True,
        source=s._resume_provenance)
    s.emit('maintenance_batch_restored',batch=s.batch,carried_stage=s.stage,
        carried_uses=s.stage_uses(s.stage['id']) if s.stage else 0,history_count=len(s.c.ledger.data['actions']))
    s.emit('decision_available',checkpoint=s.checkpoint,decision=s.decision_token,
        jump_parent=s.jump_parent,alignment_parent=s.alignment_parent)
    return s
