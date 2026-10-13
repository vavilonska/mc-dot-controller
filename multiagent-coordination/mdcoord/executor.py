"""Dry-run executor and a pure resident-command compiler; no IPC or HTTP imports."""
from __future__ import annotations

from dataclasses import dataclass
from threading import RLock
import copy

from .schema import Context, intent, identifier, require


@dataclass(frozen=True)
class Receipt:
    action_id: str
    request_id: str
    context: Context
    kind: str
    status: str
    inputs_released: bool
    postcondition_observed: bool
    native_ticks: int | None = None
    server_confirmed: bool = False


def compile_resident_command(value, context):
    """Returns data for review only. It never creates a QueueClient or submits."""
    action = intent(value)
    body = {'op': 'action', 'action': 'follow_path' if action['kind'] == 'follow_path' else 'combat_entity',
            'timeout_ms': action['timeout_ms'], 'expected_world_generation': context.world_generation,
            'expected_action_session': context.action_session}
    if action['kind'] == 'follow_path':
        body['waypoints'] = copy.deepcopy(action['waypoints'])
    else:
        body.update(expected_player_uuid=context.player_id, target_uuid=action['target_uuid'],
                    target_entity_id=action['target_entity_id'], target_type=action['target_type'],
                    approach=False, shield=True)
    return body


class ResidentAdapter:
    """Intentional hard gate until sole-owner, native receipts and fencing are integrated."""
    dry_run = True

    def prepare(self, value, context):
        return compile_resident_command(value, context)

    def dispatch(self, *args):
        raise RuntimeError('live_adapter_not_integrated')

    def poll(self, *args):
        raise RuntimeError('live_adapter_not_integrated')

    def cancel(self, *args):
        raise RuntimeError('live_adapter_not_integrated')


class FakeExecutor:
    """Deterministic contract fixture, NOT a simulation of Minecraft or its physics."""
    dry_run = True

    def __init__(self):
        self._lock = RLock()
        self.receipts = {}
        self.dispatches = []
        self.cancellations = []
        self.active_id = None
        self.max_writers = 0
        self.fail_after_dispatch = False
        self.cancel_confirms = True

    def dispatch(self, action_id, request_id, value, context):
        identifier(action_id); identifier(request_id)
        action = intent(value)
        with self._lock:
            require(self.active_id is None, 'fake_multiple_writer')
            require(action_id not in self.receipts, 'fake_action_replayed')
            self.active_id = action_id
            self.max_writers = max(self.max_writers, 1)
            self.dispatches.append((action_id, request_id, compile_resident_command(action, context)))
            receipt = Receipt(action_id, request_id, context, action['kind'], 'running', False, False)
            self.receipts[action_id] = receipt
            if self.fail_after_dispatch:
                raise TimeoutError('synthetic_response_lost')
            return receipt

    def poll(self, action_id, request_id, context):
        with self._lock:
            return self.receipts.get(action_id)

    def cancel(self, action_id, request_id, context):
        with self._lock:
            self.cancellations.append(action_id)
            current = self.receipts.get(action_id)
            if current is None or not self.cancel_confirms:
                return None
            if current.status != 'running':
                return current
            return self.finish(action_id, status='cancelled', postcondition=False)

    def finish(self, action_id, *, status='succeeded', postcondition=True, released=True, ticks=5):
        with self._lock:
            old = self.receipts[action_id]
            receipt = Receipt(old.action_id, old.request_id, old.context, old.kind, status,
                              released, postcondition, ticks)
            self.receipts[action_id] = receipt
            if released:
                self.active_id = None
            return receipt
