"""One explicitly published observation, many cache-only readers; no game client."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import copy
import hashlib
from threading import RLock
import uuid

from .schema import (Context, RESOURCE, SECTIONS, canonical, fields, identifier,
                     integer, number, require, Rejected)


def _number(obj, key, low, high):
    if key not in obj:
        return None
    try:
        return number(obj[key], low, high)
    except Rejected:
        return None


def _bool(obj, key):
    return obj.get(key) if type(obj.get(key)) is bool else None


def _id(value, resource=False):
    try:
        if resource:
            return value if isinstance(value, str) and RESOURCE.fullmatch(value) else None
        return identifier(value)
    except Rejected:
        return None


def sanitize(section, raw):
    """A whitelist, not a recursive key blacklist. Unknown keys/text are discarded."""
    require(section in SECTIONS, 'unknown_section')
    if type(raw) is not dict:
        return {}, 'unknown'
    data, state = {}, 'fresh'
    if section == 'player':
        for key, low, high in [('x', -30e6, 30e6), ('y', -2048, 2048), ('z', -30e6, 30e6),
                              ('health', 0, 2048), ('food', 0, 20)]:
            data[key] = _number(raw, key, low, high)
        for key in ('alive', 'grounded', 'screen_closed'):
            data[key] = _bool(raw, key)
        if any(data[k] is None for k in ('x', 'y', 'z', 'health', 'alive', 'grounded', 'screen_closed')):
            state = 'unknown'
    elif section == 'terrain':
        cells = raw.get('cells')
        if type(cells) is not list:
            return {'cells': [], 'complete': False}, 'unknown'
        data = {'cells': [], 'complete': raw.get('complete') is True}
        state = 'truncated' if len(cells) > 256 or not data['complete'] or raw.get('truncated') is True else 'fresh'
        seen = set()
        for cell in cells[:256]:
            if type(cell) is not dict:
                state = 'unknown'; continue
            p = {k: _number(cell, k, -30e6 if k != 'y' else -2048, 30e6 if k != 'y' else 2048)
                 for k in ('x', 'y', 'z')}
            if any(type(v) is not int for v in p.values()) or tuple(p.values()) in seen:
                state = 'unknown'; continue
            seen.add(tuple(p.values()))
            loaded = cell.get('loaded') is True
            entry = {**p, 'loaded': loaded, 'block_id': _id(cell.get('block_id'), resource=True)}
            for key in ('passable', 'full_support', 'hazard', 'fluid'):
                entry[key] = _bool(cell, key)
            if not loaded or any(entry[k] is None for k in ('passable', 'full_support', 'hazard', 'fluid')):
                state = 'unknown'
            data['cells'].append(entry)
    elif section == 'entities':
        entries = raw.get('entities')
        if type(entries) is not list:
            return {'entities': []}, 'unknown'
        state = 'truncated' if len(entries) > 32 or raw.get('truncated') is not False else 'fresh'
        data = {'entities': []}
        for entity in entries[:32]:
            if type(entity) is not dict:
                state = 'unknown'; continue
            entity_id = _number(entity, 'entity_id', 0, 2**31 - 1)
            result = {'uuid': _id(entity.get('uuid')), 'type': _id(entity.get('type'), resource=True),
                      'entity_id': entity_id, 'alive': _bool(entity, 'alive'),
                      'attackable': _bool(entity, 'attackable')}
            if None in result.values() or type(entity_id) is not int:
                state = 'unknown'; continue
            data['entities'].append(result)
    elif section == 'inventory':
        items = raw.get('slots')
        if type(items) is not list:
            return {'slots': [], 'complete': False}, 'unknown'
        state = 'truncated' if len(items) > 46 or raw.get('complete') is not True else 'fresh'
        data = {'slots': [], 'complete': raw.get('complete') is True and len(items) <= 46}
        seen_slots = set()
        for item in items[:46]:
            if type(item) is not dict:
                state = 'unknown'; continue
            slot, count = _number(item, 'slot', 0, 45), _number(item, 'count', 0, 9999)
            item_id = _id(item.get('item_id'), resource=True)
            if type(slot) is not int or type(count) is not int or item_id is None or slot in seen_slots:
                state = 'unknown'; continue
            seen_slots.add(slot)
            data['slots'].append({'slot': slot, 'item_id': item_id, 'count': count})
    elif section == 'action':
        status = raw.get('status')
        status = status if status in ('idle', 'running', 'succeeded', 'failed', 'cancelled', 'unknown') else 'unknown'
        data = {'status': status, 'action_id': _id(raw.get('action_id')),
                'input_released': _bool(raw, 'input_released'), 'server_confirmed': False}
        if status == 'unknown' or data['input_released'] is None or (status != 'idle' and data['action_id'] is None):
            state = 'unknown'
    elif section == 'scan':
        status = raw.get('status')
        data = {'scan_id': _id(raw.get('scan_id')), 'status': status if status in
                ('running', 'succeeded', 'failed', 'cancelled') else 'unknown',
                'tested_positions': _number(raw, 'tested_positions', 0, 2**53),
                'complete': _bool(raw, 'complete'), 'historical_only': True}
        state = ('unknown' if data['status'] == 'unknown' or None in data.values() else
                 'truncated' if data['complete'] is False else 'fresh')
    if section in ('terrain', 'inventory') and state != 'fresh':
        data['complete'] = False
    if section == 'entities':
        data['truncated'] = state != 'fresh'
    canonical(data)
    return data, state


@dataclass(frozen=True)
class Acquisition:
    """Owner-supplied ORIGINAL capture interval, never a file read/import timestamp."""
    clock_epoch: str
    start_mono: float | None
    end_mono: float | None
    source_time_ms: float | None
    source_tick: int | None
    source_clock: str = 'fixture_wall'


class SnapshotStore:
    def __init__(self, clock, metrics, *, epoch=None):
        self.clock, self.metrics = clock, metrics
        self.epoch = epoch or uuid.uuid4().hex
        self._lock = RLock()
        self._context = None
        self._sections = {}
        self._revision = 0
        self._sample_id = 0
        self._watermarks = {}
        self._captures = {}
        self._publications = {}
        self._subscriptions = {}

    def publish(self, context, source_id, raw_sections, acquisition, ttl_ms=1500):
        """Only the trusted observation owner publishes. Readers cannot refresh data."""
        require(type(context) is Context and type(acquisition) is Acquisition, 'invalid_observation')
        identifier(source_id)
        require(type(raw_sections) is dict and raw_sections and raw_sections.keys() <= SECTIONS,
                'unknown_section')
        integer(ttl_ms, 50, 3000)
        require(acquisition.source_clock in ('resident_result_finished_wall', 'fixture_wall', 'unknown'), 'source_clock')
        if acquisition.source_tick is not None:
            integer(acquisition.source_tick, 0, 2**63 - 1)
        if acquisition.source_time_ms is not None:
            number(acquisition.source_time_ms, 0, 1e15)
        clean = {key: sanitize(key, raw) for key, raw in raw_sections.items()}
        # Capture identity includes source stamps, excluding the caller's requested TTL.
        digest = hashlib.sha256(canonical({'context': context.wire(), 'sections': clean,
                                          'acquisition': vars(acquisition)})).hexdigest()
        with self._lock:
            if source_id in self._publications:
                require(self._publications[source_id] == digest, 'source_id_payload_conflict')
                self.metrics.count('duplicate_scans' if 'terrain' in clean or 'scan' in clean else 'duplicate_observations')
                return self.read()
            require(len(self._publications) < 4096, 'observation_identity_capacity')
            now = number(self.clock(), 0, 1e15)
            known_interval = (acquisition.clock_epoch == self.epoch and acquisition.start_mono is not None
                              and acquisition.end_mono is not None)
            if known_interval:
                number(acquisition.start_mono, 0, now)
                number(acquisition.end_mono, acquisition.start_mono, now)
            else:
                require(acquisition.start_mono is None and acquisition.end_mono is None,
                        'foreign_monotonic_clock')
            # Pin capture metadata across sections too. Otherwise publishing a
            # previously omitted section under a new label could lengthen the
            # very same capture's TTL. At most two keys per bounded publication
            # are retained, and nothing is evicted while source IDs are retained.
            capture_keys = []
            if known_interval:
                capture_keys.append((context, 'start', acquisition.start_mono))
            if acquisition.source_tick is not None or (
                    acquisition.source_clock != 'unknown' and acquisition.source_time_ms is not None):
                capture_keys.append((context, 'source', acquisition.source_tick,
                                     acquisition.source_time_ms, acquisition.source_clock))
            original = None
            for key in capture_keys:
                if key in self._captures:
                    require(original is None or original is self._captures[key], 'capture_identity_conflict')
                    original = self._captures[key]
            if original is None:
                original = {
                    'context': context.wire(), 'source_id': source_id, 'clock_epoch': self.epoch,
                    'capture_started_mono': acquisition.start_mono,
                    'capture_finished_mono': acquisition.end_mono,
                    'source_time_ms': acquisition.source_time_ms, 'source_tick': acquisition.source_tick,
                    'source_tick_clock': 'native_game_tick', 'source_time_clock': acquisition.source_clock,
                    'expires_mono': acquisition.start_mono + ttl_ms / 1000 if known_interval else None}
            captures = dict(self._captures)
            for key in capture_keys:
                captures[key] = original
            same_context = self._context == context
            sections = dict(self._sections) if same_context else {}
            # Keep provenance high-water marks even after an unknown import. A
            # missing stamp or A -> B -> A context roundtrip must not erase an
            # earlier regression guard. There are at most six section entries
            # per bounded publication.
            watermarks = copy.deepcopy(self._watermarks)
            revision, sample_id = self._revision, self._sample_id
            changed, sampled, continuity_changed = [], [], []
            for name, (payload, quality) in clean.items():
                prior = sections.get(name)
                marks = watermarks.get((context, name), {})
                if known_interval:
                    for stamp, value in (('start', acquisition.start_mono),
                                         ('end', acquisition.end_mono)):
                        if marks.get(stamp) is not None:
                            require(value >= marks[stamp], 'observation_time_reversed')
                if marks.get('tick') is not None and acquisition.source_tick is not None:
                    require(acquisition.source_tick >= marks['tick'], 'source_tick_reversed')
                source_clock = acquisition.source_clock
                comparable_wall = (source_clock != 'unknown' and source_clock == marks.get('source_clock')
                                   and acquisition.source_time_ms is not None)
                if comparable_wall:
                    require(acquisition.source_time_ms >= marks['time'], 'source_time_reversed')

                # A label, TTL change, source tick alone, or a read-time dressed
                # up as capture time cannot renew an already known capture.
                # With source stamps, both the original capture start and at
                # least one comparable source stamp must progress. With no
                # source stamps at all, the trusted owner's original interval
                # is the only available capture identity.
                had_source = marks.get('tick') is not None or marks.get('time') is not None
                source_advanced = (
                    (marks.get('tick') is not None and acquisition.source_tick is not None
                     and acquisition.source_tick > marks['tick']) or
                    (comparable_wall and acquisition.source_time_ms > marks['time']))
                start_advanced = (marks.get('sample_start') is None or
                                  acquisition.start_mono is not None and
                                  acquisition.start_mono > marks['sample_start'])
                new_capture = (prior is None or known_interval and start_advanced and
                               (not had_source or source_advanced))
                # An unclocked publication is allowed to remove freshness, never
                # add it. Preserve its actual unknown interval for consumers.
                unclocked_change = (not known_interval and (prior is None or
                    prior['capture_started_mono'] is not None or
                    prior['source_tick'] != acquisition.source_tick or
                    prior['source_time_ms'] != acquisition.source_time_ms or
                    prior['source_time_clock'] != source_clock))
                replace_sample = new_capture or unclocked_change
                if replace_sample:
                    sample_id += 1
                    sample = {**original, 'sample_id': sample_id}
                    if not known_interval:
                        sample.update(capture_started_mono=None, capture_finished_mono=None,
                                      expires_mono=None)
                    sampled.append(name)
                    if sample['capture_started_mono'] is not None:
                        marks['sample_start'] = sample['capture_started_mono']
                else:
                    sample = {key: value for key, value in prior.items()
                              if key not in ('data', 'quality', 'freshness', 'revision',
                                             'content_revision', 'continuity_revision')}
                effective_quality = quality if known_interval and sample['expires_mono'] is not None else 'unknown'
                content_changed = (prior is None or prior['data'] != payload or
                                   prior['quality'] != effective_quality)
                if content_changed:
                    revision += 1
                    changed.append(name)
                content_revision = revision if content_changed else prior['content_revision']
                freshness = self._freshness(effective_quality, sample['expires_mono'], now)
                continuity = prior['continuity_revision'] if prior else 1
                if prior and self._freshness(prior['quality'], prior['expires_mono'], now) != 'fresh' and (
                        replace_sample or freshness == 'fresh'):
                    continuity += 1
                    continuity_changed.append(name)
                sections[name] = {
                    **sample, 'revision': content_revision, 'content_revision': content_revision,
                    'continuity_revision': continuity, 'quality': effective_quality,
                    'freshness': freshness, 'data': payload}
                if known_interval:
                    marks.update(start=acquisition.start_mono, end=acquisition.end_mono)
                if acquisition.source_tick is not None:
                    marks['tick'] = acquisition.source_tick
                if source_clock != 'unknown' and acquisition.source_time_ms is not None:
                    if marks.get('source_clock') in (None, source_clock):
                        marks.update(source_clock=source_clock, time=acquisition.source_time_ms)
                watermarks[(context, name)] = marks
            # No counters, provenance, content, identities, metrics, or events
            # are committed until every section has passed validation.
            self._sections, self._context, self._revision = sections, context, revision
            self._sample_id, self._watermarks, self._captures = sample_id, watermarks, captures
            self._publications[source_id] = digest
            self.metrics.count('observations')
            if 'terrain' in clean or 'scan' in clean:
                self.metrics.count('scans')
            if known_interval:
                self.metrics.duration('observation', acquisition.start_mono, acquisition.end_mono)
            # The old envelope remains compatible. Consumers can distinguish
            # content changes, sampling changes, and interrupted freshness.
            event = {'kind': 'snapshot_changed', 'revision': self._revision,
                     'sections': list(clean), 'content_changed_sections': changed,
                     'sampled_sections': sampled, 'continuity_changed_sections': continuity_changed}
            for sub in self._subscriptions.values():
                if len(sub['events']) == sub['events'].maxlen:
                    sub['dropped'] += 1
                    self.metrics.count('dropped_events')
                sub['events'].append(event)
            return self.read()

    @staticmethod
    def _freshness(quality, expiry, now):
        if expiry is None:
            return 'unknown'
        return 'stale' if now >= expiry else quality

    def read(self):
        with self._lock:
            result = copy.deepcopy(self._sections)
            now = self.clock()
            for section in result.values():
                section['freshness'] = self._freshness(section['quality'], section['expires_mono'], now)
            return {'schema_version': 1, 'clock_epoch': self.epoch,
                    'context': self._context.wire() if self._context else None,
                    'sections': result, 'missing_sections': sorted(SECTIONS - result.keys()),
                    'read_triggers_observation': False}

    def subscribe(self, capacity=4):
        integer(capacity, 1, 16)
        with self._lock:
            require(len(self._subscriptions) < 32, 'subscriber_capacity')
            token = uuid.uuid4().hex
            self._subscriptions[token] = {'events': deque(maxlen=capacity), 'dropped': 0}
            return token

    def poll(self, token):
        with self._lock:
            require(token in self._subscriptions, 'unknown_subscription')
            sub = self._subscriptions[token]
            result = {'events': copy.deepcopy(list(sub['events'])), 'dropped': sub['dropped'],
                      'resync_required': sub['dropped'] > 0}
            sub['events'].clear(); sub['dropped'] = 0
            return result

    def unsubscribe(self, token):
        with self._lock:
            self._subscriptions.pop(token, None)
