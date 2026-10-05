"""Deterministic fake only. No sockets, credentials, game or external state."""
from dataclasses import replace
from .core import Entity, Snapshot, Vec3


class FakeClock:
    def __init__(self):
        self.now = 100.0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


def safe_snapshot(clock, **changes):
    target = Entity('fake-zombie-uuid', 'minecraft:zombie', Vec3(0, 64, 2), True, 20.0)
    state = Snapshot(
        captured_at=clock.monotonic(), identity=('offline-fake-run', 123, 'fake-player', 'minecraft:overworld'),
        generation='offline-world-generation', tick=100, position=Vec3(0, 64, 0),
        velocity=Vec3(0, 0, 0), yaw=0, pitch=0, health=20, food=20, air=300, max_air=300,
        on_ground=True, gamemode='survival', weapon='minecraft:iron_axe', entities=(target,),
        crosshair_uuid=target.uuid, crosshair_kind=target.kind, crosshair_location=Vec3(0, 64.9, 2),
        terrain_safe=True, terrain_reason='offline_fake_fixture',
    )
    return replace(state, **changes)


class FakeBridge:
    def __init__(self, clock, snapshots=None):
        self.clock = clock
        self.snapshots = snapshots
        self.calls = []
        self.looks = []
        self.attack_times = []
        self.release_count = 0
        self.observe_count = 0
        self.fail_attack = False
        self.fail_observe = False
        self.fail_release = False

    def observe(self):
        self.calls.append('observe')
        self.observe_count += 1
        if self.fail_observe:
            raise RuntimeError('simulated transport failure')
        if callable(self.snapshots):
            return self.snapshots(self.observe_count)
        if self.snapshots:
            return self.snapshots[min(self.observe_count - 1, len(self.snapshots) - 1)]
        return safe_snapshot(self.clock, tick=100 + int((self.clock.now - 100) * 20))

    def look(self, yaw, pitch, context):
        self.calls.append('look')
        self.looks.append((yaw, pitch))

    def attack(self, context):
        self.calls.append('attack')
        self.attack_times.append(self.clock.monotonic())
        if self.fail_attack:
            raise RuntimeError('simulated uncertain attack response')

    def release_all(self):
        self.calls.append('release_all')
        self.release_count += 1
        if self.fail_release:
            raise RuntimeError('simulated failed cleanup')
        return True
