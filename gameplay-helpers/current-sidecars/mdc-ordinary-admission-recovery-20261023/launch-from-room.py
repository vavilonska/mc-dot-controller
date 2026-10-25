#!/usr/bin/env python3
"""Explicit operator invocation only; fresh bind from the known room, then one roundtrip."""
import argparse,datetime,importlib.util,json,sys,uuid
from pathlib import Path
B=Path('/workspace/scratch/5f333e5a575b')
H=Path(__file__).resolve().parent
N=B/'MDC-RECOVERY-LIVE-F1220-20261022'
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--arm',action='store_true',required=True);p.add_argument('--plan',type=Path,required=True);args=p.parse_args()
    sys.path.insert(0,str(H));sp=importlib.util.spec_from_file_location('trip',H/'exposure-roundtrip.py');trip=importlib.util.module_from_spec(sp);sp.loader.exec_module(trip)
    session=N/('exposure-room-work-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+str(uuid.uuid4())[:8])
    session.mkdir(mode=0o700);binding=session/'binding';binding.mkdir(mode=0o700);run=session/'run'
    c=trip.Client(binding)
    try:
        plan=json.loads(args.plan.read_text());s=c.state()
        ctx=trip.idle.context(s)
        if not trip.fresh_released(s,ctx) or s['world'].get('dimension')!='minecraft:the_nether' or trip.idle.distance(s['player'],plan['start_anchor'])>.8:
            raise trip.idle.Refused('must_already_be_at_actual_room_neutral_alive_nether_no_active')
        plan['retreat']['arm']=True;plan['retreat']['expected_context']=ctx
        (session/'FRESH-BINDING.json').write_text(json.dumps(dict(context=ctx,pose=trip.idle.point(s['player']),health=trip.idle.health(s),neutral=True),indent=2)+'\n')
        planpath=session/'PLAN.json';planpath.write_text(json.dumps(plan,indent=2)+'\n')
    except Exception as e:
        result=dict(phase='REFUSED_NO_INPUT',reason=type(e).__name__+':'+str(e));(session/'RESULT.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result),flush=True);return 2
    pointer=N/'ordinary-exposure-current-run.txt';tmp=pointer.with_suffix('.tmp');tmp.write_text(str(run)+'\n');tmp.replace(pointer)
    print('EXPOSURE_RUN='+str(run),flush=True)
    sys.argv=[str(H/'exposure-roundtrip.py'),'--plan',str(planpath),'--run-dir',str(run)]
    return trip.main()
if __name__=='__main__':raise SystemExit(main())
