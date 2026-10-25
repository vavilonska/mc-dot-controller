"""One explicit stage action, never an automatic route or replacement-ID loop."""
import argparse
import getpass
import json
import os
from .controller import Controller
from .legacy import PROFILE,Refused
from .transport import HttpTransport
from .plan import load_plan


def main(argv=None):
    p=argparse.ArgumentParser(description='Finite reviewed navigation stage; original shared ledger required')
    p.add_argument('--ledger',required=True);p.add_argument('--endpoint',required=True);p.add_argument('--token-env');p.add_argument('--plan');p.add_argument('--plan-sha256');p.add_argument('--timeout',type=float,default=2)
    sub=p.add_subparsers(dest='command',required=True);sub.add_parser('observe');sub.add_parser('report').add_argument('--id')
    for name in ('status','stop'):sub.add_parser(name).add_argument('--id',required=True)
    for name in ('move','look'):
        a=sub.add_parser(name);a.add_argument('--id',required=True);a.add_argument('--stage',required=True);a.add_argument('--samples',type=int,default=1);a.add_argument('--ttl-ms',type=int,default=1000);a.add_argument('--accept-normal-gameplay-risk',action='store_true')
    args=p.parse_args(argv)
    try:
        effect=args.command in ('move','look')
        if effect and not args.accept_normal_gameplay_risk:raise Refused('explicit ordinary gameplay risk acknowledgment required')
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
                if plan is None:raise Refused('reviewed navigation PLAN required')
                stage=plan.stage(args.stage);old=c.ledger.data['actions'].get(args.id)
                if old is None:
                    obs=c.observe();req={k:obs[k] for k in ('session','world_generation','player_uuid','owner_generation','observation_id')}
                    req.update(schema_version=1,profile=PROFILE,owner_id=c.owner_id,id=args.id,kind=args.command,plan_version=2,plan_sha256=plan.sha256,stage_id=args.stage)
                else:req=dict(old['request'])
                if req['profile']!=PROFILE or req['kind']!=args.command or req['stage_id']!=args.stage:raise Refused('original ID profile/kind/stage mismatch')
                req['ttl_ms']=args.ttl_ms
                if args.command=='move':req.update(forward=stage['forward'],strafe=stage['strafe'],samples=args.samples,jump_first=stage['jump_first'])
                else:req.update(yaw=stage['yaw'],pitch=stage['pitch'])
                result=c.start(req)
                if old is None:result=c.finish_one_step(args.id)
            code=0
            if effect:
                t=result.get('terminal_native') or {}
                code=2 if result['state']!='CLOSED' else 3 if t.get('applied_calls',0)==0 else 0 if t.get('applied_calls')==t.get('requested_calls') and t.get('release_proven') and t.get('protocol_terminal') else 4
                result['navigation_assessment']='protocol_only_target_not_assessed' if code==0 else 'known_no_input' if code==3 else 'known_partial_not_arrival' if code==4 else 'unknown_or_unsettled_no_reissue'
            print(json.dumps(result,allow_nan=False,sort_keys=True));return code
    except (Refused,OSError,KeyError,TypeError,ValueError):
        print('Refused or uncertain. Keep original owner/ledger/ID; use report/status/stop, never effect replay.',file=__import__('sys').stderr);return 2

if __name__=='__main__':raise SystemExit(main())
