"""Narrow repair of the proven r2 zero-attempt observation-failure Session.

Not generic crash recovery. No constructor/new serial/new batch/ID allocation.
Original full source trace is externally SHA-pinned by the CLI. Every other
history/action/trace shape refuses; unknown effects are never inferred/retried.
"""
import copy,hashlib,math,time
from pathlib import Path
import rebuilt_session as r
from live_session_runner import validate_spec
from terrain_planner import TerrainPlanner

def restore(controller,*,old_trace,old_result,initial_observation,baseline_raw,
            expected_baseline_sha256,session_spec_raw,expected_session_spec_sha256,
            outdir,confirm_world,session_started_at,stop_requested=lambda:False,
            on_event=lambda e:None,monotonic=time.monotonic,sleep=time.sleep,
            decision_reader=lambda c:None):
    def require(value,reason):
        if not value:raise r.Maintenance('zero_attempt_handoff_'+reason)
    events=[r.strict_json(line) for line in old_trace.splitlines()]
    require([e.get('event') for e in events]==['session_open','batch_open','reconstructed_helper_open','session_result'],'exact_four_event_history_required')
    opened,batch_event,version,ended=events
    result=r.strict_json(old_result);spec=validate_spec(session_spec_raw,expected_session_spec_sha256)
    require(result==ended.get('result'),'terminal_evidence_mismatch')
    serial=opened.get('session_id')
    require(r._uuid(serial) and all(e.get('session_id')==serial for e in events) and result.get('session_id')==serial,'serial_mismatch')
    require(version.get('version')=='rebuild-20261022-r2-startup-wait','expected_r2_source_required')
    require(result.get('state')=='MAINTENANCE_REQUIRED' and result.get('reason')=='observation unavailable' and result.get('exception_type')=='Refused' and result.get('close_required') is True,'expected_known_observation_terminal_required')
    require(result.get('attempted_ids')==[] and result.get('completed_stages')==[] and result.get('unfinished_stage') is None and result.get('unfinished_uses')==0 and result.get('batches')==1,'zero_attempt_no_stage_required')
    require(result.get('historical_prefix_exact') is True and result.get('unknown_lock') is False,'known_original_history_required')
    baseline=r.strict_json(baseline_raw)
    require(hashlib.sha256(baseline_raw).hexdigest()==expected_baseline_sha256==spec['baseline_sha256'],'baseline_pin_mismatch')
    require(r.idle(controller)==baseline and controller.owner_id==r.OWNER and len(baseline['actions'])==result.get('final_count')==spec['baseline_count'],'current_history_not_identical')
    require(opened.get('spec')==spec and opened.get('spec_sha256')==expected_session_spec_sha256,'original_spec_mismatch')
    ctx=opened.get('context')
    require(isinstance(ctx,dict) and set(ctx)=={'session','world_generation','player_uuid','owner_id'} and ctx['owner_id']==r.OWNER and ctx['player_uuid']==r.PLAYER,'original_context_required')
    require(all(initial_observation.get('bound_owner_id' if k=='owner_id' else k)==v for k,v in ctx.items()),'actual_context_changed')
    require(confirm_world(initial_observation) is True,'actual_identity_not_confirmed')
    batch=batch_event.get('batch')
    require(isinstance(batch,dict) and set(batch)=={'id','start','deadline','ids','cursor','new_stages'},'closed_original_batch_required')
    require(batch['id']==serial+':b1' and batch['cursor']==0 and batch['new_stages']==0,'unused_original_batch_required')
    require(r.finite(batch['start']) and r.finite(batch['deadline']) and batch['deadline']==batch['start']+300 and opened.get('started_at')==batch['start'],'original_deadline_required')
    require(isinstance(batch['ids'],list) and len(batch['ids'])==min(128,4096-len(baseline['actions'])) and len(set(batch['ids']))==len(batch['ids']) and all(r._uuid(i) and i not in baseline['actions'] for i in batch['ids']),'original_reserved_ids_required')
    require(batch_event.get('carried_stage') is None and batch_event.get('carried_uses')==0 and batch_event.get('history_count')==len(baseline['actions']),'original_batch_history_mismatch')
    now=monotonic();require(r.finite(now) and now>=batch['start'],'same_monotonic_domain_required')
    timeout=getattr(controller.transport,'scheduling_quantum',getattr(controller.transport,'timeout',None));require(r.finite(timeout) and .05<=timeout<=.5,'unchanged_action_transport_required')
    out=Path(outdir);require(not out.exists() and not any(p.is_symlink() for p in (out,*out.parents)),'new_evidence_path_required')
    # All evidence/context/admission validation precedes mutation or file creation.
    s=object.__new__(r.RebuiltSession)
    s.c=controller;s.clock=monotonic;s.sleep=sleep;s.last_clock=now;s.stop_requested=stop_requested;s.on_event=on_event
    s.spec=copy.deepcopy(spec);s.baseline=copy.deepcopy(baseline);s.timeout=timeout;s.ctx=copy.deepcopy(ctx)
    s.serial=serial;s.reserved=set(baseline['actions'])|set(batch['ids']);s.batch=copy.deepcopy(batch);s.stage=None;s.stage_number=0
    s.last_id=None;s.finish_called=False;s.pending=[];s.attempted=[];s.completed=[];s.batch_number=1;s.consume_state=None;s.checkpoint=None
    s.decision_reader=decision_reader;s.accepted_decisions=set();s.decision_serial=0;s.decision_token=None;s.jump_parent=None;s.alignment_parent=None;s.batch_expired=False
    s.recovery_note='same r2 Session maintenance handoff; original serial/batch/deadline/IDs retained, zero attempted effects proven'
    s.planner=TerrainPlanner(preferred='west',stop_x=spec['mission']['stop_x']);s.check_context(initial_observation)
    s.out=out;s.out.mkdir(parents=True,mode=0o700);s.trace=out/'trace.jsonl';s.trace.touch(mode=0o600)
    s.emit('zero_attempt_maintenance_restored',source_trace_sha256=hashlib.sha256(old_trace).hexdigest(),source_result_sha256=hashlib.sha256(old_result).hexdigest(),original_context=ctx,original_started_at=batch['start'],history_count=len(baseline['actions']),initial_observation=initial_observation)
    s.emit('maintenance_batch_restored',batch=s.batch,carried_stage=None,carried_uses=0,history_count=len(baseline['actions']))
    return s

def resume(controller,*,old_trace,old_result,**kwargs):
    def factory(c,**kw):return restore(c,old_trace=old_trace,old_result=old_result,**kw)
    return r.run(controller,session_factory=factory,**kwargs)
