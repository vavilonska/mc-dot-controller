"""Offline CLI only. There is deliberately no queue, URL, token or live command."""
import argparse
import json
from pathlib import Path
import tempfile

from .adapters import dashboard_view, publish_recorded
from .coordinator import Coordinator
from .demo import run_demo
from .schema import loads, Proposal, Rejected


def _read(path):
    with Path(path).open('rb') as stream:
        return loads(stream.read(64 * 1024 + 1))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('demo', help='Run bounded fake-executor demo in a temporary directory')
    sanitize = commands.add_parser('sanitize-result', help='Read existing result; print a whitelist view without refreshing')
    sanitize.add_argument('file', type=Path)
    sanitize.add_argument('--goal', type=Path, help='Separate maintained goal JSON with its original update time')
    validate = commands.add_parser('check-proposal', help='Syntax check only; does not authorize or dispatch')
    validate.add_argument('file', type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == 'demo':
            output = run_demo()
        elif args.command == 'check-proposal':
            Proposal.parse(_read(args.file))
            output = {'valid_schema': True, 'authorized': False, 'dispatched': False}
        else:
            with tempfile.TemporaryDirectory(prefix='mdcoord-view-') as tmp:
                owner = Coordinator(tmp)
                try:
                    snapshot = publish_recorded(owner.snapshots, _read(args.file))
                    output = dashboard_view(snapshot, _read(args.goal) if args.goal else None)
                finally:
                    owner.close()
        print(json.dumps(output, allow_nan=False, sort_keys=True, indent=2))
        return 0
    except (Rejected, OSError, ValueError) as exc:
        # Do not echo arbitrary input, file contents, private paths or OS error text.
        print(json.dumps({'error': str(exc) if isinstance(exc, Rejected) else 'offline_input_unavailable'}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
