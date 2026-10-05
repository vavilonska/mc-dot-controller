"""Read-only parser for actual bridge status/state fields; no transport."""
from dataclasses import dataclass
import math
from .terrain import Block, TerrainError, TerrainGrid, WorldStamp, integer, number, protocol, uuid


@dataclass(frozen=True)
class Position:
    x: float
    y: float
    z: float

    def __post_init__(self):
        for value in (self.x, self.y, self.z):
            number(value)
            if abs(value) > 30_000_000:
                raise TerrainError('position_out_of_bounds')

    def block(self):
        return Block(math.floor(self.x), math.floor(self.y), math.floor(self.z))

    def distance(self, other):
        return math.dist((self.x, self.y, self.z), (other.x, other.y, other.z))

    @classmethod
    def parse(cls, obj):
        return cls(*(number(obj[k]) for k in ('x', 'y', 'z')))


@dataclass(frozen=True)
class Observation:
    world: WorldStamp
    run_id: str
    process_id: int
    player_uuid: str
    position: Position
    yaw: float
    terrain: TerrainGrid
    captured_at: float
    health: float = 20.0
    food: int = 20
    on_ground: bool = True
    neutral_inputs: bool = True
    screen_open: bool = False
    mouse_grabbed: bool = True
    survival: bool = True
    effects_clear: bool = True
    air_full: bool = True
    nearby_clear: bool = True
    horizontal_speed: float = 0.0

    @property
    def identity(self):
        return self.run_id, self.process_id, self.player_uuid, self.world.generation

    def require_safe(self, now):
        uuid(self.player_uuid)
        integer(self.process_id, 1)
        if not isinstance(self.run_id, str) or not self.run_id or len(self.run_id) > 160:
            raise TerrainError('invalid_run_identity')
        number(self.yaw)
        if not 0 <= number(now) - number(self.captured_at) <= 0.3:
            raise TerrainError('stale_observation')
        self.terrain.require_fresh(self.world, now, max_age_ticks=2, max_wall_age=0.3)
        if self.terrain.origin != self.position.block():
            raise TerrainError('terrain_origin_mismatch')
        if (self.screen_open is not False or self.mouse_grabbed is not True
                or self.neutral_inputs is not True or self.on_ground is not True
                or self.survival is not True or self.effects_clear is not True
                or self.air_full is not True or self.nearby_clear is not True):
            raise TerrainError('unsafe_player_state')
        if number(self.health) < 10 or integer(self.food, 0, 20) < 8 or not 0 <= number(self.horizontal_speed) <= 0.02:
            raise TerrainError('unsafe_health_hunger_or_motion')
        if abs(self.position.y - round(self.position.y)) > 0.03:
            raise TerrainError('non_full_block_standing_height')
        if not self.terrain.standable(self.position.block()):
            raise TerrainError('unsupported_player_position')


def from_wire(before, state, after, terrain, captured_at):
    """Parse status → terrain pages → state → status from an external reader.

    Does not claim singleplayer status: the current status schema does not expose
    it. The executor remains simulation-only independently of this parser.
    """
    try:
        for item in (before, state, after):
            protocol(item)
        p, world = state['player'], WorldStamp.parse(state['world'])
        identity = (before['run_id'], integer(before['process_id'], 1), uuid(before['player']['uuid']))
        if not isinstance(identity[0], str) or not identity[0] or len(identity[0]) > 160:
            raise TerrainError('invalid_run_identity')
        for status in (before, after):
            if (status.get('in_world') is not True or status.get('bridge_running') is not True
                    or status['world'].get('present') is not True or status['player'].get('present') is not True
                    or (status['run_id'], status['process_id'], status['player']['uuid']) != identity
                    or not WorldStamp.parse(status['world']).same_world(world)):
                raise TerrainError('session_changed')
        first_tick = integer(before['world']['game_time'], 0)
        last_tick = integer(after['world']['game_time'], 0)
        if not first_tick <= world.tick <= last_tick or last_tick - first_tick > 3:
            raise TerrainError('inconsistent_observation_ticks')
        if p['uuid'] != identity[2] or p['dimension'] != world.dimension:
            raise TerrainError('player_identity_mismatch')
        for key in ('on_ground', 'effects_truncated'):
            if type(p.get(key)) is not bool:
                raise TerrainError('invalid_player_boolean')
        nearby = state['nearby']
        # Bounds and entity body shapes are not exposed. Any nearby entity blocks
        # this initial executor, including tame animals; never infer free passage.
        nearby_clear = (nearby.get('truncated') is False and nearby.get('entities') == []
                        and type(nearby.get('total')) is int and nearby['total'] == 0
                        and type(nearby.get('returned')) is int and nearby['returned'] == 0
                        and number(nearby['radius']) >= 4)
        neutral, screen_open, grabbed = True, False, True
        for status in (before, after):
            mouse = status['mouse']
            if type(status['screen'].get('present')) is not bool or type(mouse.get('grabbed')) is not bool:
                raise TerrainError('invalid_status_boolean')
            screen_open |= status['screen']['present']
            grabbed &= mouse['grabbed']
            neutral &= status.get('held_mappings') == [] and mouse.get('held_world_buttons') == []
            neutral &= all(mouse.get(k) is False for k in ('left_pressed', 'right_pressed', 'middle_pressed'))
        # Idle observation brackets must not hide displacement or view changes.
        state_position = Position.parse(p)
        state_yaw = number(p['yaw'])
        for status in (before, after):
            status_player = status['player']
            yaw_delta = (number(status_player['yaw']) - state_yaw + 180) % 360 - 180
            if Position.parse(status_player).distance(state_position) > 0.01 or abs(yaw_delta) > 0.1:
                raise TerrainError('player_moved_during_observation')
        speed = Position.parse(p['velocity'])
        return Observation(world, *identity, Position.parse(p), number(p['yaw']), terrain, number(captured_at),
                           number(p['health']), integer(p['food'], 0, 20), p['on_ground'], neutral,
                           screen_open, grabbed, p.get('gamemode') == 'survival',
                           p['effects_truncated'] is False and p.get('effects') == []
                           and p.get('effects_total') == 0 and p.get('effects_returned') == 0,
                           integer(p['air']) >= integer(p['max_air'], 1), nearby_clear,
                           math.hypot(speed.x, speed.z))
    except (KeyError, TypeError, ValueError):
        raise TerrainError('invalid_or_unsafe_wire_observation') from None
