"""REBUILT after environment loss. Sidecar only; imports unchanged C8/r1.

No action can be reissued after UNKNOWN. Ordinary checkpoints keep the same
Session and game. Decisions are one-use, context/history-bound local proposals.
This is not the lost H3 byte-for-byte artifact and never adopts its action IDs.
"""
import copy
import hashlib
import math
import time
import uuid

from live_session_runner import (
    Session, Maintenance, Gameplay, Rollover, idle, finite, actual_geometry,
    redirected, arrived, grounded, OWNER, PLAYER, PROFILE, encode, strict_json, gate, Refused,
)
from terrain_planner import TerrainPlanner, manual_target
from stride_policy import redirected, arrived
from edge_support import actual_geometry, gate, GEOMETRY_REFUSALS, inward_target

COMMAND_KEYS = {'schema_version','decision_id','token','session_id','context',
                'history_count','kind','args'}
KINDS = {'continue_local','local_target','align_jump','abandon_jump'}


class InitializationWait(Exception):
    """Transient read-only pre-session confirmation, never an action result."""


class ObservationCancelled(Gameplay):
    pass


def observe_wait(controller, *, stop_requested=lambda:False,
                 on_wait=lambda o:None, sleep=time.sleep):
    """Repeat only a read while all original actions are CLOSED; never POST."""
    while True:
        if stop_requested():raise ObservationCancelled('explicit_stop_during_read_wait')
        idle(controller)
        try:return controller.observe()
        except Refused as e:
            if str(e)!='observation unavailable':raise
            on_wait({'ready':False,'reason':'observation_unavailable_read_only'})
            sleep(.25)


def _uuid(value):
    try:
        return isinstance(value,str) and str(uuid.UUID(value)) == value
    except (ValueError,TypeError,AttributeError):
        return False


def wait_ready(controller, *, player_uuid, stop_requested=lambda:False,
               on_wait=lambda o:None, sleep=time.sleep):
    """Observe only through loading/UI. Never press resume or adopt a user pause.

    There is no hidden session deadline here: no Session, batch or IDs exist yet.
    The caller can cancel waiting with stop_requested. Unexpected authority is a
    maintenance error rather than a retry. A UI/dead state is only reported.
    """
    while True:
        if stop_requested():
            raise Gameplay('initialization_cancelled_before_session')
        o=observe_wait(controller,stop_requested=stop_requested,on_wait=on_wait,sleep=sleep)
        if o.get('profile')!=PROFILE or o.get('bound_owner_id')!=OWNER or o.get('unknown_lock') is not False or o.get('active_id') is not None:
            raise Maintenance('initialization_authority_or_action_state_unavailable')
        if o.get('owner_generation')!=len(controller.ledger.data['actions'])+1:
            raise Maintenance('initialization_owner_generation_mismatch')
        if o.get('player_uuid') is not None and o.get('player_uuid')!=player_uuid:
            raise Maintenance('initialization_player_mismatch')
        if (o.get('session') is not None and o.get('world_generation') is not None
                and o.get('player_uuid')==player_uuid and o.get('alive') is True
                and o.get('ready') is True and o.get('paused') is False
                and o.get('screen_open') is False):
            return o
        on_wait(copy.deepcopy(o));sleep(.25)


class RebuiltSession(Session):
    def __init__(self, controller, *, decision_reader=lambda checkpoint:None,
                 recovery_note='new RECOVERY run from verified F1220; lost later history is not retried', **kwargs):
        self.decision_reader=decision_reader
        self.accepted_decisions=set();self.decision_serial=0;self.decision_token=None
        self.jump_parent=None;self.alignment_parent=None;self.batch_expired=False
        self.recovery_note=recovery_note
        super().__init__(controller,**kwargs)
        self.planner=TerrainPlanner(preferred='west',stop_x=self.spec['mission']['stop_x'])
        self.emit('reconstructed_helper_open',version='rebuild-20261022-r5-flat-stride',recovery_note=recovery_note)

    def _observe_wait(self):
        last=[-float('inf')]
        def waiting(o):
            now=self.now()
            if now-last[0]>=1.:
                last[0]=now
                self.emit('observation_wait',reason=o['reason'],close_required=False,
                          unfinished_stage=self.stage,
                          used=self.stage_uses(self.stage['id']) if self.stage else 0)
        return observe_wait(self.c,stop_requested=self.stop_requested,on_wait=waiting,sleep=self.sleep)

    def fresh(self):
        o=self._observe_wait();self.now();self.check_context(o)
        self.pending.append(('observation',dict(observation=o)))
        return o

    def stable(self):
        # HTTP/parse availability is not a physical settling failure. Preserve
        # the original two grounded increasing-tick samples and exclude idle
        # read time; missing data alone is not evidence of physical instability.
        deadline=self.now()+2.;previous=None
        while deadline-self.now()>=self.timeout:
            started=self.now()
            o=self.fresh();deadline+=self.now()-started
            tick=o.get('client_tick')
            if type(tick) is not int or tick<0:raise Maintenance('invalid_tick')
            if grounded(o):
                if previous is not None and tick>previous:return o
                if previous is not None and tick<previous:raise Maintenance('tick_regressed')
                previous=tick if previous is None else previous
            else:previous=None
            if deadline-self.now()<self.timeout+.05:break
            self.sleep(.05)
        raise Gameplay('physical_motion_not_yet_stable')

    def checkpoint_observe(self):
        o=self._observe_wait();self.now()
        if o.get('profile')!=PROFILE or o.get('bound_owner_id')!=OWNER or o.get('unknown_lock') is not False or o.get('active_id') is not None:
            raise Maintenance('checkpoint_authority_or_action_state_unavailable')
        if o.get('owner_generation')!=len(self.c.ledger.data['actions'])+1:
            raise Maintenance('checkpoint_owner_generation_mismatch')
        return o

    def step(self):
        # Same r1 state machine, with explicit cancellation of an idle read wait.
        try:
            if self.stop_requested() is True:return self.result('STOPPED','explicit_stop_requested',True)
            if self.checkpoint is not None:return self.poll_checkpoint()
            try:outcome=self.advance()
            except Rollover:return None
            except ObservationCancelled:raise
            except Refused as e:
                # Known idle local geometry is a game decision, not a broken driver.
                if str(e) not in GEOMETRY_REFUSALS:raise
                idle(self.c)
                if self.last_id is not None and (self.last_id not in self.c.ledger.data['actions'] or not self.finish_called):raise
                return self.enter_checkpoint('GAMEPLAY_BLOCKED','local_geometry_no_post: '+str(e))
            except Gameplay as e:return self.enter_checkpoint('GAMEPLAY_CHECKPOINT',str(e))
            if outcome is None:return None
            if outcome['close_required']:return self.result(**outcome)
            return self.enter_checkpoint(outcome['state'],outcome['reason'])
        except ObservationCancelled:
            return self.result('STOPPED','explicit_stop_during_read_wait',True)
        except BaseException as e:
            return self.result('MAINTENANCE_REQUIRED',str(e)[:180],True,exception_type=type(e).__name__[:64])

    def bind(self,nav=None,survival=None):
        plan=super().bind(nav=nav,survival=survival)
        prepared=getattr(self.c,'_prepared_history',None)
        if prepared is not None:prepared.prepare()
        # Every original effect path fetches fresh again after bind. Historical
        # serialization is therefore outside the native observation lease.
        return plan

    def ensure_batch(self,new_stage=False):
        if self.batch_expired:
            idle(self.c);o=self.fresh();self.flush()
            self.emit('batch_checkpoint',batch_id=self.batch['id'],original_deadline=self.batch['deadline'],
                      reason='monotonic_boot_changed_explicit_rollover',unfinished_stage=self.stage,
                      used=self.stage_uses(self.stage['id']) if self.stage else 0)
            self.open_batch(self.now(),o);self.batch_expired=False
        return super().ensure_batch(new_stage)

    def _planner_finished(self, stage, actual_arrival):
        # Explicit local targets may not belong to the planner's pending edge.
        pending=getattr(self.planner,'_pending',None)
        if pending == stage:
            (self.planner.arrived if actual_arrival else self.planner.blocked)(stage)

    def _checkpoint_token(self):
        self.decision_serial+=1
        self.decision_token=dict(token=str(uuid.uuid4()),session_id=self.serial,
            context=copy.deepcopy(self.ctx),history_count=len(idle(self.c)['actions']),
            decision_serial=self.decision_serial)
        return copy.deepcopy(self.decision_token)

    def enter_checkpoint(self,state,reason):
        result=super().enter_checkpoint(state,reason)
        self.emit('decision_available',checkpoint=self.checkpoint,decision=self._checkpoint_token(),
                  jump_parent=self.jump_parent,alignment_parent=self.alignment_parent)
        return result

    def decision_snapshot(self):
        if self.checkpoint is None:return None
        return dict(**copy.deepcopy(self.decision_token),state=self.checkpoint['state'],
                    reason=self.checkpoint['reason'],stage=copy.deepcopy(self.stage),
                    stage_uses=self.stage_uses(self.stage['id']) if self.stage else 0,
                    jump_parent=copy.deepcopy(self.jump_parent),
                    alignment_parent=copy.deepcopy(self.alignment_parent))

    def _peek_stage_id(self,kind):
        return f'ls.{self.serial.replace(chr(45),chr(95))}.{kind}.{self.stage_number+1}'

    def _proposal(self, command, o):
        if not isinstance(command,dict) or set(command)!=COMMAND_KEYS or type(command['schema_version']) is not int or command['schema_version']!=1:
            raise Refused('closed decision command required')
        if not _uuid(command['decision_id']) or command['decision_id'] in self.accepted_decisions:
            raise Refused('new decision UUID required')
        d=self.decision_token
        if d is None or any(command[k]!=d[k] for k in ('token','session_id','context','history_count')):
            raise Refused('current checkpoint token context and history required')
        if command['history_count']!=len(idle(self.c)['actions']):
            raise Refused('decision history changed')
        kind,args=command['kind'],command['args']
        if not isinstance(kind,str) or kind not in KINDS or not isinstance(args,dict):raise Refused('closed supported decision kind required')
        if kind in ('continue_local','abandon_jump'):
            if args:raise Refused('decision has no arguments')
            if kind=='continue_local' and self.jump_parent is not None:raise Refused('unresolved jump requires explicit landing decision')
            if kind=='abandon_jump':
                if self.jump_parent is None:raise Refused('no jump landing to accept')
                actual_geometry(o)
            return dict(kind=kind)
        if kind=='local_target':
            if self.stage is not None or self.jump_parent is not None or self.alignment_parent is not None:
                raise Refused('unfinished stage must retain its target and budget')
            if set(args)!={'target','jump'} or type(args['jump']) is not bool:raise Refused('closed target/jump arguments required')
            sid=self._peek_stage_id('nav')
            stage=manual_target(o,sid,args['target'],jump=args['jump'],max_moves=1 if args['jump'] else 8)
            return dict(kind=kind,stage=stage)
        if set(args)!=set():raise Refused('alignment takes original jump target only')
        if self.jump_parent is None or self.stage is not None:raise Refused('unresolved known jump parent required')
        parent=self.jump_parent;target=parent['stage']['target'];actual_geometry(o)
        if abs(o['pose']['y']-target['y'])>.05:raise Refused('ordinary alignment requires actual target height')
        remaining=8-parent['used']
        if not 1<=remaining<=7:raise Refused('parent jump budget leaves no ordinary alignment')
        sid=self._peek_stage_id('align')
        stage=manual_target(o,sid,target,jump=False,max_moves=remaining)
        return dict(kind=kind,stage=stage,parent=copy.deepcopy(parent))

    def accept_decision(self, command):
        """Validate without mutation; persist one acceptance before applying it.

        The decision reader must not retry an uncertain delivery. This object
        rejects accepted UUIDs/tokens; the acceptance trace is persisted before
        stage/budget mutation so a crash cannot authorize a silent replay.
        """
        if self.checkpoint is None:raise Refused('decision only at live checkpoint')
        o=self.checkpoint_observe();self.check_context(o);actual_geometry(o)
        proposal=self._proposal(command,o)  # No state/budget/parent mutation.
        if proposal['kind'] in ('local_target','align_jump'):
            # Prepare any fallible rollover/context reads before consuming the
            # decision. Revalidate its pure proposal after those observations.
            self.ensure_batch(new_stage=True)
            o=self.checkpoint_observe();self.check_context(o);actual_geometry(o)
            proposal=self._proposal(command,o)
        self.flush();self.emit('decision_accepted',command=command,proposal=proposal,observation=o)
        self.accepted_decisions.add(command['decision_id']);self.decision_token=None
        kind=proposal['kind']
        if kind in ('local_target','align_jump'):
            # Admission preparation above reserved finite batch room; no I/O or
            # fallible fresh read may interleave accepted -> applied mutation.
            self.stage_number+=1;self.batch['new_stages']+=1
            self.stage=copy.deepcopy(proposal['stage'])
            if kind=='align_jump':self.alignment_parent=proposal['parent'];self.jump_parent=None
            self.emit('navigation_target',stage=self.stage,observation=o,source='explicit_decision',
                      parent_jump=self.alignment_parent)
        elif kind=='abandon_jump':
            self.emit('jump_landing_accepted',parent=self.jump_parent,observation=o,arrival_claimed=False)
            self.jump_parent=None
        # continue_local preserves every existing stage and its spent budget.
        self.checkpoint=None
        self.emit('decision_applied',decision_id=command['decision_id'],kind=kind,stage=self.stage)
        return True

    def poll_checkpoint(self):
        if self.checkpoint is None:return None
        self.sleep(.25);o=self.checkpoint_observe()
        command=self.decision_reader(self.decision_snapshot())
        if command is not None:
            try:self.accept_decision(command)
            except (Refused,Gameplay) as e:self.emit('decision_rejected_no_effect',decision_id=command.get('decision_id') if isinstance(command,dict) else None,reason=str(e))
            return None
        # A route/landing choice stays an explicit checkpoint, not an automatic
        # second jump caused by an unrelated health, yaw or inventory change.
        automatic_reasons={'not_grounded_slow','physical_motion_not_yet_stable',
            'settle_read_window_exceeded','ordinary_ui_or_pause_active',
            'native_context_temporarily_not_ready','temporary_nearby_admission_block_same_stage'}
        if self.checkpoint['reason'] not in automatic_reasons:return None
        signature=self.material(o)
        if signature==self.checkpoint['signature']:return None
        self.checkpoint['signature']=signature
        try:self.check_context(o)
        except Gameplay:return None
        self.emit('gameplay_resume',reason='actual_material_facts_changed',observation=o,
                  unfinished_stage=self.stage,used=self.stage_uses(self.stage['id']) if self.stage else 0)
        self.checkpoint=None;self.decision_token=None
        return None

    def advance(self):
        if self.stop_requested():return dict(state='STOPPED',reason='explicit_stop_requested',close_required=True)
        self.ensure_batch();o=self.fresh()
        if self.survival(o):return None
        o=self.stable();actual_geometry(o)
        if self.stage is not None and arrived(o,self.stage):
            self._planner_finished(self.stage,True);self.completed.append(self.stage['id'])
            self.emit('stage_arrived',stage=self.stage,observation=o,parent_jump=self.alignment_parent)
            self.stage=None;self.alignment_parent=None
        if self.stage is not None:
            used=self.stage_uses(self.stage['id'])
            if self.stage['jump_first'] and used>=1:
                self.jump_parent=dict(stage=copy.deepcopy(self.stage),used=used)
                self._planner_finished(self.stage,False);self.stage=None
                return dict(state='GAMEPLAY_CHECKPOINT',reason='known_jump_landing_decision',close_required=False)
            if used>=self.stage['max_moves']:
                self.emit('stage_exhausted_known',stage=self.stage,used=used,parent_jump=self.alignment_parent)
                self._planner_finished(self.stage,False);self.stage=None;self.alignment_parent=None
                return dict(state='GAMEPLAY_BLOCKED',reason='stage_budget_exhausted',close_required=False)
        if self.stage is None:
            if self.jump_parent is not None:return dict(state='GAMEPLAY_CHECKPOINT',reason='known_jump_landing_decision',close_required=False)
            if o['pose']['x']<=self.spec['mission']['stop_x']+.1:
                return dict(state='GOAL_REACHED',reason='pinned_west_goal_observed',close_required=False)
            sid=self.new_stage_id('nav');retreat=inward_target(o)
            self.stage=manual_target(o,sid,retreat) if retreat is not None else self.planner.choose(o,sid)
            if self.stage is None:return dict(state='GAMEPLAY_BLOCKED',reason=self.planner.reason or 'no_current_local_route',close_required=False)
            self.emit('navigation_target',stage=self.stage,observation=o)
        stage,samples=redirected(o,self.stage)
        samples=8 if stage['jump_first'] else min(samples,stage['max_samples'])
        self.bind(nav=stage)
        o=self.fresh();actual_geometry(o)
        if arrived(o,self.stage):return None
        stage,samples2=redirected(o,self.stage)
        samples=8 if stage['jump_first'] else min(samples2,stage['max_samples'])
        if stage!=self.c.plan.stage(stage['id']):
            self.bind(nav=stage);o=self.fresh();actual_geometry(o)
            if arrived(o,self.stage):return None
        q=self.request(o,'move',stage['id'],forward=stage['forward'],strafe=stage['strafe'],samples=samples,jump_first=stage['jump_first'])
        try:gate(o,q,OWNER,self.c.ledger.data['actions'],self.c.plan)
        except Refused as e:
            self.emit('navigation_gate_blocked_no_post',stage=self.stage,observation=o,reason=str(e))
            if 'nearby' in str(e):raise Gameplay('temporary_nearby_admission_block_same_stage')
            self._planner_finished(self.stage,False);self.stage=None;self.alignment_parent=None
            return dict(state='GAMEPLAY_BLOCKED',reason='fresh_geometry_changed_no_post',close_required=False)
        self.effect(q);return None


def run(controller, *, initial_observation=None, decision_reader=lambda checkpoint:None,
        on_initial_wait=lambda o:None, session_factory=None, maintenance_baseline_path=None, **kwargs):
    # Always fetch ready from the live controller; caller's cached startup frame
    # is not allowed to turn a loading screen into a failed Session constructor.
    spec=strict_json(kwargs['session_spec_raw'])
    confirm=kwargs.pop('confirm_world')
    sleep=kwargs.get('sleep',time.sleep)
    while True:
        observation=wait_ready(controller,player_uuid=spec['player_uuid'],
            stop_requested=kwargs.get('stop_requested',lambda:False),
            on_wait=on_initial_wait,sleep=sleep)
        try:
            if confirm(copy.deepcopy(observation)) is not True:
                raise Maintenance('actual_formal_world_not_confirmed')
        except InitializationWait:
            on_initial_wait({'ready':False,'reason':'initial_read_only_confirmation_pending'})
            sleep(.25)
            continue
        confirmed={k:observation[k] for k in ('session','world_generation','player_uuid','bound_owner_id')}
        observation=wait_ready(controller,player_uuid=spec['player_uuid'],
            stop_requested=kwargs.get('stop_requested',lambda:False),
            on_wait=on_initial_wait,sleep=sleep)
        if any(observation[k]!=v for k,v in confirmed.items()):
            raise Maintenance('initial_confirmation_context_changed_no_adoption')
        break
    clock=kwargs.get('monotonic',time.monotonic)
    kwargs['session_started_at']=clock()
    # No network I/O in the constructor callback. Batch time starts only after
    # read-only identity confirmation and a fresh same-context ready observation.
    kwargs['confirm_world']=lambda o:all(o.get(k)==v for k,v in confirmed.items())
    s=(session_factory or RebuiltSession)(controller,initial_observation=observation,decision_reader=decision_reader,**kwargs)
    s._maintenance_baseline_path=maintenance_baseline_path
    return run_existing(s)


def run_existing(session):
    while True:
        outcome=session.step()
        if outcome is not None and outcome['close_required']:
            path=getattr(session,'_maintenance_baseline_path',None)
            if path is not None:
                from resume_manifest import save_state
                from run_recovery import write_new
                pin=save_state(session,baseline_path=path,reason=outcome['reason'])
                write_new(session.out/'MAINTENANCE-STATE-POINTER.json',encode(pin))
            return outcome
