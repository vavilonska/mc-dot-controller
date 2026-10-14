"""Opt-in bounded native full729 consumer. No replay, actions, or clock repair.

Native nano arithmetic is same-process signed-long modular subtraction only.
Python freshness starts before prepare and survives delivery, validation and I/O.
"""
from __future__ import annotations

from copy import deepcopy
import math
import re
import time
from urllib.parse import urlencode

from .capability_snapshot import exact, signed_long_string, validate_snapshot
from .action_safety import native_release_unconfirmed, native_handoff_required
from .transport import ACQUISITION_ROOT, BridgeError
from .world import (Block, CapabilityWorldStamp, TerrainAssembler, TerrainError,
                    _navigation_epoch, _scan_origin, scan_identity)

VERSION = 'native-full729-v1'
CLOCK_VERSION = 'native-full729-client-clock-v1'
from navigation_controller.observation_clock import CONTRACT, PROFILE, ClockStamp, domain
NATIVE_TIMEOUT = 3_000_000_000
MAX_BYTES = 2 * 1024 * 1024
MAX_RESPONSE = 256 * 1024
MAX_MANIFEST = 32 * 1024
MAX_POLLS = 256
TERMINAL = {'succeeded', 'failed', 'cancelled'}
COMMON = {'ok', 'protocol', 'schema_version', 'acquisition_schema_version', 'acquisition',
          'job_id', 'owner_id', 'status', 'reason', 'stop_requested', 'admission_held',
          'client_work_pending', 'encoding_pending', 'request_admissions', 'created_nano',
          'stopped_nano', 'released_nano', 'retained_bytes'}
FULL = COMMON | {'deadline_nano', 'prepared_nano', 'activated_nano', 'context', 'parts',
                 'slices', 'terminal_task_turn'}
TOMBSTONE = COMMON | {'original_status', 'expired_nano'}
CONTEXT = {'run_id', 'process_id', 'world_generation', 'dimension', 'player_uuid',
           'action_session', 'origin', 'navigation_epoch', 'defense_epoch'}
SLICE = {'index', 'task_turn', 'start_nano', 'end_nano', 'source_tick', 'response_tick',
         'offset', 'next_offset', 'returned', 'encode_start_nano', 'encode_end_nano'}
IDENTIFIER = re.compile(r'[A-Za-z0-9_-]{1,80}')
DIGEST = re.compile(r'[0-9a-f]{64}')


def require(condition, reason):
    if not condition:
        raise TerrainError('acquisition_' + reason)


def integer(value, low=0, high=2**53-1):
    return type(value) is int and low <= value <= high


def elapsed(later, earlier):
    require(signed_long_string(later) and signed_long_string(earlier), 'native_clock_schema')
    value = (int(later) - int(earlier) + 2**63) % 2**64 - 2**63
    require(value >= 0, 'clock_invalid')
    return value


def _version(value, job, owner, observation_clock=None):
    require(value.get('ok') is True and value.get('protocol') == 'mineclient-bridge'
            and type(value.get('schema_version')) is int and value['schema_version'] == 2
            and type(value.get('acquisition_schema_version')) is int and value['acquisition_schema_version'] == (2 if observation_clock is not None else 1)
            and value.get('acquisition') == (CLOCK_VERSION if observation_clock is not None else VERSION), 'version')
    require(value.get('job_id') == job and value.get('owner_id') == owner
            and type(value['job_id']) is str and IDENTIFIER.fullmatch(value['job_id']) is not None
            and type(value['owner_id']) is str and IDENTIFIER.fullmatch(value['owner_id']) is not None, 'identity')


def validate_manifest(value, job, owner, *, observation_clock=None):
    """Full live metadata and compact history are intentionally distinct schemas."""
    require(observation_clock in (None,CONTRACT), 'clock_selection')
    require(type(value) is dict, 'manifest_schema')
    retired = value.get('status') == 'expired'
    require(set(value) == (TOMBSTONE if retired else FULL), 'manifest_keys')
    _version(value, job, owner, observation_clock)
    require(value['reason'] is None or type(value['reason']) is str
            and re.fullmatch(r'[a-z0-9_]{1,80}', value['reason']) is not None, 'reason')
    require(all(type(value[k]) is bool for k in ('stop_requested', 'admission_held',
            'client_work_pending', 'encoding_pending')), 'ownership_types')
    require(integer(value['request_admissions'], 0, 2), 'request_admissions')
    require(integer(value['retained_bytes'], 1, MAX_BYTES), 'retained_bytes')
    require(signed_long_string(value['created_nano']), 'created_nano')
    for key in ('stopped_nano', 'released_nano') + (('expired_nano',) if retired else ('prepared_nano', 'activated_nano')):
        require(value[key] is None or signed_long_string(value[key]), key)
        if value[key] is not None:
            elapsed(value[key], value['created_nano'])
    if retired:
        require(value['original_status'] in TERMINAL and all(value[k] is False for k in
                ('admission_held', 'client_work_pending', 'encoding_pending'))
                and all(value[k] is not None for k in ('stopped_nano', 'released_nano', 'expired_nano')),
                'tombstone_ownership')
        require(elapsed(value['released_nano'], value['stopped_nano']) >= 0
                and elapsed(value['expired_nano'], value['released_nano']) >= 30_000_000_000, 'tombstone_clock')
        return value
    require(value['status'] in {'preparing', 'prepared', 'activating', 'active', 'encoding', 'stopping'} | TERMINAL,
            'status')
    require(signed_long_string(value['deadline_nano'])
            and elapsed(value['deadline_nano'], value['created_nano']) == NATIVE_TIMEOUT, 'deadline')
    context = value['context']
    if context is not None:
        require(type(context) is dict and set(context) == (CONTEXT | {'observation_clock_domain'} if observation_clock is not None else CONTEXT), 'context_schema')
        require(all(type(context[k]) is str and 1 <= len(context[k]) <= 256 for k in
                    ('run_id', 'world_generation', 'dimension', 'player_uuid', 'action_session')), 'context_identity')
        require(integer(context['process_id'], 1, 2**63-1)
                and (context['navigation_epoch'] is None or integer(context['navigation_epoch']))
                and (context['defense_epoch'] is None or integer(context['defense_epoch'])), 'context_epoch')
        require(type(context['origin']) is dict and set(context['origin']) == {'x', 'y', 'z'}
                and all(integer(v, -30_000_000, 30_000_000) for v in context['origin'].values()), 'context_origin')
    clock_domain=None
    if observation_clock is not None and context is not None:
        clock_domain=domain(context['observation_clock_domain'])
        ctx=context['observation_clock_domain']['context']
        require(all(exact(ctx[k],context[k]) for k in ('run_id','process_id','world_generation','dimension','player_uuid','action_session')), 'clock_context')
    parts = value['parts']
    require(type(parts) is list and len(parts) <= 6, 'parts')
    names = []
    for part in parts:
        require(type(part) is dict and set(part) == {'part', 'sha256', 'bytes'}, 'part_schema')
        require(part['part'] in ('a', 'p0', 'p1', 'p2', 'p3', 'c') and part['part'] not in names
                and type(part['sha256']) is str and DIGEST.fullmatch(part['sha256']) is not None
                and integer(part['bytes'], 1, MAX_RESPONSE), 'part')
        names.append(part['part'])
    require(sum(p['bytes'] for p in parts) <= value['retained_bytes'], 'part_retention')
    slices = value['slices']
    require(type(slices) is list and len(slices) <= 4, 'slices')
    offset, turn, prior_start, prior_response = 0, 0, None, None
    for index, row in enumerate(slices):
        require(type(row) is dict and set(row) == (SLICE | {'source_clock','response_clock'} if observation_clock is not None else SLICE), 'slice_schema')
        require(integer(row['index'], index, index) and integer(row['task_turn'], turn+1)
                and integer(row['source_tick']) and integer(row['response_tick'], 0 if observation_clock is not None else row['source_tick'])
                and integer(row['offset'], offset, offset) and integer(row['returned'], 1, 729)
                and integer(row['next_offset'], offset+row['returned'], offset+row['returned'])
                and row['next_offset'] <= 729, 'slice_coverage')
        if observation_clock is not None:
            source_clock=ClockStamp.parse(row['source_clock']);response_clock=ClockStamp.parse(row['response_clock'])
            require(clock_domain is not None and source_clock.identity == clock_domain, 'slice_clock_domain')
            response_clock.after(source_clock)
            if index: source_clock.after(ClockStamp.parse(slices[index-1]['response_clock']))
        require(signed_long_string(row['start_nano']) and signed_long_string(row['end_nano']), 'slice_clock')
        elapsed(row['start_nano'], value['created_nano'])
        elapsed(row['end_nano'], row['start_nano'])
        for key in ('encode_start_nano', 'encode_end_nano'):
            require(row[key] is None or signed_long_string(row[key]), 'encode_clock')
        if row['encode_start_nano'] is not None: elapsed(row['encode_start_nano'], row['end_nano'])
        if row['encode_end_nano'] is not None:
            require(row['encode_start_nano'] is not None, 'encode_clock')
            elapsed(row['encode_end_nano'], row['encode_start_nano'])
        if prior_start is not None:
            require(elapsed(row['start_nano'], prior_start) >= 50_000_000, 'slice_rate')
            if observation_clock is None: require(row['source_tick'] >= prior_response, 'tick_reversed')
            require(slices[index-1]['encode_end_nano'] is not None, 'overlapping_encoding')
            elapsed(row['start_nano'], slices[index-1]['encode_end_nano'])
        offset, turn, prior_start, prior_response = row['next_offset'], row['task_turn'], row['start_nano'], row['response_tick']
    require(value['terminal_task_turn'] is None or integer(value['terminal_task_turn'], 1), 'terminal_turn')
    if value['released_nano'] is not None:
        require(value['status'] in TERMINAL and value['stopped_nano'] is not None
                and all(value[k] is False for k in ('admission_held', 'client_work_pending', 'encoding_pending')),
                'release_ownership')
        elapsed(value['released_nano'], value['stopped_nano'])
    if value['status'] == 'prepared':
        require(value['request_admissions'] == 1 and context is not None
                and value['prepared_nano'] is not None and names == ['a'], 'prepared')
    if value['status'] == 'succeeded':
        require(value['reason'] is None and value['stop_requested'] is False and value['released_nano'] is not None
                and value['prepared_nano'] is not None and value['activated_nano'] is not None
                and value['request_admissions'] == 2 and context is not None
                and 1 <= len(slices) <= 4 and offset == 729
                and value['terminal_task_turn'] == slices[-1]['task_turn']
                and names == ['a'] + ['p' + str(i) for i in range(len(slices))] + ['c'], 'success')
        elapsed(value['activated_nano'], value['prepared_nano'])
        elapsed(slices[0]['start_nano'], value['activated_nano'])
        for row in slices:
            require(row['encode_end_nano'] is not None, 'success_encoding')
        elapsed(value['stopped_nano'], slices[-1]['encode_end_nano'])
        require(elapsed(value['released_nano'], value['created_nano']) < NATIVE_TIMEOUT, 'deadline')
    return value


def _context(bundle, epoch, observation_clock=None):
    state, status = bundle['state'], bundle['status']
    return {'run_id': status['run_id'], 'process_id': status['process_id'],
            'world_generation': state['world']['world_generation'], 'dimension': state['world']['dimension'],
            'player_uuid': state['player']['uuid'], 'action_session': state['client_action']['action_session'],
            'origin': vars(_scan_origin(state)), 'navigation_epoch': _navigation_epoch(state), 'defense_epoch': epoch,
            **({'observation_clock_domain':ClockStamp.parse(bundle['observation_clock']).as_domain()}
               if observation_clock is not None else {})}


def validate_options(command):
    require(set(command) <= {'op', 'request_id', 'session_id', 'submitted_at', 'terrain_acquisition',
            'capability_observation', 'terrain', 'radius', 'vertical', 'entity_radius', '_navigation_defense_epoch','observation_clock'}
            and command.get('op') == 'observe', 'command_schema')
    selected=command.get('observation_clock')
    require('observation_clock' not in command or selected == CONTRACT, 'clock_selection')
    require(type(command.get('terrain_acquisition')) is str and command['terrain_acquisition'] ==
            (CLOCK_VERSION if selected is not None else VERSION), 'version')
    require(command.get('terrain') is True and command.get('capability_observation') is True
            and all(type(command.get(k)) is int and command[k] == v
                    for k, v in (('radius', 4), ('vertical', 4), ('entity_radius', 48)))
            and not any(k in command for k in ('capability_survey', 'frame', 'coordination_step', 'allow_menu')),
            'options')
    require(type(command.get('request_id')) is str and IDENTIFIER.fullmatch(command['request_id']) is not None,
            'job_identity')
    require(command.get('_navigation_defense_epoch') is None or integer(command['_navigation_defense_epoch']),
            'defense_epoch')


class Acquisition:
    def __init__(self, resident, command):
        validate_options(command)
        self.observation_clock=command.get('observation_clock')
        self.version=2 if self.observation_clock is not None else 1
        self.resident, self.command, self.bridge = resident, command, resident.bridge
        self.cache = resident.cache
        self.job, self.owner = command['request_id'], resident.session_id
        require(type(self.owner) is str and IDENTIFIER.fullmatch(self.owner) is not None, 'owner_identity')
        require(getattr(resident, '_terrain_acquisition_unknown', None) is None, 'prior_unknown_no_replay')
        self.started = time.monotonic()
        self.last_clock = self.started
        self.owner_context = resident.coordination_context()
        self.epoch = command.get('_navigation_defense_epoch')
        self.bound_command = deepcopy(command)
        self.manifest = None
        self.polls = 0
        self.cancel_sent = False
        self.prepared = False
        self.evidence = {'schema_version': self.version, 'acquisition': CLOCK_VERSION if self.version==2 else VERSION, 'job_id': self.job, 'owner_id': self.owner,
                         'clock': 'python_monotonic', 'started_monotonic': self.started,
                         'capture_bracket': 'conservative_before_A_to_C_delivery', 'exchanges': []}

    def deadline(self):
        now = time.monotonic()
        require(math.isfinite(now) and self.last_clock <= now, 'python_clock_invalid')
        self.last_clock = now
        require(0 <= now - self.started < 3, 'python_deadline')
        return now

    def request(self, method, operation, body=None, **query):
        self.deadline()
        path = ACQUISITION_ROOT + operation
        if query: path += '?' + urlencode(query)
        stage = {'operation': operation, 'started_monotonic': time.monotonic()}
        self.evidence['exchanges'].append(stage)
        try:
            return self.bridge.request(method, path, body)
        finally:
            stage['finished_monotonic'] = time.monotonic()
            stage['response_metadata'] = deepcopy(getattr(self.bridge, 'last_response_metadata', None))

    def metadata(self, *, manifest=False):
        metadata = self.evidence['exchanges'][-1]['response_metadata']
        require(type(metadata) is dict and metadata.get('response_bytes_status') == 'observed_read_length'
                and integer(metadata.get('response_bytes_read'), 1, MAX_MANIFEST if manifest else MAX_RESPONSE)
                and type(metadata.get('response_sha256')) is str
                and DIGEST.fullmatch(metadata['response_sha256']) is not None, 'raw_byte_evidence')
        return metadata

    def accept_manifest(self, value, *, wire=True):
        validate_manifest(value, self.job, self.owner, observation_clock=self.observation_clock)
        if wire:
            metadata = self.metadata(manifest=True)
            if value['status'] == 'expired': require(metadata['response_bytes_read'] <= 4096, 'tombstone_bytes')
        if self.manifest is not None:
            old = self.manifest
            require(value['created_nano'] == old['created_nano'], 'manifest_identity_changed')
            require(value['request_admissions'] >= old['request_admissions'], 'admissions_reversed')
            if value['status'] != 'expired' and old['status'] != 'expired':
                require(exact(value['context'], old['context']) or old['context'] is None, 'context_changed')
                require(value['parts'][:len(old['parts'])] == old['parts'], 'parts_changed')
                require(len(value['slices']) >= len(old['slices']), 'slices_reversed')
                for prior, current in zip(old['slices'], value['slices']):
                    require(all(prior[k] is None or exact(prior[k], current[k]) for k in (SLICE | {'source_clock','response_clock'} if self.observation_clock is not None else SLICE)), 'slice_changed')
                for key in ('prepared_nano', 'activated_nano', 'stopped_nano', 'released_nano'):
                    require(old[key] is None or value[key] == old[key], 'lifecycle_changed')
            if old['status'] in TERMINAL:
                require(value['status'] == old['status'] or value['status'] == 'expired'
                        and value['original_status'] == old['status'], 'terminal_changed')
                require(value['reason'] == old['reason'], 'terminal_reason_changed')
        self.manifest = deepcopy(value)
        self.evidence['manifest'] = deepcopy(value)
        return value

    def policy(self, bundle):
        self.resident.coordination_context_unchanged(self.owner_context)
        require(exact(self.command, self.bound_command), 'command_changed')
        self.local_policy()
        state = bundle['state']
        require(bundle['action']['status'] != 'running', 'native_owner')
        require(not native_release_unconfirmed(bundle['action']) and not native_handoff_required(bundle['action'])
                and type(state.get('held_inputs')) is dict and state['held_inputs'].get('neutral') is True,
                'native_input_owner')
        require(state['screen_open'] is False and state['paused'] is False
                and state['focused'] is True and state['private_singleplayer'] is True, 'state_policy')

    def local_policy(self):
        """Before prepare as well as activate: no existing local owner to strand."""
        policy = self.resident.observation_policy()
        require(policy.get('requires_handoff') is False and policy.get('input_release_unconfirmed') is False,
                'resident_policy')
        r = self.resident
        require(not r.active and not r.pending and not r.paused and not r.aim.active
                and not r.combat.active and not r.combat.held, 'resident_owner')

    def observe_bundle(self, bundle):
        from .movement_wire import MARKER, validate_retained
        decoded = validate_snapshot(bundle, 48, observation_clock=self.observation_clock)
        self.last_bundle_wire = None
        if MARKER in bundle:
            self.last_bundle_wire = deepcopy(getattr(self.bridge, 'last_capability_wire', None))
            validate_retained(self.last_bundle_wire, decoded, 48, observation_clock=self.observation_clock)
        self.cache.native_binding.observe(decoded['state'])
        self.resident.check_identity(decoded['status'])
        return decoded

    def inspect_until_closed(self, manifest):
        while manifest['status'] not in TERMINAL | {'expired'} or manifest['admission_held']:
            require(self.polls < MAX_POLLS, 'status_budget')
            self.deadline()
            time.sleep(.01)
            self.deadline()
            self.polls += 1
            manifest = self.accept_manifest(self.request('GET', 'status', job_id=self.job, owner_id=self.owner))
        require(manifest['admission_held'] is False and manifest['client_work_pending'] is False
                and manifest['encoding_pending'] is False and manifest['released_nano'] is not None
                and manifest['stopped_nano'] is not None, 'ownership_not_released')
        return manifest

    def cancel(self):
        require(not self.cancel_sent, 'cancel_not_replayed')
        self.cancel_sent = True
        value = self.request('POST', 'cancel', {'acquisition_schema_version': self.version, 'job_id': self.job,
                             'owner_id': self.owner, 'cancel_id': self.job})
        self.inspect_until_closed(self.accept_manifest(value))

    def fetch(self, part):
        row = next(p for p in self.manifest['parts'] if p['part'] == part)
        value = self.request('GET', 'fetch', job_id=self.job, owner_id=self.owner, part=part, sha256=row['sha256'])
        metadata = self.metadata()
        require(metadata['response_sha256'] == row['sha256'] and metadata['response_bytes_read'] == row['bytes'],
                'raw_hash_mismatch')
        self.deadline()
        return value

    def run(self):
        self.cache.invalidate_terrain()
        self.cache.capability_bundle = self.cache.state_capture = self.cache.state_response_metadata = None
        self.cache.capability_wire = None
        self.cache._scan_start = None
        self.cache.terrain_read = {'outcome': 'reading', 'attempts': 1, 'pages': 0, 'last_rejection': None,
                                   'elapsed_ms': 0, 'acquisition': self.evidence}
        try:
            self.local_policy()
            wrapper = self.request('POST', 'prepare', {'acquisition_schema_version': self.version, 'job_id': self.job,
                'owner_id': self.owner, 'defense_epoch': self.epoch, 'radius': 4, 'vertical': 4, 'entity_radius': 48,
                **({'observation_clock':CONTRACT} if self.observation_clock is not None else {})})
            # A known prepare response means this original job may own admission,
            # even if its body fails validation. Cleanup never creates a new ID.
            self.prepared = True
            require(type(wrapper) is dict and set(wrapper) == {'ok', 'protocol', 'schema_version',
                'acquisition_schema_version', 'acquisition', 'job_id', 'owner_id', 'a', 'manifest'}, 'prepare_schema')
            _version(wrapper, self.job, self.owner, self.observation_clock)
            metadata = self.metadata()
            manifest = self.accept_manifest(wrapper['manifest'], wire=False)
            require(manifest['status'] == 'prepared', 'not_prepared')
            a_part = manifest['parts'][0]
            require(metadata.get('embedded_a_sha256') == a_part['sha256']
                    and type(metadata.get('embedded_a_bytes')) is int
                    and metadata['embedded_a_bytes'] == a_part['bytes']
                    and integer(metadata.get('embedded_manifest_bytes'), 1, MAX_MANIFEST), 'raw_a_hash_mismatch')
            a = self.observe_bundle(wrapper['a'])
            require(exact(manifest['context'], _context(a, self.epoch,self.observation_clock)), 'a_context')
            elapsed(a['state']['capability_guard']['source_nano'], manifest['created_nano'])
            elapsed(manifest['prepared_nano'], a['state']['capability_guard']['source_nano'])
            self.policy(a)
            self.deadline()
            manifest = self.accept_manifest(self.request('POST', 'activate', {'acquisition_schema_version': self.version,
                'job_id': self.job, 'owner_id': self.owner, 'a_sha256': a_part['sha256']}))
            manifest = self.inspect_until_closed(manifest)
            require(manifest['status'] == 'succeeded', manifest['reason'] or 'not_succeeded')
            self.deadline()
            first = a['state']
            assembler = TerrainAssembler(CapabilityWorldStamp.parse(first['world']), self.started,
                max_pages=4, max_scan_seconds=3, max_scan_ticks=40, capability_page_limit=1024,
                observation_clock=a.get('observation_clock') if self.observation_clock is not None else None)
            cells, sources = {}, []
            for index, native_slice in enumerate(manifest['slices']):
                page = self.fetch('p' + str(index))
                # Unchanged SCAN bounds sum each cell plus one array separator;
                # the actual JSON array contributes one additional byte.
                require(integer(self.metadata().get('embedded_cells_bytes'), 2, 224*1024+1), 'cell_payload_bytes')
                require(type(page) is dict, 'page_schema')
                for page_key, slice_key in (('game_time', 'source_tick'), ('response_game_time', 'response_tick'),
                        ('offset', 'offset'), ('next_offset', 'next_offset'), ('returned', 'returned')):
                    require(exact(page.get(page_key), native_slice[slice_key]), 'page_slice_mismatch')
                if self.observation_clock is not None:
                    require(all(exact(page.get(k),native_slice[k]) for k in ('source_clock','response_clock')), 'page_slice_clock_mismatch')
                require(type(page.get('payload_budget_exhausted')) is bool, 'payload_budget_schema')
                assembler.add(page, self.deadline())
                require(assembler.header[1:4] == (_scan_origin(first), 4, 4), 'region_changed')
                for cell in page['cells']:
                    if cell.get('status') == 'loaded': cells[(cell['x'], cell['y'], cell['z'])] = cell
                sources.append({'source_tick': page['game_time'], 'response_tick': page['response_game_time'],
                    'delivery_monotonic': self.last_clock, 'delivery_diagnostics_only': True,
                    'offset': page['offset'], 'returned': page['returned'],
                    **({'source_clock':deepcopy(page['source_clock']),'response_clock':deepcopy(page['response_clock'])}
                       if self.observation_clock is not None else {})})
                self.cache.terrain_read['pages'] += 1
            c = self.observe_bundle(self.fetch('c'))
            delivered = self.last_clock
            self.policy(c)
            require(exact(_context(c, self.epoch,self.observation_clock), manifest['context'])
                    and scan_identity(first) == scan_identity(c['state']), 'c_context')
            final_slice = manifest['slices'][-1]
            if self.observation_clock is None:
                require(c['state']['world']['game_time'] >= final_slice['response_tick'], 'c_tick_reversed')
            else: ClockStamp.parse(c['observation_clock']).after(ClockStamp.parse(final_slice['response_clock']))
            source = c['state']['capability_guard']['source_nano']
            elapsed(source, final_slice['end_nano'])
            elapsed(final_slice['encode_start_nano'], source)
            grid = assembler.finish(CapabilityWorldStamp.parse(c['state']['world']), self.deadline(),
                observation_clock=c.get('observation_clock') if self.observation_clock is not None else None)
            require(grid.complete and len(grid.cells) == 729, 'incomplete')
            if self.observation_clock is None: self.cache.grid, self.cache.cells = grid, cells
            self.cache.terrain_received_at = grid.received_at
            self.cache.state, self.cache.capability_bundle = c['state'], c
            self.cache.capability_wire = deepcopy(self.last_bundle_wire)
            self.cache.received_at = delivered
            self.cache.state_capture = {'started_mono': self.started, 'finished_mono': delivered}
            self.cache.state_response_metadata = deepcopy(self.evidence['exchanges'][-1]['response_metadata'])
            finished = self.deadline()
            self.cache.terrain_read.update(outcome='complete', elapsed_ms=(finished-self.started)*1000)
            self.evidence['finished_monotonic'] = finished
            self.evidence['source_pages'] = sources
            return {'origin': vars(grid.origin), 'radius': 4, 'vertical': 4, 'world_generation': grid.world.generation,
                'dimension': grid.world.dimension, 'scan_generation': grid.scan_generation,
                'capture_started_mono': self.started, 'capture_finished_mono': finished,
                'source_tick': grid.first_tick, 'last_tick': grid.last_tick,
                'cells': list(cells.values()), 'complete': grid.complete,
                **({'observation_clock_profile':PROFILE,'first_source_clock':grid.first_source_clock.as_dict(),
                    'last_source_clock':grid.last_source_clock.as_dict(),'last_response_clock':grid.last_response_clock.as_dict(),
                    'source_pages':sources} if self.observation_clock is not None else {})}
        except (BridgeError, ValueError, KeyError, TypeError) as exc:
            self.cache.invalidate_terrain()
            self.cache.capability_bundle = self.cache.state_capture = self.cache.state_response_metadata = None
            self.cache.capability_wire = None
            uncertain = isinstance(exc, BridgeError) and exc.uncertain
            # Known prepared rejection may send one lifecycle cancel, only while
            # original ownership is unresolved. Unknown transport never cancels.
            closed = self.manifest is not None and self.manifest['status'] in TERMINAL | {'expired'} \
                and self.manifest['admission_held'] is False
            if self.prepared and not closed and not uncertain and not self.cancel_sent:
                try:
                    self.cancel()
                    closed = True
                except (BridgeError, ValueError, KeyError, TypeError) as cleanup:
                    self.evidence['cancellation_error'] = str(cleanup)
                    uncertain = True
            if self.prepared and not closed:
                uncertain = True
            reason = str(exc)
            self.evidence['failure'] = reason
            self.evidence['unknown'] = uncertain
            self.cache.terrain_read.update(outcome='failed', last_rejection=reason,
                                          elapsed_ms=(time.monotonic()-self.started)*1000)
            if uncertain:
                self.resident._terrain_acquisition_bridge = self.bridge
                self.resident._terrain_acquisition_unknown = {
                    'job_id': self.job, 'owner_id': self.owner, 'outcome_unknown': True,
                    'ownership_unresolved': True, 'bridge_identity': deepcopy(self.owner_context[1]),
                    'defense_epoch': self.epoch, 'observation_clock':self.observation_clock, 'created_nano': self.manifest.get('created_nano') if self.manifest else None,
                    'context': deepcopy(self.manifest.get('context')) if self.manifest else None}
                original = exc
                exc = BridgeError(reason, uncertain=True, status=getattr(original, 'status', None))
            exc.terrain_read_diagnostics = deepcopy(self.cache.terrain_read)
            raise exc


def snapshot(resident, command):
    """Return normal complete siblings/terrain with an honest conservative bracket."""
    acquisition = Acquisition(resident, command)
    terrain = acquisition.run()
    bundle = resident.cache.capability_bundle
    resident.prospecting.observe_world(bundle['state']['world'])
    capture = resident.cache.state_capture
    result = {key: bundle[key] for key in ('status', 'action', 'state', 'screen')}
    result.update(capability_snapshot_schema_version=bundle['capability_snapshot_schema_version'], terrain=terrain,
        aim_lock=resident.aim.status(), combat=resident.combat.status(), resident_policy=resident.observation_policy(),
        scan_cache=resident.prospecting.summary(), capability_capture=dict(capture),
        terrain_acquisition=deepcopy(acquisition.evidence), terrain_read=deepcopy(resident.cache.terrain_read),
        state_read_diagnostics={'clock': 'python_monotonic', 'started_monotonic': capture['started_mono'],
            'finished_monotonic': capture['finished_mono'], 'capture_bracket': 'conservative_before_A_to_C_delivery',
            'response_metadata': deepcopy(resident.cache.state_response_metadata)})
    if acquisition.observation_clock is not None:
        result.update({k:deepcopy(bundle[k]) for k in ('ok','protocol','schema_version','observation_clock_profile','observation_clock')})
    if resident.cache.capability_wire is not None:
        result['native_capability_wire'] = deepcopy(resident.cache.capability_wire)
    acquisition.deadline()
    return result


def closure_command(resident, command):
    """Explicit original-ID inspection and title-only closure, never resume.

    The existing operator-owned QueueClient reaches this path. Runtime's unknown
    journal and original observation receipt are not rewritten by these commands.
    """
    saved = resident._terrain_acquisition_unknown
    bridge = getattr(resident, '_terrain_acquisition_bridge', None)
    require(bridge is not None and resident.bridge is bridge, 'closure_bridge_changed')
    meta = {'request_id', 'session_id', 'submitted_at'}
    require(command.get('session_id') == saved['owner_id'] == resident.session_id
            and type(command.get('request_id')) is str and IDENTIFIER.fullmatch(command['request_id']) is not None
            and command['request_id'] != saved['job_id']
            and type(command.get('submitted_at')) in (int, float) and math.isfinite(command['submitted_at']), 'closure_identity')
    require(exact(resident.bridge_identity, saved['bridge_identity']), 'closure_bridge_changed')
    operation = command.get('op')
    if operation == 'terrain_acquisition_status':
        require(not saved.get('shutdown_attempted'), 'closure_shutdown_already_attempted')
        require(set(command) == meta | {'op', 'job_id', 'owner_id'}
                and command['job_id'] == saved['job_id'] and command['owner_id'] == saved['owner_id'], 'closure_exact_job')
        unbound = saved['context'] is None
        fence = None
        if unbound:
            fence_start = time.monotonic()
            before = _closure_native_identity(bridge.request('GET', '/control/status'))
            first_finished = time.monotonic()
            require(exact(before, saved['bridge_identity']) and 0 <= first_finished-fence_start <= .8,
                    'closure_native_identity_fence')
        value = bridge.request('GET', ACQUISITION_ROOT+'status?'+urlencode({
            'job_id': saved['job_id'], 'owner_id': saved['owner_id']}))
        validate_manifest(value, saved['job_id'], saved['owner_id'], observation_clock=saved.get('observation_clock'))
        metadata = getattr(bridge, 'last_response_metadata', None)
        require(type(metadata) is dict and metadata.get('response_bytes_status') == 'observed_read_length'
                and integer(metadata.get('response_bytes_read'), 1, 4096 if value['status'] == 'expired' else MAX_MANIFEST)
                and type(metadata.get('response_sha256')) is str and DIGEST.fullmatch(metadata['response_sha256']),
                'closure_raw_evidence')
        require(saved['created_nano'] is None or value['created_nano'] == saved['created_nano'], 'closure_created_changed')
        if unbound:
            middle_finished = time.monotonic()
            require(value['status'] in TERMINAL | {'expired'} and value['released_nano'] is not None
                    and value['stopped_nano'] is not None and all(value[k] is False for k in
                        ('admission_held', 'client_work_pending', 'encoding_pending')),
                    'closure_ownership_unresolved')
            require(first_finished <= middle_finished and 0 <= middle_finished-fence_start <= .8,
                    'closure_native_identity_fence')
            after = _closure_native_identity(bridge.request('GET', '/control/status'))
            fence_end = time.monotonic()
            require(exact(before, after) and exact(after, saved['bridge_identity'])
                    and resident.session_id == saved['owner_id']
                    and resident.bridge is bridge
                    and exact(resident.bridge_identity, saved['bridge_identity'])
                    and middle_finished <= fence_end and 0 <= fence_end-fence_start <= .8,
                    'closure_native_identity_fence')
            fence = {'clock': 'python_monotonic', 'started_monotonic': fence_start,
                     'finished_monotonic': fence_end, 'before_identity': before, 'after_identity': after}
        previous = saved.get('release_proof')
        require(resident.session_id == saved['owner_id'] and resident.bridge is bridge
                and exact(resident.bridge_identity, saved['bridge_identity']), 'closure_bridge_changed')
        if previous is not None:
            previous_status = previous.get('original_status', previous['status'])
            require(value['status'] in TERMINAL | {'expired'}
                    and value.get('original_status', value['status']) == previous_status
                    and all(exact(value[k], previous[k]) for k in
                            ('reason', 'created_nano', 'stopped_nano', 'released_nano', 'request_admissions',
                             'stop_requested', 'admission_held', 'client_work_pending', 'encoding_pending')),
                    'closure_terminal_regression')
        if value['status'] == 'expired':
            require(fence is not None or saved['created_nano'] is not None and saved['context'] is not None,
                    'closure_retired_context_unknown')
        else:
            context = value['context']
            require(context is None and fence is not None or type(context) is dict
                    and all(exact(context.get(k), saved['bridge_identity'].get(k))
                        for k in ('run_id', 'process_id', 'action_session'))
                    and exact(context.get('defense_epoch'), saved['defense_epoch'])
                    and (saved['context'] is None or exact(context, saved['context'])), 'closure_context_changed')
            saved['created_nano'], saved['context'] = value['created_nano'], deepcopy(context)
        if value['status'] in TERMINAL | {'expired'}:
            require(value['released_nano'] is not None and value['stopped_nano'] is not None
                    and all(value[k] is False for k in ('admission_held', 'client_work_pending', 'encoding_pending')),
                    'closure_ownership_unresolved')
            saved['ownership_unresolved'] = False
            if previous is None:
                saved['release_proof'] = deepcopy(value)
            if fence is not None:
                saved['identity_fence'] = fence
                saved['created_nano'] = value['created_nano']
        resident.finish(command, 'succeeded', result={'outcome_unknown': True,
            'ownership_unresolved': saved['ownership_unresolved'], 'manifest': value,
            **({'identity_fence': fence} if fence is not None else {})})
        return True
    require(set(command) == meta | {'op'}, 'closure_command_shape')
    require(saved['ownership_unresolved'] is False, 'closure_ownership_unresolved')
    require(not resident.active and not resident.pending and not resident.combat.active
            and not resident.combat.held and not resident.aim.active, 'closure_owner_active')
    if operation == 'observe':
        require(not saved.get('shutdown_attempted'), 'closure_shutdown_already_attempted')
        saved.pop('title_proof', None)
        started = time.monotonic()
        result = resident.snapshot(command)  # Exact existing nonterrain read path.
        require(resident.bridge is bridge, 'closure_bridge_changed')
        _title(result, saved['bridge_identity'])
        require(0 <= time.monotonic()-started < .8, 'closure_title_stale')
        saved['title_proof'] = {'started_mono': started, 'owner_id': resident.session_id,
                                'result': deepcopy(result)}
        resident.finish(command, 'succeeded', result=result, outcome_unknown=True)
        return True
    scope = getattr(resident, '_terrain_acquisition_shutdown_scope', None)
    if operation == 'cancel' and scope is command:
        return False  # Only the exact internal recursive command object below.
    require(operation == 'shutdown' and not saved.get('shutdown_attempted'), 'closure_no_new_work')
    proof = saved.get('title_proof')
    require(type(proof) is dict and proof['owner_id'] == resident.session_id
            and 0 <= time.monotonic()-proof['started_mono'] < .8, 'closure_title_stale')
    _title(proof['result'], saved['bridge_identity'])
    saved['shutdown_attempted'] = True
    nested = {**command, 'op': 'cancel'}
    resident._terrain_acquisition_shutdown_scope = nested
    try:
        resident.command(nested)  # Original same-ID cancel/release-all path once.
        resident.running = False
    finally:
        resident._terrain_acquisition_shutdown_scope = None
    return True


def _title(payload, identity):
    status, action, screen = (payload.get(k) for k in ('status', 'action', 'screen'))
    require(all(type(v) is dict for v in (status, action, screen)), 'closure_title_schema')
    actual = {'run_id': status.get('run_id'), 'process_id': status.get('process_id'),
              'action_session': status.get('client_action', {}).get('action_session')}
    require(exact(actual, identity) and action.get('action_session') == identity['action_session'], 'closure_title_identity')
    require(status.get('in_world') is False and status.get('world', {}).get('present') is False
            and status.get('player', {}).get('present') is False
            and status.get('screen', {}).get('class') == 'net.minecraft.client.gui.screens.TitleScreen'
            and screen.get('class') == 'net.minecraft.client.gui.screens.TitleScreen'
            and screen.get('open') is True and action.get('status') == 'idle' and action.get('action_id') is None
            and status.get('client_action', {}).get('status') == 'idle'
            and status.get('client_action', {}).get('action_id') is None,
            'closure_not_title_idle')
    mouse, isolation = status.get('mouse'), status.get('input_isolation')
    require(status.get('held_mappings') == [] and type(mouse) is dict
            and mouse.get('held_world_buttons') == []
            and all(mouse.get(k) is False for k in ('left_pressed', 'right_pressed', 'middle_pressed'))
            and type(isolation) is dict and type(isolation.get('held_keys')) is int and isolation['held_keys'] == 0,
            'closure_inputs_not_neutral')


def _closure_native_identity(status):
    require(type(status) is dict and status.get('ok') is True
            and status.get('protocol') == 'mineclient-bridge' and type(status.get('schema_version')) is int
            and status['schema_version'] == 2 and type(status.get('run_id')) is str
            and 1 <= len(status['run_id']) <= 256 and integer(status.get('process_id'), 1, 2**63-1)
            and type(status.get('client_action')) is dict
            and type(status['client_action'].get('action_session')) is str
            and 1 <= len(status['client_action']['action_session']) <= 256, 'closure_native_identity_schema')
    return {'run_id': status['run_id'], 'process_id': status['process_id'],
            'action_session': status['client_action']['action_session']}


def validate_shutdown(resident, command, status):
    saved = resident._terrain_acquisition_unknown
    proof = saved.get('title_proof')
    require(getattr(resident, '_terrain_acquisition_shutdown_scope', None) is command
            and saved.get('shutdown_attempted') is True and saved['ownership_unresolved'] is False,
            'unexpected_cleanup_blocked')
    require(resident.bridge is getattr(resident, '_terrain_acquisition_bridge', None), 'closure_bridge_changed')
    require(type(proof) is dict and proof['owner_id'] == resident.session_id
            and 0 <= time.monotonic()-proof['started_mono'] < .8, 'closure_title_stale')
    _title({**proof['result'], 'status': status}, saved['bridge_identity'])
