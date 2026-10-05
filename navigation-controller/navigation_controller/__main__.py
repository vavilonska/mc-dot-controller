"""Run only the offline obstacle-detour demonstration."""
import json
from .executor import ExecutorConfig, Navigator
from .fake import FakeAdapter, FakeClock, FakeWorld
from .planner import plan
from .terrain import Block, WorldStamp


def main():
    clock, world = FakeClock(), FakeWorld()
    world.set(Block(1, 64, 0))
    grid = world.grid()
    result = plan(grid, Block(0, 64, 0), Block(3, 64, 0),
                  WorldStamp(world.generation, 'minecraft:overworld', 100), clock.monotonic())
    if not result.route:
        raise SystemExit(result.reason)
    adapter = FakeAdapter(clock, world)
    execution = Navigator(adapter, clock, ExecutorConfig(enabled=True)).run(result.route)
    print(json.dumps({'mode': 'offline_fake_only', 'planning': result.reason,
                      'path': [[p.x, p.y, p.z] for p in result.route.nodes],
                      'cost': round(result.route.cost, 3), 'execution': execution.reason,
                      'pulses': execution.pulses, 'all_pulses_at_most_100ms': all(v <= 100 for v in adapter.pulses),
                      'released': execution.released}, indent=2))


if __name__ == '__main__':
    main()
