"""The command line deliberately exposes OFFLINE DEMO ONLY in stage one."""
import argparse
import json
from .core import Config, Controller
from .fake import FakeBridge, FakeClock


def main():
    parser = argparse.ArgumentParser(description='Offline fake-state combat demo; never connects to Minecraft')
    parser.add_argument('--demo', action='store_true', help='run an explicitly enabled fake session')
    args = parser.parse_args()
    clock = FakeClock()
    bridge = FakeBridge(clock)
    result = Controller(bridge, Config(enabled=args.demo, session_seconds=4, action_budget=3), clock).run()
    print(json.dumps({
        'offline_only': True, 'reason': result.reason, 'attempted_actions': result.actions,
        'attempted_attacks': result.attacks, 'fake_release_confirmed': result.release_confirmed,
        'events': [{'phase': e.phase.value, 'reason': e.reason, 'elapsed': round(e.elapsed, 3)} for e in result.events],
    }, indent=2))


if __name__ == '__main__':
    main()
