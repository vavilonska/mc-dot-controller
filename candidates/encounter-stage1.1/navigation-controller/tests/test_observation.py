from copy import deepcopy
import unittest
from navigation_controller.fake import FakeWorld, WORLD_ID, PLAYER_ID
from navigation_controller.observation import from_wire
from navigation_controller.terrain import TerrainError


def fixtures():
    world = dict(world_generation=WORLD_ID, dimension='minecraft:overworld', game_time=100, present=True)
    p = dict(uuid=PLAYER_ID, x=.5, y=64, z=.5, yaw=0, pitch=0, present=True,
             dimension='minecraft:overworld', velocity=dict(x=0, y=0, z=0), health=20,
             food=20, on_ground=True, gamemode='survival', effects=[], effects_total=0,
             effects_returned=0, effects_truncated=False, air=300, max_air=300)
    base = dict(ok=True, protocol='mineclient-bridge', schema_version=2)
    status = dict(**base, run_id='offline-simulation', process_id=1, bridge_running=True,
                  in_world=True, player=deepcopy(p), world=deepcopy(world), screen=dict(present=False),
                  mouse=dict(grabbed=True, left_pressed=False, right_pressed=False,
                             middle_pressed=False, held_world_buttons=[]), held_mappings=[])
    state = dict(**base, player=deepcopy(p), world=deepcopy(world),
                 nearby=dict(radius=16, total=0, returned=0, truncated=False, entities=[]))
    return deepcopy(status), state, deepcopy(status)


class ObservationTests(unittest.TestCase):
    def setUp(self):
        self.before, self.state, self.after = fixtures()
        self.grid = FakeWorld().grid()

    def parse(self):
        return from_wire(self.before, self.state, self.after, self.grid, 100)

    def test_actual_state_status_schema(self):
        self.parse().require_safe(100)

    def test_reset_between_statuses_rejected(self):
        self.after['world']['world_generation'] = '00000000-0000-4000-8000-000000000099'
        with self.assertRaises(TerrainError):
            self.parse()

    def test_process_changed_rejected(self):
        self.after['process_id'] = 2
        with self.assertRaises(TerrainError):
            self.parse()

    def test_missing_generation_rejected(self):
        del self.state['world']['world_generation']
        with self.assertRaises(TerrainError):
            self.parse()

    def test_after_status_displacement_rejected(self):
        self.after['player']['x'] = 5.5
        with self.assertRaises(TerrainError):
            self.parse()

    def test_before_status_displacement_rejected(self):
        self.before['player']['z'] = 5.5
        with self.assertRaises(TerrainError):
            self.parse()

    def test_after_status_rotation_rejected(self):
        self.after['player']['yaw'] = 180
        with self.assertRaises(TerrainError):
            self.parse()

    def test_yaw_wrap_equivalent(self):
        self.after['player']['yaw'] = 360
        self.parse().require_safe(100)

    def test_too_wide_tick_bracket(self):
        self.after['world']['game_time'] = 104
        with self.assertRaises(TerrainError):
            self.parse()

    def test_truncated_nearby_blocked(self):
        self.state['nearby']['truncated'] = True
        with self.assertRaises(TerrainError):
            self.parse().require_safe(100)

    def test_small_nearby_radius_blocked(self):
        self.state['nearby']['radius'] = 1
        with self.assertRaises(TerrainError):
            self.parse().require_safe(100)

    def test_nearby_entity_blocked(self):
        self.state['nearby'].update(total=1, returned=1, entities=[{'type': 'minecraft:cow'}])
        with self.assertRaises(TerrainError):
            self.parse().require_safe(100)

    def test_mouse_press_blocked(self):
        self.after['mouse']['left_pressed'] = True
        with self.assertRaises(TerrainError):
            self.parse().require_safe(100)

    def test_nonfinite_position_rejected(self):
        self.state['player']['x'] = float('nan')
        with self.assertRaises(TerrainError):
            self.parse()
