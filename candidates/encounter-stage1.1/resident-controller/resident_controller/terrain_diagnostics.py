"""Bounded, observation-only timings for one terrain refresh.

No network calls, sleeps, retries, policy decisions or payload serialization here.
Times share Python's monotonic clock; Java durations are reported, not subtracted.
"""
from __future__ import annotations

from contextlib import contextmanager
import math

from .transport import Bridge, BridgeError


def _scalar(value):
    # Never retain a response object, cells, cursor, credentials or arbitrary text.
    if type(value) in (int, bool) or value is None:
        return value
    if type(value) is str and len(value) <= 160:
        return value
    return None


def rejection(exc):
    # Even a hostile exception formatter/property must not mask the original error.
    result = {'type': type(exc).__name__, 'message': None,
              'message_truncated': False, 'message_status': 'unknown'}
    try:
        message = str(exc)
        result.update(message=message[:512], message_truncated=len(message) > 512,
                      message_status='observed')
    except Exception:
        result['message_status'] = 'unknown_format_error'
    try:
        if hasattr(exc, 'detail'):
            result['detail'] = _scalar(exc.detail)
            result['refreshable'] = _scalar(exc.refreshable)
        if isinstance(exc, BridgeError):
            result.update(code=_scalar(exc.code), http_status=_scalar(exc.status),
                          uncertain=_scalar(exc.uncertain))
    except Exception:
        result['detail_status'] = 'unknown_attribute_error'
    return result


class ScanDiagnostics:
    """At most 2 attempts / 32 pages each, bounded by the unchanged scan loop."""
    def __init__(self, clock, started, deadline):
        self.clock, self.started, self.deadline = clock, started, deadline
        self.attempt = None
        self.phase = 'scan_start'
        self.data = {
            'schema_version': 1, 'clock': 'python_monotonic',
            'time_origin': 'scan_start', 'total_budget_ms': (deadline - started) * 1000,
            'actual_attempts': 0, 'attempts_entered': 0, 'attempts': [],
            'total_elapsed_ms': None, 'remaining_total_ms': None,
            'network_elapsed_ms': None, 'http_queue_elapsed_ms': None,
            'python_cpu_elapsed_ms': None, 'attribution_status': 'unknown',
            'clock_observation_errors': 0,
        }

    def now(self):
        try:
            value = self.clock()
            if type(value) in (int, float) and math.isfinite(value):
                return value
        except Exception:
            pass
        self.data['clock_observation_errors'] += 1
        return None

    @staticmethod
    def elapsed(start, end):
        if start is None or end is None or end < start:
            return None
        return round((end - start) * 1000, 3)

    def offset(self, when):
        return self.elapsed(self.started, when)

    def remaining(self, when):
        return None if when is None else round((self.deadline - when) * 1000, 3)

    def enter_attempt(self, number):
        now = self.now()
        self.attempt = {
            'attempt': number, 'initial_state_requested': False,
            'started_offset_ms': self.offset(now), 'budget_at_entry_ms': self.remaining(now),
            'elapsed_ms': None, 'remaining_total_ms': None,
            'assembler_budget_ms': None, 'stages': [], 'outcome': 'entered',
            'last_rejection': None, 'original_rejection': None, 'rejection_phase': None,
        }
        self._attempt_started = now
        self.data['attempts'].append(self.attempt)
        self.data['attempts_entered'] += 1

    def at(self, phase):
        self.phase = phase

    @contextmanager
    def stage(self, phase, page=None):
        self.phase = phase
        record = {'phase': phase, 'page': page, 'start_offset_ms': None,
                  'end_offset_ms': None, 'elapsed_ms': None,
                  'remaining_total_at_start_ms': None, 'remaining_total_at_end_ms': None,
                  'attempt_elapsed_at_end_ms': None, 'timing_status': 'unknown',
                  'outcome': 'running', 'original_rejection': None}
        self.attempt['stages'].append(record)
        start = self.now()
        record['start_offset_ms'] = self.offset(start)
        record['remaining_total_at_start_ms'] = self.remaining(start)
        try:
            yield record
        except BaseException as exc:
            # This is observation only: propagate the identical exception instance.
            record['outcome'] = 'raised'
            record['original_rejection'] = rejection(exc)
            raise
        else:
            record['outcome'] = 'returned'
        finally:
            end = self.now()
            record['end_offset_ms'] = self.offset(end)
            record['elapsed_ms'] = self.elapsed(start, end)
            record['remaining_total_at_end_ms'] = self.remaining(end)
            record['attempt_elapsed_at_end_ms'] = self.elapsed(self._attempt_started, end)
            record['timing_status'] = ('unknown_clock_error' if start is None or end is None
                                       else 'clock_reversed' if start < self.started or end < start
                                       else 'measured')

    def request(self, bridge, phase, path, page=None):
        if phase == 'initial_state':
            self.attempt['initial_state_requested'] = True
            self.data['actual_attempts'] += 1
        result = None
        # request() is called exactly once, using the original method/path.
        with self.stage(phase, page) as record:
            record.update(method='GET', route=path.split('?', 1)[0],
                          response_bytes_read=None, response_bytes_status='unknown',
                          http_status=None, roundtrip_ms=None, request_start_offset_ms=None,
                          request_return_offset_ms=None, roundtrip_status='unknown',
                          roundtrip_scope='bridge.request_including_decode_and_close')
            if phase == 'terrain_page':
                record.update(java_read_elapsed_micros=None, java_read_elapsed_status='unknown')
            request_start = self.now()
            try:
                result = bridge.request('GET', path)
            finally:
                request_end = self.now()
                record.update(request_start_offset_ms=self.offset(request_start),
                              request_return_offset_ms=self.offset(request_end),
                              roundtrip_ms=self.elapsed(request_start, request_end),
                              roundtrip_status=('unknown_clock_error'
                                  if request_start is None or request_end is None
                                  else 'clock_reversed' if request_start < self.started or request_end < request_start
                                  else 'measured'))
                # Only our known synchronous transport provides measured raw bytes.
                # Fake/custom clients remain explicitly unknown; never re-encode JSON.
                if type(bridge) is Bridge:
                    metadata = bridge.last_response_metadata
                    record.update(response_bytes_read=metadata['response_bytes_read'],
                                  response_bytes_status=metadata['response_bytes_status'],
                                  http_status=metadata['http_status'],
                                  server_timing=metadata.get('server_timing'))
        if type(result) is dict:
            if phase == 'terrain_page':
                fields = ('offset', 'next_offset', 'returned', 'total_cells', 'complete',
                          'budget_exhausted', 'game_time', 'response_game_time',
                          'generation', 'world_generation', 'dimension')
                record['page_reported'] = {key: _scalar(result.get(key)) for key in fields}
                micros = result.get('read_elapsed_micros')
                valid = type(micros) is int and micros >= 0
                record['java_read_elapsed_micros'] = micros if valid else None
                record['java_read_elapsed_status'] = 'reported_unvalidated' if valid else 'unknown'
            else:
                world = result.get('world')
                record['state_reported'] = {key: _scalar(result.get(key))
                                            for key in ('paused', 'screen_open')}
                record['state_reported']['world'] = {
                    key: _scalar(world.get(key)) if type(world) is dict else None
                    for key in ('world_generation', 'dimension', 'game_time')}
        return result

    def end_attempt(self, when, outcome, reason=None, exc=None):
        self.attempt.update(outcome=outcome, elapsed_ms=self.elapsed(self._attempt_started, when),
                            ended_offset_ms=self.offset(when), remaining_total_ms=self.remaining(when),
                            last_rejection=reason, original_rejection=rejection(exc) if exc else None,
                            rejection_phase=self.phase if exc else None)
        self.data.update(total_elapsed_ms=self.offset(when), remaining_total_ms=self.remaining(when))
