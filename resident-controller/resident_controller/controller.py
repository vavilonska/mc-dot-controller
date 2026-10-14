"""Single foreground controller; Minecraft owns continuous tick execution."""
from __future__ import annotations

from collections import deque
from copy import deepcopy
from dataclasses import dataclass
import fcntl
import math
import os
from pathlib import Path
import re
import time
import uuid
from urllib.parse import quote

from .coordination_contract import check_resident as check_coordination, native_action_id
from .entity_aim_lock import EntityAimLock, MAX_SAMPLE_SECONDS
from .native_combat import NativeCombat
from .ipc import ID, MAX_PENDING, MAX_RESULTS, atomic_json, read_json
from .prospecting import ProspectingCache, SCAN_OPS, scan_id, start_body, validate_scan
from .tasks import make_task
from .action_safety import native_release_unconfirmed, native_handoff_required
from .navigation_binding import NAVIGATION_REJECTIONS
from .encounter_contract import (validate_encounter_command, validate_encounter_request,
                                 validate_encounter_receipt)
from .pause_contract import pause_body, validate_pause_receipt
from .transport import BridgeError, DIRECT
from .capability_snapshot import source_freshness
from .movement_wire import valid_size_diagnostic
from .world import WorldCache, scan_identity

TERMINAL = {'succeeded', 'failed', 'cancelled'}
TASKS = {'action', 'walk_to', 'craft_planks', 'pillar'}


def action_rejection_admission(exc):
    """Only called for an actual definite POST rejection; diagnostics add no authority."""
    result = {'schema_version': 1, 'http_status': exc.status,
              'admitted': False, 'uncertain': False, 'reason': exc.code}
    freshness = getattr(exc, 'capability_source_freshness', None)
    if freshness is not None and source_freshness(freshness):
        result['capability_source_freshness'] = deepcopy(freshness)
    elif freshness is not None or getattr(exc, 'capability_source_freshness_status', None) == 'invalid':
        result['capability_source_freshness_status'] = 'invalid'
    movement_size = getattr(exc, 'scoped_movement_response_size', None)
    if exc.status == 409 and exc.code == 'scoped_movement_response_evidence_too_large':
        if valid_size_diagnostic(movement_size):
            result['scoped_movement_response_size'] = deepcopy(movement_size)
        elif movement_size is not None or getattr(exc, 'scoped_movement_response_size_status', None) == 'invalid':
            result['scoped_movement_response_size_status'] = 'invalid'
    return result


@dataclass
class Running:
    command: dict
    recipe: object
    action_id: str | None = None
    step_number: int = 0
    response: object = None
    last_action_result: object = None
    wake_at: float = 0.0
    encounter_request: dict | None = None
    capability_cancel_attempted: bool = False
    capability_unknown: bool = False
    coordination_cancel_attempted: bool = False
    coordination_unknown: bool = False
    coordination_result_published: bool = False
    coordination_post_metadata: dict | None = None


class Resident:
    def __init__(self, bridge, directory):
        self.bridge, self.root = bridge, Path(directory)
        self.session_id = uuid.uuid4().hex
        self.pending, self.active = deque(), None
        self.cache = WorldCache()
        self.paused = False
        self.reason = None
        self.running = True
        self.bridge_identity = None
        self.started_at = time.time()
        self.last_status = None
        self.last_publish = 0.0
        self.lock = None
        self.owns_lock = False
        self.initialized = False
        self.seen = set()
        self.aim = EntityAimLock()
        self.combat = NativeCombat()
        self.prospecting = ProspectingCache(self.root / 'scan_cache.json', self.session_id)

    def observation_policy(self):
        active = getattr(self, 'active', None)
        pending = getattr(self, 'pending', ())
        handoff = (getattr(active, 'encounter_request', None) is not None
                   or any(any(k in c for k in ('encounter_mode', 'encounter_scope', 'encounter_pause_on_terminal'))
                          for c in pending)
                   or getattr(self, 'paused', False) and getattr(self, 'reason', None) in (
                       'encounter_requires_handoff', 'encounter_pause_requested', 'encounter_pause_unknown'))
        return {'schema_version': 1, 'requires_handoff': bool(handoff),
                'input_release_unconfirmed': bool(getattr(self, 'paused', False)
                    and getattr(self, 'reason', None) == 'input_release_unconfirmed')}

    def publish(self):
        data = {'schema_version': 1, 'session_id': self.session_id, 'coordination_protocol': 1,
                'state': 'stopped' if not self.running else 'starting' if not self.initialized else 'paused' if self.paused else 'busy' if self.active else 'ready',
                'resident_policy': self.observation_policy(),
                'reason': self.reason, 'started_at': self.started_at, 'updated_at': time.time(),
                'base_url': self.bridge.base_url, 'controller_pid': os.getpid(),
                'bridge_identity': self.bridge_identity,
                'active_request_id': self.active.command['request_id'] if self.active else None,
                'active_action_id': self.active.action_id if self.active else None,
                'pending': len(self.pending),
                'pending_request_ids': [c['request_id'] for c in self.pending], 'aim_lock': self.aim.status(),
                'combat': self.combat.status(), 'scan_cache': self.prospecting.summary(),
                'terrain_read': dict(self.cache.terrain_read)}
        if getattr(self, '_terrain_acquisition_unknown', None) is not None:
            saved = self._terrain_acquisition_unknown
            data['terrain_acquisition_unknown'] = {key: deepcopy(saved[key]) for key in
                ('job_id', 'owner_id', 'outcome_unknown', 'ownership_unresolved')}
        atomic_json(self.root / 'session.json', data)
        self.last_publish = time.monotonic()

    def start(self):
        self.root.mkdir(parents=True, exist_ok=True)
        os.chmod(self.root, 0o700)
        for folder in ('inbox', 'working', 'results'):
            (self.root / folder).mkdir(exist_ok=True)
        self.lock = (self.root / '.controller.lock').open('a')
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('controller_already_running_for_queue') from None
        self.owns_lock = True
        # Never present a previous resident process's observations as current.
        self.prospecting.reset()
        self.publish()
        # A prior process may have crashed after sending a request. Never replay it.
        for path in list((self.root / 'working').glob('*.json')) + list((self.root / 'inbox').glob('*.json')):
            self.finish({'request_id': path.stem}, 'uncertain', reason='previous_session_not_replayed')
            path.unlink(missing_ok=True)
        status = self.bridge.request('GET', '/control/status')
        if status.get('protocol') != 'mineclient-bridge' or status.get('schema_version') != 2:
            raise ValueError('unsupported_bridge_protocol')
        continuous = self.bridge.request('GET', '/control/action/status')
        if continuous.get('action_schema_version') != 1 or not continuous.get('action_session'):
            raise ValueError('continuous_action_mod_required')
        self.bridge_identity = {'run_id': status.get('run_id'), 'process_id': status.get('process_id'),
                                'action_session': continuous['action_session']}
        self.last_status = status
        self.prospecting.observe_world(status.get('world'), in_world=status.get('in_world') is True)
        self.initialized = True
        if continuous.get('status') == 'running':
            self.paused, self.reason = True, ('encounter_requires_handoff' if native_handoff_required(continuous)
                                              else 'preexisting_action_use_observe_or_direct_takeover')
        elif native_release_unconfirmed(continuous):
            self.paused, self.reason = True, 'input_release_unconfirmed'
        elif native_handoff_required(continuous):
            self.paused, self.reason = True, 'encounter_requires_handoff'
        self.publish()

    def check_identity(self, status):
        actual = {'run_id': status.get('run_id'), 'process_id': status.get('process_id'),
                  'action_session': status.get('client_action', {}).get('action_session')}
        if actual != self.bridge_identity:
            self.prospecting.reset()
            self.combat.stop(self, 'bridge_restarted', release=False)
            self.aim.release('bridge_restarted')
            self.paused, self.reason = True, 'bridge_restarted_owner_restart_controller'
            raise ValueError(self.reason)
        self.prospecting.observe_world(status.get('world'), in_world=status.get('in_world') is True)
        if (status.get('client_action', {}).get('status') == 'running'
                and (self.combat.active or self.combat.held)):
            # A newly observed ClientActions owner already cleared old inputs.
            # This also covers explicit stop/final cleanup before the next aim tick.
            self.combat.confirm_released()
            self.combat.stop(self, 'external_action_took_control', release=False)
        self.last_status = status

    def finish(self, command, status, **fields):
        request_id = command['request_id']
        if not ID.fullmatch(request_id):
            return
        if any(k in command for k in ('encounter_mode', 'encounter_scope', 'encounter_pause_on_terminal')):
            fields.update(risk_remaining=True, requires_handoff=True, safety_assured=False)
        atomic_json(self.root / 'results' / (request_id + '.json'),
                    {'request_id': request_id, 'session_id': command.get('session_id', self.session_id),
                     'status': status, 'finished_at': time.time(), **fields})
        (self.root / 'working' / (request_id + '.json')).unlink(missing_ok=True)
        files = sorted((self.root / 'results').glob('*.json'), key=lambda p: p.stat().st_mtime)
        for path in files[:-MAX_RESULTS]:
            path.unlink(missing_ok=True)

    def discard_pending(self, reason):
        while self.pending:
            self.finish(self.pending.popleft(), 'cancelled', reason=reason)

    def end_active(self, status, **fields):
        if self.active:
            self.finish(self.active.command, status, **fields)
            self.active = None
        if status != 'succeeded':
            self.discard_pending('prior_task_stopped')
        self.publish()

    def interrupt_local(self, reason):
        # Caller follows this with the single atomic mod takeover POST.
        self.discard_pending(reason)
        if self.active:
            self.end_active('cancelled', reason=reason, mod_cancel_confirmed=False)

    def snapshot(self, command):
        clock_profile=command.get('observation_clock')
        if 'observation_clock' in command:
            if (clock_profile != 'client-pre-tick-v1' or command.get('op') != 'observe'
                    or command.get('capability_observation') is not True
                    or any(k in command for k in ('capability_survey','coordination_step','frame'))):
                raise ValueError('read_only_observation_options')
        if 'terrain_acquisition' in command:
            from .terrain_acquisition import snapshot
            result = snapshot(self, command)
            atomic_json(self.root / 'observation.json', result)
            return result
        capability = command.get('capability_observation') is True
        scan_start = None
        if capability:
            options = {'entity_radius': command.get('entity_radius', 8),
                       'coordination': command.get('coordination_step') is True, 'observation_clock':clock_profile}
            if command.get('terrain'):
                # A failed coherent A must not leave a previous terrain success
                # available as if this requested refresh had succeeded.
                self.cache.invalidate_terrain()
                _state, scan_start = self.cache.observe_scan_start(self.bridge, **options)
            else:
                self.cache.observe(self.bridge, capability=True, **options)
            bundle = self.cache.capability_bundle
            status = bundle['status']
            self.check_identity(status)
            result = {key: bundle[key] for key in ('status', 'action', 'state', 'screen')}
            result['capability_snapshot_schema_version'] = bundle['capability_snapshot_schema_version']
            if clock_profile is not None:
                result.update({k:deepcopy(bundle[k]) for k in ('ok','protocol','schema_version','observation_clock_profile','observation_clock')})
        else:
            status = self.bridge.request('GET', '/control/status')
            self.check_identity(status)
            result = {'status': status, 'aim_lock': self.aim.status(), 'combat': self.combat.status(),
                      'action': self.bridge.request('GET', '/control/action/status'),
                      'scan_cache': self.prospecting.summary()}
        if capability:
            result.update(aim_lock=self.aim.status(), combat=self.combat.status(),
                          scan_cache=self.prospecting.summary())
        policy = self.observation_policy()
        result['resident_policy'] = policy
        if policy['requires_handoff'] or policy['input_release_unconfirmed']:
            result['requires_handoff'] = True
        if not capability and status.get('in_world'):
            result['state'] = self.cache.observe(self.bridge,
                **({'entity_radius': command['entity_radius']} if 'entity_radius' in command else {}),
                **({'coordination': True} if command.get('coordination_step') is True else {}))
        if 'state' in result:
            self.prospecting.observe_world(result['state'].get('world'))
        if not capability:
            result['screen'] = self.bridge.request('GET', '/control/screen')
        if command.get('terrain'):
            previous_read = self.cache.terrain_read
            try:
                result['terrain'] = self.cache.scan(self.bridge, command.get('radius', 4), command.get('vertical', 2),
                    **({'capability': True, 'entity_radius': command.get('entity_radius', 8), 'survey': command.get('capability_survey', False), '_initial_observation': scan_start, 'observation_clock':clock_profile} if command.get('capability_observation') is True else {}), **({'coordination': True} if command.get('coordination_step') is True else {}))
                first, final = result.get('state', {}), self.cache.state
                if (scan_identity(first) != scan_identity(final)
                        or any(first.get('world', {}).get(k) != final.get('world', {}).get(k)
                               for k in ('world_generation', 'dimension'))):
                    self.cache.invalidate_terrain()
                    raise ValueError('terrain_snapshot_context_changed')
                # C replaces every native sibling together in capability mode.
                # Legacy observations keep their original independent reads.
                if capability:
                    bundle = self.cache.capability_bundle
                    self.check_identity(bundle['status'])
                    result.update({key: bundle[key] for key in ('status', 'action', 'state', 'screen')})
                    if clock_profile is not None:
                        result.update({k:deepcopy(bundle[k]) for k in ('ok','protocol','schema_version','observation_clock_profile','observation_clock')})
                else:
                    result['state'] = final
                self.prospecting.observe_world(final.get('world'))
            except (BridgeError, ValueError, KeyError, TypeError) as exc:
                # Bind only this scan's evidence to this failed request. An invalid
                # request rejected before scan entry must not inherit an older read.
                if self.cache.terrain_read is not previous_read:
                    exc.terrain_read_diagnostics = dict(self.cache.terrain_read)
                raise
        if (command.get('coordination_step') is True or capability) and self.cache.state_capture is not None and 'state' in result:
            capture = self.cache.state_capture
            if command.get('coordination_step') is True:
                result['coordination_capture'] = dict(capture)
            if capability:
                result['capability_capture'] = dict(capture)
            result['state_read_diagnostics'] = {
                'clock': 'python_monotonic', 'started_monotonic': capture['started_mono'],
                'finished_monotonic': capture['finished_mono'],
                'response_metadata': deepcopy(self.cache.state_response_metadata)}
        if capability and self.cache.capability_wire is not None:
            # Original bytes are stored once, separately from the decoded semantic siblings.
            result['native_capability_wire'] = deepcopy(self.cache.capability_wire)
        if command.get('frame'):
            frame = self.bridge.request('GET', '/control/frame')
            path = self.root / 'latest.png'
            temp = path.with_suffix('.tmp.png')
            temp.write_bytes(frame)
            os.replace(temp, path)
            result['frame'] = {'path': str(path), 'captured_at': time.time(), 'source': 'native_minecraft_frame'}
        result['scan_cache'] = self.prospecting.summary()
        result['terrain_read'] = dict(self.cache.terrain_read)
        atomic_json(self.root / 'observation.json', result)
        return result

    def check_menu_recovery(self, command):
        context = command.get('expected_menu_context')
        stamp = command.get('menu_recovery_requested_at')
        if (command.get('watchdog_menu_recovery') is not True or command.get('op') != 'direct'
                or command.get('endpoint') != 'raw-key'
                or command.get('body') != {'key': 'key.keyboard.escape', 'action': 'click'}
                or command.get('expected_resident_session') != self.session_id
                or type(context) is not dict
                or set(context) != {'world_generation', 'player_uuid', 'action_session', 'game_time', 'paused'}
                or any(type(context[k]) is not str or not context[k] for k in ('world_generation', 'player_uuid', 'action_session'))
                or type(context['game_time']) is not int or context['game_time'] < 0
                or type(context['paused']) is not bool):
            raise ValueError('invalid_menu_recovery_command')
        if (type(stamp) not in (int, float) or not math.isfinite(stamp)
                or not 0 <= time.time() - stamp <= .8):
            raise ValueError('stale_menu_recovery_command')
        policy = self.observation_policy()
        if (policy['requires_handoff'] or policy['input_release_unconfirmed'] or self.paused
                or self.active or self.pending or self.combat.active or self.combat.held or self.aim.active):
            raise ValueError('resident_owner_blocks_menu_recovery')
        if context['action_session'] != self.bridge_identity.get('action_session'):
            raise ValueError('menu_recovery_context_changed')
        return context

    def recover_menu(self, command):
        context = self.check_menu_recovery(command)
        status = self.bridge.request('GET', '/control/status')
        if not isinstance(status, dict) or not isinstance(status.get('client_action'), dict):
            raise ValueError('menu_recovery_status_unconfirmed')
        # Ordinary check_identity performs owner cleanup on a restart. This
        # restricted request only rejects; it has no authority to clean an owner.
        identity = {'run_id': status.get('run_id'), 'process_id': status.get('process_id'),
                    'action_session': status.get('client_action', {}).get('action_session')}
        if (identity != self.bridge_identity or type(status.get('process_id')) is not int
                or status.get('in_world') is not True
                or status.get('client_action', {}).get('status') not in ('idle', 'succeeded', 'failed', 'cancelled')):
            raise ValueError('menu_recovery_context_changed')
        self.check_menu_recovery(command)  # A queued owner can change during a read.
        if status.get('held_mappings') != []:
            raise ValueError('menu_recovery_inputs_not_released')
        state = self.bridge.request('GET', '/control/state?radius=8')
        self.check_menu_recovery(command)
        if (not isinstance(state, dict)
                or any(not isinstance(state.get(k), dict) for k in ('world', 'player', 'client_action'))):
            raise ValueError('menu_recovery_state_unconfirmed')
        actual = (state.get('world', {}).get('world_generation'), state.get('player', {}).get('uuid'),
                  state.get('client_action', {}).get('action_session'))
        expected = tuple(context[k] for k in ('world_generation', 'player_uuid', 'action_session'))
        tick = state.get('world', {}).get('game_time')
        player = state.get('player', {})
        if (actual != expected or type(tick) is not int or tick < context['game_time']
                or type(state.get('paused')) is not bool or state['paused'] != context['paused']
                or state.get('screen_open') is not True or player.get('alive') is not True
                or type(player.get('health')) not in (int, float) or not math.isfinite(player['health']) or player['health'] <= 0
                or state.get('client_action', {}).get('status') not in ('idle', 'succeeded', 'failed', 'cancelled')):
            raise ValueError('menu_recovery_observation_changed')
        self.check_menu_recovery(command)  # Final bounded age and local ownership before the only POST.
        result = self.bridge.request('POST', '/control/raw-key', command['body'])
        if not isinstance(result, dict) or result.get('ok') is not True:
            raise BridgeError('menu_recovery_response_unconfirmed', uncertain=True)
        policy = self.observation_policy()
        self.finish(command, 'succeeded', reason='menu_recovery_dispatched', result=result,
                    resident_policy=policy, requires_handoff=policy['requires_handoff'], gameplay_effect_confirmed=False)

    def command(self, command):
        if 'observation_clock' in command and (command.get('op') != 'observe'
                or command['observation_clock'] != 'client-pre-tick-v1'
                or command.get('capability_observation') is not True
                or any(k in command for k in ('capability_survey','coordination_step','frame'))):
            raise ValueError('read_only_observation_command_forbidden')
        if getattr(self, '_terrain_acquisition_unknown', None) is not None:
            from .terrain_acquisition import closure_command
            if closure_command(self, command):
                return
        validate_encounter_command(command)  # Reject before any read, cancellation or takeover.
        operation = command.get('op')
        if operation == 'capability_cancel_exact':
            self.capability_cancel_exact(command)
            return
        check_coordination(command, self)  # Before generic owner takeover.
        if operation in ('coordination_status', 'coordination_cancel'):
            getattr(self, operation)(command)
            return
        if 'watchdog_menu_recovery' in command:
            self.recover_menu(command)
            return
        if 'watchdog_observation_fallback' in command:
            if (operation != 'cancel' or command['watchdog_observation_fallback'] is not True
                    or command.get('expected_resident_session') != self.session_id):
                raise ValueError('invalid_watchdog_observation_fallback')
            policy = self.observation_policy()
            if policy['requires_handoff'] or policy['input_release_unconfirmed']:
                raise ValueError('resident_policy_blocks_automatic_release')
        # A new explicit owner command wins over automatic combat. Stop only
        # combat-owned holds, then let the existing direct/task path run once.
        if operation in ({'direct', 'cancel', 'shutdown', 'aim_lock', 'aim_unlock'} | TASKS):
            if self.combat.active or self.combat.held:
                self.combat.stop(self, 'explicit_' + str(operation), release=False)
                self.check_identity(self.bridge.request('GET', '/control/status'))
                self.combat.stop(self, 'explicit_' + str(operation))
                if self.combat.held:
                    if operation == 'direct':
                        # An uncertain old up must not later release a newer
                        # owner down. Finish the explicit takeover first.
                        result = self.bridge.request('POST', '/control/release-all', {})
                        if result.get('ok') is not True:
                            raise BridgeError('combat_input_release_unconfirmed', uncertain=True)
                        self.combat.confirm_released()
                    elif operation not in ('cancel', 'shutdown'):
                        raise BridgeError('combat_input_release_unconfirmed', uncertain=True)
        if operation == 'encounter_pause':
            self.encounter_pause(command)
        elif operation == 'observe':
            self.publish()  # Current policy is visible even if the following native read blocks.
            self.finish(command, 'succeeded', result=self.snapshot(command))
        elif operation in SCAN_OPS:
            self.scan_command(command)
        elif operation == 'combat_start':
            if self.paused:
                raise ValueError(self.reason or 'controller_paused')
            if self.active or self.pending:
                raise ValueError('combat_requires_idle_task_queue')
            if self.combat.active:
                raise ValueError('combat_already_active_stop_first')
            if self.combat.held:
                raise ValueError('combat_inputs_unreleased_use_cancel')
            self.check_identity(self.bridge.request('GET', '/control/status'))
            radius = command.get('radius', 12)
            if type(radius) is not int or not 1 <= radius <= 32:
                raise ValueError('combat_radius_1_to_32')
            started = time.monotonic()
            state = self.bridge.request('GET', f'/control/state?radius={max(5, radius)}')
            combat = self.combat.prepare(command, state)
            aim = EntityAimLock()
            aim.start({'target_uuid': combat.target_uuid, 'radius': combat.radius}, state,
                      self.bridge_identity['action_session'])
            if time.monotonic() - started > MAX_SAMPLE_SECONDS:
                raise ValueError('stale_combat_observation')
            # Starting automatic combat explicitly takes input ownership. Clear
            # preexisting direct attack/use/movement once before acquiring it.
            released = self.bridge.request('POST', '/control/release-all', {})
            if released.get('ok') is not True:
                raise BridgeError('combat_input_response_invalid', uncertain=True)
            self.combat, self.aim = combat, aim
            self.apply_aim(state, started)
            self.finish(command, 'succeeded', reason='combat_started', result=self.combat.status(),
                        gameplay_effect_confirmed=False)
        elif operation == 'combat_stop':
            self.combat.stop(self, 'combat_stop_requested', release=False)
            self.check_identity(self.bridge.request('GET', '/control/status'))
            result = self.combat.stop(self, 'combat_stop_requested')
            if self.combat.held:
                raise BridgeError('combat_input_release_unconfirmed', uncertain=True)
            self.finish(command, 'succeeded', result=result)
        elif operation == 'aim_lock':
            if self.paused:
                raise ValueError(self.reason or 'controller_paused')
            if self.active or self.pending:
                raise ValueError('action_owns_view_cancel_task_first')
            self.check_identity(self.bridge.request('GET', '/control/status'))
            radius = command.get('radius', 16)
            if type(radius) is not int or not 1 <= radius <= 32:
                raise ValueError('aim_radius_1_to_32')
            started = time.monotonic()
            state = self.bridge.request('GET', f'/control/state?radius={radius}')
            self.aim.start(command, state, self.bridge_identity['action_session'])
            self.apply_aim(state, started)
            self.finish(command, 'succeeded', reason='aim_lock_started', result=self.aim.status(),
                        gameplay_effect_confirmed=False)
        elif operation == 'aim_unlock':
            self.finish(command, 'succeeded', result=self.aim.release('unlock_requested'))
        elif operation == 'direct':
            endpoint, body = command.get('endpoint'), command.get('body')
            if endpoint not in DIRECT or not isinstance(body, dict):
                raise ValueError('invalid_direct_command')
            self.check_identity(self.bridge.request('GET', '/control/status'))
            if endpoint in ('look', 'release-all'):
                self.aim.release('manual_look' if endpoint == 'look' else 'inputs_released')
            self.interrupt_local('direct_takeover')
            result = self.bridge.request('POST', '/control/' + endpoint, body)
            if endpoint == 'release-all' and result.get('ok') is True:
                self.combat.confirm_released()
            self.paused, self.reason = False, None
            self.finish(command, 'succeeded', reason='direct_input_dispatched', result=result,
                        gameplay_effect_confirmed=False)
        elif operation == 'cancel':
            self.aim.release('cancel_requested')
            status = self.bridge.request('GET', '/control/status')
            self.check_identity(status)
            if getattr(self, '_terrain_acquisition_unknown', None) is not None:
                from .terrain_acquisition import validate_shutdown
                validate_shutdown(self, command, status)
            self.interrupt_local('cancel_requested')
            # Explicit cancel is release-all, including held direct keys. It never leaves a game.
            result = self.bridge.request('POST', '/control/release-all', {})
            if result.get('ok') is True:
                self.combat.confirm_released()
            self.paused, self.reason = False, None
            self.finish(command, 'succeeded', result=result)
        elif operation == 'resume':
            if self.active is not None and self.active.capability_unknown:
                raise ValueError('scoped_original_requires_operator_reconciliation')
            if (self.paused and (self.reason in ('encounter_pause_requested', 'encounter_pause_unknown')
                    or self.reason == 'input_release_unconfirmed'
                    and getattr(self.active, 'encounter_request', None) is not None)
                    and (self.active or self.pending)):
                raise ValueError('encounter_pause_original_unresolved')
            self.check_identity(self.bridge.request('GET', '/control/status'))
            result = self.bridge.request('GET', '/control/action/status')
            if result.get('status') == 'running':
                raise ValueError('action_still_running_observe_or_cancel')
            self.paused, self.reason = False, None
            self.finish(command, 'succeeded', reason='ready_for_new_requests_no_replay')
        elif operation == 'shutdown':
            self.command({**command, 'op': 'cancel'})
            self.running = False
        elif operation in TASKS:
            if self.paused:
                raise ValueError(self.reason or 'controller_paused')
            if len(self.pending) >= MAX_PENDING:
                raise ValueError('queue_full')
            self.aim.release('semantic_task_owns_view')
            self.pending.append(command)
        else:
            raise ValueError('unknown_operation')

    def coordination_policy_fields(self):
        policy = self.observation_policy()
        return {'resident_policy': policy, 'requires_handoff': (not isinstance(policy, dict)
                or policy.get('requires_handoff') is not False)}

    def coordination_not_admitted(self, command, reason):
        e = command.get('_coordination')
        e = e if isinstance(e, dict) else {}
        return {'schema_version': 1, 'admitted': False, 'uncertain': False,
                'request_id': command.get('request_id'), 'resident_session': self.session_id,
                'native_action_id': e.get('native_action_id'), 'action_session': e.get('action_session'),
                'source_id': e.get('source_id'), 'reason': reason}

    def coordination_identity(self, status):
        """Restricted reads never invoke check_identity's generic owner cleanup."""
        if (type(status) is not dict or type(status.get('client_action')) is not dict
                or status.get('protocol') != 'mineclient-bridge'
                or type(status.get('schema_version')) is not int or status['schema_version'] != 2
                or type(status.get('process_id')) is not int or status.get('in_world') is not True):
            raise ValueError('coordination_status_identity_changed')
        actual = {'run_id': status.get('run_id'), 'process_id': status['process_id'],
                  'action_session': status['client_action'].get('action_session')}
        if actual != self.bridge_identity:
            raise ValueError('coordination_status_identity_changed')

    def coordination_context(self):
        # Check both identities and contents: a later owner must survive a narrow
        # read error, including changes injected while the native read blocks.
        task = self.active
        return (self.session_id, deepcopy(self.bridge_identity), id(task),
                deepcopy(task.command) if task else None, task.action_id if task else None,
                tuple((id(p), deepcopy(p)) for p in self.pending), self.paused, self.reason,
                deepcopy(self.observation_policy()), deepcopy(self.aim.status()),
                deepcopy(self.combat.status()))

    def coordination_context_unchanged(self, context):
        if self.coordination_context() != context:
            raise ValueError('coordination_owner_or_policy_changed')

    def coordination_exact_request(self, command):
        required = {'op', 'expected_request_id', 'expected_action_id', 'expected_action_session',
                    'expected_resident_session', 'request_id', 'session_id', 'submitted_at'}
        if (set(command) != required or command['expected_resident_session'] != self.session_id
                or command['session_id'] != self.session_id
                or command['expected_action_session'] != (self.bridge_identity or {}).get('action_session')
                or type(command['expected_request_id']) is not str
                or not ID.fullmatch(command['expected_request_id'])
                or native_action_id(self.session_id, command['expected_request_id']) != command['expected_action_id']):
            raise ValueError('coordination_exact_identity_changed')
        policy = self.observation_policy()
        if (type(policy) is not dict or type(policy.get('schema_version')) is not int
                or policy['schema_version'] != 1 or type(policy.get('requires_handoff')) is not bool
                or type(policy.get('input_release_unconfirmed')) is not bool):
            raise ValueError('coordination_policy_unconfirmed')
        target = command['expected_request_id']
        action_id = command['expected_action_id']
        if self.aim.active or self.combat.active or self.combat.held:
            raise ValueError('coordination_foreign_owner')
        for task_command in ([self.active.command] if self.active else []) + list(self.pending):
            e = task_command.get('_coordination')
            if (not isinstance(e, dict) or task_command.get('request_id') != target
                    or e.get('native_action_id') != action_id
                    or e.get('action_session') != command['expected_action_session']):
                raise ValueError('coordination_foreign_owner')
        return self.coordination_context()

    def coordination_exact_read(self, command):
        context = self.coordination_exact_request(command)
        status = self.bridge.request('GET', '/control/status')
        self.coordination_identity(status)
        native = status['client_action']
        if native.get('status') == 'running' and native.get('action_id') != command['expected_action_id']:
            raise ValueError('coordination_foreign_native_owner')
        self.coordination_context_unchanged(context)
        self.coordination_exact_request(command)
        return context

    def coordination_status(self, command):
        context = self.coordination_exact_read(command)
        result = self.bridge.request('GET', '/control/action/status?action_id=' + quote(command['expected_action_id'], safe=''))
        self.coordination_context_unchanged(context)
        if (type(result) is not dict or type(result.get('action_schema_version')) is not int
                or result['action_schema_version'] != 1
                or result.get('action_id') != command['expected_action_id']
                or result.get('action_session') != command['expected_action_session']
                or result.get('status') not in TERMINAL | {'running'}):
            raise ValueError('coordination_status_identity_changed')
        if self.active is not None:
            self.coordination_receipt(self.active, result)
        else:
            self.coordination_known_outcome(result)
        self.finish(command, 'succeeded', result=result,
                    coordination_status={'request_id': command['expected_request_id'],
                                         'action_id': command['expected_action_id'],
                                         'action_session': command['expected_action_session']},
                    **self.coordination_policy_fields())

    def end_coordination(self, task, status, **fields):
        """Only finish this request; neither new owners nor foreign pending work."""
        if not task.coordination_result_published:
            self.finish(task.command, status, **fields, **self.coordination_policy_fields())
            task.coordination_result_published = True
        if self.active is task:
            self.active = None
        self.publish()

    def coordination_receipt(self, task, result, *, terminal=False):
        e = task.command['_coordination']
        payload = result.get('result') if isinstance(result, dict) else None
        if (type(result) is not dict or type(result.get('action_schema_version')) is not int
                or result['action_schema_version'] != 1
                or result.get('action_id') != e['native_action_id']
                or result.get('action_session') != e['action_session']
                or result.get('action') != task.command['action']
                or type(payload) is not dict or payload.get('world_generation') != e['world_generation']
                or type(payload.get('coordination_step_schema_version')) is not int
                or payload['coordination_step_schema_version'] != 1
                or result.get('status') not in (TERMINAL if terminal else TERMINAL | {'running'})):
            raise BridgeError('coordination_action_receipt_invalid', uncertain=True)
        self.coordination_known_outcome(result)
        try:
            validate_encounter_receipt(result, task.encounter_request)
        except (ValueError, KeyError, TypeError):
            raise BridgeError('coordination_action_receipt_invalid', uncertain=True) from None
        return result

    def coordination_known_outcome(self, result):
        if any(result.get(key, False) is not False
               for key in ('unknown_outcome', 'uncertain', 'post_uncertain')):
            error = BridgeError('coordination_action_outcome_unconfirmed', uncertain=True)
            error.coordination_raw_receipt = deepcopy(result)
            raise error

    def coordination_latch_release(self):
        self.paused, self.reason = True, 'input_release_unconfirmed'
        self.publish()

    def capability_cancel_exact(self, command):
        """No release-all, takeover, or retry; one bound native cancellation only."""
        fields = {'op', 'expected_request_id', 'expected_resident_session', 'expected_action_session', 'expected_action_id'}
        metadata = {'request_id', 'session_id', 'submitted_at'}
        if (set(command) - metadata != fields or command['expected_resident_session'] != self.session_id
                or command['expected_action_session'] != (self.bridge_identity or {}).get('action_session')
                or not ID.fullmatch(command['expected_request_id'])
                or command['expected_action_id'] != uuid.uuid5(uuid.UUID(self.session_id), command['expected_request_id'] + ':1').hex):
            raise ValueError('exact_cancel_identity_mismatch')
        policy = self.observation_policy()
        if policy['requires_handoff'] or policy['input_release_unconfirmed']:
            raise ValueError('exact_cancel_unknown_owner')
        target = command['expected_request_id']
        pending = next((p for p in self.pending if p['request_id'] == target), None)
        if pending is not None:
            if not isinstance(pending.get('capability_guard'), dict) or self.active is not None:
                raise ValueError('exact_cancel_foreign_pending_owner')
            self.pending.remove(pending)
            proof = {'schema_version': 1, 'original_request_id': target, 'admitted': False,
                     'input_release_confirmed': True, 'reason': 'cancelled_before_native_dispatch'}
            self.finish(pending, 'cancelled', reason=proof['reason'], exact_cancel=proof,
                        gameplay_effect_confirmed=False, action=None, action_id=None, cancellation=None)
            self.finish(command, 'succeeded', exact_cancel=proof)
            return
        task = self.active
        if (task is None or task.command.get('request_id') != target
                or not isinstance(task.command.get('capability_guard'), dict)
                or task.step_number != 1
                or (task.action_id or (task.last_action_result or {}).get('action_id')) != command['expected_action_id']):
            raise ValueError('exact_cancel_target_not_active')
        if task.capability_cancel_attempted:
            raise ValueError('exact_cancel_already_attempted')
        # Commit attempt before side effects; an ambiguous receipt leaves the task frozen.
        task.capability_cancel_attempted = True
        try:
            if task.action_id is None:
                terminal = task.last_action_result
            else:
                terminal = self.bridge.request('POST', '/control/action/cancel',
                    {'action_id': command['expected_action_id'],
                     'expected_action_session': command['expected_action_session']})
            if (not isinstance(terminal, dict) or terminal.get('action_id') != command['expected_action_id']
                    or terminal.get('action_session') != command['expected_action_session']
                    or terminal.get('action_schema_version') != 1 or terminal.get('status') not in TERMINAL
                    or native_release_unconfirmed(terminal) or native_handoff_required(terminal)
                    or terminal.get('result', {}).get('input_release_confirmed') is not True):
                raise BridgeError('exact_cancel_release_unconfirmed', uncertain=True)
        except (BridgeError, ValueError, KeyError, TypeError):
            self.paused, self.reason = True, 'input_release_unconfirmed'
            self.publish()
            raise
        task.last_action_result = terminal
        proof = {'schema_version': 1, 'original_request_id': target, 'action_id': command['expected_action_id'],
                 'action_session': command['expected_action_session'], 'admitted': True,
                 'input_release_confirmed': True, 'native_status': terminal['status']}
        self.end_active(terminal['status'], reason=terminal.get('reason', terminal['status']), action=terminal,
                        exact_cancel=proof, postcondition_observed=False)
        self.finish(command, 'succeeded', exact_cancel=proof, result=terminal)

    def coordination_cancel_once(self, task):
        if task.coordination_cancel_attempted:
            return self.bridge.request('GET', '/control/action/status?action_id=' + quote(task.action_id, safe=''))
        # Commit before the side effect. Unknown completion never permits retry.
        task.coordination_cancel_attempted = True
        return self.bridge.request('POST', '/control/action/cancel',
            {'action_id': task.action_id,
             'expected_action_session': task.command['_coordination']['action_session']})

    def coordination_cancel(self, command):
        context = self.coordination_exact_read(command)
        target = command['expected_request_id']
        pending = next((p for p in self.pending if p['request_id'] == target), None)
        if pending is not None:
            self.pending.remove(pending)
            evidence = self.coordination_not_admitted(pending, 'cancelled_before_native_dispatch')
            self.finish(pending, 'cancelled', reason='cancelled_before_native_dispatch',
                        coordination_admission=evidence, **self.coordination_policy_fields())
            self.finish(command, 'succeeded', coordination_admission=evidence, **self.coordination_policy_fields())
            return
        task = self.active
        if task is None or task.action_id != command['expected_action_id']:
            raise ValueError('coordination_cancel_target_not_active')
        try:
            result = self.coordination_cancel_once(task)
            self.coordination_context_unchanged(context)
            terminal = self.coordination_receipt(task, result, terminal=True)
            if (native_release_unconfirmed(terminal)
                    or terminal['result'].get('input_release_confirmed') is not True):
                error = BridgeError('coordination_cancel_release_unconfirmed', uncertain=True)
                error.coordination_raw_receipt = deepcopy(terminal)
                raise error
        except (BridgeError, ValueError, KeyError, TypeError):
            task.coordination_unknown = True
            if self.coordination_context() == context:
                self.coordination_latch_release()
            raise
        task.last_action_result = terminal
        if native_handoff_required(terminal) and self.reason != 'input_release_unconfirmed':
            self.paused, self.reason = True, 'encounter_requires_handoff'
        self.end_coordination(task, terminal['status'], action=terminal, postcondition_observed=False)
        self.finish(command, 'succeeded', result=terminal, **self.coordination_policy_fields())

    def accept_coordination_status(self, task, result):
        result = self.coordination_receipt(task, result)
        task.last_action_result = result
        if result['status'] == 'running':
            return False
        if (native_release_unconfirmed(result)
                or result['result'].get('input_release_confirmed') is not True):
            self.coordination_latch_release()
            self.end_coordination(task, 'failed', reason='input_release_unconfirmed', action=result)
            return True
        if native_handoff_required(result) and self.reason != 'input_release_unconfirmed':
            self.paused, self.reason = True, 'encounter_requires_handoff'
        if task.coordination_unknown or result['status'] != 'succeeded':
            self.end_coordination(task, result['status'], reason=result.get('reason', result['status']), action=result)
            return True
        task.action_id = None
        task.response = result
        return False

    def observe_recipe_step(self, step):
        """Bounded per-step entity window; legacy recipes retain radius 8."""
        options = {}
        if 'entity_radius' in step:
            radius = step['entity_radius']
            if type(radius) is not int or not 1 <= radius <= 128:
                raise ValueError('entity_radius_1_to_128')
            options['entity_radius'] = radius
        return self.cache.observe(self.bridge, **options)

    def advance_coordination(self, task):
        if time.monotonic() < task.wake_at:
            return
        sending_action = False
        context = self.coordination_context()
        try:
            if task.action_id:
                result = self.bridge.request('GET', '/control/action/status?action_id=' + quote(task.action_id, safe=''))
                self.coordination_context_unchanged(context)
                if self.accept_coordination_status(task, result):
                    return
                if task.action_id:
                    task.wake_at = time.monotonic() + .2
                    return
            step = task.recipe.send(task.response)
            task.response = None
            if step['step'] == 'action':
                check_coordination(task.command, self, before_post=True, task=task)
                if task.step_number != 0:
                    raise ValueError('coordination_single_step_required')
                task.encounter_request = validate_encounter_request(step['body'])
                task.step_number = 1
                action_id = native_action_id(self.session_id, task.command['request_id'])
                if task.command['_coordination']['native_action_id'] != action_id:
                    raise ValueError('coordination_native_identity_changed')
                task.action_id = action_id
                sending_action = True
                try:
                    result = self.bridge.request('POST', '/control/action', {**step['body'], 'action_id': action_id})
                finally:
                    # Diagnostic copy of this exchange, before any cancel/read
                    # replaces bridge metadata. Never binding or retry authority.
                    task.coordination_post_metadata = deepcopy(getattr(self.bridge, 'last_response_metadata', None))
                # The action id above is our own transition; guard other changes.
                post_context = list(context); post_context[4] = action_id
                self.coordination_context_unchanged(tuple(post_context))
                if self.accept_coordination_status(task, result):
                    return
                task.wake_at = time.monotonic() + .1
            elif step['step'] == 'observe':
                task.response = self.observe_recipe_step(step)
            elif step['step'] == 'wait':
                task.wake_at = time.monotonic() + step['seconds']
            else:
                raise ValueError('invalid_recipe_step')
        except StopIteration as done:
            self.end_coordination(task, 'succeeded', result=done.value)
        except (BridgeError, ValueError, KeyError, TypeError) as exc:
            reason = safe_reason(exc)
            expected_context = list(context)
            expected_context[4] = task.action_id
            context_changed = self.coordination_context() != tuple(expected_context)
            definite = (sending_action and isinstance(exc, BridgeError) and not exc.uncertain
                        and exc.status is not None and 400 <= exc.status < 500)
            fields = {}
            if hasattr(exc, 'coordination_raw_receipt'):
                fields['unconfirmed_action'] = exc.coordination_raw_receipt
            if definite and exc.status == 409 and exc.code in NAVIGATION_REJECTIONS:
                self.cache.native_binding.seen = True
            if definite:
                fields['action_admission'] = action_rejection_admission(exc)
                task.action_id = None
            uncertain = task.action_id is not None or isinstance(exc, BridgeError) and exc.uncertain
            if not uncertain and task.last_action_result is None:
                fields['coordination_admission'] = self.coordination_not_admitted(task.command, reason)
                self.end_coordination(task, 'failed', reason=reason, action_id=None, action=None, **fields)
                return
            # A race never licenses cleanup of a new owner. Once cancellation was
            # attempted, every subsequent failure is a read-only unresolved state.
            if (task.coordination_cancel_attempted or context_changed or self.pending
                    or self.aim.active or self.combat.active or self.combat.held):
                task.coordination_unknown = True
                task.wake_at = time.monotonic() + .2
                return
            cancel = None
            resolved = None
            cancel_context = self.coordination_context()
            if task.action_id and self.active is task:
                try:
                    cancel = self.coordination_cancel_once(task)
                    self.coordination_context_unchanged(cancel_context)
                    resolved = self.coordination_receipt(task, cancel, terminal=True)
                except (BridgeError, ValueError, KeyError, TypeError):
                    if cancel is None:
                        cancel = {'status': 'unconfirmed'}
            elif task.last_action_result is not None:
                try:
                    resolved = self.coordination_receipt(task, task.last_action_result, terminal=True)
                except (BridgeError, ValueError, KeyError, TypeError):
                    pass
            task.coordination_unknown = True
            released = (resolved is not None and not native_release_unconfirmed(resolved)
                        and resolved['result'].get('input_release_confirmed') is True)
            if self.coordination_context() == cancel_context:
                if not released:
                    self.coordination_latch_release()
                elif uncertain and not self.paused:
                    self.paused, self.reason = True, 'uncertain_request_observe_then_resume'
            fields.update(action_id=task.action_id, action=task.last_action_result, cancellation=cancel,
                          resolved_action=resolved, task_completed=False,
                          action_outcome=resolved['status'] if resolved else 'unresolved')
            if uncertain:
                fields['action_request_diagnostics'] = {'schema_version': 1, 'diagnostics_only': True,
                    'post_action': {'response_metadata': deepcopy(task.coordination_post_metadata)}}
            if not task.coordination_result_published:
                self.finish(task.command, 'uncertain' if uncertain else 'failed', reason=reason,
                            **fields, **self.coordination_policy_fields())
                task.coordination_result_published = True
            if released:
                if self.active is task:
                    self.active = None
            task.wake_at = time.monotonic() + .2

    def scan_command(self, command):
        operation = command['op']
        body = start_body(command) if operation == 'scan_start' else {'id': scan_id(command)}
        self.check_identity(self.bridge.request('GET', '/control/status'))
        if operation == 'scan_status':
            response = self.bridge.request('GET', '/control/scan/status?id=' + quote(body['id'], safe=''))
        else:
            response = self.bridge.request('POST', '/control/scan' + ('/cancel' if operation == 'scan_cancel' else ''), body)
        try:
            validate_scan(response, body['id'])
        except (ValueError, KeyError, TypeError):
            # A POST might have been admitted. Report uncertainty, never replay.
            raise BridgeError('invalid_scan_response', uncertain=operation != 'scan_status') from None
        retained = self.prospecting.record(response)
        self.finish(command, 'succeeded', scan_id=body['id'], result=response,
                    scan_cache={**self.prospecting.summary(), 'result_retained': retained})

    def read_commands(self):
        paths = list((self.root / 'inbox').glob('*.json'))
        # File mtime is only ordering within the mailbox, not cross-namespace process evidence.
        paths.sort(key=lambda p: (p.stat().st_mtime_ns, p.name))
        commands = []
        for path in paths[:MAX_PENDING * 2]:
            destination = self.root / 'working' / path.name
            os.replace(path, destination)  # Claim before any side effect.
            command = {'request_id': path.stem}
            try:
                command = read_json(destination)
                if command.get('request_id') != path.stem or not ID.fullmatch(path.stem):
                    raise ValueError('invalid_request_id')
                if command.get('session_id') != self.session_id:
                    raise ValueError('stale_controller_session_not_replayed')
                if (self.root / 'results' / path.name).exists():
                    destination.unlink(missing_ok=True)
                    continue
                if path.stem in self.seen:
                    self.finish(command, 'failed', reason='request_id_already_consumed_result_expired')
                    continue
                self.seen.add(path.stem)
                commands.append(command)
            except Exception:
                self.finish({'request_id': path.stem}, 'failed', reason='invalid_or_stale_command')
        # Direct/cancel commands preempt tasks already admitted this turn too.
        for command in commands:
            if not self.running:
                self.finish(command, 'cancelled', reason='controller_stopped')
                continue
            try:
                self.command(command)
            except (BridgeError, ValueError, KeyError, TypeError) as exc:
                self.command_error(command, exc)
        if commands:
            self.publish()

    def encounter_pause(self, command):
        body = pause_body(command, self.session_id, (self.bridge_identity or {}).get('action_session'))
        task = self.active
        if self.aim.active or self.combat.active or self.combat.held:
            raise ValueError('encounter_pause_foreign_automatic_owner')
        for pending in self.pending:
            planned_id = uuid.uuid5(uuid.UUID(self.session_id), pending['request_id'] + ':1').hex
            if (planned_id != body['expected_action_id'] or validate_encounter_command(pending) is None):
                raise ValueError('encounter_pause_foreign_pending_work')
        if task is not None:
            owner = task.action_id or (task.last_action_result or {}).get('action_id')
            if (owner != body['expected_action_id'] or task.encounter_request is None
                    or task.command.get('op') != 'action'):
                raise ValueError('encounter_pause_foreign_resident_owner')
        # No preliminary GET, input takeover, or original-result publication on this path.
        prior_release_unconfirmed = self.observation_policy()['input_release_unconfirmed']
        self.paused, self.reason = True, ('input_release_unconfirmed' if prior_release_unconfirmed
                                          else 'encounter_pause_requested')
        self.publish()  # Preserve the current policy while the single pause POST is pending.
        value = self.bridge.request('POST', '/control/pause', body)
        try:
            value = validate_pause_receipt(value, body, task.encounter_request if task else None)
        except (ValueError, KeyError, TypeError, AttributeError):
            raise BridgeError('encounter_pause_response_invalid', uncertain=True) from None
        self.paused, self.reason = True, ('input_release_unconfirmed'
            if prior_release_unconfirmed or value['input_release_confirmed'] is False
            else 'encounter_pause_requested')
        self.finish(command, 'succeeded', reason='native_pause_screen_installed', result=value,
                    gameplay_effect_confirmed=False, risk_remaining=True,
                    requires_handoff=True, safety_assured=False)
        # A matching undispatched pending command stays held; resume refuses it.
        # Retain the original task. The next advance performs only a bound read,
        # not a cancel/retry or a multi-step recipe transition.

    def reconcile_paused_encounter(self):
        task = self.active
        if task is None or task.encounter_request is None or time.monotonic() < task.wake_at:
            return
        action_id = task.action_id or (task.last_action_result or {}).get('action_id')
        if not action_id:
            return
        task.wake_at = time.monotonic() + 0.2
        try:
            value = self.bridge.request('GET', '/control/action/status?action_id=' + quote(action_id, safe=''))
            terminal = self.resolved_encounter_terminal(task, value)
            if terminal is None:
                return
            if native_release_unconfirmed(terminal):
                self.paused, self.reason = True, 'input_release_unconfirmed'
                self.discard_pending('input_release_unconfirmed')
                self.end_active('failed', reason='input_release_unconfirmed', action=terminal)
                return
            if terminal['status'] == 'succeeded':
                # Preserve the ordinary basic-action result shape using only a read.
                state = self.cache.observe(self.bridge)
                self.end_active('succeeded', result={'action': terminal, 'state': state,
                                                      'server_confirmed': False,
                                                      'evidence': {'level': 'client_observed', 'stable': False,
                                                          'later_state_game_time': state.get('world', {}).get('game_time')}})
            else:
                self.end_active(terminal['status'], reason=terminal['reason'], action=terminal)
        except (BridgeError, ValueError, KeyError, TypeError):
            # Unknown remains pending; neither this read nor an acknowledgement
            # licenses another POST or rewriting an earlier uncertain envelope.
            return

    def command_error(self, command, exc):
        uncertain = isinstance(exc, BridgeError) and exc.uncertain
        reason = safe_reason(exc)
        if command.get('op') == 'capability_cancel_exact':
            self.finish(command, 'uncertain' if uncertain else 'failed', reason=reason,
                        resident_policy=self.observation_policy())
            return
        if 'terrain_acquisition' in command or getattr(self, '_terrain_acquisition_unknown', None) is not None:
            # Acquisition owns sampling admission, never gameplay inputs. Its
            # uncertainty must not invoke the generic combat/aim cleanup below.
            fields = {'resident_policy': self.observation_policy()}
            if hasattr(exc, 'terrain_read_diagnostics'):
                fields['terrain_read'] = exc.terrain_read_diagnostics
            if getattr(self, '_terrain_acquisition_unknown', None) is not None:
                fields['terrain_acquisition_unknown'] = deepcopy(self._terrain_acquisition_unknown)
            self.finish(command, 'uncertain' if uncertain else 'failed', reason=reason, **fields)
            return
        if '_coordination' in command or command.get('op') in ('coordination_status', 'coordination_cancel'):
            fields = self.coordination_policy_fields()
            if hasattr(exc, 'coordination_raw_receipt'):
                fields['unconfirmed_action'] = exc.coordination_raw_receipt
            if '_coordination' in command and not uncertain:
                fields['coordination_admission'] = self.coordination_not_admitted(command, reason)
            self.finish(command, 'uncertain' if uncertain else 'failed', reason=reason, **fields)
            return
        if 'watchdog_menu_recovery' in command:
            # This narrow recovery request cannot take over an owner even on its
            # error path. Preserve current policy and the original pending work.
            policy = self.observation_policy()
            self.finish(command, 'uncertain' if uncertain else 'failed', reason=reason,
                        resident_policy=policy, requires_handoff=policy['requires_handoff'])
            return
        if command.get('op') == 'encounter_pause':
            if uncertain and self.reason != 'input_release_unconfirmed':
                self.paused, self.reason = True, 'encounter_pause_unknown'
            self.finish(command, 'uncertain' if uncertain else 'failed', reason=reason,
                        risk_remaining=True, requires_handoff=True, safety_assured=False)
            return
        policy = self.observation_policy()
        if ((command.get('op') == 'observe' or command.get('watchdog_observation_fallback') is True)
                and (policy['requires_handoff'] or policy['input_release_unconfirmed'])):
            fields = {'resident_policy': policy, 'requires_handoff': policy['requires_handoff']}
            if hasattr(exc, 'terrain_read_diagnostics'):
                fields['terrain_read'] = exc.terrain_read_diagnostics
            # Read failure cannot release inputs, change the owner/reason, or consume its task.
            self.finish(command, 'uncertain' if uncertain else 'failed', reason=reason, **fields)
            return
        if command.get('op') in SCAN_OPS:
            # Scanning owns no gameplay inputs. Even an ambiguous scan POST must
            # not stop combat/aim, release keys, or discard semantic tasks.
            fields = {}
            try:
                fields['scan_id'] = scan_id(command)
            except ValueError:
                pass
            self.finish(command, 'uncertain' if uncertain else 'failed', reason=reason, **fields)
            return
        if (command.get('op') == 'combat_start' and self.combat.request_id == command.get('request_id')) or uncertain:
            self.combat.stop(self, reason)
        if command.get('op') == 'aim_lock' or uncertain:
            self.aim.release(reason)
        if uncertain:
            self.paused, self.reason = True, 'uncertain_request_observe_then_resume'
            self.discard_pending('uncertain_request')
        elif self.combat.held and not self.combat.active:
            self.paused, self.reason = True, 'combat_input_release_unconfirmed'
        fields = {}
        if hasattr(exc, 'terrain_read_diagnostics'):
            fields['terrain_read'] = exc.terrain_read_diagnostics
        self.finish(command, 'uncertain' if uncertain else 'failed', reason=reason, **fields)

    def apply_aim(self, state, started):
        if time.monotonic() - started > MAX_SAMPLE_SECONDS:
            raise ValueError('stale_aim_observation')
        body = self.aim.prepare(state, self.bridge_identity['action_session'])
        # Guarded look updates only the view. No key release, task takeover or retry.
        result = self.bridge.request('POST', '/control/look', body)
        try:
            self.aim.accepted(result)
        except (ValueError, KeyError, TypeError):
            # The write may already have applied; an invalid acknowledgement is not a rejection.
            raise BridgeError('aim_update_response_invalid', uncertain=True) from None

    def advance_aim(self):
        if not self.aim.active:
            return
        if self.paused or self.active or self.pending:
            self.aim.release('controller_paused' if self.paused else 'semantic_task_owns_view')
            self.publish()
            return
        if time.monotonic() < self.aim.next_update:
            return
        try:
            started = time.monotonic()
            state = self.bridge.request('GET', f'/control/state?radius={self.aim.radius}')
            self.apply_aim(state, started)
        except (BridgeError, ValueError, KeyError, TypeError) as exc:
            self.aim.release(safe_reason(exc))
            if isinstance(exc, BridgeError) and exc.uncertain:
                self.paused, self.reason = True, 'uncertain_aim_update_no_retry'
                self.discard_pending('uncertain_request')
            self.publish()

    def advance_combat(self):
        if not self.combat.active:
            return
        try:
            self.combat.advance(self)
            if not self.combat.active and self.combat.held:
                self.paused, self.reason = True, 'combat_input_release_unconfirmed'
                self.publish()
        except (BridgeError, ValueError, KeyError, TypeError) as exc:
            if safe_reason(exc) == 'action_owns_view':
                self.combat.confirm_released()
            self.combat.stop(self, safe_reason(exc), release=safe_reason(exc) != 'bridge_session_changed')
            if (isinstance(exc, BridgeError) and exc.uncertain) or self.combat.held:
                self.paused, self.reason = True, 'uncertain_combat_input_observe_then_resume'
                self.discard_pending('uncertain_request')
            self.publish()

    def advance(self):
        if self.active is not None and '_coordination' in self.active.command:
            self.advance_coordination(self.active)
            return
        if self.paused and (self.reason in ('encounter_pause_requested', 'encounter_pause_unknown')
                or self.reason == 'input_release_unconfirmed'
                and getattr(self.active, 'encounter_request', None) is not None):
            self.reconcile_paused_encounter()
            return
        if self.active is None:
            if not self.pending or self.paused:
                return
            command = self.pending.popleft()
            try:
                if '_coordination' in command:
                    check_coordination(command, self)
                    status = self.bridge.request('GET', '/control/status')
                    self.coordination_identity(status)
                    check_coordination(command, self)
                    self.last_status = status
                    check_coordination(command, self, before_post=True)
                else:
                    self.check_identity(self.bridge.request('GET', '/control/status'))
                self.active = Running(command, make_task({k: v for k, v in command.items() if k != 'scoped_native_preflight'}, self.cache, self.bridge))
            except (BridgeError, ValueError, KeyError, TypeError) as exc:
                self.command_error(command, exc)
                if '_coordination' not in command:
                    self.discard_pending('prior_task_stopped')
                return
        task = self.active
        if task.capability_unknown or task.capability_cancel_attempted and self.paused:
            return
        if '_coordination' in task.command:
            self.advance_coordination(task)
            return
        if time.monotonic() < task.wake_at:
            return
        sending_action = False
        try:
            if task.action_id:
                result = self.bridge.request('GET', '/control/action/status?action_id=' + quote(task.action_id, safe=''))
                self.accept_action_status(task, result)
                if task.action_id:
                    task.wake_at = time.monotonic() + 0.2
                    return
            step = task.recipe.send(task.response)
            task.response = None
            kind = step['step']
            if kind == 'action':
                if self.paused and self.reason == 'encounter_requires_handoff':
                    raise ValueError('encounter_requires_handoff')
                task.encounter_request = validate_encounter_request(step['body'])
                task.step_number += 1
                task.action_id = uuid.uuid5(uuid.UUID(self.session_id), task.command['request_id'] + ':' + str(task.step_number)).hex
                sending_action = True
                if task.encounter_request is not None:
                    self.publish()  # Publish the new bounded owner before a possibly blocking POST.
                if 'scoped_native_preflight' in task.command:
                    result = self.bridge.request('POST', '/control/scoped-action', {
                        'preflight': task.command['scoped_native_preflight'],
                        'intent': {**step['body'], 'action_id': task.action_id}})
                    from .capability_snapshot import validate_scoped_witness
                    validate_scoped_witness(result, task.command['scoped_native_preflight'], task.action_id,
                                            {**step['body'], 'action_id': task.action_id})
                else:
                    result = self.bridge.request('POST', '/control/action', {**step['body'], 'action_id': task.action_id})
                self.accept_action_status(task, result)
                task.wake_at = time.monotonic() + 0.1
            elif kind == 'observe':
                task.response = self.observe_recipe_step(step)
            elif kind == 'wait':
                task.wake_at = time.monotonic() + step['seconds']
            else:
                raise ValueError('invalid_recipe_step')
        except StopIteration as done:
            self.end_active('succeeded', result=done.value)
        except (BridgeError, ValueError, KeyError, TypeError) as exc:
            # This profile can fail after local use/slot-sync hooks have run. HTTP
            # status alone cannot prove admission phase; retain the original ID.
            # No pre-admission proof envelope is currently defined for block-menu-v1.
            block_menu_submission = (sending_action and
                task.command.get('scoped_native_preflight', {}).get('profile') == 'block-menu-v1')
            definite_rejection = (sending_action and not block_menu_submission and isinstance(exc, BridgeError)
                                  and not exc.uncertain and exc.status is not None and 400 <= exc.status < 500)
            admission = {}
            if definite_rejection and exc.status == 409 and exc.code in NAVIGATION_REJECTIONS:
                self.cache.native_binding.seen = True
            if definite_rejection and task.step_number == 1 and task.last_action_result is None:
                admission['action_admission'] = action_rejection_admission(exc)
            if definite_rejection:
                task.action_id = None
            if ('scoped_native_preflight' in task.command and not definite_rejection
                    and (sending_action or task.action_id is not None)):
                # A scoped submit/status/witness ambiguity never authorizes a cancel.
                # Keep the original owner frozen and publish uncertainty exactly once.
                task.capability_unknown = True
                self.paused, self.reason = True, 'input_release_unconfirmed'
                self.finish(task.command, 'uncertain', reason='scoped_original_outcome_unknown:' + safe_reason(exc),
                            action_id=task.action_id, action=task.last_action_result,
                            resident_policy=self.observation_policy(), input_release_unconfirmed=True,
                            unknown_outcome=True)
                self.publish()
                return
            uncertain = isinstance(exc, BridgeError) and (exc.uncertain or task.action_id is not None)
            cancel = None
            if task.action_id:
                # Cancelling an action ID is a different request, never a replay of it.
                try:
                    cancel_body = {'action_id': task.action_id}
                    if task.encounter_request is not None:
                        cancel_body['expected_action_session'] = self.bridge_identity['action_session']
                    cancel = self.bridge.request('POST', '/control/action/cancel', cancel_body)
                except BridgeError:
                    cancel = {'status': 'unconfirmed'}
            if uncertain:
                self.paused, self.reason = True, 'uncertain_request_observe_then_resume'
            if task.encounter_request is not None:
                self.paused, self.reason = True, 'encounter_requires_handoff'
                resolved = self.resolved_encounter_terminal(task, cancel or task.last_action_result)
                admission.update(resolved_action=resolved, task_completed=False,
                                 action_outcome=resolved['status'] if resolved else 'unresolved')
            self.end_active('uncertain' if uncertain else 'failed', reason=safe_reason(exc),
                            action_id=task.action_id, action=task.last_action_result, cancellation=cancel, **admission)

    def resolved_encounter_terminal(self, task, result):
        if (not isinstance(result, dict) or result.get('status') not in TERMINAL
                or result.get('action_id') != (task.action_id or (task.last_action_result or {}).get('action_id'))):
            return None
        try:
            validate_encounter_receipt(result, task.encounter_request)
        except (ValueError, KeyError, TypeError):
            return None
        return result

    def accept_action_status(self, task, result):
        if not isinstance(result, dict):
            raise BridgeError('action_status_mismatch', uncertain=True)
        if (result.get('action_schema_version') != 1 or result.get('action_id') != task.action_id
                or result.get('action_session') != self.bridge_identity['action_session']):
            raise BridgeError('action_status_mismatch', uncertain=True)
        try:
            validate_encounter_receipt(result, task.encounter_request)
        except (ValueError, KeyError, TypeError):
            raise BridgeError('encounter_action_receipt_invalid', uncertain=True) from None
        task.last_action_result = result
        status = result.get('status')
        if status == 'running':
            return
        if status not in TERMINAL:
            raise BridgeError('unknown_action_status', uncertain=True)
        task.action_id = None
        if native_release_unconfirmed(result):
            # Raw native failed evidence is retained; this is not an ordinary
            # route failure from which automatic actions may continue.
            self.paused, self.reason = True, 'input_release_unconfirmed'
            self.discard_pending('input_release_unconfirmed')
            self.end_active('failed', reason='input_release_unconfirmed', action=result)
            raise TaskEnded()
        if task.encounter_request is not None:
            self.paused, self.reason = True, 'encounter_requires_handoff'
            self.discard_pending('encounter_requires_handoff')
        if status != 'succeeded':
            # Preserve the full compact action status in the task result.
            self.end_active(status, reason=result.get('reason', status), action=result)
            raise TaskEnded()
        task.response = result

    def tick(self):
        self.read_commands()
        if not self.running:
            return
        if getattr(self, '_terrain_acquisition_unknown', None) is not None:
            # No automatic action/aim/combat continuation after an uncertain
            # native acquisition. Do not manufacture input-release evidence.
            if time.monotonic() - self.last_publish > 1:
                self.publish()
            return
        try:
            self.advance()
        except TaskEnded:
            pass
        self.advance_aim()
        self.advance_combat()
        if time.monotonic() - self.last_publish > 1:
            self.publish()

    def serve(self):
        try:
            self.start()
            while self.running:
                self.tick()
                time.sleep(0.05)
        except KeyboardInterrupt:
            if getattr(self, '_terrain_acquisition_unknown', None) is not None:
                self._terrain_acquisition_unknown['unexpected_cleanup_blocked'] = True
                self.reason = 'unexpected_cleanup_blocked'
                raise
            # Explicit owner Ctrl-C stops input only, never disconnects or quits Minecraft.
            self.interrupt_local('controller_stopped')
            self.combat.stop(self, 'controller_stopped', release=False)
            self.aim.release('controller_stopped')
            try:
                self.check_identity(self.bridge.request('GET', '/control/status'))
                result = self.bridge.request('POST', '/control/release-all', {})
                if result.get('ok') is True:
                    self.combat.confirm_released()
                else:
                    self.reason = 'stopped_input_release_unconfirmed'
            except (BridgeError, ValueError):
                self.reason = 'stopped_input_release_unconfirmed'
        finally:
            self.combat.stop(self, 'controller_stopped', release=False)
            if self.initialized and self.combat.held and getattr(self, '_terrain_acquisition_unknown', None) is None:
                try:
                    self.check_identity(self.bridge.request('GET', '/control/status'))
                    self.combat.stop(self, 'controller_stopped')
                except (BridgeError, ValueError):
                    self.reason = 'stopped_input_release_unconfirmed'
            self.aim.release('controller_stopped')
            self.running = False
            if self.owns_lock:
                self.publish()
            if self.lock:
                self.lock.close()


class TaskEnded(Exception):
    pass


def safe_reason(exc):
    if isinstance(exc, BridgeError):
        return exc.code
    value = str(exc)
    return value if re.fullmatch(r'[a-zA-Z0-9_]{1,100}', value) else 'invalid_command_or_observation'
