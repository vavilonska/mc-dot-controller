from copy import deepcopy
import uuid

SESSION = '12345678-1234-1234-1234-123456789abc'
NATIVE = '87654321-4321-4321-4321-cba987654321'

class Clock:
    def __init__(self): self.now = 100.0
    def __call__(self): return self.now
    def sleep(self, value): self.now += value


def state(tick=100, x=.5):
    inv = [{'slot': i, 'id': 'minecraft:air', 'count': 0, 'empty': True,
            'damage': 0, 'item_fingerprint': 'item-' + str(i)} for i in range(36)]
    return {'focused': True, 'private_singleplayer': True, 'screen_open': False, 'paused': False,
        'held_inputs': {'neutral': True, 'keys': [], 'raw_keys': 0},
        'capability_guard': {'schema_version': 1, 'source_tick': tick, 'source_nano': '100000000000'},
        'world': {'world_generation': 'world-one', 'dimension': 'minecraft:overworld', 'game_time': tick,
            'navigation_guard': {'schema_version': 1, 'epoch': 4, 'rebind_ready': True, 'fresh_binding_required': False, 'stable_ticks': 3}},
        'player': {'uuid': 'player-one', 'dimension': 'minecraft:overworld', 'alive': True, 'health': 20,
            'x': x, 'y': 64, 'z': .5, 'selected_slot': 0, 'inventory': inv, 'mainhand': inv[0],
            'inventory_truncated': False, 'food': 20, 'on_ground': True},
        'client_action': {'action_session': NATIVE, 'action_id': None, 'status': 'idle'}}


class Client:
    def __init__(self, clock):
        self.clock = clock
        self.session_id = SESSION
        self.tick = 100
        self.x = .5
        self.calls = []
        self.results = {}
        self.mode = None
        self.patch_state = lambda s: s
        self.patch_result = lambda r: r
        self.epoch = None
        self.pending = 0
        self.fail_after_submit = False
        self.action_count = 0
        self.native = None

    def session(self):
        data = {'session_id': self.session_id, 'state': 'ready', 'pending': self.pending}
        if self.epoch is not None: data['defense_epoch'] = self.epoch
        return data

    def submit(self, command, request_id):
        self.calls.append((deepcopy(command), request_id))
        if command['op'] == 'action':
            self.action_count += 1
        if self.fail_after_submit and command['op'] == 'action':
            raise OSError('lost')
        self.results[request_id] = command
        return request_id

    def wait(self, request_id, timeout):
        command = self.results[request_id]
        self.clock.now += .001
        if command['op'] == 'observe':
            self.tick += 1
            s = self.patch_state(state(self.tick, self.x))
            if self.native is not None: s['client_action'] = deepcopy(self.native)
            result = {'state': s}
            if command.get('terrain'): result['terrain'] = {'complete': True, 'cells': [], 'radius': command['radius']}
        else:
            if self.mode == 'pending': return {'request_id': request_id, 'status': 'pending'}
            self.x += 1
            native = {'action_session': NATIVE, 'action_id': uuid.uuid5(uuid.UUID(SESSION), request_id + ':1').hex,
                'action': command['action'], 'status': 'succeeded', 'reason': 'test_action',
                'result': {'input_release_confirmed': True}, 'server_confirmed': False}
            self.native = deepcopy(native)
            result = {'action': native, 'state': self.patch_state(state(self.tick, self.x))}
        return self.patch_result({'request_id': request_id, 'session_id': self.session_id,
                                 'status': 'succeeded', 'result': result})

    def result(self, request_id):
        if self.mode == 'pending': return None
        return self.wait(request_id, 0)


def move():
    return {'op': 'action', 'action': 'follow_path', 'waypoints': [{'x': 1.5, 'y': 64, 'z': .5}], 'timeout_ms': 1000}


def arrived(before, after):
    return after.player['x'] == before.player['x'] + 1
