import copy
from mdcoord import Acquisition, Context, Grant
from mdcoord.threats import ThreatClearance


class Clock:
    def __init__(self):
        self.now = 100.0
    def __call__(self):
        return self.now
    def step(self, seconds):
        self.now += seconds


CONTEXT = Context('minecraft:overworld', '11111111-1111-1111-1111-111111111111',
                  '22222222-2222-2222-2222-222222222222', '33333333-3333-3333-3333-333333333333',
                  'resident-test')
TARGET = '44444444-4444-4444-4444-444444444444'


def grant(**changes):
    values = dict(task_id='test-task', context=CONTEXT, allowed_kinds=frozenset({'follow_path', 'defend_entity'}),
                  bounds=(-4, 63, -4, 20, 65, 4), allowed_targets=frozenset({TARGET}),
                  max_actions=16, execution_budget_ms=15000, duration_ms=20_000, lease_ms=15_000,
                  allow_defense_preemption=True, max_cancellations=2)
    values.update(changes)
    return Grant(**values)


def player(x=.5):
    return {'x': x, 'y': 64, 'z': .5, 'health': 20, 'food': 20, 'alive': True,
            'grounded': True, 'screen_closed': True}


def sections():
    cells = []
    for x in range(18):
        for y in (63, 64, 65):
            cells.append({'x': x, 'y': y, 'z': 0, 'loaded': True,
                          'block_id': 'minecraft:stone' if y == 63 else 'minecraft:air',
                          'passable': y > 63, 'full_support': y == 63, 'hazard': False, 'fluid': False})
    return {'player': player(), 'terrain': {'cells': cells, 'complete': True},
            'entities': {'entities': [{'uuid': TARGET, 'entity_id': 7, 'type': 'minecraft:zombie',
                                       'alive': True, 'attackable': True}], 'truncated': False},
            'inventory': {'slots': [{'slot': 0, 'count': 1, 'item_id': 'minecraft:stone_sword'}], 'complete': True},
            'action': {'status': 'idle', 'input_released': True, 'action_id': None}}


def publish_synthetic_clearance(owner, snapshot, acquisition, *, proof_id, ttl=3000):
    """Independent test simulator assertion, never inferred from entity entries.

    The synthetic scenario explicitly stipulates no threats capable of reaching
    the x=.5..17.5, y=64, z=.5 corridor, even though a zombie elsewhere is listed
    to exercise defense. Resident imports and production snapshots do not call
    this helper. It intentionally says nothing about routes outside this strip.
    """
    entities = snapshot['sections'].get('entities')
    if (entities is None or entities['freshness'] != 'fresh' or
            acquisition.clock_epoch != owner.snapshots.epoch or
            acquisition.source_clock != 'fixture_wall'):
        return
    owner.threats.publish(ThreatClearance(
        proof_id=proof_id, context=Context.parse(snapshot['context']),
        entities_sample_id=entities['sample_id'], entities_content_revision=entities['content_revision'],
        acquisition=acquisition,
        ttl_ms=ttl, complete=True, no_threats=True, valid=True,
        bounds=(.5, 64, .5, 17.5, 64, .5)))


def publish(owner, source='obs1', data=None, *, context=CONTEXT, ttl=3000, tick=10, capture=None,
            threat_clearance=True):
    raw = data if data is not None else sections()
    acquisition = capture or Acquisition(owner.snapshots.epoch, owner.clock(), owner.clock(),
                                         1_700_000_000_000, tick)
    snapshot = owner.snapshots.publish(context, source, raw, acquisition, ttl_ms=ttl)
    if threat_clearance and 'entities' in raw:
        publish_synthetic_clearance(owner, snapshot, acquisition, proof_id=source + '-clearance', ttl=ttl)
    return snapshot


def proposal(owner, pid='plan1', *, start=.5, end=1.5, dependencies=(), kind='follow_path', priority=10):
    snapshot, lease = owner.snapshots.read(), owner.lease_state()
    intent = {'kind': kind, 'timeout_ms': 1000}
    if kind == 'follow_path':
        intent['waypoints'] = [{'x': end, 'y': 64, 'z': .5}]
        refs = {'terrain': snapshot['sections']['terrain']['revision']}
    else:
        intent.update(target_uuid=TARGET, target_entity_id=7, target_type='minecraft:zombie')
        refs = {'entities': snapshot['sections']['entities']['revision']}
    return {'proposal_id': pid, 'task_id': lease['task_id'], 'epoch': lease['epoch'],
            'lease_revision': lease['revision'], 'role': 'route_planner', 'context': snapshot['context'],
            'based_on': refs, 'ttl_ms': 3000, 'intent': intent, 'dependencies': list(dependencies),
            'priority': priority, 'preconditions': {'alive': True, 'grounded': True,
                'screen_closed': True, 'min_health': 5,
                'expected_position': {'x': start, 'y': 64, 'z': .5} if kind == 'follow_path' else None},
            'cancel_requested': False}
