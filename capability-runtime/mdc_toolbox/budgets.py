"""One immutable deadline and ledger shared by every nested skill.

Reserves partition the original total. They never create additional allowance.
"""
from __future__ import annotations
import math
import threading
import time
from mdc_skills.core import SkillError


class SharedBudget:
    METRICS = ('max_actions', 'max_observations', 'reflex_reserve_actions', 'cleanup_reserve_actions')

    def __init__(self, limits, deadline_at, *, wall_clock=time.time, clock=time.monotonic):
        if type(limits) is not dict or set(limits) - set(self.METRICS):
            raise SkillError('unsupported_budget_metric')
        self.limits = dict(limits)
        self.limits.setdefault('max_observations', 1024)
        self.limits.setdefault('reflex_reserve_actions', 0)
        self.limits.setdefault('cleanup_reserve_actions', 1)
        if any(type(v) is not int or v < 0 or v > 100000 for v in self.limits.values()):
            raise SkillError('invalid_shared_budget')
        if self.limits.get('max_actions', 0) < sum(self.limits[k] for k in ('reflex_reserve_actions', 'cleanup_reserve_actions')):
            raise SkillError('reserves_exceed_original_budget')
        if self.limits['max_observations'] < 1:
            raise SkillError('cleanup_observation_reserve_required')
        if type(deadline_at) not in (int, float) or not math.isfinite(deadline_at):
            raise SkillError('invalid_original_deadline')
        self.deadline_at = deadline_at
        self.clock = clock
        self.deadline = clock() + max(0, deadline_at - wall_clock())
        self.used = {lane: {'actions': 0, 'observations': 0} for lane in ('ordinary', 'reflex', 'cleanup')}
        self._lock = threading.RLock()

    def remaining_seconds(self):
        return max(0, self.deadline - self.clock())

    def consume(self, kind='actions', amount=1, lane='ordinary'):
        if kind not in ('actions', 'observations') or lane not in self.used or type(amount) is not int or amount < 0:
            raise SkillError('invalid_budget_charge')
        with self._lock:
            total = sum(row[kind] for row in self.used.values())
            limit = self.limits['max_' + kind]
            if total + amount > limit:
                raise SkillError('original_' + kind + '_budget_exhausted')
            if lane == 'ordinary':
                reserve = (self.limits['reflex_reserve_actions'] + self.limits['cleanup_reserve_actions'] if kind == 'actions' else 1)
                if self.used[lane][kind] + amount > limit - reserve:
                    raise SkillError('ordinary_' + kind + '_budget_exhausted')
            if lane == 'reflex' and kind == 'actions' and self.used[lane][kind] + amount > self.limits['reflex_reserve_actions']:
                raise SkillError('reflex_reserve_exhausted')
            if lane == 'cleanup' and kind == 'actions' and self.used[lane][kind] + amount > self.limits['cleanup_reserve_actions']:
                raise SkillError('cleanup_reserve_exhausted')
            self.used[lane][kind] += amount

    def snapshot(self):
        with self._lock:
            return {'limits': dict(self.limits), 'used': {k: dict(v) for k, v in self.used.items()},
                    'deadline_at': self.deadline_at, 'remaining_seconds': self.remaining_seconds(),
                    'remaining': {k: self.limits['max_' + k] - sum(row[k] for row in self.used.values())
                                  for k in ('actions', 'observations')}}
