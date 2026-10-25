"""QueueClient-shaped gateway client. It never writes to the resident mailbox."""
import json
from pathlib import Path
import re
import time
import threading
import uuid
from watchdog import OWNER_OPS, write_json
from base_watchdog import recovery_close_command
from capability_ownership import CONTROL_OPS
ID = re.compile(r'[A-Za-z0-9_-]{1,80}')

def _pending_owner_intent(directory):
    # The daemon atomically claims inbox files into working. Restart the whole
    # read-only snapshot when that happens; never skip an unreadable entry or
    # retry a submit/write. Admission counts pending inbox work, not the active
    # working request, which remains serialized by the daemon's owner.
    for attempt in range(3):
        try:
            return any(json.loads(p.read_text()).get('op') not in CONTROL_OPS
                       for p in directory.glob('*.json'))
        except FileNotFoundError:
            if attempt == 2:
                raise

class IntentClient:
    def __init__(self, directory):
        self.root = Path(directory)
        self._capability_lock = threading.RLock()
        self._capability_stop = threading.Event()
        self._capability_thread = None
        self._capability_owner = None
        self._capability_epoch = None
        self._capability_fault = None
        self._capability_session = None
    def session(self):
        if self._capability_fault:
            raise ValueError(self._capability_fault)
        return self._read_session()
    def _read_session(self):
        data = json.loads((self.root/'state.json').read_text())
        if data.get('implementation') != 'native-defense-watchdog-v5':
            raise ValueError('watchdog_v5_required')
        if time.time() - data.get('updated_at', 0) > 3:
            raise ValueError('watchdog_heartbeat_stale')
        return data
    def reconciliation_session(self):
        from reconciliation_read import session
        return session(self)
    def reconciliation_submit(self, request_id, watchdog_session, original_job_id):
        from reconciliation_read import submit
        return submit(self, request_id, watchdog_session, original_job_id)
    def reconciliation_result(self, request):
        from reconciliation_read import result
        return result(self, request)
    def submit(self, command, request_id=None):
        from fall_rescue_adjudication import OPS,validate
        adjudication=isinstance(command,dict) and command.get('op') in OPS
        if adjudication:validate(command)
        life_ack=isinstance(command,dict) and command.get('op')=='acknowledge_new_life'
        if life_ack:
            from resident_controller.new_life_acknowledgment import command as validate_life
            validate_life(command)
            if self._capability_owner is not None:raise ValueError('new_life_ack_owner_present')
        pause_ack=isinstance(command,dict) and command.get('op')=='acknowledge_idle_pause'
        if pause_ack:
            from resident_controller.pause_acknowledgment import command as validate_pause
            validate_pause(command)
            if self._capability_owner is not None:raise ValueError('pause_ack_owner_present')
        session = self._read_session() if adjudication else self.session()
        recovery = recovery_close_command(command)
        if isinstance(command, dict) and command.get('op') == 'recovery_close_menu' and not recovery:
            raise ValueError('invalid_recovery_close_menu')
        if ((recovery and (session.get('state') != 'paused' or not isinstance(session.get('menu_recovery'), dict)
                          or session['menu_recovery'].get('can_close') is not True))
                or (not recovery and not adjudication and not pause_ack and not life_ack and session.get('state') not in ('ready', 'busy'))
                or (adjudication and session.get('state') not in ('paused','ready','busy'))
                or ((pause_ack or life_ack) and session.get('state')!='paused') or (self.root/'STOP').exists()):
            raise ValueError('watchdog_not_accepting_intents')
        if not isinstance(command, dict) or command.get('op') not in OWNER_OPS:
            raise ValueError('unsupported_owner_intent')
        request_id = request_id or uuid.uuid4().hex
        if not ID.fullmatch(request_id):
            raise ValueError('invalid_request_id')
        name = request_id+'.json'
        for folder in ('inbox','working','results'):
            if (self.root/folder/name).exists():return request_id
        if command.get('op') not in CONTROL_OPS and _pending_owner_intent(self.root/'inbox'):
            raise ValueError('one_pending_owner_intent_only')
        body = {**command, '_watchdog_session_id': session['session_id']}
        if recovery:
            if type(session.get('defense_epoch')) is not int:
                raise ValueError('menu_recovery_epoch_required')
            body.update(_navigation_defense_epoch=session['defense_epoch'], _menu_recovery_requested_at=time.time())
        if len(json.dumps(body).encode()) > 64*1024:
            raise ValueError('intent_too_large')
        write_json(self.root/'inbox'/name,body)
        return request_id
    def result(self, request_id):
        if not ID.fullmatch(request_id):raise ValueError('invalid_request_id')
        path=self.root/'results'/(request_id+'.json')
        if not path.exists():return None
        wrapped=json.loads(path.read_text())
        if 'intent_id' not in wrapped:
            return wrapped  # Explicit restart/stale-intent result.
        original=wrapped['result']
        if (any(k in original for k in ('acquisition_refusal', 'exact_cancel_terminal', 'exact_queued_cancel_terminal', 'pause_acknowledgment', 'new_life_acknowledgment'))
                and wrapped.get('intent_id') != request_id):
            raise ValueError('capability_refusal_wrapper_identity_changed')
        result = {**original, 'request_id':request_id, 'session_id':wrapped['session_id'],
                  'queue_request_id':wrapped['queue_request_id'],
                  'queue_session_id':original.get('session_id')}
        if 'exact_cancel_terminal' in result:
            from resident_controller.cancel_terminal import validate
            proof = result['exact_cancel_terminal']
            if not validate(result, proof.get('command') if isinstance(proof, dict) else None,
                            request_id, wrapped['session_id']):
                raise ValueError('exact_cancel_terminal_proof_invalid')
        if 'exact_queued_cancel_terminal' in result:
            from resident_controller.queued_cancel_terminal import validate
            proof = result['exact_queued_cancel_terminal']
            if not validate(result, proof.get('command') if isinstance(proof, dict) else None,
                            request_id, wrapped['session_id']):
                raise ValueError('exact_queued_cancel_terminal_proof_invalid')
        if 'new_life_acknowledgment' in result:
            from resident_controller.new_life_acknowledgment import validate as validate_life_result
            p=result['new_life_acknowledgment']
            validate_life_result(result,p.get('command') if isinstance(p,dict) else None,request_id,wrapped['session_id'])
        if 'pause_acknowledgment' in result:

            from resident_controller.pause_acknowledgment import validate as validate_pause_result
            p=result['pause_acknowledgment']
            validate_pause_result(result,p.get('command') if isinstance(p,dict) else None,request_id,wrapped['session_id'])
        return result
    def wait(self, request_id, timeout=30):
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            result=self.result(request_id)
            if result is not None:return result
            # An already-confirmed capability lease uses a shorter READ-only
            # result poll. No request is resubmitted and no deadline is reset.
            interval = (.01 if self._capability_owner is not None
                        and self._capability_fault is None
                        and not self._capability_stop.is_set() else .1)
            remaining = deadline-time.monotonic()
            if remaining <= 0:break
            time.sleep(min(interval,remaining))
        return {'request_id':request_id,'status':'pending','reason':'wait_timeout_not_action_failure'}


    def _capability_control_exchange(self, command, timeout, request_id=None):
        # A new control gets one exact identity. An unknown result is never retried.
        request_id = request_id or uuid.uuid4().hex
        returned = self.submit(command, request_id=request_id)
        if returned != request_id:
            raise ValueError('capability_control_submission_identity_changed')
        result = self.wait(request_id, timeout=timeout)
        from resident_controller.acquisition_refusal import validate as valid_refusal
        if valid_refusal(result, command, request_id, self._capability_session):
            return result
        if (not isinstance(result, dict) or result.get('request_id') != request_id
                or result.get('session_id') != self._capability_session
                or result.get('queue_request_id') is not None
                or result.get('status') != 'succeeded'):
            raise ValueError('capability_control_unconfirmed:' + str((result or {}).get('reason', 'identity_or_status')))
        return result

    def acquire_capability(self, owner_id, duration_ms=7200000, timeout=3, *, request_id=None, expected_context=None, expected_defense_epoch=None, owner_mode="ordinary"):
        if owner_mode not in ("ordinary", "external_stop"):
            raise ValueError("invalid_owner_mode")
        with self._capability_lock:
            if self._capability_owner is not None or self._capability_fault:
                raise ValueError('capability_client_already_claimed_or_faulted')
            session = self.session()
            if session.get('capability_lease_schema_version') != 1:
                raise ValueError('capability_lease_gateway_required')
            self._capability_session = session['session_id']
            try:
                command = {'op': 'external_stop_acquire' if owner_mode == 'external_stop' else 'capability_acquire', 'owner_id': owner_id,
                    'expected_defense_epoch': session.get('defense_epoch') if expected_defense_epoch is None else expected_defense_epoch,
                    'expected_context': session.get('capability_context') if expected_context is None else expected_context,
                    'duration_ms': duration_ms}
                result = self._capability_control_exchange(command, timeout, request_id=request_id)
                from resident_controller.acquisition_refusal import validate as valid_refusal
                if valid_refusal(result, command, result.get('request_id'), self._capability_session):
                    # No owner, heartbeat or client fault is created. A caller
                    # may request different new work after fresh readiness.
                    return result
                lease = result.get('capability_lease')
                if (not isinstance(lease, dict) or lease.get('owner_id') != owner_id
                        or lease.get('state') != 'active' or lease.get('defense_epoch') != session.get('defense_epoch')
                        or lease.get('owner_mode', 'ordinary') != owner_mode):
                    raise ValueError('capability_acquisition_identity_unconfirmed')
            except Exception as exc:
                self._capability_fault = 'capability_acquisition_unconfirmed:' + type(exc).__name__
                raise
            self._capability_owner = owner_id
            self._capability_epoch = lease['defense_epoch']
            self._capability_stop.clear()
            self._capability_thread = threading.Thread(target=self._capability_heartbeat_loop,
                                                       name='mdc-capability-heartbeat', daemon=True)
            self._capability_thread.start()
            return result

    def _capability_heartbeat_loop(self):
        while not self._capability_stop.wait(1):
            with self._capability_lock:
                if self._capability_stop.is_set() or self._capability_owner is None:
                    return
                try:
                    session = self.session()
                    lease = session.get('capability_lease')
                    if (session['session_id'] != self._capability_session or not isinstance(lease, dict)
                            or lease.get('owner_id') != self._capability_owner or lease.get('state') != 'active'
                            or session.get('defense_epoch') != self._capability_epoch):
                        raise ValueError('capability_heartbeat_owner_changed')
                    self._capability_control_exchange({'op': 'capability_heartbeat', 'owner_id': self._capability_owner,
                        'expected_defense_epoch': self._capability_epoch}, 1.5)
                except Exception as exc:
                    self._capability_fault = 'capability_heartbeat_unconfirmed:' + type(exc).__name__
                    self._capability_stop.set()
                    return

    def release_capability(self, owner_id, timeout=3, *, request_id=None):
        with self._capability_lock:
            if owner_id != self._capability_owner:
                raise ValueError('capability_release_owner_mismatch')
            try:
                result = self._capability_control_exchange({'op': 'capability_release', 'owner_id': owner_id,
                    'expected_defense_epoch': self._capability_epoch}, timeout, request_id=request_id)
                if result.get('capability_lease') is not None:
                    raise ValueError('capability_release_unconfirmed')
            except Exception as exc:
                self._capability_fault = 'capability_release_unconfirmed:' + type(exc).__name__
                self._capability_stop.set()
                raise
            self._capability_owner = None
            self._capability_stop.set()
        self.close_capability()
        return result

    def close_capability(self):
        """Stop heartbeats. Unresolved ownership stays latched at the gateway."""
        self._capability_stop.set()
        thread = self._capability_thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2)
        self._capability_thread = None


    def stop_capability_heartbeat(self, owner_id):
        if self._capability_owner is not None and self._capability_owner != owner_id:
            raise ValueError('capability_heartbeat_owner_mismatch')
        self.close_capability()

    def adjudication_release_local(self,owner_id,gateway_session):
        """Called only after exact gateway/native proof; no external control write."""
        self.close_capability()
        with self._capability_lock:
            if self._capability_owner!=owner_id or self._capability_session!=gateway_session:
                raise ValueError('fall_adjudication_client_owner_changed')
            self._capability_owner=None;self._capability_epoch=None;self._capability_fault=None
