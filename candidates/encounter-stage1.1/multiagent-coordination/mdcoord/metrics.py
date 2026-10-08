"""Bounded measurements: only durations from one clock domain may be subtracted."""
from collections import defaultdict, deque
from threading import RLock
from .schema import require, number, identifier


class Metrics:
    def __init__(self, clock):
        self.clock = clock
        self._lock = RLock()
        self._samples = defaultdict(lambda: deque(maxlen=256))
        self._counts = defaultdict(int)
        self._model_starts = {}
        self._native_ticks = deque(maxlen=256)

    def count(self, name):
        require(name in {'retries', 'cancellations', 'duplicate_scans', 'duplicate_proposals',
                         'dropped_events', 'observations', 'scans', 'reconciliations', 'duplicate_observations'}, 'metric_name')
        with self._lock:
            self._counts[name] += 1

    def duration(self, name, start, end, *, clock_domain='owner_monotonic'):
        require(name in {'queue', 'observation', 'scan', 'dispatch_to_terminal_observation', 'model_wait'}, 'metric_name')
        require(clock_domain == 'owner_monotonic', 'incomparable_clock')
        number(start, 0, 1e15)
        number(end, start, 1e15)
        with self._lock:
            self._samples[name].append((end - start) * 1000)

    def model_start(self, marker):
        identifier(marker)
        with self._lock:
            require(marker not in self._model_starts and len(self._model_starts) < 64, 'model_marker_bound')
            self._model_starts[marker] = self.clock()

    def model_end(self, marker):
        with self._lock:
            require(marker in self._model_starts, 'missing_model_start')
            self.duration('model_wait', self._model_starts.pop(marker), self.clock())

    def native_ticks(self, ticks):
        require(type(ticks) is int and ticks >= 0, 'invalid_native_ticks')
        with self._lock:
            self._native_ticks.append(ticks)

    def snapshot(self):
        with self._lock:
            return {'clock_domain': 'owner_monotonic', 'unit': 'ms', 'retained_samples_per_metric': 256,
                    'durations': {k: list(v) for k, v in self._samples.items()},
                    'counts': dict(self._counts),
                    'native_execution_ms': None, 'native_tick_counts': list(self._native_ticks),
                    'measurement_origin': 'dry_run_contract_only',
                    'model_wait_available': bool(self._samples.get('model_wait')),
                    'speedup_claim': None}
