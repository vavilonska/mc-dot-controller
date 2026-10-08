"""Offline one-sample wire-contract demo; no HTTP, game or token access."""
import json
from dataclasses import asdict
from .fake import FakeClock
from .planner import plan
from .sample_adapter import GuardedSampleAdapter, SampleConfig, SampleNavigator
from .sample_fake import FakeSampleTransport
from .terrain import Block, WorldStamp


def main():
    clock = FakeClock()
    transport = FakeSampleTransport(clock)
    world = WorldStamp(transport.world.generation, 'minecraft:overworld', 100)
    result = plan(transport.world.grid(), Block(0,64,0), Block(3,64,0), world, clock.monotonic())
    if result.route is None:
        raise SystemExit(result.reason)
    adapter = GuardedSampleAdapter(transport, clock, transport.identity, SampleConfig(enabled=True))
    outcome = SampleNavigator(adapter).run(result.route)
    print(json.dumps({'mode': 'offline_one_sample_contract', 'lease_is_not_travel_duration': True,
                      'result': asdict(outcome), 'elapsed_fake_seconds': round(clock.now-100,3),
                      'final_fake_position': asdict(transport.position)}, indent=2))
    if outcome.reason != 'arrived':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
