"""Exactly one supplied maintenance request; no planner, automatic target or retry loop."""
import argparse
import getpass
import json
import os
from pathlib import Path
from .controller import Controller
from .legacy import Refused,strict_json,PROFILE
from .transport import HttpTransport
from .plan import load_plan

def main(argv=None):
    p=argparse.ArgumentParser(description='Finite exact maintenance request with original shared history')
    p.add_argument('--ledger',required=True);p.add_argument('--endpoint',required=True);p.add_argument('--token-env');p.add_argument('--plan');p.add_argument('--plan-sha256');p.add_argument('--timeout',type=float,default=2)
    sub=p.add_subparsers(dest='command',required=True);sub.add_parser('observe');sub.add_parser('report').add_argument('--id')
    for name in ('status','stop'):sub.add_parser(name).add_argument('--id',required=True)
    a=sub.add_parser('start');a.add_argument('--request',required=True);a.add_argument('--accept-normal-gameplay-risk',action='store_true')
    args=p.parse_args(argv)
    try:
        if bool(args.plan)!=bool(args.plan_sha256):raise Refused('PLAN file and hash must be paired')
        plan=load_plan(args.plan,args.plan_sha256) if args.plan else None
        if args.command=='report':
            class Offline:
                endpoint=args.endpoint.rstrip('/')
                def request(self,*_):raise Refused('report is local only')
            transport=Offline()
        else:transport=HttpTransport(args.endpoint,os.environ.get(args.token_env,'') if args.token_env else getpass.getpass('Existing native token (hidden): '),args.timeout)
        with Controller(args.ledger,transport,plan) as c:
            if args.command=='report':result=c.report(args.id)
            elif args.command=='observe':result=c.observe()
            elif args.command=='status':result=c.status(args.id)
            elif args.command=='stop':result=c.stop(args.id)
            else:
                if not args.accept_normal_gameplay_risk or plan is None:raise Refused('reviewed PLAN and explicit ordinary risk acknowledgment required')
                with open(args.request,'rb') as stream:raw=stream.read(16385)
                if len(raw)>16384:raise Refused('bounded request file required')
                req=strict_json(raw);c.validate_request(req)
                if req['profile']!=PROFILE:raise Refused('new effects require v5')
                old=c.ledger.data['actions'].get(req['id'])
                if old is None:
                    # Caller supplies finite action, not an old observation lease. Fresh identity only;
                    # every effect parameter and PLAN/hash/stage remain caller-pinned and checked.
                    obs=c.observe()
                    if any(req[k]!=obs[k] for k in ('session','world_generation','player_uuid')):raise Refused('request must retain its reviewed native context')
                    for k in ('owner_generation','observation_id'):req[k]=obs[k]
                result=c.start(req)
                if old is None:result=c.finish_one_step(req['id'])
            print(json.dumps(result,allow_nan=False,sort_keys=True))
            return 2 if args.command=='start' and (result['state']!='CLOSED' or not result.get('terminal_native',{}).get('applied_calls')) else 0
    except (Refused,OSError,KeyError,TypeError,ValueError):
        print('Refused or uncertain; retain original owner/ledger/ID. Never replay an effect.',file=__import__('sys').stderr);return 2
if __name__=='__main__':raise SystemExit(main())
