"""No implicit service start, credential discovery, gameplay retry, or reset."""
import argparse
import getpass
import json
import os
from .controller import Controller, PROFILE
from .storage import Refused
from .transport import HttpTransport


def assess_step(result):
    native=result.get('terminal_native') or result.get('latest_native') or {}
    if result.get('state') != 'CLOSED': return 2, 'unknown_or_unsettled_no_reissue'
    if native.get('applied_samples') == 0: return 3, 'known_no_input_not_a_successful_step'
    if (native.get('applied_samples') == native.get('requested_samples') and native.get('reason') == 'samples_complete'
            and native.get('release_proven') is True and native.get('protocol_terminal') is True):
        return 0, 'finite_input_complete_displacement_and_gameplay_not_verified'
    return 4, 'known_partial_or_interrupted_input_not_a_successful_step'


def main(argv=None):
    p = argparse.ArgumentParser(description='Explicit short-input recovery prototype; ordinary gameplay damage/death risk accepted.')
    p.add_argument('--ledger', required=True, help='original private persistent ledger directory; never replace to bypass UNKNOWN')
    p.add_argument('--endpoint', required=True, help='explicit HTTP loopback IP and port')
    p.add_argument('--token-env', help='name of explicitly selected existing token environment variable; otherwise hidden prompt')
    p.add_argument('--timeout', type=float, default=2)
    sub=p.add_subparsers(dest='command',required=True)
    sub.add_parser('observe')
    sub.add_parser('report').add_argument('--id')
    for name in ('status','stop'):
        sub.add_parser(name).add_argument('--id',required=True)
    step=sub.add_parser('step')
    step.add_argument('--id',required=True,help='canonical caller UUID; retain forever')
    step.add_argument('--forward',type=float,default=.5)
    step.add_argument('--strafe',type=float,default=0)
    step.add_argument('--samples',type=int,default=1)
    step.add_argument('--accept-normal-gameplay-risk',action='store_true')
    args=p.parse_args(argv)
    try:
        if args.command=='step' and not args.accept_normal_gameplay_risk: raise Refused('explicit normal-gameplay-risk acknowledgment required')
        if args.command == 'report':
            class OfflineTransport:
                endpoint=args.endpoint.rstrip('/')
                def request(self,*_): raise Refused('report is local only')
            transport=OfflineTransport()
        else:
            token=os.environ.get(args.token_env,'') if args.token_env else getpass.getpass('Existing native token (hidden): ')
            transport=HttpTransport(args.endpoint,token,args.timeout)
        with Controller(args.ledger,transport) as c:
            if args.command=='report': result=c.report(args.id)
            elif args.command=='observe': result=c.observe()
            elif args.command=='status': result=c.status(args.id)
            elif args.command=='stop': result=c.stop(args.id)
            else:
                existing=c.ledger.data['actions'].get(args.id)
                if existing is not None:
                    req=dict(existing['request'])
                    req.update(forward=args.forward,strafe=args.strafe,samples=args.samples)
                    result=c.start(req) # SameID returns original only; no auto status/stop replay.
                else:
                    obs=c.observe()
                    req={k:obs[k] for k in ('session','world_generation','player_uuid','owner_generation','observation_id')}
                    req.update(schema_version=1,profile=PROFILE,id=args.id,owner_id=c.owner_id,forward=args.forward,strafe=args.strafe,samples=args.samples,jump_first=False,ttl_ms=1000)
                    c.start(req)
                    # Let native finite ticks settle naturally; stop only on unresolved release.
                    result=c.finish_one_step(args.id)
            exit_code=0
            if args.command == 'step':
                exit_code, assessment = assess_step(result)
                result['step_assessment']=assessment
            print(json.dumps(result,allow_nan=False,sort_keys=True))
        return exit_code
    except (Refused,OSError,KeyError,TypeError,ValueError):
        # No exception repr, token, raw response, or credential-bearing argv in errors.
        print('Refused or uncertain; preserve the original ledger and use original-ID report/status/stop only.',file=__import__('sys').stderr)
        return 2

if __name__=='__main__': raise SystemExit(main())
