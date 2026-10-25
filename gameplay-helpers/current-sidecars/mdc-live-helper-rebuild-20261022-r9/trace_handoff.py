"""Narrow, explicit r4 STOPPED -> r5 same-Session policy-upgrade handoff.

NOT crash recovery. An unfinished/live trace, unknown action, missing receipt,
unpaired decision, jump, survival action, manual target, hidden failed proposal,
or untraced cursor consumption is refused. Historical planner decisions replay
only through the SHA-pinned *r4* planner. No transport action/finish is called.
The old game, controller ledger, r4 source and evidence are never written.
"""
import copy
import hashlib
import importlib.util
import sys
import time
from pathlib import Path

import rebuilt_session as r
import live_session_runner as original
import session_state as ss
from terrain_planner import TerrainPlanner


R4_VERSION = 'rebuild-20261022-r4-prepared-history'
R4_PINS = {
    'rebuilt_session.py': '59cb7ea844a944fa5af7526726c444c33a977979f285f620bb8bd57c6103c3fd',
    'live_session_runner.py': '63e937d75bc0d8185a52c0cb84d7586c868f957ce34af0ab17d9dda2eacea4ce',
    'terrain_planner.py': '5acec32bc8a59dce94202c539c1f447753123b25e93fd06b77be132cb8c23d58',
}
ALLOWED = {'session_open', 'batch_open', 'reconstructed_helper_open',
           'navigation_target', 'plan_bound', 'observation', 'pre_start',
           'action_finished', 'stage_arrived', 'observation_wait',
           'gameplay_checkpoint', 'decision_available', 'decision_accepted',
           'decision_applied', 'batch_checkpoint', 'session_result'}


def require(condition, reason):
    if not condition:
        raise r.Maintenance('trace_handoff_' + reason)


def same(left, right):
    return ss.encode(left) == ss.encode(right)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def frozen_sources(source_root=None):
    root = Path(source_root or Path(__file__).parent.parent / 'mdc-live-helper-rebuild-20261022-r4')
    sources = {}
    for name, digest in R4_PINS.items():
        path = ss._safe_path(root / name, existing=True)
        require(sha(path.read_bytes()) == digest, 'frozen_r4_source_changed_' + name)
        sources['frozen_r4_' + name] = path
    path = sources['frozen_r4_terrain_planner.py']
    name = '_mdc_frozen_r4_terrain_' + R4_PINS['terrain_planner.py'][:12]
    module = sys.modules.get(name)
    if module is None:
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    sources['trace_handoff'] = __file__
    for dependency in ('stride_policy.py', 'fast_pending.py', 'run_recovery.py'):
        sources['r5_' + dependency] = ss._safe_path(Path(__file__).parent / dependency, existing=True)
    return module.TerrainPlanner, sources


def _context(observation, context):
    require(isinstance(observation, dict), 'observation_required')
    require(all(same(observation.get('bound_owner_id' if key == 'owner_id' else key), value)
                for key, value in context.items()), 'historical_context_changed')
    require(observation.get('unknown_lock') is False and observation.get('active_id') is None,
            'historical_observation_not_known_idle')


def reconstruct_snapshot(controller, *, old_trace, old_result, old_trace_path,
                         expected_trace_sha256, baseline_raw,
                         expected_baseline_sha256, session_spec_raw,
                         expected_session_spec_sha256, source_boot_id=None,
                         source_root=None, monotonic=time.monotonic):
    """Replay only finalized evidence into the existing session_state schema.

    Pure with respect to files/game/history: this does not persist a snapshot or
    fetch an observation. The exact old trace must still exist at its pinned
    path. ``source_boot_id`` is an explicit operator assertion about the old
    process boot, not a value inferred from an unrecorded trace field.
    """
    require(type(old_trace) is bytes and old_trace.endswith(b'\n')
            and sha(old_trace) == expected_trace_sha256, 'pinned_complete_trace_required')
    path = ss._safe_path(old_trace_path, existing=True)
    require(path.read_bytes() == old_trace, 'original_trace_bytes_changed')
    events = [r.strict_json(line) for line in old_trace.splitlines()]
    require(len(events) >= 4 and all(isinstance(e, dict) and e.get('event') in ALLOWED for e in events),
            'unsupported_or_incomplete_trace_shape')
    require(events[0]['event'] == 'session_open' and events[-1]['event'] == 'session_result'
            and sum(e['event'] == 'session_result' for e in events) == 1,
            'finalized_trace_required_no_live_snapshot')
    result = r.strict_json(old_result)
    require(same(result, events[-1].get('result')), 'terminal_result_mismatch')
    require(result.get('state') == 'STOPPED' and result.get('close_required') is True
            and result.get('reason') in {'explicit_stop_requested', 'explicit_stop_during_read_wait'}
            and result.get('unknown_lock') is False and result.get('historical_prefix_exact') is True,
            'explicit_known_stop_required')
    # r4 does not emit a failed choose() attempt. A null final stage could hide
    # an incremented stage counter/planner mutation if STOP arrived during the
    # subsequent checkpoint read. Do not infer that missing state.
    require(isinstance(result.get('unfinished_stage'), dict),
            'unfinished_ordinary_stage_required_no_hidden_choose_state')
    opened = events[0]
    serial = opened.get('session_id')
    require(r._uuid(serial) and all(e.get('session_id') == serial for e in events)
            and result.get('session_id') == serial, 'original_serial_required')
    spec = original.validate_spec(session_spec_raw, expected_session_spec_sha256)
    require(same(opened.get('spec'), spec) and opened.get('spec_sha256') == expected_session_spec_sha256,
            'original_spec_required')
    require(sha(baseline_raw) == expected_baseline_sha256 == spec['baseline_sha256'], 'baseline_pin_mismatch')
    baseline = r.strict_json(baseline_raw)
    history = r.idle(controller)
    require(controller.owner_id == r.OWNER and len(baseline['actions']) == spec['baseline_count'],
            'original_owner_and_baseline_count_required')
    require(all(history['actions'].get(aid) == rec for aid, rec in baseline['actions'].items()),
            'historical_baseline_changed')
    history_path = getattr(controller.ledger, 'path', None)
    require(history_path is not None, 'persisted_current_ledger_required')
    history_raw = ss._read(history_path)
    require(same(r.strict_json(history_raw), history), 'current_disk_history_mismatch')
    ctx = opened.get('context')
    require(isinstance(ctx, dict) and set(ctx) == ss.CONTEXT_KEYS
            and ctx['owner_id'] == r.OWNER and ctx['player_uuid'] == r.PLAYER, 'original_context_required')
    _context(opened.get('initial_observation'), ctx)
    old_planner_class, sources = frozen_sources(source_root)
    planner = old_planner_class(preferred='west', stop_x=spec['mission']['stop_x'])
    s = object.__new__(r.RebuiltSession)
    s.c = controller; s.spec = copy.deepcopy(spec); s.baseline = copy.deepcopy(baseline)
    s.ctx = copy.deepcopy(ctx); s.serial = serial; s.reserved = set(baseline['actions'])
    s.batch = None; s.batch_number = 0; s.stage = None; s.stage_number = 0
    s.last_id = None; s.finish_called = False; s.pending = []; s.attempted = []; s.completed = []
    s.consume_state = None; s.checkpoint = None; s.jump_parent = None; s.alignment_parent = None
    s.accepted_decisions = set(); s.decision_serial = 0; s.decision_token = None
    s.recovery_note = ''; s.batch_expired = source_boot_id is None
    s.clock = monotonic; s.last_clock = None; s.timeout = getattr(controller.transport, 'scheduling_quantum', getattr(controller.transport, 'timeout', None))
    s.trace = path; s.out = path.parent
    finished = []; pending_action = None; pending_decision = None; plan = None
    awaiting_batch = False; seen_version = False; seen_open = False

    def uses(stage):
        return sum(history['actions'][aid]['request']['stage_id'] == stage['id'] for aid in finished) if stage else 0

    def count():
        return len(baseline['actions']) + len(finished)

    for event in events:
        kind = event['event']
        if kind == 'session_open':
            require(not seen_open, 'duplicate_session_open'); seen_open = True
        elif kind == 'reconstructed_helper_open':
            require(not seen_version and event.get('version') == R4_VERSION, 'expected_frozen_r4_version_required')
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
                    and same(event.get('request'), q) and event.get('public_state') == 'CLOSED',
                    'missing_original_action_pair')
            rec = history['actions'].get(q['id']); term = event.get('terminal')
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
            require(original.arrived(event['observation'], s.stage), 'actual_r4_arrival_not_established')
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
    require(seen_version and s.batch is not None and not awaiting_batch
            and pending_action is None and pending_decision is None and s.attempted == finished,
            'finalized_idle_pairs_required')
    require(set(history['actions']) == set(baseline['actions']) | set(finished), 'untraced_current_history_forbidden')
    require(s.stage is None or same(planner._pending, s.stage), 'planner_pending_stage_mismatch')
    now = monotonic()
    require(r.finite(now) and now >= s.batch['start'], 'same_monotonic_domain_required')
    old_planner_state = planner.snapshot()
    s.planner = TerrainPlanner.restore(copy.deepcopy(old_planner_state))
    require(same(s.planner.snapshot(), old_planner_state), 'upgraded_planner_must_preserve_old_state')
    snap = ss.snapshot_session(s, history_raw=history_raw, baseline_raw=baseline_raw,
                               session_spec_raw=session_spec_raw, source_paths=sources,
                               boot_id=source_boot_id or ss.current_boot_id())
    # Unknown old boot never inherits a usable monotonic lease. Old deadline and
    # pools remain exact; only the runner's explicit rollover may replace them.
    return snap


def restore(controller, *, old_trace, old_result, old_trace_path, expected_trace_sha256,
            initial_observation, baseline_raw, expected_baseline_sha256,
            session_spec_raw, expected_session_spec_sha256, outdir, confirm_world,
            session_started_at=None, stop_requested=lambda: False, on_event=lambda e: None,
            monotonic=time.monotonic, sleep=time.sleep, decision_reader=lambda checkpoint: None,
            source_boot_id=None, source_root=None):
    """Prepare same Session in NEW evidence directory, with no action or retry."""
    snap = reconstruct_snapshot(controller, old_trace=old_trace, old_result=old_result,
        old_trace_path=old_trace_path, expected_trace_sha256=expected_trace_sha256,
        baseline_raw=baseline_raw, expected_baseline_sha256=expected_baseline_sha256,
        session_spec_raw=session_spec_raw, expected_session_spec_sha256=expected_session_spec_sha256,
        source_boot_id=source_boot_id, source_root=source_root, monotonic=monotonic)
    _context(initial_observation, snap['state']['ctx'])
    require(callable(confirm_world) and confirm_world(copy.deepcopy(initial_observation)) is True,
            'same_live_world_confirmation_required')
    s = ss.restore_session(r.RebuiltSession, snap, controller=controller,
        history_raw=ss._read(controller.ledger.path), expected_context=snap['state']['ctx'],
        outdir=outdir, planner_restore=TerrainPlanner.restore, monotonic=monotonic,
        sleep=sleep, stop_requested=stop_requested, on_event=on_event, decision_reader=decision_reader,
        boot_id=ss.current_boot_id(), initial_observation=initial_observation)
    snapshot_pin = ss.save_snapshot(s.out / 'TRACE-HANDOFF-SNAPSHOT.json', snap)
    s.emit('trace_policy_upgrade_restored', source_version=R4_VERSION,
           source_trace_sha256=sha(old_trace), source_result_sha256=sha(old_result),
           reconstructed_snapshot=snapshot_pin, preserved_serial=s.serial,
           unfinished_stage=s.stage, used=s.stage_uses(s.stage['id']) if s.stage else 0,
           original_reserved_count=len(s.reserved), accepted_decisions=sorted(s.accepted_decisions),
           policy_upgrade_explicit=True, no_action_retried=True)
    # Seed the strict CLI transport allowlist; retained used IDs remain protected
    # by the exact cursor and CLOSED ledger, never allocated a second time.
    s.emit('maintenance_batch_restored', batch=s.batch, carried_stage=s.stage,
           carried_uses=s.stage_uses(s.stage['id']) if s.stage else 0,
           history_count=len(controller.ledger.data['actions']))
    if s.decision_token is not None:
        s.emit('decision_available', checkpoint=s.checkpoint, decision=s.decision_token,
               jump_parent=None, alignment_parent=None)
    return s


def resume(controller, **kwargs):
    trace_keys = ('old_trace','old_result','old_trace_path','expected_trace_sha256','source_boot_id','source_root')
    trace = {key: kwargs.pop(key) for key in trace_keys if key in kwargs}
    return r.run(controller, session_factory=lambda c, **kw: restore(c, **trace, **kw), **kwargs)
