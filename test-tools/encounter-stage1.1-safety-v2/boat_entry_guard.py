"""One-shot, pre-action entry check. No resume, mount, drive, cancel or raw input.

Construct while natively paused on independently reviewed solid support, then
check immediately after the separately authorized resume in the SAME process.
This cooperative guard cannot protect swimming waits, a frozen client/process,
or an action already submitted. Its durable reservation is never reloadable.
"""
from copy import deepcopy
import hashlib
from pathlib import Path
import os
import time
import uuid

from post_trial_safety import (MAX_OBSERVE_SECONDS, PAUSE_SCREEN, SafetyHalt,
                              _finite, _load, _ref, _require, _write)
from receipt_binding import _uncertain
from resident_controller.ipc import ID
from resident_controller.pause_contract import validate_pause_request, validate_pause_receipt


class BoatEntryGuard:
    def __init__(self, client, case_id, binding, *, surface_y, support_evidence_ref,
                 pause_authorization_ref, clock=time.monotonic, wall_clock=time.time):
        _require(isinstance(case_id, str) and ID.fullmatch(case_id), 'invalid_boat_entry_case_id')
        _require(set(binding) == {'resident_session', 'action_session', 'world_generation', 'player_uuid'},
                 'invalid_boat_entry_binding')
        _require(_ref(support_evidence_ref) and _ref(pause_authorization_ref), 'boat_entry_references_required')
        _require(type(surface_y) is int and -2048 <= surface_y <= 2048, 'invalid_water_surface')
        self.c, self.b, self.y = client, deepcopy(binding), surface_y
        self.clock, self.wall_clock, self.used, self.blocked = clock, wall_clock, False, False
        self.io = []
        namespace = uuid.UUID(binding['resident_session'])
        self.pause_id = uuid.uuid5(namespace, case_id + ':entry-pause').hex
        body = validate_pause_request({'pause_schema_version': 1,
            **{'expected_' + k: binding[k] for k in ('action_session', 'world_generation', 'player_uuid')},
            'expected_action_id': uuid.uuid5(namespace, case_id + ':never-submitted-entry-action').hex})
        self.command = {'op': 'encounter_pause', 'expected_resident_session': binding['resident_session'], 'body': body}
        self.folder = Path(client.root) / 'boat-entry-guard'
        self.path = self.folder / (case_id + '.reservation.json')
        audit = validate_store(client.root)  # Unknown/partial prior cases cannot renew by renaming.
        _require(not set((case_id, self.pause_id, body['expected_action_id'])).intersection(audit['consumed_request_ids']),
                 'boat_entry_identity_previously_consumed')
        _require(not self.path.exists(), 'boat_entry_case_already_used')
        self._unused_pause_id()
        before = self._observe()
        _require(self._paused(before), 'boat_entry_requires_native_pause')
        self._entry(before)
        self.reservation = {'boat_entry_guard_schema_version': 1,
            'case_id': case_id, 'binding': self.b, 'pause_request_id': self.pause_id,
            'command': self.command, 'before': before, 'surface_y': surface_y,
            'support_evidence_ref': support_evidence_ref, 'pause_authorization_ref': pause_authorization_ref,
            'single_use_claimed_before_resume': True, 'automatic_retry': False}
        self.folder.mkdir(exist_ok=True)
        fd = os.open(self.folder.parent, os.O_RDONLY)
        try: os.fsync(fd)
        finally: os.close(fd)
        _write(self.path, self.reservation)  # Exclusive, fsynced claim BEFORE any resume.

    def _unused_pause_id(self):
        _require(all(not (Path(self.c.root) / d / (self.pause_id + '.json')).exists()
                     for d in ('inbox', 'working', 'results')), 'boat_entry_pause_id_preexists_no_replay')

    def _session(self, allow_own_pause=False):
        s = self.c.session()
        good = self._session_ok(s, self.b, allow_own_pause)
        if not good: self.blocked = True
        _require(good, 'boat_entry_foreign_or_unknown_resident_owner')
        return s

    @staticmethod
    def _session_ok(s, binding, allow_own_pause=False):
        if not isinstance(s, dict): return False
        clean = s.get('state') == 'ready' and 'reason' in s and s['reason'] is None
        own_pause = (allow_own_pause and s.get('state') == 'paused'
            and s.get('reason') in ('encounter_pause_requested', 'encounter_pause_unknown'))
        return (s.get('session_id') == binding['resident_session']
            and s.get('bridge_identity', {}).get('action_session') == binding['action_session']
            and (clean or own_pause)
            and 'active_request_id' in s and s['active_request_id'] is None
            and 'active_action_id' in s and s['active_action_id'] is None
            and type(s.get('pending')) is int and s['pending'] == 0 and s.get('pending_request_ids') == []
            and s.get('aim_lock', {}).get('active') is False
            and s.get('combat', {}).get('active') is False and s.get('combat', {}).get('held_mappings') == [])

    def _request(self, command, rid, session_before):
        started, wall = self.clock(), self.wall_clock()
        raw = {'request_id': rid, 'command': deepcopy(command), 'started_monotonic': started,
               'started_wall': wall, 'session_before': deepcopy(session_before), 'session_after': None, 'receipt': None}
        self.io.append(raw)
        _require(self.c.submit(command, request_id=rid) == rid, 'boat_entry_submit_id_mismatch')
        receipt = self.c.wait(rid, MAX_OBSERVE_SECONDS)
        raw.update(receipt=deepcopy(receipt), finished_monotonic=self.clock(), finished_wall=self.wall_clock())
        _require(type(receipt) is dict and receipt.get('request_id') == rid
            and receipt.get('session_id') == self.b['resident_session'] and receipt.get('status') == 'succeeded'
            and not _uncertain(receipt) and _finite(receipt.get('finished_at'))
            and wall <= receipt['finished_at'] <= self.wall_clock()
            and 0 <= self.clock() - started <= MAX_OBSERVE_SECONDS, 'boat_entry_receipt_unknown_or_stale')
        return receipt

    def _observe(self, allow_own_pause=False):
        before = self._session(allow_own_pause)
        value = self._request({'op': 'observe', 'frame': False}, uuid.uuid4().hex, before)['result']
        good = self._context(value, self.b)
        if not good: self.blocked = True
        _require(good, 'boat_entry_identity_or_native_owner_changed')
        self.io[-1]['session_after'] = deepcopy(self._session(allow_own_pause))
        return value

    @staticmethod
    def _context(value, binding):
        state, status = value.get('state', {}), value.get('status', {})
        good = (state.get('world', {}).get('world_generation') == binding['world_generation']
            and status.get('world', {}).get('world_generation') == binding['world_generation']
            and state.get('player', {}).get('uuid') == binding['player_uuid']
            and status.get('player', {}).get('uuid') == binding['player_uuid'])
        for action in (value.get('action', {}), state.get('client_action', {}), status.get('client_action', {})):
            good &= (action.get('action_session') == binding['action_session']
                and action.get('status') == 'idle' and 'action_id' in action and action['action_id'] is None
                and action.get('input_owner') == 'direct')
        good &= (value.get('aim_lock', {}).get('active') is False
            and value.get('combat', {}).get('active') is False and value.get('combat', {}).get('held_mappings') == []
            and status.get('guarded_movement', {}).get('owner_request_id') is None
            and status.get('guarded_movement', {}).get('owner_action') is None)
        return good

    @staticmethod
    def _paused(value):
        return (value['state'].get('paused') is True and value['state'].get('screen_open') is True
            and value.get('screen', {}).get('open') is True and value['screen'].get('class') == PAUSE_SCREEN)

    @staticmethod
    def _neutral(value):
        s, p = value['status'], value['state']['player']
        _require(s.get('held_mappings') == [] and s.get('mouse', {}).get('held_world_buttons') == []
            and all(s.get('mouse', {}).get(k) is False for k in ('left_pressed', 'right_pressed', 'middle_pressed'))
            and type(s.get('input_isolation', {}).get('held_keys')) is int and s['input_isolation']['held_keys'] == 0
            and s.get('guarded_movement', {}).get('held_keys') is False
            and s['guarded_movement'].get('released') is True
            and 'owner_request_id' in s['guarded_movement'] and s['guarded_movement']['owner_request_id'] is None
            and 'owner_action' in s['guarded_movement'] and s['guarded_movement']['owner_action'] is None
            and s.get('guarded_turn', {}).get('held_input') is False
            and p.get('using_item') is False and p.get('sprinting') is False, 'boat_entry_inputs_not_neutral')

    def _entry(self, value):
        self._entry_at_surface(value, self.y)

    @staticmethod
    def _entry_at_surface(value, surface_y):
        BoatEntryGuard._neutral(value)
        p = value['state']['player']
        _require(p.get('alive') is True and p.get('on_ground') is True
            and p.get('health') == 20 and p.get('air') == p.get('max_air') == 300
            and p.get('vehicle', {}).get('riding') is False
            and _finite(p.get('eye_position', {}).get('y')) and p['eye_position']['y'] > surface_y + .1,
            'boat_entry_requires_supported_full_air_player_above_water')

    def check(self, entry_assertions, *, main_action_submitted):
        """entry_assertions is read-only; its exception is caught before any report write."""
        _require(not self.used and main_action_submitted is False, 'boat_entry_consumed_or_main_already_submitted')
        self.used = True
        report = {'boat_entry_guard_schema_version': 1, 'case_id': self.reservation['case_id'],
                  'binding': deepcopy(self.b), 'pause_request_id': self.pause_id, 'command': deepcopy(self.command),
                  'entry_ready': False, 'main_action_submitted': False, 'main_action_accepted': False,
                  'pause_attempted': False, 'pause_acknowledged': False, 'pause_observed': False,
                  'neutral_inputs_observed': False, 'automatic_retry': False, 'requests': self.io}
        try:
            try:
                _require(_load(self.path) == self.reservation, 'boat_entry_reservation_changed')
            except Exception:
                self.blocked = True
                raise
            observation = self._observe()
            _require(observation['state'].get('paused') is False
                and observation['state'].get('screen_open') is False
                and observation.get('screen', {}).get('open') is False, 'boat_entry_not_resumed')
            self._entry(observation)
            _require(entry_assertions(deepcopy(observation)) is not False, 'boat_entry_assertions_failed')
            report.update(entry_ready=True, observation=observation)
        except Exception as exc:
            report['stop_reason'] = str(exc)
            try:
                _require(not self.blocked, 'boat_entry_context_changed_no_pause')
                session = self._session()
                self._unused_pause_id()
                report['pause_attempted'] = True  # Consumed even if submit raises.
                receipt = self._request(self.command, self.pause_id, session)
                report['pause_receipt'] = receipt
                result = validate_pause_receipt(receipt['result'], self.command['body'])
                _require(result['expected_action_present'] is False, 'boat_entry_expected_action_was_not_missing')
                report['pause_acknowledged'] = True
            except Exception as pause_error:
                report['pause_error'] = str(pause_error)
            # Read-only reconciliation even after unknown pause; never another POST.
            if report['pause_attempted']:
                try:
                    report['after'] = self._observe(allow_own_pause=True)
                    report['pause_observed'] = self._paused(report['after'])
                    self._neutral(report['after'])
                    report['neutral_inputs_observed'] = True
                except Exception as effect_error:
                    report['effect_error'] = str(effect_error)
        _write(self.path.with_name(self.reservation['case_id'] + '.result.json'), report)
        return report


def _verified_read(raw, binding, command, allow_own_pause=False):
    """Recheck a retained receipt, never borrow a newer observation to fix it."""
    _require(type(raw) is dict and raw.get('command') == command
        and isinstance(raw.get('request_id'), str) and ID.fullmatch(raw['request_id'])
        and BoatEntryGuard._session_ok(raw.get('session_before'), binding, allow_own_pause)
        and (command['op'] != 'observe' or BoatEntryGuard._session_ok(raw.get('session_after'), binding, allow_own_pause)),
        'boat_entry_stored_request_invalid')
    receipt = raw.get('receipt')
    _require(type(receipt) is dict and receipt.get('request_id') == raw['request_id']
        and receipt.get('session_id') == binding['resident_session'] and receipt.get('status') == 'succeeded'
        and not _uncertain(receipt) and _finite(receipt.get('finished_at'))
        and all(_finite(raw.get(k)) for k in ('started_monotonic', 'finished_monotonic', 'started_wall', 'finished_wall'))
        and raw['started_wall'] <= receipt['finished_at'] <= raw['finished_wall']
        and 0 <= raw['finished_monotonic'] - raw['started_monotonic'] <= MAX_OBSERVE_SECONDS,
        'boat_entry_stored_receipt_unknown_or_stale')
    return receipt['result']


def validate_store(queue_root):
    """Pure narrow audit; return file pins/guard outcomes, never main-action completion.

    Missing store is unused. Existing empty/partial/unknown stores raise SafetyHalt.
    Both new guard construction and normal rollover must use this exact check.
    """
    folder = Path(queue_root) / 'boat-entry-guard'
    answer = {'present': False, 'files': {}, 'entries': [], 'consumed_request_ids': [], 'main_action_evaluated': False}
    _require(not folder.is_symlink(), 'boat_entry_store_alias_forbidden')
    if not folder.exists(): return answer
    try:
        _require(folder.is_dir(), 'boat_entry_store_not_directory')
        files = list(folder.iterdir())
        cases = sorted(p.name.removesuffix('.reservation.json') for p in files if p.name.endswith('.reservation.json'))
        _require(bool(cases) and all(ID.fullmatch(c) for c in cases), 'boat_entry_store_partial_or_empty')
        expected = {c + suffix for c in cases for suffix in
                    ('.reservation.json', '.reservation.json.sha256', '.result.json', '.result.json.sha256')}
        _require({p.name for p in files} == expected and all(p.is_file() and not p.is_symlink() for p in files),
                 'boat_entry_store_partial_or_unknown_file')
        pins = {str(p.relative_to(Path(queue_root))): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(files)}
        used = set()
        for case in cases:
            reservation = _load(folder / (case + '.reservation.json'))
            result = _load(folder / (case + '.result.json'))
            binding, command = reservation['binding'], reservation['command']
            _require(set(binding) == {'resident_session', 'action_session', 'world_generation', 'player_uuid'},
                     'boat_entry_stored_binding_invalid')
            namespace = uuid.UUID(binding['resident_session'])
            _require(binding['resident_session'] in (str(namespace), namespace.hex), 'boat_entry_stored_resident_noncanonical')
            body = validate_pause_request(command['body'])
            _require(command == {'op': 'encounter_pause', 'expected_resident_session': binding['resident_session'], 'body': body}
                and all(body['expected_' + k] == binding[k] for k in ('action_session', 'world_generation', 'player_uuid'))
                and body['expected_action_id'] == uuid.uuid5(namespace, case + ':never-submitted-entry-action').hex
                and reservation['pause_request_id'] == uuid.uuid5(namespace, case + ':entry-pause').hex,
                'boat_entry_stored_pause_binding_mismatch')
            for key in ('boat_entry_guard_schema_version', 'case_id', 'binding', 'pause_request_id', 'command'):
                _require(result.get(key) == reservation.get(key), 'boat_entry_result_reservation_mismatch')
            _require(type(reservation.get('boat_entry_guard_schema_version')) is int
                and type(result.get('boat_entry_guard_schema_version')) is int
                and reservation['boat_entry_guard_schema_version'] == 1 and reservation.get('case_id') == case
                and reservation.get('single_use_claimed_before_resume') is True
                and reservation.get('automatic_retry') is False and result.get('automatic_retry') is False
                and _ref(reservation.get('support_evidence_ref')) and _ref(reservation.get('pause_authorization_ref'))
                and type(reservation.get('surface_y')) is int and -2048 <= reservation['surface_y'] <= 2048,
                'boat_entry_stored_reservation_invalid')
            flags = ('entry_ready', 'main_action_submitted', 'main_action_accepted', 'pause_attempted',
                     'pause_acknowledged', 'pause_observed', 'neutral_inputs_observed')
            _require(all(type(result.get(k)) is bool for k in flags)
                and result['main_action_submitted'] is False and result['main_action_accepted'] is False,
                'boat_entry_result_scope_invalid')
            requests = result['requests']; observe = {'op': 'observe', 'frame': False}
            _require(type(requests) is list and len(requests) in (2, 4), 'boat_entry_stored_io_shape_invalid')
            previous_mono = previous_wall = float('-inf')
            for raw in requests:
                _require(type(raw) is dict and _finite(raw.get('started_monotonic')) and _finite(raw.get('started_wall'))
                    and raw['started_monotonic'] >= previous_mono and raw['started_wall'] >= previous_wall,
                    'boat_entry_stored_io_out_of_order')
                previous_mono = raw.get('finished_monotonic', raw['started_monotonic'])
                previous_wall = raw.get('finished_wall', raw['started_wall'])
                _require(_finite(previous_mono) and _finite(previous_wall)
                    and previous_mono >= raw['started_monotonic'] and previous_wall >= raw['started_wall'],
                    'boat_entry_stored_io_invalid_timing')
            ids = [r['request_id'] for r in requests]
            _require(all(isinstance(r, str) and ID.fullmatch(r) for r in ids)
                and len(set(ids)) == len(ids) and not used.intersection(ids), 'boat_entry_stored_request_id_reused')
            used.update(ids)
            before = _verified_read(requests[0], binding, observe)
            _require(before == reservation['before'] and BoatEntryGuard._context(before, binding)
                and BoatEntryGuard._paused(before), 'boat_entry_stored_baseline_unbound')
            BoatEntryGuard._entry_at_surface(before, reservation['surface_y'])
            if result['entry_ready']:
                _require(len(requests) == 2 and all(result[k] is False for k in flags[3:])
                    and not any(k in result for k in ('stop_reason', 'pause_error', 'effect_error', 'pause_receipt', 'after')),
                    'boat_entry_ready_with_stop_or_pause')
                fresh = _verified_read(requests[1], binding, observe)
                _require(result.get('observation') == fresh and BoatEntryGuard._context(fresh, binding)
                    and fresh['state'].get('paused') is False and fresh['state'].get('screen_open') is False
                    and fresh.get('screen', {}).get('open') is False, 'boat_entry_ready_observation_invalid')
                BoatEntryGuard._entry_at_surface(fresh, reservation['surface_y'])
                outcome = 'entry_ready'
            else:
                _require(len(requests) == 4 and all(result[k] is True for k in flags[3:])
                    and _ref(result.get('stop_reason')) and 'pause_error' not in result and 'effect_error' not in result
                    and requests[1].get('command') == observe and requests[2]['request_id'] == reservation['pause_request_id'],
                    'boat_entry_pause_unresolved')
                acknowledgement = _verified_read(requests[2], binding, command)
                _require(result.get('pause_receipt') == requests[2]['receipt'], 'boat_entry_pause_receipt_replaced')
                validate_pause_receipt(acknowledgement, body)
                _require(acknowledgement['expected_action_present'] is False, 'boat_entry_missing_action_not_proven')
                after = _verified_read(requests[3], binding, observe, allow_own_pause=True)
                _require(result.get('after') == after and BoatEntryGuard._context(after, binding)
                    and BoatEntryGuard._paused(after), 'boat_entry_pause_effect_unverified')
                BoatEntryGuard._neutral(after)
                outcome = 'paused_on_entry_failure'
            answer['entries'].append({'case_id': case, 'outcome': outcome, 'binding': binding,
                'pause_request_id': reservation['pause_request_id'], 'expected_action_id': body['expected_action_id'],
                'request_ids': ids, 'main_action_evaluated': False})
        answer['present'] = True
        answer['consumed_request_ids'] = sorted(used | {x[k] for x in answer['entries']
            for k in ('case_id', 'pause_request_id', 'expected_action_id')})
        _require({p.name for p in folder.iterdir()} == expected and pins == {
            str(p.relative_to(Path(queue_root))): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(files)},
            'boat_entry_store_changed_during_audit')
        answer['files'] = pins
        return answer
    except SafetyHalt:
        raise
    except Exception as exc:
        raise SafetyHalt('boat_entry_store_invalid_no_reset') from exc
