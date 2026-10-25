"""Explicit one-intent CLI. Never a batch, planner, owner initializer or replay loop."""
import argparse
import getpass
import json
import os
from .controller import Controller
from .journal import NEW_PROFILE
from .legacy import Refused
from .transport import HttpTransport


def assess(record):
    if record['state']!='CLOSED':return 2,'unknown_or_unsettled_no_reissue'
    receipt=record.get('terminal_native') or {}
    if record['request']['profile']!=NEW_PROFILE:return 0,'historical_legacy_record_only'
    count=receipt.get('applied_calls',0)
    if count==0:return 3,'known_no_call_not_gameplay_success'
    if record['request']['kind']=='break_block':
        return (0,'known_target_changed_not_server_confirmed') if receipt.get('gameplay_outcome')=='target_changed' else (4,'known_break_attempt_target_not_confirmed_changed')
    if count==receipt.get('requested_calls') and receipt.get('protocol_terminal') and receipt.get('release_proven'):return 0,'known_finite_call_completion_gameplay_not_verified'
    return 4,'known_partial_or_interrupted_calls'


def main(argv=None):
    p=argparse.ArgumentParser(description='Task-specific finite recovery interaction; original ledger required')
    p.add_argument('--ledger',required=True);p.add_argument('--endpoint',required=True)
    p.add_argument('--token-env',help='explicit existing token variable name; otherwise hidden prompt')
    p.add_argument('--timeout',type=float,default=2)
    sub=p.add_subparsers(dest='command',required=True)
    sub.add_parser('observe');sub.add_parser('report').add_argument('--id')
    for name in ('status','stop'):sub.add_parser(name).add_argument('--id',required=True)
    for kind in ('move','look','select_hotbar','break_block'):
        a=sub.add_parser(kind);a.add_argument('--id',required=True);a.add_argument('--ttl-ms',type=int,default=1000);a.add_argument('--accept-normal-gameplay-risk',action='store_true')
        if kind=='move':
            a.add_argument('--forward',type=float,default=.5);a.add_argument('--strafe',type=float,default=0);a.add_argument('--samples',type=int,default=1);a.add_argument('--jump-first',action='store_true')
        elif kind=='look':a.add_argument('--yaw',type=float,required=True);a.add_argument('--pitch',type=float,required=True)
        elif kind=='select_hotbar':a.add_argument('--slot',type=int,required=True)
        else:
            for key in ('x','y','z'):a.add_argument('--'+key,type=int,required=True)
            a.add_argument('--face',required=True);a.add_argument('--max-calls',type=int,default=32)
    args=p.parse_args(argv)
    try:
        effect=args.command in ('move','look','select_hotbar','break_block')
        if effect and not args.accept_normal_gameplay_risk:raise Refused('explicit normal gameplay risk acknowledgment required')
        if args.command=='report':
            class Offline:
                endpoint=args.endpoint.rstrip('/')
                def request(self,*_):raise Refused('report is local only')
            transport=Offline()
        else:transport=HttpTransport(args.endpoint,os.environ.get(args.token_env,'') if args.token_env else getpass.getpass('Existing native token (hidden): '),args.timeout)
        with Controller(args.ledger,transport) as c:
            if args.command=='report':result=c.report(args.id)
            elif args.command=='observe':result=c.observe()
            elif args.command=='status':result=c.status(args.id)
            elif args.command=='stop':result=c.stop(args.id)
            else:
                old=c.ledger.data['actions'].get(args.id)
                if old is not None:
                    req=dict(old['request'])
                    if req.get('kind')!=args.command:raise Refused('shared ID kind mismatch')
                else:
                    obs=c.observe();req={k:obs[k] for k in ('session','world_generation','player_uuid','owner_generation','observation_id')}
                    req.update(schema_version=1,profile=NEW_PROFILE,id=args.id,owner_id=c.owner_id,kind=args.command)
                req['ttl_ms']=args.ttl_ms
                if args.command=='move':req.update(forward=args.forward,strafe=args.strafe,samples=args.samples,jump_first=args.jump_first)
                elif args.command=='look':req.update(yaw=args.yaw,pitch=args.pitch)
                elif args.command=='select_hotbar':
                    req['slot']=args.slot
                    if old is None:req['stack_fingerprint']=next(s for s in obs['hotbar'] if s['slot']==args.slot)['stack_fingerprint']
                else:
                    req.update(x=args.x,y=args.y,z=args.z,face=args.face,block_id='minecraft:cobblestone',max_calls=args.max_calls)
                    if old is None:req['stack_fingerprint']=next(s for s in obs['hotbar'] if s['slot']==obs['selected_slot'])['stack_fingerprint']
                result=c.start(req)
                if old is None:result=c.finish_one_step(args.id)
            code=0
            if effect:code,result['interaction_assessment']=assess(result)
            print(json.dumps(result,allow_nan=False,sort_keys=True))
            return code
    except (Refused,OSError,KeyError,TypeError,ValueError,StopIteration):
        print('Refused or uncertain; preserve original ledger/IDs. Use original-ID report/status/stop, not effect replay.',file=__import__('sys').stderr);return 2

if __name__=='__main__':raise SystemExit(main())
