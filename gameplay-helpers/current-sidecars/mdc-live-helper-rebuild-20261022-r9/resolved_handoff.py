"""One explicit r4 -> r5 -> resolved-1276 maintenance handoff, never retry.

The original r5 UNKNOWN trace/result remains immutable. Only an externally
SHA-pinned reconciliation proof may account for its exact last action becoming
CLOSED with a known zero-effect terminal. This is not generic crash recovery.
Large baseline/history JSON is never copied or serialized by this module;
the supplied parsed baseline is held by reference and the small manifest pins
its immutable file. No call to the generic 103 MB snapshot implementation.
"""
import copy
import hashlib
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import time

import rebuilt_session as r
import live_session_runner as original
import session_state as ss
from terrain_planner import TerrainPlanner
from trace_handoff import R4_PINS, R4_VERSION, ALLOWED as R4_ALLOWED

ACTION_ID = '168600cd-1eda-4e4c-83ef-b93231525f34'
R5_PINS = {
 'rebuilt_session.py': '7015d30a1f86f571a4d0c057d5fbd7ec5d20ba36c72a3167240d974f0eaab2eb',
 'terrain_planner.py': '49c7b27e74268723dec09bcc83629dc1679994d2b8b2c95724bed987dc4d5384',
 'stride_policy.py': '744c299345d7cb25d5ecb45c1a480c065c2414f04f674dc0c636b10c0fde8001',
 'trace_handoff.py': '2b8e544fe429b4f01e58bf9fa5db887d032ce091371e468c91ecbfeaf0fe4b22',
}
MIGRATION_EVENTS = {'session_restored','trace_policy_upgrade_restored','maintenance_batch_restored'}


def require(value, reason):
    if not value: raise r.Maintenance('resolved_handoff_' + reason)


def sha(raw): return hashlib.sha256(raw).hexdigest()
def same(a,b): return ss.encode(a) == ss.encode(b)


def file_pin(path):
    path=ss._safe_path(path,existing=True)
    digest=hashlib.sha256();size=0
    with path.open('rb') as stream:
        while True:
            block=stream.read(1024*1024)
            if not block:break
            digest.update(block);size+=len(block)
    return dict(path=str(path),sha256=digest.hexdigest(),bytes=size)


def frozen_module(path, expected, name):
    require(file_pin(path)['sha256']==expected,'frozen_source_changed')
    name='_resolved_handoff_'+name+'_'+expected[:12]
    if name not in sys.modules:
        spec=importlib.util.spec_from_file_location(name,path)
        module=importlib.util.module_from_spec(spec);sys.modules[name]=module
        spec.loader.exec_module(module)
    return sys.modules[name]


def sources(r4_root=None,r5_root=None):
    parent=Path(__file__).parent.parent
    roots={4:Path(r4_root or parent/'mdc-live-helper-rebuild-20261022-r4'),
           5:Path(r5_root or parent/'mdc-live-helper-rebuild-20261022-r5')}
    pins={}
    for version,expected in ((4,R4_PINS),(5,R5_PINS)):
        for name,digest in expected.items():
            pin=file_pin(roots[version]/name)
            require(pin['sha256']==digest,'frozen_policy_source_changed')
            pins[f'r{version}_{name}']=pin
    p4=frozen_module(roots[4]/'terrain_planner.py',R4_PINS['terrain_planner.py'],'r4_planner').TerrainPlanner
    p5=frozen_module(roots[5]/'terrain_planner.py',R5_PINS['terrain_planner.py'],'r5_planner').TerrainPlanner
    a5=frozen_module(roots[5]/'stride_policy.py',R5_PINS['stride_policy.py'],'r5_stride').arrived
    for name in ('resolved_handoff.py','rebuilt_session.py','terrain_planner.py','stride_policy.py',
                 'live_session_runner.py','fast_pending.py','run_recovery.py','reconcile_original.py'):
        path=Path(__file__).parent/name
        if name=='reconcile_original.py' and not path.exists():continue
        pins['current_'+name]=file_pin(path)
    return p4,p5,a5,pins


def _context(observation, context):
    require(isinstance(observation,dict) and all(
        same(observation.get('bound_owner_id' if k=='owner_id' else k),v) for k,v in context.items()),
        'historical_context_changed')
    require(observation.get('unknown_lock') is False and observation.get('active_id') is None,
            'historical_observation_not_known_idle')


def _events(raw, result_raw, expected_sha, expected_result_sha, phase):
    require(type(raw) is bytes and raw.endswith(b'\n') and sha(raw)==expected_sha
            and sha(result_raw)==expected_result_sha,'pinned_complete_trace_result_required')
    events=[r.strict_json(line) for line in raw.splitlines()]
    allowed=R4_ALLOWED | (MIGRATION_EVENTS if phase==5 else set())
    require(events and all(isinstance(e,dict) and e.get('event') in allowed for e in events)
            and events[-1]['event']=='session_result'
            and sum(e['event']=='session_result' for e in events)==1,'closed_final_trace_required')
    result=r.strict_json(result_raw)
    require(same(result,events[-1].get('result')),'unchanged_original_result_required')
    if phase==4:
        require(events[0]['event']=='session_open' and result.get('state')=='STOPPED'
                and result.get('unknown_lock') is False,'known_r4_stop_required')
    else:
        require(events[0]['event']=='session_restored'
                and result.get('state')=='MAINTENANCE_REQUIRED'
                and result.get('reason')=='original_action_unresolved_no_reissue'
                and result.get('exception_type')=='Maintenance' and result.get('unknown_lock') is True,
                'unchanged_r5_unknown_maintenance_result_required')
    require(result.get('close_required') is True and result.get('historical_prefix_exact') is True
            and isinstance(result.get('unfinished_stage'),dict),'original_unfinished_stage_required')
    return events,result


def _replay(controller,events,result,s,planner,*,phase,resolution,provenance,r5_planner,r5_arrival):
    history=controller.ledger.data;baseline=s.baseline;ctx=s.ctx;serial=s.serial
    finished=list(s.attempted);pending_action=None;pending_decision=None;plan=None
    awaiting_batch=False;seen_version=False;seen_open=False;unknown_seen=0
    migration_open=False;migrated=False;batch_republished=False;allow_token_republish=False
    arrival=original.arrived
    def uses(stage):
        return sum(history['actions'][aid]['request']['stage_id']==stage['id'] for aid in finished) if stage else 0
    def count():return len(baseline['actions'])+len(finished)
    opened=events[0] if phase==4 else None
    for event_index, event in enumerate(events):
        kind = event['event']
        if kind == 'session_restored':
            require(phase == 5 and event_index == 0 and not migration_open
                    and same(event.get('context'), ctx) and event.get('history_count') == count()
                    and event.get('original_batch_deadline') == s.batch['deadline']
                    and event.get('source_trace', {}).get('sha256') == provenance['r4_trace_sha256'],
                    'r5_original_restore_link_mismatch')
            migration_open = True
            s.batch_expired = event.get('batch_expired') is True
        elif kind == 'trace_policy_upgrade_restored':
            require(phase == 5 and migration_open and not migrated
                    and event.get('source_trace_sha256') == provenance['r4_trace_sha256']
                    and event.get('source_result_sha256') == provenance['r4_result_sha256']
                    and event.get('source_version') == R4_VERSION
                    and event.get('preserved_serial') == serial
                    and event.get('original_reserved_count') == len(s.reserved)
                    and event.get('accepted_decisions') == sorted(s.accepted_decisions)
                    and same(event.get('unfinished_stage'), s.stage) and event.get('used') == uses(s.stage)
                    and event.get('policy_upgrade_explicit') is True and event.get('no_action_retried') is True,
                    'r5_policy_upgrade_state_mismatch')
            previous = planner.snapshot()
            planner = r5_planner.restore(previous)
            require(same(previous, planner.snapshot()), 'r5_upgrade_lost_planner_state')
            arrival = r5_arrival
            migrated = True
        elif kind == 'maintenance_batch_restored':
            require(phase == 5 and migrated and not batch_republished
                    and same(event.get('batch'), s.batch) and same(event.get('carried_stage'), s.stage)
                    and event.get('carried_uses') == uses(s.stage) and event.get('history_count') == count(),
                    'r5_restored_original_pool_mismatch')
            batch_republished = True; allow_token_republish = True
        elif kind == 'session_open':
            require(phase == 4 and not seen_open, 'duplicate_session_open'); seen_open = True
        elif kind == 'reconstructed_helper_open':
            require(phase == 4 and not seen_version and event.get('version') == R4_VERSION, 'expected_frozen_r4_version_required')
            seen_version = True; s.recovery_note = event.get('recovery_note')
            require(type(s.recovery_note) is str, 'recovery_note_required')
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
            require((s.batch is None and b['start'] == opened.get('started_at'))
                    or (s.batch is not None and b['start'] >= s.batch['start']), 'batch_time_regression')
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
                require(phase == 5 and q['id'] == resolution['action_id']
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
    require(s.batch is not None and not awaiting_batch and pending_action is None
            and pending_decision is None and s.attempted==finished,'finalized_idle_pairs_required')
    require((phase==4 and seen_open and seen_version and unknown_seen==0)
            or (phase==5 and migration_open and migrated and batch_republished and unknown_seen==1),
            'exact_r4_r5_resolution_transition_required')
    require(s.stage is not None and same(planner._pending,s.stage),'planner_pending_stage_mismatch')
    return s,planner


FINAL_COUNT=1276
RESOLUTION_BASE_KEYS={'schema_version','kind','original_id','original_public_state',
 'original_record_sha256','original_ledger_sha256','independent_status_sha256',
 'fresh_status_sha256','fresh_observation_sha256','source_sha256','original_unknown_reasons',
 'resolved','no_effect_retried','applied_calls','context','stage_id','retained_stage_uses'}
RESOLUTION_RESULT_KEYS=RESOLUTION_BASE_KEYS | {'state','unknown_lock','final_count',
 'after_ledger_sha256','after_record_sha256','evidence_dir','original_request_unchanged',
 'unrelated_1275_records_unchanged'}


def validate_resolution(controller,resolution_raw,expected_resolution_sha256,resolution_path):
    """Verify a single already committed resolution; never perform that write."""
    import base64
    require(type(resolution_raw) is bytes and sha(resolution_raw)==expected_resolution_sha256,
            'resolution_pin_mismatch')
    resolution=r.strict_json(resolution_raw)
    require(set(resolution)==RESOLUTION_RESULT_KEYS and resolution['schema_version']==1
            and resolution['kind']=='explicit_original_zero_input_resolution_v1'
            and resolution['original_id']==ACTION_ID and resolution['original_public_state']=='UNKNOWN'
            and resolution['original_unknown_reasons']==['start_receipt_uncertain']
            and resolution['resolved'] is True and resolution['no_effect_retried'] is True
            and type(resolution['applied_calls']) is int and resolution['applied_calls']==0
            and resolution['state']=='CLOSED' and resolution['unknown_lock'] is False
            and resolution['final_count']==FINAL_COUNT and resolution['retained_stage_uses']==3
            and resolution['original_request_unchanged'] is True
            and resolution['unrelated_1275_records_unchanged'] is True,'exact_resolution_result_required')
    result_pin=file_pin(resolution_path)
    require(result_pin['sha256']==expected_resolution_sha256,'original_resolution_bytes_changed')
    directory=ss._safe_path(resolution['evidence_dir'],existing=False)
    require(directory.is_dir(),'existing_resolution_directory_required')
    require(Path(result_pin['path']).parent==directory,'resolution_evidence_directory_mismatch')
    original_raw=ss._read(directory/'ORIGINAL-ACTION.json')
    require(sha(original_raw)==resolution['original_record_sha256'],'original_record_pin_mismatch')
    old=r.strict_json(original_raw)
    history=r.idle(controller);rec=history['actions'].get(ACTION_ID)
    require(len(history['actions'])==FINAL_COUNT and isinstance(rec,dict)
            and old.get('state')=='UNKNOWN' and old.get('terminal_native') is None
            and old.get('unknown_reasons')==['start_receipt_uncertain'] and old.get('stop_attempted') is True
            and 'resolution' not in old,'original_uncertain_start_required')
    require(sha(r.encode(rec))==resolution['after_record_sha256']
            and same(rec.get('resolution'),{k:resolution[k] for k in RESOLUTION_BASE_KEYS}),
            'resolved_record_pin_mismatch')
    before_pin=file_pin(directory/'BEFORE-LEDGER.json')
    require(before_pin['sha256']==resolution['original_ledger_sha256'],'exact_before_history_pin_required')
    history_pin=file_pin(controller.ledger.path)
    require(history_pin['sha256']==resolution['after_ledger_sha256'],'exact_current_history_pin_required')
    terminal=rec.get('terminal_native');q=rec.get('request')
    require(isinstance(q,dict) and q.get('id')==ACTION_ID
            and q.get('stage_id')==resolution['stage_id']
            and same(resolution['context'],{k:q.get(k) for k in ss.CONTEXT_KEYS}),
            'resolution_original_context_mismatch')
    require(isinstance(terminal,dict) and terminal.get('state')=='SETTLED'
            and terminal.get('protocol_state')=='SETTLED' and terminal.get('protocol_terminal') is True
            and terminal.get('settled') is True and terminal.get('applied_calls')==0
            and terminal.get('effect_state')=='not_started' and terminal.get('input_invalidated') is True
            and terminal.get('release_proven') is True and terminal.get('release_state')=='not_needed'
            and terminal.get('unknown_lock') is False,'exact_released_zero_input_terminal_required')
    controller._validate_receipt(terminal,q)
    proof_pins={}
    for filename,key in (('INDEPENDENT-STATUS.json','independent_status_sha256'),
                         ('FRESH-STATUS.json','fresh_status_sha256'),
                         ('FRESH-OBSERVATION.json','fresh_observation_sha256')):
        raw=ss._read(directory/filename);proof_pins[filename]=file_pin(directory/filename)
        require(sha(raw)==resolution[key],'resolution_fresh_evidence_pin_mismatch')
        parsed=r.strict_json(raw)
        if filename.endswith('STATUS.json'):
            require(same(parsed,terminal),'original_independent_fresh_terminals_conflict')
        else:
            _context(parsed,resolution['context'])
            require(parsed.get('owner_generation')==FINAL_COUNT+1,'resolution_generation_mismatch')
    require(same(old.get('latest_native'),terminal),'retained_original_terminal_changed')
    retained_kinds=[]
    for entry in old.get('evidence',[]):
        if entry.get('kind') in ('stop','status') and entry.get('complete') is True and entry.get('http_status')==200:
            require(same(r.strict_json(base64.b64decode(entry['raw_base64'],validate=True)),terminal),
                    'retained_original_evidence_conflicts')
            retained_kinds.append(entry['kind'])
    require('stop' in retained_kinds and 'status' in retained_kinds
            and any(e.get('kind')=='start' and e.get('complete') is False for e in old.get('evidence',[])),
            'all_original_uncertain_and_terminal_evidence_required')
    expected=dict(old, state='CLOSED', latest_native=terminal,terminal_native=terminal,
        resolution={k:resolution[k] for k in RESOLUTION_BASE_KEYS},
        evidence=old['evidence']+[dict(kind='status',complete=True,http_status=200,
          raw_base64=base64.b64encode(ss._read(directory/'FRESH-STATUS.json')).decode('ascii'))])
    require(same(rec,expected),'only_explicit_original_record_delta_allowed')
    pins=dict(result=result_pin,original_record=file_pin(directory/'ORIGINAL-ACTION.json'),
              before_history=before_pin,**proof_pins)
    return dict(action_id=ACTION_ID,terminal=terminal,proof=resolution),history_pin,pins


def _state(s):
    keys=('serial','ctx','spec','batch','batch_number','stage','stage_number','last_id','finish_called',
          'attempted','completed','consume_state','checkpoint','jump_parent','alignment_parent',
          'decision_serial','decision_token','recovery_note','batch_expired','last_clock')
    data={key:copy.deepcopy(getattr(s,key)) for key in keys}
    data['reserved']=sorted(s.reserved);data['accepted_decisions']=sorted(s.accepted_decisions)
    data['pending']=[];data['planner']=s.planner.snapshot()
    data['stage_uses']=s.stage_uses(s.stage['id']) if s.stage else 0
    return data


def reconstruct(controller, *, r4_trace,r4_result,r4_trace_path,r4_result_path,
                expected_r4_trace_sha256,expected_r4_result_sha256,
                r5_trace,r5_result,r5_trace_path,r5_result_path,
                expected_r5_trace_sha256,expected_r5_result_sha256,
                baseline_path,expected_baseline_sha256,session_spec_raw,expected_session_spec_sha256,
                resolution_raw,resolution_path,expected_resolution_sha256,
                baseline_raw=None,baseline=None,r4_root=None,r5_root=None,monotonic=time.monotonic):
    """Read-only reconstruction. ``baseline`` may be the caller's parsed immutable dict.

    Returns (same_session_object, small_manifest), with no constructor, game
    calls, new IDs, file writes, or whole-history encode/deepcopy. A caller that
    supplies the parsed baseline must have parsed it from its SHA-pinned file.
    """
    e4,result4=_events(r4_trace,r4_result,expected_r4_trace_sha256,expected_r4_result_sha256,4)
    e5,result5=_events(r5_trace,r5_result,expected_r5_trace_sha256,expected_r5_result_sha256,5)
    evidence={}
    for name,path,digest in (('r4_trace',r4_trace_path,expected_r4_trace_sha256),
                            ('r4_result',r4_result_path,expected_r4_result_sha256),
                            ('r5_trace',r5_trace_path,expected_r5_trace_sha256),
                            ('r5_result',r5_result_path,expected_r5_result_sha256)):
        evidence[name]=file_pin(path)
        require(evidence[name]['sha256']==digest,'original_trace_or_result_file_changed')
    spec=original.validate_spec(session_spec_raw,expected_session_spec_sha256)
    base_pin=file_pin(baseline_path)
    require(base_pin['sha256']==expected_baseline_sha256==spec['baseline_sha256'],'original_baseline_pin_required')
    if baseline_raw is not None:
        require(type(baseline_raw) is bytes and sha(baseline_raw)==expected_baseline_sha256,'baseline_raw_pin_mismatch')
    if baseline is None:
        baseline=r.strict_json(baseline_raw if baseline_raw is not None else ss._read(baseline_path))
    require(isinstance(baseline,dict) and len(baseline.get('actions',{}))==spec['baseline_count'],
            'original_baseline_records_required')
    history=r.idle(controller)
    require(controller.owner_id==r.OWNER and all(history['actions'].get(aid)==record
            for aid,record in baseline['actions'].items()),'original_baseline_prefix_changed')
    resolution,history_pin,proof_pins=validate_resolution(controller,resolution_raw,
                                                        expected_resolution_sha256,resolution_path)
    opened=e4[0];serial=opened.get('session_id');ctx=opened.get('context')
    require(r._uuid(serial) and all(e.get('session_id')==serial for e in e4+e5)
            and result4.get('session_id')==serial==result5.get('session_id'),'original_serial_required')
    require(isinstance(ctx,dict) and set(ctx)==ss.CONTEXT_KEYS and ctx['owner_id']==r.OWNER
            and ctx['player_uuid']==r.PLAYER and same(ctx,resolution['proof']['context']),
            'original_same_native_context_required')
    require(same(opened.get('spec'),spec) and opened.get('spec_sha256')==expected_session_spec_sha256,
            'unchanged_original_session_spec_required')
    _context(opened.get('initial_observation'),ctx)
    p4,p5,a5,source_pins=sources(r4_root,r5_root)
    require(source_pins['current_reconcile_original.py']['sha256']==resolution['proof']['source_sha256'],
            'pinned_reconciliation_source_required')
    s=object.__new__(r.RebuiltSession)
    s.c=controller;s.spec=spec;s.baseline=baseline;s.ctx=copy.deepcopy(ctx);s.serial=serial
    s.reserved=set(baseline['actions']);s.batch=None;s.batch_number=0;s.stage=None;s.stage_number=0
    s.last_id=None;s.finish_called=False;s.pending=[];s.attempted=[];s.completed=[]
    s.consume_state=None;s.checkpoint=None;s.jump_parent=None;s.alignment_parent=None
    s.accepted_decisions=set();s.decision_serial=0;s.decision_token=None;s.recovery_note=''
    s.batch_expired=True;s.clock=monotonic;s.last_clock=None;s.timeout=getattr(controller.transport,'scheduling_quantum',getattr(controller.transport,'timeout',None))
    provenance=dict(r4_trace_sha256=expected_r4_trace_sha256,r4_result_sha256=expected_r4_result_sha256,
                    r5_trace_sha256=expected_r5_trace_sha256,r5_result_sha256=expected_r5_result_sha256)
    planner=p4(preferred='west',stop_x=spec['mission']['stop_x'])
    for phase,events,result in ((4,e4,result4),(5,e5,result5)):
        s,planner=_replay(controller,events,result,s,planner,phase=phase,resolution=resolution,
                          provenance=provenance,r5_planner=p5,r5_arrival=a5)
    require(set(history['actions'])==set(baseline['actions'])|set(s.attempted)
            and len(history['actions'])==len(baseline['actions'])+len(s.attempted),
            'all_1276_records_owned_by_original_baseline_or_traces')
    require(s.last_id==ACTION_ID and s.finish_called and s.stage_uses(s.stage['id'])==3
            and s.stage['id']==resolution['proof']['stage_id'] and s.checkpoint is None
            and s.decision_token is None,'resolved_last_attempt_original_stage_budget_required')
    state=planner.snapshot();s.planner=TerrainPlanner.restore(state)
    require(same(state,s.planner.snapshot()),'current_policy_restore_lost_state')
    s.batch_expired=True # No old boot identity was recorded; retain exact pool/deadline until explicit rollover.
    now=monotonic();require(r.finite(now),'valid_restore_clock_required');s.last_clock=now
    manifest=dict(schema_version=1,kind='explicit_resolved_same_session_handoff_v1',
        baseline=dict(**base_pin,count=len(baseline['actions'])),
        history=dict(**history_pin,count=len(history['actions'])),
        evidence=evidence,resolution_evidence=proof_pins,sources=source_pins,
        no_action_retried=True,original_results_unchanged=True,state=_state(s))
    require(file_pin(controller.ledger.path)==history_pin,'history_changed_during_reconstruction')
    return s,manifest


def _write_manifest(path,manifest):
    require(not path.exists(),'new_manifest_required')
    raw=ss.encode(manifest);require(len(raw)<2*1024*1024,'small_reference_manifest_required')
    fd,temp=tempfile.mkstemp(prefix='.handoff-',dir=path.parent)
    try:
        os.fchmod(fd,0o600)
        with os.fdopen(fd,'wb') as stream:stream.write(raw);stream.flush();os.fsync(stream.fileno())
        os.replace(temp,path)
        fd=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY)
        try:os.fsync(fd)
        finally:os.close(fd)
    finally:
        if os.path.exists(temp):os.unlink(temp)
    return file_pin(path)


def restore(controller, *, initial_observation,outdir,confirm_world,sleep=time.sleep,
            stop_requested=lambda:False,on_event=lambda event:None,decision_reader=None,
            session_started_at=None,**kwargs):
    """Restore only to a decision checkpoint; the resolved ID is never reissued."""
    s,manifest=reconstruct(controller,**kwargs)
    output=ss._safe_path(outdir,existing=False)
    require(not output.exists(),'new_evidence_directory_required')
    s.sleep=sleep;s.stop_requested=stop_requested;s.on_event=on_event;s.decision_reader=decision_reader
    s.check_context(initial_observation)
    fresh=r.observe_wait(controller,stop_requested=stop_requested,sleep=sleep);s.now();s.check_context(fresh)
    require(confirm_world(fresh) is True,'explicit_same_world_confirmation_required')
    require(file_pin(controller.ledger.path)=={k:manifest['history'][k] for k in ('path','sha256','bytes')},
            'history_changed_during_world_confirmation')
    # The old maintenance outcome is not rewritten. Establish a new ordinary
    # checkpoint based on the explicitly resolved zero-input terminal.
    s.checkpoint=dict(state='GAMEPLAY_CHECKPOINT',reason='known_zero_or_partial_no_reissue',
                      signature=s.material(fresh))
    token=s._checkpoint_token()
    manifest['state']=_state(s)
    manifest['restore_observation']=copy.deepcopy(fresh)
    output.mkdir(parents=True,mode=0o700);s.out=output;s.trace=output/'trace.jsonl'
    pin=_write_manifest(output/'RESOLVED-HANDOFF-MANIFEST.json',manifest)
    s.emit('resolved_same_session_restored',manifest=pin,context=s.ctx,history_count=len(s.c.ledger.data['actions']),
        resolved_original_id=ACTION_ID,original_public_state='UNKNOWN',current_public_state='CLOSED',
        preserved_serial=s.serial,original_batch_deadline=s.batch['deadline'],batch_expired=True,
        unfinished_stage=s.stage,used=s.stage_uses(s.stage['id']),no_action_retried=True)
    s.emit('maintenance_batch_restored',batch=s.batch,carried_stage=s.stage,
           carried_uses=s.stage_uses(s.stage['id']),history_count=len(s.c.ledger.data['actions']))
    s.emit('gameplay_checkpoint',state=s.checkpoint['state'],reason=s.checkpoint['reason'],
        close_required=False,observation=fresh,unfinished_stage=s.stage,used=s.stage_uses(s.stage['id']))
    s.emit('decision_available',checkpoint=s.checkpoint,decision=token,jump_parent=None,alignment_parent=None)
    return s
