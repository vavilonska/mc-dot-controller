"""Explicit owner-run loader. No default gateway path and no direct queue client."""
import argparse
import json
from pathlib import Path
import sys
import time
from navigation_cursor import Navigator


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--adapter-dir', required=True, type=Path,
                        help='Verified watchdog source directory containing intent_client.py')
    parser.add_argument('--gateway', required=True, type=Path,
                        help='Verified running watchdog control directory, never the resident mailbox')
    parser.add_argument('--checkpoint', required=True, type=Path)
    parser.add_argument('--target', required=True, nargs='+', type=int, metavar='COORD')
    parser.add_argument('--slice-size', type=int, default=None,
                        help='Explicit 1..32 waypoint limit; default follows the observed safe prefix (up to 32)')
    parser.add_argument('--radius', type=int, default=4)
    parser.add_argument('--vertical', type=int, default=4, help='Use >4 only after verified wrapper upgrade')
    args = parser.parse_args()
    sys.path.insert(0, str(args.adapter_dir.resolve()))
    from intent_client import IntentClient
    gateway = IntentClient(args.gateway)
    nav = Navigator(gateway, args.checkpoint, slice_size=args.slice_size, radius=args.radius, vertical=args.vertical)
    previous = None
    while True:
        result = nav.tick(args.target)
        display = {k: v for k, v in result.items() if k != 'request_id'}
        if display != previous:
            print(json.dumps(result), flush=True)
            previous = display
        if result['status'] in ('complete', 'blocked'):
            return 0 if result['status'] == 'complete' else 2
        # A paused watchdog requires its operator; this loader must not rearm it.
        if result['status'] == 'waiting' and gateway.session().get('state') in ('paused', 'stopped'):
            return 3
        time.sleep(.15)


if __name__ == '__main__':
    raise SystemExit(main())
