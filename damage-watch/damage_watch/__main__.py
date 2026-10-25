"""One read-only diagnostic window. Operator separately arms UI-close fallback."""
import argparse
import getpass
import json
import os
import sys
from .strict import Invalid
from .transport import HttpTransport
from .watcher import watch


def main(argv=None):
    p=argparse.ArgumentParser(description='Read-only diagnostic GET capture; no game control')
    p.add_argument('--endpoint',required=True);p.add_argument('--outdir',required=True)
    for axis in ('x','y','z'):p.add_argument('--expected-'+axis,type=float,required=True)
    p.add_argument('--expected-owner',required=True);p.add_argument('--expected-player',required=True)
    p.add_argument('--expected-next-generation',type=int,required=True);p.add_argument('--expected-entry-count',type=int,required=True)
    p.add_argument('--token-env',help='explicit existing token environment variable NAME; otherwise hidden prompt')
    p.add_argument('--startup-seconds',type=float,default=60);p.add_argument('--world-seconds',type=float,default=12);p.add_argument('--interval-seconds',type=float,default=.2)
    a=p.parse_args(argv)
    try:
        token=os.environ.get(a.token_env,'') if a.token_env else getpass.getpass('Existing native token (hidden): ')
        transport=HttpTransport(a.endpoint,token)
        result=watch(transport,a.outdir,expected_pose=dict(x=a.expected_x,y=a.expected_y,z=a.expected_z),expected_owner=a.expected_owner,expected_player=a.expected_player,expected_next_generation=a.expected_next_generation,expected_entry_count=a.expected_entry_count,startup_s=a.startup_seconds,world_s=a.world_seconds,interval_s=a.interval_seconds)
        print(json.dumps(result,allow_nan=False,sort_keys=True));return 0 if result['reason'] in ('damage_detected','health_below20','window_not_reproduced','native_window_closed_not_reproduced','startup_not_in_world') else 2
    except (Invalid,OSError,ValueError,TypeError,KeyboardInterrupt):
        print('Capture unavailable or interrupted. close_required=true; use the prearmed external normal-close fallback. No further GET or game action was issued.',file=sys.stderr)
        return 2

if __name__=='__main__':raise SystemExit(main())
