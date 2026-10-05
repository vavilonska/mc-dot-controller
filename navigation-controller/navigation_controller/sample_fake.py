"""Wire-shaped offline transport for guarded sample/turn contract tests only."""
from copy import deepcopy
from dataclasses import replace
import math
import struct
from .executor import wrap_yaw
from .fake import FakeWorld, PLAYER_ID
from .observation import Position
from .terrain import integer, number, uuid


class FakeSampleTransport:
    simulation_only = True

    def __init__(self, clock, world=None):
        self.clock = clock
        self.world = world or FakeWorld()
        self.position = Position(.5, 64, .5)
        self.yaw = 0.0
        self.velocity = Position(0, -.0784, 0)
        self.health = 20.0
        self.session = '00000000-0000-4000-8000-000000000401'
        self.calls = []
        self.actions = []
        self.response_hook = None
        self.state_changes = {}
        self._observation = None
        self._counter = 500
        self._used = set()
        self._motion = []
        self._physics_tick = self.tick
        self.stalled = False
        self.never_settles = False

    @property
    def tick(self):
        return 100 + int(round((self.clock.monotonic() - 100)*20))

    @property
    def identity(self):
        return ('offline-sample-simulation', 1, PLAYER_ID, self.world.generation)

    def _advance(self):
        tick = self.tick
        if tick > self._physics_tick and self._motion:
            distance, speed = self._motion.pop(0)
            a = math.radians(self.yaw)
            self.position = Position(self.position.x-math.sin(a)*distance, self.position.y,
                                     self.position.z+math.cos(a)*distance)
            self.velocity = Position(-math.sin(a)*speed, -.0784, math.cos(a)*speed)
        if self.never_settles:
            self.velocity = Position(.005, -.0784, 0)
        self._physics_tick = tick

    def movement(self):
        return dict(schema_version=1, enabled=True, session=self.session, owner_request_id=None, owner_action=None,
                    sampled=False, released=True, admission_open=True, requests_remaining=4096-len(self._used),
                    max_duration_ms=100, max_ttl_ms=250, max_input_samples=1, forward_impulse=.5,
                    local_unpublished_survival_only=True, held_keys=False, turn_supported=True)

    def turning(self):
        return dict(schema_version=1, enabled=True, max_ttl_ms=100, max_yaw_step=30.0,
                    held_input=False, local_unpublished_survival_only=True,
                    shared_movement_observation=True, pitch_supported=False)

    def _base(self):
        return dict(ok=True, protocol='mineclient-bridge', schema_version=2)

    def _world(self):
        return dict(world_generation=self.world.generation, dimension='minecraft:overworld', game_time=self.tick)

    def _player(self):
        p = dict(uuid=PLAYER_ID, dimension='minecraft:overworld', x=self.position.x, y=self.position.y,
                 z=self.position.z, yaw=self.yaw, pitch=0.0, health=self.health, max_health=20.0,
                 food=20, air=300, max_air=300, on_ground=True, gamemode='survival',
                 effects=[], effects_total=0, effects_returned=0, effects_truncated=False,
                 velocity=dict(x=self.velocity.x, y=self.velocity.y, z=self.velocity.z))
        p.update(deepcopy(self.state_changes))
        return p

    def _status(self):
        return dict(**self._base(), run_id=self.identity[0], process_id=1, bridge_running=True, in_world=True,
                    world=dict(**self._world(), present=True), player=dict(**self._player(), present=True),
                    screen=dict(present=False), mouse=dict(grabbed=True, left_pressed=False,
                    right_pressed=False, middle_pressed=False, held_world_buttons=[]), held_mappings=[],
                    guarded_movement=self.movement(), guarded_turn=self.turning())

    def _state(self):
        self._counter += 1
        challenge = f'00000000-0000-4000-8000-{self._counter:012d}'
        gm = self.movement()
        gm.update(observation_id=challenge, observation_yaw=wrap_yaw(self.yaw), max_observation_age_ms=150)
        result = dict(**self._base(), player=self._player(), world=self._world(),
                      nearby=dict(radius=4.0, total=0, returned=0, truncated=False, entities=[]),
                      guarded_movement=gm, guarded_turn=self.turning())
        self._observation = (deepcopy(result), self.clock.monotonic())
        return result

    def request(self, method, path, body=None):
        self._advance()
        self.calls.append((method, path, deepcopy(body)))
        if method == 'GET' and path == '/control/capabilities':
            result = dict(**self._base(), guarded_movement=self.movement(), guarded_turn=self.turning())
        elif method == 'GET' and path == '/control/status':
            result = self._status()  # Does not renew the /state challenge.
        elif method == 'GET' and path == '/control/state?radius=4':
            result = self._state()
        elif method == 'GET' and path == '/control/terrain?radius=1&vertical=1&limit=128':
            result = self.world.pages(origin=self.position.block(), radius=1, vertical=1, tick=self.tick)[0]
        elif method == 'POST' and path in ('/control/guarded-movement', '/control/guarded-turn'):
            result = self._action(path, body)
        else:
            raise ValueError('unexpected fake transport route')
        if self.response_hook:
            result = self.response_hook(method, path, deepcopy(body), result)
        return result

    def _action(self, path, body):
        if self._observation is None:
            raise ValueError('missing fake challenge')
        state, issued = self._observation
        gm, player, world = state['guarded_movement'], state['player'], state['world']
        common = {'session', 'request_id', 'observation_id', 'expected_world_generation', 'expected_player_uuid',
                  'expected_tick', 'expected_x', 'expected_y', 'expected_z', 'expected_yaw', 'ttl_ms', 'action'}
        is_move = path == '/control/guarded-movement'
        fields = common | ({'movement_schema_version', 'duration_ms'} if is_move else {'turn_schema_version', 'target_yaw'})
        if set(body) != fields:
            raise ValueError('fake request field mismatch')
        for key in ('request_id','session','observation_id','expected_world_generation','expected_player_uuid'):
            uuid(body[key])
        integer(body['expected_tick'],0,9_007_199_254_740_991)
        integer(body['ttl_ms'],1,250 if is_move else 100)
        integer(body['movement_schema_version' if is_move else 'turn_schema_version'],1,1)
        if is_move:
            integer(body['duration_ms'],1,min(100,body['ttl_ms']))
        else:
            if not -180 <= number(body['target_yaw']) < 180:
                raise ValueError('fake target yaw invalid')
        for key in ('expected_x','expected_y','expected_z'):
            if abs(number(body[key])) > 30_000_000:
                raise ValueError('fake position invalid')
        if not -180 <= number(body['expected_yaw']) < 180:
            raise ValueError('fake yaw invalid')
        if body['request_id'] in self._used or body['session'] != self.session or body['observation_id'] != gm['observation_id']:
            raise ValueError('replayed or stale fake request')
        self._observation = None
        self._used.add(body['request_id'])
        if not 0 <= self.clock.monotonic()-issued < .15:
            raise ValueError('expired fake observation')
        expected = dict(expected_world_generation=world['world_generation'], expected_player_uuid=player['uuid'],
                        expected_tick=world['game_time'], expected_x=player['x'], expected_y=player['y'],
                        expected_z=player['z'], expected_yaw=gm['observation_yaw'])
        if any(body[k] != v for k, v in expected.items()) or not 1 <= body['ttl_ms'] <= (250 if is_move else 100):
            raise ValueError('fake observed pose mismatch')
        self.actions.append(deepcopy(body))
        if is_move:
            if body['action'] != 'forward_sample' or body['movement_schema_version'] != 1 or not 1 <= body['duration_ms'] <= min(100, body['ttl_ms']):
                raise ValueError('fake movement schema mismatch')
            # Exactly one fixed illustrative sample. Duration does not scale it.
            self._motion = [] if self.stalled else [(.08, .01), (.02, .002), (.003, .0005), (0, 0)]
            self.clock.sleep(.05)
            self._advance()
            return dict(**self._base(), movement_schema_version=1, request_id=body['request_id'],
                        sampled=True, released=True, movement_confirmed=False)
        if (body['action'] != 'yaw' or body['turn_schema_version'] != 1
                or not -180 <= body['target_yaw'] < 180 or abs(wrap_yaw(body['target_yaw']-self.yaw)) > 30):
            raise ValueError('fake turn schema mismatch')
        rounded = wrap_yaw(struct.unpack('!f',struct.pack('!f',body['target_yaw']))[0])
        if abs(wrap_yaw(rounded-self.yaw)) > 30:
            raise ValueError('rounded fake yaw exceeds step')
        self.yaw = rounded
        return dict(**self._base(), turn_schema_version=1, request_id=body['request_id'],
                    dispatched=True, released=True, turn_confirmed=False)
